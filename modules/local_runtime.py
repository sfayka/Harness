"""Local app runtime CLI and process contract for Harness."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from modules.local_secrets import (
    create_secret_store,
    LocalSecretError,
    SecretStatus,
    collect_secret_statuses,
    load_runtime_managed_secrets_into_environment,
    secret_status_payload,
)
from modules.local_setup import (
    LocalSetupError,
    available_workflow_ids,
    build_guided_setup_status,
)
from modules.store import SQLiteHarnessStore, StoreError


APP_NAME = "Harness"
CONFIG_SCHEMA_VERSION = 1
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8765
DEFAULT_REQUEST_TIMEOUT_SECONDS = 2.0

EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_SETUP_REQUIRED = 2
EXIT_RUNTIME_ERROR = 3

ENV_RUNTIME_MODE = "HARNESS_RUNTIME_MODE"
ENV_RUNTIME_CONFIG_PATH = "HARNESS_RUNTIME_CONFIG_PATH"
ENV_RUNTIME_DATA_DIR = "HARNESS_RUNTIME_DATA_DIR"
ENV_RUNTIME_LOG_PATH = "HARNESS_RUNTIME_LOG_PATH"
ENV_RUNTIME_HOST = "HARNESS_RUNTIME_HOST"
ENV_RUNTIME_PORT = "HARNESS_RUNTIME_PORT"
ENV_RUNTIME_BASE_URL = "HARNESS_RUNTIME_BASE_URL"
ENV_RUNTIME_EXECUTABLE = "HARNESS_RUNTIME_EXECUTABLE"
ENV_DASHBOARD_ASSETS_DIR = "HARNESS_DASHBOARD_ASSETS_DIR"
ENV_PROOFLINE_DASHBOARD_ASSETS_DIR = "PROOFLINE_DASHBOARD_ASSETS_DIR"
ENV_SECRET_PROVIDER = "HARNESS_SECRET_PROVIDER"
ENV_NOTIFICATION_PERMISSION = "HARNESS_NOTIFICATION_PERMISSION"
ENV_LAUNCH_AT_LOGIN = "HARNESS_LAUNCH_AT_LOGIN"
ENV_WORKSPACE_FOLDERS = "HARNESS_WORKSPACE_FOLDERS"
ENV_SYMPHONY_BIN = "HARNESS_SYMPHONY_BIN"


class LocalRuntimeError(ValueError):
    """Operator-readable local runtime failure."""

    def __init__(self, message: str, *, exit_code: int = EXIT_RUNTIME_ERROR) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path
    log_dir: Path
    runtime_dir: Path
    config_path: Path
    database_path: Path
    dashboard_assets_dir: Path
    pid_path: Path
    log_path: Path


@dataclass(frozen=True)
class RuntimeConfig:
    schema_version: int
    host: str
    port: int
    database_path: Path
    dashboard_assets_dir: Path
    data_dir: Path
    log_dir: Path
    runtime_dir: Path
    pid_path: Path
    log_path: Path

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def asdict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "api": {
                "host": self.host,
                "port": self.port,
                "base_url": self.base_url,
            },
            "storage": {
                "backend": "sqlite",
                "sqlite_path": str(self.database_path),
            },
            "paths": {
                "data_dir": str(self.data_dir),
                "dashboard_assets_dir": str(self.dashboard_assets_dir),
                "log_dir": str(self.log_dir),
                "runtime_dir": str(self.runtime_dir),
                "pid_path": str(self.pid_path),
                "log_path": str(self.log_path),
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, paths: RuntimePaths) -> "RuntimeConfig":
        api = payload.get("api") if isinstance(payload.get("api"), dict) else {}
        storage = payload.get("storage") if isinstance(payload.get("storage"), dict) else {}
        stored_paths = payload.get("paths") if isinstance(payload.get("paths"), dict) else {}
        try:
            schema_version = int(payload.get("schema_version") or CONFIG_SCHEMA_VERSION)
        except (TypeError, ValueError) as error:
            raise LocalRuntimeError(
                "Harness runtime config has an invalid schema_version.",
                exit_code=EXIT_SETUP_REQUIRED,
            ) from error
        if schema_version != CONFIG_SCHEMA_VERSION:
            raise LocalRuntimeError(
                f"Unsupported Harness runtime config schema_version={schema_version}. "
                f"Expected {CONFIG_SCHEMA_VERSION}.",
                exit_code=EXIT_SETUP_REQUIRED,
            )

        host = str(api.get("host") or DEFAULT_API_HOST)
        try:
            port = int(api.get("port") or DEFAULT_API_PORT)
        except (TypeError, ValueError) as error:
            raise LocalRuntimeError(
                "Harness runtime config has an invalid api.port.",
                exit_code=EXIT_SETUP_REQUIRED,
            ) from error
        database_path = Path(str(storage.get("sqlite_path") or paths.database_path)).expanduser()
        data_dir = Path(str(stored_paths.get("data_dir") or paths.data_dir)).expanduser()
        dashboard_assets_dir = Path(
            str(stored_paths.get("dashboard_assets_dir") or paths.dashboard_assets_dir)
        ).expanduser()
        log_dir = Path(str(stored_paths.get("log_dir") or paths.log_dir)).expanduser()
        runtime_dir = Path(str(stored_paths.get("runtime_dir") or paths.runtime_dir)).expanduser()
        pid_path = Path(str(stored_paths.get("pid_path") or paths.pid_path)).expanduser()
        log_path = Path(str(stored_paths.get("log_path") or paths.log_path)).expanduser()
        return cls(
            schema_version=schema_version,
            host=host,
            port=port,
            database_path=database_path,
            dashboard_assets_dir=dashboard_assets_dir,
            data_dir=data_dir,
            log_dir=log_dir,
            runtime_dir=runtime_dir,
            pid_path=pid_path,
            log_path=log_path,
        )


@dataclass(frozen=True)
class RuntimeCheck:
    code: str
    status: str
    message: str
    impact: str
    next_action: str
    details: dict[str, Any] | None = None


def resolve_runtime_paths(
    *,
    data_dir: str | Path | None = None,
    log_dir: str | Path | None = None,
    platform_name: str | None = None,
    home: str | Path | None = None,
) -> RuntimePaths:
    """Resolve managed local runtime paths."""

    current_platform = platform_name or sys.platform
    home_path = Path(home).expanduser() if home is not None else Path.home()

    resolved_data_dir = Path(
        data_dir or os.environ.get("HARNESS_APP_DATA_DIR") or _default_data_dir(current_platform, home_path)
    ).expanduser()
    resolved_log_dir = Path(
        log_dir or os.environ.get("HARNESS_APP_LOG_DIR") or _default_log_dir(current_platform, home_path)
    ).expanduser()
    runtime_dir = resolved_data_dir / "runtime"
    return RuntimePaths(
        data_dir=resolved_data_dir,
        log_dir=resolved_log_dir,
        runtime_dir=runtime_dir,
        config_path=resolved_data_dir / "config.json",
        database_path=resolved_data_dir / "harness.db",
        dashboard_assets_dir=resolved_data_dir / "dashboard",
        pid_path=runtime_dir / "harness.pid",
        log_path=resolved_log_dir / "harness.log",
    )


def _default_data_dir(platform_name: str, home_path: Path) -> Path:
    if platform_name == "darwin":
        return home_path / "Library" / "Application Support" / APP_NAME
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "harness"
    return home_path / ".local" / "share" / "harness"


def _default_log_dir(platform_name: str, home_path: Path) -> Path:
    if platform_name == "darwin":
        return home_path / "Library" / "Logs" / APP_NAME
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "harness" / "logs"
    return home_path / ".local" / "state" / "harness" / "logs"


def create_default_config(
    paths: RuntimePaths,
    *,
    host: str = DEFAULT_API_HOST,
    port: int = DEFAULT_API_PORT,
) -> RuntimeConfig:
    return RuntimeConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        host=host,
        port=port,
        database_path=paths.database_path,
        dashboard_assets_dir=paths.dashboard_assets_dir,
        data_dir=paths.data_dir,
        log_dir=paths.log_dir,
        runtime_dir=paths.runtime_dir,
        pid_path=paths.pid_path,
        log_path=paths.log_path,
    )


def load_runtime_config(paths: RuntimePaths) -> RuntimeConfig:
    if not paths.config_path.exists():
        raise LocalRuntimeError(
            f"Harness local runtime is not initialized at {paths.config_path}. Run `harness init` first.",
            exit_code=EXIT_SETUP_REQUIRED,
        )
    try:
        payload = json.loads(paths.config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LocalRuntimeError(
            f"Harness runtime config at {paths.config_path} could not be read: {error}",
            exit_code=EXIT_SETUP_REQUIRED,
        ) from error
    if not isinstance(payload, dict):
        raise LocalRuntimeError(
            f"Harness runtime config at {paths.config_path} must contain a JSON object.",
            exit_code=EXIT_SETUP_REQUIRED,
        )
    return RuntimeConfig.from_dict(payload, paths=paths)


def init_runtime(
    paths: RuntimePaths,
    *,
    host: str = DEFAULT_API_HOST,
    port: int = DEFAULT_API_PORT,
    force: bool = False,
) -> tuple[RuntimeConfig, bool]:
    """Create runtime-managed directories, config, log file, and SQLite schema."""

    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.log_dir.mkdir(parents=True, exist_ok=True)
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)

    created = False
    if paths.config_path.exists() and not force:
        config = load_runtime_config(paths)
    else:
        config = create_default_config(paths, host=host, port=port)
        paths.config_path.write_text(
            json.dumps(config.asdict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        created = True

    try:
        SQLiteHarnessStore(config.database_path)
    except StoreError as error:
        raise LocalRuntimeError(str(error), exit_code=EXIT_SETUP_REQUIRED) from error
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    config.log_path.touch(exist_ok=True)
    return config, created


def apply_runtime_environment(config: RuntimeConfig, *, config_path: Path) -> None:
    """Apply runtime-managed environment for backend startup."""

    secret_store = create_secret_store()
    os.environ["PROOFLINE_STORE_BACKEND"] = "sqlite"
    os.environ["PROOFLINE_SQLITE_PATH"] = str(config.database_path)
    os.environ["HARNESS_STORE_BACKEND"] = "sqlite"
    os.environ["HARNESS_SQLITE_PATH"] = str(config.database_path)
    os.environ[ENV_RUNTIME_MODE] = "local-app"
    os.environ[ENV_RUNTIME_CONFIG_PATH] = str(config_path)
    os.environ[ENV_RUNTIME_DATA_DIR] = str(config.data_dir)
    os.environ[ENV_RUNTIME_LOG_PATH] = str(config.log_path)
    os.environ[ENV_RUNTIME_HOST] = config.host
    os.environ[ENV_RUNTIME_PORT] = str(config.port)
    os.environ[ENV_RUNTIME_BASE_URL] = config.base_url
    os.environ.setdefault(ENV_PROOFLINE_DASHBOARD_ASSETS_DIR, str(config.dashboard_assets_dir))
    os.environ.setdefault(ENV_DASHBOARD_ASSETS_DIR, str(config.dashboard_assets_dir))
    load_runtime_managed_secrets_into_environment(store=secret_store)
    os.environ.setdefault(
        ENV_SECRET_PROVIDER,
        str(getattr(secret_store, "provider_name", "runtime-managed-secret-store")),
    )


def fetch_runtime_health(
    config: RuntimeConfig,
    *,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> tuple[int | None, dict[str, Any] | None, str | None]:
    request = Request(f"{config.base_url}/health", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return int(response.status), payload if isinstance(payload, dict) else None, None
    except HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        return int(error.code), payload if isinstance(payload, dict) else None, str(error)
    except (OSError, TimeoutError, URLError) as error:
        return None, None, str(error)


def fetch_http_status(
    url: str,
    *,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    accept: str = "text/html,application/json",
) -> tuple[int | None, str | None]:
    request = Request(url, headers={"Accept": accept})
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), None
    except HTTPError as error:
        return int(error.code), str(error)
    except (OSError, TimeoutError, URLError) as error:
        return None, str(error)


def read_pid(pid_path: Path) -> int | None:
    try:
        raw_pid = pid_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw_pid:
        return None
    try:
        return int(raw_pid)
    except ValueError:
        return None


def process_is_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def runtime_is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def runtime_subprocess_command(
    paths: RuntimePaths,
    *,
    host: str | None = None,
    port: int | None = None,
) -> list[str]:
    runtime_executable = _clean_env_value(ENV_RUNTIME_EXECUTABLE)
    if runtime_executable:
        command = [runtime_executable]
    elif runtime_is_frozen():
        command = [sys.executable]
    else:
        command = [sys.executable, "-m", "modules.local_runtime"]
    command.extend(["--data-dir", str(paths.data_dir), "--log-dir", str(paths.log_dir), "serve"])
    if host:
        command.extend(["--host", host])
    if port:
        command.extend(["--port", str(port)])
    return command


def runtime_status(
    config: RuntimeConfig,
    *,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> tuple[int, dict[str, Any]]:
    pid = read_pid(config.pid_path)
    process_running = process_is_running(pid)
    http_status, health, error = fetch_runtime_health(config, timeout=timeout)
    healthy = http_status == 200 and bool(health and health.get("status") == "ok")
    status = "running" if healthy else "degraded" if http_status is not None else "stopped"
    exit_code = EXIT_OK if healthy else EXIT_UNHEALTHY
    return exit_code, {
        "status": status,
        "api_base_url": config.base_url,
        "pid": pid,
        "process_running": process_running,
        "health_http_status": http_status,
        "health": health,
        "error": None if healthy else error,
        "paths": _paths_payload(config),
    }


def start_runtime(
    paths: RuntimePaths,
    *,
    host: str | None = None,
    port: int | None = None,
    timeout_seconds: float = 10.0,
    force_restart: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Start the local runtime as a runtime-managed background process."""

    config, _ = init_runtime(paths, host=host or DEFAULT_API_HOST, port=port or DEFAULT_API_PORT)
    if host or port:
        config = RuntimeConfig.from_dict(
            {**config.asdict(), "api": {"host": host or config.host, "port": port or config.port}},
            paths=paths,
        )

    _, status_payload = runtime_status(config)
    if status_payload["status"] == "running" and not force_restart:
        return EXIT_OK, {
            "status": "running",
            "message": "Harness runtime is already running.",
            "api_base_url": config.base_url,
            "pid": status_payload.get("pid"),
            "recovered": False,
            "paths": _paths_payload(config),
        }

    recovered = False
    if status_payload.get("pid") and status_payload.get("process_running"):
        stop_exit_code, stop_payload = stop_runtime(config, timeout_seconds=min(timeout_seconds, 10.0))
        if stop_exit_code != EXIT_OK:
            stop_payload["next_action"] = (
                "Quit the stuck Harness process from Activity Monitor, then choose Recover Runtime again."
            )
            return stop_exit_code, stop_payload
        recovered = True
    elif status_payload.get("pid"):
        with contextlib.suppress(OSError):
            config.pid_path.unlink()
        recovered = True

    available, port_error = _port_available(config.host, config.port)
    if not available:
        return EXIT_RUNTIME_ERROR, {
            "status": "port_conflict",
            "message": f"Harness cannot start because {config.host}:{config.port} is already in use.",
            "error": port_error,
            "next_action": (
                "Stop the process using that port, then choose Recover Runtime. "
                "If another app owns the port permanently, reinitialize Harness with a different local port."
            ),
            "api_base_url": config.base_url,
            "paths": _paths_payload(config),
        }

    command = runtime_subprocess_command(paths, host=host, port=port)

    try:
        process = subprocess.Popen(
            command,
            cwd=Path.cwd(),
            start_new_session=True,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise LocalRuntimeError(
            f"Harness runtime could not be started: {error}",
            exit_code=EXIT_RUNTIME_ERROR,
        ) from error

    healthy = _wait_for_runtime_health(config, timeout_seconds=timeout_seconds)
    if healthy:
        return EXIT_OK, {
            "status": "running",
            "message": "Harness runtime started.",
            "api_base_url": config.base_url,
            "pid": read_pid(config.pid_path) or process.pid,
            "recovered": recovered,
            "paths": _paths_payload(config),
        }

    if process.poll() is not None:
        message = "Harness runtime exited before it became healthy."
    else:
        message = f"Harness runtime did not become healthy within {timeout_seconds:g} seconds."
    return EXIT_RUNTIME_ERROR, {
        "status": "start_failed",
        "message": message,
        "pid": read_pid(config.pid_path) or process.pid,
        "next_action": "Open Harness logs, fix the reported startup problem, then choose Recover Runtime.",
        "paths": _paths_payload(config),
    }


def recover_runtime(
    paths: RuntimePaths,
    *,
    timeout_seconds: float = 10.0,
) -> tuple[int, dict[str, Any]]:
    """Recover the runtime-managed process after stale PID, crash, or degraded health."""

    return start_runtime(paths, timeout_seconds=timeout_seconds, force_restart=True)


def uninitialized_status(paths: RuntimePaths) -> dict[str, Any]:
    return {
        "status": "uninitialized",
        "error": f"Harness local runtime is not initialized at {paths.config_path}.",
        "next_action": "Run `harness init`.",
        "paths": {
            "data_dir": str(paths.data_dir),
            "log_dir": str(paths.log_dir),
            "config_path": str(paths.config_path),
        },
    }


def run_doctor(paths: RuntimePaths) -> tuple[int, dict[str, Any]]:
    checks: list[RuntimeCheck] = []
    config: RuntimeConfig | None = None
    status_payload: dict[str, Any] | None = None

    checks.append(
        _check_writable_directory(
            "app_data_dir",
            paths.data_dir,
            "Harness needs a writable app data directory.",
        )
    )
    checks.append(_check_writable_directory("log_dir", paths.log_dir, "Harness needs a writable log directory."))

    try:
        config = load_runtime_config(paths)
    except LocalRuntimeError as error:
        checks.append(
            RuntimeCheck(
                code="config",
                status="fail",
                message=str(error),
                impact="Harness cannot start reliably until local runtime config exists and is readable.",
                next_action="Run `harness init` from the CLI.",
            )
        )
    else:
        checks.append(
            RuntimeCheck(
                code="config",
                status="pass",
                message=f"Runtime config exists at {paths.config_path}.",
                impact="Harness can read non-secret local runtime settings.",
                next_action="No action needed.",
            )
        )

    if config is not None:
        try:
            store = SQLiteHarnessStore(config.database_path)
            sqlite_ready = store.schema_ready()
        except StoreError as error:
            checks.append(
                RuntimeCheck(
                    code="sqlite",
                    status="fail",
                    message=str(error),
                    impact="Harness cannot persist canonical task truth or reset verifier state.",
                    next_action=(
                        "Move the damaged database aside and rerun setup, "
                        "or restore a known-good backup."
                    ),
                )
            )
        else:
            checks.append(
                RuntimeCheck(
                    code="sqlite",
                    status="pass" if sqlite_ready else "fail",
                    message=(
                        "SQLite database is "
                        f"{'ready' if sqlite_ready else 'not on the expected schema'} at {config.database_path}."
                    ),
                    impact=(
                        "Harness can persist local task and verifier state."
                        if sqlite_ready
                        else "Harness storage exists but is not on the expected schema."
                    ),
                    next_action=(
                        "No action needed."
                        if sqlite_ready
                        else "Restart Harness after rerunning `harness init`."
                    ),
                )
            )

        _, status_payload = runtime_status(config)
        api_running = status_payload["status"] == "running"
        checks.append(
            RuntimeCheck(
                code="api_health",
                status="pass" if api_running else "warn",
                message="Local API is healthy." if api_running else "Local API is not running.",
                impact=(
                    "The CLI and dashboard can read Harness state."
                    if api_running
                    else "Setup checks can still run, but live task status and the dashboard are unavailable."
                ),
                next_action=(
                    "No action needed."
                    if api_running
                    else "Run `harness start` or `harness serve`."
                ),
                details={
                    "api_base_url": config.base_url,
                    "health_http_status": status_payload.get("health_http_status"),
                },
            )
        )
        checks.append(_check_dashboard(config, status_payload=status_payload))
    else:
        checks.append(
            RuntimeCheck(
                code="sqlite",
                status="fail",
                message="SQLite database has not been initialized.",
                impact="Harness cannot store local task truth until setup creates the database.",
                next_action="Run `harness init` from the app bundle or CLI.",
            )
        )
        checks.append(
            RuntimeCheck(
                code="api_health",
                status="warn",
                message="Local API cannot be checked before runtime initialization.",
                impact="The app cannot report live task status until setup completes and the API starts.",
                next_action="Run `harness init`, then start Harness.",
            )
        )
        checks.append(
            RuntimeCheck(
                code="dashboard",
                status="warn",
                message="Dashboard assets cannot be checked before runtime initialization.",
                impact="The dashboard window may not open until setup completes.",
                next_action="Run `harness init`, then install packaged dashboard assets.",
            )
        )

    checks.extend(_secret_doctor_checks())
    checks.append(_check_execution_substrate())
    checks.append(_check_ingress_executor())
    checks.append(_check_notification_permission())
    checks.append(_check_launch_at_login())
    checks.append(_check_workspace_folders())

    exit_code = EXIT_RUNTIME_ERROR if any(check.status == "fail" for check in checks) else EXIT_OK
    counts = {
        "pass": sum(1 for check in checks if check.status == "pass"),
        "warn": sum(1 for check in checks if check.status == "warn"),
        "fail": sum(1 for check in checks if check.status == "fail"),
    }
    return exit_code, {
        "status": "fail" if exit_code else "ok",
        "summary": counts,
        "checks": [asdict(check) for check in checks],
    }


def _check_writable_directory(code: str, path: Path, impact: str) -> RuntimeCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".harness-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        return RuntimeCheck(
            code=code,
            status="fail",
            message=f"{impact} {path} is not writable: {error}",
            impact=impact,
            next_action="Choose a writable app data location or fix directory permissions.",
            details={"path": str(path)},
        )
    return RuntimeCheck(
        code=code,
        status="pass",
        message=f"{path} is writable.",
        impact=impact,
        next_action="No action needed.",
        details={"path": str(path)},
    )


def _check_dashboard(config: RuntimeConfig, *, status_payload: dict[str, Any]) -> RuntimeCheck:
    configured_assets_dir = (
        os.environ.get(ENV_PROOFLINE_DASHBOARD_ASSETS_DIR)
        or os.environ.get(ENV_DASHBOARD_ASSETS_DIR)
        or config.dashboard_assets_dir
    )
    assets_dir = Path(configured_assets_dir).expanduser()
    dashboard_url = f"{config.base_url}/dashboard/"
    assets_ready = (assets_dir / "index.html").is_file()
    api_running = status_payload.get("status") == "running"
    details: dict[str, Any] = {
        "assets_dir": str(assets_dir),
        "dashboard_url": dashboard_url,
        "assets_ready": assets_ready,
    }

    if not assets_ready:
        return RuntimeCheck(
            code="dashboard",
            status="warn",
            message=f"Dashboard assets are missing at {assets_dir}.",
            impact="The dashboard window cannot render until packaged assets are installed.",
            next_action="Build or install the packaged dashboard assets, then set PROOFLINE_DASHBOARD_ASSETS_DIR if they are not in the default app data path.",
            details=details,
        )

    if not api_running:
        return RuntimeCheck(
            code="dashboard",
            status="warn",
            message="Dashboard assets are present, but the local API is not running.",
            impact="The dashboard window can be opened after Harness starts.",
            next_action="Start Harness from the app or run `harness serve`.",
            details=details,
        )

    http_status, error = fetch_http_status(dashboard_url)
    details["http_status"] = http_status
    if http_status == 200:
        return RuntimeCheck(
            code="dashboard",
            status="pass",
            message="Dashboard is reachable from the local Harness runtime.",
            impact="The dashboard window can inspect live local Harness state.",
            next_action="No action needed.",
            details=details,
        )
    details["error"] = error
    return RuntimeCheck(
        code="dashboard",
        status="warn",
        message="Dashboard assets are present, but the dashboard route is not reachable.",
        impact="The dashboard window may fail to open or may show a backend error.",
        next_action="Restart Harness and rerun doctor. If the problem continues, reinstall the dashboard assets.",
        details=details,
    )


def _secret_doctor_checks() -> list[RuntimeCheck]:
    statuses = collect_secret_statuses(store=create_secret_store())
    checks: list[RuntimeCheck] = []
    for status in statuses:
        if status.name == "github_token":
            checks.append(_secret_status_to_check("github_connection", status))
        elif status.name == "linear_api_key":
            checks.append(_secret_status_to_check("linear_connection", status))
    return checks


def _secret_status_to_check(code: str, status: SecretStatus) -> RuntimeCheck:
    configured = status.status == "configured"
    required_for = status.required_for.rstrip(".")
    return RuntimeCheck(
        code=code,
        status="pass" if configured else "warn",
        message=(
            f"{status.label} is configured."
            if configured
            else f"{status.label} is not ready: {status.message}"
        ),
        impact=(
            status.required_for
            if configured
            else f"{required_for} will remain unavailable until this credential is connected."
        ),
        next_action=status.next_action,
        details={
            "secret": status.name,
            "env_var": status.env_var,
            "source": status.source,
            "credential_status": status.status,
        },
    )


def _symphony_binary_candidates() -> list[Path]:
    candidates: list[Path] = []
    for env_var in (ENV_SYMPHONY_BIN, "SYMPHONY_BIN"):
        configured = _clean_env_value(env_var)
        if configured:
            candidates.append(Path(configured).expanduser())

    path_binary = shutil.which("symphony")
    if path_binary:
        candidates.append(Path(path_binary))

    repo_root = Path(__file__).resolve().parents[1]
    candidates.append(repo_root.parent / "Infrastructure" / "symphony" / "elixir" / "bin" / "symphony")

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique_candidates.append(candidate)
            seen.add(key)
    return unique_candidates


def _check_execution_substrate() -> RuntimeCheck:
    candidates = _symphony_binary_candidates()
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return RuntimeCheck(
                code="execution_substrate",
                status="pass",
                message=f"Symphony execution substrate is installed at {candidate}.",
                impact=(
                    "Harness can include the Symphony-compatible runner in local dry runs and later "
                    "execution-substrate E2E tests."
                ),
                next_action="No action needed.",
                details={
                    "preferred_runner": "symphony",
                    "binary": str(candidate),
                    "checked_candidates": [str(path) for path in candidates],
                    "mode": "installed",
                    "live_dispatch_enabled": False,
                    "completion_authority": "harness_verification",
                    "runner_completion_is_truth": False,
                },
            )

    return RuntimeCheck(
        code="execution_substrate",
        status="warn",
        message="No Symphony-compatible execution substrate binary was found.",
        impact=(
            "Harness can still verify work, but new runner/scheduler E2E coverage is unavailable "
            "until Symphony or a compatible substrate is installed."
        ),
        next_action=(
            "Install/build Symphony and set HARNESS_SYMPHONY_BIN if the binary is not on PATH."
        ),
        details={
            "preferred_runner": "symphony",
            "checked_candidates": [str(path) for path in candidates],
            "mode": "unconfigured",
            "live_dispatch_enabled": False,
            "completion_authority": "harness_verification",
            "runner_completion_is_truth": False,
        },
    )


def _check_ingress_executor() -> RuntimeCheck:
    cli_config_path = _clean_env_value("OPENCLAW_CONFIG_PATH")
    state_dir = _clean_env_value("OPENCLAW_STATE_DIR")
    base_url = _clean_env_value("OPENCLAW_BASE_URL")
    cli_bin = _clean_env_value("OPENCLAW_BIN") or "openclaw"

    if cli_config_path or state_dir:
        details = {
            "mode": "local_cli",
            "config_path": cli_config_path,
            "state_dir": state_dir,
            "cli_bin": cli_bin,
        }
        if cli_config_path and not Path(cli_config_path).expanduser().is_file():
            return RuntimeCheck(
                code="ingress_executor",
                status="fail",
                message=f"Desktop-agent CLI config is configured but missing at {cli_config_path}.",
                impact="Harness repair dispatch cannot use the configured local desktop-agent bridge.",
                next_action="Fix OPENCLAW_CONFIG_PATH or rerun the desktop-agent setup flow.",
                details=details,
            )
        if shutil.which(cli_bin) is None:
            return RuntimeCheck(
                code="ingress_executor",
                status="warn",
                message=f"Desktop-agent CLI config is present, but `{cli_bin}` is not on PATH.",
                impact="Harness may not be able to dispatch repair work through the local bridge.",
                next_action="Install the configured desktop-agent CLI or set OPENCLAW_BIN to the executable path.",
                details=details,
            )
        return RuntimeCheck(
            code="ingress_executor",
            status="pass",
            message="Desktop-agent local CLI bridge is configured.",
            impact="Harness can request repair work through the configured local bridge when a workflow needs it.",
            next_action="No action needed.",
            details=details,
        )

    if base_url:
        return RuntimeCheck(
            code="ingress_executor",
            status="pass",
            message="Desktop-agent HTTP repair bridge is configured.",
            impact="Harness can request repair work through the configured HTTP bridge when a workflow needs it.",
            next_action="No action needed.",
            details={"mode": "http", "base_url": base_url},
        )

    return RuntimeCheck(
        code="ingress_executor",
        status="warn",
        message="No legacy desktop-agent ingress/executor bridge is configured.",
        impact=(
            "Legacy OpenClaw/Hermes repair dispatch is unavailable. New execution scheduling should use "
            "the Symphony-compatible execution substrate instead."
        ),
        next_action="Only configure this compatibility bridge if an older workflow still depends on it.",
        details={"mode": "unconfigured"},
    )


def _check_notification_permission() -> RuntimeCheck:
    permission = (_clean_env_value(ENV_NOTIFICATION_PERMISSION) or "unknown").lower()
    if permission in {"authorized", "granted", "enabled"}:
        return RuntimeCheck(
            code="notification_permission",
            status="pass",
            message="Notification permission is authorized.",
            impact="Harness can surface attention events through local notifications.",
            next_action="No action needed.",
            details={"permission": permission},
        )
    if permission in {"denied", "disabled"}:
        return RuntimeCheck(
            code="notification_permission",
            status="pass",
            message="Wrapper notification delivery is disabled.",
            impact="Harness can run normally through CLI/web surfaces without local notifications.",
            next_action="No action needed.",
            details={"permission": permission},
        )
    return RuntimeCheck(
        code="notification_permission",
        status="pass",
        message="No wrapper notification delivery is configured.",
        impact="Harness can run normally through CLI/web surfaces without local notifications.",
        next_action="No action needed.",
        details={"permission": permission},
    )


def _check_launch_at_login() -> RuntimeCheck:
    state = (_clean_env_value(ENV_LAUNCH_AT_LOGIN) or "unknown").lower()
    if state in {"enabled", "true", "1", "yes"}:
        return RuntimeCheck(
            code="launch_at_login",
            status="pass",
            message="Launch at Login is enabled.",
            impact="Harness can start automatically after login.",
            next_action="No action needed.",
            details={"state": state},
        )
    if state in {"disabled", "false", "0", "no"}:
        return RuntimeCheck(
            code="launch_at_login",
            status="pass",
            message="Wrapper startup after login is disabled.",
            impact="Harness can run normally through explicit CLI/web startup.",
            next_action="No action needed.",
            details={"state": state},
        )
    return RuntimeCheck(
        code="launch_at_login",
        status="pass",
        message="No wrapper startup after login is configured.",
        impact="Harness can run normally through explicit CLI/web startup.",
        next_action="No action needed.",
        details={"state": state},
    )


def _check_workspace_folders() -> RuntimeCheck:
    raw_folders = _clean_env_value(ENV_WORKSPACE_FOLDERS)
    if not raw_folders:
        return RuntimeCheck(
            code="workspace_folders",
            status="pass",
            message="No workspace folders are configured.",
            impact="No external folder access is required until a workflow needs local repo or artifact inspection.",
            next_action="No action needed.",
            details={"folders": []},
        )

    folders = [Path(value).expanduser() for value in raw_folders.split(os.pathsep) if value.strip()]
    missing = [str(path) for path in folders if not path.exists()]
    unreadable = [str(path) for path in folders if path.exists() and not os.access(path, os.R_OK)]
    details = {
        "folders": [str(path) for path in folders],
        "missing": missing,
        "unreadable": unreadable,
    }
    if missing or unreadable:
        return RuntimeCheck(
            code="workspace_folders",
            status="fail",
            message="One or more configured workspace folders are unavailable.",
            impact="Workflows that need local repository or artifact inspection may fail.",
            next_action="Reconnect the missing folders through your wrapper shell or remove stale workspace folder entries.",
            details=details,
        )
    return RuntimeCheck(
        code="workspace_folders",
        status="pass",
        message="Configured workspace folders are accessible.",
        impact="Harness can use the configured local workspace folders when a workflow needs them.",
        next_action="No action needed.",
        details=details,
    )


def _clean_env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def serve_runtime(paths: RuntimePaths, *, host: str | None = None, port: int | None = None) -> int:
    config, _ = init_runtime(paths, host=host or DEFAULT_API_HOST, port=port or DEFAULT_API_PORT)
    if host or port:
        config = RuntimeConfig.from_dict(
            {**config.asdict(), "api": {"host": host or config.host, "port": port or config.port}},
            paths=paths,
        )
    apply_runtime_environment(config, config_path=paths.config_path)
    _assert_port_available(config.host, config.port)
    config.pid_path.parent.mkdir(parents=True, exist_ok=True)
    config.pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    try:
        with config.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"[local-runtime] starting Harness API at {config.base_url}\n")
            log_file.flush()
            with contextlib.redirect_stdout(log_file), contextlib.redirect_stderr(log_file):
                _run_uvicorn(config)
    finally:
        with contextlib.suppress(OSError):
            config.pid_path.unlink()
    return EXIT_OK


def _assert_port_available(host: str, port: int) -> None:
    available, error = _port_available(host, port)
    if not available:
        raise LocalRuntimeError(
            f"Harness runtime cannot bind {host}:{port}: {error}. "
            "Stop the existing process or choose a different port.",
            exit_code=EXIT_RUNTIME_ERROR,
        )


def _port_available(host: str, port: int) -> tuple[bool, str | None]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as error:
            return False, str(error)
    return True, None


def _wait_for_runtime_health(config: RuntimeConfig, *, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        http_status, health, _ = fetch_runtime_health(config, timeout=0.5)
        if http_status == 200 and bool(health and health.get("status") == "ok"):
            return True
        time.sleep(0.2)
    return False


def _run_uvicorn(config: RuntimeConfig) -> None:
    import uvicorn

    uvicorn.run("backend.server:app", host=config.host, port=config.port, log_level="info")


def stop_runtime(config: RuntimeConfig, *, timeout_seconds: float = 10.0) -> tuple[int, dict[str, Any]]:
    pid = read_pid(config.pid_path)
    if not process_is_running(pid):
        with contextlib.suppress(OSError):
            config.pid_path.unlink()
        return EXIT_OK, {
            "status": "stopped",
            "message": "Harness runtime is not running.",
            "pid": pid,
            "paths": _paths_payload(config),
        }
    assert pid is not None
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not process_is_running(pid):
            with contextlib.suppress(OSError):
                config.pid_path.unlink()
            return EXIT_OK, {
                "status": "stopped",
                "message": "Harness runtime stopped.",
                "pid": pid,
                "paths": _paths_payload(config),
            }
        time.sleep(0.1)
    return EXIT_RUNTIME_ERROR, {
        "status": "failed",
        "message": f"Harness runtime pid {pid} did not stop within {timeout_seconds:g} seconds.",
        "pid": pid,
        "paths": _paths_payload(config),
    }


def open_runtime(config: RuntimeConfig, *, launch: bool = True) -> tuple[int, dict[str, Any]]:
    url = os.environ.get("HARNESS_DASHBOARD_URL") or f"{config.base_url}/dashboard"
    if launch:
        _open_url(url)
    return EXIT_OK, {
        "status": "opened" if launch else "ready",
        "url": url,
    }


def _open_url(url: str) -> None:
    system_name = platform.system()
    if system_name not in {"Darwin", "Linux"}:
        raise LocalRuntimeError(f"Opening URLs is not supported on {system_name}. Use this URL: {url}")
    command = "open" if system_name == "Darwin" else "xdg-open"
    try:
        subprocess.run([command, url], check=False)
    except OSError as error:
        raise LocalRuntimeError(f"Could not open {url}: {error}. Use the URL directly.") from error


def build_runtime_status_payload(health_payload: dict[str, Any]) -> dict[str, Any]:
    """Build the stable backend endpoint payload used by local runtime clients."""

    base_url = os.environ.get(ENV_RUNTIME_BASE_URL)
    if not base_url:
        host = os.environ.get(ENV_RUNTIME_HOST, DEFAULT_API_HOST)
        port = os.environ.get(ENV_RUNTIME_PORT, str(DEFAULT_API_PORT))
        base_url = f"http://{host}:{port}"

    return {
        "status": "running" if health_payload.get("status") == "ok" else "degraded",
        "mode": os.environ.get(ENV_RUNTIME_MODE, "developer"),
        "secret_provider": os.environ.get(ENV_SECRET_PROVIDER),
        "api_base_url": base_url,
        "store_backend": health_payload.get("store_backend"),
        "database_schema_ready": health_payload.get("database_schema_ready"),
        "paths": {
            "config_path": os.environ.get(ENV_RUNTIME_CONFIG_PATH),
            "data_dir": os.environ.get(ENV_RUNTIME_DATA_DIR),
            "database_path": health_payload.get("database_path"),
            "log_path": os.environ.get(ENV_RUNTIME_LOG_PATH),
        },
        "health": health_payload,
    }


def _paths_payload(config: RuntimeConfig) -> dict[str, str]:
    return {
        "data_dir": str(config.data_dir),
        "log_dir": str(config.log_dir),
        "config_path": str(config.data_dir / "config.json"),
        "dashboard_assets_dir": str(config.dashboard_assets_dir),
        "database_path": str(config.database_path),
        "runtime_dir": str(config.runtime_dir),
        "pid_path": str(config.pid_path),
        "log_path": str(config.log_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Control the local Harness runtime.",
    )
    parser.add_argument("--data-dir", help="Override the runtime-managed data directory")
    parser.add_argument("--log-dir", help="Override the runtime-managed log directory")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="Create local runtime config, directories, logs, and SQLite schema",
    )
    init_parser.add_argument("--host", default=DEFAULT_API_HOST, help="Loopback host for the local API")
    init_parser.add_argument("--port", default=DEFAULT_API_PORT, type=int, help="Port for the local API")
    init_parser.add_argument("--force", action="store_true", help="Rewrite config with the supplied defaults")

    serve_parser = subparsers.add_parser("serve", help="Run the local Harness API in the foreground")
    serve_parser.add_argument("--host", help="Temporary host override for this process")
    serve_parser.add_argument("--port", type=int, help="Temporary port override for this process")

    start_parser = subparsers.add_parser("start", help="Start the local Harness API as a runtime-managed process")
    start_parser.add_argument("--host", help="Temporary host override for this process")
    start_parser.add_argument("--port", type=int, help="Temporary port override for this process")
    start_parser.add_argument("--timeout", default=10.0, type=float, help="Startup timeout in seconds")

    status_parser = subparsers.add_parser("status", help="Check whether the local Harness runtime is healthy")
    status_parser.add_argument(
        "--timeout",
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        type=float,
        help="Health request timeout in seconds",
    )

    doctor_parser = subparsers.add_parser("doctor", help="Run local setup checks with remediation hints")
    doctor_parser.set_defaults(command="doctor")

    open_parser = subparsers.add_parser("open", help="Open the local Harness dashboard or API URL")
    open_parser.add_argument(
        "--print-url",
        action="store_true",
        help="Print the URL without launching a browser",
    )

    stop_parser = subparsers.add_parser("stop", help="Gracefully stop the local Harness runtime")
    stop_parser.add_argument("--timeout", default=10.0, type=float, help="Shutdown timeout in seconds")

    recover_parser = subparsers.add_parser("recover", help="Recover a stale, crashed, or degraded local runtime")
    recover_parser.add_argument("--timeout", default=10.0, type=float, help="Recovery startup timeout in seconds")

    setup_parser = subparsers.add_parser("setup", help="Guide local runtime and optional integration setup")
    setup_subparsers = setup_parser.add_subparsers(dest="setup_command", required=True)

    setup_status_parser = setup_subparsers.add_parser(
        "status",
        help="Report guided setup state for CLI/web setup flows",
    )
    setup_status_parser.add_argument(
        "--workflow",
        action="append",
        choices=available_workflow_ids(),
        default=[],
        help="Treat integrations for the selected workflow as required",
    )

    secrets_parser = subparsers.add_parser("secrets", help="Manage runtime-managed Harness secrets")
    secrets_subparsers = secrets_parser.add_subparsers(dest="secret_command", required=True)

    secrets_status_parser = secrets_subparsers.add_parser(
        "status",
        help="Report configured and missing runtime-managed secrets without printing values",
    )
    secrets_status_parser.add_argument(
        "--require",
        action="append",
        default=[],
        help="Treat the named secret as required for this status check",
    )

    secrets_set_parser = secrets_subparsers.add_parser(
        "set",
        help="Store a secret in the runtime-managed secret provider",
    )
    secrets_set_parser.add_argument("name", help="Secret name")
    secrets_set_parser.add_argument(
        "--value-stdin",
        action="store_true",
        help="Read the secret value from stdin",
    )

    secrets_delete_parser = secrets_subparsers.add_parser(
        "delete",
        help="Delete a stored runtime-managed secret",
    )
    secrets_delete_parser.add_argument("name", help="Secret name")

    return parser

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = resolve_runtime_paths(data_dir=args.data_dir, log_dir=args.log_dir)

    try:
        if args.command == "init":
            config, created = init_runtime(paths, host=args.host, port=args.port, force=args.force)
            return _emit(
                {
                    "status": "initialized",
                    "created": created,
                    "api_base_url": config.base_url,
                    "paths": _paths_payload(config),
                },
                as_json=args.as_json,
            )
        if args.command == "serve":
            return serve_runtime(paths, host=args.host, port=args.port)
        if args.command == "start":
            exit_code, payload = start_runtime(
                paths,
                host=args.host,
                port=args.port,
                timeout_seconds=args.timeout,
            )
            return _emit(payload, as_json=args.as_json, exit_code=exit_code)
        if args.command == "status":
            try:
                config = load_runtime_config(paths)
            except LocalRuntimeError as error:
                if paths.config_path.exists():
                    return _emit(
                        {"status": "error", "error": str(error)},
                        as_json=args.as_json,
                        exit_code=error.exit_code,
                    )
                return _emit(uninitialized_status(paths), as_json=args.as_json, exit_code=EXIT_SETUP_REQUIRED)
            exit_code, payload = runtime_status(config, timeout=args.timeout)
            return _emit(payload, as_json=args.as_json, exit_code=exit_code)
        if args.command == "doctor":
            exit_code, payload = run_doctor(paths)
            return _emit(payload, as_json=args.as_json, exit_code=exit_code)
        if args.command == "open":
            config = load_runtime_config(paths)
            exit_code, payload = open_runtime(config, launch=not args.print_url)
            return _emit(payload, as_json=args.as_json, exit_code=exit_code)
        if args.command == "stop":
            config = load_runtime_config(paths)
            exit_code, payload = stop_runtime(config, timeout_seconds=args.timeout)
            return _emit(payload, as_json=args.as_json, exit_code=exit_code)
        if args.command == "recover":
            exit_code, payload = recover_runtime(paths, timeout_seconds=args.timeout)
            return _emit(payload, as_json=args.as_json, exit_code=exit_code)
        if args.command == "setup":
            return _handle_setup_command(paths, args, as_json=args.as_json)
        if args.command == "secrets":
            return _handle_secrets_command(args, as_json=args.as_json)
    except LocalRuntimeError as error:
        return _emit({"status": "error", "error": str(error)}, as_json=args.as_json, exit_code=error.exit_code)
    except LocalSetupError as error:
        return _emit({"status": "error", "error": str(error)}, as_json=args.as_json, exit_code=EXIT_SETUP_REQUIRED)
    except LocalSecretError as error:
        return _emit({"status": "error", "error": str(error)}, as_json=args.as_json, exit_code=EXIT_SETUP_REQUIRED)
    except Exception as error:
        return _emit(
            {"status": "error", "error": f"{type(error).__name__}: {error}"},
            as_json=args.as_json,
            exit_code=EXIT_RUNTIME_ERROR,
        )

    parser.error(f"Unsupported command {args.command!r}")
    return EXIT_RUNTIME_ERROR


def _handle_setup_command(paths: RuntimePaths, args: argparse.Namespace, *, as_json: bool) -> int:
    if args.setup_command == "status":
        _, doctor_payload = run_doctor(paths)
        payload = build_guided_setup_status(doctor_payload, selected_workflows=args.workflow)
        exit_code = EXIT_SETUP_REQUIRED if payload.get("required_blockers") else EXIT_OK
        return _emit(payload, as_json=as_json, exit_code=exit_code)
    raise LocalRuntimeError(f"Unsupported setup command {args.setup_command!r}.")


def _handle_secrets_command(args: argparse.Namespace, *, as_json: bool) -> int:
    store = create_secret_store()
    if args.secret_command == "status":
        statuses = collect_secret_statuses(store=store, required_names=args.require)
        payload = secret_status_payload(statuses)
        missing_required = bool(payload.get("missing_required"))
        exit_code = EXIT_SETUP_REQUIRED if missing_required else EXIT_OK
        return _emit(payload, as_json=as_json, exit_code=exit_code)
    if args.secret_command == "set":
        if not args.value_stdin:
            raise LocalRuntimeError(
                "Use `--value-stdin` so secrets are not stored in shell history.",
                exit_code=EXIT_SETUP_REQUIRED,
            )
        value = sys.stdin.read().rstrip("\n")
        store.set_secret(args.name, value)
        return _emit(
            {
                "status": "stored",
                "secret": args.name,
                "message": "Secret stored in the runtime-managed secret provider.",
            },
            as_json=as_json,
        )
    if args.secret_command == "delete":
        deleted = store.delete_secret(args.name)
        return _emit(
            {
                "status": "deleted" if deleted else "missing",
                "secret": args.name,
                "message": "Secret deleted." if deleted else "Secret was not stored.",
            },
            as_json=as_json,
        )
    raise LocalRuntimeError(f"Unsupported secrets command {args.secret_command!r}.")


def _emit(payload: dict[str, Any], *, as_json: bool, exit_code: int = EXIT_OK) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return exit_code

    status = payload.get("status", "unknown")
    print(f"status: {status}")
    for key in ("message", "error", "next_action", "api_base_url", "url"):
        value = payload.get(key)
        if value:
            print(f"{key}: {value}")
    paths = payload.get("paths")
    if isinstance(paths, dict):
        print("paths:")
        for key, value in paths.items():
            print(f"- {key}: {value}")
    checks = payload.get("checks")
    if isinstance(checks, list):
        print("checks:")
        for check in checks:
            if isinstance(check, dict):
                print(f"- {check.get('code')}: {check.get('status')} - {check.get('message')}")
                if check.get("impact"):
                    print(f"  impact: {check.get('impact')}")
                if check.get("next_action"):
                    print(f"  next_action: {check.get('next_action')}")
    secrets = payload.get("secrets")
    if isinstance(secrets, list):
        print("secrets:")
        for secret in secrets:
            if isinstance(secret, dict):
                print(f"- {secret.get('name')}: {secret.get('status')} - {secret.get('message')}")
    items = payload.get("items")
    if isinstance(items, list):
        print("setup_items:")
        for item in items:
            if isinstance(item, dict):
                marker = "required" if item.get("required") else "optional"
                print(f"- {item.get('id')}: {item.get('status')} ({marker})")
                if item.get("next_action"):
                    print(f"  next_action: {item.get('next_action')}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

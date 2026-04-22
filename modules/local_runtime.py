"""Local app runtime CLI and process contract for Harness."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
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
    pid_path: Path
    log_path: Path


@dataclass(frozen=True)
class RuntimeConfig:
    schema_version: int
    host: str
    port: int
    database_path: Path
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
        log_dir = Path(str(stored_paths.get("log_dir") or paths.log_dir)).expanduser()
        runtime_dir = Path(str(stored_paths.get("runtime_dir") or paths.runtime_dir)).expanduser()
        pid_path = Path(str(stored_paths.get("pid_path") or paths.pid_path)).expanduser()
        log_path = Path(str(stored_paths.get("log_path") or paths.log_path)).expanduser()
        return cls(
            schema_version=schema_version,
            host=host,
            port=port,
            database_path=database_path,
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
    next_action: str


def resolve_runtime_paths(
    *,
    data_dir: str | Path | None = None,
    log_dir: str | Path | None = None,
    platform_name: str | None = None,
    home: str | Path | None = None,
) -> RuntimePaths:
    """Resolve app-managed local runtime paths."""

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
    """Create app-managed runtime directories, config, log file, and SQLite schema."""

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
    """Apply app-managed runtime environment for backend startup."""

    os.environ["HARNESS_STORE_BACKEND"] = "sqlite"
    os.environ["HARNESS_SQLITE_PATH"] = str(config.database_path)
    os.environ[ENV_RUNTIME_MODE] = "local-app"
    os.environ[ENV_RUNTIME_CONFIG_PATH] = str(config_path)
    os.environ[ENV_RUNTIME_DATA_DIR] = str(config.data_dir)
    os.environ[ENV_RUNTIME_LOG_PATH] = str(config.log_path)
    os.environ[ENV_RUNTIME_HOST] = config.host
    os.environ[ENV_RUNTIME_PORT] = str(config.port)
    os.environ[ENV_RUNTIME_BASE_URL] = config.base_url


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
                next_action="Run `harness init` from the app bundle or CLI.",
            )
        )
    else:
        checks.append(
            RuntimeCheck(
                code="config",
                status="pass",
                message=f"Runtime config exists at {paths.config_path}.",
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
                next_action=(
                    "No action needed."
                    if api_running
                    else "Start Harness from the app or run `harness serve`."
                ),
            )
        )

    exit_code = EXIT_RUNTIME_ERROR if any(check.status == "fail" for check in checks) else EXIT_OK
    return exit_code, {
        "status": "fail" if exit_code else "ok",
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
            next_action="Choose a writable app data location or fix directory permissions.",
        )
    return RuntimeCheck(
        code=code,
        status="pass",
        message=f"{path} is writable.",
        next_action="No action needed.",
    )


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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as error:
            raise LocalRuntimeError(
                f"Harness runtime cannot bind {host}:{port}: {error}. "
                "Stop the existing process or choose a different port.",
                exit_code=EXIT_RUNTIME_ERROR,
            ) from error


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
    url = os.environ.get("HARNESS_DASHBOARD_URL") or config.base_url
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
    """Build the stable backend endpoint payload used by the app shell."""

    base_url = os.environ.get(ENV_RUNTIME_BASE_URL)
    if not base_url:
        host = os.environ.get(ENV_RUNTIME_HOST, DEFAULT_API_HOST)
        port = os.environ.get(ENV_RUNTIME_PORT, str(DEFAULT_API_PORT))
        base_url = f"http://{host}:{port}"

    return {
        "status": "running" if health_payload.get("status") == "ok" else "degraded",
        "mode": os.environ.get(ENV_RUNTIME_MODE, "developer"),
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
    parser.add_argument("--data-dir", help="Override the app-managed data directory")
    parser.add_argument("--log-dir", help="Override the app-managed log directory")
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
    except LocalRuntimeError as error:
        return _emit({"status": "error", "error": str(error)}, as_json=args.as_json, exit_code=error.exit_code)
    except Exception as error:
        return _emit(
            {"status": "error", "error": f"{type(error).__name__}: {error}"},
            as_json=args.as_json,
            exit_code=EXIT_RUNTIME_ERROR,
        )

    parser.error(f"Unsupported command {args.command!r}")
    return EXIT_RUNTIME_ERROR


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
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

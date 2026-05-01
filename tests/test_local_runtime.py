from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.local_secrets import InMemorySecretStore, LinuxSecretServiceSecretStore
from modules.local_runtime import (
    DEFAULT_API_PORT,
    EXIT_OK,
    EXIT_RUNTIME_ERROR,
    EXIT_SETUP_REQUIRED,
    EXIT_UNHEALTHY,
    build_runtime_status_payload,
    init_runtime,
    main,
    recover_runtime,
    resolve_runtime_paths,
    serve_runtime,
    start_runtime,
    stop_runtime,
    _check_execution_substrate,
)


class LocalRuntimeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_dir = tempfile.TemporaryDirectory()
        self.data_path = Path(self.temp_dir.name)
        self.log_path = Path(self.log_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        self.log_dir.cleanup()

    def _run_cli(self, *args: str) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(
                [
                    "--data-dir",
                    str(self.data_path),
                    "--log-dir",
                    str(self.log_path),
                    "--json",
                    *args,
                ]
            )
        return exit_code, json.loads(stdout.getvalue())

    def test_init_creates_runtime_managed_config_sqlite_database_and_log(self) -> None:
        exit_code, payload = self._run_cli("init")

        config_path = self.data_path / "config.json"
        database_path = self.data_path / "harness.db"
        runtime_log_path = self.log_path / "harness.log"

        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(payload["status"], "initialized")
        self.assertTrue(config_path.exists())
        self.assertTrue(database_path.exists())
        self.assertTrue(runtime_log_path.exists())

        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["storage"]["backend"], "sqlite")
        self.assertEqual(config["storage"]["sqlite_path"], str(database_path))
        self.assertEqual(config["api"]["port"], DEFAULT_API_PORT)
        self.assertEqual(
            config["paths"]["dashboard_assets_dir"],
            str(self.data_path / "dashboard"),
        )
        self.assertNotIn("GITHUB_TOKEN", json.dumps(config))
        self.assertNotIn("LINEAR_API_KEY", json.dumps(config))

    def test_status_before_init_returns_setup_required(self) -> None:
        exit_code, payload = self._run_cli("status")

        self.assertEqual(exit_code, EXIT_SETUP_REQUIRED)
        self.assertEqual(payload["status"], "uninitialized")
        self.assertIn("proofline init", payload["next_action"])

    def test_status_reports_stopped_when_health_is_unreachable(self) -> None:
        self._run_cli("init")

        with patch("modules.local_runtime.fetch_runtime_health", return_value=(None, None, "not running")):
            exit_code, payload = self._run_cli("status", "--timeout", "0.01")

        self.assertEqual(exit_code, EXIT_UNHEALTHY)
        self.assertEqual(payload["status"], "stopped")
        self.assertFalse(payload["process_running"])

    def test_invalid_config_returns_readable_setup_error(self) -> None:
        self.data_path.mkdir(parents=True, exist_ok=True)
        (self.data_path / "config.json").write_text(
            json.dumps({"schema_version": 1, "api": {"port": "not-a-port"}}),
            encoding="utf-8",
        )

        exit_code, payload = self._run_cli("status")

        self.assertEqual(exit_code, EXIT_SETUP_REQUIRED)
        self.assertEqual(payload["status"], "error")
        self.assertIn("invalid api.port", payload["error"])

    def test_doctor_reports_setup_passes_and_api_warning_when_stopped(self) -> None:
        self._run_cli("init")
        dashboard_dir = self.data_path / "dashboard"
        dashboard_dir.mkdir()
        (dashboard_dir / "index.html").write_text("<h1>Harness</h1>", encoding="utf-8")
        workspace_dir = self.data_path / "workspace"
        workspace_dir.mkdir()

        with (
            patch.dict(
                os.environ,
                {
                    "HARNESS_DASHBOARD_ASSETS_DIR": str(dashboard_dir),
                    "HARNESS_SYMPHONY_BIN": sys.executable,
                    "OPENCLAW_BASE_URL": "http://127.0.0.1:18789",
                    "HARNESS_NOTIFICATION_PERMISSION": "authorized",
                    "HARNESS_LAUNCH_AT_LOGIN": "enabled",
                    "HARNESS_WORKSPACE_FOLDERS": str(workspace_dir),
                },
                clear=True,
            ),
            patch("modules.local_runtime.fetch_runtime_health", return_value=(None, None, "not running")),
            patch(
                "modules.local_runtime.create_secret_store",
                return_value=InMemorySecretStore(
                    {
                        "github_token": "ghp_secret",
                        "linear_api_key": "lin_secret",
                    }
                ),
            ),
        ):
            exit_code, payload = self._run_cli("doctor")
        checks = {check["code"]: check for check in payload["checks"]}

        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["summary"]["fail"], 0)
        self.assertEqual(checks["app_data_dir"]["status"], "pass")
        self.assertEqual(checks["log_dir"]["status"], "pass")
        self.assertEqual(checks["config"]["status"], "pass")
        self.assertEqual(checks["sqlite"]["status"], "pass")
        self.assertEqual(checks["api_health"]["status"], "warn")
        self.assertEqual(checks["dashboard"]["status"], "warn")
        self.assertEqual(checks["github_connection"]["status"], "pass")
        self.assertEqual(checks["linear_connection"]["status"], "pass")
        self.assertEqual(checks["execution_substrate"]["status"], "pass")
        self.assertFalse(checks["execution_substrate"]["details"]["live_dispatch_enabled"])
        self.assertEqual(
            checks["execution_substrate"]["details"]["completion_authority"],
            "harness_verification",
        )
        self.assertFalse(checks["execution_substrate"]["details"]["runner_completion_is_truth"])
        self.assertEqual(checks["ingress_executor"]["status"], "pass")
        self.assertEqual(checks["notification_permission"]["status"], "pass")
        self.assertEqual(checks["launch_at_login"]["status"], "pass")
        self.assertEqual(checks["workspace_folders"]["status"], "pass")
        self.assertIn("proofline serve", checks["api_health"]["next_action"])
        self.assertNotIn("Harness app", json.dumps(payload))
        self.assertNotIn("menu-bar", json.dumps(payload))
        self.assertTrue(all(check.get("impact") for check in payload["checks"]))
        self.assertTrue(all(check.get("next_action") for check in payload["checks"]))

    def test_execution_substrate_warning_still_preserves_harness_authority(self) -> None:
        missing_binary = self.data_path / "missing-symphony"

        with patch("modules.local_runtime._symphony_binary_candidates", return_value=[missing_binary]):
            check = _check_execution_substrate()

        self.assertEqual(check.status, "warn")
        self.assertEqual(check.details["mode"], "unconfigured")
        self.assertFalse(check.details["live_dispatch_enabled"])
        self.assertEqual(check.details["completion_authority"], "harness_verification")
        self.assertFalse(check.details["runner_completion_is_truth"])

    def test_doctor_fails_when_configured_workspace_folder_is_missing(self) -> None:
        self._run_cli("init")

        with (
            patch.dict(
                os.environ,
                {"HARNESS_WORKSPACE_FOLDERS": str(self.data_path / "missing-workspace")},
                clear=True,
            ),
            patch("modules.local_runtime.create_secret_store", return_value=InMemorySecretStore()),
        ):
            exit_code, payload = self._run_cli("doctor")
        checks = {check["code"]: check for check in payload["checks"]}

        self.assertEqual(exit_code, EXIT_RUNTIME_ERROR)
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(checks["workspace_folders"]["status"], "fail")
        self.assertIn("Reconnect", checks["workspace_folders"]["next_action"])
        self.assertNotIn("Traceback", json.dumps(payload))

    def test_doctor_fails_when_configured_executor_config_is_missing(self) -> None:
        self._run_cli("init")

        with (
            patch.dict(
                os.environ,
                {"OPENCLAW_CONFIG_PATH": str(self.data_path / "missing-openclaw.json5")},
                clear=True,
            ),
            patch("modules.local_runtime.create_secret_store", return_value=InMemorySecretStore()),
        ):
            exit_code, payload = self._run_cli("doctor")
        checks = {check["code"]: check for check in payload["checks"]}

        self.assertEqual(exit_code, EXIT_RUNTIME_ERROR)
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(checks["ingress_executor"]["status"], "fail")
        self.assertIn("OPENCLAW_CONFIG_PATH", checks["ingress_executor"]["next_action"])

    def test_secrets_status_reports_required_missing_without_values(self) -> None:
        store = InMemorySecretStore({"github_token": "ghp_secret"})

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("modules.local_runtime.create_secret_store", return_value=store),
        ):
            exit_code, payload = self._run_cli("secrets", "status", "--require", "linear_api_key")

        self.assertEqual(exit_code, EXIT_SETUP_REQUIRED)
        self.assertEqual(payload["status"], "missing_required_secrets")
        self.assertEqual(payload["missing_required"], ["linear_api_key"])
        self.assertNotIn("ghp_secret", json.dumps(payload))

    def test_secrets_set_reads_value_from_stdin_without_echoing_value(self) -> None:
        store = InMemorySecretStore()

        with (
            patch("modules.local_runtime.create_secret_store", return_value=store),
            patch("sys.stdin", io.StringIO("ghp_secret\n")),
        ):
            exit_code, payload = self._run_cli("secrets", "set", "github_token", "--value-stdin")

        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(payload["status"], "stored")
        self.assertEqual(store.values["github_token"], "ghp_secret")
        self.assertNotIn("ghp_secret", json.dumps(payload))

    def test_secrets_delete_reports_missing_without_error(self) -> None:
        store = InMemorySecretStore()

        with patch("modules.local_runtime.create_secret_store", return_value=store):
            exit_code, payload = self._run_cli("secrets", "delete", "github_token")

        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(payload["status"], "missing")

    def test_setup_status_allows_runtime_only_onboarding(self) -> None:
        self._run_cli("init")

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("modules.local_runtime.create_secret_store", return_value=InMemorySecretStore()),
        ):
            exit_code, payload = self._run_cli("setup", "status")
        items = {item["id"]: item for item in payload["items"]}

        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["onboarding_complete"])
        self.assertEqual(payload["required_blockers"], [])
        self.assertEqual(items["local_runtime"]["status"], "complete")
        self.assertEqual(items["github"]["status"], "incomplete")
        self.assertEqual(items["linear"]["status"], "incomplete")
        self.assertIn(items["execution_substrate"]["status"], {"complete", "incomplete"})
        self.assertEqual(items["ingress_executor"]["status"], "incomplete")
        self.assertFalse(items["github"]["required"])
        self.assertFalse(items["linear"]["required"])
        self.assertFalse(items["execution_substrate"]["required"])
        self.assertFalse(items["ingress_executor"]["required"])

    def test_setup_status_selected_workflow_requires_missing_integration(self) -> None:
        self._run_cli("init")

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("modules.local_runtime.create_secret_store", return_value=InMemorySecretStore()),
        ):
            exit_code, payload = self._run_cli("setup", "status", "--workflow", "github-proof")
        items = {item["id"]: item for item in payload["items"]}

        self.assertEqual(exit_code, EXIT_SETUP_REQUIRED)
        self.assertEqual(payload["status"], "setup_required")
        self.assertEqual(payload["required_blockers"], ["github"])
        self.assertTrue(items["github"]["required"])
        self.assertEqual(items["github"]["secret_names"], ["github_token"])
        self.assertNotIn("ghp_secret", json.dumps(payload))


class LocalRuntimeProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_dir = tempfile.TemporaryDirectory()
        self.paths = resolve_runtime_paths(data_dir=self.temp_dir.name, log_dir=self.log_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        self.log_dir.cleanup()

    def test_serve_applies_runtime_environment_and_cleans_pid_file(self) -> None:
        observed: dict[str, object] = {}

        def fake_run_uvicorn(config) -> None:  # noqa: ANN001
            observed["pid_exists_during_run"] = config.pid_path.exists()
            observed["proofline_store_backend"] = os.environ.get("PROOFLINE_STORE_BACKEND")
            observed["proofline_sqlite_path"] = os.environ.get("PROOFLINE_SQLITE_PATH")
            observed["store_backend"] = os.environ.get("HARNESS_STORE_BACKEND")
            observed["sqlite_path"] = os.environ.get("HARNESS_SQLITE_PATH")
            observed["runtime_mode"] = os.environ.get("HARNESS_RUNTIME_MODE")
            observed["proofline_dashboard_assets_dir"] = os.environ.get("PROOFLINE_DASHBOARD_ASSETS_DIR")
            observed["dashboard_assets_dir"] = os.environ.get("HARNESS_DASHBOARD_ASSETS_DIR")
            observed["secret_provider"] = os.environ.get("HARNESS_SECRET_PROVIDER")
            observed["github_token"] = os.environ.get("GITHUB_TOKEN")
            print("server-started")

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("modules.local_runtime._assert_port_available"),
            patch(
                "modules.local_runtime.create_secret_store",
                return_value=InMemorySecretStore({"github_token": "ghp_secret"}),
            ),
            patch(
                "modules.local_runtime._run_uvicorn",
                side_effect=fake_run_uvicorn,
            ),
        ):
            exit_code = serve_runtime(self.paths)

        self.assertEqual(exit_code, EXIT_OK)
        self.assertTrue(observed["pid_exists_during_run"])
        self.assertEqual(observed["proofline_store_backend"], "sqlite")
        self.assertEqual(observed["proofline_sqlite_path"], str(self.paths.database_path))
        self.assertEqual(observed["store_backend"], "sqlite")
        self.assertEqual(observed["sqlite_path"], str(self.paths.database_path))
        self.assertEqual(observed["runtime_mode"], "local-app")
        self.assertEqual(observed["proofline_dashboard_assets_dir"], str(self.paths.dashboard_assets_dir))
        self.assertEqual(observed["dashboard_assets_dir"], str(self.paths.dashboard_assets_dir))
        self.assertEqual(observed["secret_provider"], "memory")
        self.assertEqual(observed["github_token"], "ghp_secret")
        self.assertFalse(self.paths.pid_path.exists())
        log_text = self.paths.log_path.read_text(encoding="utf-8")
        self.assertIn("server-started", log_text)
        self.assertNotIn("ghp_secret", log_text)

    def test_serve_uses_platform_secret_provider_without_macos_assumption(self) -> None:
        observed: dict[str, object] = {}

        def fake_run_uvicorn(config) -> None:  # noqa: ANN001
            observed["secret_provider"] = os.environ.get("HARNESS_SECRET_PROVIDER")

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("modules.local_runtime._assert_port_available"),
            patch(
                "modules.local_runtime.create_secret_store",
                return_value=LinuxSecretServiceSecretStore(platform_name="Linux"),
            ),
            patch("modules.local_runtime._run_uvicorn", side_effect=fake_run_uvicorn),
        ):
            exit_code = serve_runtime(self.paths)

        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(observed["secret_provider"], "linux-secret-service")

    def test_stop_treats_missing_or_stale_process_as_stopped(self) -> None:
        config, _ = init_runtime(self.paths)
        config.pid_path.write_text("999999\n", encoding="utf-8")

        with patch("modules.local_runtime.process_is_running", return_value=False):
            exit_code, payload = stop_runtime(config)

        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(payload["status"], "stopped")
        self.assertFalse(config.pid_path.exists())

    def test_start_launches_background_runtime_and_waits_for_health(self) -> None:
        class FakeProcess:
            pid = 4242

            def poll(self) -> None:
                return None

        with (
            patch("modules.local_runtime.fetch_runtime_health", return_value=(None, None, "not running")),
            patch("modules.local_runtime._port_available", return_value=(True, None)),
            patch("modules.local_runtime._wait_for_runtime_health", return_value=True),
            patch("modules.local_runtime.subprocess.Popen", return_value=FakeProcess()) as popen,
        ):
            exit_code, payload = start_runtime(self.paths)

        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["pid"], 4242)
        self.assertFalse(payload["recovered"])
        popen.assert_called_once()
        self.assertIn("serve", popen.call_args.args[0])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_start_removes_stale_pid_before_launch(self) -> None:
        class FakeProcess:
            pid = 5252

            def poll(self) -> None:
                return None

        config, _ = init_runtime(self.paths)
        config.pid_path.write_text("999999\n", encoding="utf-8")

        with (
            patch("modules.local_runtime.fetch_runtime_health", return_value=(None, None, "not running")),
            patch("modules.local_runtime.process_is_running", return_value=False),
            patch("modules.local_runtime._port_available", return_value=(True, None)),
            patch("modules.local_runtime._wait_for_runtime_health", return_value=True),
            patch("modules.local_runtime.subprocess.Popen", return_value=FakeProcess()),
        ):
            exit_code, payload = start_runtime(self.paths)

        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(payload["status"], "running")
        self.assertTrue(payload["recovered"])
        self.assertFalse(config.pid_path.exists())

    def test_start_reports_port_conflict_without_launching_child(self) -> None:
        with (
            patch("modules.local_runtime.fetch_runtime_health", return_value=(None, None, "not running")),
            patch("modules.local_runtime._port_available", return_value=(False, "address already in use")),
            patch("modules.local_runtime.subprocess.Popen") as popen,
        ):
            exit_code, payload = start_runtime(self.paths)

        self.assertEqual(exit_code, EXIT_RUNTIME_ERROR)
        self.assertEqual(payload["status"], "port_conflict")
        self.assertIn("already in use", payload["message"])
        self.assertIn("Recover Runtime", payload["next_action"])
        popen.assert_not_called()

    def test_start_uses_bundled_runtime_executable_when_frozen(self) -> None:
        class FakeProcess:
            pid = 4343

            def poll(self) -> None:
                return None

        with (
            patch("modules.local_runtime.fetch_runtime_health", return_value=(None, None, "not running")),
            patch("modules.local_runtime._port_available", return_value=(True, None)),
            patch("modules.local_runtime._wait_for_runtime_health", return_value=True),
            patch("modules.local_runtime.runtime_is_frozen", return_value=True),
            patch("modules.local_runtime.sys.executable", "/Applications/Harness.app/Contents/Resources/HarnessRuntime/harness"),
            patch("modules.local_runtime.subprocess.Popen", return_value=FakeProcess()) as popen,
        ):
            exit_code, payload = start_runtime(self.paths)

        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(payload["status"], "running")
        self.assertEqual(
            popen.call_args.args[0][0],
            "/Applications/Harness.app/Contents/Resources/HarnessRuntime/harness",
        )
        self.assertNotIn("-m", popen.call_args.args[0])
        self.assertIn("serve", popen.call_args.args[0])

    def test_recover_stops_unhealthy_pid_before_restart(self) -> None:
        class FakeProcess:
            pid = 6262

            def poll(self) -> None:
                return None

        with (
            patch(
                "modules.local_runtime.runtime_status",
                return_value=(
                    EXIT_UNHEALTHY,
                    {"status": "degraded", "pid": 123, "process_running": True},
                ),
            ),
            patch("modules.local_runtime.stop_runtime", return_value=(EXIT_OK, {"status": "stopped"})) as stop,
            patch("modules.local_runtime._port_available", return_value=(True, None)),
            patch("modules.local_runtime._wait_for_runtime_health", return_value=True),
            patch("modules.local_runtime.subprocess.Popen", return_value=FakeProcess()),
        ):
            exit_code, payload = recover_runtime(self.paths)

        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(payload["status"], "running")
        self.assertTrue(payload["recovered"])
        stop.assert_called_once()


class LocalRuntimeContractTests(unittest.TestCase):
    def test_resolves_macos_runtime_managed_paths(self) -> None:
        paths = resolve_runtime_paths(platform_name="darwin", home="/Users/sean")

        self.assertEqual(paths.data_dir, Path("/Users/sean/Library/Application Support/Harness"))
        self.assertEqual(paths.log_dir, Path("/Users/sean/Library/Logs/Harness"))
        self.assertEqual(paths.config_path, paths.data_dir / "config.json")
        self.assertEqual(paths.database_path, paths.data_dir / "harness.db")
        self.assertEqual(paths.dashboard_assets_dir, paths.data_dir / "dashboard")

    def test_resolves_linux_runtime_managed_paths(self) -> None:
        with patch.dict(
            os.environ,
            {"XDG_DATA_HOME": "/tmp/xdg-data", "XDG_STATE_HOME": "/tmp/xdg-state"},
            clear=True,
        ):
            paths = resolve_runtime_paths(platform_name="linux", home="/Users/sean")

        self.assertEqual(paths.data_dir, Path("/tmp/xdg-data/harness"))
        self.assertEqual(paths.log_dir, Path("/tmp/xdg-state/harness/logs"))
        self.assertEqual(paths.database_path, Path("/tmp/xdg-data/harness/harness.db"))
        self.assertEqual(paths.dashboard_assets_dir, Path("/tmp/xdg-data/harness/dashboard"))

    def test_backend_runtime_status_payload_uses_runtime_environment_without_secrets(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HARNESS_RUNTIME_MODE": "local-app",
                "HARNESS_SECRET_PROVIDER": "linux-secret-service",
                "HARNESS_RUNTIME_BASE_URL": "http://127.0.0.1:8765",
                "HARNESS_RUNTIME_CONFIG_PATH": "/tmp/harness/config.json",
                "HARNESS_RUNTIME_DATA_DIR": "/tmp/harness",
                "HARNESS_RUNTIME_LOG_PATH": "/tmp/harness.log",
            },
            clear=True,
        ):
            payload = build_runtime_status_payload(
                {
                    "status": "ok",
                    "store_backend": "sqlite",
                    "database_path": "/tmp/harness/harness.db",
                    "database_schema_ready": True,
                }
            )

        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["mode"], "local-app")
        self.assertEqual(payload["secret_provider"], "linux-secret-service")
        self.assertEqual(payload["api_base_url"], "http://127.0.0.1:8765")
        self.assertEqual(payload["store_backend"], "sqlite")
        self.assertEqual(payload["paths"]["database_path"], "/tmp/harness/harness.db")


if __name__ == "__main__":
    unittest.main()

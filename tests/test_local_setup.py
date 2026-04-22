from __future__ import annotations

import unittest

from modules.local_setup import (
    LocalSetupError,
    build_guided_setup_status,
)


def healthy_runtime_doctor_payload(
    *,
    github_status: str = "warn",
    linear_status: str = "warn",
    executor_status: str = "warn",
) -> dict[str, object]:
    checks = [
        check("app_data_dir", "pass"),
        check("log_dir", "pass"),
        check("config", "pass"),
        check("sqlite", "pass"),
        check("api_health", "warn", next_action="Start Harness from the app or run `harness serve`."),
        check("dashboard", "warn", next_action="Install packaged dashboard assets."),
        check("notification_permission", "warn", next_action="Complete the notifications setup step."),
        check("launch_at_login", "warn", next_action="Complete the Launch at Login setup step."),
        check("workspace_folders", "pass"),
        check(
            "github_connection",
            github_status,
            next_action="Connect GitHub token during setup or run `harness secrets set github_token --value-stdin`.",
        ),
        check(
            "linear_connection",
            linear_status,
            next_action="Connect Linear API key during setup or run `harness secrets set linear_api_key --value-stdin`.",
        ),
        check(
            "ingress_executor",
            executor_status,
            next_action="Connect OpenClaw, Hermes, Codex, or another compatible desktop-agent bridge during setup.",
        ),
    ]
    return {
        "status": "ok",
        "summary": {
            "pass": sum(1 for item in checks if item["status"] == "pass"),
            "warn": sum(1 for item in checks if item["status"] == "warn"),
            "fail": sum(1 for item in checks if item["status"] == "fail"),
        },
        "checks": checks,
    }


def check(code: str, status: str, *, next_action: str = "No action needed.") -> dict[str, object]:
    return {
        "code": code,
        "status": status,
        "message": f"{code} is {status}.",
        "impact": f"{code} impact.",
        "next_action": next_action,
    }


class GuidedSetupStatusTests(unittest.TestCase):
    def test_runtime_only_onboarding_can_complete_with_missing_optional_integrations(self) -> None:
        payload = build_guided_setup_status(healthy_runtime_doctor_payload())
        items = {item["id"]: item for item in payload["items"]}

        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["onboarding_complete"])
        self.assertTrue(payload["runtime_ready"])
        self.assertEqual(payload["required_blockers"], [])
        self.assertEqual(items["local_runtime"]["status"], "complete")
        self.assertTrue(items["local_runtime"]["required"])
        self.assertEqual(items["github"]["status"], "incomplete")
        self.assertEqual(items["linear"]["status"], "incomplete")
        self.assertEqual(items["ingress_executor"]["status"], "incomplete")
        self.assertFalse(items["github"]["required"])
        self.assertFalse(items["linear"]["required"])
        self.assertFalse(items["ingress_executor"]["required"])

    def test_selected_workflow_makes_integration_setup_required(self) -> None:
        payload = build_guided_setup_status(
            healthy_runtime_doctor_payload(),
            selected_workflows=["github-proof"],
        )
        items = {item["id"]: item for item in payload["items"]}

        self.assertEqual(payload["status"], "setup_required")
        self.assertFalse(payload["onboarding_complete"])
        self.assertEqual(payload["required_blockers"], ["github"])
        self.assertTrue(items["github"]["required"])
        self.assertTrue(items["github"]["blocks_onboarding"])
        self.assertEqual(items["github"]["secret_names"], ["github_token"])
        self.assertIn("harness secrets set github_token --value-stdin", items["github"]["next_action"])
        self.assertNotIn("GITHUB_TOKEN=", str(items["github"]))

    def test_configured_integration_completes_required_workflow(self) -> None:
        payload = build_guided_setup_status(
            healthy_runtime_doctor_payload(github_status="pass"),
            selected_workflows=["github-proof"],
        )
        items = {item["id"]: item for item in payload["items"]}

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["required_blockers"], [])
        self.assertEqual(items["github"]["status"], "complete")
        self.assertTrue(items["github"]["required"])

    def test_repair_dispatch_requires_client_neutral_executor_bridge(self) -> None:
        payload = build_guided_setup_status(
            healthy_runtime_doctor_payload(),
            selected_workflows=["repair-dispatch"],
        )
        items = {item["id"]: item for item in payload["items"]}
        executor = items["ingress_executor"]

        self.assertEqual(payload["status"], "setup_required")
        self.assertEqual(payload["required_blockers"], ["ingress_executor"])
        self.assertEqual(executor["status"], "incomplete")
        self.assertTrue(executor["required"])
        self.assertIn("OpenClaw", executor["compatible_clients"])
        self.assertIn("Hermes", executor["compatible_clients"])
        self.assertIn("Codex", executor["compatible_clients"])
        self.assertIn("future desktop-agent clients", executor["compatible_clients"])
        self.assertIn("client-neutral", " ".join(executor["notes"]))

    def test_configured_broken_runtime_blocks_onboarding(self) -> None:
        payload = healthy_runtime_doctor_payload()
        for item in payload["checks"]:
            if item["code"] == "workspace_folders":
                item["status"] = "fail"
                item["next_action"] = "Reconnect the missing folders."

        setup_payload = build_guided_setup_status(payload)
        items = {item["id"]: item for item in setup_payload["items"]}

        self.assertEqual(setup_payload["status"], "setup_required")
        self.assertEqual(setup_payload["required_blockers"], ["local_runtime"])
        self.assertEqual(items["local_runtime"]["status"], "blocked")
        self.assertIn("Reconnect", items["local_runtime"]["next_action"])

    def test_unknown_workflow_raises_operator_readable_error(self) -> None:
        with self.assertRaisesRegex(LocalSetupError, "Unknown setup workflow"):
            build_guided_setup_status(healthy_runtime_doctor_payload(), selected_workflows=["unknown"])


if __name__ == "__main__":
    unittest.main()

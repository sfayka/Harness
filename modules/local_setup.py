"""Guided setup contract for the local Harness app."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


class LocalSetupError(ValueError):
    """Operator-readable guided setup failure."""


@dataclass(frozen=True)
class SetupAction:
    kind: str
    label: str
    description: str
    command: str | None = None
    secret_name: str | None = None
    stores_secret: bool = False

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SetupWorkflow:
    id: str
    label: str
    description: str
    required_items: tuple[str, ...]

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SetupItemDefinition:
    id: str
    title: str
    category: str
    purpose: str
    what_user_needs: tuple[str, ...]
    how_harness_validates: str
    doctor_check_codes: tuple[str, ...]
    completion_check_codes: tuple[str, ...]
    setup_actions: tuple[SetupAction, ...] = ()
    secret_names: tuple[str, ...] = ()
    compatible_clients: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


WORKFLOW_DEFINITIONS: tuple[SetupWorkflow, ...] = (
    SetupWorkflow(
        id="github-proof",
        label="GitHub artifact verification",
        description="Require GitHub before accepting repository, branch, commit, pull-request, or changed-file proof.",
        required_items=("github",),
    ),
    SetupWorkflow(
        id="linear-sync",
        label="Linear coordination",
        description="Require Linear before reading or writing coordinated work state.",
        required_items=("linear",),
    ),
    SetupWorkflow(
        id="repair-dispatch",
        label="Execution substrate dispatch",
        description=(
            "Require a Symphony-compatible execution substrate before Harness can request repair "
            "or executor-backed work."
        ),
        required_items=("execution_substrate",),
    ),
)
WORKFLOW_DEFINITIONS_BY_ID = {workflow.id: workflow for workflow in WORKFLOW_DEFINITIONS}


SETUP_ITEM_DEFINITIONS: tuple[SetupItemDefinition, ...] = (
    SetupItemDefinition(
        id="local_runtime",
        title="Local Harness runtime",
        category="core",
        purpose=(
            "Runs Harness locally with app-managed config, SQLite persistence, local logs, "
            "and the dashboard/API served from the local backend."
        ),
        what_user_needs=(
            "Writable app data and log folders.",
            "Initialized app-managed config and SQLite database.",
            "A running local API when the menu-bar summary or dashboard needs live progress.",
        ),
        how_harness_validates=(
            "Harness checks writable app folders, config readability, SQLite schema readiness, "
            "API health, dashboard assets, app-reported permissions, and selected workspace folders."
        ),
        doctor_check_codes=(
            "app_data_dir",
            "log_dir",
            "config",
            "sqlite",
            "api_health",
            "dashboard",
            "notification_permission",
            "launch_at_login",
            "workspace_folders",
        ),
        completion_check_codes=("app_data_dir", "log_dir", "config", "sqlite", "workspace_folders"),
        setup_actions=(
            SetupAction(
                kind="runtime",
                label="Initialize local runtime",
                description="Create app-managed config, logs, and the SQLite database.",
                command="harness init",
            ),
            SetupAction(
                kind="runtime",
                label="Start Harness",
                description="Start the local API when live status or the dashboard should be available.",
                command="harness serve",
            ),
        ),
        notes=(
            "API and dashboard warnings do not block onboarding; the app can start the runtime when needed.",
            "Notifications and Launch at Login are encouraged app-shell choices, not hard requirements.",
        ),
    ),
    SetupItemDefinition(
        id="github",
        title="GitHub artifact verification",
        category="integration",
        purpose=(
            "Lets Harness verify external execution proof such as repositories, branches, commits, "
            "pull requests, and changed files instead of trusting an agent summary."
        ),
        what_user_needs=(
            "A GitHub account or token with access to the repositories Harness should verify.",
            "The packaged app should store the credential through its app-managed secret provider.",
        ),
        how_harness_validates=(
            "Harness checks the redacted status of the app-managed `github_token` secret through the setup doctor."
        ),
        doctor_check_codes=("github_connection",),
        completion_check_codes=("github_connection",),
        setup_actions=(
            SetupAction(
                kind="secret",
                label="Connect GitHub",
                description="Store the GitHub credential through the app-managed secret boundary.",
                command="harness secrets set github_token --value-stdin",
                secret_name="github_token",
                stores_secret=True,
            ),
        ),
        secret_names=("github_token",),
    ),
    SetupItemDefinition(
        id="linear",
        title="Linear coordination",
        category="integration",
        purpose=(
            "Lets Harness read and update Linear work state when a workflow uses Linear for coordination "
            "or reconciliation."
        ),
        what_user_needs=(
            "A Linear API key or app authorization for the workspace Harness should coordinate with.",
            "The packaged app should store the credential through its app-managed secret provider.",
        ),
        how_harness_validates=(
            "Harness checks the redacted status of the app-managed `linear_api_key` secret through the setup doctor."
        ),
        doctor_check_codes=("linear_connection",),
        completion_check_codes=("linear_connection",),
        setup_actions=(
            SetupAction(
                kind="secret",
                label="Connect Linear",
                description="Store the Linear credential through the app-managed secret boundary.",
                command="harness secrets set linear_api_key --value-stdin",
                secret_name="linear_api_key",
                stores_secret=True,
            ),
        ),
        secret_names=("linear_api_key",),
    ),
    SetupItemDefinition(
        id="execution_substrate",
        title="Execution substrate",
        category="integration",
        purpose=(
            "Lets Harness hand executable work to a scheduler/runner layer. Symphony is the preferred "
            "substrate for polling structured work, creating isolated workspaces, launching Codex, "
            "and reporting advisory execution events back to Harness."
        ),
        what_user_needs=(
            "A local Symphony checkout or another Symphony-compatible runner.",
            "A built runner binary that Harness can find through HARNESS_SYMPHONY_BIN, SYMPHONY_BIN, PATH, "
            "or the Knox Infrastructure checkout convention.",
            "A workflow contract such as WORKFLOW.md before any live runner is enabled.",
        ),
        how_harness_validates=(
            "Harness checks whether a Symphony-compatible runner binary is available. This only proves "
            "the execution substrate is installed; Harness still treats runner output as advisory until "
            "verification and reconciliation succeed."
        ),
        doctor_check_codes=("execution_substrate",),
        completion_check_codes=("execution_substrate",),
        setup_actions=(
            SetupAction(
                kind="connection",
                label="Connect Symphony",
                description=(
                    "Install or build Symphony, then set HARNESS_SYMPHONY_BIN if the binary is not on PATH."
                ),
                command="mise exec -- mix build",
            ),
        ),
        compatible_clients=("Symphony", "Symphony-compatible runners"),
        notes=(
            "This replaces Harness-owned runner scheduling for new work. Harness still owns verification, reconciliation, and lifecycle truth.",
            "A configured runner is not allowed to mark work complete directly.",
        ),
    ),
    SetupItemDefinition(
        id="ingress_executor",
        title="Legacy ingress/executor bridge",
        category="compatibility",
        purpose=(
            "Keeps older OpenClaw/Hermes/Codex bridge paths visible while Harness pivots execution "
            "scheduling to a Symphony-compatible substrate."
        ),
        what_user_needs=(
            "A compatible desktop-agent bridge such as OpenClaw, Hermes, Codex, or a future equivalent.",
            "Either a local CLI bridge configuration or an HTTP repair bridge reachable by the local runtime.",
            "A callback bearer secret only when the selected bridge requires bearer-protected callbacks.",
        ),
        how_harness_validates=(
            "Harness checks the configured desktop-agent bridge mode through the setup doctor. "
            "Current adapter validation accepts a local CLI config/state pair or an HTTP bridge URL, "
            "but new execution-scheduling work should use the execution substrate item instead."
        ),
        doctor_check_codes=("ingress_executor",),
        completion_check_codes=("ingress_executor",),
        setup_actions=(
            SetupAction(
                kind="connection",
                label="Connect desktop-agent bridge",
                description=(
                    "Connect OpenClaw, Hermes, Codex, or another compatible client through the app setup flow."
                ),
            ),
            SetupAction(
                kind="secret",
                label="Store callback bearer token",
                description="Only needed for bearer-protected repair callback workflows.",
                command="harness secrets set repair_callback_bearer_token --value-stdin",
                secret_name="repair_callback_bearer_token",
                stores_secret=True,
            ),
        ),
        secret_names=("repair_callback_bearer_token",),
        compatible_clients=("OpenClaw", "Hermes", "Codex", "future desktop-agent clients"),
        notes=(
            "Compatibility path only; Symphony-compatible execution substrate is the preferred runner layer for new work.",
            "OpenClaw-shaped environment variable names are adapter wiring, not Harness product boundaries.",
        ),
    ),
)
SETUP_ITEM_DEFINITIONS_BY_ID = {definition.id: definition for definition in SETUP_ITEM_DEFINITIONS}


def available_workflow_ids() -> list[str]:
    return sorted(WORKFLOW_DEFINITIONS_BY_ID)


def build_guided_setup_status(
    doctor_payload: dict[str, Any],
    *,
    selected_workflows: Iterable[str] = (),
) -> dict[str, Any]:
    """Build the app-renderable guided onboarding status from doctor output."""

    workflows = _normalize_workflows(selected_workflows)
    required_item_ids = {"local_runtime"}
    for workflow in workflows:
        required_item_ids.update(workflow.required_items)

    checks_by_code = _checks_by_code(doctor_payload)
    items = [
        _build_setup_item(definition, required=definition.id in required_item_ids, checks_by_code=checks_by_code)
        for definition in SETUP_ITEM_DEFINITIONS
    ]
    required_blockers = [
        item["id"] for item in items if item["required"] and item["status"] != "complete"
    ]
    optional_incomplete = [
        item["id"] for item in items if not item["required"] and item["status"] != "complete"
    ]
    optional_attention = [
        item["id"] for item in items if not item["required"] and item["status"] == "blocked"
    ]
    onboarding_complete = not required_blockers

    return {
        "status": "ready" if onboarding_complete else "setup_required",
        "onboarding_complete": onboarding_complete,
        "runtime_ready": _item_by_id(items, "local_runtime")["status"] == "complete",
        "selected_workflows": [workflow.asdict() for workflow in workflows],
        "available_workflows": [workflow.asdict() for workflow in WORKFLOW_DEFINITIONS],
        "required_blockers": required_blockers,
        "optional_incomplete": optional_incomplete,
        "optional_attention": optional_attention,
        "items": items,
        "doctor_summary": doctor_payload.get("summary"),
    }


def _normalize_workflows(selected_workflows: Iterable[str]) -> list[SetupWorkflow]:
    workflows: list[SetupWorkflow] = []
    seen: set[str] = set()
    for raw_workflow in selected_workflows:
        workflow_id = str(raw_workflow).strip()
        if not workflow_id or workflow_id in seen:
            continue
        try:
            workflows.append(WORKFLOW_DEFINITIONS_BY_ID[workflow_id])
        except KeyError as error:
            choices = ", ".join(available_workflow_ids())
            raise LocalSetupError(f"Unknown setup workflow {workflow_id!r}. Expected one of: {choices}.") from error
        seen.add(workflow_id)
    return workflows


def _checks_by_code(doctor_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    checks = doctor_payload.get("checks")
    if not isinstance(checks, list):
        return {}
    checks_by_code: dict[str, dict[str, Any]] = {}
    for check in checks:
        if not isinstance(check, dict):
            continue
        code = check.get("code")
        if code:
            checks_by_code[str(code)] = check
    return checks_by_code


def _build_setup_item(
    definition: SetupItemDefinition,
    *,
    required: bool,
    checks_by_code: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    relevant_checks = [
        checks_by_code[code]
        for code in definition.doctor_check_codes
        if code in checks_by_code
    ]
    completion_checks = [
        checks_by_code[code]
        for code in definition.completion_check_codes
        if code in checks_by_code
    ]
    missing_completion_checks = [
        code for code in definition.completion_check_codes if code not in checks_by_code
    ]
    status = _item_status(
        definition,
        completion_checks=completion_checks,
        missing_completion_checks=missing_completion_checks,
    )
    blocks_onboarding = required and status != "complete"
    item = {
        "id": definition.id,
        "title": definition.title,
        "category": definition.category,
        "required": required,
        "status": status,
        "blocks_onboarding": blocks_onboarding,
        "purpose": definition.purpose,
        "what_user_needs": list(definition.what_user_needs),
        "how_harness_validates": definition.how_harness_validates,
        "next_action": _next_action(definition, status=status, checks=relevant_checks, required=required),
        "doctor_check_codes": list(definition.doctor_check_codes),
        "secret_names": list(definition.secret_names),
        "compatible_clients": list(definition.compatible_clients),
        "setup_actions": [action.asdict() for action in definition.setup_actions],
        "notes": list(definition.notes),
        "validation": {
            "status": _validation_status(relevant_checks, missing_completion_checks=missing_completion_checks),
            "checks": [_summarize_check(check) for check in relevant_checks],
            "missing_check_codes": missing_completion_checks,
        },
    }
    if definition.id == "execution_substrate":
        item["execution_transport"] = _execution_transport_policy(relevant_checks)
    return item


def _execution_transport_policy(checks: list[dict[str, Any]]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for check in checks:
        raw_details = check.get("details")
        if isinstance(raw_details, dict):
            details.update(raw_details)

    return {
        "preferred_runner": str(details.get("preferred_runner") or "symphony"),
        "mode": str(details.get("mode") or "unknown"),
        "live_dispatch_enabled": bool(details.get("live_dispatch_enabled")),
        "completion_authority": str(details.get("completion_authority") or "harness_verification"),
        "runner_completion_is_truth": bool(details.get("runner_completion_is_truth")),
    }


def _item_status(
    definition: SetupItemDefinition,
    *,
    completion_checks: list[dict[str, Any]],
    missing_completion_checks: list[str],
) -> str:
    if missing_completion_checks:
        return "blocked" if definition.id == "local_runtime" else "incomplete"
    statuses = {str(check.get("status")) for check in completion_checks}
    if "fail" in statuses:
        return "blocked"
    if definition.id == "local_runtime":
        return "complete"
    if statuses == {"pass"}:
        return "complete"
    return "incomplete"


def _validation_status(
    checks: list[dict[str, Any]],
    *,
    missing_completion_checks: list[str],
) -> str:
    if missing_completion_checks:
        return "unknown"
    statuses = {str(check.get("status")) for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    if statuses == {"pass"}:
        return "pass"
    return "unknown"


def _next_action(
    definition: SetupItemDefinition,
    *,
    status: str,
    checks: list[dict[str, Any]],
    required: bool,
) -> str:
    if status == "complete":
        if definition.id == "local_runtime":
            return "No setup action is required to finish onboarding. Start Harness when live progress is needed."
        return "No action needed."

    failing_check = next((check for check in checks if check.get("status") == "fail"), None)
    if failing_check and failing_check.get("next_action"):
        return str(failing_check["next_action"])

    warning_check = next((check for check in checks if check.get("status") == "warn"), None)
    if warning_check and warning_check.get("next_action"):
        if required:
            return str(warning_check["next_action"])
        return f"Optional until a selected workflow requires it. {warning_check['next_action']}"

    if definition.setup_actions:
        action = definition.setup_actions[0]
        if action.command:
            return f"Run `{action.command}` or complete the equivalent app setup step."
        return action.description
    return "Open Harness setup and complete this item."


def _summarize_check(check: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "code": check.get("code"),
        "status": check.get("status"),
        "message": check.get("message"),
        "impact": check.get("impact"),
        "next_action": check.get("next_action"),
    }
    details = check.get("details")
    if isinstance(details, dict):
        summary["details"] = details
    return summary


def _item_by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    for item in items:
        if item.get("id") == item_id:
            return item
    raise LocalSetupError(f"Missing setup item {item_id!r}.")

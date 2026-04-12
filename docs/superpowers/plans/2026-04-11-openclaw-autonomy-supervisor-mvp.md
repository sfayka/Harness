# OpenClaw Autonomy Supervisor MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a canonical supervision queue that OpenClaw can poll to identify stale, blocked, review-gated, retryable, or invalid-proof tasks without rebuilding policy client-side.

**Architecture:** Add a new read-only supervision service that projects queue entries from existing read-models and timelines, then expose it via a new `GET /supervision/queue` endpoint. Reuse existing review, clarification, execution, and failure summaries so the queue remains a thin projection over canonical Harness truth.

**Tech Stack:** Python 3, existing `modules.api` HTTP server, existing `modules.read_model` surfaces, `unittest`

---

### Task 1: Add failing supervision service tests

**Files:**
- Create: `tests/test_supervision.py`
- Test: `tests/test_supervision.py`

- [ ] **Step 1: Write failing tests for queue classification**

```python
import unittest
from copy import deepcopy

from modules.api import HarnessApiService
from modules.store import FileBackedHarnessStore
from modules.supervision import HarnessSupervisionService
from tests.test_api import _completion_claim_payload, _execution_attempt_payload, _manual_happy_path_overlay_payload


class HarnessSupervisionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FileBackedHarnessStore(".tmp/test-supervision-store")
        self.api = HarnessApiService(store=self.store)
        self.service = HarnessSupervisionService(store=self.store, now_provider=lambda: "2026-04-12T12:00:00Z")

    def test_queue_surfaces_review_required_tasks(self) -> None:
        payload = {"request": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}
        status, created = self.api.submit(payload)
        self.assertEqual(status, 200)

        # Replace with a real review-required creation path during implementation.
        queue = self.service.list_attention_queue()

        self.assertEqual(queue[0]["attention_type"], "review_required")

    def test_queue_surfaces_invalid_execution_attempt_tasks(self) -> None:
        payload = {"request": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}
        status, created = self.api.submit(payload)
        self.assertEqual(status, 200)

        queue = self.service.list_attention_queue()

        self.assertEqual(queue[0]["attention_type"], "invalid_execution_attempt")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_supervision`
Expected: FAIL with `ModuleNotFoundError` or missing supervision service/test behavior.

- [ ] **Step 3: Replace placeholder setup in the tests with real canonical task scenarios**

```python
# Use existing API helpers and canonical flows to create:
# - a review-required task
# - a clarification-required task
# - a retryable blocked task
# - an invalid execution attempt task
# - a stale assigned task with old timestamps
```

- [ ] **Step 4: Re-run the tests and confirm they still fail for missing implementation**

Run: `python3 -m unittest tests.test_supervision`
Expected: FAIL because `HarnessSupervisionService` and/or queue behavior are not implemented yet.

- [ ] **Step 5: Commit**

```bash
git add tests/test_supervision.py
git commit -m "test: add supervision queue regressions"
```

### Task 2: Implement the supervision service

**Files:**
- Create: `modules/supervision.py`
- Modify: `modules/__init__.py`
- Test: `tests/test_supervision.py`

- [ ] **Step 1: Add the new service with queue-entry builders**

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from modules.read_model import HarnessReadModelService
from modules.store import HarnessStore, build_harness_store


def _parse_iso_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass(frozen=True)
class SupervisionQueueEntry:
    task_id: str
    title: str
    current_status: str
    attention_type: str
    suggested_action: str
    reason: str
    last_activity_at: str | None
    stale: bool
    review_status: str
    clarification_status: str
    failure_state: str
    retry_eligible: bool


class HarnessSupervisionService:
    def __init__(
        self,
        *,
        store: HarnessStore | None = None,
        now_provider: Callable[[], str] | None = None,
    ) -> None:
        self.read_model_service = HarnessReadModelService(store=store or build_harness_store())
        self._now_provider = now_provider
```

- [ ] **Step 2: Implement attention classification priority**

```python
    def _classify_attention(self, task: dict[str, Any]) -> tuple[str, str, str] | None:
        review_status = str((task.get("review_summary") or {}).get("status") or "none")
        clarification_status = str((task.get("clarification_summary") or {}).get("status") or "none")
        execution_summary = task.get("execution_summary") or {}
        failure_state = str((task.get("failure_summary") or {}).get("state") or "clear")
        latest_validation = (execution_summary.get("latest_attempt_validation") or {}) if isinstance(execution_summary, dict) else {}

        if str(task.get("current_status") or "") == "in_review" or review_status == "requested":
            return ("review_required", "resolve_review_gate", "Task has an active manual review gate.")
        if clarification_status == "required":
            return ("clarification_required", "collect_clarification", "Task is blocked on explicit clarification.")
        if latest_validation.get("failure_type") == "invalid_execution_attempt":
            return ("invalid_execution_attempt", "request_fresh_proof_or_rework", "Latest execution attempt failed the proof contract.")
        if bool(execution_summary.get("retry_eligible")) or failure_state == "retryable":
            return ("retryable_failure", "retry_or_redispatch", "Task is in a retryable failure state.")
        return None
```

- [ ] **Step 3: Implement last-activity and staleness logic**

```python
    def _last_activity_at(self, task: dict[str, Any]) -> str | None:
        timeline = task.get("timeline") or []
        events = [event for event in timeline if isinstance(event, dict)]
        if not events:
            return None
        latest = max(events, key=lambda event: (_parse_iso_timestamp(str(event.get("occurred_at") or "")), str(event.get("event_id") or "")))
        occurred_at = latest.get("occurred_at")
        return str(occurred_at) if occurred_at is not None else None
```

- [ ] **Step 4: Implement queue assembly**

```python
    def list_attention_queue(self) -> list[dict[str, Any]]:
        tasks = [asdict(item) for item in self.read_model_service.list_task_read_models()]
        queue: list[dict[str, Any]] = []
        for task in tasks:
            classification = self._classify_attention(task)
            if classification is None:
                continue
            attention_type, suggested_action, reason = classification
            queue.append(
                asdict(
                    SupervisionQueueEntry(
                        task_id=str(task["task_id"]),
                        title=str(task["title"]),
                        current_status=str(task["current_status"]),
                        attention_type=attention_type,
                        suggested_action=suggested_action,
                        reason=reason,
                        last_activity_at=self._last_activity_at(task),
                        stale=False,
                        review_status=str((task.get("review_summary") or {}).get("status") or "none"),
                        clarification_status=str((task.get("clarification_summary") or {}).get("status") or "none"),
                        failure_state=str((task.get("failure_summary") or {}).get("state") or "clear"),
                        retry_eligible=bool((task.get("execution_summary") or {}).get("retry_eligible")),
                    )
                )
            )
        return queue
```

- [ ] **Step 5: Run the tests and make them pass**

Run: `python3 -m unittest tests.test_supervision`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add modules/supervision.py modules/__init__.py tests/test_supervision.py
git commit -m "feat: add supervision queue service"
```

### Task 3: Expose the queue in the API

**Files:**
- Modify: `modules/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing API test**

```python
def test_api_exposes_supervision_queue_endpoint(self) -> None:
    status, payload = self._get_json("/supervision/queue")

    self.assertEqual(status, 200)
    self.assertIn("generated_at", payload)
    self.assertIn("queue", payload)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_api.HarnessApiHttpTests.test_api_exposes_supervision_queue_endpoint`
Expected: FAIL with `404` or missing route.

- [ ] **Step 3: Add service and route wiring**

```python
from modules.supervision import HarnessSupervisionService


class HarnessApiService:
    def __init__(...):
        ...
        self.supervision_service = HarnessSupervisionService(store=self.store)

    def get_supervision_queue(self) -> tuple[int, dict[str, Any]]:
        return HTTPStatus.OK, {
            "generated_at": _iso_now(),
            "queue": self.supervision_service.list_attention_queue(),
        }
```

- [ ] **Step 4: Add the GET route**

```python
if path_components == ("supervision", "queue"):
    status, payload = service.get_supervision_queue()
    self._write_json(status, payload)
    return
```

- [ ] **Step 5: Re-run the API test**

Run: `python3 -m unittest tests.test_api.HarnessApiHttpTests.test_api_exposes_supervision_queue_endpoint`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add modules/api.py tests/test_api.py
git commit -m "feat: expose supervision queue endpoint"
```

### Task 4: Add end-to-end queue semantics coverage

**Files:**
- Modify: `tests/e2e/runtime_harness.py`
- Create: `tests/e2e/test_control_plane_supervision_queue_flows.py`

- [ ] **Step 1: Add a runtime helper for the queue endpoint**

```python
def supervision_queue(self) -> tuple[int, dict]:
    return self.get_json("/supervision/queue")
```

- [ ] **Step 2: Write an end-to-end flow for review, clarification, retryable, and stale queue entries**

```python
def test_supervision_queue_surfaces_review_and_retry_attention(self) -> None:
    review = self.create_evaluate_scenario(...)
    retryable = self.create_evaluate_scenario(...)

    status, payload = self.supervision_queue()

    self.assertEqual(status, 200)
    tasks = {item["task_id"]: item for item in payload["queue"]}
    self.assertEqual(tasks[review.task_id]["attention_type"], "review_required")
    self.assertEqual(tasks[retryable.task_id]["attention_type"], "retryable_failure")
```

- [ ] **Step 3: Run the targeted e2e test and make it pass**

Run: `python3 -m unittest tests.e2e.test_control_plane_supervision_queue_flows`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/runtime_harness.py tests/e2e/test_control_plane_supervision_queue_flows.py
git commit -m "test: cover supervision queue control-plane flows"
```

### Task 5: Update docs and run full verification

**Files:**
- Modify: `docs/api/agent-api-usage.md`
- Modify: `docs/integrations/overview.md`
- Modify: `docs/architecture/openclaw-executor-adapter.md`

- [ ] **Step 1: Document the new canonical queue**

```md
- `GET /supervision/queue`: list tasks that currently need autonomous or operator attention.
```

- [ ] **Step 2: Document OpenClaw polling intent**

```md
OpenClaw should poll the supervision queue rather than infer stale or retryable states from raw task data.
```

- [ ] **Step 3: Run targeted verification**

Run: `python3 -m unittest tests.test_supervision tests.test_api tests.e2e.test_control_plane_supervision_queue_flows`
Expected: PASS

- [ ] **Step 4: Run full backend verification**

Run: `python3 -m unittest discover -s tests`
Expected: PASS with all existing suites green.

- [ ] **Step 5: Commit**

```bash
git add docs/api/agent-api-usage.md docs/integrations/overview.md docs/architecture/openclaw-executor-adapter.md
git commit -m "docs: describe supervision queue for autonomy MVP"
```

# Harness Verifier Reset V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local-first reset slice that verifies GitHub proof for Linear issues, writes canonical truth back into Linear, and triggers bounded OpenClaw repair without depending on the dashboard or the broad TaskEnvelope flow.

**Architecture:** Keep the existing TaskEnvelope control-plane routes intact, but add a parallel reset-specific service with its own contract store, verification engine, Linear/OpenClaw clients, and deterministic supervision tick endpoint. Use existing GitHub lookup patterns where they help, but make the reset slice explicit and small so it can ship before any larger repo cleanup.

**Tech Stack:** Python 3, FastAPI, file-backed JSON persistence, GitHub REST API, Linear GraphQL API, existing local OpenClaw bootstrap/config, `unittest`

---

## File Map

- `backend/server.py`
  Add reset-specific HTTP routes next to the existing API.

- `modules/reset/__init__.py`
  Reset slice package boundary.

- `modules/reset/contracts.py`
  Dataclasses and validation for verification contracts, completion claims, and verdicts.

- `modules/reset/store.py`
  File-backed persistence for reset contracts and event history.

- `modules/reset/github_verifier.py`
  Strict GitHub verification of repo, branch, commit SHA, and PR alignment.

- `modules/reset/linear_client.py`
  Thin Linear GraphQL client for issue state/substatus/comment updates.

- `modules/reset/openclaw_client.py`
  Thin HTTP client that sends repair requests to OpenClaw.

- `modules/reset/service.py`
  Orchestrates registration, completion claim handling, verdict evaluation, Linear updates, and supervision ticks.

- `modules/local_env.py`
  Lightweight local `.env.local` loader for local runtime convenience.

- `tests/reset/test_contracts.py`
  Validation tests for reset contract objects.

- `tests/reset/test_store.py`
  Persistence tests for reset contract state and event history.

- `tests/reset/test_github_verifier.py`
  GitHub proof validation tests with fake API responses.

- `tests/reset/test_service.py`
  End-to-end service tests covering registration, invalid proof, retries, review escalation, and verified completion.

- `tests/test_fastapi_backend.py`
  HTTP route coverage for the new reset endpoints.

- `README.md`
  Narrow product description and reset-slice local run instructions.

- `docs/setup/local-development.md`
  Add reset-slice local run/test instructions and `.env.local` autoload notes.

### Task 1: Add local `.env.local` autoload for native backend runs

**Files:**
- Create: `modules/local_env.py`
- Modify: `backend/server.py`
- Test: `tests/test_fastapi_backend.py`

- [ ] **Step 1: Write the failing backend env-loader tests**

```python
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from modules.local_env import load_local_env_file


class LocalEnvLoaderTests(unittest.TestCase):
    def test_loads_key_value_pairs_without_overwriting_existing_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env.local"
            env_path.write_text("FIRST=one\nSECOND=two\n", encoding="utf-8")

            os.environ["SECOND"] = "existing"
            self.addCleanup(lambda: os.environ.pop("SECOND", None))
            self.addCleanup(lambda: os.environ.pop("FIRST", None))

            loaded = load_local_env_file(env_path)

            self.assertEqual(loaded, ("FIRST",))
            self.assertEqual(os.environ["FIRST"], "one")
            self.assertEqual(os.environ["SECOND"], "existing")
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python3 -m unittest tests.test_fastapi_backend.LocalEnvLoaderTests -v`
Expected: FAIL because `modules.local_env` and `load_local_env_file` do not exist yet.

- [ ] **Step 3: Add the local env loader and call it during backend startup**

```python
from __future__ import annotations

import os
from pathlib import Path


def load_local_env_file(path: str | Path, *, override: bool = False) -> tuple[str, ...]:
    env_path = Path(path)
    if not env_path.exists():
        return ()

    loaded: list[str] = []
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if key in os.environ and not override:
            continue
        os.environ[key] = value
        loaded.append(key)
    return tuple(loaded)


def load_repo_root_env() -> tuple[str, ...]:
    repo_root = Path(__file__).resolve().parents[1]
    return load_local_env_file(repo_root / ".env.local")
```

```python
from modules.local_env import load_repo_root_env

load_repo_root_env()
```

- [ ] **Step 4: Re-run the focused backend test**

Run: `python3 -m unittest tests.test_fastapi_backend.LocalEnvLoaderTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/local_env.py backend/server.py tests/test_fastapi_backend.py
git commit -m "feat: autoload local Harness env file"
```

### Task 2: Add reset contract models and file-backed persistence

**Files:**
- Create: `modules/reset/__init__.py`
- Create: `modules/reset/contracts.py`
- Create: `modules/reset/store.py`
- Create: `tests/reset/test_contracts.py`
- Create: `tests/reset/test_store.py`

- [ ] **Step 1: Write the failing reset contract and store tests**

```python
from __future__ import annotations

import tempfile
import unittest

from modules.reset.contracts import (
    ResetCompletionClaim,
    ResetVerificationContract,
    ResetVerificationContractError,
)
from modules.reset.store import FileBackedResetStore


class ResetContractTests(unittest.TestCase):
    def test_contract_requires_linear_issue_and_repository(self) -> None:
        with self.assertRaises(ResetVerificationContractError):
            ResetVerificationContract(
                contract_id="",
                linear_issue_id="",
                repository_owner="",
                repository_name="",
                branch_ref="",
            )


class ResetStoreTests(unittest.TestCase):
    def test_round_trips_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileBackedResetStore(temp_dir)
            contract = ResetVerificationContract(
                contract_id="contract-1",
                linear_issue_id="KNO-999",
                repository_owner="sfayka",
                repository_name="Harness",
                branch_ref="main",
            )

            store.create_contract(contract)
            loaded = store.get_contract("contract-1")

            self.assertEqual(loaded.contract_id, "contract-1")
            self.assertEqual(loaded.linear_issue_id, "KNO-999")
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python3 -m unittest tests.reset.test_contracts tests.reset.test_store -v`
Expected: FAIL because the reset modules do not exist yet.

- [ ] **Step 3: Add the reset contract dataclasses and file-backed store**

```python
from __future__ import annotations

from dataclasses import dataclass, field


class ResetVerificationContractError(ValueError):
    pass


@dataclass(frozen=True)
class ResetCompletionClaim:
    repository_owner: str
    repository_name: str
    branch_name: str
    commit_sha: str
    pull_request_number: int | None = None
    pull_request_url: str | None = None


@dataclass(frozen=True)
class ResetVerificationContract:
    contract_id: str
    linear_issue_id: str
    repository_owner: str
    repository_name: str
    branch_ref: str
    retry_count: int = 0
    retry_budget: int = 2
    harness_status: str = "running"
    latest_claim: ResetCompletionClaim | None = None
    latest_verdict: str | None = None
    event_log: tuple[dict[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.contract_id.strip():
            raise ResetVerificationContractError("contract_id is required")
        if not self.linear_issue_id.strip():
            raise ResetVerificationContractError("linear_issue_id is required")
        if not self.repository_owner.strip() or not self.repository_name.strip():
            raise ResetVerificationContractError("repository owner/name are required")
        if not self.branch_ref.strip():
            raise ResetVerificationContractError("branch_ref is required")
```

```python
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .contracts import ResetVerificationContract


class FileBackedResetStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.contracts_dir = self.root_dir / "reset-contracts"
        self.contracts_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, contract_id: str) -> Path:
        return self.contracts_dir / f"{contract_id}.json"

    def create_contract(self, contract: ResetVerificationContract) -> ResetVerificationContract:
        path = self._path(contract.contract_id)
        if path.exists():
            raise ValueError(f"contract {contract.contract_id!r} already exists")
        path.write_text(json.dumps(asdict(contract), indent=2, sort_keys=True), encoding="utf-8")
        return contract

    def get_contract(self, contract_id: str) -> ResetVerificationContract:
        payload = json.loads(self._path(contract_id).read_text(encoding="utf-8"))
        return ResetVerificationContract(**payload)
```

- [ ] **Step 4: Re-run the focused reset tests**

Run: `python3 -m unittest tests.reset.test_contracts tests.reset.test_store -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/reset/__init__.py modules/reset/contracts.py modules/reset/store.py tests/reset/test_contracts.py tests/reset/test_store.py
git commit -m "feat: add reset verification contract store"
```

### Task 3: Add strict GitHub verification for repo, branch, commit, and PR alignment

**Files:**
- Create: `modules/reset/github_verifier.py`
- Create: `tests/reset/test_github_verifier.py`

- [ ] **Step 1: Write the failing GitHub verifier tests**

```python
from __future__ import annotations

import unittest

from modules.reset.github_verifier import ResetGitHubVerifier, ResetGitHubVerdict


class FakeGitHubClient:
    def __init__(self) -> None:
        self.branch_exists_result = True
        self.commit_exists_result = True
        self.pull_request_payload = {
            "number": 42,
            "html_url": "https://github.com/sfayka/Harness/pull/42",
            "state": "open",
            "head": {
                "ref": "codex/reset-verifier-v1",
                "sha": "abc123",
                "repo": {"owner": {"login": "sfayka"}, "name": "Harness"},
            },
        }


class ResetGitHubVerifierTests(unittest.TestCase):
    def test_returns_verified_done_for_matching_claim(self) -> None:
        verifier = ResetGitHubVerifier(client=FakeGitHubClient())

        verdict = verifier.verify(
            expected_owner="sfayka",
            expected_repo="Harness",
            expected_branch="codex/reset-verifier-v1",
            branch_name="codex/reset-verifier-v1",
            commit_sha="abc123",
            pull_request_number=42,
        )

        self.assertEqual(verdict.status, "verified_done")
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python3 -m unittest tests.reset.test_github_verifier -v`
Expected: FAIL because the verifier does not exist yet.

- [ ] **Step 3: Add a strict reset verifier**

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResetGitHubVerdict:
    status: str
    reason: str


class ResetGitHubVerifier:
    def __init__(self, client) -> None:
        self.client = client

    def verify(
        self,
        *,
        expected_owner: str,
        expected_repo: str,
        expected_branch: str,
        branch_name: str,
        commit_sha: str,
        pull_request_number: int,
    ) -> ResetGitHubVerdict:
        pull_request = self.client.get_pull_request(expected_owner, expected_repo, pull_request_number)
        if pull_request is None:
            return ResetGitHubVerdict("retryable_invalid_proof", "pull request does not exist")

        head = pull_request["head"]
        head_repo = head["repo"]
        if head_repo["owner"]["login"] != expected_owner or head_repo["name"] != expected_repo:
            return ResetGitHubVerdict("retryable_invalid_proof", "pull request points at the wrong repository")
        if head["ref"] != branch_name or branch_name != expected_branch:
            return ResetGitHubVerdict("retryable_invalid_proof", "pull request head branch does not match expected branch")
        if head["sha"] != commit_sha:
            return ResetGitHubVerdict("retryable_invalid_proof", "pull request head sha does not match claim")
        return ResetGitHubVerdict("verified_done", "github proof verified")
```

- [ ] **Step 4: Re-run the GitHub verifier tests**

Run: `python3 -m unittest tests.reset.test_github_verifier -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/reset/github_verifier.py tests/reset/test_github_verifier.py
git commit -m "feat: add strict reset github proof verifier"
```

### Task 4: Add Linear writeback, OpenClaw repair callback, and reset service orchestration

**Files:**
- Create: `modules/reset/linear_client.py`
- Create: `modules/reset/openclaw_client.py`
- Create: `modules/reset/service.py`
- Create: `tests/reset/test_service.py`

- [ ] **Step 1: Write the failing reset service tests**

```python
from __future__ import annotations

import tempfile
import unittest

from modules.reset.contracts import ResetCompletionClaim, ResetVerificationContract
from modules.reset.service import ResetVerificationService
from modules.reset.store import FileBackedResetStore


class FakeLinearClient:
    def __init__(self) -> None:
        self.actions = []

    def update_issue(self, issue_id: str, *, state: str | None, harness_status: str, comment: str) -> None:
        self.actions.append((issue_id, state, harness_status, comment))


class FakeOpenClawClient:
    def __init__(self) -> None:
        self.repairs = []

    def request_repair(self, issue_id: str, *, reason: str) -> None:
        self.repairs.append((issue_id, reason))


class FakeVerifier:
    def __init__(self, status: str, reason: str) -> None:
        self.status = status
        self.reason = reason

    def verify(self, **_: object):
        return type("Verdict", (), {"status": self.status, "reason": self.reason})()


class ResetVerificationServiceTests(unittest.TestCase):
    def test_invalid_proof_requests_repair_and_keeps_issue_in_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileBackedResetStore(temp_dir)
            linear = FakeLinearClient()
            openclaw = FakeOpenClawClient()
            service = ResetVerificationService(store=store, linear_client=linear, verifier=FakeVerifier("retryable_invalid_proof", "wrong sha"), openclaw_client=openclaw)

            contract = ResetVerificationContract(
                contract_id="contract-1",
                linear_issue_id="KNO-999",
                repository_owner="sfayka",
                repository_name="Harness",
                branch_ref="codex/reset-verifier-v1",
            )
            service.register_contract(contract)

            result = service.submit_claim(
                "contract-1",
                ResetCompletionClaim(
                    repository_owner="sfayka",
                    repository_name="Harness",
                    branch_name="codex/reset-verifier-v1",
                    commit_sha="bad",
                    pull_request_number=42,
                ),
            )

            self.assertEqual(result["status"], "retryable_invalid_proof")
            self.assertEqual(openclaw.repairs[0][0], "KNO-999")
            self.assertEqual(linear.actions[-1][1], "In Progress")
```

- [ ] **Step 2: Run the reset service tests and verify they fail**

Run: `python3 -m unittest tests.reset.test_service -v`
Expected: FAIL because the reset service and clients do not exist yet.

- [ ] **Step 3: Add the thin Linear client, OpenClaw repair client, and reset orchestration service**

```python
class ResetVerificationService:
    def __init__(self, *, store, linear_client, verifier, openclaw_client) -> None:
        self.store = store
        self.linear_client = linear_client
        self.verifier = verifier
        self.openclaw_client = openclaw_client

    def register_contract(self, contract):
        self.store.create_contract(contract)
        self.linear_client.update_issue(
            contract.linear_issue_id,
            state="In Progress",
            harness_status="running",
            comment="Harness verification contract registered.",
        )
        return contract

    def submit_claim(self, contract_id, claim):
        contract = self.store.get_contract(contract_id)
        verdict = self.verifier.verify(
            expected_owner=contract.repository_owner,
            expected_repo=contract.repository_name,
            expected_branch=contract.branch_ref,
            branch_name=claim.branch_name,
            commit_sha=claim.commit_sha,
            pull_request_number=claim.pull_request_number,
        )

        if verdict.status == "verified_done":
            self.linear_client.update_issue(
                contract.linear_issue_id,
                state="Done",
                harness_status="verified",
                comment=verdict.reason,
            )
            return {"status": "verified_done", "reason": verdict.reason}

        self.openclaw_client.request_repair(contract.linear_issue_id, reason=verdict.reason)
        self.linear_client.update_issue(
            contract.linear_issue_id,
            state="In Progress",
            harness_status="retrying",
            comment=verdict.reason,
        )
        return {"status": "retryable_invalid_proof", "reason": verdict.reason}
```

- [ ] **Step 4: Re-run the reset service tests**

Run: `python3 -m unittest tests.reset.test_service -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/reset/linear_client.py modules/reset/openclaw_client.py modules/reset/service.py tests/reset/test_service.py
git commit -m "feat: add reset verification service orchestration"
```

### Task 5: Expose reset HTTP endpoints and add a deterministic supervision tick

**Files:**
- Modify: `backend/server.py`
- Modify: `modules/reset/service.py`
- Modify: `tests/test_fastapi_backend.py`
- Modify: `README.md`
- Modify: `docs/setup/local-development.md`

- [ ] **Step 1: Write the failing reset HTTP route tests**

```python
def test_register_claim_and_tick_routes_round_trip(self) -> None:
    response = self.client.post(
        "/reset/contracts",
        json={
            "contract_id": "contract-1",
            "linear_issue_id": "KNO-999",
            "repository_owner": "sfayka",
            "repository_name": "Harness",
            "branch_ref": "codex/reset-verifier-v1",
        },
    )
    self.assertEqual(response.status_code, 201)

    claim = self.client.post(
        "/reset/contracts/contract-1/claims",
        json={
            "repository_owner": "sfayka",
            "repository_name": "Harness",
            "branch_name": "codex/reset-verifier-v1",
            "commit_sha": "abc123",
            "pull_request_number": 42,
        },
    )
    self.assertIn(claim.status_code, (200, 409, 422))
```

- [ ] **Step 2: Run the HTTP route tests and verify they fail**

Run: `python3 -m unittest tests.test_fastapi_backend.FastApiBackendTests -v`
Expected: FAIL because the reset routes do not exist yet.

- [ ] **Step 3: Add the reset HTTP routes and supervision tick path**

```python
@app.post("/reset/contracts")
async def register_reset_contract(request: Request) -> JSONResponse:
    payload = await request.json()
    return _json_response(reset_service.register_contract_http(payload))

@app.get("/reset/contracts")
def list_reset_contracts() -> JSONResponse:
    return _json_response(reset_service.list_contracts_http())

@app.get("/reset/contracts/{contract_id}")
def get_reset_contract(contract_id: str) -> JSONResponse:
    return _json_response(reset_service.get_contract_http(contract_id))

@app.post("/reset/contracts/{contract_id}/claims")
async def submit_reset_claim(contract_id: str, request: Request) -> JSONResponse:
    payload = await request.json()
    return _json_response(reset_service.submit_claim_http(contract_id, payload))

@app.post("/reset/tick")
async def run_reset_tick() -> JSONResponse:
    return _json_response(reset_service.tick_http())
```

- [ ] **Step 4: Run backend validation and the focused reset suite**

Run: `python3 -m unittest tests.reset.test_contracts tests.reset.test_store tests.reset.test_github_verifier tests.reset.test_service tests.test_fastapi_backend -v`
Expected: PASS

Run: `python3 -m unittest discover -s tests -p 'test_*.py'`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/server.py modules/reset/service.py tests/test_fastapi_backend.py README.md docs/setup/local-development.md
git commit -m "feat: expose reset verifier api"
```

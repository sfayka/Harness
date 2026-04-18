# Reset Verifier Next Test Steps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the reset verifier loop across local and hosted environments without tying the product to OpenClaw, Hermes, or any single desktop agent client.

**Architecture:** Run the next test sequence in layers. Start with deterministic local proof, then add live Linear and GitHub, then prove hosted repair reachability, then prove hosted end-to-end repair, and finally prove that a non-OpenClaw client can still use the canonical Harness boundaries. Keep the current `OPENCLAW_*` env names where the code requires them, but treat them as adapter wiring rather than product truth.

**Tech Stack:** Python `unittest`, FastAPI, local `uvicorn`, GitHub REST, Linear GraphQL, Vercel-hosted FastAPI service, current OpenClaw-shaped repair callback adapter, canonical Harness `/tasks`, `/reset/*`, `/sync/github`, and `/supervision/queue` routes

---

### Task 1: Reconfirm The Deterministic Local Reset Baseline

**Files:**
- Reference: `docs/setup/local-development.md`
- Test: `tests/test_reset_dryrun.py`
- Test: `tests/reset/test_service.py`
- Test: `tests/reset/test_scenarios.py`
- Test: `tests/reset/test_openclaw_client.py`

- [ ] **Step 1: Run the deterministic reset dry runs**

Run:

```bash
python3 -m modules.reset_dryrun success
python3 -m modules.reset_dryrun review
```

Expected:
- the success path ends in `verified_done`
- the review path ends in `needs_review`

- [ ] **Step 2: Run the focused reset verifier unit tests**

Run:

```bash
python3 -m unittest \
  tests.test_reset_dryrun \
  tests.reset.test_service \
  tests.reset.test_scenarios \
  tests.reset.test_openclaw_client -v
```

Expected:
- PASS across the reset dry-run, service, scenario, and repair-client tests

- [ ] **Step 3: Record any command drift immediately in the local-development doc**

Modify if needed:
- `docs/setup/local-development.md`

Change only if one of the commands above is wrong, stale, or missing a prerequisite.

### Task 2: Reconfirm The Local Live Smoke Against Linear And GitHub

**Files:**
- Reference: `docs/setup/local-development.md`
- Test: `tests/test_reset_live_smoke.py`
- Reference: `modules/reset_live_smoke.py`

- [ ] **Step 1: Prepare the required local environment**

Confirm these env vars exist in repo-root `.env.local`:

```bash
GITHUB_TOKEN=...
LINEAR_API_KEY=...
HARNESS_RESET_POLL_SECONDS=0
```

Expected:
- `GITHUB_TOKEN` and `LINEAR_API_KEY` are present
- `HARNESS_RESET_POLL_SECONDS=0` keeps the retry loop deterministic

- [ ] **Step 2: Run the gated live smoke**

Run:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v
```

Expected:
- happy path returns `verified_done`
- missing PR path returns `retryable_invalid_proof`
- wrong SHA path escalates to `needs_review`

- [ ] **Step 3: Capture the concrete external artifacts from the run**

Record:
- Linear issue identifiers
- GitHub branch names
- commit SHAs
- PR URLs

Expected:
- every live scenario has external proof, not just a test summary

### Task 3: Prove Hosted Repair Callback Reachability

**Files:**
- Reference: `docs/setup/vercel-neon.md`
- Reference: `modules/reset/openclaw_client.py`
- Test: `tests/test_fastapi_backend.py`

- [ ] **Step 1: Deploy or identify a Vercel preview with the reset slice enabled**

Confirm:

```bash
curl -sS https://<preview-host>/backend/health
```

Expected:
- `status` is healthy
- `store_backend` is `postgres` in the intended hosted path

- [ ] **Step 2: Point the hosted env at a real remote repair receiver**

Confirm these hosted env vars:

```bash
OPENCLAW_BASE_URL=https://<remote-repair-receiver>
OPENCLAW_REPAIR_ENDPOINT=/repair
OPENCLAW_REPAIR_BEARER_TOKEN=<token-if-required>
```

Expected:
- the receiver is remote-reachable from Vercel
- no loopback or laptop-only URL is used

- [ ] **Step 3: Submit an invalid hosted completion claim and verify the callback is attempted**

Use the hosted reset routes to create a contract and submit obviously invalid proof:

```bash
curl -sS -X POST https://<preview-host>/backend/reset/contracts \
  -H 'content-type: application/json' \
  -d '{"contract_id":"hosted-reset-callback-smoke","linear_issue_id":"KNO-TEST","repository_owner":"sfayka","repository_name":"HARNESS-DRYRUN","branch_ref":"codex/hosted-reset-callback-smoke"}'
```

Then submit a bad claim:

```bash
curl -sS -X POST https://<preview-host>/backend/reset/contracts/hosted-reset-callback-smoke/claims \
  -H 'content-type: application/json' \
  -d '{"repository_owner":"sfayka","repository_name":"HARNESS-DRYRUN","branch_name":"codex/hosted-reset-callback-smoke","commit_sha":"deadbeef","pull_request_number":999999,"pull_request_url":"https://github.com/sfayka/HARNESS-DRYRUN/pull/999999"}'
```

Expected:
- Harness does not silently idle
- the contract moves to `retrying` or `needs_review`
- the remote receiver logs one repair callback attempt

### Task 4: Prove Hosted End-To-End Remote Repair

**Files:**
- Reference: `docs/setup/vercel-neon.md`
- Reference: `modules/reset/service.py`
- Reference: `modules/reset_live_smoke.py`

- [ ] **Step 1: Run one hosted scenario that starts invalid and ends valid**

Sequence:
1. create a hosted reset contract
2. submit invalid proof
3. let the remote repair receiver trigger fresh work
4. submit or sync the corrected GitHub proof

Expected:
- first verdict is `retryable_invalid_proof`
- final verdict is `verified_done`
- Linear moves from `In Progress` to `Done`

- [ ] **Step 2: Preserve operator proof from the hosted run**

Record:
- hosted deployment URL
- Linear issue identifier
- final branch
- final commit SHA
- final PR URL

Expected:
- the hosted proof can be inspected later without rerunning the scenario

### Task 5: Prove The Canonical Client Boundary Is Brand-Agnostic

**Files:**
- Reference: `docs/api/agent-api-usage.md`
- Reference: `docs/architecture/system-context.md`
- Reference: `modules/connectors/openclaw_supervisor.py`

- [ ] **Step 1: Submit a planning-only task through the canonical task API using a non-OpenClaw client identity**

Use the canonical task contract with a Hermes-style origin:

```bash
curl -sS -X POST http://127.0.0.1:8000/tasks \
  -H 'content-type: application/json' \
  -d '{"request":{"acceptance_criteria_satisfied":false,"claimed_completion":false,"external_facts":{},"task_envelope":{"id":"task-hermes-boundary-smoke","title":"Hermes boundary smoke","description":"Validate brand-agnostic ingress through the canonical Harness boundary.","origin":{"source_system":"hermes","source_type":"ingress_request","source_id":"telegram:test:hermes-boundary-smoke","ingress_id":"hermes-boundary-smoke","ingress_name":"Hermes","requested_by":"Sean Fay via Hermes"},"status":"planned","timestamps":{"created_at":"2026-04-18T00:00:00Z","updated_at":"2026-04-18T00:00:00Z","completed_at":null},"status_history":[],"objective":{"summary":"Prove that a non-OpenClaw client can submit planning-only work through the canonical Harness API.","deliverable_type":"planning_validation","success_signal":"Harness persists the task with Hermes provenance and no OpenClaw-specific requirement."},"constraints":[{"type":"mode","description":"Planning-only ingress validation.","required":true}],"acceptance_criteria":[{"id":"ac-1","description":"Task is accepted through POST /tasks.","required":true}],"parent_task_id":null,"child_task_ids":[],"dependencies":[],"assigned_executor":null,"required_capabilities":[],"priority":"normal","artifacts":{"completion_evidence":{"notes":null,"policy":"deferred","required_artifact_types":[],"status":"deferred","validated_artifact_ids":[],"validated_at":null,"validation_method":"deferred","validator":null},"items":[]},"observability":{"errors":[],"execution_metadata":{},"retries":{"attempt_count":0,"last_retry_at":null,"max_attempts":0}},"extensions":{"hermes":{"agent_id":"hermes","platform":"telegram","channel":"dm","conversation_id":"hermes-boundary-smoke","message_id":"hermes-boundary-smoke","user_id":"telegram:test","submitted_at":"2026-04-18T00:00:00Z","purpose":"boundary smoke"}}}}}'
```

Expected:
- Harness accepts the task
- provenance is stored under `origin` and `extensions.hermes`
- no OpenClaw-specific route is required

- [ ] **Step 2: Poll the canonical inspection surfaces**

Run:

```bash
curl -sS http://127.0.0.1:8000/tasks/task-hermes-boundary-smoke/read-model
curl -sS http://127.0.0.1:8000/tasks/task-hermes-boundary-smoke/timeline
curl -sS http://127.0.0.1:8000/supervision/queue
```

Expected:
- read-model and timeline show canonical task truth
- the supervision queue remains the same generic surface regardless of client brand

- [ ] **Step 3: Write down any remaining OpenClaw-only assumptions that still block a Hermes or future-client swap**

Expected:
- a short list of actual code-level coupling, if any remains
- no vague architecture complaint without a concrete file or env var name

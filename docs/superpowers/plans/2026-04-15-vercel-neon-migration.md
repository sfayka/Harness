# Harness Vercel + Neon Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate Harness onto a single Vercel project using `Services`, Neon-backed Postgres, and a much simpler hosted deployment contract without changing canonical control-plane behavior.

**Architecture:** Add a thin FastAPI adapter around `HarnessApiService` for Vercel hosting, keep the Next.js dashboard as the web service, and make hosted backend resolution deterministic by deriving the API base from Vercel deployment context instead of requiring bespoke environment configuration. Treat Blob as provisioned-only in this slice unless a real hosted artifact consumer is identified; do not invent provider code without a concrete persistence surface.

**Tech Stack:** Python 3, FastAPI, Next.js 16, React 19, TypeScript 5, Node `node:test` via `tsx`, Vercel `experimentalServices`, Postgres via `DATABASE_URL`

---

## File Map

- `backend/server.py`
  Thin FastAPI adapter that exposes the existing `HarnessApiService` methods on HTTP routes suitable for Vercel hosting.

- `backend/requirements.txt`
  Explicit Python dependency file for the Vercel backend service entrypoint.

- `lib/harness-api-base.ts`
  Shared server-side helper that resolves the upstream Harness API base URL with a hosted default derived from `VERCEL_URL`.

- `app/api/harness/[...path]/route.ts`
  Next.js proxy route that should use the resolver helper instead of raw `HARNESS_API_BASE_URL` only.

- `vercel.json`
  Single-project service layout for `web` and `api`.

- `.env.example`
  Local-first environment contract. Hosted deployments should not require hand-entered API base configuration.

- `README.md`
  Top-level hosted deployment story and operator guidance.

- `docs/setup/local-development.md`
  Local runbook with the updated default backend entrypoint and hosted-path notes.

- `docs/setup/vercel-neon.md`
  New default hosted deployment runbook replacing the Render/Supabase path.

- `tests/frontend/harness-api-base.test.ts`
  Regression coverage for hosted/local API base resolution.

- `tests/test_fastapi_backend.py`
  Backend adapter regression coverage proving the FastAPI layer preserves canonical API behavior.

- `tests/test_hosted_deployment_contract.py`
  Config-level regression coverage for `vercel.json` and `.env.example`.

- `tests/test_hosted_docs.py`
  Documentation contract tests that prevent drift back to Render/Supabase as the default hosted story.

---

### Task 1: Make hosted API resolution deterministic

**Files:**
- Create: `lib/harness-api-base.ts`
- Create: `tests/frontend/harness-api-base.test.ts`
- Modify: `app/api/harness/[...path]/route.ts`
- Modify: `package.json`

- [ ] **Step 1: Write the failing frontend resolver tests**

```ts
import test from "node:test";
import assert from "node:assert/strict";

import { resolveHarnessApiBaseUrl } from "../../lib/harness-api-base";

test("prefers explicit HARNESS_API_BASE_URL and strips a trailing slash", () => {
  const resolved = resolveHarnessApiBaseUrl({
    HARNESS_API_BASE_URL: "https://api.example.com/",
    VERCEL_URL: "ignored.example.vercel.app",
  });

  assert.equal(resolved, "https://api.example.com");
});

test("derives the hosted backend url from VERCEL_URL when no override is set", () => {
  const resolved = resolveHarnessApiBaseUrl({
    VERCEL_URL: "harness-preview.vercel.app",
  });

  assert.equal(resolved, "https://harness-preview.vercel.app/backend");
});

test("returns null when neither local override nor hosted deployment context exists", () => {
  const resolved = resolveHarnessApiBaseUrl({});

  assert.equal(resolved, null);
});
```

- [ ] **Step 2: Run the frontend resolver tests and verify they fail**

Run: `pnpm exec tsx --test tests/frontend/harness-api-base.test.ts`
Expected: FAIL because `tsx` is not installed and `lib/harness-api-base.ts` does not exist yet.

- [ ] **Step 3: Add the frontend test runner and resolver helper**

```json
{
  "scripts": {
    "dev": "next dev --turbopack",
    "build": "next build",
    "start": "next start",
    "lint": "eslint .",
    "test:frontend": "tsx --test tests/frontend/**/*.test.ts"
  },
  "devDependencies": {
    "tsx": "^4.20.0"
  }
}
```

```ts
export const DEFAULT_VERCEL_BACKEND_ROUTE_PREFIX = "/backend";

function stripTrailingSlash(value: string): string {
  return value.replace(/\/$/, "");
}

export function resolveHarnessApiBaseUrl(
  env: Partial<Record<"HARNESS_API_BASE_URL" | "VERCEL_URL", string | undefined>>,
): string | null {
  const explicit = env.HARNESS_API_BASE_URL?.trim();
  if (explicit) {
    return stripTrailingSlash(explicit);
  }

  const vercelUrl = env.VERCEL_URL?.trim();
  if (vercelUrl) {
    return `https://${vercelUrl}${DEFAULT_VERCEL_BACKEND_ROUTE_PREFIX}`;
  }

  return null;
}
```

```ts
import { NextRequest, NextResponse } from "next/server";

import { resolveHarnessApiBaseUrl } from "@/lib/harness-api-base";

function getBaseUrl(): string | null {
  return resolveHarnessApiBaseUrl({
    HARNESS_API_BASE_URL: process.env.HARNESS_API_BASE_URL,
    VERCEL_URL: process.env.VERCEL_URL,
  });
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const baseUrl = getBaseUrl();
  if (!baseUrl) {
    return NextResponse.json(
      {
        error:
          "Harness API base URL could not be resolved. Set HARNESS_API_BASE_URL locally or deploy behind Vercel Services.",
      },
      { status: 503 },
    );
  }

  const params = await context.params;
  const upstreamPath = params.path.join("/");
  const upstreamUrl = new URL(`${baseUrl}/${upstreamPath}`);
  upstreamUrl.search = request.nextUrl.search;

  try {
    const upstreamResponse = await fetch(upstreamUrl, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });

    const body = await upstreamResponse.text();
    return new NextResponse(body, {
      status: upstreamResponse.status,
      headers: {
        "Content-Type":
          upstreamResponse.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: `Harness API proxy could not reach ${upstreamUrl.origin}: ${
          error instanceof Error ? error.message : "unknown error"
        }`,
      },
      { status: 502 },
    );
  }
}
```

- [ ] **Step 4: Re-run the frontend tests and the production build**

Run: `pnpm exec tsx --test tests/frontend/harness-api-base.test.ts`
Expected: PASS

Run: `pnpm build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add package.json pnpm-lock.yaml lib/harness-api-base.ts app/api/harness/[...path]/route.ts tests/frontend/harness-api-base.test.ts
git commit -m "feat: derive hosted Harness API base from Vercel context"
```

### Task 2: Add a thin FastAPI backend adapter for Vercel

**Files:**
- Create: `backend/__init__.py`
- Create: `backend/server.py`
- Create: `backend/requirements.txt`
- Create: `tests/test_fastapi_backend.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write the failing FastAPI backend tests**

```python
from __future__ import annotations

import tempfile
import unittest

from fastapi.testclient import TestClient

from backend.server import create_app
from modules.store import FileBackedHarnessStore
from tests.test_api import _request_payload


class FastApiBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FileBackedHarnessStore(self.temp_dir.name)
        self.client = TestClient(create_app(store=self.store))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_health_route_returns_canonical_health_payload(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertIn("store_backend", response.json())

    def test_submit_and_read_model_round_trip_through_fastapi_adapter(self) -> None:
        created = self.client.post("/tasks", json=_request_payload("accepted_completion"))
        self.assertEqual(created.status_code, 200)

        task_id = created.json()["task_envelope"]["id"]

        read_model = self.client.get(f"/tasks/{task_id}/read-model")
        self.assertEqual(read_model.status_code, 200)
        self.assertEqual(read_model.json()["task"]["task_id"], task_id)
```

- [ ] **Step 2: Run the backend adapter tests and verify they fail**

Run: `python -m unittest tests.test_fastapi_backend`
Expected: FAIL because `fastapi` is not installed and `backend/server.py` does not exist yet.

- [ ] **Step 3: Add the backend adapter dependencies and the FastAPI service entrypoint**

```txt
jsonschema==4.25.1
psycopg[binary]==3.2.10
fastapi==0.115.12
uvicorn==0.34.2
```

```txt
-r ../requirements.txt
```

```python
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from modules.api import HarnessApiService
from modules.store import HarnessStore


def _json_response(result: tuple[int, dict[str, Any]]) -> JSONResponse:
    status_code, payload = result
    return JSONResponse(status_code=int(status_code), content=payload)


def create_app(*, store: HarnessStore | None = None) -> FastAPI:
    service = HarnessApiService(store=store)
    app = FastAPI(title="Harness API", version="0.1.0")

    @app.get("/health")
    def health() -> JSONResponse:
        return _json_response(service.health())

    @app.get("/tasks")
    def list_tasks() -> JSONResponse:
        return _json_response(service.list_tasks())

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str) -> JSONResponse:
        return _json_response(service.get_task(task_id))

    @app.get("/tasks/{task_id}/read-model")
    def get_task_read_model(task_id: str) -> JSONResponse:
        return _json_response(service.get_task_read_model(task_id))

    @app.get("/tasks/{task_id}/timeline")
    def get_task_timeline(task_id: str) -> JSONResponse:
        return _json_response(service.get_task_timeline(task_id))

    @app.get("/supervision/queue")
    def get_supervision_queue() -> JSONResponse:
        return _json_response(service.get_supervision_queue())

    @app.post("/tasks")
    async def submit(request: Request) -> JSONResponse:
        payload = await request.json()
        return _json_response(service.submit(payload))

    @app.post("/tasks/{task_id}/reevaluate")
    async def reevaluate(task_id: str, request: Request) -> JSONResponse:
        payload = await request.json()
        return _json_response(service.reevaluate(task_id, payload))

    @app.post("/tasks/{task_id}/completion-claims")
    async def submit_completion_claim(task_id: str, request: Request) -> JSONResponse:
        payload = await request.json()
        return _json_response(service.submit_completion_claim(task_id, payload))

    @app.post("/tasks/{task_id}/dispatch")
    async def dispatch_task(task_id: str, request: Request) -> JSONResponse:
        payload = await request.json()
        return _json_response(service.dispatch_task(task_id, payload))

    @app.post("/ingress/manual")
    async def submit_manual_ingress(request: Request) -> JSONResponse:
        payload = await request.json()
        return _json_response(service.submit_manual_ingress(payload))

    @app.post("/ingress/linear")
    async def submit_linear_ingress(request: Request) -> JSONResponse:
        payload = await request.json()
        return _json_response(service.submit_linear_ingress(payload))

    @app.post("/ingress/openclaw")
    async def submit_openclaw_ingress(request: Request) -> JSONResponse:
        payload = await request.json()
        return _json_response(service.submit_openclaw_ingress(payload))

    @app.post("/sync/github")
    async def submit_github_sync(request: Request) -> JSONResponse:
        payload = await request.json()
        return _json_response(service.submit_github_sync(payload))

    @app.post("/evaluate")
    async def evaluate(request: Request) -> JSONResponse:
        payload = await request.json()
        return _json_response(service.evaluate(payload))

    return app


app = create_app()
```

- [ ] **Step 4: Re-run the backend adapter tests**

Run: `python -m unittest tests.test_fastapi_backend`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt backend/__init__.py backend/server.py backend/requirements.txt tests/test_fastapi_backend.py
git commit -m "feat: add FastAPI adapter for Vercel backend service"
```

### Task 3: Declare the single-project Vercel service contract

**Files:**
- Create: `tests/test_hosted_deployment_contract.py`
- Modify: `vercel.json`
- Modify: `.env.example`

- [ ] **Step 1: Write the failing deployment-contract tests**

```python
from __future__ import annotations

import json
import unittest
from pathlib import Path


class HostedDeploymentContractTests(unittest.TestCase):
    def test_vercel_json_declares_web_and_api_services(self) -> None:
        payload = json.loads(Path("vercel.json").read_text(encoding="utf-8"))

        services = payload["experimentalServices"]
        self.assertEqual(services["web"]["entrypoint"], ".")
        self.assertEqual(services["web"]["framework"], "nextjs")
        self.assertEqual(services["web"]["routePrefix"], "/")
        self.assertEqual(services["api"]["entrypoint"], "backend/server.py")
        self.assertEqual(services["api"]["framework"], "fastapi")
        self.assertEqual(services["api"]["routePrefix"], "/backend")

    def test_env_example_documents_local_override_only(self) -> None:
        env_example = Path(".env.example").read_text(encoding="utf-8")

        self.assertIn("HARNESS_API_BASE_URL=http://127.0.0.1:8000", env_example)
        self.assertIn("Hosted Vercel deployments derive the backend route automatically", env_example)
```

- [ ] **Step 2: Run the deployment-contract tests and verify they fail**

Run: `python -m unittest tests.test_hosted_deployment_contract`
Expected: FAIL because `vercel.json` does not yet declare `experimentalServices` and `.env.example` does not yet document hosted auto-derivation.

- [ ] **Step 3: Update the Vercel project config and local env example**

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "experimentalServices": {
    "web": {
      "entrypoint": ".",
      "framework": "nextjs",
      "routePrefix": "/"
    },
    "api": {
      "entrypoint": "backend/server.py",
      "framework": "fastapi",
      "routePrefix": "/backend"
    }
  }
}
```

```dotenv
# Local dashboard -> local API override.
HARNESS_API_BASE_URL=http://127.0.0.1:8000

# Hosted Vercel deployments derive the backend route automatically from VERCEL_URL and /backend.
# DATABASE_URL is injected by the Neon + Vercel integration in hosted environments.
# DATABASE_URL=postgresql://...
```

- [ ] **Step 4: Re-run the deployment-contract tests**

Run: `python -m unittest tests.test_hosted_deployment_contract`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vercel.json .env.example tests/test_hosted_deployment_contract.py
git commit -m "chore: declare single-project Vercel services contract"
```

### Task 4: Remove the old hosted deployment story from docs

**Files:**
- Create: `docs/setup/vercel-neon.md`
- Create: `tests/test_hosted_docs.py`
- Modify: `README.md`
- Modify: `docs/setup/local-development.md`
- Modify: `docs/demo/operator-walkthrough.md`
- Delete: `docs/setup/render-supabase.md`

- [ ] **Step 1: Write the failing documentation contract tests**

```python
from __future__ import annotations

import unittest
from pathlib import Path


class HostedDocsTests(unittest.TestCase):
    def test_readme_points_to_vercel_and_neon_as_the_default_hosted_story(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("Vercel Services", readme)
        self.assertIn("Neon", readme)
        self.assertNotIn("Render + Supabase Deployment", readme)

    def test_vercel_neon_runbook_exists_and_render_supabase_runbook_is_removed(self) -> None:
        self.assertTrue(Path("docs/setup/vercel-neon.md").exists())
        self.assertFalse(Path("docs/setup/render-supabase.md").exists())
```

- [ ] **Step 2: Run the documentation contract tests and verify they fail**

Run: `python -m unittest tests.test_hosted_docs`
Expected: FAIL because the repo still references the Render/Supabase hosted path.

- [ ] **Step 3: Rewrite the hosted setup docs around the single-project Vercel path**

```md
# Vercel + Neon Deployment

Use this mode when Harness should run as one Vercel project with:

- a `web` service for the Next.js dashboard
- an `api` service for the Python backend
- Neon-backed Postgres injected through Vercel

## Backend

The backend service entrypoint is `backend/server.py`.

Vercel injects `DATABASE_URL` from the attached Neon integration.

## Frontend

The dashboard does not require a hosted `HARNESS_API_BASE_URL` override when deployed behind the same Vercel project. It derives the backend route from the deployment URL and the `/backend` service prefix.

## Local override

`HARNESS_API_BASE_URL` remains a local-development override only.
```

```md
## Vercel Preview / Hosted Deployment

Harness now prefers a single-project Vercel deployment:

- dashboard served by the `web` service
- backend served by the `api` service
- Postgres provided by Neon through Vercel

Hosted deployments should not require a hand-entered `HARNESS_API_BASE_URL` when running behind the same Vercel project.
```

```md
- [`docs/setup/vercel-neon.md`](docs/setup/vercel-neon.md)
```

- [ ] **Step 4: Re-run the documentation contract tests**

Run: `python -m unittest tests.test_hosted_docs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md docs/setup/local-development.md docs/setup/vercel-neon.md docs/demo/operator-walkthrough.md tests/test_hosted_docs.py
git rm docs/setup/render-supabase.md
git commit -m "docs: replace Render and Supabase hosted runbook"
```

### Task 5: Run the full verification and smoke checks

**Files:**
- Modify: `README.md` (only if final command examples or notes still need alignment after verification)
- Modify: `docs/setup/local-development.md` (only if verification uncovers stale commands)

- [ ] **Step 1: Run the focused migration regression suite**

Run: `python -m unittest tests.test_fastapi_backend tests.test_hosted_deployment_contract tests.test_hosted_docs`
Expected: PASS

Run: `pnpm exec tsx --test tests/frontend/harness-api-base.test.ts`
Expected: PASS

- [ ] **Step 2: Run the full backend and frontend validation**

Run: `python -m unittest discover -s tests`
Expected: PASS

Run: `pnpm lint`
Expected: PASS

Run: `pnpm build`
Expected: PASS

- [ ] **Step 3: Run one local smoke test through the new backend entrypoint**

Run: `python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000`
Expected: Starts a local API on `http://127.0.0.1:8000`

Run in a second shell: `HARNESS_API_BASE_URL=http://127.0.0.1:8000 pnpm exec next dev --turbopack --hostname 127.0.0.1 --port 3000`
Expected: Dashboard loads and `app/api/harness/[...path]/route.ts` can reach the local API

- [ ] **Step 4: Record any command or doc fixes discovered by the smoke test**

```md
- If `uvicorn` invocation or local dashboard startup differs from the docs, update `README.md` and `docs/setup/local-development.md` immediately in the same change.
- Do not leave verification-only discoveries unstated.
```

- [ ] **Step 5: Commit**

```bash
git add README.md docs/setup/local-development.md
git commit -m "chore: finalize Vercel and Neon migration verification"
```

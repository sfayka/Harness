from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from modules.api import HarnessApiService
from modules.local_env import load_native_local_env
from modules.local_runtime import build_runtime_status_payload
from modules.reset.service import ResetVerificationService
from modules.store import HarnessStore

load_native_local_env()

DASHBOARD_ASSETS_DIR_ENV_VARS = ("PROOFLINE_DASHBOARD_ASSETS_DIR", "HARNESS_DASHBOARD_ASSETS_DIR")
TRACEBACK_FIELD_NAMES = {"exception", "stack", "stacktrace", "trace", "traceback"}


def _public_json_value(value: Any, *, field_name: str | None = None) -> Any:
    if field_name and field_name.lower() in TRACEBACK_FIELD_NAMES:
        return "omitted"
    if isinstance(value, dict):
        return {str(key): _public_json_value(item, field_name=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_public_json_value(item, field_name=field_name) for item in value]
    return value


def _json_response(result: tuple[int, dict[str, Any]]) -> JSONResponse:
    status_code, payload = result
    public_payload = _public_json_value(payload)
    # codeql[py/stack-trace-exposure] API payloads strip traceback-shaped fields above.
    return JSONResponse(status_code=int(status_code), content=public_payload)


class _UnavailableResetService:
    """Fail-closed reset adapter used when reset startup cannot succeed."""

    def _response(self) -> tuple[int, dict[str, Any]]:
        return 503, {
            "status": "unavailable",
            "message": "Reset verifier is unavailable in this runtime.",
            "reason": "Reset verifier startup failed. Check server logs and runtime configuration.",
        }

    def register_contract_http(self, _: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return self._response()

    def list_contracts_http(self) -> tuple[int, dict[str, Any]]:
        return self._response()

    def get_contract_http(self, __: str) -> tuple[int, dict[str, Any]]:
        return self._response()

    def submit_claim_http(self, __: str, _: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return self._response()

    def tick_http(self) -> tuple[int, dict[str, Any]]:
        return self._response()


def _build_reset_service(store: HarnessStore | None) -> ResetVerificationService:
    root_dir = getattr(store, "root_dir", None) if store is not None else None
    try:
        return ResetVerificationService.from_env(root_dir=root_dir)
    except (OSError, ValueError):
        return _UnavailableResetService()


def _resolve_dashboard_assets_dir() -> Path | None:
    configured = next(
        (
            value
            for env_var in DASHBOARD_ASSETS_DIR_ENV_VARS
            if (value := os.environ.get(env_var)) and value.strip()
        ),
        None,
    )
    if not configured or not configured.strip():
        return None
    assets_dir = Path(configured).expanduser()
    if not (assets_dir / "index.html").is_file():
        return None
    return assets_dir


def _mount_dashboard_assets(app: FastAPI) -> None:
    assets_dir = _resolve_dashboard_assets_dir()
    if assets_dir is None:
        return
    app.mount(
        "/dashboard",
        StaticFiles(directory=str(assets_dir), html=True),
        name="dashboard",
    )


def create_app(
    *,
    store: HarnessStore | None = None,
    reset_service: ResetVerificationService | None = None,
) -> FastAPI:
    service = HarnessApiService(store=store)
    reset_verifier = reset_service or _build_reset_service(store)
    app = FastAPI(title="Proofline API", version="0.1.0")

    @app.get("/health")
    def health() -> JSONResponse:
        return _json_response(service.health())

    @app.get("/runtime/status")
    def runtime_status() -> JSONResponse:
        _, health_payload = service.health()
        return JSONResponse(status_code=200, content=build_runtime_status_payload(health_payload))

    @app.get("/tasks")
    def list_tasks() -> JSONResponse:
        return _json_response(service.list_tasks())

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str) -> JSONResponse:
        return _json_response(service.get_task(task_id))

    @app.get("/tasks/{task_id}/evaluations")
    def get_evaluation_history(task_id: str) -> JSONResponse:
        return _json_response(service.get_evaluation_history(task_id))

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

    @app.post("/reset/contracts")
    async def register_reset_contract(request: Request) -> JSONResponse:
        payload = await request.json()
        return _json_response(reset_verifier.register_contract_http(payload))

    @app.get("/reset/contracts")
    def list_reset_contracts() -> JSONResponse:
        return _json_response(reset_verifier.list_contracts_http())

    @app.get("/reset/contracts/{contract_id}")
    def get_reset_contract(contract_id: str) -> JSONResponse:
        return _json_response(reset_verifier.get_contract_http(contract_id))

    @app.post("/reset/contracts/{contract_id}/claims")
    async def submit_reset_claim(contract_id: str, request: Request) -> JSONResponse:
        payload = await request.json()
        return _json_response(reset_verifier.submit_claim_http(contract_id, payload))

    @app.post("/reset/tick")
    def run_reset_tick() -> JSONResponse:
        return _json_response(reset_verifier.tick_http())

    _mount_dashboard_assets(app)

    return app


app = create_app()

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from modules.api import HarnessApiService
from modules.local_env import load_native_local_env
from modules.reset.service import ResetVerificationService
from modules.store import HarnessStore

load_native_local_env()


def _json_response(result: tuple[int, dict[str, Any]]) -> JSONResponse:
    status_code, payload = result
    return JSONResponse(status_code=int(status_code), content=payload)


def _build_reset_service(store: HarnessStore | None) -> ResetVerificationService:
    root_dir = getattr(store, "root_dir", None) if store is not None else None
    return ResetVerificationService.from_env(root_dir=root_dir)


def create_app(
    *,
    store: HarnessStore | None = None,
    reset_service: ResetVerificationService | None = None,
) -> FastAPI:
    service = HarnessApiService(store=store)
    reset_verifier = reset_service or _build_reset_service(store)
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

    return app


app = create_app()

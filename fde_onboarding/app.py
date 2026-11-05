"""FastAPI app. Tenant scoping: tenant-scoped routes require the
X-Tenant-Id header to match the path tenant id, otherwise 404 (a tenant
cannot even see that another tenant's progress exists).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .clock import ClockFn
from .flow import FLOW
from .service import ConflictError, NotFoundError, OnboardingService, ValidationFailed
from .store import Store


class TenantCreate(BaseModel):
    name: str = Field(min_length=1)
    tenant_id: str | None = None


class SubmitBody(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


def create_app(db_path: str | Path = "onboarding.db", clock: ClockFn | None = None) -> FastAPI:
    store = Store(db_path)
    svc = OnboardingService(store, clock=clock)
    app = FastAPI(title="fde-onboarding", version="0.1.0")
    app.state.service = svc
    app.state.store = store

    def scoped_tenant(tenant_id: str, x_tenant_id: str | None) -> str:
        if x_tenant_id is None or x_tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="tenant not found")
        return tenant_id

    @app.exception_handler(NotFoundError)
    async def _nf(_req: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def _conflict(_req: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValidationFailed)
    async def _validation(_req: Request, exc: ValidationFailed):
        return JSONResponse(
            status_code=400, content={"detail": str(exc), "progress": exc.progress}
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/flow/steps")
    def flow_steps():
        return {"steps": [s.to_dict() for s in FLOW]}

    @app.post("/tenants", status_code=201)
    def create_tenant(body: TenantCreate):
        tenant = svc.create_tenant(name=body.name, tenant_id=body.tenant_id)
        return {**tenant, "progress": svc.get_progress(tenant["id"])}

    @app.get("/tenants/{tenant_id}/steps")
    def tenant_steps(tenant_id: str, x_tenant_id: str | None = Header(default=None)):
        scoped_tenant(tenant_id, x_tenant_id)
        return svc.get_progress(tenant_id)

    @app.get("/tenants/{tenant_id}/progress")
    def progress(tenant_id: str, x_tenant_id: str | None = Header(default=None)):
        scoped_tenant(tenant_id, x_tenant_id)
        return svc.get_progress(tenant_id)

    @app.post("/tenants/{tenant_id}/steps/{step_id}/submit")
    def submit(
        tenant_id: str,
        step_id: str,
        body: SubmitBody,
        x_tenant_id: str | None = Header(default=None),
    ):
        scoped_tenant(tenant_id, x_tenant_id)
        return svc.submit_step(tenant_id, step_id, body.payload)

    @app.post("/tenants/{tenant_id}/steps/{step_id}/skip")
    def skip(tenant_id: str, step_id: str, x_tenant_id: str | None = Header(default=None)):
        scoped_tenant(tenant_id, x_tenant_id)
        return svc.skip_step(tenant_id, step_id)

    @app.get("/tenants/{tenant_id}/stats")
    def tenant_stats(tenant_id: str, x_tenant_id: str | None = Header(default=None)):
        scoped_tenant(tenant_id, x_tenant_id)
        p = svc.get_progress(tenant_id)
        return {
            "tenant_id": tenant_id,
            "ttfv_seconds": p["ttfv_seconds"],
            "completed_count": p["completed_count"],
            "current_step": p["current_step"],
        }

    @app.get("/stats")
    def stats():
        return svc.compute_stats()

    return app


app = create_app()

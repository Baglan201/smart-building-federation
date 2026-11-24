"""Application factory; each process opens only its own node directory."""

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from building_federation.models import (
    EmptyBody,
    HealthResult,
    SignedGrant,
    SignedRequest,
    UnlockResult,
)
from building_federation.service import Node, Rejected


def create_app(directory: Path) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Ignore environment proxies: all peer traffic is deliberately local.
        with httpx.Client(timeout=3.0, trust_env=False, follow_redirects=False) as client:
            app.state.node = Node(directory, client)
            yield

    app = FastAPI(title="Smart Building Federation", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def no_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Rejected)
    async def rejected_handler(request: Request, error: Rejected):
        return JSONResponse(status_code=error.status, content={"detail": error.code})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, error: RequestValidationError):
        # Pydantic's default details can echo input. Never echo a secret share/signature.
        return JSONResponse(status_code=422, content={"detail": "invalid_request_schema"})

    @app.get("/health", response_model=HealthResult)
    def health(request: Request):
        return HealthResult(node_id=request.app.state.node.node_id)

    @app.post("/v1/share", response_model=SignedGrant)
    def share(body: SignedRequest, request: Request):
        return request.app.state.node.grant_share(body)

    @app.post("/v1/unlock", response_model=UnlockResult)
    def unlock(body: EmptyBody, request: Request):
        return request.app.state.node.unlock()

    return app

"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from multi_agentic_rag.api import routes_coverage, routes_delta, routes_documents, routes_queries
from multi_agentic_rag.utils.diagnostics import run_diagnostics


def create_app() -> FastAPI:
    """Create the FastAPI app."""

    application = FastAPI(
        title="multi-agentic-rag",
        version="0.1.0",
        description="Local-first graph-based agentic RAG service boundary.",
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/doctor")
    def doctor() -> dict[str, list[dict[str, str]]]:
        return {"checks": [check.__dict__ for check in run_diagnostics()]}

    application.include_router(routes_documents.router)
    application.include_router(routes_queries.router)
    application.include_router(routes_delta.router)
    application.include_router(routes_coverage.router)
    return application


app = create_app()

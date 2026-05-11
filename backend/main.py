"""
kb-rag RAG Backend — FastAPI entry point.

Starts the web server and registers all route groups:
  /qa      → Q&A Flow (the main chatbot pipeline)
  /tasks   → Individual AI task APIs
  /search  → Raw search endpoints
  /manage  → CMS document management
  /health  → Kubernetes liveness/readiness probes
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from backend.api.management.router import router as management_router
from backend.api.qa_flow.router import router as qa_router
from backend.api.search_apis.router import router as search_router
from backend.api.task_apis.router import router as task_router
from backend.core.config import get_settings
from backend.core.limiter import limiter
from backend.pipeline.indexer import ensure_search_index

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs at startup: ensures the Azure AI Search index exists."""
    s = get_settings()
    if not s.content_safety_endpoint or not s.content_safety_key:
        logger.warning(
            "CONTENT_SAFETY_ENDPOINT / CONTENT_SAFETY_KEY not set — "
            "harmful content screening is disabled for this deployment"
        )
    await ensure_search_index()
    yield


def create_app() -> FastAPI:
    s = get_settings()

    app = FastAPI(
        title=s.app_name,
        version="1.0.0",
        description=(
            "KB RAG — General-purpose knowledge base Q&A powered by "
            "Azure OpenAI, Azure AI Search, Cosmos DB, and Redis."
        ),
        lifespan=lifespan,
        # Interactive docs only in debug mode — never expose in production
        docs_url="/docs" if s.debug else None,
        redoc_url="/redoc" if s.debug else None,
        openapi_url="/openapi.json" if s.debug else None,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(qa_router)
    app.include_router(task_router)
    app.include_router(search_router)
    app.include_router(management_router)

    @app.get("/health", tags=["Health"])
    async def health() -> dict:
        """Kubernetes liveness probe — returns 200 if the server is running."""
        return {"status": "healthy"}

    @app.get("/ready", tags=["Health"])
    async def readiness() -> dict:
        """Kubernetes readiness probe — verifies critical dependencies."""
        from backend.core.clients import get_redis_client
        redis = get_redis_client()
        await redis.ping()
        return {"status": "ready"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=get_settings().debug)

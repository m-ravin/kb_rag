"""
kb-rag RAG Backend — FastAPI entry point.

Starts the web server and registers all route groups:
  /qa      → Q&A Flow (the main chatbot pipeline)
  /tasks   → Individual AI task APIs
  /search  → Raw search endpoints
  /manage  → CMS document management
  /health  → Kubernetes liveness/readiness probes
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.management.router import router as management_router
from backend.api.qa_flow.router import router as qa_router
from backend.api.search_apis.router import router as search_router
from backend.api.task_apis.router import router as task_router
from backend.core.config import get_settings
from backend.pipeline.indexer import ensure_search_index


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs at startup: ensures the Azure AI Search index exists."""
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
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Tighten to specific origins in production
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

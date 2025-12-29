"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from provo.api.routes import assumptions, fragments, search
from provo.storage import init_database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize services on startup."""
    # Initialize database
    await init_database()
    yield
    # Cleanup (if needed) would go here


app = FastAPI(
    title="Provenance API",
    description="Capture the why behind your decisions",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "provenance"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


# Include routers
app.include_router(fragments.router, prefix="/api/fragments", tags=["fragments"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(assumptions.router, prefix="/api/assumptions", tags=["assumptions"])

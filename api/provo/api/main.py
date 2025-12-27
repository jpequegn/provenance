"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Provenance API",
    description="Capture the why behind your decisions",
    version="0.1.0",
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


# TODO: Add routers
# from provo.api.routes import fragments, search, decisions
# app.include_router(fragments.router, prefix="/api/fragments", tags=["fragments"])
# app.include_router(search.router, prefix="/api/search", tags=["search"])
# app.include_router(decisions.router, prefix="/api/decisions", tags=["decisions"])

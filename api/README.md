# Provenance API

Python FastAPI backend for Provenance - capture the why behind decisions.

## Setup

```bash
# Install dependencies
uv sync

# Run the API
uv run uvicorn provo.api.main:app --reload

# Run tests
uv run pytest
```

## Structure

```
provo/
├── api/         # FastAPI routes and endpoints
├── capture/     # Capture mechanisms for different sources
├── processing/  # AI processing pipeline
├── storage/     # SQLite and vector database
└── query/       # Query layer - search and retrieval
```

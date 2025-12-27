# Provenance (Provo)

A personal knowledge base that captures the *why* behind software decisions.

## Problem

Every day, we lose:
- The reasoning behind decisions in code
- Context about "temporary" workarounds that become permanent
- Understanding of what alternatives were considered and rejected
- Knowledge that walks out the door when people leave

## Solution

Provenance combines **ambient capture** from multiple sources with **quick active capture**, processing everything into a queryable graph of decisions, assumptions, and context.

```
┌─────────────────────────────────────────────────────────────┐
│                      CAPTURE LAYER                          │
├─────────────┬─────────────┬─────────────┬──────────────────┤
│ Quick CLI   │ Zoom        │ Teams       │ Notes folder     │
│ (active)    │ transcripts │ webhooks    │ watcher          │
└─────────────┴─────────────┴─────────────┴──────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              PROCESSING → STORAGE → QUERY                   │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Capture a decision
provo "chose Redis for sessions because we need sub-ms latency"

# Search your context
provo search "why did we choose Redis?"

# View all decisions
provo decisions --last 7d

# Start the web UI
provo serve
```

## Architecture

- **CLI**: TypeScript + Bun + Commander.js
- **API**: Python + FastAPI
- **Storage**: SQLite + ChromaDB (vectors)
- **AI**: Ollama (local-first) with cloud fallback
- **Web UI**: React + Vite

## Project Structure

```
provenance/
├── cli/                    # TypeScript CLI
├── api/                    # Python FastAPI backend
├── web/                    # React web interface
├── data/                   # Local data (gitignored)
└── docs/                   # Documentation
```

## Development

### Prerequisites

- [Bun](https://bun.sh) (for CLI)
- [Python 3.11+](https://python.org) with [uv](https://github.com/astral-sh/uv)
- [Ollama](https://ollama.com) with `nomic-embed-text` and `llama3.2` models

### Setup

```bash
# Clone the repo
git clone https://github.com/jpequegn/provenance.git
cd provenance

# Install CLI dependencies
cd cli && bun install

# Install API dependencies
cd ../api && uv sync

# Pull Ollama models
ollama pull nomic-embed-text
ollama pull llama3.2

# Start the API
cd api && uv run uvicorn provo.api.main:app --reload

# Use the CLI
cd cli && bun run provo --help
```

## Status

🚧 **In Development** - See [Issues](https://github.com/jpequegn/provenance/issues) for current progress.

## License

MIT

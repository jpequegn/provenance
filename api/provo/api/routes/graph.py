"""Graph visualization API endpoints."""

from collections import Counter
from datetime import datetime

from fastapi import APIRouter

from provo.api.schemas import GraphDataResponse, GraphEdge, GraphNode
from provo.storage import SourceType, get_database

router = APIRouter()


def truncate_text(text: str, max_length: int = 60) -> str:
    """Truncate text to max length with ellipsis."""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


@router.get(
    "",
    response_model=GraphDataResponse,
    responses={
        200: {"description": "Graph data retrieved successfully"},
    },
)
async def get_graph_data(
    project: str | None = None,
    source_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 500,
) -> GraphDataResponse:
    """Get graph data for visualization.

    Returns nodes (fragments) and edges (links) in a format suitable
    for graph visualization libraries.

    Args:
        project: Filter by project name.
        source_type: Filter by source type (quick_capture, zoom, teams, notes).
        since: Only include fragments captured after this time.
        until: Only include fragments captured before this time.
        limit: Maximum number of fragments to include.
    """
    db = get_database()

    # Parse source_type if provided
    source_type_enum = None
    if source_type:
        try:
            source_type_enum = SourceType(source_type.lower())
        except ValueError:
            pass  # Ignore invalid source type

    # Get fragments
    fragments = await db.list_fragments(
        project=project,
        source_type=source_type_enum,
        since=since,
        until=until,
        limit=limit,
    )

    # Get all links
    links = await db.list_links(limit=5000)

    # Build set of fragment IDs for quick lookup
    fragment_ids = {str(f.id) for f in fragments}

    # Count connections per fragment
    connection_counts: Counter[str] = Counter()
    for link in links:
        source_id = str(link.source_id)
        target_id = str(link.target_id)
        if source_id in fragment_ids:
            connection_counts[source_id] += 1
        if target_id in fragment_ids:
            connection_counts[target_id] += 1

    # Build nodes
    nodes = [
        GraphNode(
            id=str(f.id),
            label=truncate_text(f.raw_content),
            source_type=f.source_type,
            project=f.project,
            captured_at=f.captured_at,
            topics=f.topics,
            connections=connection_counts[str(f.id)],
        )
        for f in fragments
    ]

    # Build edges (only include edges where both nodes are in our set)
    edges = [
        GraphEdge(
            id=str(link.id),
            source=str(link.source_id),
            target=str(link.target_id),
            link_type=link.link_type.value,
            strength=link.strength,
        )
        for link in links
        if str(link.source_id) in fragment_ids and str(link.target_id) in fragment_ids
    ]

    return GraphDataResponse(nodes=nodes, edges=edges)

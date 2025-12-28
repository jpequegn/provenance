"""Semantic search API endpoint."""

from fastapi import APIRouter, HTTPException, Query, status

from provo.api.schemas import SearchResponse, SearchResultItem
from provo.processing import get_embedding_service
from provo.storage import get_database, get_vector_store

router = APIRouter()


def cosine_distance_to_similarity(distance: float) -> float:
    """Convert cosine distance to similarity score.

    ChromaDB returns cosine distance (0 = identical, 2 = opposite).
    We convert to similarity score (1 = identical, 0 = orthogonal).
    """
    # Cosine distance = 1 - cosine_similarity
    # So cosine_similarity = 1 - cosine_distance
    # Clamp to [0, 1] range
    similarity = 1.0 - distance
    return max(0.0, min(1.0, similarity))


@router.get(
    "",
    response_model=SearchResponse,
    responses={
        200: {"description": "Search results returned successfully"},
        400: {"description": "Invalid or empty query"},
        503: {"description": "Embedding service unavailable"},
    },
)
async def search_fragments(
    q: str = Query(
        ...,
        min_length=1,
        description="Natural language search query",
        examples=["why did we choose postgres", "authentication decisions"],
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of results to return",
    ),
    project: str | None = Query(
        default=None,
        description="Filter results by project name",
    ),
) -> SearchResponse:
    """Search fragments by semantic similarity.

    This endpoint:
    1. Embeds the query text using the embedding service
    2. Searches ChromaDB for similar fragment embeddings
    3. Fetches full fragment details from SQLite
    4. Returns ranked results with similarity scores

    Results are ordered by similarity score (highest first).
    """
    # Get services
    embedding_service = get_embedding_service()
    vector_store = get_vector_store()
    db = get_database()

    try:
        # Generate embedding for the query
        embedding_result = await embedding_service.embed(q)
        query_vector = embedding_result.vector

        # Build metadata filter if project specified
        where_filter: dict[str, str] | None = None
        if project:
            where_filter = {"project": project}

        # Search for similar fragments
        search_results = await vector_store.search_similar(
            query_vector=query_vector,
            limit=limit,
            where=where_filter,
        )

        # Fetch full fragment details and build response
        result_items: list[SearchResultItem] = []

        for search_result in search_results:
            fragment = await db.get_fragment(search_result.fragment_id)

            if fragment is None:
                # Fragment was deleted but embedding still exists
                # This shouldn't happen with proper cleanup, but handle gracefully
                continue

            # Convert distance to similarity score
            score = cosine_distance_to_similarity(search_result.distance)

            # Build result item with score
            result_items.append(
                SearchResultItem(
                    id=fragment.id,
                    raw_content=fragment.raw_content,
                    summary=fragment.summary,
                    score=score,
                    source_type=fragment.source_type,
                    source_ref=fragment.source_ref,
                    captured_at=fragment.captured_at,
                    topics=fragment.topics,
                    project=fragment.project,
                )
            )

        return SearchResponse(query=q, results=result_items)

    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service unavailable: {e}",
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {e}",
        ) from e

"""Fragment capture API endpoints."""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from provo.api.schemas import FragmentCreateRequest, FragmentResponse
from provo.processing import (
    get_assumption_extractor,
    get_decision_extractor,
    get_embedding_service,
)
from provo.storage import ContextFragment, SourceType, get_database, get_vector_store

logger = logging.getLogger(__name__)

router = APIRouter()


async def extract_decisions_background(fragment_id: str, content: str) -> None:
    """Background task to extract decisions from fragment content.

    This runs asynchronously after the fragment is created and stored.
    Failures are logged but don't affect the main request.
    """
    from uuid import UUID

    try:
        db = get_database()
        extractor = get_decision_extractor()

        # Extract decisions using LLM
        result = await extractor.extract_decisions(
            content=content,
            fragment_id=UUID(fragment_id),
            min_confidence=0.5,
        )

        # Store each decision in the database
        for decision in result.decisions:
            await db.create_decision(decision)
            logger.info(
                f"Stored decision for fragment {fragment_id}: {decision.what[:50]}..."
            )

        logger.info(
            f"Decision extraction complete for {fragment_id}: "
            f"{len(result.decisions)} decisions stored"
        )

    except Exception as e:
        # Log but don't raise - this is a background task
        logger.error(f"Failed to extract decisions for fragment {fragment_id}: {e}")


async def extract_assumptions_background(fragment_id: str, content: str) -> None:
    """Background task to extract assumptions from fragment content.

    This runs asynchronously after the fragment is created and stored.
    Failures are logged but don't affect the main request.
    """
    from uuid import UUID

    try:
        db = get_database()
        extractor = get_assumption_extractor()

        # Extract assumptions using LLM
        result = await extractor.extract_assumptions(
            content=content,
            fragment_id=UUID(fragment_id),
        )

        # Store each assumption in the database
        for assumption in result.assumptions:
            await db.create_assumption(assumption)
            logger.info(
                f"Stored assumption for fragment {fragment_id}: "
                f"{assumption.statement[:50]}..."
            )

        logger.info(
            f"Assumption extraction complete for {fragment_id}: "
            f"{len(result.assumptions)} assumptions stored"
        )

    except Exception as e:
        # Log but don't raise - this is a background task
        logger.error(f"Failed to extract assumptions for fragment {fragment_id}: {e}")


@router.post(
    "",
    response_model=FragmentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Fragment created successfully"},
        400: {"description": "Invalid request data"},
        503: {"description": "Service unavailable (database or embedding service error)"},
    },
)
async def create_fragment(
    request: FragmentCreateRequest,
    background_tasks: BackgroundTasks,
) -> FragmentResponse:
    """Create a new context fragment.

    This endpoint:
    1. Validates the request data
    2. Creates the fragment in SQLite
    3. Generates an embedding for the content
    4. Stores the embedding in ChromaDB for semantic search
    5. Triggers async decision and assumption extraction (background)

    The fragment is immediately searchable after creation.
    Decision and assumption extraction run in the background and don't block the response.
    """
    # Get services
    db = get_database()
    embedding_service = get_embedding_service()
    vector_store = get_vector_store()

    # Convert source_type to enum if it's a string
    source_type = (
        request.source_type
        if isinstance(request.source_type, SourceType)
        else SourceType(request.source_type)
    )

    # Create the fragment model
    fragment = ContextFragment(
        raw_content=request.content,
        project=request.project,
        topics=request.topics,
        source_type=source_type,
        source_ref=request.source_ref,
        participants=request.participants,
    )

    try:
        # Store in SQLite
        created_fragment = await db.create_fragment(fragment)

        # Generate embedding
        embedding_result = await embedding_service.embed(request.content)

        # Build metadata for vector store (only include non-None values)
        metadata: dict[str, str | int | float | bool] = {}
        if request.project:
            metadata["project"] = request.project
        if source_type:
            metadata["source_type"] = source_type.value

        # Store embedding in ChromaDB
        await vector_store.add_embedding(
            fragment_id=created_fragment.id,
            vector=embedding_result.vector,
            metadata=metadata if metadata else None,
        )

        # Schedule decision and assumption extraction as background tasks
        background_tasks.add_task(
            extract_decisions_background,
            str(created_fragment.id),
            request.content,
        )
        background_tasks.add_task(
            extract_assumptions_background,
            str(created_fragment.id),
            request.content,
        )

        return FragmentResponse.model_validate(created_fragment)

    except ConnectionError as e:
        # Embedding service unavailable
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service unavailable: {e}",
        ) from e
    except Exception as e:
        # Log the error for debugging
        # In production, use proper logging
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create fragment: {e}",
        ) from e


@router.get(
    "/{fragment_id}",
    response_model=FragmentResponse,
    responses={
        200: {"description": "Fragment retrieved successfully"},
        404: {"description": "Fragment not found"},
    },
)
async def get_fragment(fragment_id: str) -> FragmentResponse:
    """Get a fragment by ID."""
    from uuid import UUID

    db = get_database()

    try:
        uuid_id = UUID(fragment_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid fragment ID format",
        ) from e

    fragment = await db.get_fragment(uuid_id)

    if fragment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fragment not found",
        )

    return FragmentResponse.model_validate(fragment)


@router.get(
    "",
    response_model=list[FragmentResponse],
    responses={
        200: {"description": "Fragments retrieved successfully"},
    },
)
async def list_fragments(
    project: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[FragmentResponse]:
    """List fragments with optional filtering."""
    db = get_database()

    fragments = await db.list_fragments(
        project=project,
        limit=limit,
        offset=offset,
    )

    return [FragmentResponse.model_validate(f) for f in fragments]


@router.delete(
    "/{fragment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Fragment deleted successfully"},
        404: {"description": "Fragment not found"},
    },
)
async def delete_fragment(fragment_id: str) -> None:
    """Delete a fragment by ID.

    Also removes the embedding from the vector store.
    """
    from uuid import UUID

    db = get_database()
    vector_store = get_vector_store()

    try:
        uuid_id = UUID(fragment_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid fragment ID format",
        ) from e

    # Delete from database
    deleted = await db.delete_fragment(uuid_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fragment not found",
        )

    # Also remove from vector store
    await vector_store.delete_embedding(uuid_id)

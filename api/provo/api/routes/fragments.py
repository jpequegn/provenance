"""Fragment capture API endpoints."""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from provo.api.schemas import (
    FragmentCreateRequest,
    FragmentLinkRequest,
    FragmentLinkResponse,
    FragmentResponse,
    FragmentUpdateRequest,
    RelatedFragmentItem,
    RelatedFragmentsResponse,
)
from provo.processing import (
    get_assumption_extractor,
    get_decision_extractor,
    get_embedding_service,
)
from provo.storage import (
    ContextFragment,
    FragmentLink,
    LinkType,
    SourceType,
    get_database,
    get_vector_store,
)

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


# Similarity threshold for creating RELATES_TO links
SIMILARITY_THRESHOLD = 0.75


async def link_similar_fragments_background(
    fragment_id: str,
    embedding_vector: list[float],
) -> None:
    """Background task to find and link semantically similar fragments.

    This runs asynchronously after the fragment is created and stored.
    Failures are logged but don't affect the main request.
    """
    from uuid import UUID

    try:
        db = get_database()
        vector_store = get_vector_store()

        # Search for similar fragments (excluding self)
        # ChromaDB uses cosine distance, so lower = more similar
        # Cosine distance = 1 - cosine similarity
        # For threshold 0.75 similarity, we want distance < 0.25
        similar_results = await vector_store.search_similar(
            query_vector=embedding_vector,
            limit=10,  # Check up to 10 candidates
        )

        fragment_uuid = UUID(fragment_id)
        links_created = 0

        for result in similar_results:
            # Skip self
            if result.fragment_id == fragment_uuid:
                continue

            # Check if similarity is above threshold
            # Distance is cosine distance, so similarity = 1 - distance
            similarity = 1.0 - result.distance
            if similarity < SIMILARITY_THRESHOLD:
                continue

            # Create bidirectional RELATES_TO link
            link = FragmentLink(
                source_id=fragment_uuid,
                target_id=result.fragment_id,
                link_type=LinkType.RELATES_TO,
                strength=similarity,
            )
            await db.create_link(link)
            links_created += 1

            logger.info(
                f"Linked fragment {fragment_id} to {result.fragment_id} "
                f"with similarity {similarity:.2f}"
            )

        logger.info(
            f"Fragment linking complete for {fragment_id}: "
            f"{links_created} links created"
        )

    except Exception as e:
        # Log but don't raise - this is a background task
        logger.error(f"Failed to link similar fragments for {fragment_id}: {e}")


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

        # Schedule fragment linking based on semantic similarity
        background_tasks.add_task(
            link_similar_fragments_background,
            str(created_fragment.id),
            embedding_result.vector,
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
    "/{fragment_id}/related",
    response_model=RelatedFragmentsResponse,
    responses={
        200: {"description": "Related fragments retrieved successfully"},
        400: {"description": "Invalid fragment ID format"},
        404: {"description": "Fragment not found"},
    },
)
async def get_related_fragments(
    fragment_id: str,
    link_type: str | None = None,
    limit: int = 20,
) -> RelatedFragmentsResponse:
    """Get fragments related to a given fragment.

    Returns fragments that are semantically similar or otherwise linked
    to the specified fragment.

    Args:
        fragment_id: The ID of the fragment to find related content for.
        link_type: Optional filter by link type (relates_to, references, etc.).
        limit: Maximum number of related fragments to return.
    """
    from uuid import UUID

    db = get_database()

    try:
        uuid_id = UUID(fragment_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid fragment ID format",
        ) from e

    # Check that the fragment exists
    fragment = await db.get_fragment(uuid_id)
    if fragment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fragment not found",
        )

    # Parse link type if provided
    link_type_enum = None
    if link_type:
        try:
            link_type_enum = LinkType(link_type.lower())
        except ValueError as e:
            valid_types = [t.value for t in LinkType]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid link type: {link_type}. Valid types: {valid_types}",
            ) from e

    # Get related fragments
    related_results = await db.get_related_fragments(
        fragment_id=uuid_id,
        link_type=link_type_enum,
    )

    # Limit results
    related_results = related_results[:limit]

    # Build response
    related_items = [
        RelatedFragmentItem(
            id=frag.id,
            content=frag.raw_content,
            summary=frag.summary,
            strength=strength,
            link_type=frag_link_type.value,
            source_type=frag.source_type,
            source_ref=frag.source_ref,
            captured_at=frag.captured_at,
            topics=frag.topics,
            project=frag.project,
        )
        for frag, strength, frag_link_type in related_results
    ]

    return RelatedFragmentsResponse(
        fragment_id=uuid_id,
        related=related_items,
    )


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


@router.patch(
    "/{fragment_id}",
    response_model=FragmentResponse,
    responses={
        200: {"description": "Fragment updated successfully"},
        400: {"description": "Invalid request data"},
        404: {"description": "Fragment not found"},
    },
)
async def update_fragment(
    fragment_id: str,
    request: FragmentUpdateRequest,
) -> FragmentResponse:
    """Update a fragment's metadata (project, topics, summary).

    Only the fields provided in the request will be updated.
    """
    from uuid import UUID

    db = get_database()

    try:
        uuid_id = UUID(fragment_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid fragment ID format",
        ) from e

    # Get existing fragment
    fragment = await db.get_fragment(uuid_id)
    if fragment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fragment not found",
        )

    # Update only provided fields
    if request.project is not None:
        fragment.project = request.project
    if request.topics is not None:
        fragment.topics = request.topics
    if request.summary is not None:
        fragment.summary = request.summary

    # Save updates
    updated_fragment = await db.update_fragment(fragment)

    return FragmentResponse.model_validate(updated_fragment)


@router.post(
    "/{fragment_id}/links",
    response_model=FragmentLinkResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Link created successfully"},
        400: {"description": "Invalid request data"},
        404: {"description": "Fragment not found"},
    },
)
async def create_fragment_link(
    fragment_id: str,
    request: FragmentLinkRequest,
) -> FragmentLinkResponse:
    """Create a manual link between two fragments.

    This allows users to explicitly link related fragments
    that may not have been automatically connected.
    """
    from uuid import UUID

    db = get_database()

    try:
        source_uuid = UUID(fragment_id)
        target_uuid = UUID(request.target_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid fragment ID format",
        ) from e

    # Check both fragments exist
    source_fragment = await db.get_fragment(source_uuid)
    if source_fragment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source fragment not found",
        )

    target_fragment = await db.get_fragment(target_uuid)
    if target_fragment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target fragment not found",
        )

    # Parse link type
    try:
        link_type_enum = LinkType(request.link_type.lower())
    except ValueError as e:
        valid_types = [t.value for t in LinkType]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid link type: {request.link_type}. Valid types: {valid_types}",
        ) from e

    # Create the link
    link = FragmentLink(
        source_id=source_uuid,
        target_id=target_uuid,
        link_type=link_type_enum,
        strength=request.strength,
    )

    created_link = await db.create_link(link)

    return FragmentLinkResponse(
        id=created_link.id,
        source_id=created_link.source_id,
        target_id=created_link.target_id,
        link_type=created_link.link_type.value,
        strength=created_link.strength,
        created_at=created_link.created_at,
    )


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

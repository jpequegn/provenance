"""Assumptions API endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from provo.storage import get_database

router = APIRouter()


class InvalidateAssumptionRequest(BaseModel):
    """Request body for invalidating an assumption."""

    invalidated_by: str  # Fragment ID that invalidates this assumption


class AssumptionResponse(BaseModel):
    """Response model for an assumption."""

    model_config = {"from_attributes": True}

    id: str
    fragment_id: str
    statement: str
    explicit: bool
    still_valid: bool | None
    invalidated_by: str | None
    created_at: str


@router.post(
    "/{assumption_id}/invalidate",
    response_model=AssumptionResponse,
    responses={
        200: {"description": "Assumption marked as invalid"},
        400: {"description": "Invalid ID format"},
        404: {"description": "Assumption not found"},
    },
)
async def invalidate_assumption(
    assumption_id: str,
    request: InvalidateAssumptionRequest,
) -> AssumptionResponse:
    """Mark an assumption as invalid.

    When new information comes in that contradicts a previous assumption,
    use this endpoint to mark it as invalid and track which fragment
    caused the invalidation.
    """
    db = get_database()

    try:
        uuid_id = UUID(assumption_id)
        invalidated_by_id = UUID(request.invalidated_by)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid ID format",
        ) from e

    # Check that the invalidating fragment exists
    invalidating_fragment = await db.get_fragment(invalidated_by_id)
    if invalidating_fragment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalidating fragment not found",
        )

    # Invalidate the assumption
    success = await db.invalidate_assumption(uuid_id, invalidated_by_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assumption not found",
        )

    # Fetch the updated assumption
    all_assumptions = await db.list_assumptions(limit=1000)
    updated_assumption = next(
        (a for a in all_assumptions if a.id == uuid_id), None
    )

    if updated_assumption is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assumption not found after update",
        )

    return AssumptionResponse(
        id=str(updated_assumption.id),
        fragment_id=str(updated_assumption.fragment_id),
        statement=updated_assumption.statement,
        explicit=updated_assumption.explicit,
        still_valid=updated_assumption.still_valid,
        invalidated_by=(
            str(updated_assumption.invalidated_by)
            if updated_assumption.invalidated_by
            else None
        ),
        created_at=updated_assumption.created_at.isoformat(),
    )


@router.get(
    "",
    response_model=list[AssumptionResponse],
    responses={
        200: {"description": "Assumptions retrieved successfully"},
    },
)
async def list_assumptions(
    fragment_id: str | None = None,
    project: str | None = None,
    still_valid: bool | None = None,
    limit: int = 50,
) -> list[AssumptionResponse]:
    """List assumptions with optional filtering.

    Args:
        fragment_id: Filter by parent fragment ID.
        project: Filter by project name.
        still_valid: Filter by validity status (true/false/null for not yet checked).
        limit: Maximum number of results to return.
    """
    db = get_database()

    fragment_uuid = None
    if fragment_id:
        try:
            fragment_uuid = UUID(fragment_id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid fragment ID format",
            ) from e

    # Convert still_valid filter to valid_only/invalid_only flags
    valid_only = False
    invalid_only = False
    if still_valid is True:
        valid_only = True
    elif still_valid is False:
        invalid_only = True

    assumptions = await db.list_assumptions(
        fragment_id=fragment_uuid,
        project=project,
        valid_only=valid_only,
        invalid_only=invalid_only,
        limit=limit,
    )

    return [
        AssumptionResponse(
            id=str(a.id),
            fragment_id=str(a.fragment_id),
            statement=a.statement,
            explicit=a.explicit,
            still_valid=a.still_valid,
            invalidated_by=str(a.invalidated_by) if a.invalidated_by else None,
            created_at=a.created_at.isoformat(),
        )
        for a in assumptions
    ]

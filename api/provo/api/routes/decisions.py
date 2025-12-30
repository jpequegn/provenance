"""Decisions API endpoints."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from provo.storage import get_database

router = APIRouter()


class DecisionResponse(BaseModel):
    """Response model for a decision."""

    model_config = {"from_attributes": True}

    id: str
    fragment_id: str
    what: str
    why: str
    confidence: float
    created_at: str


@router.get(
    "",
    response_model=list[DecisionResponse],
    responses={
        200: {"description": "Decisions retrieved successfully"},
    },
)
async def list_decisions(
    fragment_id: str | None = None,
    project: str | None = None,
    since: datetime | None = None,
    limit: int = 50,
) -> list[DecisionResponse]:
    """List decisions with optional filtering.

    Args:
        fragment_id: Filter by parent fragment ID.
        project: Filter by project name.
        since: Filter by decisions created after this datetime.
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

    decisions = await db.list_decisions(
        fragment_id=fragment_uuid,
        project=project,
        since=since,
        limit=limit,
    )

    return [
        DecisionResponse(
            id=str(d.id),
            fragment_id=str(d.fragment_id),
            what=d.what,
            why=d.why,
            confidence=d.confidence,
            created_at=d.created_at.isoformat(),
        )
        for d in decisions
    ]

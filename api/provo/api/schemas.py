"""Pydantic schemas for API request/response validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from provo.storage.models import SourceType


class FragmentCreateRequest(BaseModel):
    """Request schema for creating a new fragment."""

    content: str = Field(..., min_length=1, description="The raw content to capture")
    project: str | None = Field(None, description="Project name for organization")
    topics: list[str] = Field(default_factory=list, description="List of topic tags")
    source_type: SourceType = Field(
        default=SourceType.QUICK_CAPTURE,
        description="Type of capture source",
    )
    source_ref: str | None = Field(
        None,
        description="Reference URL or identifier for the source",
    )
    participants: list[str] = Field(
        default_factory=list,
        description="List of participants (for meetings)",
    )

    model_config = {"use_enum_values": True}


class FragmentResponse(BaseModel):
    """Response schema for a fragment."""

    id: UUID
    content: str = Field(..., validation_alias="raw_content")
    summary: str | None = None
    source_type: SourceType
    source_ref: str | None = None
    captured_at: datetime
    participants: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    project: str | None = None

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
    code: str | None = None

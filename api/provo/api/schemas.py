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


class SearchResultItem(BaseModel):
    """A single search result with similarity score."""

    id: UUID
    content: str = Field(..., validation_alias="raw_content")
    summary: str | None = None
    score: float = Field(..., description="Similarity score (0-1, higher is more similar)")
    source_type: SourceType
    source_ref: str | None = None
    captured_at: datetime
    topics: list[str] = Field(default_factory=list)
    project: str | None = None

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }


class SearchResponse(BaseModel):
    """Response schema for semantic search."""

    query: str
    results: list[SearchResultItem] = Field(default_factory=list)


class RelatedFragmentItem(BaseModel):
    """A related fragment with link information."""

    id: UUID
    content: str = Field(..., validation_alias="raw_content")
    summary: str | None = None
    strength: float = Field(
        ..., description="Link strength (0-1, higher is more related)"
    )
    link_type: str = Field(..., description="Type of relationship")
    source_type: SourceType
    source_ref: str | None = None
    captured_at: datetime
    topics: list[str] = Field(default_factory=list)
    project: str | None = None

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }


class RelatedFragmentsResponse(BaseModel):
    """Response schema for related fragments."""

    fragment_id: UUID
    related: list[RelatedFragmentItem] = Field(default_factory=list)

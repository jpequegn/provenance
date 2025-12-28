"""Data models for Provenance storage layer."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4


def _utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(UTC)


class SourceType(str, Enum):
    """Type of context source."""

    QUICK_CAPTURE = "quick_capture"
    ZOOM = "zoom"
    TEAMS = "teams"
    NOTES = "notes"


class LinkType(str, Enum):
    """Type of relationship between fragments."""

    RELATES_TO = "relates_to"  # Semantic similarity
    REFERENCES = "references"  # Same entities mentioned
    FOLLOWS = "follows"  # Temporal sequence
    CONTRADICTS = "contradicts"  # Conflicting decisions
    INVALIDATES = "invalidates"  # New info breaks old assumptions


@dataclass
class Decision:
    """A decision extracted from a fragment."""

    id: UUID = field(default_factory=uuid4)
    fragment_id: UUID = field(default_factory=uuid4)
    what: str = ""
    why: str = ""
    confidence: float = 0.0
    created_at: datetime = field(default_factory=_utc_now)


@dataclass
class Assumption:
    """An assumption extracted from a fragment."""

    id: UUID = field(default_factory=uuid4)
    fragment_id: UUID = field(default_factory=uuid4)
    statement: str = ""
    explicit: bool = True
    still_valid: bool | None = None
    invalidated_by: UUID | None = None
    created_at: datetime = field(default_factory=_utc_now)


@dataclass
class FragmentLink:
    """A relationship between two fragments."""

    id: UUID = field(default_factory=uuid4)
    source_id: UUID = field(default_factory=uuid4)
    target_id: UUID = field(default_factory=uuid4)
    link_type: LinkType = LinkType.RELATES_TO
    strength: float = 0.0  # 0.0 to 1.0
    created_at: datetime = field(default_factory=_utc_now)


@dataclass
class ContextFragment:
    """A piece of captured context."""

    id: UUID = field(default_factory=uuid4)
    raw_content: str = ""
    summary: str | None = None
    source_type: SourceType = SourceType.QUICK_CAPTURE
    source_ref: str | None = None
    captured_at: datetime = field(default_factory=_utc_now)
    participants: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    project: str | None = None

    # Related data (populated when fetching)
    decisions: list[Decision] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)

"""Tests for the database storage layer."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from provo.storage import (
    Assumption,
    ContextFragment,
    Database,
    Decision,
    FragmentLink,
    LinkType,
    SourceType,
)


@pytest.fixture
async def db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        database = Database(db_path)
        await database.initialize()
        yield database


class TestDatabaseInitialization:
    """Tests for database initialization."""

    async def test_initialize_creates_tables(self, db: Database):
        """Test that initialization creates all required tables."""
        async with db.connect() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row["name"] for row in await cursor.fetchall()}

        expected_tables = {
            "schema_version",
            "fragments",
            "decisions",
            "assumptions",
            "fragment_links",
        }
        assert expected_tables.issubset(tables)

    async def test_initialize_creates_indexes(self, db: Database):
        """Test that initialization creates indexes."""
        async with db.connect() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
            indexes = {row["name"] for row in await cursor.fetchall()}

        assert "idx_fragments_captured_at" in indexes
        assert "idx_fragments_source_type" in indexes
        assert "idx_fragments_project" in indexes

    async def test_initialize_records_schema_version(self, db: Database):
        """Test that schema version is recorded."""
        async with db.connect() as conn:
            cursor = await conn.execute("SELECT version FROM schema_version")
            row = await cursor.fetchone()

        assert row is not None
        assert row["version"] == 1


class TestFragmentCRUD:
    """Tests for fragment CRUD operations."""

    async def test_create_fragment(self, db: Database):
        """Test creating a new fragment."""
        fragment = ContextFragment(
            raw_content="Decided to use PostgreSQL for the database",
            source_type=SourceType.QUICK_CAPTURE,
            project="billing",
            topics=["database", "architecture"],
        )

        created = await db.create_fragment(fragment)

        assert created.id == fragment.id
        assert created.raw_content == fragment.raw_content
        assert created.project == "billing"

    async def test_get_fragment(self, db: Database):
        """Test retrieving a fragment by ID."""
        fragment = ContextFragment(
            raw_content="Test content",
            source_type=SourceType.ZOOM,
            participants=["Alice", "Bob"],
        )
        await db.create_fragment(fragment)

        retrieved = await db.get_fragment(fragment.id)

        assert retrieved is not None
        assert retrieved.id == fragment.id
        assert retrieved.raw_content == "Test content"
        assert retrieved.participants == ["Alice", "Bob"]

    async def test_get_fragment_not_found(self, db: Database):
        """Test that getting a non-existent fragment returns None."""
        result = await db.get_fragment(uuid4())
        assert result is None

    async def test_list_fragments(self, db: Database):
        """Test listing fragments."""
        for i in range(5):
            await db.create_fragment(
                ContextFragment(raw_content=f"Fragment {i}")
            )

        fragments = await db.list_fragments()

        assert len(fragments) == 5

    async def test_list_fragments_with_project_filter(self, db: Database):
        """Test filtering fragments by project."""
        await db.create_fragment(
            ContextFragment(raw_content="Project A", project="project-a")
        )
        await db.create_fragment(
            ContextFragment(raw_content="Project B", project="project-b")
        )

        fragments = await db.list_fragments(project="project-a")

        assert len(fragments) == 1
        assert fragments[0].project == "project-a"

    async def test_list_fragments_with_source_type_filter(self, db: Database):
        """Test filtering fragments by source type."""
        await db.create_fragment(
            ContextFragment(raw_content="Zoom", source_type=SourceType.ZOOM)
        )
        await db.create_fragment(
            ContextFragment(raw_content="Quick", source_type=SourceType.QUICK_CAPTURE)
        )

        fragments = await db.list_fragments(source_type=SourceType.ZOOM)

        assert len(fragments) == 1
        assert fragments[0].source_type == SourceType.ZOOM

    async def test_list_fragments_with_date_filter(self, db: Database):
        """Test filtering fragments by date range."""
        now = datetime.now(UTC)
        yesterday = now - timedelta(days=1)
        last_week = now - timedelta(days=7)

        await db.create_fragment(
            ContextFragment(raw_content="Today", captured_at=now)
        )
        await db.create_fragment(
            ContextFragment(raw_content="Yesterday", captured_at=yesterday)
        )
        await db.create_fragment(
            ContextFragment(raw_content="Last week", captured_at=last_week)
        )

        # Get fragments from the last 2 days
        since = now - timedelta(days=2)
        fragments = await db.list_fragments(since=since)

        assert len(fragments) == 2

    async def test_update_fragment(self, db: Database):
        """Test updating a fragment."""
        fragment = ContextFragment(raw_content="Original content")
        await db.create_fragment(fragment)

        fragment.raw_content = "Updated content"
        fragment.summary = "A summary"
        await db.update_fragment(fragment)

        retrieved = await db.get_fragment(fragment.id)
        assert retrieved is not None
        assert retrieved.raw_content == "Updated content"
        assert retrieved.summary == "A summary"

    async def test_delete_fragment(self, db: Database):
        """Test deleting a fragment."""
        fragment = ContextFragment(raw_content="To be deleted")
        await db.create_fragment(fragment)

        deleted = await db.delete_fragment(fragment.id)

        assert deleted is True
        assert await db.get_fragment(fragment.id) is None

    async def test_delete_fragment_not_found(self, db: Database):
        """Test deleting a non-existent fragment."""
        deleted = await db.delete_fragment(uuid4())
        assert deleted is False


class TestDecisionCRUD:
    """Tests for decision CRUD operations."""

    async def test_create_decision(self, db: Database):
        """Test creating a decision."""
        fragment = ContextFragment(raw_content="Test")
        await db.create_fragment(fragment)

        decision = Decision(
            fragment_id=fragment.id,
            what="Use PostgreSQL",
            why="ACID compliance needed",
            confidence=0.95,
        )
        created = await db.create_decision(decision)

        assert created.id == decision.id
        assert created.what == "Use PostgreSQL"

    async def test_get_fragment_includes_decisions(self, db: Database):
        """Test that getting a fragment includes its decisions."""
        fragment = ContextFragment(raw_content="Test")
        await db.create_fragment(fragment)

        await db.create_decision(
            Decision(fragment_id=fragment.id, what="Decision 1", confidence=0.9)
        )
        await db.create_decision(
            Decision(fragment_id=fragment.id, what="Decision 2", confidence=0.8)
        )

        retrieved = await db.get_fragment(fragment.id)

        assert retrieved is not None
        assert len(retrieved.decisions) == 2

    async def test_list_decisions_by_project(self, db: Database):
        """Test listing decisions filtered by project."""
        frag_a = ContextFragment(raw_content="A", project="project-a")
        frag_b = ContextFragment(raw_content="B", project="project-b")
        await db.create_fragment(frag_a)
        await db.create_fragment(frag_b)

        await db.create_decision(
            Decision(fragment_id=frag_a.id, what="Decision A", confidence=0.9)
        )
        await db.create_decision(
            Decision(fragment_id=frag_b.id, what="Decision B", confidence=0.9)
        )

        decisions = await db.list_decisions(project="project-a")

        assert len(decisions) == 1
        assert decisions[0].what == "Decision A"


class TestAssumptionCRUD:
    """Tests for assumption CRUD operations."""

    async def test_create_assumption(self, db: Database):
        """Test creating an assumption."""
        fragment = ContextFragment(raw_content="Test")
        await db.create_fragment(fragment)

        assumption = Assumption(
            fragment_id=fragment.id,
            statement="Traffic will stay under 1000 RPS",
            explicit=True,
        )
        created = await db.create_assumption(assumption)

        assert created.id == assumption.id
        assert created.statement == "Traffic will stay under 1000 RPS"

    async def test_invalidate_assumption(self, db: Database):
        """Test invalidating an assumption."""
        frag1 = ContextFragment(raw_content="Original assumption")
        frag2 = ContextFragment(raw_content="New information")
        await db.create_fragment(frag1)
        await db.create_fragment(frag2)

        assumption = Assumption(
            fragment_id=frag1.id,
            statement="Will never exceed 100 users",
        )
        await db.create_assumption(assumption)

        result = await db.invalidate_assumption(assumption.id, frag2.id)

        assert result is True

        assumptions = await db.list_assumptions(invalid_only=True)
        assert len(assumptions) == 1
        assert assumptions[0].still_valid is False
        assert assumptions[0].invalidated_by == frag2.id

    async def test_list_assumptions_valid_only(self, db: Database):
        """Test listing only valid assumptions."""
        fragment = ContextFragment(raw_content="Test")
        await db.create_fragment(fragment)

        # Valid assumption
        await db.create_assumption(
            Assumption(fragment_id=fragment.id, statement="Valid", still_valid=True)
        )
        # Invalid assumption
        invalid = Assumption(fragment_id=fragment.id, statement="Invalid")
        await db.create_assumption(invalid)
        await db.invalidate_assumption(invalid.id, fragment.id)
        # Unknown assumption
        await db.create_assumption(
            Assumption(fragment_id=fragment.id, statement="Unknown")
        )

        valid_assumptions = await db.list_assumptions(valid_only=True)

        # Should include valid and unknown (None), but not invalid
        assert len(valid_assumptions) == 2


class TestFragmentLinks:
    """Tests for fragment link operations."""

    async def test_create_link(self, db: Database):
        """Test creating a link between fragments."""
        frag1 = ContextFragment(raw_content="Fragment 1")
        frag2 = ContextFragment(raw_content="Fragment 2")
        await db.create_fragment(frag1)
        await db.create_fragment(frag2)

        link = FragmentLink(
            source_id=frag1.id,
            target_id=frag2.id,
            link_type=LinkType.RELATES_TO,
            strength=0.85,
        )
        created = await db.create_link(link)

        assert created.id == link.id
        assert created.strength == 0.85

    async def test_get_related_fragments(self, db: Database):
        """Test getting fragments related to a given fragment."""
        center = ContextFragment(raw_content="Center")
        related1 = ContextFragment(raw_content="Related 1")
        related2 = ContextFragment(raw_content="Related 2")
        unrelated = ContextFragment(raw_content="Unrelated")

        await db.create_fragment(center)
        await db.create_fragment(related1)
        await db.create_fragment(related2)
        await db.create_fragment(unrelated)

        await db.create_link(
            FragmentLink(
                source_id=center.id,
                target_id=related1.id,
                link_type=LinkType.RELATES_TO,
                strength=0.9,
            )
        )
        await db.create_link(
            FragmentLink(
                source_id=center.id,
                target_id=related2.id,
                link_type=LinkType.REFERENCES,
                strength=0.7,
            )
        )

        # Get all related
        all_related = await db.get_related_fragments(center.id)
        assert len(all_related) == 2

        # Filter by link type
        relates_only = await db.get_related_fragments(
            center.id, link_type=LinkType.RELATES_TO
        )
        assert len(relates_only) == 1
        assert relates_only[0][0].raw_content == "Related 1"

    async def test_cascade_delete_on_fragment_removal(self, db: Database):
        """Test that deleting a fragment cascades to related data."""
        fragment = ContextFragment(raw_content="Test")
        await db.create_fragment(fragment)

        await db.create_decision(
            Decision(fragment_id=fragment.id, what="Test decision", confidence=0.9)
        )
        await db.create_assumption(
            Assumption(fragment_id=fragment.id, statement="Test assumption")
        )

        # Verify they exist
        retrieved = await db.get_fragment(fragment.id)
        assert retrieved is not None
        assert len(retrieved.decisions) == 1
        assert len(retrieved.assumptions) == 1

        # Delete the fragment
        await db.delete_fragment(fragment.id)

        # Verify cascade
        async with db.connect() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) as count FROM decisions WHERE fragment_id = ?",
                (str(fragment.id),),
            )
            row = await cursor.fetchone()
            assert row["count"] == 0

            cursor = await conn.execute(
                "SELECT COUNT(*) as count FROM assumptions WHERE fragment_id = ?",
                (str(fragment.id),),
            )
            row = await cursor.fetchone()
            assert row["count"] == 0

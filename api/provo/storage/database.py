"""Async SQLite database connection and schema management."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import aiosqlite

from provo.storage.models import (
    Assumption,
    ContextFragment,
    Decision,
    FragmentLink,
    LinkType,
    SourceType,
)

# Default database path
DEFAULT_DB_PATH = Path("data/provenance.db")

# Schema version for migrations
SCHEMA_VERSION = 1

SCHEMA_SQL = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Context fragments table
CREATE TABLE IF NOT EXISTS fragments (
    id TEXT PRIMARY KEY,
    raw_content TEXT NOT NULL,
    summary TEXT,
    source_type TEXT NOT NULL CHECK (source_type IN ('quick_capture', 'zoom', 'teams', 'notes')),
    source_ref TEXT,
    captured_at TEXT NOT NULL,
    participants TEXT NOT NULL DEFAULT '[]',  -- JSON array
    topics TEXT NOT NULL DEFAULT '[]',         -- JSON array
    project TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Decisions extracted from fragments
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    fragment_id TEXT NOT NULL REFERENCES fragments(id) ON DELETE CASCADE,
    what TEXT NOT NULL,
    why TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Assumptions extracted from fragments
CREATE TABLE IF NOT EXISTS assumptions (
    id TEXT PRIMARY KEY,
    fragment_id TEXT NOT NULL REFERENCES fragments(id) ON DELETE CASCADE,
    statement TEXT NOT NULL,
    explicit INTEGER NOT NULL DEFAULT 1,  -- Boolean as integer
    still_valid INTEGER,                   -- NULL = unknown, 1 = valid, 0 = invalid
    invalidated_by TEXT REFERENCES fragments(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Links between fragments
CREATE TABLE IF NOT EXISTS fragment_links (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES fragments(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES fragments(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL CHECK (
        link_type IN ('relates_to', 'references', 'follows', 'contradicts', 'invalidates')
    ),
    strength REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, target_id, link_type)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_fragments_captured_at ON fragments(captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_fragments_source_type ON fragments(source_type);
CREATE INDEX IF NOT EXISTS idx_fragments_project ON fragments(project);
CREATE INDEX IF NOT EXISTS idx_fragments_created_at ON fragments(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_decisions_fragment_id ON decisions(fragment_id);
CREATE INDEX IF NOT EXISTS idx_decisions_created_at ON decisions(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_assumptions_fragment_id ON assumptions(fragment_id);
CREATE INDEX IF NOT EXISTS idx_assumptions_still_valid ON assumptions(still_valid);

CREATE INDEX IF NOT EXISTS idx_fragment_links_source_id ON fragment_links(source_id);
CREATE INDEX IF NOT EXISTS idx_fragment_links_target_id ON fragment_links(target_id);
CREATE INDEX IF NOT EXISTS idx_fragment_links_type ON fragment_links(link_type);
"""


class Database:
    """Async SQLite database connection manager."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._connection: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize the database and apply schema."""
        # Ensure data directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        async with self.connect() as db:
            # Enable foreign keys
            await db.execute("PRAGMA foreign_keys = ON")

            # Apply schema
            await db.executescript(SCHEMA_SQL)

            # Record schema version
            await db.execute(
                """
                INSERT OR REPLACE INTO schema_version (version, applied_at)
                VALUES (?, ?)
                """,
                (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
            )
            await db.commit()

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Get a database connection."""
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        try:
            await db.execute("PRAGMA foreign_keys = ON")
            yield db
        finally:
            await db.close()

    # ============== Fragment CRUD ==============

    async def create_fragment(self, fragment: ContextFragment) -> ContextFragment:
        """Create a new context fragment."""
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO fragments (id, raw_content, summary, source_type, source_ref,
                                       captured_at, participants, topics, project)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(fragment.id),
                    fragment.raw_content,
                    fragment.summary,
                    fragment.source_type.value,
                    fragment.source_ref,
                    fragment.captured_at.isoformat(),
                    json.dumps(fragment.participants),
                    json.dumps(fragment.topics),
                    fragment.project,
                ),
            )
            await db.commit()
        return fragment

    async def get_fragment(self, fragment_id: UUID) -> ContextFragment | None:
        """Get a fragment by ID with its decisions and assumptions."""
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM fragments WHERE id = ?", (str(fragment_id),)
            )
            row = await cursor.fetchone()
            if not row:
                return None

            fragment = self._row_to_fragment(row)

            # Fetch decisions
            cursor = await db.execute(
                "SELECT * FROM decisions WHERE fragment_id = ?", (str(fragment_id),)
            )
            rows = await cursor.fetchall()
            fragment.decisions = [self._row_to_decision(r) for r in rows]

            # Fetch assumptions
            cursor = await db.execute(
                "SELECT * FROM assumptions WHERE fragment_id = ?", (str(fragment_id),)
            )
            rows = await cursor.fetchall()
            fragment.assumptions = [self._row_to_assumption(r) for r in rows]

            return fragment

    async def list_fragments(
        self,
        *,
        project: str | None = None,
        source_type: SourceType | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ContextFragment]:
        """List fragments with optional filters."""
        query = "SELECT * FROM fragments WHERE 1=1"
        params: list = []

        if project:
            query += " AND project = ?"
            params.append(project)
        if source_type:
            query += " AND source_type = ?"
            params.append(source_type.value)
        if since:
            query += " AND captured_at >= ?"
            params.append(since.isoformat())
        if until:
            query += " AND captured_at <= ?"
            params.append(until.isoformat())

        query += " ORDER BY captured_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with self.connect() as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [self._row_to_fragment(row) for row in rows]

    async def update_fragment(self, fragment: ContextFragment) -> ContextFragment:
        """Update an existing fragment."""
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE fragments SET
                    raw_content = ?,
                    summary = ?,
                    source_type = ?,
                    source_ref = ?,
                    captured_at = ?,
                    participants = ?,
                    topics = ?,
                    project = ?
                WHERE id = ?
                """,
                (
                    fragment.raw_content,
                    fragment.summary,
                    fragment.source_type.value,
                    fragment.source_ref,
                    fragment.captured_at.isoformat(),
                    json.dumps(fragment.participants),
                    json.dumps(fragment.topics),
                    fragment.project,
                    str(fragment.id),
                ),
            )
            await db.commit()
        return fragment

    async def delete_fragment(self, fragment_id: UUID) -> bool:
        """Delete a fragment and its related data."""
        async with self.connect() as db:
            cursor = await db.execute(
                "DELETE FROM fragments WHERE id = ?", (str(fragment_id),)
            )
            await db.commit()
            return cursor.rowcount > 0

    # ============== Decision CRUD ==============

    async def create_decision(self, decision: Decision) -> Decision:
        """Create a new decision."""
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO decisions (id, fragment_id, what, why, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(decision.id),
                    str(decision.fragment_id),
                    decision.what,
                    decision.why,
                    decision.confidence,
                ),
            )
            await db.commit()
        return decision

    async def list_decisions(
        self,
        *,
        fragment_id: UUID | None = None,
        project: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Decision]:
        """List decisions with optional filters."""
        if project:
            query = """
                SELECT d.* FROM decisions d
                JOIN fragments f ON d.fragment_id = f.id
                WHERE f.project = ?
            """
            params: list = [project]
        else:
            query = "SELECT * FROM decisions WHERE 1=1"
            params = []

        if fragment_id:
            query += " AND fragment_id = ?"
            params.append(str(fragment_id))
        if since:
            query += " AND d.created_at >= ?" if project else " AND created_at >= ?"
            params.append(since.isoformat())

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        async with self.connect() as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [self._row_to_decision(row) for row in rows]

    # ============== Assumption CRUD ==============

    async def create_assumption(self, assumption: Assumption) -> Assumption:
        """Create a new assumption."""
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO assumptions
                    (id, fragment_id, statement, explicit, still_valid, invalidated_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(assumption.id),
                    str(assumption.fragment_id),
                    assumption.statement,
                    1 if assumption.explicit else 0,
                    None
                    if assumption.still_valid is None
                    else (1 if assumption.still_valid else 0),
                    str(assumption.invalidated_by) if assumption.invalidated_by else None,
                ),
            )
            await db.commit()
        return assumption

    async def invalidate_assumption(
        self, assumption_id: UUID, invalidated_by: UUID
    ) -> bool:
        """Mark an assumption as invalid."""
        async with self.connect() as db:
            cursor = await db.execute(
                """
                UPDATE assumptions SET still_valid = 0, invalidated_by = ?
                WHERE id = ?
                """,
                (str(invalidated_by), str(assumption_id)),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def update_assumption_validity(
        self, assumption_id: UUID, still_valid: bool
    ) -> bool:
        """Update an assumption's validity status."""
        async with self.connect() as db:
            cursor = await db.execute(
                """
                UPDATE assumptions SET still_valid = ?
                WHERE id = ?
                """,
                (1 if still_valid else 0, str(assumption_id)),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def list_assumptions(
        self,
        *,
        fragment_id: UUID | None = None,
        project: str | None = None,
        since: datetime | None = None,
        valid_only: bool = False,
        invalid_only: bool = False,
        limit: int = 100,
    ) -> list[Assumption]:
        """List assumptions with optional filters."""
        if project:
            query = """
                SELECT a.* FROM assumptions a
                JOIN fragments f ON a.fragment_id = f.id
                WHERE f.project = ?
            """
            params: list = [project]
        else:
            query = "SELECT * FROM assumptions WHERE 1=1"
            params = []

        if fragment_id:
            query += " AND fragment_id = ?"
            params.append(str(fragment_id))
        if since:
            query += " AND a.created_at >= ?" if project else " AND created_at >= ?"
            params.append(since.isoformat())
        if valid_only:
            query += " AND (still_valid = 1 OR still_valid IS NULL)"
        if invalid_only:
            query += " AND still_valid = 0"

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        async with self.connect() as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [self._row_to_assumption(row) for row in rows]

    # ============== Fragment Links CRUD ==============

    async def create_link(self, link: FragmentLink) -> FragmentLink:
        """Create a link between two fragments."""
        async with self.connect() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO fragment_links
                    (id, source_id, target_id, link_type, strength)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(link.id),
                    str(link.source_id),
                    str(link.target_id),
                    link.link_type.value,
                    link.strength,
                ),
            )
            await db.commit()
        return link

    async def get_related_fragments(
        self,
        fragment_id: UUID,
        link_type: LinkType | None = None,
    ) -> list[tuple[ContextFragment, float, LinkType]]:
        """Get fragments related to a given fragment.

        Returns a list of tuples: (fragment, strength, link_type)
        """
        query = """
            SELECT f.*, fl.strength, fl.link_type FROM fragments f
            JOIN fragment_links fl ON (fl.target_id = f.id OR fl.source_id = f.id)
            WHERE (fl.source_id = ? OR fl.target_id = ?) AND f.id != ?
        """
        params: list = [str(fragment_id), str(fragment_id), str(fragment_id)]

        if link_type:
            query += " AND fl.link_type = ?"
            params.append(link_type.value)

        query += " ORDER BY fl.strength DESC"

        async with self.connect() as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [
                (
                    self._row_to_fragment(row),
                    row["strength"],
                    LinkType(row["link_type"]),
                )
                for row in rows
            ]

    # ============== Helpers ==============

    def _row_to_fragment(self, row: aiosqlite.Row) -> ContextFragment:
        """Convert a database row to a ContextFragment."""
        return ContextFragment(
            id=UUID(row["id"]),
            raw_content=row["raw_content"],
            summary=row["summary"],
            source_type=SourceType(row["source_type"]),
            source_ref=row["source_ref"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
            participants=json.loads(row["participants"]),
            topics=json.loads(row["topics"]),
            project=row["project"],
        )

    def _row_to_decision(self, row: aiosqlite.Row) -> Decision:
        """Convert a database row to a Decision."""
        return Decision(
            id=UUID(row["id"]),
            fragment_id=UUID(row["fragment_id"]),
            what=row["what"],
            why=row["why"],
            confidence=row["confidence"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_assumption(self, row: aiosqlite.Row) -> Assumption:
        """Convert a database row to an Assumption."""
        return Assumption(
            id=UUID(row["id"]),
            fragment_id=UUID(row["fragment_id"]),
            statement=row["statement"],
            explicit=bool(row["explicit"]),
            still_valid=None if row["still_valid"] is None else bool(row["still_valid"]),
            invalidated_by=UUID(row["invalidated_by"]) if row["invalidated_by"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )


# Global database instance
_db: Database | None = None


def get_database(db_path: Path | None = None) -> Database:
    """Get or create the global database instance."""
    global _db
    if _db is None:
        _db = Database(db_path or DEFAULT_DB_PATH)
    return _db


async def init_database(db_path: Path | None = None) -> Database:
    """Initialize and return the database."""
    db = get_database(db_path)
    await db.initialize()
    return db

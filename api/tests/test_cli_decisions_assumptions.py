"""Tests for CLI decisions and assumptions commands."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from provo.api.main import app
from provo.cli.main import parse_period
from provo.storage import Database, reset_vector_store
from provo.storage.models import Assumption, ContextFragment, Decision


@pytest.fixture(autouse=True)
def reset_services():
    """Reset global services before each test."""
    from provo.processing.embeddings import reset_embedding_service

    reset_embedding_service()
    reset_vector_store()

    # Reset database global
    import provo.storage.database as db_module

    db_module._db = None

    yield

    reset_embedding_service()
    reset_vector_store()
    db_module._db = None


@pytest.fixture
async def test_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        database = Database(db_path)
        await database.initialize()
        yield database


@pytest.fixture
def mock_embedding_service():
    """Mock the embedding service."""
    mock_service = AsyncMock()
    mock_service.embed.return_value = AsyncMock(
        vector=[0.1] * 768,
        model="nomic-embed-text",
        provider="ollama",
        cached=False,
    )
    return mock_service


@pytest.fixture
def mock_vector_store():
    """Mock the vector store."""
    mock_store = AsyncMock()
    mock_store.add_embedding.return_value = None
    mock_store.delete_embedding.return_value = True
    mock_store.search_similar.return_value = []
    return mock_store


@pytest.fixture
async def client(test_db, mock_embedding_service, mock_vector_store):
    """Create a test client with mocked services."""
    with (
        patch("provo.api.routes.fragments.get_database", return_value=test_db),
        patch("provo.api.routes.decisions.get_database", return_value=test_db),
        patch("provo.api.routes.assumptions.get_database", return_value=test_db),
        patch(
            "provo.api.routes.fragments.get_embedding_service",
            return_value=mock_embedding_service,
        ),
        patch(
            "provo.api.routes.fragments.get_vector_store",
            return_value=mock_vector_store,
        ),
        patch("provo.api.main.init_database", new_callable=AsyncMock),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac


class TestParsePeriod:
    """Tests for the parse_period helper function."""

    def test_parse_days(self):
        """Test parsing days format."""
        result = parse_period("7d")
        assert result is not None
        # Should be approximately 7 days ago
        expected = datetime.now() - timedelta(days=7)
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_weeks(self):
        """Test parsing weeks format."""
        result = parse_period("2w")
        assert result is not None
        expected = datetime.now() - timedelta(weeks=2)
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_months(self):
        """Test parsing months format (approximate)."""
        result = parse_period("1m")
        assert result is not None
        expected = datetime.now() - timedelta(days=30)
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_uppercase(self):
        """Test parsing uppercase format."""
        result = parse_period("7D")
        assert result is not None

    def test_invalid_format(self):
        """Test invalid format returns None."""
        assert parse_period("invalid") is None
        assert parse_period("7x") is None
        assert parse_period("abc") is None
        assert parse_period("") is None

    def test_zero_value(self):
        """Test zero value."""
        result = parse_period("0d")
        assert result is not None
        # Should be approximately now
        assert abs((result - datetime.now()).total_seconds()) < 2


class TestDecisionsEndpoint:
    """Tests for GET /api/decisions endpoint."""

    async def test_list_decisions_empty(self, client: AsyncClient, test_db):
        """Test listing decisions when none exist."""
        response = await client.get("/api/decisions")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    async def test_list_decisions_with_data(self, client: AsyncClient, test_db):
        """Test listing decisions with data."""
        # Create a fragment first
        fragment = ContextFragment(
            raw_content="Test content",
            project="test-project",
        )
        created_fragment = await test_db.create_fragment(fragment)

        # Create a decision
        decision = Decision(
            fragment_id=created_fragment.id,
            what="Use Postgres for billing",
            why="Need ACID transactions for money",
            confidence=0.92,
        )
        await test_db.create_decision(decision)

        response = await client.get("/api/decisions")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["what"] == "Use Postgres for billing"
        assert data[0]["why"] == "Need ACID transactions for money"
        assert data[0]["confidence"] == pytest.approx(0.92)

    async def test_list_decisions_filter_by_project(
        self, client: AsyncClient, test_db
    ):
        """Test filtering decisions by project."""
        # Create fragments for different projects
        fragment1 = ContextFragment(
            raw_content="Test 1",
            project="billing",
        )
        created1 = await test_db.create_fragment(fragment1)

        fragment2 = ContextFragment(
            raw_content="Test 2",
            project="auth",
        )
        created2 = await test_db.create_fragment(fragment2)

        # Create decisions for each
        decision1 = Decision(
            fragment_id=created1.id,
            what="Billing decision",
            confidence=0.9,
        )
        await test_db.create_decision(decision1)

        decision2 = Decision(
            fragment_id=created2.id,
            what="Auth decision",
            confidence=0.8,
        )
        await test_db.create_decision(decision2)

        # Filter by project
        response = await client.get("/api/decisions?project=billing")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["what"] == "Billing decision"

    async def test_list_decisions_filter_by_since(
        self, client: AsyncClient, test_db
    ):
        """Test filtering decisions by since datetime."""
        # Create a fragment
        fragment = ContextFragment(raw_content="Test", project="test")
        created_fragment = await test_db.create_fragment(fragment)

        # Create a decision
        decision = Decision(
            fragment_id=created_fragment.id,
            what="Recent decision",
            confidence=0.9,
        )
        await test_db.create_decision(decision)

        # Filter by since (future date should return nothing)
        future = (datetime.now() + timedelta(days=1)).isoformat()
        response = await client.get(f"/api/decisions?since={future}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

        # Filter by since (past date should return the decision)
        past = (datetime.now() - timedelta(days=1)).isoformat()
        response = await client.get(f"/api/decisions?since={past}")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1

    async def test_list_decisions_limit(self, client: AsyncClient, test_db):
        """Test limiting decisions results."""
        # Create a fragment
        fragment = ContextFragment(raw_content="Test", project="test")
        created_fragment = await test_db.create_fragment(fragment)

        # Create multiple decisions
        for i in range(5):
            decision = Decision(
                fragment_id=created_fragment.id,
                what=f"Decision {i}",
                confidence=0.9,
            )
            await test_db.create_decision(decision)

        # Request with limit
        response = await client.get("/api/decisions?limit=2")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 2


class TestAssumptionsEndpoint:
    """Tests for GET /api/assumptions endpoint."""

    async def test_list_assumptions_empty(self, client: AsyncClient, test_db):
        """Test listing assumptions when none exist."""
        response = await client.get("/api/assumptions")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    async def test_list_assumptions_with_data(self, client: AsyncClient, test_db):
        """Test listing assumptions with data."""
        # Create a fragment first
        fragment = ContextFragment(
            raw_content="Test content",
            project="test-project",
        )
        created_fragment = await test_db.create_fragment(fragment)

        # Create an assumption
        assumption = Assumption(
            fragment_id=created_fragment.id,
            statement="Users will have modern browsers",
            explicit=True,
            still_valid=None,
        )
        await test_db.create_assumption(assumption)

        response = await client.get("/api/assumptions")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["statement"] == "Users will have modern browsers"
        assert data[0]["explicit"] is True
        assert data[0]["still_valid"] is None

    async def test_list_assumptions_filter_by_project(
        self, client: AsyncClient, test_db
    ):
        """Test filtering assumptions by project."""
        # Create fragments for different projects
        fragment1 = ContextFragment(raw_content="Test 1", project="auth")
        created1 = await test_db.create_fragment(fragment1)

        fragment2 = ContextFragment(raw_content="Test 2", project="billing")
        created2 = await test_db.create_fragment(fragment2)

        # Create assumptions
        assumption1 = Assumption(
            fragment_id=created1.id,
            statement="Auth assumption",
            explicit=True,
        )
        await test_db.create_assumption(assumption1)

        assumption2 = Assumption(
            fragment_id=created2.id,
            statement="Billing assumption",
            explicit=True,
        )
        await test_db.create_assumption(assumption2)

        # Filter by project
        response = await client.get("/api/assumptions?project=auth")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["statement"] == "Auth assumption"

    async def test_list_assumptions_filter_by_validity(
        self, client: AsyncClient, test_db
    ):
        """Test filtering assumptions by validity status."""
        # Create a fragment
        fragment = ContextFragment(raw_content="Test", project="test")
        created_fragment = await test_db.create_fragment(fragment)

        # Create valid and invalid assumptions
        valid_assumption = Assumption(
            fragment_id=created_fragment.id,
            statement="Valid assumption",
            still_valid=True,
        )
        await test_db.create_assumption(valid_assumption)

        invalid_assumption = Assumption(
            fragment_id=created_fragment.id,
            statement="Invalid assumption",
            still_valid=False,
        )
        await test_db.create_assumption(invalid_assumption)

        # Filter by still_valid=false (invalid only)
        response = await client.get("/api/assumptions?still_valid=false")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["statement"] == "Invalid assumption"

    async def test_list_assumptions_filter_by_since(
        self, client: AsyncClient, test_db
    ):
        """Test filtering assumptions by since datetime."""
        # Create a fragment
        fragment = ContextFragment(raw_content="Test", project="test")
        created_fragment = await test_db.create_fragment(fragment)

        # Create an assumption
        assumption = Assumption(
            fragment_id=created_fragment.id,
            statement="Recent assumption",
        )
        await test_db.create_assumption(assumption)

        # Filter by since (future date should return nothing)
        future = (datetime.now() + timedelta(days=1)).isoformat()
        response = await client.get(f"/api/assumptions?since={future}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

        # Filter by since (past date should return the assumption)
        past = (datetime.now() - timedelta(days=1)).isoformat()
        response = await client.get(f"/api/assumptions?since={past}")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1

    async def test_list_assumptions_limit(self, client: AsyncClient, test_db):
        """Test limiting assumptions results."""
        # Create a fragment
        fragment = ContextFragment(raw_content="Test", project="test")
        created_fragment = await test_db.create_fragment(fragment)

        # Create multiple assumptions
        for i in range(5):
            assumption = Assumption(
                fragment_id=created_fragment.id,
                statement=f"Assumption {i}",
            )
            await test_db.create_assumption(assumption)

        # Request with limit
        response = await client.get("/api/assumptions?limit=2")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 2

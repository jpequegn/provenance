"""Tests for the assumptions API endpoints."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from provo.api.main import app
from provo.storage import Database, reset_vector_store
from provo.storage.models import Assumption, ContextFragment


@pytest.fixture(autouse=True)
def reset_services():
    """Reset global services before each test."""
    from provo.processing.embeddings import reset_embedding_service

    reset_embedding_service()
    reset_vector_store()

    # Reset database global
    import provo.storage.database as db_module

    db_module._database = None

    yield

    reset_embedding_service()
    reset_vector_store()
    db_module._database = None


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
    return mock_store


@pytest.fixture
async def client(test_db, mock_embedding_service, mock_vector_store):
    """Create a test client with mocked services."""
    with (
        patch("provo.api.routes.fragments.get_database", return_value=test_db),
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


@pytest.fixture
async def sample_fragment(test_db):
    """Create a sample fragment for testing."""
    fragment = ContextFragment(
        raw_content="Test fragment content",
        project="test-project",
    )
    created = await test_db.create_fragment(fragment)
    return created


@pytest.fixture
async def sample_assumption(test_db, sample_fragment):
    """Create a sample assumption for testing."""
    assumption = Assumption(
        fragment_id=sample_fragment.id,
        statement="The API will remain stable",
        explicit=True,
        still_valid=None,
        invalidated_by=None,
    )
    await test_db.create_assumption(assumption)
    return assumption


class TestListAssumptions:
    """Tests for GET /api/assumptions endpoint."""

    async def test_list_assumptions_empty(self, client: AsyncClient):
        """Test listing assumptions when none exist."""
        response = await client.get("/api/assumptions")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    async def test_list_assumptions_returns_data(
        self, client: AsyncClient, sample_assumption
    ):
        """Test listing assumptions returns stored data."""
        response = await client.get("/api/assumptions")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["statement"] == "The API will remain stable"
        assert data[0]["explicit"] is True
        assert data[0]["still_valid"] is None

    async def test_list_assumptions_filter_by_fragment_id(
        self, test_db, client: AsyncClient, sample_fragment, sample_assumption
    ):
        """Test filtering assumptions by fragment ID."""
        # Create another fragment with a different assumption
        fragment2 = ContextFragment(
            raw_content="Another fragment",
            project="test-project",
        )
        created_fragment2 = await test_db.create_fragment(fragment2)
        assumption2 = Assumption(
            fragment_id=created_fragment2.id,
            statement="Different assumption",
            explicit=False,
        )
        await test_db.create_assumption(assumption2)

        # Filter by first fragment ID
        response = await client.get(
            f"/api/assumptions?fragment_id={sample_fragment.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["statement"] == "The API will remain stable"

    async def test_list_assumptions_filter_by_project(
        self, test_db, client: AsyncClient, sample_fragment
    ):
        """Test filtering assumptions by project."""
        # Create assumption for first fragment
        assumption1 = Assumption(
            fragment_id=sample_fragment.id,
            statement="Project A assumption",
            explicit=True,
        )
        await test_db.create_assumption(assumption1)

        # Create fragment with different project
        fragment2 = ContextFragment(
            raw_content="Another fragment",
            project="different-project",
        )
        created_fragment2 = await test_db.create_fragment(fragment2)
        assumption2 = Assumption(
            fragment_id=created_fragment2.id,
            statement="Different project assumption",
            explicit=False,
        )
        await test_db.create_assumption(assumption2)

        # Filter by project
        response = await client.get("/api/assumptions?project=test-project")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["statement"] == "Project A assumption"

    async def test_list_assumptions_filter_by_still_valid(
        self, test_db, client: AsyncClient, sample_fragment
    ):
        """Test filtering assumptions by validity status."""
        # Create valid assumption
        assumption1 = Assumption(
            fragment_id=sample_fragment.id,
            statement="Valid assumption",
            explicit=True,
            still_valid=True,
        )
        await test_db.create_assumption(assumption1)

        # Create invalid assumption
        assumption2 = Assumption(
            fragment_id=sample_fragment.id,
            statement="Invalid assumption",
            explicit=True,
            still_valid=False,
        )
        await test_db.create_assumption(assumption2)

        # Filter by still_valid=true
        response = await client.get("/api/assumptions?still_valid=true")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["statement"] == "Valid assumption"

    async def test_list_assumptions_invalid_fragment_id(self, client: AsyncClient):
        """Test filtering with invalid fragment ID format."""
        response = await client.get("/api/assumptions?fragment_id=not-a-uuid")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_list_assumptions_limit(
        self, test_db, client: AsyncClient, sample_fragment
    ):
        """Test limiting the number of assumptions returned."""
        # Create multiple assumptions
        for i in range(5):
            assumption = Assumption(
                fragment_id=sample_fragment.id,
                statement=f"Assumption {i}",
                explicit=True,
            )
            await test_db.create_assumption(assumption)

        response = await client.get("/api/assumptions?limit=2")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2


class TestInvalidateAssumption:
    """Tests for POST /api/assumptions/{id}/invalidate endpoint."""

    async def test_invalidate_assumption_success(
        self, test_db, client: AsyncClient, sample_fragment, sample_assumption
    ):
        """Test successfully invalidating an assumption."""
        # Create a new fragment that invalidates the assumption
        invalidating_fragment = ContextFragment(
            raw_content="This new info contradicts the API stability assumption",
            project="test-project",
        )
        created_invalidator = await test_db.create_fragment(invalidating_fragment)

        response = await client.post(
            f"/api/assumptions/{sample_assumption.id}/invalidate",
            json={"invalidated_by": str(created_invalidator.id)},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["still_valid"] is False
        assert data["invalidated_by"] == str(created_invalidator.id)

    async def test_invalidate_assumption_not_found(
        self, test_db, client: AsyncClient, sample_fragment
    ):
        """Test invalidating a non-existent assumption."""
        # Create a fragment for the invalidated_by reference
        invalidating_fragment = ContextFragment(
            raw_content="Test",
            project="test",
        )
        created_invalidator = await test_db.create_fragment(invalidating_fragment)

        response = await client.post(
            "/api/assumptions/00000000-0000-0000-0000-000000000000/invalidate",
            json={"invalidated_by": str(created_invalidator.id)},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_invalidate_assumption_invalid_id(self, client: AsyncClient):
        """Test invalidating with invalid assumption ID format."""
        response = await client.post(
            "/api/assumptions/not-a-uuid/invalidate",
            json={"invalidated_by": "00000000-0000-0000-0000-000000000000"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_invalidate_assumption_invalid_fragment_id(
        self, client: AsyncClient, sample_assumption
    ):
        """Test invalidating with invalid fragment ID format."""
        response = await client.post(
            f"/api/assumptions/{sample_assumption.id}/invalidate",
            json={"invalidated_by": "not-a-uuid"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_invalidate_assumption_fragment_not_found(
        self, client: AsyncClient, sample_assumption
    ):
        """Test invalidating with a non-existent invalidating fragment."""
        response = await client.post(
            f"/api/assumptions/{sample_assumption.id}/invalidate",
            json={"invalidated_by": "00000000-0000-0000-0000-000000000000"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "fragment" in response.json()["detail"].lower()


class TestAssumptionResponse:
    """Tests for assumption response format."""

    async def test_assumption_response_format(
        self, client: AsyncClient, sample_assumption
    ):
        """Test that assumption response has all required fields."""
        response = await client.get("/api/assumptions")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1

        assumption = data[0]
        assert "id" in assumption
        assert "fragment_id" in assumption
        assert "statement" in assumption
        assert "explicit" in assumption
        assert "still_valid" in assumption
        assert "invalidated_by" in assumption
        assert "created_at" in assumption

    async def test_assumption_response_types(
        self, client: AsyncClient, sample_assumption
    ):
        """Test that assumption response fields have correct types."""
        response = await client.get("/api/assumptions")

        data = response.json()
        assumption = data[0]

        # IDs should be strings (serialized UUIDs)
        assert isinstance(assumption["id"], str)
        assert isinstance(assumption["fragment_id"], str)

        # Statement should be string
        assert isinstance(assumption["statement"], str)

        # Boolean flags
        assert isinstance(assumption["explicit"], bool)

        # Optional fields can be None
        assert assumption["still_valid"] is None or isinstance(
            assumption["still_valid"], bool
        )
        assert assumption["invalidated_by"] is None or isinstance(
            assumption["invalidated_by"], str
        )

        # Created at should be ISO format string
        assert isinstance(assumption["created_at"], str)

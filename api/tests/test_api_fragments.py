"""Tests for the fragments API endpoints."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from provo.api.main import app
from provo.storage import Database, reset_vector_store


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


class TestCreateFragment:
    """Tests for POST /api/fragments endpoint."""

    async def test_create_fragment_success(self, client: AsyncClient):
        """Test successful fragment creation."""
        response = await client.post(
            "/api/fragments",
            json={
                "content": "Decided to use PostgreSQL for the database",
                "project": "billing",
                "topics": ["database", "architecture"],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "id" in data
        assert data["content"] == "Decided to use PostgreSQL for the database"
        assert data["project"] == "billing"
        assert data["topics"] == ["database", "architecture"]
        assert data["source_type"] == "quick_capture"

    async def test_create_fragment_minimal(self, client: AsyncClient):
        """Test creating fragment with only required fields."""
        response = await client.post(
            "/api/fragments",
            json={"content": "Simple note"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["content"] == "Simple note"
        assert data["project"] is None
        assert data["topics"] == []

    async def test_create_fragment_with_source_type(self, client: AsyncClient):
        """Test creating fragment with specific source type."""
        response = await client.post(
            "/api/fragments",
            json={
                "content": "Notes from meeting",
                "source_type": "zoom",
                "participants": ["Alice", "Bob"],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["source_type"] == "zoom"
        assert data["participants"] == ["Alice", "Bob"]

    async def test_create_fragment_with_source_ref(self, client: AsyncClient):
        """Test creating fragment with source reference."""
        response = await client.post(
            "/api/fragments",
            json={
                "content": "Decision from PR review",
                "source_ref": "https://github.com/org/repo/pull/123",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["source_ref"] == "https://github.com/org/repo/pull/123"

    async def test_create_fragment_empty_content_fails(self, client: AsyncClient):
        """Test that empty content is rejected."""
        response = await client.post(
            "/api/fragments",
            json={"content": ""},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_create_fragment_missing_content_fails(self, client: AsyncClient):
        """Test that missing content is rejected."""
        response = await client.post(
            "/api/fragments",
            json={"project": "test"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_create_fragment_invalid_source_type_fails(self, client: AsyncClient):
        """Test that invalid source type is rejected."""
        response = await client.post(
            "/api/fragments",
            json={
                "content": "Test content",
                "source_type": "invalid_type",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestGetFragment:
    """Tests for GET /api/fragments/{id} endpoint."""

    async def test_get_fragment_success(self, client: AsyncClient):
        """Test retrieving an existing fragment."""
        # Create a fragment first
        create_response = await client.post(
            "/api/fragments",
            json={"content": "Test fragment"},
        )
        fragment_id = create_response.json()["id"]

        # Retrieve it
        response = await client.get(f"/api/fragments/{fragment_id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == fragment_id
        assert data["content"] == "Test fragment"

    async def test_get_fragment_not_found(self, client: AsyncClient):
        """Test retrieving a non-existent fragment."""
        response = await client.get(
            "/api/fragments/00000000-0000-0000-0000-000000000000"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_get_fragment_invalid_id(self, client: AsyncClient):
        """Test retrieving with invalid ID format."""
        response = await client.get("/api/fragments/not-a-uuid")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestListFragments:
    """Tests for GET /api/fragments endpoint."""

    async def test_list_fragments_empty(self, client: AsyncClient):
        """Test listing fragments when none exist."""
        response = await client.get("/api/fragments")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    async def test_list_fragments_multiple(self, client: AsyncClient):
        """Test listing multiple fragments."""
        # Create some fragments
        for i in range(3):
            await client.post(
                "/api/fragments",
                json={"content": f"Fragment {i}"},
            )

        response = await client.get("/api/fragments")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 3

    async def test_list_fragments_filter_by_project(self, client: AsyncClient):
        """Test filtering fragments by project."""
        await client.post(
            "/api/fragments",
            json={"content": "Project A", "project": "alpha"},
        )
        await client.post(
            "/api/fragments",
            json={"content": "Project B", "project": "beta"},
        )

        response = await client.get("/api/fragments?project=alpha")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["project"] == "alpha"

    async def test_list_fragments_pagination(self, client: AsyncClient):
        """Test pagination with limit and offset."""
        # Create 5 fragments
        for i in range(5):
            await client.post(
                "/api/fragments",
                json={"content": f"Fragment {i}"},
            )

        # Get first 2
        response = await client.get("/api/fragments?limit=2")
        assert len(response.json()) == 2

        # Get next 2
        response = await client.get("/api/fragments?limit=2&offset=2")
        assert len(response.json()) == 2


class TestDeleteFragment:
    """Tests for DELETE /api/fragments/{id} endpoint."""

    async def test_delete_fragment_success(self, client: AsyncClient):
        """Test deleting an existing fragment."""
        # Create a fragment
        create_response = await client.post(
            "/api/fragments",
            json={"content": "To be deleted"},
        )
        fragment_id = create_response.json()["id"]

        # Delete it
        response = await client.delete(f"/api/fragments/{fragment_id}")

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify it's gone
        get_response = await client.get(f"/api/fragments/{fragment_id}")
        assert get_response.status_code == status.HTTP_404_NOT_FOUND

    async def test_delete_fragment_not_found(self, client: AsyncClient):
        """Test deleting a non-existent fragment."""
        response = await client.delete(
            "/api/fragments/00000000-0000-0000-0000-000000000000"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_delete_fragment_invalid_id(self, client: AsyncClient):
        """Test deleting with invalid ID format."""
        response = await client.delete("/api/fragments/not-a-uuid")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestEmbeddingIntegration:
    """Tests for embedding service integration."""

    async def test_embedding_generated_on_create(
        self, client: AsyncClient, mock_embedding_service, mock_vector_store
    ):
        """Test that embedding is generated when creating a fragment."""
        await client.post(
            "/api/fragments",
            json={"content": "Test content for embedding"},
        )

        # Verify embedding service was called
        mock_embedding_service.embed.assert_called_once_with("Test content for embedding")

        # Verify vector store was called
        mock_vector_store.add_embedding.assert_called_once()

    async def test_embedding_deleted_on_fragment_delete(
        self, client: AsyncClient, mock_vector_store
    ):
        """Test that embedding is deleted when fragment is deleted."""
        # Create a fragment
        create_response = await client.post(
            "/api/fragments",
            json={"content": "Test content"},
        )
        fragment_id = create_response.json()["id"]

        # Reset mock to track delete call
        mock_vector_store.reset_mock()

        # Delete the fragment
        await client.delete(f"/api/fragments/{fragment_id}")

        # Verify vector store delete was called
        mock_vector_store.delete_embedding.assert_called_once()

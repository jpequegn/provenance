"""Tests for the semantic search API endpoint."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from provo.api.main import app
from provo.api.routes.search import cosine_distance_to_similarity
from provo.storage import Database, reset_vector_store
from provo.storage.models import ContextFragment, SourceType
from provo.storage.vector_store import SearchResult


@pytest.fixture(autouse=True)
def reset_services():
    """Reset global services before each test."""
    from provo.processing.embeddings import reset_embedding_service

    reset_embedding_service()
    reset_vector_store()

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
    mock_store.search_similar.return_value = []
    return mock_store


@pytest.fixture
async def client(test_db, mock_embedding_service, mock_vector_store):
    """Create a test client with mocked services."""
    with (
        patch("provo.api.routes.search.get_database", return_value=test_db),
        patch(
            "provo.api.routes.search.get_embedding_service",
            return_value=mock_embedding_service,
        ),
        patch(
            "provo.api.routes.search.get_vector_store",
            return_value=mock_vector_store,
        ),
        patch("provo.api.main.init_database", new_callable=AsyncMock),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac


class TestCosineDistanceConversion:
    """Tests for the cosine distance to similarity conversion."""

    def test_identical_vectors(self):
        """Identical vectors have distance 0, similarity 1."""
        assert cosine_distance_to_similarity(0.0) == 1.0

    def test_orthogonal_vectors(self):
        """Orthogonal vectors have distance 1, similarity 0."""
        assert cosine_distance_to_similarity(1.0) == 0.0

    def test_opposite_vectors(self):
        """Opposite vectors have distance 2, similarity clamped to 0."""
        assert cosine_distance_to_similarity(2.0) == 0.0

    def test_partial_similarity(self):
        """Test intermediate distance values."""
        assert cosine_distance_to_similarity(0.5) == 0.5
        assert cosine_distance_to_similarity(0.25) == 0.75

    def test_negative_distance_clamped(self):
        """Negative distances (shouldn't happen) are clamped."""
        assert cosine_distance_to_similarity(-0.5) == 1.0


class TestSearchEndpoint:
    """Tests for GET /api/search endpoint."""

    async def test_search_empty_results(self, client: AsyncClient):
        """Test search when no results found."""
        response = await client.get("/api/search?q=test+query")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["query"] == "test query"
        assert data["results"] == []

    async def test_search_missing_query(self, client: AsyncClient):
        """Test that missing query returns 422."""
        response = await client.get("/api/search")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_search_empty_query(self, client: AsyncClient):
        """Test that empty query returns 422."""
        response = await client.get("/api/search?q=")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_search_with_results(
        self,
        client: AsyncClient,
        test_db: Database,
        mock_vector_store,
    ):
        """Test search returns results with scores."""
        # Create a fragment in the database
        fragment = ContextFragment(
            raw_content="We chose PostgreSQL for ACID compliance",
            project="billing",
            topics=["database", "architecture"],
        )
        await test_db.create_fragment(fragment)

        # Mock vector store to return this fragment
        mock_vector_store.search_similar.return_value = [
            SearchResult(
                fragment_id=fragment.id,
                distance=0.1,  # Close match
                metadata={"project": "billing"},
            )
        ]

        response = await client.get("/api/search?q=why+postgres")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["query"] == "why postgres"
        assert len(data["results"]) == 1

        result = data["results"][0]
        assert result["id"] == str(fragment.id)
        assert result["content"] == "We chose PostgreSQL for ACID compliance"
        assert result["score"] == pytest.approx(0.9, rel=0.01)  # 1 - 0.1
        assert result["project"] == "billing"

    async def test_search_results_have_correct_fields(
        self,
        client: AsyncClient,
        test_db: Database,
        mock_vector_store,
    ):
        """Test that search results include all expected fields."""
        fragment = ContextFragment(
            raw_content="Important decision about caching",
            summary="Caching strategy",
            source_type=SourceType.ZOOM,
            source_ref="https://zoom.us/meeting/123",
            topics=["caching", "performance"],
            project="infra",
        )
        await test_db.create_fragment(fragment)

        mock_vector_store.search_similar.return_value = [
            SearchResult(fragment_id=fragment.id, distance=0.2)
        ]

        response = await client.get("/api/search?q=caching")

        data = response.json()
        result = data["results"][0]

        assert "id" in result
        assert "content" in result
        assert "summary" in result
        assert "score" in result
        assert "source_type" in result
        assert "source_ref" in result
        assert "captured_at" in result
        assert "topics" in result
        assert "project" in result

        assert result["source_type"] == "zoom"
        assert result["topics"] == ["caching", "performance"]

    async def test_search_with_limit(
        self,
        client: AsyncClient,
        test_db: Database,
        mock_vector_store,
    ):
        """Test search respects limit parameter."""
        # Create multiple fragments
        fragments = []
        for i in range(5):
            fragment = ContextFragment(raw_content=f"Fragment {i}")
            await test_db.create_fragment(fragment)
            fragments.append(fragment)

        # Mock vector store to return all fragments
        mock_vector_store.search_similar.return_value = [
            SearchResult(fragment_id=f.id, distance=0.1 * i)
            for i, f in enumerate(fragments)
        ]

        response = await client.get("/api/search?q=test&limit=3")

        assert response.status_code == status.HTTP_200_OK
        # Vector store is called with limit
        mock_vector_store.search_similar.assert_called_once()
        call_kwargs = mock_vector_store.search_similar.call_args.kwargs
        assert call_kwargs["limit"] == 3

    async def test_search_with_project_filter(
        self,
        client: AsyncClient,
        mock_vector_store,
    ):
        """Test search with project filter."""
        response = await client.get("/api/search?q=test&project=billing")

        assert response.status_code == status.HTTP_200_OK
        # Vector store should be called with where filter
        mock_vector_store.search_similar.assert_called_once()
        call_kwargs = mock_vector_store.search_similar.call_args.kwargs
        assert call_kwargs["where"] == {"project": "billing"}

    async def test_search_limit_bounds(self, client: AsyncClient):
        """Test limit parameter validation."""
        # Too low
        response = await client.get("/api/search?q=test&limit=0")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Too high
        response = await client.get("/api/search?q=test&limit=200")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Valid max
        response = await client.get("/api/search?q=test&limit=100")
        assert response.status_code == status.HTTP_200_OK

    async def test_search_results_ordered_by_score(
        self,
        client: AsyncClient,
        test_db: Database,
        mock_vector_store,
    ):
        """Test that results are ordered by similarity score (highest first)."""
        # Create fragments with different relevance
        frag_high = ContextFragment(raw_content="Very relevant")
        frag_medium = ContextFragment(raw_content="Somewhat relevant")
        frag_low = ContextFragment(raw_content="Barely relevant")

        await test_db.create_fragment(frag_high)
        await test_db.create_fragment(frag_medium)
        await test_db.create_fragment(frag_low)

        # Return in order from vector store (closest first = lowest distance)
        mock_vector_store.search_similar.return_value = [
            SearchResult(fragment_id=frag_high.id, distance=0.1),
            SearchResult(fragment_id=frag_medium.id, distance=0.3),
            SearchResult(fragment_id=frag_low.id, distance=0.7),
        ]

        response = await client.get("/api/search?q=relevant")

        data = response.json()
        assert len(data["results"]) == 3

        # Scores should be in descending order (highest similarity first)
        scores = [r["score"] for r in data["results"]]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] > scores[1] > scores[2]

    async def test_search_handles_deleted_fragments(
        self,
        client: AsyncClient,
        test_db: Database,
        mock_vector_store,
    ):
        """Test that search gracefully handles orphaned embeddings."""
        # Create and then "delete" a fragment (only delete from DB, not vector store)
        fragment = ContextFragment(raw_content="Deleted fragment")
        await test_db.create_fragment(fragment)
        await test_db.delete_fragment(fragment.id)

        # Vector store still returns the ID
        mock_vector_store.search_similar.return_value = [
            SearchResult(fragment_id=fragment.id, distance=0.1)
        ]

        response = await client.get("/api/search?q=deleted")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Should not include the deleted fragment
        assert len(data["results"]) == 0


class TestSearchServiceIntegration:
    """Tests for search service integration."""

    async def test_embedding_service_called(
        self,
        client: AsyncClient,
        mock_embedding_service,
    ):
        """Test that the embedding service is called with the query."""
        await client.get("/api/search?q=why+did+we+choose+postgres")

        mock_embedding_service.embed.assert_called_once_with("why did we choose postgres")

    async def test_vector_store_called_with_embedding(
        self,
        client: AsyncClient,
        mock_embedding_service,
        mock_vector_store,
    ):
        """Test that vector store is called with the query embedding."""
        await client.get("/api/search?q=test+query")

        mock_vector_store.search_similar.assert_called_once()
        call_kwargs = mock_vector_store.search_similar.call_args.kwargs
        assert call_kwargs["query_vector"] == [0.1] * 768  # From mock

    async def test_embedding_service_error(
        self,
        client: AsyncClient,
        mock_embedding_service,
    ):
        """Test handling of embedding service errors."""
        mock_embedding_service.embed.side_effect = ConnectionError("Service down")

        response = await client.get("/api/search?q=test")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "Embedding service unavailable" in response.json()["detail"]

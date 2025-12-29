"""Tests for fragment linking via semantic similarity."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from provo.api.main import app
from provo.api.routes.fragments import (
    SIMILARITY_THRESHOLD,
    link_similar_fragments_background,
)
from provo.storage import Database, reset_vector_store
from provo.storage.models import ContextFragment, FragmentLink, LinkType


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
    mock_store.search_similar.return_value = []
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


class TestSimilarityThreshold:
    """Tests for the similarity threshold constant."""

    def test_threshold_value(self):
        """Test that threshold is 0.75 as specified in issue."""
        assert SIMILARITY_THRESHOLD == 0.75


class TestLinkSimilarFragmentsBackground:
    """Tests for the background fragment linking task."""

    async def test_creates_links_for_similar_fragments(self, test_db):
        """Test that links are created for similar fragments."""
        from uuid import UUID

        from provo.storage.vector_store import SearchResult

        # Create existing fragment
        existing_fragment = ContextFragment(
            raw_content="Test fragment about databases",
            project="test",
        )
        created_existing = await test_db.create_fragment(existing_fragment)

        # Create new fragment
        new_fragment = ContextFragment(
            raw_content="Another fragment about databases",
            project="test",
        )
        created_new = await test_db.create_fragment(new_fragment)

        # Mock vector store to return similar result
        mock_vector_store = AsyncMock()
        mock_vector_store.search_similar.return_value = [
            SearchResult(
                fragment_id=created_existing.id,
                distance=0.2,  # Distance = 1 - similarity, so this is 0.8 similarity
                metadata=None,
            ),
        ]

        with patch(
            "provo.api.routes.fragments.get_vector_store",
            return_value=mock_vector_store,
        ):
            with patch(
                "provo.api.routes.fragments.get_database",
                return_value=test_db,
            ):
                await link_similar_fragments_background(
                    str(created_new.id),
                    [0.1] * 768,
                )

        # Check that link was created
        related = await test_db.get_related_fragments(created_new.id)
        assert len(related) == 1
        assert related[0][0].id == created_existing.id
        assert related[0][1] == pytest.approx(0.8, rel=0.01)
        assert related[0][2] == LinkType.RELATES_TO

    async def test_skips_links_below_threshold(self, test_db):
        """Test that links are not created for low similarity."""
        from provo.storage.vector_store import SearchResult

        # Create fragments
        existing_fragment = ContextFragment(raw_content="Test", project="test")
        created_existing = await test_db.create_fragment(existing_fragment)

        new_fragment = ContextFragment(raw_content="Different", project="test")
        created_new = await test_db.create_fragment(new_fragment)

        # Mock vector store to return low similarity
        mock_vector_store = AsyncMock()
        mock_vector_store.search_similar.return_value = [
            SearchResult(
                fragment_id=created_existing.id,
                distance=0.4,  # Distance = 1 - similarity, so this is 0.6 similarity
                metadata=None,
            ),
        ]

        with patch(
            "provo.api.routes.fragments.get_vector_store",
            return_value=mock_vector_store,
        ):
            with patch(
                "provo.api.routes.fragments.get_database",
                return_value=test_db,
            ):
                await link_similar_fragments_background(
                    str(created_new.id),
                    [0.1] * 768,
                )

        # Check that no link was created
        related = await test_db.get_related_fragments(created_new.id)
        assert len(related) == 0

    async def test_skips_self_links(self, test_db):
        """Test that a fragment is not linked to itself."""
        from provo.storage.vector_store import SearchResult

        # Create fragment
        fragment = ContextFragment(raw_content="Test", project="test")
        created = await test_db.create_fragment(fragment)

        # Mock vector store to return self as most similar
        mock_vector_store = AsyncMock()
        mock_vector_store.search_similar.return_value = [
            SearchResult(
                fragment_id=created.id,  # Same fragment
                distance=0.0,  # Perfect match
                metadata=None,
            ),
        ]

        with patch(
            "provo.api.routes.fragments.get_vector_store",
            return_value=mock_vector_store,
        ):
            with patch(
                "provo.api.routes.fragments.get_database",
                return_value=test_db,
            ):
                await link_similar_fragments_background(
                    str(created.id),
                    [0.1] * 768,
                )

        # Check that no self-link was created
        related = await test_db.get_related_fragments(created.id)
        assert len(related) == 0


class TestGetRelatedFragmentsEndpoint:
    """Tests for GET /api/fragments/{id}/related endpoint."""

    async def test_get_related_empty(self, client: AsyncClient, test_db):
        """Test getting related fragments when none exist."""
        # Create a fragment
        response = await client.post(
            "/api/fragments",
            json={"content": "Test fragment"},
        )
        fragment_id = response.json()["id"]

        # Get related
        response = await client.get(f"/api/fragments/{fragment_id}/related")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["fragment_id"] == fragment_id
        assert data["related"] == []

    async def test_get_related_with_links(self, client: AsyncClient, test_db):
        """Test getting related fragments when links exist."""
        # Create two fragments
        response1 = await client.post(
            "/api/fragments",
            json={"content": "Fragment about databases"},
        )
        fragment1_id = response1.json()["id"]

        response2 = await client.post(
            "/api/fragments",
            json={"content": "Another fragment about databases"},
        )
        fragment2_id = response2.json()["id"]

        # Create link manually
        from uuid import UUID

        link = FragmentLink(
            source_id=UUID(fragment1_id),
            target_id=UUID(fragment2_id),
            link_type=LinkType.RELATES_TO,
            strength=0.85,
        )
        await test_db.create_link(link)

        # Get related for fragment1
        response = await client.get(f"/api/fragments/{fragment1_id}/related")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["related"]) == 1
        assert data["related"][0]["id"] == fragment2_id
        assert data["related"][0]["strength"] == pytest.approx(0.85)
        assert data["related"][0]["link_type"] == "relates_to"

    async def test_get_related_bidirectional(self, client: AsyncClient, test_db):
        """Test that links work bidirectionally."""
        # Create two fragments
        response1 = await client.post(
            "/api/fragments",
            json={"content": "Fragment A"},
        )
        fragment1_id = response1.json()["id"]

        response2 = await client.post(
            "/api/fragments",
            json={"content": "Fragment B"},
        )
        fragment2_id = response2.json()["id"]

        # Create link from 1 to 2
        from uuid import UUID

        link = FragmentLink(
            source_id=UUID(fragment1_id),
            target_id=UUID(fragment2_id),
            link_type=LinkType.RELATES_TO,
            strength=0.8,
        )
        await test_db.create_link(link)

        # Get related for fragment2 (should still find fragment1)
        response = await client.get(f"/api/fragments/{fragment2_id}/related")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["related"]) == 1
        assert data["related"][0]["id"] == fragment1_id

    async def test_get_related_filter_by_link_type(self, client: AsyncClient, test_db):
        """Test filtering related fragments by link type."""
        from uuid import UUID

        # Create fragments
        response1 = await client.post(
            "/api/fragments",
            json={"content": "Fragment A"},
        )
        fragment1_id = response1.json()["id"]

        response2 = await client.post(
            "/api/fragments",
            json={"content": "Fragment B"},
        )
        fragment2_id = response2.json()["id"]

        response3 = await client.post(
            "/api/fragments",
            json={"content": "Fragment C"},
        )
        fragment3_id = response3.json()["id"]

        # Create different types of links
        link1 = FragmentLink(
            source_id=UUID(fragment1_id),
            target_id=UUID(fragment2_id),
            link_type=LinkType.RELATES_TO,
            strength=0.8,
        )
        await test_db.create_link(link1)

        link2 = FragmentLink(
            source_id=UUID(fragment1_id),
            target_id=UUID(fragment3_id),
            link_type=LinkType.REFERENCES,
            strength=0.9,
        )
        await test_db.create_link(link2)

        # Filter by relates_to
        response = await client.get(
            f"/api/fragments/{fragment1_id}/related?link_type=relates_to"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["related"]) == 1
        assert data["related"][0]["id"] == fragment2_id

    async def test_get_related_not_found(self, client: AsyncClient):
        """Test getting related for non-existent fragment."""
        response = await client.get(
            "/api/fragments/00000000-0000-0000-0000-000000000000/related"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_get_related_invalid_id(self, client: AsyncClient):
        """Test getting related with invalid fragment ID."""
        response = await client.get("/api/fragments/not-a-uuid/related")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_get_related_invalid_link_type(self, client: AsyncClient, test_db):
        """Test filtering with invalid link type."""
        response = await client.post(
            "/api/fragments",
            json={"content": "Test"},
        )
        fragment_id = response.json()["id"]

        response = await client.get(
            f"/api/fragments/{fragment_id}/related?link_type=invalid_type"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid link type" in response.json()["detail"]

    async def test_get_related_limit(self, client: AsyncClient, test_db):
        """Test limiting related fragments."""
        from uuid import UUID

        # Create main fragment
        response = await client.post(
            "/api/fragments",
            json={"content": "Main fragment"},
        )
        main_id = response.json()["id"]

        # Create multiple related fragments
        for i in range(5):
            resp = await client.post(
                "/api/fragments",
                json={"content": f"Related fragment {i}"},
            )
            related_id = resp.json()["id"]
            link = FragmentLink(
                source_id=UUID(main_id),
                target_id=UUID(related_id),
                link_type=LinkType.RELATES_TO,
                strength=0.8 + i * 0.01,
            )
            await test_db.create_link(link)

        # Request with limit
        response = await client.get(
            f"/api/fragments/{main_id}/related?limit=2"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["related"]) == 2


class TestRelatedFragmentResponse:
    """Tests for related fragment response format."""

    async def test_response_contains_all_fields(self, client: AsyncClient, test_db):
        """Test that response contains all required fields."""
        from uuid import UUID

        # Create and link fragments
        response1 = await client.post(
            "/api/fragments",
            json={
                "content": "Fragment with full metadata",
                "project": "test-project",
                "topics": ["topic1", "topic2"],
            },
        )
        fragment1_id = response1.json()["id"]

        response2 = await client.post(
            "/api/fragments",
            json={"content": "Related fragment"},
        )
        fragment2_id = response2.json()["id"]

        link = FragmentLink(
            source_id=UUID(fragment1_id),
            target_id=UUID(fragment2_id),
            link_type=LinkType.RELATES_TO,
            strength=0.85,
        )
        await test_db.create_link(link)

        # Get related
        response = await client.get(f"/api/fragments/{fragment2_id}/related")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        related = data["related"][0]

        # Check all required fields are present
        assert "id" in related
        assert "content" in related
        assert "strength" in related
        assert "link_type" in related
        assert "source_type" in related
        assert "captured_at" in related
        assert "topics" in related
        assert "project" in related

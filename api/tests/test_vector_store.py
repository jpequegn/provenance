"""Tests for the ChromaDB vector store."""

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from provo.storage import SearchResult, VectorStore, reset_vector_store


@pytest.fixture(autouse=True)
def reset_global_store():
    """Reset the global vector store before each test."""
    reset_vector_store()
    yield
    reset_vector_store()


@pytest.fixture
def vector_store():
    """Create a temporary vector store for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStore(persist_path=Path(tmpdir) / "vectors")
        yield store
        store.reset()


@pytest.fixture
def sample_embedding():
    """Generate a sample embedding vector (768 dimensions for nomic-embed-text)."""
    return [0.1] * 768


@pytest.fixture
def sample_embeddings():
    """Generate multiple sample embeddings with varying values."""
    return [
        [0.1 + (i * 0.01)] * 768 for i in range(5)
    ]


class TestVectorStoreInitialization:
    """Tests for vector store initialization."""

    def test_creates_persist_directory(self, vector_store: VectorStore):
        """Test that initialization creates the persist directory."""
        # Force client initialization
        vector_store._get_client()
        assert vector_store.persist_path.exists()

    def test_creates_collection(self, vector_store: VectorStore):
        """Test that getting collection creates it if not exists."""
        collection = vector_store._get_collection()
        assert collection is not None
        assert collection.name == "fragments"

    def test_collection_uses_cosine_distance(self, vector_store: VectorStore):
        """Test that the collection uses cosine distance metric."""
        collection = vector_store._get_collection()
        # ChromaDB stores the distance metric in collection metadata
        assert collection.metadata is not None
        assert collection.metadata.get("hnsw:space") == "cosine"


class TestAddEmbedding:
    """Tests for adding embeddings."""

    async def test_add_single_embedding(
        self, vector_store: VectorStore, sample_embedding: list[float]
    ):
        """Test adding a single embedding."""
        fragment_id = uuid4()

        await vector_store.add_embedding(fragment_id, sample_embedding)

        assert vector_store.count == 1

    async def test_add_embedding_with_metadata(
        self, vector_store: VectorStore, sample_embedding: list[float]
    ):
        """Test adding an embedding with metadata."""
        fragment_id = uuid4()
        metadata = {"project": "test-project", "source": "zoom"}

        await vector_store.add_embedding(fragment_id, sample_embedding, metadata)

        # Verify by retrieving
        embedding = await vector_store.get_embedding(fragment_id)
        assert embedding is not None

    async def test_add_embedding_upserts_existing(
        self, vector_store: VectorStore, sample_embedding: list[float]
    ):
        """Test that adding an embedding for existing ID updates it."""
        fragment_id = uuid4()

        # Add initial
        await vector_store.add_embedding(fragment_id, sample_embedding)
        assert vector_store.count == 1

        # Update with different embedding
        new_embedding = [0.2] * 768
        await vector_store.add_embedding(fragment_id, new_embedding)

        # Should still be 1 (upserted, not duplicated)
        assert vector_store.count == 1

        # Verify it was updated
        retrieved = await vector_store.get_embedding(fragment_id)
        assert retrieved is not None
        assert retrieved[0] == pytest.approx(0.2)


class TestAddEmbeddingsBatch:
    """Tests for batch adding embeddings."""

    async def test_add_batch(
        self, vector_store: VectorStore, sample_embeddings: list[list[float]]
    ):
        """Test adding multiple embeddings in a batch."""
        items = [
            (uuid4(), emb, {"index": i})
            for i, emb in enumerate(sample_embeddings)
        ]

        await vector_store.add_embeddings_batch(items)

        assert vector_store.count == 5

    async def test_add_empty_batch(self, vector_store: VectorStore):
        """Test adding an empty batch does nothing."""
        await vector_store.add_embeddings_batch([])
        assert vector_store.count == 0


class TestSearchSimilar:
    """Tests for similarity search."""

    async def test_search_returns_results(
        self, vector_store: VectorStore, sample_embedding: list[float]
    ):
        """Test that search returns matching results."""
        fragment_id = uuid4()
        await vector_store.add_embedding(fragment_id, sample_embedding)

        results = await vector_store.search_similar(sample_embedding, limit=10)

        assert len(results) == 1
        assert results[0].fragment_id == fragment_id

    async def test_search_returns_ordered_by_distance(
        self, vector_store: VectorStore
    ):
        """Test that results are ordered by distance (most similar first)."""
        # Create embeddings with varying directions (not just magnitudes)
        # For cosine distance, vectors must point in different directions
        query = [1.0, 0.0] + [0.0] * 766  # Points along first axis

        # Close: nearly same direction
        close = [0.99, 0.1] + [0.0] * 766

        # Medium: 45 degrees off
        medium = [0.7, 0.7] + [0.0] * 766

        # Far: nearly orthogonal
        far = [0.1, 0.99] + [0.0] * 766

        id_close = uuid4()
        id_medium = uuid4()
        id_far = uuid4()

        await vector_store.add_embedding(id_far, far, {"name": "far"})
        await vector_store.add_embedding(id_close, close, {"name": "close"})
        await vector_store.add_embedding(id_medium, medium, {"name": "medium"})

        results = await vector_store.search_similar(query, limit=10)

        assert len(results) == 3
        # Most similar should be first (closest in cosine distance)
        assert results[0].fragment_id == id_close
        # Distances should be in ascending order
        assert results[0].distance <= results[1].distance <= results[2].distance

    async def test_search_respects_limit(self, vector_store: VectorStore):
        """Test that search respects the limit parameter."""
        # Add many embeddings
        for i in range(20):
            await vector_store.add_embedding(uuid4(), [0.1 + i * 0.01] * 768)

        results = await vector_store.search_similar([0.1] * 768, limit=5)

        assert len(results) == 5

    async def test_search_with_metadata_filter(
        self, vector_store: VectorStore, sample_embedding: list[float]
    ):
        """Test searching with metadata filter."""
        id1 = uuid4()
        id2 = uuid4()

        await vector_store.add_embedding(id1, sample_embedding, {"project": "alpha"})
        await vector_store.add_embedding(id2, sample_embedding, {"project": "beta"})

        results = await vector_store.search_similar(
            sample_embedding,
            limit=10,
            where={"project": "alpha"},
        )

        assert len(results) == 1
        assert results[0].fragment_id == id1

    async def test_search_empty_store_returns_empty(self, vector_store: VectorStore):
        """Test that searching an empty store returns empty list."""
        results = await vector_store.search_similar([0.1] * 768, limit=10)
        assert results == []

    async def test_search_result_includes_metadata(
        self, vector_store: VectorStore, sample_embedding: list[float]
    ):
        """Test that search results include metadata."""
        fragment_id = uuid4()
        metadata = {"project": "test", "source": "zoom"}

        await vector_store.add_embedding(fragment_id, sample_embedding, metadata)

        results = await vector_store.search_similar(sample_embedding, limit=10)

        assert len(results) == 1
        assert results[0].metadata is not None
        assert results[0].metadata.get("project") == "test"


class TestGetEmbedding:
    """Tests for getting individual embeddings."""

    async def test_get_existing_embedding(
        self, vector_store: VectorStore, sample_embedding: list[float]
    ):
        """Test getting an existing embedding."""
        fragment_id = uuid4()
        await vector_store.add_embedding(fragment_id, sample_embedding)

        retrieved = await vector_store.get_embedding(fragment_id)

        assert retrieved is not None
        assert len(retrieved) == 768
        assert retrieved[0] == pytest.approx(0.1)

    async def test_get_nonexistent_embedding(self, vector_store: VectorStore):
        """Test getting a non-existent embedding returns None."""
        result = await vector_store.get_embedding(uuid4())
        assert result is None


class TestDeleteEmbedding:
    """Tests for deleting embeddings."""

    async def test_delete_existing_embedding(
        self, vector_store: VectorStore, sample_embedding: list[float]
    ):
        """Test deleting an existing embedding."""
        fragment_id = uuid4()
        await vector_store.add_embedding(fragment_id, sample_embedding)
        assert vector_store.count == 1

        deleted = await vector_store.delete_embedding(fragment_id)

        assert deleted is True
        assert vector_store.count == 0

    async def test_delete_nonexistent_embedding(self, vector_store: VectorStore):
        """Test deleting a non-existent embedding returns False."""
        deleted = await vector_store.delete_embedding(uuid4())
        assert deleted is False


class TestDeleteEmbeddingsBatch:
    """Tests for batch deleting embeddings."""

    async def test_delete_batch(
        self, vector_store: VectorStore, sample_embeddings: list[list[float]]
    ):
        """Test deleting multiple embeddings."""
        ids = [uuid4() for _ in range(5)]
        items = [(id, emb, None) for id, emb in zip(ids, sample_embeddings)]
        await vector_store.add_embeddings_batch(items)
        assert vector_store.count == 5

        deleted = await vector_store.delete_embeddings_batch(ids[:3])

        assert deleted == 3
        assert vector_store.count == 2

    async def test_delete_empty_batch(self, vector_store: VectorStore):
        """Test deleting empty batch returns 0."""
        deleted = await vector_store.delete_embeddings_batch([])
        assert deleted == 0

    async def test_delete_batch_with_nonexistent(
        self, vector_store: VectorStore, sample_embedding: list[float]
    ):
        """Test deleting batch with some non-existent IDs."""
        existing_id = uuid4()
        await vector_store.add_embedding(existing_id, sample_embedding)

        deleted = await vector_store.delete_embeddings_batch([existing_id, uuid4(), uuid4()])

        assert deleted == 1
        assert vector_store.count == 0


class TestVectorStoreReset:
    """Tests for resetting the vector store."""

    async def test_reset_clears_all_data(
        self, vector_store: VectorStore, sample_embeddings: list[list[float]]
    ):
        """Test that reset clears all embeddings."""
        for i, emb in enumerate(sample_embeddings):
            await vector_store.add_embedding(uuid4(), emb)
        assert vector_store.count == 5

        vector_store.reset()

        assert vector_store.count == 0

    def test_reset_on_empty_store(self, vector_store: VectorStore):
        """Test that reset on empty store doesn't raise."""
        vector_store.reset()  # Should not raise
        assert vector_store.count == 0


class TestSearchResultDataclass:
    """Tests for the SearchResult dataclass."""

    def test_search_result_creation(self):
        """Test creating a SearchResult."""
        result = SearchResult(
            fragment_id=uuid4(),
            distance=0.15,
            metadata={"project": "test"},
        )

        assert result.distance == 0.15
        assert result.metadata is not None
        assert result.metadata["project"] == "test"

    def test_search_result_without_metadata(self):
        """Test creating a SearchResult without metadata."""
        result = SearchResult(
            fragment_id=uuid4(),
            distance=0.2,
        )

        assert result.metadata is None


class TestPersistence:
    """Tests for data persistence across store instances."""

    async def test_data_persists_across_instances(self, sample_embedding: list[float]):
        """Test that data persists when creating a new store instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = Path(tmpdir) / "vectors"
            fragment_id = uuid4()

            # First store instance - add data
            store1 = VectorStore(persist_path=persist_path)
            await store1.add_embedding(fragment_id, sample_embedding)
            assert store1.count == 1
            # Close by dereferencing
            del store1

            # Second store instance - verify data persists
            store2 = VectorStore(persist_path=persist_path)
            assert store2.count == 1

            retrieved = await store2.get_embedding(fragment_id)
            assert retrieved is not None
            assert len(retrieved) == 768

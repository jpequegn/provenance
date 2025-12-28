"""ChromaDB vector store for semantic search on fragment embeddings."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from chromadb.api import ClientAPI
    from chromadb.api.models.Collection import Collection

# Default paths
DEFAULT_VECTOR_PATH = Path("./data/vectors")
COLLECTION_NAME = "fragments"

# Type aliases for ChromaDB types
Metadata = dict[str, str | int | float | bool]


@dataclass
class SearchResult:
    """Result from a similarity search."""

    fragment_id: UUID
    distance: float
    metadata: Metadata | None = None


class VectorStore:
    """ChromaDB-based vector store for fragment embeddings.

    Provides persistent storage and similarity search for embeddings.
    Uses cosine distance for similarity calculations.
    """

    def __init__(
        self,
        persist_path: Path | str | None = None,
        collection_name: str = COLLECTION_NAME,
    ):
        """Initialize the vector store.

        Args:
            persist_path: Path to store ChromaDB data. Defaults to ./data/vectors/
            collection_name: Name of the collection. Defaults to 'fragments'
        """
        path_value = persist_path or os.getenv("VECTOR_STORE_PATH")
        self.persist_path = Path(path_value) if path_value else DEFAULT_VECTOR_PATH
        self.collection_name = collection_name
        self._client: ClientAPI | None = None
        self._collection: Collection | None = None

    def _ensure_directory(self) -> None:
        """Ensure the persist directory exists."""
        self.persist_path.mkdir(parents=True, exist_ok=True)

    def _get_client(self) -> ClientAPI:
        """Get or create the ChromaDB client."""
        if self._client is None:
            try:
                import chromadb

                self._ensure_directory()
                self._client = chromadb.PersistentClient(path=str(self.persist_path))
            except ImportError as e:
                raise ImportError(
                    "chromadb package not installed. Install with: pip install chromadb"
                ) from e
        return self._client

    def _get_collection(self) -> Collection:
        """Get or create the fragments collection."""
        if self._collection is None:
            client = self._get_client()
            # Use cosine distance for semantic similarity
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    async def add_embedding(
        self,
        fragment_id: UUID,
        vector: list[float],
        metadata: Metadata | None = None,
    ) -> None:
        """Add an embedding for a fragment.

        Args:
            fragment_id: The UUID of the fragment
            vector: The embedding vector
            metadata: Optional metadata to store with the embedding
        """
        collection = self._get_collection()
        # ChromaDB uses string IDs
        str_id = str(fragment_id)

        # Prepare metadata (ChromaDB requires specific types)
        chroma_metadata = metadata or {}

        collection.upsert(
            ids=[str_id],
            embeddings=[vector],  # type: ignore[arg-type]
            metadatas=[chroma_metadata] if chroma_metadata else None,
        )

    async def add_embeddings_batch(
        self,
        items: list[tuple[UUID, list[float], Metadata | None]],
    ) -> None:
        """Add multiple embeddings in a batch.

        Args:
            items: List of (fragment_id, vector, metadata) tuples
        """
        if not items:
            return

        collection = self._get_collection()

        ids = [str(item[0]) for item in items]
        embeddings: Sequence[Sequence[float]] = [item[1] for item in items]
        metadatas = [item[2] or {} for item in items]

        collection.upsert(
            ids=ids,
            embeddings=embeddings,  # type: ignore[arg-type]
            metadatas=metadatas if any(metadatas) else None,  # type: ignore[arg-type]
        )

    async def search_similar(
        self,
        query_vector: list[float],
        limit: int = 10,
        where: Metadata | None = None,
    ) -> list[SearchResult]:
        """Search for similar fragments by embedding.

        Args:
            query_vector: The query embedding vector
            limit: Maximum number of results to return
            where: Optional metadata filter

        Returns:
            List of SearchResult ordered by similarity (most similar first)
        """
        collection = self._get_collection()

        results: Any = collection.query(
            query_embeddings=[query_vector],  # type: ignore[arg-type]
            n_results=limit,
            where=where,  # type: ignore[arg-type]
            include=["distances", "metadatas"],  # type: ignore[list-item]
        )

        search_results: list[SearchResult] = []

        # ChromaDB returns nested lists for batch queries
        if results["ids"] and results["ids"][0]:
            ids = results["ids"][0]
            distances = results["distances"][0] if results["distances"] else [0.0] * len(ids)
            metadatas: list[Metadata | None] = (
                results["metadatas"][0] if results["metadatas"] else [None] * len(ids)
            )

            for i, fragment_id_str in enumerate(ids):
                meta = metadatas[i] if metadatas else None
                search_results.append(
                    SearchResult(
                        fragment_id=UUID(fragment_id_str),
                        distance=float(distances[i]),
                        metadata=dict(meta) if meta else None,
                    )
                )

        return search_results

    async def get_embedding(self, fragment_id: UUID) -> list[float] | None:
        """Get the embedding for a specific fragment.

        Args:
            fragment_id: The UUID of the fragment

        Returns:
            The embedding vector, or None if not found
        """
        collection = self._get_collection()
        str_id = str(fragment_id)

        result: Any = collection.get(ids=[str_id], include=["embeddings"])  # type: ignore[list-item]

        if result["embeddings"] is not None and len(result["embeddings"]) > 0:
            embedding = result["embeddings"][0]
            if embedding is not None:
                return list(embedding)
        return None

    async def delete_embedding(self, fragment_id: UUID) -> bool:
        """Delete an embedding for a fragment.

        Args:
            fragment_id: The UUID of the fragment

        Returns:
            True if deleted, False if not found
        """
        collection = self._get_collection()
        str_id = str(fragment_id)

        # Check if exists first
        existing = collection.get(ids=[str_id])
        if not existing["ids"]:
            return False

        collection.delete(ids=[str_id])
        return True

    async def delete_embeddings_batch(self, fragment_ids: list[UUID]) -> int:
        """Delete multiple embeddings.

        Args:
            fragment_ids: List of fragment UUIDs to delete

        Returns:
            Number of embeddings deleted
        """
        if not fragment_ids:
            return 0

        collection = self._get_collection()
        str_ids = [str(fid) for fid in fragment_ids]

        # Get existing to count
        existing = collection.get(ids=str_ids)
        count = len(existing["ids"]) if existing["ids"] else 0

        if count > 0:
            collection.delete(ids=str_ids)

        return count

    @property
    def count(self) -> int:
        """Return the number of embeddings in the collection."""
        collection = self._get_collection()
        return collection.count()

    def reset(self) -> None:
        """Delete all embeddings and reset the collection.

        Warning: This is destructive and cannot be undone.
        """
        client = self._get_client()
        try:
            client.delete_collection(self.collection_name)
        except ValueError:
            # Collection doesn't exist
            pass
        self._collection = None


# Global instance
_vector_store: VectorStore | None = None


def get_vector_store(
    persist_path: Path | str | None = None,
    collection_name: str = COLLECTION_NAME,
) -> VectorStore:
    """Get or create the global vector store instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(
            persist_path=persist_path,
            collection_name=collection_name,
        )
    return _vector_store


def reset_vector_store() -> None:
    """Reset the global vector store instance (useful for testing)."""
    global _vector_store
    _vector_store = None

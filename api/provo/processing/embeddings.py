"""Embedding service with provider abstraction for generating vector embeddings."""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import ollama
    import openai


class EmbeddingProvider(str, Enum):
    """Supported embedding providers."""

    OLLAMA = "ollama"
    OPENAI = "openai"


@dataclass
class EmbeddingResult:
    """Result of an embedding operation."""

    vector: list[float]
    model: str
    provider: EmbeddingProvider
    cached: bool = False


class EmbeddingProviderBase(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate embedding for text."""
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model name used by this provider."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension for this provider/model."""
        ...


class OllamaEmbeddingProvider(EmbeddingProviderBase):
    """Embedding provider using local Ollama."""

    # Model dimensions for common models
    MODEL_DIMENSIONS = {
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "all-minilm": 384,
        "snowflake-arctic-embed": 1024,
    }

    def __init__(self, model: str = "nomic-embed-text", host: str | None = None):
        self.model = model
        self.host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self._client: ollama.AsyncClient | None = None

    async def _get_client(self) -> ollama.AsyncClient:
        """Get or create Ollama async client."""
        if self._client is None:
            try:
                import ollama

                self._client = ollama.AsyncClient(host=self.host)
            except ImportError as e:
                raise ImportError(
                    "ollama package not installed. Install with: pip install ollama"
                ) from e
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for text using Ollama."""
        client = await self._get_client()
        try:
            response = await client.embeddings(model=self.model, prompt=text)
            return response["embedding"]
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Ollama at {self.host}: {e}") from e

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        # Ollama doesn't have native batch support, so we process sequentially
        # Could be optimized with asyncio.gather for parallel processing
        results = []
        for text in texts:
            embedding = await self.embed(text)
            results.append(embedding)
        return results

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def dimension(self) -> int:
        return self.MODEL_DIMENSIONS.get(self.model, 768)


class OpenAIEmbeddingProvider(EmbeddingProviderBase):
    """Embedding provider using OpenAI API."""

    MODEL_DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(self, model: str = "text-embedding-3-small", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client: openai.AsyncOpenAI | None = None

    async def _get_client(self) -> openai.AsyncOpenAI:
        """Get or create OpenAI async client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError(
                    "OpenAI API key not provided. Set OPENAI_API_KEY environment variable."
                )
            try:
                import openai

                self._client = openai.AsyncOpenAI(api_key=self.api_key)
            except ImportError as e:
                raise ImportError(
                    "openai package not installed. Install with: pip install openai"
                ) from e
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for text using OpenAI."""
        client = await self._get_client()
        response = await client.embeddings.create(model=self.model, input=text)
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts using OpenAI batch API."""
        client = await self._get_client()
        response = await client.embeddings.create(model=self.model, input=texts)
        # Sort by index to maintain order
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in sorted_data]

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def dimension(self) -> int:
        return self.MODEL_DIMENSIONS.get(self.model, 1536)


class EmbeddingCache:
    """Simple in-memory cache for embeddings."""

    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self._cache: dict[str, list[float]] = {}
        self._access_order: list[str] = []

    def _hash_text(self, text: str, model: str) -> str:
        """Create a hash key for text and model."""
        content = f"{model}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, text: str, model: str) -> list[float] | None:
        """Get cached embedding if available."""
        key = self._hash_text(text, model)
        if key in self._cache:
            # Move to end of access order (LRU)
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        return None

    def set(self, text: str, model: str, embedding: list[float]) -> None:
        """Cache an embedding."""
        key = self._hash_text(text, model)

        # Evict oldest if at capacity
        while len(self._cache) >= self.max_size and self._access_order:
            oldest_key = self._access_order.pop(0)
            self._cache.pop(oldest_key, None)

        self._cache[key] = embedding
        self._access_order.append(key)

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()
        self._access_order.clear()

    @property
    def size(self) -> int:
        """Return current cache size."""
        return len(self._cache)


class EmbeddingService:
    """Main embedding service with provider abstraction and caching."""

    def __init__(
        self,
        provider: EmbeddingProvider | None = None,
        model: str | None = None,
        cache_enabled: bool = True,
        cache_size: int = 10000,
    ):
        # Load from environment if not specified
        provider_name = provider or os.getenv("EMBED_PROVIDER", "ollama")
        if isinstance(provider_name, str):
            provider_name = EmbeddingProvider(provider_name.lower())

        self.provider_type = provider_name
        self.model = model or self._get_default_model(provider_name)
        self._provider: EmbeddingProviderBase | None = None
        self._cache = EmbeddingCache(max_size=cache_size) if cache_enabled else None

    def _get_default_model(self, provider: EmbeddingProvider) -> str:
        """Get default model for provider."""
        if provider == EmbeddingProvider.OLLAMA:
            return os.getenv("EMBED_MODEL", "nomic-embed-text")
        elif provider == EmbeddingProvider.OPENAI:
            return os.getenv("EMBED_MODEL", "text-embedding-3-small")
        return "nomic-embed-text"

    def _get_provider(self) -> EmbeddingProviderBase:
        """Get or create the embedding provider."""
        if self._provider is None:
            if self.provider_type == EmbeddingProvider.OLLAMA:
                self._provider = OllamaEmbeddingProvider(model=self.model)
            elif self.provider_type == EmbeddingProvider.OPENAI:
                self._provider = OpenAIEmbeddingProvider(model=self.model)
            else:
                raise ValueError(f"Unknown provider: {self.provider_type}")
        return self._provider

    async def embed(self, text: str) -> EmbeddingResult:
        """Generate embedding for text with caching."""
        provider = self._get_provider()

        # Check cache first
        if self._cache:
            cached = self._cache.get(text, provider.model_name)
            if cached is not None:
                return EmbeddingResult(
                    vector=cached,
                    model=provider.model_name,
                    provider=self.provider_type,
                    cached=True,
                )

        # Generate embedding
        vector = await provider.embed(text)

        # Cache the result
        if self._cache:
            self._cache.set(text, provider.model_name, vector)

        return EmbeddingResult(
            vector=vector,
            model=provider.model_name,
            provider=self.provider_type,
            cached=False,
        )

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts."""
        provider = self._get_provider()
        results: list[EmbeddingResult] = []
        texts_to_embed: list[tuple[int, str]] = []  # (original_index, text)

        # Check cache first for each text
        for i, text in enumerate(texts):
            if self._cache:
                cached = self._cache.get(text, provider.model_name)
                if cached is not None:
                    results.append(
                        EmbeddingResult(
                            vector=cached,
                            model=provider.model_name,
                            provider=self.provider_type,
                            cached=True,
                        )
                    )
                    continue
            texts_to_embed.append((i, text))
            results.append(None)  # type: ignore  # Placeholder

        # Embed uncached texts
        if texts_to_embed:
            uncached_texts = [t for _, t in texts_to_embed]
            embeddings = await provider.embed_batch(uncached_texts)

            for (original_idx, text), embedding in zip(texts_to_embed, embeddings):
                if self._cache:
                    self._cache.set(text, provider.model_name, embedding)
                results[original_idx] = EmbeddingResult(
                    vector=embedding,
                    model=provider.model_name,
                    provider=self.provider_type,
                    cached=False,
                )

        return results

    @property
    def dimension(self) -> int:
        """Return the embedding dimension for the current provider/model."""
        return self._get_provider().dimension

    @property
    def cache_stats(self) -> dict[str, int]:
        """Return cache statistics."""
        if self._cache:
            return {"size": self._cache.size, "max_size": self._cache.max_size}
        return {"size": 0, "max_size": 0, "enabled": False}


# Global service instance
_embedding_service: EmbeddingService | None = None


def get_embedding_service(
    provider: EmbeddingProvider | None = None,
    model: str | None = None,
) -> EmbeddingService:
    """Get or create the global embedding service."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(provider=provider, model=model)
    return _embedding_service


def reset_embedding_service() -> None:
    """Reset the global embedding service (useful for testing)."""
    global _embedding_service
    _embedding_service = None

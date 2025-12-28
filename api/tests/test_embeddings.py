"""Tests for the embedding service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from provo.processing import (
    EmbeddingCache,
    EmbeddingProvider,
    EmbeddingService,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
    reset_embedding_service,
)


@pytest.fixture(autouse=True)
def reset_service():
    """Reset the global embedding service before each test."""
    reset_embedding_service()
    yield
    reset_embedding_service()


class TestEmbeddingCache:
    """Tests for the embedding cache."""

    def test_cache_set_and_get(self):
        """Test basic cache set and get."""
        cache = EmbeddingCache(max_size=100)
        embedding = [0.1, 0.2, 0.3]

        cache.set("test text", "model-1", embedding)
        result = cache.get("test text", "model-1")

        assert result == embedding

    def test_cache_miss(self):
        """Test cache miss returns None."""
        cache = EmbeddingCache(max_size=100)

        result = cache.get("nonexistent", "model-1")

        assert result is None

    def test_cache_different_models(self):
        """Test that different models have separate cache entries."""
        cache = EmbeddingCache(max_size=100)
        embedding1 = [0.1, 0.2, 0.3]
        embedding2 = [0.4, 0.5, 0.6]

        cache.set("test text", "model-1", embedding1)
        cache.set("test text", "model-2", embedding2)

        assert cache.get("test text", "model-1") == embedding1
        assert cache.get("test text", "model-2") == embedding2

    def test_cache_eviction(self):
        """Test that oldest items are evicted when cache is full."""
        cache = EmbeddingCache(max_size=2)

        cache.set("text1", "model", [0.1])
        cache.set("text2", "model", [0.2])
        cache.set("text3", "model", [0.3])  # Should evict text1

        assert cache.get("text1", "model") is None
        assert cache.get("text2", "model") == [0.2]
        assert cache.get("text3", "model") == [0.3]

    def test_cache_lru_behavior(self):
        """Test LRU eviction - accessing an item moves it to end."""
        cache = EmbeddingCache(max_size=2)

        cache.set("text1", "model", [0.1])
        cache.set("text2", "model", [0.2])
        cache.get("text1", "model")  # Access text1, making text2 oldest
        cache.set("text3", "model", [0.3])  # Should evict text2

        assert cache.get("text1", "model") == [0.1]
        assert cache.get("text2", "model") is None
        assert cache.get("text3", "model") == [0.3]

    def test_cache_clear(self):
        """Test clearing the cache."""
        cache = EmbeddingCache(max_size=100)
        cache.set("text", "model", [0.1])

        cache.clear()

        assert cache.get("text", "model") is None
        assert cache.size == 0

    def test_cache_size(self):
        """Test cache size property."""
        cache = EmbeddingCache(max_size=100)

        assert cache.size == 0

        cache.set("text1", "model", [0.1])
        cache.set("text2", "model", [0.2])

        assert cache.size == 2


class TestOllamaEmbeddingProvider:
    """Tests for the Ollama embedding provider."""

    async def test_embed_success(self):
        """Test successful embedding generation."""
        provider = OllamaEmbeddingProvider(model="nomic-embed-text")

        mock_client = AsyncMock()
        mock_client.embeddings.return_value = {"embedding": [0.1, 0.2, 0.3]}

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.embed("test text")

        assert result == [0.1, 0.2, 0.3]
        mock_client.embeddings.assert_called_once_with(
            model="nomic-embed-text", prompt="test text"
        )

    async def test_embed_connection_error(self):
        """Test that connection errors are wrapped properly."""
        provider = OllamaEmbeddingProvider(model="nomic-embed-text")

        mock_client = AsyncMock()
        mock_client.embeddings.side_effect = Exception("Connection refused")

        with patch.object(provider, "_get_client", return_value=mock_client):
            with pytest.raises(ConnectionError) as exc_info:
                await provider.embed("test text")

        assert "Failed to connect to Ollama" in str(exc_info.value)

    async def test_embed_batch(self):
        """Test batch embedding."""
        provider = OllamaEmbeddingProvider(model="nomic-embed-text")

        mock_client = AsyncMock()
        mock_client.embeddings.side_effect = [
            {"embedding": [0.1, 0.2]},
            {"embedding": [0.3, 0.4]},
        ]

        with patch.object(provider, "_get_client", return_value=mock_client):
            results = await provider.embed_batch(["text1", "text2"])

        assert results == [[0.1, 0.2], [0.3, 0.4]]
        assert mock_client.embeddings.call_count == 2

    def test_model_name(self):
        """Test model name property."""
        provider = OllamaEmbeddingProvider(model="custom-model")
        assert provider.model_name == "custom-model"

    def test_dimension(self):
        """Test dimension property for known models."""
        provider1 = OllamaEmbeddingProvider(model="nomic-embed-text")
        assert provider1.dimension == 768

        provider2 = OllamaEmbeddingProvider(model="mxbai-embed-large")
        assert provider2.dimension == 1024

        # Unknown model defaults to 768
        provider3 = OllamaEmbeddingProvider(model="unknown-model")
        assert provider3.dimension == 768


class TestOpenAIEmbeddingProvider:
    """Tests for the OpenAI embedding provider."""

    async def test_embed_success(self):
        """Test successful embedding generation."""
        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-small", api_key="test-key"
        )

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

        mock_client = AsyncMock()
        mock_client.embeddings.create.return_value = mock_response

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.embed("test text")

        assert result == [0.1, 0.2, 0.3]
        mock_client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small", input="test text"
        )

    async def test_embed_batch(self):
        """Test batch embedding."""
        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-small", api_key="test-key"
        )

        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(index=0, embedding=[0.1, 0.2]),
            MagicMock(index=1, embedding=[0.3, 0.4]),
        ]

        mock_client = AsyncMock()
        mock_client.embeddings.create.return_value = mock_response

        with patch.object(provider, "_get_client", return_value=mock_client):
            results = await provider.embed_batch(["text1", "text2"])

        assert results == [[0.1, 0.2], [0.3, 0.4]]

    async def test_missing_api_key(self):
        """Test that missing API key raises error."""
        provider = OpenAIEmbeddingProvider(model="text-embedding-3-small", api_key=None)

        # Clear any environment variable
        with patch.dict("os.environ", {}, clear=True):
            provider.api_key = None
            with pytest.raises(ValueError) as exc_info:
                await provider._get_client()

        assert "API key not provided" in str(exc_info.value)

    def test_dimension(self):
        """Test dimension property for known models."""
        provider1 = OpenAIEmbeddingProvider(
            model="text-embedding-3-small", api_key="test"
        )
        assert provider1.dimension == 1536

        provider2 = OpenAIEmbeddingProvider(
            model="text-embedding-3-large", api_key="test"
        )
        assert provider2.dimension == 3072


class TestEmbeddingService:
    """Tests for the main embedding service."""

    async def test_embed_with_caching(self):
        """Test that embeddings are cached."""
        service = EmbeddingService(
            provider=EmbeddingProvider.OLLAMA,
            model="nomic-embed-text",
            cache_enabled=True,
        )

        mock_provider = AsyncMock()
        mock_provider.embed.return_value = [0.1, 0.2, 0.3]
        mock_provider.model_name = "nomic-embed-text"

        with patch.object(service, "_get_provider", return_value=mock_provider):
            # First call should hit the provider
            result1 = await service.embed("test text")
            assert result1.cached is False
            assert result1.vector == [0.1, 0.2, 0.3]

            # Second call should hit cache
            result2 = await service.embed("test text")
            assert result2.cached is True
            assert result2.vector == [0.1, 0.2, 0.3]

            # Provider should only be called once
            mock_provider.embed.assert_called_once()

    async def test_embed_without_caching(self):
        """Test embedding without cache."""
        service = EmbeddingService(
            provider=EmbeddingProvider.OLLAMA,
            model="nomic-embed-text",
            cache_enabled=False,
        )

        mock_provider = AsyncMock()
        mock_provider.embed.return_value = [0.1, 0.2, 0.3]
        mock_provider.model_name = "nomic-embed-text"

        with patch.object(service, "_get_provider", return_value=mock_provider):
            result1 = await service.embed("test text")
            result2 = await service.embed("test text")

            assert result1.cached is False
            assert result2.cached is False
            assert mock_provider.embed.call_count == 2

    async def test_embed_batch_with_partial_cache(self):
        """Test batch embedding with some items cached."""
        service = EmbeddingService(
            provider=EmbeddingProvider.OLLAMA,
            model="nomic-embed-text",
            cache_enabled=True,
        )

        mock_provider = AsyncMock()
        mock_provider.model_name = "nomic-embed-text"

        with patch.object(service, "_get_provider", return_value=mock_provider):
            # First, cache one text
            mock_provider.embed.return_value = [0.1, 0.2]
            await service.embed("text1")

            # Now batch embed including the cached text
            mock_provider.embed_batch.return_value = [[0.3, 0.4]]
            results = await service.embed_batch(["text1", "text2"])

            assert results[0].cached is True
            assert results[0].vector == [0.1, 0.2]
            assert results[1].cached is False
            assert results[1].vector == [0.3, 0.4]

            # Only text2 should have been sent to embed_batch
            mock_provider.embed_batch.assert_called_once_with(["text2"])

    async def test_embed_result_metadata(self):
        """Test that EmbeddingResult contains correct metadata."""
        service = EmbeddingService(
            provider=EmbeddingProvider.OLLAMA,
            model="nomic-embed-text",
        )

        mock_provider = AsyncMock()
        mock_provider.embed.return_value = [0.1, 0.2, 0.3]
        mock_provider.model_name = "nomic-embed-text"

        with patch.object(service, "_get_provider", return_value=mock_provider):
            result = await service.embed("test")

        assert result.model == "nomic-embed-text"
        assert result.provider == EmbeddingProvider.OLLAMA
        assert result.vector == [0.1, 0.2, 0.3]

    def test_cache_stats(self):
        """Test cache stats reporting."""
        service = EmbeddingService(cache_enabled=True, cache_size=500)
        stats = service.cache_stats

        assert stats["size"] == 0
        assert stats["max_size"] == 500

    def test_cache_stats_disabled(self):
        """Test cache stats when disabled."""
        service = EmbeddingService(cache_enabled=False)
        stats = service.cache_stats

        assert stats["size"] == 0
        assert "enabled" in stats and stats["enabled"] is False

    def test_provider_selection_ollama(self):
        """Test Ollama provider is selected correctly."""
        service = EmbeddingService(provider=EmbeddingProvider.OLLAMA)
        provider = service._get_provider()

        assert isinstance(provider, OllamaEmbeddingProvider)

    def test_provider_selection_openai(self):
        """Test OpenAI provider is selected correctly."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            service = EmbeddingService(provider=EmbeddingProvider.OPENAI)
            provider = service._get_provider()

        assert isinstance(provider, OpenAIEmbeddingProvider)

    def test_dimension_property(self):
        """Test dimension property delegates to provider."""
        service = EmbeddingService(
            provider=EmbeddingProvider.OLLAMA, model="nomic-embed-text"
        )
        assert service.dimension == 768

    def test_environment_config(self):
        """Test configuration from environment variables."""
        with patch.dict(
            "os.environ",
            {"EMBED_PROVIDER": "openai", "EMBED_MODEL": "text-embedding-3-large"},
        ):
            service = EmbeddingService()
            assert service.provider_type == EmbeddingProvider.OPENAI
            assert service.model == "text-embedding-3-large"

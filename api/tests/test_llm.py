"""Tests for the LLM service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from provo.processing import (
    LLMProvider,
    LLMService,
    OllamaLLMProvider,
    OpenAILLMProvider,
    reset_llm_service,
)


@pytest.fixture(autouse=True)
def reset_service():
    """Reset the global LLM service before each test."""
    reset_llm_service()
    yield
    reset_llm_service()


class TestOllamaLLMProvider:
    """Tests for the Ollama LLM provider."""

    async def test_generate_success(self):
        """Test successful text generation."""
        provider = OllamaLLMProvider(model="llama3.2")

        mock_client = AsyncMock()
        mock_client.chat.return_value = {"message": {"content": "Hello, world!"}}

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.generate("Say hello")

        assert result == "Hello, world!"
        mock_client.chat.assert_called_once()

    async def test_generate_with_system_prompt(self):
        """Test generation with system prompt."""
        provider = OllamaLLMProvider(model="llama3.2")

        mock_client = AsyncMock()
        mock_client.chat.return_value = {"message": {"content": "Response"}}

        with patch.object(provider, "_get_client", return_value=mock_client):
            await provider.generate(
                "User prompt", system_prompt="You are a helpful assistant"
            )

        # Check that both system and user messages were sent
        call_args = mock_client.chat.call_args
        messages = call_args.kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    async def test_generate_connection_error(self):
        """Test that connection errors are wrapped properly."""
        provider = OllamaLLMProvider(model="llama3.2")

        mock_client = AsyncMock()
        mock_client.chat.side_effect = Exception("Connection refused")

        with patch.object(provider, "_get_client", return_value=mock_client):
            with pytest.raises(ConnectionError) as exc_info:
                await provider.generate("test")

        assert "Failed to connect to Ollama" in str(exc_info.value)

    async def test_generate_json_success(self):
        """Test successful JSON generation."""
        provider = OllamaLLMProvider(model="llama3.2")

        mock_client = AsyncMock()
        mock_client.chat.return_value = {
            "message": {"content": '{"key": "value"}'}
        }

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.generate_json("Return JSON")

        assert result == {"key": "value"}
        # Check format="json" was passed
        call_args = mock_client.chat.call_args
        assert call_args.kwargs["format"] == "json"

    async def test_generate_json_parse_error(self):
        """Test JSON parse error handling."""
        provider = OllamaLLMProvider(model="llama3.2")

        mock_client = AsyncMock()
        mock_client.chat.return_value = {"message": {"content": "not valid json"}}

        with patch.object(provider, "_get_client", return_value=mock_client):
            with pytest.raises(ValueError) as exc_info:
                await provider.generate_json("Return JSON")

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_model_name(self):
        """Test model name property."""
        provider = OllamaLLMProvider(model="custom-model")
        assert provider.model_name == "custom-model"

    def test_default_host(self):
        """Test default host configuration."""
        provider = OllamaLLMProvider()
        assert provider.host == "http://localhost:11434"


class TestOpenAILLMProvider:
    """Tests for the OpenAI LLM provider."""

    async def test_generate_success(self):
        """Test successful text generation."""
        provider = OpenAILLMProvider(model="gpt-4o-mini", api_key="test-key")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello!"))]

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.generate("Say hello")

        assert result == "Hello!"
        mock_client.chat.completions.create.assert_called_once()

    async def test_generate_with_system_prompt(self):
        """Test generation with system prompt."""
        provider = OpenAILLMProvider(model="gpt-4o-mini", api_key="test-key")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Response"))]

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(provider, "_get_client", return_value=mock_client):
            await provider.generate(
                "User prompt", system_prompt="You are a helpful assistant"
            )

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    async def test_generate_json_success(self):
        """Test successful JSON generation."""
        provider = OpenAILLMProvider(model="gpt-4o-mini", api_key="test-key")

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"key": "value"}'))
        ]

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(provider, "_get_client", return_value=mock_client):
            result = await provider.generate_json("Return JSON")

        assert result == {"key": "value"}
        # Check response_format was passed
        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["response_format"] == {"type": "json_object"}

    async def test_generate_json_parse_error(self):
        """Test JSON parse error handling."""
        provider = OpenAILLMProvider(model="gpt-4o-mini", api_key="test-key")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="not json"))]

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(provider, "_get_client", return_value=mock_client):
            with pytest.raises(ValueError) as exc_info:
                await provider.generate_json("Return JSON")

        assert "Failed to parse JSON" in str(exc_info.value)

    async def test_missing_api_key(self):
        """Test that missing API key raises error."""
        provider = OpenAILLMProvider(model="gpt-4o-mini", api_key=None)

        with patch.dict("os.environ", {}, clear=True):
            provider.api_key = None
            with pytest.raises(ValueError) as exc_info:
                await provider._get_client()

        assert "API key not provided" in str(exc_info.value)

    def test_model_name(self):
        """Test model name property."""
        provider = OpenAILLMProvider(model="gpt-4", api_key="test")
        assert provider.model_name == "gpt-4"


class TestLLMService:
    """Tests for the main LLM service."""

    async def test_generate_returns_llm_result(self):
        """Test that generate returns LLMResult with metadata."""
        service = LLMService(provider=LLMProvider.OLLAMA, model="llama3.2")

        mock_provider = AsyncMock()
        mock_provider.generate.return_value = "Generated text"
        mock_provider.model_name = "llama3.2"

        with patch.object(service, "_get_provider", return_value=mock_provider):
            result = await service.generate("Test prompt")

        assert result.content == "Generated text"
        assert result.model == "llama3.2"
        assert result.provider == LLMProvider.OLLAMA

    async def test_generate_json_returns_tuple(self):
        """Test that generate_json returns tuple of (dict, LLMResult)."""
        service = LLMService(provider=LLMProvider.OLLAMA, model="llama3.2")

        mock_provider = AsyncMock()
        mock_provider.generate_json.return_value = {"key": "value"}
        mock_provider.model_name = "llama3.2"

        with patch.object(service, "_get_provider", return_value=mock_provider):
            json_result, llm_result = await service.generate_json("Return JSON")

        assert json_result == {"key": "value"}
        assert llm_result.model == "llama3.2"
        assert llm_result.provider == LLMProvider.OLLAMA

    def test_provider_selection_ollama(self):
        """Test Ollama provider is selected correctly."""
        service = LLMService(provider=LLMProvider.OLLAMA)
        provider = service._get_provider()

        assert isinstance(provider, OllamaLLMProvider)

    def test_provider_selection_openai(self):
        """Test OpenAI provider is selected correctly."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            service = LLMService(provider=LLMProvider.OPENAI)
            provider = service._get_provider()

        assert isinstance(provider, OpenAILLMProvider)

    def test_environment_config(self):
        """Test configuration from environment variables."""
        with patch.dict(
            "os.environ", {"LLM_PROVIDER": "openai", "LLM_MODEL": "gpt-4"}
        ):
            service = LLMService()
            assert service.provider_type == LLMProvider.OPENAI
            assert service.model == "gpt-4"

    def test_default_model_ollama(self):
        """Test default model for Ollama."""
        service = LLMService(provider=LLMProvider.OLLAMA)
        assert service.model == "llama3.2"

    def test_default_model_openai(self):
        """Test default model for OpenAI."""
        service = LLMService(provider=LLMProvider.OPENAI)
        assert service.model == "gpt-4o-mini"

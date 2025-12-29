"""LLM service with provider abstraction for text generation."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import ollama
    import openai


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OLLAMA = "ollama"
    OPENAI = "openai"


@dataclass
class LLMResult:
    """Result of an LLM generation."""

    content: str
    model: str
    provider: LLMProvider
    usage: dict[str, int] | None = None


class LLMProviderBase(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text from a prompt."""
        ...

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Generate JSON output from a prompt."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model name used by this provider."""
        ...


class OllamaLLMProvider(LLMProviderBase):
    """LLM provider using local Ollama."""

    def __init__(self, model: str = "llama3.2", host: str | None = None):
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

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text using Ollama."""
        client = await self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens

        try:
            response = await client.chat(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                options=options,  # type: ignore[arg-type]
            )
            return str(response["message"]["content"])  # type: ignore[index]
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Ollama at {self.host}: {e}") from e

    async def generate_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Generate JSON output using Ollama with format enforcement."""
        client = await self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await client.chat(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                options={"temperature": temperature},
                format="json",
            )
            content = str(response["message"]["content"])  # type: ignore[index]
            result: dict[str, Any] = json.loads(content)
            return result
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {e}") from e
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Ollama at {self.host}: {e}") from e

    @property
    def model_name(self) -> str:
        return self.model


class OpenAILLMProvider(LLMProviderBase):
    """LLM provider using OpenAI API."""

    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None):
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

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text using OpenAI."""
        client = await self._get_client()

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content
        return content or ""

    async def generate_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Generate JSON output using OpenAI with response format."""
        client = await self._get_client()

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await client.chat.completions.create(  # type: ignore[call-overload]
            model=self.model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or "{}"
        try:
            result: dict[str, Any] = json.loads(content)
            return result
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {e}") from e

    @property
    def model_name(self) -> str:
        return self.model


class LLMService:
    """Main LLM service with provider abstraction."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        model: str | None = None,
    ):
        # Load from environment if not specified
        provider_str = provider.value if provider else os.getenv("LLM_PROVIDER", "ollama")
        self.provider_type = LLMProvider(provider_str.lower())

        self.model = model or self._get_default_model(self.provider_type)
        self._provider: LLMProviderBase | None = None

    def _get_default_model(self, provider: LLMProvider) -> str:
        """Get default model for provider."""
        if provider == LLMProvider.OLLAMA:
            return os.getenv("LLM_MODEL", "llama3.2")
        elif provider == LLMProvider.OPENAI:
            return os.getenv("LLM_MODEL", "gpt-4o-mini")
        return "llama3.2"

    def _get_provider(self) -> LLMProviderBase:
        """Get or create the LLM provider."""
        if self._provider is None:
            if self.provider_type == LLMProvider.OLLAMA:
                self._provider = OllamaLLMProvider(model=self.model)
            elif self.provider_type == LLMProvider.OPENAI:
                self._provider = OpenAILLMProvider(model=self.model)
            else:
                raise ValueError(f"Unknown provider: {self.provider_type}")
        return self._provider

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        """Generate text from a prompt."""
        provider = self._get_provider()

        content = await provider.generate(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return LLMResult(
            content=content,
            model=provider.model_name,
            provider=self.provider_type,
        )

    async def generate_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any], LLMResult]:
        """Generate JSON output from a prompt.

        Returns a tuple of (parsed_json, llm_result).
        """
        provider = self._get_provider()

        json_result = await provider.generate_json(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
        )

        result = LLMResult(
            content=json.dumps(json_result),
            model=provider.model_name,
            provider=self.provider_type,
        )

        return json_result, result


# Global service instance
_llm_service: LLMService | None = None


def get_llm_service(
    provider: LLMProvider | None = None,
    model: str | None = None,
) -> LLMService:
    """Get or create the global LLM service."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService(provider=provider, model=model)
    return _llm_service


def reset_llm_service() -> None:
    """Reset the global LLM service (useful for testing)."""
    global _llm_service
    _llm_service = None

"""AI processing pipeline - chunking, embedding, extraction."""

from provo.processing.embeddings import (
    EmbeddingCache,
    EmbeddingProvider,
    EmbeddingProviderBase,
    EmbeddingResult,
    EmbeddingService,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_embedding_service,
    reset_embedding_service,
)
from provo.processing.extraction import (
    AssumptionExtractionResult,
    AssumptionExtractor,
    DecisionExtractor,
    ExtractionResult,
    get_assumption_extractor,
    get_decision_extractor,
    reset_assumption_extractor,
    reset_decision_extractor,
)
from provo.processing.llm import (
    LLMProvider,
    LLMProviderBase,
    LLMResult,
    LLMService,
    OllamaLLMProvider,
    OpenAILLMProvider,
    get_llm_service,
    reset_llm_service,
)

__all__ = [
    # Embeddings
    "EmbeddingCache",
    "EmbeddingProvider",
    "EmbeddingProviderBase",
    "EmbeddingResult",
    "EmbeddingService",
    "OllamaEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "get_embedding_service",
    "reset_embedding_service",
    # Extraction - Decisions
    "DecisionExtractor",
    "ExtractionResult",
    "get_decision_extractor",
    "reset_decision_extractor",
    # Extraction - Assumptions
    "AssumptionExtractor",
    "AssumptionExtractionResult",
    "get_assumption_extractor",
    "reset_assumption_extractor",
    # LLM
    "LLMProvider",
    "LLMProviderBase",
    "LLMResult",
    "LLMService",
    "OllamaLLMProvider",
    "OpenAILLMProvider",
    "get_llm_service",
    "reset_llm_service",
]

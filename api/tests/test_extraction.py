"""Tests for the decision and assumption extraction services."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from provo.processing import (
    AssumptionExtractor,
    DecisionExtractor,
    reset_assumption_extractor,
    reset_decision_extractor,
)
from provo.processing.extraction import (
    ASSUMPTION_SYSTEM_PROMPT,
    ASSUMPTION_USER_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_PROMPT,
)
from provo.processing.llm import LLMProvider, LLMResult


@pytest.fixture(autouse=True)
def reset_extractors():
    """Reset the global extractors before each test."""
    reset_decision_extractor()
    reset_assumption_extractor()
    yield
    reset_decision_extractor()
    reset_assumption_extractor()


class TestDecisionExtractor:
    """Tests for the DecisionExtractor class."""

    async def test_extract_decisions_single_decision(self):
        """Test extracting a single decision."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {
                "decisions": [
                    {
                        "what": "Use PostgreSQL for the database",
                        "why": "Better JSON support",
                        "confidence": 0.9,
                    }
                ]
            },
            LLMResult(
                content='{"decisions": [...]}',
                model="llama3.2",
                provider=LLMProvider.OLLAMA,
            ),
        )

        extractor = DecisionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_decisions(
            content="We decided to use PostgreSQL for better JSON support.",
            fragment_id=fragment_id,
        )

        assert len(result.decisions) == 1
        assert result.decisions[0].what == "Use PostgreSQL for the database"
        assert result.decisions[0].why == "Better JSON support"
        assert result.decisions[0].confidence == 0.9
        assert result.decisions[0].fragment_id == fragment_id
        assert result.model == "llama3.2"

    async def test_extract_decisions_multiple_decisions(self):
        """Test extracting multiple decisions."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {
                "decisions": [
                    {
                        "what": "Use React for frontend",
                        "why": "Team experience",
                        "confidence": 0.85,
                    },
                    {
                        "what": "Deploy to AWS",
                        "why": "Cost effective",
                        "confidence": 0.75,
                    },
                ]
            },
            LLMResult(
                content="...",
                model="llama3.2",
                provider=LLMProvider.OLLAMA,
            ),
        )

        extractor = DecisionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_decisions(
            content="We'll use React and deploy to AWS.",
            fragment_id=fragment_id,
        )

        assert len(result.decisions) == 2
        assert result.decisions[0].what == "Use React for frontend"
        assert result.decisions[1].what == "Deploy to AWS"

    async def test_extract_decisions_no_decisions(self):
        """Test when no decisions are found."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {"decisions": []},
            LLMResult(
                content='{"decisions": []}',
                model="llama3.2",
                provider=LLMProvider.OLLAMA,
            ),
        )

        extractor = DecisionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_decisions(
            content="Just chatting about the weather.",
            fragment_id=fragment_id,
        )

        assert len(result.decisions) == 0
        assert result.raw_response == {"decisions": []}

    async def test_extract_decisions_filters_low_confidence(self):
        """Test that low confidence decisions are filtered out."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {
                "decisions": [
                    {"what": "High confidence", "why": "", "confidence": 0.8},
                    {"what": "Low confidence", "why": "", "confidence": 0.3},
                ]
            },
            LLMResult(
                content="...",
                model="llama3.2",
                provider=LLMProvider.OLLAMA,
            ),
        )

        extractor = DecisionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_decisions(
            content="Some content",
            fragment_id=fragment_id,
            min_confidence=0.5,
        )

        assert len(result.decisions) == 1
        assert result.decisions[0].what == "High confidence"

    async def test_extract_decisions_custom_min_confidence(self):
        """Test custom minimum confidence threshold."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {
                "decisions": [
                    {"what": "Decision 1", "why": "", "confidence": 0.6},
                    {"what": "Decision 2", "why": "", "confidence": 0.85},
                ]
            },
            LLMResult(
                content="...",
                model="llama3.2",
                provider=LLMProvider.OLLAMA,
            ),
        )

        extractor = DecisionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_decisions(
            content="Some content",
            fragment_id=fragment_id,
            min_confidence=0.8,
        )

        assert len(result.decisions) == 1
        assert result.decisions[0].what == "Decision 2"

    async def test_extract_decisions_handles_json_error(self):
        """Test handling of JSON parse errors."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.side_effect = ValueError("Failed to parse JSON")

        extractor = DecisionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_decisions(
            content="Some content",
            fragment_id=fragment_id,
        )

        assert len(result.decisions) == 0
        assert result.raw_response == {}
        assert result.model == "unknown"

    async def test_extract_decisions_handles_connection_error(self):
        """Test handling of connection errors."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.side_effect = ConnectionError("Cannot connect")

        extractor = DecisionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        with pytest.raises(ConnectionError):
            await extractor.extract_decisions(
                content="Some content",
                fragment_id=fragment_id,
            )

    async def test_extract_decisions_uses_correct_prompts(self):
        """Test that the correct prompts are used."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {"decisions": []},
            LLMResult(content="", model="llama3.2", provider=LLMProvider.OLLAMA),
        )

        extractor = DecisionExtractor(llm_service=mock_llm)
        content = "Test content"

        await extractor.extract_decisions(content=content, fragment_id=uuid4())

        # Verify the call
        mock_llm.generate_json.assert_called_once()
        call_args = mock_llm.generate_json.call_args

        # Check user prompt contains the content
        user_prompt = call_args.args[0]
        assert content in user_prompt
        assert "decisions" in user_prompt.lower()

        # Check system prompt is passed
        assert call_args.kwargs["system_prompt"] == EXTRACTION_SYSTEM_PROMPT
        assert call_args.kwargs["temperature"] == 0.0

    async def test_extract_decisions_empty_why_field(self):
        """Test handling of empty 'why' field."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {
                "decisions": [
                    {"what": "Some decision", "why": "", "confidence": 0.7}
                ]
            },
            LLMResult(content="", model="llama3.2", provider=LLMProvider.OLLAMA),
        )

        extractor = DecisionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_decisions(
            content="Some content",
            fragment_id=fragment_id,
        )

        assert len(result.decisions) == 1
        assert result.decisions[0].why == ""

    async def test_extraction_result_contains_raw_response(self):
        """Test that ExtractionResult contains the raw LLM response."""
        raw_response = {
            "decisions": [
                {"what": "Decision", "why": "Reason", "confidence": 0.9}
            ]
        }
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            raw_response,
            LLMResult(content="", model="llama3.2", provider=LLMProvider.OLLAMA),
        )

        extractor = DecisionExtractor(llm_service=mock_llm)

        result = await extractor.extract_decisions(
            content="Content",
            fragment_id=uuid4(),
        )

        assert result.raw_response == raw_response


class TestExtractionPrompts:
    """Tests for the extraction prompts."""

    def test_system_prompt_contains_key_elements(self):
        """Test that system prompt contains required elements."""
        assert "decision" in EXTRACTION_SYSTEM_PROMPT.lower()
        assert "what" in EXTRACTION_SYSTEM_PROMPT.lower()
        assert "why" in EXTRACTION_SYSTEM_PROMPT.lower()
        assert "confidence" in EXTRACTION_SYSTEM_PROMPT.lower()

    def test_user_prompt_has_content_placeholder(self):
        """Test that user prompt has content placeholder."""
        assert "{content}" in EXTRACTION_USER_PROMPT

    def test_user_prompt_specifies_json_format(self):
        """Test that user prompt specifies JSON output format."""
        assert "json" in EXTRACTION_USER_PROMPT.lower()
        assert "decisions" in EXTRACTION_USER_PROMPT.lower()


class TestAssumptionExtractor:
    """Tests for the AssumptionExtractor class."""

    async def test_extract_assumptions_single_explicit(self):
        """Test extracting a single explicit assumption."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {
                "assumptions": [
                    {
                        "statement": "The API will remain stable",
                        "explicit": True,
                    }
                ]
            },
            LLMResult(
                content='{"assumptions": [...]}',
                model="llama3.2",
                provider=LLMProvider.OLLAMA,
            ),
        )

        extractor = AssumptionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_assumptions(
            content="We're assuming the API will remain stable.",
            fragment_id=fragment_id,
        )

        assert len(result.assumptions) == 1
        assert result.assumptions[0].statement == "The API will remain stable"
        assert result.assumptions[0].explicit is True
        assert result.assumptions[0].fragment_id == fragment_id
        assert result.assumptions[0].still_valid is None
        assert result.assumptions[0].invalidated_by is None
        assert result.model == "llama3.2"

    async def test_extract_assumptions_implicit(self):
        """Test extracting an implicit assumption."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {
                "assumptions": [
                    {
                        "statement": "Users have modern browsers",
                        "explicit": False,
                    }
                ]
            },
            LLMResult(
                content="...",
                model="llama3.2",
                provider=LLMProvider.OLLAMA,
            ),
        )

        extractor = AssumptionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_assumptions(
            content="Using React for the frontend.",
            fragment_id=fragment_id,
        )

        assert len(result.assumptions) == 1
        assert result.assumptions[0].explicit is False

    async def test_extract_assumptions_multiple(self):
        """Test extracting multiple assumptions."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {
                "assumptions": [
                    {"statement": "Server is online", "explicit": True},
                    {"statement": "Database has capacity", "explicit": False},
                ]
            },
            LLMResult(
                content="...",
                model="llama3.2",
                provider=LLMProvider.OLLAMA,
            ),
        )

        extractor = AssumptionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_assumptions(
            content="This will work if the server is online.",
            fragment_id=fragment_id,
        )

        assert len(result.assumptions) == 2
        assert result.assumptions[0].statement == "Server is online"
        assert result.assumptions[0].explicit is True
        assert result.assumptions[1].statement == "Database has capacity"
        assert result.assumptions[1].explicit is False

    async def test_extract_assumptions_no_assumptions(self):
        """Test when no assumptions are found."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {"assumptions": []},
            LLMResult(
                content='{"assumptions": []}',
                model="llama3.2",
                provider=LLMProvider.OLLAMA,
            ),
        )

        extractor = AssumptionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_assumptions(
            content="The meeting ended early.",
            fragment_id=fragment_id,
        )

        assert len(result.assumptions) == 0
        assert result.raw_response == {"assumptions": []}

    async def test_extract_assumptions_handles_json_error(self):
        """Test handling of JSON parse errors."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.side_effect = ValueError("Failed to parse JSON")

        extractor = AssumptionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_assumptions(
            content="Some content",
            fragment_id=fragment_id,
        )

        assert len(result.assumptions) == 0
        assert result.raw_response == {}
        assert result.model == "unknown"

    async def test_extract_assumptions_handles_connection_error(self):
        """Test handling of connection errors."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.side_effect = ConnectionError("Cannot connect")

        extractor = AssumptionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        with pytest.raises(ConnectionError):
            await extractor.extract_assumptions(
                content="Some content",
                fragment_id=fragment_id,
            )

    async def test_extract_assumptions_uses_correct_prompts(self):
        """Test that the correct prompts are used."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {"assumptions": []},
            LLMResult(content="", model="llama3.2", provider=LLMProvider.OLLAMA),
        )

        extractor = AssumptionExtractor(llm_service=mock_llm)
        content = "Test content"

        await extractor.extract_assumptions(content=content, fragment_id=uuid4())

        # Verify the call
        mock_llm.generate_json.assert_called_once()
        call_args = mock_llm.generate_json.call_args

        # Check user prompt contains the content
        user_prompt = call_args.args[0]
        assert content in user_prompt
        assert "assumptions" in user_prompt.lower()

        # Check system prompt is passed
        assert call_args.kwargs["system_prompt"] == ASSUMPTION_SYSTEM_PROMPT
        assert call_args.kwargs["temperature"] == 0.0

    async def test_extract_assumptions_skips_empty_statements(self):
        """Test that empty statement assumptions are skipped."""
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            {
                "assumptions": [
                    {"statement": "Valid assumption", "explicit": True},
                    {"statement": "", "explicit": True},  # Empty statement
                    {"statement": "Another valid", "explicit": False},
                ]
            },
            LLMResult(content="", model="llama3.2", provider=LLMProvider.OLLAMA),
        )

        extractor = AssumptionExtractor(llm_service=mock_llm)
        fragment_id = uuid4()

        result = await extractor.extract_assumptions(
            content="Some content",
            fragment_id=fragment_id,
        )

        assert len(result.assumptions) == 2
        assert result.assumptions[0].statement == "Valid assumption"
        assert result.assumptions[1].statement == "Another valid"

    async def test_extraction_result_contains_raw_response(self):
        """Test that AssumptionExtractionResult contains the raw LLM response."""
        raw_response = {
            "assumptions": [{"statement": "Test", "explicit": True}]
        }
        mock_llm = AsyncMock()
        mock_llm.generate_json.return_value = (
            raw_response,
            LLMResult(content="", model="llama3.2", provider=LLMProvider.OLLAMA),
        )

        extractor = AssumptionExtractor(llm_service=mock_llm)

        result = await extractor.extract_assumptions(
            content="Content",
            fragment_id=uuid4(),
        )

        assert result.raw_response == raw_response


class TestAssumptionPrompts:
    """Tests for the assumption extraction prompts."""

    def test_system_prompt_contains_key_elements(self):
        """Test that system prompt contains required elements."""
        assert "assumption" in ASSUMPTION_SYSTEM_PROMPT.lower()
        assert "explicit" in ASSUMPTION_SYSTEM_PROMPT.lower()
        assert "implicit" in ASSUMPTION_SYSTEM_PROMPT.lower()
        assert "statement" in ASSUMPTION_SYSTEM_PROMPT.lower()

    def test_user_prompt_has_content_placeholder(self):
        """Test that user prompt has content placeholder."""
        assert "{content}" in ASSUMPTION_USER_PROMPT

    def test_user_prompt_specifies_json_format(self):
        """Test that user prompt specifies JSON output format."""
        assert "json" in ASSUMPTION_USER_PROMPT.lower()
        assert "assumptions" in ASSUMPTION_USER_PROMPT.lower()

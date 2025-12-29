"""Decision and assumption extraction services using LLM."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from provo.processing.llm import LLMService, get_llm_service
from provo.storage.models import Assumption, Decision

logger = logging.getLogger(__name__)

# System prompt for decision extraction
EXTRACTION_SYSTEM_PROMPT = """\
You are an expert at identifying decisions from meeting transcripts and notes.

A decision is a choice that was made about how to proceed with something.
Look for patterns like:
- "We decided to..."
- "Let's go with..."
- "The choice is..."
- "We're going to..."
- "We'll use..."
- "The plan is..."

For each decision found, extract:
- what: A clear, concise statement of what was decided (the choice made)
- why: The reasoning or justification given for the decision (if mentioned)
- confidence: A score from 0.0 to 1.0 indicating how confident you are this is a real decision

Be conservative - only extract clear decisions, not vague intentions or possibilities.
If no clear decisions are found, return an empty list."""

EXTRACTION_USER_PROMPT = """\
Analyze the following text and extract any decisions made.

TEXT:
{content}

Respond with a JSON object containing a "decisions" array. Each decision should have:
- "what": string (the decision made)
- "why": string (the reasoning, or empty string if not stated)
- "confidence": number between 0.0 and 1.0

Example response:
{{"decisions": [{{"what": "Use PostgreSQL", "why": "JSON support", "confidence": 0.9}}]}}

If no decisions are found, respond with: {{"decisions": []}}"""


@dataclass
class ExtractionResult:
    """Result of decision extraction."""

    decisions: list[Decision]
    raw_response: dict[str, object]
    model: str


class DecisionExtractor:
    """Service for extracting decisions from text using LLM."""

    def __init__(self, llm_service: LLMService | None = None):
        """Initialize the extractor.

        Args:
            llm_service: Optional LLM service to use. If not provided,
                        uses the global service.
        """
        self._llm_service = llm_service

    def _get_llm_service(self) -> LLMService:
        """Get the LLM service (lazy initialization)."""
        if self._llm_service is None:
            self._llm_service = get_llm_service()
        return self._llm_service

    async def extract_decisions(
        self,
        content: str,
        fragment_id: UUID,
        *,
        min_confidence: float = 0.5,
    ) -> ExtractionResult:
        """Extract decisions from text content.

        Args:
            content: The text to analyze.
            fragment_id: The ID of the fragment being analyzed.
            min_confidence: Minimum confidence threshold for including decisions.

        Returns:
            ExtractionResult containing the extracted decisions.
        """
        llm = self._get_llm_service()

        # Format the prompt with the content
        user_prompt = EXTRACTION_USER_PROMPT.format(content=content)

        try:
            json_result, llm_result = await llm.generate_json(
                user_prompt,
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                temperature=0.0,
            )

            # Parse decisions from response
            decisions = []
            raw_decisions = json_result.get("decisions", [])

            for raw_decision in raw_decisions:
                confidence = float(raw_decision.get("confidence", 0.0))

                # Filter by minimum confidence
                if confidence < min_confidence:
                    logger.debug(
                        f"Skipping decision with confidence {confidence} < {min_confidence}"
                    )
                    continue

                decision = Decision(
                    fragment_id=fragment_id,
                    what=str(raw_decision.get("what", "")),
                    why=str(raw_decision.get("why", "")),
                    confidence=confidence,
                )
                decisions.append(decision)

            logger.info(
                f"Extracted {len(decisions)} decisions from fragment {fragment_id}"
            )

            return ExtractionResult(
                decisions=decisions,
                raw_response=json_result,
                model=llm_result.model,
            )

        except ValueError as e:
            # JSON parsing failed
            logger.error(f"Failed to parse LLM response: {e}")
            return ExtractionResult(
                decisions=[],
                raw_response={},
                model="unknown",
            )
        except Exception as e:
            logger.error(f"Decision extraction failed: {e}")
            raise


# Global extractor instance
_extractor: DecisionExtractor | None = None


def get_decision_extractor() -> DecisionExtractor:
    """Get or create the global decision extractor."""
    global _extractor
    if _extractor is None:
        _extractor = DecisionExtractor()
    return _extractor


def reset_decision_extractor() -> None:
    """Reset the global decision extractor (useful for testing)."""
    global _extractor
    _extractor = None


# ============== Assumption Extraction ==============

# System prompt for assumption extraction
ASSUMPTION_SYSTEM_PROMPT = """\
You are an expert at identifying assumptions from meeting transcripts and notes.

Assumptions include:
- Explicit constraints mentioned ("We're assuming the API is stable")
- Implicit beliefs underlying decisions ("Using React implies a modern browser")
- Dependencies on external factors ("This works if the server is online")
- Unstated prerequisites for plans to work

For each assumption found, extract:
- statement: A clear statement of what is being assumed
- explicit: true if the assumption was stated directly, false if it was implied

Be thorough - look for both stated and unstated assumptions.
If no assumptions are found, return an empty list."""

ASSUMPTION_USER_PROMPT = """\
Analyze the following text and extract any assumptions being made.

TEXT:
{content}

Respond with a JSON object containing an "assumptions" array. Each assumption should have:
- "statement": string (what is being assumed)
- "explicit": boolean (true if stated directly, false if implied)

Example response:
{{"assumptions": [{{"statement": "The API will remain stable", "explicit": true}}]}}

If no assumptions are found, respond with: {{"assumptions": []}}"""


@dataclass
class AssumptionExtractionResult:
    """Result of assumption extraction."""

    assumptions: list[Assumption]
    raw_response: dict[str, object]
    model: str


class AssumptionExtractor:
    """Service for extracting assumptions from text using LLM."""

    def __init__(self, llm_service: LLMService | None = None):
        """Initialize the extractor.

        Args:
            llm_service: Optional LLM service to use. If not provided,
                        uses the global service.
        """
        self._llm_service = llm_service

    def _get_llm_service(self) -> LLMService:
        """Get the LLM service (lazy initialization)."""
        if self._llm_service is None:
            self._llm_service = get_llm_service()
        return self._llm_service

    async def extract_assumptions(
        self,
        content: str,
        fragment_id: UUID,
    ) -> AssumptionExtractionResult:
        """Extract assumptions from text content.

        Args:
            content: The text to analyze.
            fragment_id: The ID of the fragment being analyzed.

        Returns:
            AssumptionExtractionResult containing the extracted assumptions.
        """
        llm = self._get_llm_service()

        # Format the prompt with the content
        user_prompt = ASSUMPTION_USER_PROMPT.format(content=content)

        try:
            json_result, llm_result = await llm.generate_json(
                user_prompt,
                system_prompt=ASSUMPTION_SYSTEM_PROMPT,
                temperature=0.0,
            )

            # Parse assumptions from response
            assumptions = []
            raw_assumptions = json_result.get("assumptions", [])

            for raw_assumption in raw_assumptions:
                statement = str(raw_assumption.get("statement", ""))
                if not statement:
                    continue

                assumption = Assumption(
                    fragment_id=fragment_id,
                    statement=statement,
                    explicit=bool(raw_assumption.get("explicit", True)),
                    still_valid=None,  # Not yet validated
                    invalidated_by=None,
                )
                assumptions.append(assumption)

            logger.info(
                f"Extracted {len(assumptions)} assumptions from fragment {fragment_id}"
            )

            return AssumptionExtractionResult(
                assumptions=assumptions,
                raw_response=json_result,
                model=llm_result.model,
            )

        except ValueError as e:
            # JSON parsing failed
            logger.error(f"Failed to parse LLM response: {e}")
            return AssumptionExtractionResult(
                assumptions=[],
                raw_response={},
                model="unknown",
            )
        except Exception as e:
            logger.error(f"Assumption extraction failed: {e}")
            raise


# Global assumption extractor instance
_assumption_extractor: AssumptionExtractor | None = None


def get_assumption_extractor() -> AssumptionExtractor:
    """Get or create the global assumption extractor."""
    global _assumption_extractor
    if _assumption_extractor is None:
        _assumption_extractor = AssumptionExtractor()
    return _assumption_extractor


def reset_assumption_extractor() -> None:
    """Reset the global assumption extractor (useful for testing)."""
    global _assumption_extractor
    _assumption_extractor = None

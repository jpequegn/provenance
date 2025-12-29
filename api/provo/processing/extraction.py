"""Decision extraction service using LLM."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from provo.processing.llm import LLMService, get_llm_service
from provo.storage.models import Decision

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

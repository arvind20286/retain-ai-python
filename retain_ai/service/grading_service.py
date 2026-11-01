import json
import logging
from typing import Optional
from google import genai
from google.genai import types

from retain_ai.adapter.openrouter_client import OpenRouterClient
from retain_ai.config import settings
from retain_ai.domain.grade_result import GradeResult
from retain_ai.domain.review_card import ReviewCard

logger = logging.getLogger(__name__)

GEMINI_GRADING_PROMPT = """
You are an expert technical evaluator assessing a software engineer's spoken answer during a spaced-repetition retrieval practice session.

EVALUATION TASK:
Compare the user's spoken (transcribed) answer against the question and the reference answer extracted from source material.

Question:
{question}

Reference Answer / Source Excerpt:
{reference_answer}

User's Spoken Answer (Transcribed):
{transcribed_answer}

GRADING CRITERIA:
1. Partial Credit is essential:
   - A conversational, informal, or rambling response that demonstrates accurate understanding of the core mechanism MUST receive a high score (80-100).
   - A short, confident, but factually wrong answer must receive a low score (< 50).
   - If the user grasps the main idea but missed a critical nuance or term, award partial credit (60-79) and set missed_key_point = true.
   - If the user says "I don't know" or skips, score 0.
2. Feedback must be spoken-friendly:
   - Provide 1 or 2 concise, supportive sentences that the voice partner can say out loud.
   - State what was correct and briefly clarify what was missed or wrong.
   - Keep it collegiate, not lecturing.
"""

class GradingService:
    """
    Grades spoken transcribed answers against a ReviewCard's reference answer.
    Supports OpenRouter (e.g. DeepSeek with reasoning) or Gemini.
    Returns a structured GradeResult (score 0-100, missed_key_point, feedback).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        openrouter_client: Optional[OpenRouterClient] = None,
        openrouter_api_key: Optional[str] = None,
        openrouter_model: Optional[str] = None,
    ):
        # OpenRouter client configuration
        if openrouter_client is not None:
            self.openrouter_client = openrouter_client
        elif openrouter_api_key is not None:
            self.openrouter_client = (
                OpenRouterClient(api_key=openrouter_api_key, model_name=openrouter_model)
                if openrouter_api_key
                else None
            )
        elif settings.openrouter_api_key:
            self.openrouter_client = OpenRouterClient(
                api_key=settings.openrouter_api_key,
                model_name=openrouter_model or settings.openrouter_model,
            )
        else:
            self.openrouter_client = None

        # Gemini fallback configuration
        self.gemini_api_key = api_key or settings.gemini_api_key
        self.model_name = model_name or settings.get_text_model_name()
        self.client = genai.Client(api_key=self.gemini_api_key) if self.gemini_api_key else None

    async def grade(self, card: ReviewCard, transcribed_answer: str) -> GradeResult:
        clean_answer = transcribed_answer.strip()
        if not clean_answer or clean_answer.lower() in ["i don't know", "idk", "skip", "pass", "no idea"]:
            return GradeResult(
                score=0,
                missed_key_point=True,
                feedback="No worries! Reviewing it now will help lock it into memory."
            )

        # 1. Prioritize OpenRouter if configured
        if self.openrouter_client and self.openrouter_client.client:
            logger.info("Using OpenRouterClient to grade card %s", card.id)
            return await self.openrouter_client.grade_answer(
                question=card.question,
                reference_answer=card.reference_answer,
                transcribed_answer=clean_answer,
            )

        # 2. Fallback to Gemini
        if self.client:
            return await self._grade_with_gemini(card, clean_answer)

        raise RuntimeError(
            "No LLM client configured for grading. "
            "Please configure OPENROUTER_API_KEY or GEMINI_API_KEY in your .env file."
        )

    async def _grade_with_gemini(self, card: ReviewCard, clean_answer: str) -> GradeResult:
        prompt = GEMINI_GRADING_PROMPT.format(
            question=card.question,
            reference_answer=card.reference_answer,
            transcribed_answer=clean_answer
        )

        logger.info("Calling Gemini (%s) to grade response for card %s...", self.model_name, card.id)
        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GradeResult,
                temperature=0.1,
            )
        )

        raw_text = response.text
        data = json.loads(raw_text)
        result = GradeResult.model_validate(data)
        logger.info("Graded card %s with Gemini: score=%d, missedKeyPoint=%s, feedback='%s'",
                    card.id, result.score, result.missed_key_point, result.feedback)
        return result

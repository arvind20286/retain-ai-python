import json
import logging
import re
from typing import Any, Optional
from openai import AsyncOpenAI
from pydantic import BaseModel

from retain_ai.config import settings
from retain_ai.domain.grade_result import GradeResult

logger = logging.getLogger(__name__)

GRADING_SYSTEM_PROMPT = """
You are an expert technical evaluator assessing a software engineer's spoken answer during a spaced-repetition retrieval practice session.

EVALUATION TASK:
Compare the user's spoken (transcribed) answer against the question and the reference answer extracted from source material.

GRADING CRITERIA:
1. Partial Credit is essential:
   - A conversational, informal, or rambling response that demonstrates accurate understanding of the core mechanism MUST receive a high score (80-100).
   - A short, confident, but factually wrong answer must receive a low score (< 50).
   - If the user grasps the main idea but missed a critical nuance or term, award partial credit (60-79) and set missed_key_point = true.
   - If the user says "I don't know" or skips, score 0 and set missed_key_point = true.
2. Feedback must be spoken-friendly:
   - Provide 1 or 2 concise, supportive sentences that the voice partner can say out loud.
   - State what was correct and briefly clarify what was missed or wrong.
   - Keep it collegiate, not lecturing.

RESPONSE FORMAT:
You MUST respond strictly with a valid JSON object matching this schema:
{
  "score": <int 0-100>,
  "missed_key_point": <bool>,
  "feedback": "<concise 1-2 sentence spoken feedback>"
}
"""

GRADING_USER_TEMPLATE = """
Question:
{question}

Reference Answer / Source Excerpt:
{reference_answer}

User's Spoken Answer (Transcribed):
{transcribed_answer}
"""

class OpenRouterClient:
    """
    Wraps the OpenAI-compatible OpenRouter API (https://openrouter.ai).
    Provides structured generation with optional reasoning (e.g. DeepSeek-R1 / V3).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or settings.openrouter_api_key
        self.model_name = model_name or settings.openrouter_model
        self.base_url = base_url or settings.openrouter_base_url

        self.client = (
            AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
            if self.api_key
            else None
        )

    @staticmethod
    def extract_json(raw_text: str) -> dict[str, Any]:
        """Extracts JSON object from response text, handling markdown fences and leading/trailing text."""
        text = raw_text.strip()
        if "```" in text:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
            if match:
                text = match.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]
        return json.loads(text)

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        enable_reasoning: bool = True,
        temperature: float = 0.1,
        response_format: Optional[dict[str, str]] = None,
    ) -> tuple[str, Optional[str]]:
        """
        Sends a completion request to OpenRouter.
        Returns a tuple of (content, reasoning_details).
        """
        if not self.client:
            raise RuntimeError(
                "OpenRouter client not initialized — OPENROUTER_API_KEY is missing or empty."
            )

        active_model = model or self.model_name
        extra_body = {"reasoning": {"enabled": True}} if enable_reasoning else None

        kwargs: dict[str, Any] = {
            "model": active_model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format:
            kwargs["response_format"] = response_format
        if extra_body:
            kwargs["extra_body"] = extra_body

        try:
            response = await self.client.chat.completions.create(**kwargs)
        except Exception as e:
            if extra_body:
                logger.warning(
                    "OpenRouter request with reasoning failed (%s). Retrying without extra_body...",
                    e,
                )
                kwargs.pop("extra_body", None)
                response = await self.client.chat.completions.create(**kwargs)
            else:
                raise

        choice = response.choices[0]
        content = choice.message.content or ""
        reasoning = (
            getattr(choice.message, "reasoning_details", None)
            or getattr(choice.message, "reasoning", None)
        )
        return content, reasoning

    async def grade_answer(
        self,
        question: str,
        reference_answer: str,
        transcribed_answer: str,
        model: Optional[str] = None,
    ) -> GradeResult:
        """
        Evaluates a user's answer against the reference answer using OpenRouter.
        Returns a validated GradeResult.
        """
        clean_answer = transcribed_answer.strip()
        if not clean_answer or clean_answer.lower() in [
            "i don't know", "idk", "skip", "pass", "no idea"
        ]:
            return GradeResult(
                score=0,
                missed_key_point=True,
                feedback="No worries! Reviewing it now will help lock it into memory.",
            )

        user_content = GRADING_USER_TEMPLATE.format(
            question=question,
            reference_answer=reference_answer,
            transcribed_answer=clean_answer,
        )

        messages = [
            {"role": "system", "content": GRADING_SYSTEM_PROMPT.strip()},
            {"role": "user", "content": user_content.strip()},
        ]

        logger.info(
            "Calling OpenRouter (%s) to grade response...",
            model or self.model_name,
        )
        content, reasoning = await self.complete(
            messages=messages,
            model=model,
            enable_reasoning=True,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        if reasoning:
            logger.info("OpenRouter grading reasoning: %s", str(reasoning)[:120])

        data = self.extract_json(content)
        result = GradeResult.model_validate(data)
        logger.info(
            "Graded card: score=%d, missedKeyPoint=%s, feedback='%s'",
            result.score,
            result.missed_key_point,
            result.feedback,
        )
        return result


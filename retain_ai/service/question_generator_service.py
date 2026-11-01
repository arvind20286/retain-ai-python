from datetime import datetime, timezone
import json
import logging
import re
from typing import Optional
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from retain_ai.config import settings
from retain_ai.domain.article import Article
from retain_ai.domain.review_card import ReviewCard

logger = logging.getLogger(__name__)

class QAPair(BaseModel):
    question: str = Field(description="A clear, conversational retrieval question testing a key concept, trade-off, or design decision")
    reference_answer: str = Field(description="A concise 1-3 sentence source-grounded answer containing the key facts/mechanisms")

class GeneratedQuestionsResponse(BaseModel):
    cards: list[QAPair] = Field(description="3 to 5 high-yield question and reference answer pairs")

QUESTION_GEN_PROMPT = """
You are an expert technical tutor preparing spaced repetition review cards for a software engineer.
Analyze the following article content and extracted personal notes.
Extract 3 to 5 high-yield, specific question/reference-answer pairs.

GUIDELINES:
1. Questions should test understanding, trade-offs, mechanisms, and core concepts (NOT trivia or superficial dates).
2. The question must be natural when read out loud in a voice conversation.
3. The reference answer should be concise (1-3 sentences), factual, and highlight the necessary key points required to demonstrate mastery.
4. Ground everything strictly in the provided text.
5. Return your final answer strictly as a valid JSON object matching this schema:
{{
  "cards": [
    {{
      "question": "The question here",
      "reference_answer": "The reference answer here"
    }}
  ]
}}

Article Title: {title}
Tags: {tags}
User Notes / Insight:
{notes}

Article Content:
{content}
"""

class QuestionGeneratorService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        openrouter_api_key: Optional[str] = None,
        openrouter_model: Optional[str] = None,
        openrouter_base_url: Optional[str] = None,
        max_retries: int = 3,
    ):
        self.max_retries = max_retries
        # OpenRouter configuration
        if openrouter_api_key is not None:
            self.openrouter_api_key = openrouter_api_key
        elif api_key and not settings.openrouter_api_key:
            self.openrouter_api_key = ""
        else:
            self.openrouter_api_key = settings.openrouter_api_key

        self.openrouter_model = openrouter_model or settings.openrouter_model
        self.openrouter_base_url = openrouter_base_url or settings.openrouter_base_url

        if self.openrouter_api_key:
            self.openrouter_client = AsyncOpenAI(
                base_url=self.openrouter_base_url,
                api_key=self.openrouter_api_key,
            )
        else:
            self.openrouter_client = None

        # Gemini fallback configuration
        self.gemini_api_key = api_key or settings.gemini_api_key
        self.model_name = model_name or settings.get_text_model_name()
        self.client = genai.Client(api_key=self.gemini_api_key) if self.gemini_api_key else None

    @staticmethod
    def _extract_json(text: str) -> dict:
        text = text.strip()
        if "```" in text:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
            if match:
                text = match.group(1).strip()
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx : end_idx + 1]
        return json.loads(text)

    async def generate_cards_for(self, article: Article) -> list[ReviewCard]:
        """
        Generates 3-5 structured question/answer pairs from an article using OpenRouter
        (with reasoning) or Gemini.
        """
        title = article.title or "Untitled"
        content = (article.content or "").strip()
        notes = (article.user_notes or "").strip()
        tags = ", ".join(article.tags or [])

        if not content and not notes:
            logger.warning("Article %s has no content or notes. Skipping card generation.", article.id)
            return []

        prompt = QUESTION_GEN_PROMPT.format(
            title=title,
            tags=tags,
            notes=notes or "None provided",
            content=content[:12000]
        )

        # Prioritize OpenRouter if configured
        if self.openrouter_client:
            return await self._generate_with_openrouter(article, prompt)

        # Fallback to Gemini
        if self.client:
            return await self._generate_with_gemini(article, prompt)

        raise RuntimeError(
            "No LLM API key configured for question generation. "
            "Please configure OPENROUTER_API_KEY or GEMINI_API_KEY in your .env file."
        )

    async def _generate_with_openrouter(self, article: Article, prompt: str) -> list[ReviewCard]:
        title = article.title or "Untitled"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert technical tutor preparing spaced repetition cards. "
                    "You must output only a valid JSON object matching the requested schema."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]
        extra_body = {"reasoning": {"enabled": True}}

        for attempt in range(1, self.max_retries + 1):
            logger.info(
                "Calling OpenRouter (%s) (attempt %d/%d) to generate questions for article '%s'...",
                self.openrouter_model, attempt, self.max_retries, title
            )
            try:
                try:
                    response = await self.openrouter_client.chat.completions.create(
                        model=self.openrouter_model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        extra_body=extra_body,
                        temperature=0.3,
                    )
                except Exception as e:
                    logger.warning(
                        "OpenRouter request with reasoning/json_object failed (%s). Retrying standard chat completion...",
                        e
                    )
                    response = await self.openrouter_client.chat.completions.create(
                        model=self.openrouter_model,
                        messages=messages,
                        temperature=0.3,
                    )

                choice = response.choices[0]
                raw_text = choice.message.content or ""
                reasoning = getattr(choice.message, "reasoning_details", None) or getattr(choice.message, "reasoning", None)
                if reasoning:
                    logger.info("OpenRouter reasoning captured successfully.")

                data = self._extract_json(raw_text)
                parsed = GeneratedQuestionsResponse.model_validate(data)

                if not parsed.cards:
                    raise ValueError("Generated response contains an empty list of cards.")

                now = datetime.now(timezone.utc)
                cards = []
                for item in parsed.cards:
                    card = ReviewCard(
                        article_id=article.id,
                        question=item.question.strip(),
                        reference_answer=item.reference_answer.strip(),
                        stability=0.4,
                        difficulty=5.0,
                        last_reviewed_at=None,
                        next_review_at=now,
                        times_reviewed=0
                    )
                    cards.append(card)

                logger.info("OpenRouter generated %d card(s) for article '%s'", len(cards), title)
                return cards

            except Exception as e:
                logger.warning(
                    "Attempt %d/%d failed to match schema for article '%s': %s",
                    attempt, self.max_retries, title, e
                )

        logger.error(
            "Failed to generate valid cards matching schema for article '%s' after %d attempts. Skipping article.",
            title, self.max_retries
        )
        return []

    async def _generate_with_gemini(self, article: Article, prompt: str) -> list[ReviewCard]:
        title = article.title or "Untitled"

        for attempt in range(1, self.max_retries + 1):
            logger.info(
                "Calling Gemini (%s) (attempt %d/%d) to generate questions for article '%s'...",
                self.model_name, attempt, self.max_retries, title
            )
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=GeneratedQuestionsResponse,
                        temperature=0.3,
                    )
                )

                raw_text = response.text
                data = self._extract_json(raw_text)
                parsed = GeneratedQuestionsResponse.model_validate(data)

                if not parsed.cards:
                    raise ValueError("Generated response contains an empty list of cards.")

                now = datetime.now(timezone.utc)
                cards = []
                for item in parsed.cards:
                    card = ReviewCard(
                        article_id=article.id,
                        question=item.question.strip(),
                        reference_answer=item.reference_answer.strip(),
                        stability=0.4,
                        difficulty=5.0,
                        last_reviewed_at=None,
                        next_review_at=now,
                        times_reviewed=0
                    )
                    cards.append(card)

                logger.info("Gemini generated %d card(s) for article '%s'", len(cards), title)
                return cards

            except Exception as e:
                logger.warning(
                    "Attempt %d/%d failed to match schema for article '%s': %s",
                    attempt, self.max_retries, title, e
                )

        logger.error(
            "Failed to generate valid cards matching schema for article '%s' after %d attempts. Skipping article.",
            title, self.max_retries
        )
        return []

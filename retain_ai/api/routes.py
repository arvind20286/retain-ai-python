import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from retain_ai.adapter.notion.notion_client import NotionClient
from retain_ai.adapter.notion.notion_content_source import NotionContentSource
from retain_ai.adapter.openrouter_client import OpenRouterClient
from retain_ai.config import settings
from retain_ai.database import get_db
from retain_ai.domain.grade_result import GradeResult
from retain_ai.domain.review_card import ReviewCardSchema
from retain_ai.repository.article_repository import ArticleRepository
from retain_ai.repository.review_card_repository import ReviewCardRepository
from retain_ai.service.grading_service import GradingService
from retain_ai.service.question_generator_service import QuestionGeneratorService
from retain_ai.service.review_orchestrator import ReviewOrchestrator
from retain_ai.service.review_service import ReviewService
from retain_ai.service.scheduler_service import SchedulerService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["review"])

def get_services(session: AsyncSession = Depends(get_db)):
    article_repo = ArticleRepository(session)
    card_repo = ReviewCardRepository(session)

    notion_client = NotionClient(
        api_token=settings.notion_api_token,
        datasource_id=settings.notion_datasource_id
    )
    content_source = NotionContentSource(notion_client, article_repo)

    question_gen = QuestionGeneratorService(
        api_key=settings.gemini_api_key,
        model_name=settings.get_text_model_name(),
        openrouter_api_key=settings.openrouter_api_key,
        openrouter_model=settings.openrouter_model,
        openrouter_base_url=settings.openrouter_base_url,
    )
    openrouter_client = (
        OpenRouterClient(
            api_key=settings.openrouter_api_key,
            model_name=settings.openrouter_model,
            base_url=settings.openrouter_base_url,
        )
        if settings.openrouter_api_key
        else None
    )
    grading_svc = GradingService(
        openrouter_client=openrouter_client,
        api_key=settings.gemini_api_key,
        model_name=settings.get_text_model_name(),
    )
    scheduler_svc = SchedulerService(card_repo)
    orchestrator = ReviewOrchestrator(scheduler_svc, grading_svc)
    review_svc = ReviewService(article_repo, card_repo, content_source, question_gen)

    return {
        "article_repo": article_repo,
        "card_repo": card_repo,
        "review_svc": review_svc,
        "orchestrator": orchestrator,
        "grading_svc": grading_svc,
        "question_gen": question_gen,
    }

@router.post("/sync")
async def trigger_sync(deps: dict = Depends(get_services)):
    """
    Manually triggers a Notion -> local DB sync, then extracts review questions
    using Gemini for any newly fetched articles.
    """
    review_svc = deps["review_svc"]
    try:
        result = await review_svc.sync_articles()
        return {"status": "ok", **result}
    except Exception as e:
        logger.error("Sync failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

@router.get("/cards/due", response_model=list[ReviewCardSchema])
async def get_due_cards(deps: dict = Depends(get_services)):
    """
    Returns all review cards due right now to drive the study queue.
    """
    orchestrator: ReviewOrchestrator = deps["orchestrator"]
    cards = await orchestrator.next_cards_for_session()
    return [ReviewCardSchema.model_validate(c) for c in cards]

class GradeRequest(BaseModel):
    card_id: int
    transcribed_answer: str

@router.post("/cards/grade", response_model=GradeResult)
async def grade_card_answer(req: GradeRequest, deps: dict = Depends(get_services)):
    """
    Grades an answer for a specific card using Gemini and applies the FSRS schedule update.
    """
    card_repo: ReviewCardRepository = deps["card_repo"]
    orchestrator: ReviewOrchestrator = deps["orchestrator"]

    card = await card_repo.find_by_id(req.card_id)
    if not card:
        raise HTTPException(status_code=404, detail="ReviewCard not found")

    result = await orchestrator.submit_answer(card, req.transcribed_answer)
    return result

class GenerateCardsRequest(BaseModel):
    article_id: int

@router.post("/cards/generate", response_model=list[ReviewCardSchema])
async def generate_cards_for_article(req: GenerateCardsRequest, deps: dict = Depends(get_services)):
    """
    Generates new cards for an existing article in the database.
    """
    article_repo: ArticleRepository = deps["article_repo"]
    card_repo: ReviewCardRepository = deps["card_repo"]
    question_gen: QuestionGeneratorService = deps["question_gen"]

    article = await article_repo.find_by_id(req.article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    new_cards = await question_gen.generate_cards_for(article)
    if new_cards:
        saved = await card_repo.save_all(new_cards)
        return [ReviewCardSchema.model_validate(c) for c in saved]
    return []


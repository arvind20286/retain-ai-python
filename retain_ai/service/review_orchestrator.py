import logging
from retain_ai.domain.grade_result import GradeResult
from retain_ai.domain.review_card import ReviewCard
from retain_ai.service.grading_service import GradingService
from retain_ai.service.scheduler_service import SchedulerService

logger = logging.getLogger(__name__)

class ReviewOrchestrator:
    """
    Coordinates a review session: picks due cards, and for each one, drives
    the cycle of 'ask question aloud -> receive answer -> grade -> update schedule'.
    """

    def __init__(self, scheduler_service: SchedulerService, grading_service: GradingService):
        self.scheduler_service = scheduler_service
        self.grading_service = grading_service

    async def next_cards_for_session(self) -> list[ReviewCard]:
        return await self.scheduler_service.find_due_cards()

    async def submit_answer(self, card: ReviewCard, transcribed_answer: str) -> GradeResult:
        grade = await self.grading_service.grade(card, transcribed_answer)
        await self.scheduler_service.apply_grade(card, grade)
        return grade


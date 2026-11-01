from datetime import datetime, timezone
import logging
from fsrs import Card, Rating, Scheduler

from retain_ai.domain.grade_result import GradeResult
from retain_ai.domain.review_card import ReviewCard
from retain_ai.repository.review_card_repository import ReviewCardRepository

logger = logging.getLogger(__name__)

class SchedulerService:
    """
    Wraps the Free Spaced Repetition Scheduler (FSRS) implementation.
    Translates grading scores into FSRS ratings and updates stability,
    difficulty, and next review interval.
    """

    def __init__(self, review_card_repository: ReviewCardRepository):
        self.review_card_repository = review_card_repository
        self.fsrs = Scheduler()

    async def find_due_cards(self) -> list[ReviewCard]:
        now = datetime.now(timezone.utc)
        return await self.review_card_repository.find_due(now)

    def score_to_rating(self, score: int) -> Rating:
        """
        Maps a 0-100 grading score to an FSRS Rating.
        - < 60: Again (forgot or major misunderstanding)
        - 60 - 74: Hard (struggled, partial recall)
        - 75 - 89: Good (recalled key points accurately)
        - 90 - 100: Easy (flawless, immediate understanding)
        """
        if score < 60:
            return Rating.Again
        elif score < 75:
            return Rating.Hard
        elif score < 90:
            return Rating.Good
        else:
            return Rating.Easy

    async def apply_grade(self, card: ReviewCard, grade: GradeResult) -> ReviewCard:
        """
        Feeds the grading score into FSRS to update stability/difficulty and
        compute the next review date, then persists the card.
        """
        now = datetime.now(timezone.utc)
        rating = self.score_to_rating(grade.score)

        # Build an FSRS Card from card's current state
        last_rev = card.last_reviewed_at
        if last_rev and last_rev.tzinfo is None:
            last_rev = last_rev.replace(tzinfo=timezone.utc)

        due_date = card.next_review_at
        if due_date and due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=timezone.utc)

        fsrs_card = Card(
            stability=card.stability if card.stability > 0 else 0.4,
            difficulty=card.difficulty if card.difficulty > 0 else 5.0,
            due=due_date or now,
            last_review=last_rev or now
        )

        updated_fsrs_card, review_log = self.fsrs.review_card(fsrs_card, rating, now)
        card.stability = float(updated_fsrs_card.stability)
        card.difficulty = float(updated_fsrs_card.difficulty)
        card.next_review_at = updated_fsrs_card.due
        card.last_reviewed_at = now
        card.times_reviewed += 1
        logger.info(
            "Card %s updated: score=%d rating=%s -> stability=%.2f difficulty=%.2f next_review=%s",
            card.id, grade.score, rating.name, card.stability, card.difficulty, card.next_review_at
        )

        return await self.review_card_repository.save(card)


from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from retain_ai.domain.review_card import ReviewCard

class ReviewCardRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_id(self, card_id: int) -> Optional[ReviewCard]:
        stmt = select(ReviewCard).options(selectinload(ReviewCard.article)).where(ReviewCard.id == card_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_article_id(self, article_id: int) -> list[ReviewCard]:
        stmt = select(ReviewCard).where(ReviewCard.article_id == article_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_due(self, now: Optional[datetime] = None) -> list[ReviewCard]:
        if now is None:
            now = datetime.now(timezone.utc)
        stmt = (
            select(ReviewCard)
            .options(selectinload(ReviewCard.article))
            .where(
                or_(
                    ReviewCard.next_review_at.is_(None),
                    ReviewCard.next_review_at <= now
                )
            )
            .order_by(ReviewCard.next_review_at.asc().nullsfirst())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def save(self, card: ReviewCard) -> ReviewCard:
        if card.id is None:
            self.session.add(card)
        else:
            await self.session.merge(card)
        await self.session.commit()
        await self.session.refresh(card)
        return card

    async def save_all(self, cards: list[ReviewCard]) -> list[ReviewCard]:
        for card in cards:
            if card.id is None:
                self.session.add(card)
            else:
                await self.session.merge(card)
        await self.session.commit()
        for card in cards:
            await self.session.refresh(card)
        return cards


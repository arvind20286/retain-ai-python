from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from retain_ai.database import Base

class ReviewCard(Base):
    """
    A single question/answer pair generated from an Article, plus everything
    the scheduler needs. Replaces the review-state properties from Notion.
    """
    __tablename__ = "review_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=True)

    question = Column(Text, nullable=False)
    reference_answer = Column(Text, nullable=False)

    # FSRS scheduling state
    stability = Column(Float, default=0.0, nullable=False)
    difficulty = Column(Float, default=0.0, nullable=False)
    last_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    next_review_at = Column(DateTime(timezone=True), nullable=True)
    times_reviewed = Column(Integer, default=0, nullable=False)

    article = relationship("Article", back_populates="cards")

    @property
    def is_due(self) -> bool:
        if self.next_review_at is None:
            return True
        now = datetime.now(timezone.utc)
        target = self.next_review_at
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return target <= now

class ReviewCardSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    article_id: Optional[int] = None
    question: str
    reference_answer: str
    stability: float = 0.0
    difficulty: float = 0.0
    last_reviewed_at: Optional[datetime] = None
    next_review_at: Optional[datetime] = None
    times_reviewed: int = 0
    is_due: bool = True


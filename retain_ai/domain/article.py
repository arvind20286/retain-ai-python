from typing import Optional
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from retain_ai.database import Base

class Article(Base):
    """
    Content only — deliberately has no review-state fields (status, level,
    next review, etc). Those live on ReviewCard. This split is what
    lets us swap or add note-app sources without touching scheduling logic.
    """
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    page_id = Column(String(255), unique=True, index=True, nullable=False)
    source_name = Column(String(50), nullable=False, default="notion")
    title = Column(String(500), nullable=True)
    source_url = Column(String(1000), nullable=True)
    content = Column(Text, nullable=True)
    user_notes = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True, default=list)

    cards = relationship("ReviewCard", back_populates="article", cascade="all, delete-orphan")

class ArticleSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    page_id: str
    source_name: str = "notion"
    title: Optional[str] = None
    source_url: Optional[str] = None
    content: Optional[str] = None
    user_notes: Optional[str] = None
    tags: Optional[list[str]] = None


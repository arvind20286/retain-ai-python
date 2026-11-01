from typing import Optional
from abc import ABC, abstractmethod
from retain_ai.domain.article import Article
from retain_ai.repository.article_repository import ArticleRepository

class ContentSource(ABC):
    """
    A source of raw content to turn into review material.
    This seam keeps the review engine decoupled from where articles come from.
    """

    @abstractmethod
    def source_name(self) -> str:
        """A short identifier for this source, e.g. 'notion', 'obsidian'."""
        pass

    @abstractmethod
    async def fetch_ready_articles(self, article_repository: Optional[ArticleRepository] = None) -> list[Article]:
        """Pulls all articles currently marked ready-to-review in this source."""
        pass

    async def write_back_status(self, external_id: str, status: str) -> None:
        """Optional: push review status back to the source."""
        pass


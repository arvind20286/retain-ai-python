from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from retain_ai.domain.article import Article

class ArticleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_source_and_page_id(self, source_name: str, page_id: str) -> Optional[Article]:
        stmt = select(Article).where(
            Article.source_name == source_name,
            Article.page_id == page_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_id(self, article_id: int) -> Optional[Article]:
        stmt = select(Article).where(Article.id == article_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Article]:
        stmt = select(Article)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def save(self, article: Article) -> Article:
        existing = await self.find_by_source_and_page_id(article.source_name, article.page_id)
        if existing:
            existing.title = article.title
            existing.source_url = article.source_url
            existing.content = article.content
            existing.user_notes = article.user_notes
            existing.tags = article.tags
            await self.session.commit()
            await self.session.refresh(existing)
            return existing
        else:
            self.session.add(article)
            await self.session.commit()
            await self.session.refresh(article)
            return article


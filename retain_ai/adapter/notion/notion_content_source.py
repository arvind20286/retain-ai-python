from typing import Any, Optional
import logging
from retain_ai.adapter.content_source import ContentSource
from retain_ai.adapter.notion.notion_client import NotionClient
from retain_ai.domain.article import Article
from retain_ai.repository.article_repository import ArticleRepository

logger = logging.getLogger(__name__)

class NotionContentSource(ContentSource):
    """
    Reads articles from a Notion database and maps them to the internal Article model.
    Decoupled from review state (which lives in our own DB).
    """

    def __init__(self, notion_client: NotionClient, article_repository: Optional[ArticleRepository] = None):
        self.notion_client = notion_client
        self.article_repository = article_repository

    def source_name(self) -> str:
        return "notion"

    def _extract_title(self, properties: dict[str, Any]) -> str:
        for key in ["Topic", "Reading List", "Title", "Name"]:
            prop = properties.get(key)
            if prop:
                # Can be 'title' type or 'rich_text'
                elements = prop.get("title") or prop.get("rich_text") or []
                if elements and len(elements) > 0:
                    return elements[0].get("plain_text", "")
        return ""

    def _extract_url(self, properties: dict[str, Any]) -> str:
        for key in ["Resource Link", "URL", "Link"]:
            prop = properties.get(key)
            if prop:
                return prop.get("url", "") or ""
        return ""

    def _extract_tags(self, properties: dict[str, Any]) -> list[str]:
        tags = []
        for key in ["Tag", "Tags"]:
            prop = properties.get(key)
            if prop:
                multi_select = prop.get("multi_select", [])
                for item in multi_select:
                    name = item.get("name")
                    if name:
                        tags.append(name)
        return tags

    def _extract_notes(self, properties: dict[str, Any]) -> str:
        for key in ["Insight", "Notes", "Summary"]:
            prop = properties.get(key)
            if prop:
                elements = prop.get("rich_text", [])
                if elements:
                    return "".join(el.get("plain_text", "") for el in elements)
        return ""

    async def fetch_ready_articles(self, article_repository: Optional[ArticleRepository] = None) -> list[Article]:
        try:
            data = await self.notion_client.query_datasource()
        except Exception as e:
            logger.error("Failed to query Notion datasource: %s", e)
            return []

        repo = article_repository or self.article_repository
        articles = []
        results = data.get("results", [])
        logger.info("Found %d page(s) in Notion datasource", len(results))

        for page in results:
            page_id = page.get("id", "")
            if not page_id:
                continue

            properties = page.get("properties", {})
            title = self._extract_title(properties)
            source_url = self._extract_url(properties)
            tags = self._extract_tags(properties)
            notes = self._extract_notes(properties)

            # If page id is already present in articles, don't fetch its markdown
            existing_article = None
            if repo:
                existing_article = await repo.find_by_source_and_page_id(self.source_name(), page_id)

            if existing_article and existing_article.content:
                logger.info("Page %s ('%s') already exists in articles. Skipping markdown fetch.", page_id, title)
                markdown_content = existing_article.content
            else:
                markdown_content = await self.notion_client.get_page_as_markdown(page_id)
                logger.info("Fetched markdown for page %s ('%s')", page_id, title)

            article = Article(
                page_id=page_id,
                source_name=self.source_name(),
                title=title or f"Notion Article ({page_id[:8]})",
                source_url=source_url,
                content=markdown_content or notes,
                user_notes=notes,
                tags=tags,
            )
            articles.append(article)
            
            if(len(articles) == 10):
                break

        return articles

    async def write_back_status(self, external_id: str, status: str) -> None:
        try:
            await self.notion_client.update_page_status(external_id, status)
        except Exception as e:
            logger.warning("Failed to write back status for %s: %s", external_id, e)


import asyncio
from unittest.mock import AsyncMock
from retain_ai.adapter.notion.notion_client import NotionClient
from retain_ai.adapter.notion.notion_content_source import NotionContentSource

async def test_notion_source_mapping():
    mock_client = NotionClient(api_token="test_token", datasource_id="test_db")
    mock_client.query_datasource = AsyncMock(return_value={
        "results": [
            {
                "id": "page-uuid-999",
                "properties": {
                    "Topic": {
                        "title": [{"plain_text": "CAP Theorem & PACELC"}]
                    },
                    "Resource Link": {
                        "url": "https://en.wikipedia.org/wiki/CAP_theorem"
                    },
                    "Tag": {
                        "multi_select": [{"name": "Architecture"}, {"name": "Database"}]
                    },
                    "Insight": {
                        "rich_text": [{"plain_text": "In presence of partition, choose between C and A; else between L and C."}]
                    }
                }
            }
        ]
    })
    mock_client.get_page_as_markdown = AsyncMock(return_value="Detailed article on CAP and PACELC trade-offs.")

    source = NotionContentSource(mock_client)
    assert source.source_name() == "notion"

    articles = await source.fetch_ready_articles()
    assert len(articles) == 1
    art = articles[0]
    assert art.page_id == "page-uuid-999"
    assert art.title == "CAP Theorem & PACELC"
    assert art.source_url == "https://en.wikipedia.org/wiki/CAP_theorem"
    assert art.tags == ["Architecture", "Database"]
    assert "partition" in art.user_notes
    assert "Detailed article" in art.content
    print("Notion mapping test passed! Article parsed correctly:", art.title)

async def test_notion_skip_markdown_if_already_present():
    mock_client = NotionClient(api_token="test_token", datasource_id="test_db")
    mock_client.query_datasource = AsyncMock(return_value={
        "results": [
            {
                "id": "existing-page-123",
                "properties": {
                    "Topic": {"title": [{"plain_text": "Existing Document"}]},
                    "Resource Link": {"url": "https://example.com"},
                    "Tag": {"multi_select": []},
                    "Insight": {"rich_text": []}
                }
            }
        ]
    })
    mock_client.get_page_as_markdown = AsyncMock()

    # Mock ArticleRepository returning an existing article with content
    mock_repo = AsyncMock()
    existing_mock_article = AsyncMock()
    existing_mock_article.content = "Cached existing markdown content"
    mock_repo.find_by_source_and_page_id.return_value = existing_mock_article

    source = NotionContentSource(mock_client, article_repository=mock_repo)
    articles = await source.fetch_ready_articles()

    # Verify that get_page_as_markdown was NEVER called because page_id was already present
    mock_client.get_page_as_markdown.assert_not_called()
    assert len(articles) == 1
    assert articles[0].content == "Cached existing markdown content"
    print("Skip markdown fetch test passed!")

if __name__ == "__main__":
    asyncio.run(test_notion_source_mapping())

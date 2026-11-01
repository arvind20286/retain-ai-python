import logging
from typing import Any, Optional
import httpx

logger = logging.getLogger(__name__)

class NotionClient:
    """
    Thin async wrapper around Notion's REST API (https://developers.notion.com).
    Raw HTTP in, raw JSON-ish responses out. Interpretation lives in NotionContentSource.
    """

    def __init__(self, api_token: str, datasource_id: str, notion_version: str = "2026-03-11"):
        self.api_token = api_token
        self.datasource_id = datasource_id
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Notion-Version": notion_version,
            "Content-Type": "application/json",
        }

    async def query_datasource(self, filter_properties: Optional[list[str]] = None) -> dict[str, Any]:
        """
        Queries the database for pages. Supports filter_properties query params.
        """
        if not self.api_token or not self.datasource_id:
            logger.warning("Notion API token or datasource ID not configured.")
            return {"results": []}

        params = {}
        if filter_properties:
            params["filter_properties"] = filter_properties

        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=20.0) as client:
            url = f"/data_sources/{self.datasource_id}/query"
            logger.info("Querying Notion database: %s", url)
            response = await client.post(url, json=params)

            if not response.is_success:
                try:
                    err_data = response.json()
                    err_msg = err_data.get("message", response.text)
                except Exception:
                    err_msg = response.text
                logger.error("Notion API returned HTTP %s: %s", response.status_code, err_msg)
                response.raise_for_status()

            return response.json()

    async def get_page_as_markdown(self, page_id: str) -> str:
        """
        Retrieves page content as markdown or extracts text from block children.
        """
        if not self.api_token:
            return ""

        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=20.0) as client:
            # Check if Notion markdown endpoint is supported
            try:
                resp = await client.get(f"/pages/{page_id}/markdown")
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("markdown", "")
            except Exception:
                pass

            # Fallback: extract block children paragraphs
            try:
                resp = await client.get(f"/blocks/{page_id}/children")
                if resp.status_code == 200:
                    data = resp.json()
                    lines = []
                    for block in data.get("results", []):
                        block_type = block.get("type", "")
                        content_obj = block.get(block_type, {})
                        rich_text = content_obj.get("rich_text", [])
                        text_fragments = [rt.get("plain_text", "") for rt in rich_text]
                        if text_fragments:
                            lines.append("".join(text_fragments))
                    return "\n\n".join(lines)
            except Exception as e:
                logger.warning("Could not fetch page blocks for %s: %s", page_id, e)

        return ""

    async def update_page_status(self, page_id: str, status: str) -> None:
        """
        PATCH /v1/pages/{page_id} to update the Status property.
        """
        if not self.api_token:
            return

        payload = {
            "properties": {
                "Status": {
                    "status": {
                        "name": status
                    }
                }
            }
        }
        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=20.0) as client:
            logger.info("Updating Notion page status for %s to %s", page_id, status)
            resp = await client.patch(f"/pages/{page_id}", json=payload)
            if not resp.is_success:
                logger.warning("Failed to update status on Notion page %s: %s", page_id, resp.text)


from fastmcp import FastMCP
import os
import requests
import logging
from typing import List
from dotenv import load_dotenv

load_dotenv()

# MCP server
mcp = FastMCP(
    name="Notion",
    json_response=True
)


class NotionAdapter:
    def __init__(self, access_token: str = None):
        # Use the provided access token or fallback to the environment variable.
        self.access_token = access_token or os.getenv('NOTION_ACCESS_TOKEN')

    @property
    def headers(self):
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Notion-Version': '2022-06-28',
            'Content-Type': 'application/json'
        }

    def query_database(self, database_id: str, filter: dict):
        url = f'https://api.notion.com/v1/databases/{database_id}/query'
        if not self.access_token:
            logging.error("No Notion access token provided.")
            return None
        response = requests.post(url, headers=self.headers, json=filter)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Query error: {response.json()}")
            return {"error": response.status_code}

    def update_page(self, page_id: str, data: dict):
        url = f'https://api.notion.com/v1/pages/{page_id}'
        if not self.access_token:
            logging.error("No Notion access token provided.")
            return None
        response = requests.patch(url, headers=self.headers, json=data)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Update error: {response.json()}")
            return {"error": response.status_code}

    def create_page(self):
        ...
    
    def delete_page(self):
        ...

    def workspace_search(
        self,
        query: str = "",
        filter: dict | None = None,
        sort: dict | None = None,
        start_cursor: str | None = None,
        page_size: int | None = None
    ):
        url = 'https://api.notion.com/v1/search'
        if not self.access_token:
            logging.error("No Notion access token provided.")
            return None

        payload: dict = {}
        if query is not None:
            payload["query"] = query
        if filter:
            payload["filter"] = filter
        if sort:
            payload["sort"] = sort
        if start_cursor:
            payload["start_cursor"] = start_cursor
        if page_size:
            payload["page_size"] = max(1, min(page_size, 100))  # Notion max page size is 100

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            data = response.json()
        except ValueError:
            logging.error("Search response was not valid JSON.")
            return {"error": "invalid_json", "status": response.status_code, "text": response.text}

        if response.status_code == 200:
            return data

        logging.error(f"Search error: {data}")
        return {"error": response.status_code, "details": data}


notion_adapter = NotionAdapter()


@mcp.tool()
def query_database(database_id: str, filter: dict):
    """Run a Notion database query.

    Args:
        database_id: UUID of the database to search.
        filter: Full request body for the query endpoint (filters, sorts, page size, etc.).
            Example::

                {
                    "filter": {"property": "Status", "select": {"equals": "In Progress"}},
                    "sorts": [{"property": "Last edited", "direction": "descending"}],
                    "page_size": 10
                }
    """
    return notion_adapter.query_database(database_id, filter)


@mcp.tool()
def update_page(page_id: str, data: dict):
    """Update a Notion page's properties or content.

    Args:
        page_id: UUID of the page to patch.
        data: Payload matching https://api.notion.com/v1/pages/{page_id} requirements.
    """
    return notion_adapter.update_page(page_id, data)


@mcp.tool()
def workspace_search(
    query: str = "",
    filter: dict | None = None,
    sort: dict | None = None,
    start_cursor: str | None = None,
    page_size: int | None = None
):
    """Search across the Notion workspace. This tool is good for identifying ids and urls of Notion pages and databases.

    Args:
        query: Free-text string that Notion matches against page titles and content.
            Example: "Quarterly planning notes".
        filter: Optional type filter, e.g. {"property": "object", "value": "page"}.
        sort: Ordering instruction, e.g. {"timestamp": "last_edited_time", "direction": "descending"}.
        start_cursor: Cursor from a previous response to paginate forward.
        page_size: Maximum number of items to return (1-100).
    """
    return notion_adapter.workspace_search(query, filter, sort, start_cursor, page_size)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8081)
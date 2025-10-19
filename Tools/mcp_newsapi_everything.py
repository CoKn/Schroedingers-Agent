from __future__ import annotations

import os
import time
import typing as t
from dataclasses import dataclass
from enum import Enum
import requests
from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

try:
    mcp = FastMCP(name="NewsAPI")
except TypeError:
    mcp = FastMCP()


# --------------------------- Response Format Enum ---------------------------

class ResponseFormat(str, Enum):
    """Control the verbosity of tool responses.

    - CONCISE: Returns only essential fields (title, source, date, description, url)
    - DETAILED: Returns all available article metadata including content snippets
    """
    CONCISE = "concise"
    DETAILED = "detailed"


# --------------------------- HTTP client ------------------------------------

@dataclass
class HTTPResult:
    status: int
    json: dict | list | None
    text: str
    headers: dict[str, str]


class NewsAPIClient:
    def __init__(self, api_key: str, base_url: str = "https://newsapi.org/v2", timeout: int = 20):
        if not api_key:
            raise ValueError(
                "Missing NewsAPI key. Set NEWSAPI_KEY_ENV environment variable. "
                "Get a free key at https://newsapi.org/register"
            )
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key})
        self.base_url = base_url
        self.timeout = timeout

    def _request(
            self,
            method: str,
            path: str,
            params: dict[str, t.Any],
            max_retries: int = 3,
            backoff_base: float = 1.5,
    ) -> HTTPResult:
        url = f"{self.base_url}/{path.lstrip('/')}"
        attempt = 0
        while True:
            resp = self.session.request(
                method=method, url=url, params=params, timeout=self.timeout
            )

            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                attempt += 1
                retry_after = resp.headers.get("Retry-After")
                try:
                    sleep_s = float(retry_after) if retry_after else backoff_base ** attempt
                except ValueError:
                    sleep_s = backoff_base ** attempt
                time.sleep(sleep_s)
                continue

            try:
                data = resp.json()
            except Exception:
                data = None
            return HTTPResult(resp.status_code, data, resp.text, dict(resp.headers))

    def everything(
            self,
            *,
            q: str | None = None,
            q_in_title: str | None = None,
            search_in: str | None = None,
            sources: str | None = None,
            domains: str | None = None,
            exclude_domains: str | None = None,
            from_: str | None = None,
            to: str | None = None,
            language: str | None = None,
            sort_by: str | None = "publishedAt",
            page_size: int = 20,
            page: int = 1,
    ) -> dict:
        params = {
            "q": q,
            "qInTitle": q_in_title,
            "searchIn": search_in,
            "sources": sources,
            "domains": domains,
            "excludeDomains": exclude_domains,
            "from": from_,
            "to": to,
            "language": language,
            "sortBy": sort_by,
            "pageSize": page_size,
            "page": page,
        }
        params = {k: v for k, v in params.items() if v is not None}
        res = self._request("GET", "/everything", params)

        if res.status != 200:
            msg = (res.json.get("message") if isinstance(res.json, dict) else None) or res.text
            return {"status": "error", "message": msg, "code": res.status}

        return t.cast(dict, res.json)


def _client() -> NewsAPIClient:
    # Use environment variable - NEVER hardcode API keys
    api_key = os.getenv("NEWSAPI_KEY_ENV")
    if not api_key:
        raise ValueError("NEWSAPI_KEY_ENV environment variable not set")
    return NewsAPIClient(api_key=api_key)


def _format_article(article: dict, format: ResponseFormat) -> dict:
    """Transform article to requested format."""
    if format == ResponseFormat.CONCISE:
        return {
            "title": article.get("title", "No title"),
            "source": article.get("source", {}).get("name", "Unknown source"),
            "published_date": article.get("publishedAt", "Unknown date"),
            "description": article.get("description", "No description available"),
            "url": article.get("url"),
        }
    else:  # DETAILED
        return {
            "title": article.get("title"),
            "source_name": article.get("source", {}).get("name"),
            "source_id": article.get("source", {}).get("id"),
            "author": article.get("author"),
            "description": article.get("description"),
            "url": article.get("url"),
            "image_url": article.get("urlToImage"),
            "published_date": article.get("publishedAt"),
            "content_snippet": article.get("content"),
        }


# --------------------------- MCP tools --------------------------------------

@mcp.tool()
def newsapi_search(
        query: str,
        from_date: str | None = None,
        to_date: str | None = None,
        language: str = "en",
        sort_by: str = "relevancy",
        max_results: int = 20,
        response_format: ResponseFormat = ResponseFormat.CONCISE,
        domains: str | None = None,
        exclude_domains: str | None = None,
) -> dict:
    """Search for news articles using NewsAPI.

    This tool searches across thousands of news sources and returns articles matching
    your query. Use it to find recent news, research topics, or track specific stories.

    Args:
        query: Search keywords or phrases. Use quotes for exact phrases (e.g., "climate change").
               Supports AND/OR/NOT operators (e.g., "bitcoin AND regulation NOT crypto").

        from_date: Start date in ISO 8601 format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).
                   Example: "2025-01-01" for articles from January 1st onwards.
                   Defaults to articles from the past month if not specified.

        to_date: End date in ISO 8601 format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).
                 Example: "2025-01-15" for articles up to January 15th.
                 Defaults to current date/time if not specified.

        language: Language code (ISO 639-1). Examples: "en" (English), "de" (German), 
                  "fr" (French), "es" (Spanish), "zh" (Chinese).

        sort_by: How to order results. Options:
                 - "relevancy": Most relevant to query (best for research)
                 - "popularity": Most shared/engaged with (best for trending topics)
                 - "publishedAt": Most recent first (best for breaking news)

        max_results: Maximum number of articles to return (1-100). Start with 20 for most
                     queries. Use fewer (5-10) for very specific searches, more (50+) for
                     comprehensive research. The tool automatically handles pagination.

        response_format: Output verbosity:
                         - "concise": Title, source, date, description, url (recommended for
                           most queries - uses ~70% fewer tokens)
                         - "detailed": All metadata including author, images, content snippets

        domains: Comma-separated list of domains to search within.
                 Example: "bbc.co.uk,nytimes.com" to only search BBC and NY Times.

        exclude_domains: Comma-separated list of domains to exclude.
                         Example: "tabloid.com,spam.site" to filter out unreliable sources.

    Returns:
        Dictionary with:
        - total_results: Total matching articles found (may exceed max_results)
        - articles: List of article objects (length up to max_results)
        - truncated: Boolean indicating if results were limited
        - message: Helpful context about the search

    Examples:
        - Breaking news: newsapi_search("Ukraine war", sort_by="publishedAt", max_results=10)
        - Research topic: newsapi_search("AI safety regulation", from_date="2024-01-01", max_results=50)
        - Specific source: newsapi_search("climate policy", domains="bbc.co.uk,reuters.com")

    Tips:
        - For broad topics, start with max_results=20 and refine your query if needed
        - Use date ranges to focus on recent developments or historical context
        - Use "concise" format unless you specifically need author/image/content details
        - Combine with multiple searches rather than requesting 100+ results at once
    """
    client = _client()

    # Validate and cap max_results
    if max_results < 1:
        return {
            "status": "error",
            "message": "max_results must be at least 1. Please provide a positive number."
        }

    max_results = min(max_results, 100)  # NewsAPI hard limit

    # Calculate pagination
    page_size = min(max_results, 100)
    pages_needed = 1

    all_articles = []
    total_results = 0

    try:
        # Fetch first page
        response = client.everything(
            q=query,
            from_=from_date,
            to=to_date,
            language=language,
            sort_by=sort_by,
            page_size=page_size,
            page=1,
            domains=domains,
            exclude_domains=exclude_domains,
        )

        if response.get("status") == "error":
            return {
                "status": "error",
                "message": f"NewsAPI error: {response.get('message', 'Unknown error')}. "
                           f"Check your query syntax and parameters."
            }

        total_results = response.get("totalResults", 0)
        articles = response.get("articles", [])

        # Format articles
        for article in articles[:max_results]:
            all_articles.append(_format_article(article, response_format))

        result = {
            "total_results": total_results,
            "articles": all_articles,
            "returned_count": len(all_articles),
            "truncated": total_results > len(all_articles),
        }

        # Add helpful context message
        if total_results == 0:
            result["message"] = (
                "No articles found. Try: (1) broadening your query, "
                "(2) removing date restrictions, or (3) checking for typos."
            )
        elif total_results > max_results:
            result["message"] = (
                f"Found {total_results} total articles but returned {len(all_articles)}. "
                f"To see more results, make your query more specific or increase max_results."
            )
        else:
            result["message"] = f"Found {total_results} articles matching your query."

        return result

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error searching news: {str(e)}. Please check your parameters and try again."
        }


@mcp.tool()
def newsapi_get_headlines(
        country: str = "us",
        category: str | None = None,
        max_results: int = 20,
        response_format: ResponseFormat = ResponseFormat.CONCISE,
) -> dict:
    """Get current top headlines from a specific country and/or category.

    Use this tool to quickly see what's making headlines right now in major news outlets.
    This is optimized for "what's in the news today?" type queries.

    Args:
        country: 2-letter ISO country code. Examples: "us" (USA), "gb" (UK), "de" (Germany),
                 "fr" (France), "jp" (Japan), "au" (Australia), "ca" (Canada).

        category: Filter by category. Options: "business", "entertainment", "general",
                  "health", "science", "sports", "technology". Leave empty for all categories.

        max_results: Number of headlines to return (1-100). Default is 20.

        response_format: Same as newsapi_search - use "concise" for efficiency.

    Returns:
        Dictionary with articles and metadata, similar to newsapi_search.

    Examples:
        - US top news: newsapi_get_headlines(country="us")
        - UK tech news: newsapi_get_headlines(country="gb", category="technology")
        - Business headlines: newsapi_get_headlines(category="business", max_results=10)
    """
    client = _client()

    max_results = min(max(max_results, 1), 100)

    try:
        response = client.session.get(
            f"{client.base_url}/top-headlines",
            params={
                "country": country,
                "category": category,
                "pageSize": min(max_results, 100),
            },
            timeout=client.timeout,
        )

        data = response.json()

        if data.get("status") == "error":
            return {
                "status": "error",
                "message": f"NewsAPI error: {data.get('message')}. "
                           f"Valid countries: us, gb, de, fr, etc. "
                           f"Valid categories: business, entertainment, general, health, science, sports, technology."
            }

        articles = data.get("articles", [])
        formatted = [_format_article(a, response_format) for a in articles[:max_results]]

        return {
            "total_results": len(articles),
            "articles": formatted,
            "returned_count": len(formatted),
            "message": f"Current top headlines from {country.upper()}"
                       + (f" in {category}" if category else ""),
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error fetching headlines: {str(e)}"
        }


if __name__ == "__main__":
    print(
        "[NewsAPI] Starting MCP server on 0.0.0.0:8082 (streamable-http). "
        "Tools: newsapi_search, newsapi_get_headlines",
        flush=True,
    )
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8082)
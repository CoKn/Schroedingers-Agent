# Tools/mcp_newsapi_everything.py
from __future__ import annotations

import os
import time
import typing as t
from dataclasses import dataclass
import requests

# ----- fastmcp compatibility shims ------------------------------------------
from fastmcp import FastMCP

# ----- env loading & safe defaults ------------------------------------------
from dotenv import load_dotenv


# Load into os.environ if python-dotenv is available
load_dotenv()

# ---- Hard-coded fallback (set this to your key if you want to bypass env) ---
# HARDCODED_NEWSAPI_KEY = "a22b451ddb5648b0a4d71064308a2bcd"  # <-- PASTE YOUR KEY HERE (or leave empty to use .env)
HARDCODED_NEWSAPI_KEY = os.getenv("NEWSAPI_KEY_ENV")
# ----- create MCP (avoid ctor kwarg issues across versions) -----------------
try:
    mcp = FastMCP(name="NewsAPI Everything")
except TypeError:
    mcp = FastMCP()

# --------------------------- HTTP client ------------------------------------

@dataclass
class HTTPResult:
    status: int
    json: dict | list | None
    text: str
    headers: dict[str, str]

class NewsAPIClient:
    def __init__(self, api_key: str, base_url: str | None = None, timeout: int = 20):
        if not api_key:
            raise ValueError(
                "Missing API key. Set NEWSAPI_KEY_ENV =<your key> in the environment, "
                "or put it into HARDCODED_NEWSAPI_KEY."
            )
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key})
        self.base_url = (base_url or os.getenv("NEWSAPI_BASE"))
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

            # Retry on rate limit / transient errors
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                attempt += 1
                retry_after = resp.headers.get("Retry-After")
                try:
                    sleep_s = float(retry_after) if retry_after else backoff_base**attempt
                except ValueError:
                    sleep_s = backoff_base**attempt
                time.sleep(sleep_s)
                continue

            try:
                data = resp.json()
            except Exception:
                data = None
            return HTTPResult(resp.status_code, data, resp.text, dict(resp.headers))

    # --------------------------- /everything ---------------------------------

    def everything(
        self,
        *,
        q: str | None = None,
        q_in_title: str | None = None,   # maps to qInTitle
        search_in: str | None = None,    # "title,description,content"
        sources: str | None = None,      # comma-separated source ids
        domains: str | None = None,      # comma-separated hostnames
        exclude_domains: str | None = None,
        from_: str | None = None,        # ISO8601 date/time
        to: str | None = None,           # ISO8601 date/time
        language: str | None = None,     # e.g. en,de,fr
        sort_by: str | None = "publishedAt",  # relevancy|popularity|publishedAt
        page_size: int = 20,             # NewsAPI caps at 100
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
        return t.cast(dict, res.json)

    def paginate_everything(
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
        page_size: int = 100,
        max_pages: int = 3,
    ) -> t.Iterator[dict]:
        """Yield result pages from /everything."""
        for p in range(1, max_pages + 1):
            yield self.everything(
                q=q,
                q_in_title=q_in_title,
                search_in=search_in,
                sources=sources,
                domains=domains,
                exclude_domains=exclude_domains,
                from_=from_,
                to=to,
                language=language,
                sort_by=sort_by,
                page_size=page_size,
                page=p,
            )

def _client() -> NewsAPIClient:
    api_key = "a22b451ddb5648b0a4d71064308a2bcd"
    base_url = os.getenv("NEWSAPI_BASE")
    return NewsAPIClient(api_key=api_key, base_url=base_url)

# --------------------------- MCP tools --------------------------------------

@mcp.tool()
def ping() -> dict:
    """Health check to verify the MCP server is reachable."""
    return {"ok": True, "tools": ["everything", "paginate_everything", "summarize_articles"]}

@mcp.tool()
def everything(
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
    """NewsAPI /everything search."""
    return _client().everything(
        q=q,
        q_in_title=q_in_title,
        search_in=search_in,
        sources=sources,
        domains=domains,
        exclude_domains=exclude_domains,
        from_=from_,
        to=to,
        language=language,
        sort_by=sort_by,
        page_size=page_size,
        page=page,
    )

@mcp.tool()
def paginate_everything(
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
    page_size: int = 100,
    max_pages: int = 3,
) -> list[dict]:
    """Fetch multiple pages from /everything and return a list of page dicts."""
    pages: list[dict] = []
    for page in _client().paginate_everything(
        q=q,
        q_in_title=q_in_title,
        search_in=search_in,
        sources=sources,
        domains=domains,
        exclude_domains=exclude_domains,
        from_=from_,
        to=to,
        language=language,
        sort_by=sort_by,
        page_size=page_size,
        max_pages=max_pages,
    ):
        pages.append(page)
    return pages

@mcp.tool()
def summarize_articles(articles: list[dict], max_items: int = 10) -> list[dict]:
    """Trim NewsAPI article objects down to agent-friendly fields."""
    out: list[dict] = []
    for a in (articles or [])[: max(0, max_items)]:
        out.append(
            {
                "title": a.get("title"),
                "url": a.get("url"),
                "publishedAt": a.get("publishedAt"),
                "source": (a.get("source") or {}).get("name"),
                "author": a.get("author"),
                "description": a.get("description"),
            }
        )
    return out

if __name__ == "__main__":
    print(
        "[NewsAPI] Starting MCP server on 0.0.0.0:8082 (streamable-http). "
        "Tools: everything, paginate_everything, summarize_articles, ping, debug_env",
        flush=True,
    )

    mcp.run(transport="streamable-http", host="0.0.0.0", port=8082)

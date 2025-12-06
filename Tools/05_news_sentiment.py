# =============================================================
# MCP TOOL: altdata_news_sentiment (Standalone Complete Version)
# =============================================================

from fastmcp import FastMCP
from typing import Dict, List, Optional
import requests
import os
from dotenv import load_dotenv

# -------------------------------------------------------------
# Environment
# -------------------------------------------------------------
load_dotenv()

ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
ALPHA_BASE = "https://www.alphavantage.co/query"

if not ALPHAVANTAGE_API_KEY:
    raise RuntimeError("Missing ALPHAVANTAGE_API_KEY environment variable.")

# -------------------------------------------------------------
# Create MCP instance (you can attach it to your main instance)
# -------------------------------------------------------------
mcp = FastMCP(
    name="Alternative Data — News & Sentiment",
    json_response=True
)

# -------------------------------------------------------------
# AlphaVantage request wrapper
# -------------------------------------------------------------
def alpha_get(params: dict) -> dict:
    """
    Internal helper to call the AlphaVantage API consistently.
    """
    params_clean = {k: v for k, v in params.items() if v is not None}
    params_clean["apikey"] = ALPHAVANTAGE_API_KEY

    r = requests.get(ALPHA_BASE, params=params_clean)
    r.raise_for_status()
    return r.json()


# -------------------------------------------------------------
# MCP Tool: altdata_news_sentiment
# -------------------------------------------------------------
@mcp.tool()
def alternative_data_news_sentiment(
    tickers: str,
    limit: int = 50,
    sort: str = "LATEST"
) -> Dict:
    """
    Retrieve news + sentiment for a given ticker using
    AlphaVantage’s NEWS_SENTIMENT endpoint.

    This tool provides alternative-data context for:
    - risk detection,
    - reputation and controversy signals,
    - market perception,
    - governance or leadership issues,
    - competitive intelligence,
    - acquisition due diligence,
    - event-driven or sentiment-driven movements.

    PARAMETERS
    ----------
    tickers : str
        Comma-separated list of ticker symbols.
        Examples:
            "AAPL"
            "SNOW"
            "COIN,CRYPTO:BTC,FOREX:USD"

    limit : int
        Maximum number of articles to return (AlphaVantage supports up to 1000).

    sort : str
        Sorting behavior for returned articles:
            "LATEST" (default)
            "EARLIEST"
            "RELEVANCE"

    RETURNS
    -------
    Dict:
        {
            "tickers": "SNOW",
            "articles": [
                {
                    "title": "...",
                    "summary": "...",
                    "source": "...",
                    "url": "...",
                    "authors": [...],
                    "time_published": "20250201T150000",
                    "sentiment_score": 0.42,
                    "sentiment_label": "Positive",
                    "relevance_score": 0.89,
                    "ticker_mentions": [...],
                    "topic_sentiment": [...]
                }
            ]
        }

    AGENT USAGE NOTES
    -----------------
    - Use this tool to detect:
        • controversies or lawsuits,
        • market sentiment shifts,
        • regulatory or governance issues,
        • competitor actions,
        • acquisition risk factors.
    - It is especially useful BEFORE an M&A recommendation.
    - Always follow this tool with LLM summarization for deeper insight.
    """

    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": tickers,
        "sort": sort.upper(),
        "limit": str(limit)
    }

    data = alpha_get(params)
    feed = data.get("feed", []) or []
    articles = []

    for item in feed:
        articles.append({
            "title": item.get("title"),
            "summary": item.get("summary"),
            "source": item.get("source"),
            "url": item.get("url"),
            "authors": item.get("authors"),
            "time_published": item.get("time_published"),
            "sentiment_score": item.get("overall_sentiment_score"),
            "sentiment_label": item.get("overall_sentiment_label"),
            "relevance_score": item.get("relevance_score"),
            "ticker_mentions": item.get("ticker_sentiment"),
            "topic_sentiment": item.get("topic_sentiment")
        })

    return {
        "tickers": tickers,
        "articles": articles[:limit]
    }


# -------------------------------------------------------------
# MCP server entrypoint (optional)
# -------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8082
    )

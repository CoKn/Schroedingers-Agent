from fastmcp import FastMCP
from typing import Dict, Any, Optional, List, Tuple
import requests
import time
import os
from dotenv import load_dotenv

# Load API key
load_dotenv()
API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
BASE_URL = "https://www.alphavantage.co/query"

if not API_KEY:
    raise RuntimeError("Missing ALPHAVANTAGE_API_KEY environment variable.")

# MCP server (clean style)
mcp = FastMCP(
    name="AlphaVantage REST Tools",
    json_response=True
)

###############################################
# RATE LIMITING
###############################################

RATE_LIMIT_PER_MINUTE = 5
RATE_LIMIT_PER_DAY = 25

class RateTracker:
    def __init__(self):
        self.calls_minute: List[float] = []
        self.calls_day: List[float] = []

    def can_call(self) -> Tuple[bool, str | None]:
        now = time.time()
        self.calls_minute = [t for t in self.calls_minute if now - t < 60]
        self.calls_day = [t for t in self.calls_day if now - t < 86400]

        if len(self.calls_minute) >= RATE_LIMIT_PER_MINUTE:
            return False, "Rate limit exceeded: 5 calls/minute."

        if len(self.calls_day) >= RATE_LIMIT_PER_DAY:
            return False, "Daily rate limit exceeded: 25 calls/day."

        return True, None

    def mark(self):
        now = time.time()
        self.calls_minute.append(now)
        self.calls_day.append(now)

rate_tracker = RateTracker()

###############################################
# HELPER FUNCTIONS
###############################################

def call_alpha_vantage(params: Dict[str, str]) -> Dict[str, Any]:
    params["apikey"] = API_KEY
    r = requests.get(BASE_URL, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def validate_symbol(symbol: str) -> Tuple[bool, str | None]:
    if not symbol:
        return False, "Symbol cannot be empty."
    if " " in symbol:
        return False, "Symbol must not contain spaces."
    if len(symbol) > 15:
        return False, "Symbol too long."
    return True, None

###############################################
# MCP TOOLS (CLEAN STYLE)
###############################################

@mcp.tool()
def alphavantage_symbol_search(keywords: str) -> Dict[str, Any]:
    """Search for stock ticker symbols by company name."""
    ok, msg = rate_tracker.can_call()
    if not ok:
        return {"error": msg}

    data = call_alpha_vantage({
        "function": "SYMBOL_SEARCH",
        "keywords": keywords
    })

    rate_tracker.mark()
    return data


@mcp.tool()
def alphavantage_global_quote(symbol: str) -> Dict[str, Any]:
    """Get real-time stock quote."""
    ok, msg = rate_tracker.can_call()
    if not ok:
        return {"error": msg}

    valid, err = validate_symbol(symbol)
    if not valid:
        return {"error": err}

    data = call_alpha_vantage({
        "function": "GLOBAL_QUOTE",
        "symbol": symbol.upper()
    })

    rate_tracker.mark()
    return data


@mcp.tool()
def alphavantage_time_series_daily(symbol: str, outputsize: str = "compact") -> Dict[str, Any]:
    """Daily OHLCV data."""
    ok, msg = rate_tracker.can_call()
    if not ok:
        return {"error": msg}

    valid, err = validate_symbol(symbol)
    if not valid:
        return {"error": err}

    data = call_alpha_vantage({
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol.upper(),
        "outputsize": outputsize
    })

    rate_tracker.mark()
    return data


@mcp.tool()
def alphavantage_news_sentiment(
    tickers: Optional[str] = None,
    topics: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """Get news articles with sentiment analysis."""
    ok, msg = rate_tracker.can_call()
    if not ok:
        return {"error": msg}

    params = {
        "function": "NEWS_SENTIMENT",
        "limit": str(min(limit, 1000))
    }
    if tickers:
        params["tickers"] = tickers
    if topics:
        params["topics"] = topics

    data = call_alpha_vantage(params)
    rate_tracker.mark()
    return data


@mcp.tool()
def alphavantage_currency_exchange_rate(from_currency: str, to_currency: str) -> Dict[str, Any]:
    """Get real-time currency exchange rate."""
    ok, msg = rate_tracker.can_call()
    if not ok:
        return {"error": msg}

    data = call_alpha_vantage({
        "function": "CURRENCY_EXCHANGE_RATE",
        "from_currency": from_currency.upper(),
        "to_currency": to_currency.upper()
    })

    rate_tracker.mark()
    return data


@mcp.tool()
def alphavantage_real_gdp(interval: str = "annual") -> Dict[str, Any]:
    """Get US Real GDP."""
    ok, msg = rate_tracker.can_call()
    if not ok:
        return {"error": msg}

    data = call_alpha_vantage({
        "function": "REAL_GDP",
        "interval": interval
    })

    rate_tracker.mark()
    return data

###############################################
# RUN SERVER
###############################################

if __name__ == "__main__":
    print("Starting AlphaVantage MCP server on port 8085")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8085)

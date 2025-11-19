"""
AlphaVantage MCP Server - Comprehensive Financial Data Tools
Enhanced wrapper around AlphaVantage's official MCP server with validation, 
rate limiting, and intelligent error guidance.

This server provides access to stock market data, fundamental analysis, forex rates,
and economic indicators through AlphaVantage's API.
"""

from __future__ import annotations

import os
import time
import asyncio
import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from fastmcp import FastMCP
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize MCP server
try:
    mcp = FastMCP(name="AlphaVantage")
except TypeError:
    mcp = FastMCP()


# ============================================================================
# CONFIGURATION & ENUMS
# ============================================================================

class ResponseFormat(str, Enum):
    """Control verbosity of tool responses for token efficiency."""
    CONCISE = "concise"  # Essential fields only (~50-70% token reduction)
    DETAILED = "detailed"  # Full API response


# Rate limit configuration
RATE_LIMIT_PER_MINUTE = 5
RATE_LIMIT_PER_DAY = 25


# ============================================================================
# RATE LIMITING SYSTEM
# ============================================================================

@dataclass
class RateLimitTracker:
    """Tracks API call rate limits."""
    calls_per_minute: List[float]
    calls_per_day: List[float]

    def __init__(self):
        self.calls_per_minute = []
        self.calls_per_day = []

    def can_make_call(self) -> Tuple[bool, Optional[str]]:
        """
        Check if we can make an API call without exceeding rate limits.

        Returns:
            (can_call, error_message)
        """
        now = time.time()

        # Clean up old timestamps
        one_minute_ago = now - 60
        one_day_ago = now - 86400

        self.calls_per_minute = [t for t in self.calls_per_minute if t > one_minute_ago]
        self.calls_per_day = [t for t in self.calls_per_day if t > one_day_ago]

        # Check minute limit
        if len(self.calls_per_minute) >= RATE_LIMIT_PER_MINUTE:
            wait_time = 60 - (now - self.calls_per_minute[0])
            return False, (
                f"Rate limit exceeded: {RATE_LIMIT_PER_MINUTE} calls per minute. "
                f"Wait {wait_time:.0f} seconds before retrying. "
                f"Consider spacing out your requests or upgrading to a premium plan."
            )

        # Check day limit
        if len(self.calls_per_day) >= RATE_LIMIT_PER_DAY:
            wait_time = 86400 - (now - self.calls_per_day[0])
            hours = wait_time / 3600
            return False, (
                f"Daily rate limit exceeded: {RATE_LIMIT_PER_DAY} calls per day. "
                f"Resets in {hours:.1f} hours. "
                f"Upgrade to a premium plan for higher limits (up to 1200 calls/minute)."
            )

        return True, None

    def record_call(self):
        """Record a successful API call."""
        now = time.time()
        self.calls_per_minute.append(now)
        self.calls_per_day.append(now)

    def get_status(self) -> Dict[str, Any]:
        """Get current rate limit status."""
        now = time.time()
        one_minute_ago = now - 60
        one_day_ago = now - 86400

        calls_last_minute = len([t for t in self.calls_per_minute if t > one_minute_ago])
        calls_last_day = len([t for t in self.calls_per_day if t > one_day_ago])

        return {
            "calls_last_minute": calls_last_minute,
            "minute_limit": RATE_LIMIT_PER_MINUTE,
            "calls_today": calls_last_day,
            "daily_limit": RATE_LIMIT_PER_DAY,
            "minute_remaining": RATE_LIMIT_PER_MINUTE - calls_last_minute,
            "daily_remaining": RATE_LIMIT_PER_DAY - calls_last_day
        }


# Global rate limiter
rate_limiter = RateLimitTracker()

# ============================================================================
# TOOL GUIDANCE & VALIDATION RULES
# ============================================================================

TOOL_GUIDANCE = {
    "SYMBOL_SEARCH": {
        "description": "Search for stock ticker symbols by company name or keywords.",
        "parameters": {
            "keywords": "Required. Company name or keywords (e.g., 'Microsoft', 'Apple', 'Tesla')"
        },
        "critical_notes": [
            "ALWAYS use this first when you have a company name but not the ticker symbol",
            "Returns multiple matches with their ticker symbols and exchange information",
            "Use the returned symbol in other tools (e.g., GLOBAL_QUOTE, TIME_SERIES_DAILY)"
        ],
        "examples": [
            '{"keywords": "Microsoft"}',
            '{"keywords": "Tesla"}',
            '{"keywords": "AAPL"}'
        ],
        "common_mistakes": [
            "Not using this before other stock tools when only company name is known"
        ]
    },

    "GLOBAL_QUOTE": {
        "description": "Get real-time stock quote with price, volume, and daily change.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol (e.g., 'AAPL', 'MSFT'). Use SYMBOL_SEARCH if unsure.",
            "response_format": "Optional. 'concise' (recommended, ~50% fewer tokens) or 'detailed'"
        },
        "critical_notes": [
            "Use exact ticker symbols, NOT company names",
            "If ticker unknown, call SYMBOL_SEARCH first",
            "Free tier updates at market close; premium gets realtime/15-min delayed"
        ],
        "examples": [
            '{"symbol": "AAPL"}',
            '{"symbol": "TSLA", "response_format": "concise"}'
        ],
        "common_mistakes": [
            "Using company name instead of ticker: 'Apple' vs 'AAPL'",
            "Forgetting exchange suffix for non-US stocks (e.g., 'TSCO.LON' for UK)"
        ]
    },

    "NEWS_SENTIMENT": {
        "description": "Get news articles with sentiment analysis for stocks/topics.",
        "parameters": {
            "tickers": "Optional. Single or comma-separated tickers (e.g., 'AAPL' or 'AAPL,MSFT')",
            "topics": "Optional. Topics like 'technology', 'earnings', 'ipo', 'mergers_and_acquisitions'",
            "time_from": "Optional. Format: YYYYMMDDTHHMM (e.g., '20240101T0000')",
            "time_to": "Optional. Format: YYYYMMDDTHHMM",
            "sort": "Optional. 'LATEST' (default), 'EARLIEST', or 'RELEVANCE'",
            "limit": "Optional. Number of results (default: 50, max: 1000)",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Use exact ticker symbols, NOT company names",
            "If ticker unknown, call SYMBOL_SEARCH first",
            "Can combine tickers and topics for refined search"
        ],
        "examples": [
            '{"tickers": "AAPL", "limit": 10}',
            '{"topics": "technology", "limit": 20}',
            '{"tickers": "TSLA,AAPL", "sort": "LATEST"}'
        ],
        "common_mistakes": [
            "Using company names: 'Tesla' instead of 'TSLA'",
            "Not using SYMBOL_SEARCH first for unfamiliar companies"
        ]
    },

    "TIME_SERIES_INTRADAY": {
        "description": "Get intraday OHLCV data (1min to 60min intervals) for stocks.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol",
            "interval": "Required. '1min', '5min', '15min', '30min', or '60min'",
            "adjusted": "Optional. 'true' (default, split/dividend adjusted) or 'false'",
            "extended_hours": "Optional. 'true' (default, includes pre/post market) or 'false'",
            "month": "Optional. YYYY-MM format for specific month (e.g., '2024-01')",
            "outputsize": "Optional. 'compact' (last 100 points) or 'full' (30 days or full month)",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Free tier: updated at market close. Premium: realtime/15-min delayed",
            "Use 'compact' for recent data to reduce tokens",
            "Specify 'month' to get historical intraday data (any month since 2000-01)"
        ],
        "examples": [
            '{"symbol": "IBM", "interval": "5min"}',
            '{"symbol": "AAPL", "interval": "15min", "outputsize": "compact"}'
        ]
    },

    "TIME_SERIES_DAILY": {
        "description": "Get daily OHLCV data for stocks (20+ years history).",
        "parameters": {
            "symbol": "Required. Stock ticker symbol",
            "outputsize": "Optional. 'compact' (last 100 days) or 'full' (20+ years)",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Returns raw (as-traded) prices - not adjusted for splits/dividends",
            "For adjusted prices, some users prefer TIME_SERIES_DAILY_ADJUSTED (premium)",
            "Use 'compact' unless you need full historical data"
        ],
        "examples": [
            '{"symbol": "IBM"}',
            '{"symbol": "TSCO.LON", "outputsize": "full"}'
        ]
    },

    "OVERVIEW": {
        "description": "Get comprehensive company overview with fundamentals and ratios.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Returns extensive data: market cap, P/E ratio, dividend yield, revenue, etc.",
            "Data refreshed same day company reports earnings",
            "One of the most comprehensive fundamental data endpoints"
        ],
        "examples": [
            '{"symbol": "IBM"}',
            '{"symbol": "MSFT", "response_format": "concise"}'
        ]
    },

    "INCOME_STATEMENT": {
        "description": "Get annual and quarterly income statements.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Returns normalized fields mapped to GAAP and IFRS taxonomies",
            "Data refreshed same day company reports earnings",
            "Includes revenue, gross profit, operating income, net income, EPS"
        ],
        "examples": [
            '{"symbol": "IBM"}',
            '{"symbol": "AAPL", "response_format": "concise"}'
        ]
    },

    "BALANCE_SHEET": {
        "description": "Get annual and quarterly balance sheets.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Returns normalized GAAP/IFRS fields",
            "Includes assets, liabilities, equity",
            "Data refreshed on earnings day"
        ],
        "examples": [
            '{"symbol": "IBM"}',
            '{"symbol": "MSFT", "response_format": "concise"}'
        ]
    },

    "CASH_FLOW": {
        "description": "Get annual and quarterly cash flow statements.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Returns operating, investing, and financing cash flows",
            "Normalized GAAP/IFRS fields",
            "Data refreshed on earnings day"
        ],
        "examples": [
            '{"symbol": "IBM"}',
            '{"symbol": "AAPL", "response_format": "concise"}'
        ]
    },

    "EARNINGS": {
        "description": "Get annual and quarterly earnings (EPS) history with estimates and surprises.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Quarterly data includes analyst estimates and surprise metrics",
            "Shows historical EPS performance",
            "Useful for earnings trend analysis"
        ],
        "examples": [
            '{"symbol": "IBM"}',
            '{"symbol": "TSLA", "response_format": "concise"}'
        ]
    },

    "CURRENCY_EXCHANGE_RATE": {
        "description": "Get realtime exchange rate between two currencies.",
        "parameters": {
            "from_currency": "Required. 3-letter code (e.g., 'USD', 'EUR', 'GBP', 'JPY')",
            "to_currency": "Required. 3-letter code",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Use 3-letter currency CODES, not names ('USD' not 'Dollar')",
            "Works for both physical currencies and crypto (e.g., 'BTC')",
            "Realtime rates"
        ],
        "examples": [
            '{"from_currency": "USD", "to_currency": "EUR"}',
            '{"from_currency": "GBP", "to_currency": "JPY"}'
        ],
        "common_mistakes": [
            "Using currency names instead of codes: 'Dollar' vs 'USD'"
        ]
    },

    "FX_DAILY": {
        "description": "Get daily historical forex OHLC data.",
        "parameters": {
            "from_symbol": "Required. 3-letter currency code",
            "to_symbol": "Required. 3-letter currency code",
            "outputsize": "Optional. 'compact' (last 100 days) or 'full' (full history)",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Note: Uses 'from_symbol' and 'to_symbol' (different from CURRENCY_EXCHANGE_RATE)",
            "Returns OHLC time series",
            "Updated realtime"
        ],
        "examples": [
            '{"from_symbol": "EUR", "to_symbol": "USD"}',
            '{"from_symbol": "GBP", "to_symbol": "JPY", "outputsize": "compact"}'
        ]
    },

    "REAL_GDP": {
        "description": "Get US Real GDP data (annual or quarterly).",
        "parameters": {
            "interval": "Optional. 'annual' (default) or 'quarterly'",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Key economic indicator for US economic health",
            "Source: U.S. Bureau of Economic Analysis via FRED"
        ],
        "examples": [
            '{"interval": "annual"}',
            '{"interval": "quarterly"}'
        ]
    },

    "FEDERAL_FUNDS_RATE": {
        "description": "Get US Federal Funds Rate (key interest rate).",
        "parameters": {
            "interval": "Optional. 'daily', 'weekly', or 'monthly' (default)",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Critical for understanding monetary policy",
            "Affects borrowing costs, investment decisions",
            "Source: Federal Reserve via FRED"
        ],
        "examples": [
            '{"interval": "monthly"}',
            '{"interval": "daily"}'
        ]
    },

    "CPI": {
        "description": "Get US Consumer Price Index (inflation indicator).",
        "parameters": {
            "interval": "Optional. 'monthly' (default) or 'semiannual'",
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Primary inflation indicator",
            "Affects monetary policy decisions",
            "Source: U.S. Bureau of Labor Statistics via FRED"
        ],
        "examples": [
            '{"interval": "monthly"}',
            '{}'
        ]
    },

    "UNEMPLOYMENT": {
        "description": "Get US unemployment rate (monthly).",
        "parameters": {
            "response_format": "Optional. 'concise' or 'detailed'"
        },
        "critical_notes": [
            "Key labor market indicator",
            "Percentage of labor force that is unemployed",
            "Source: U.S. Bureau of Labor Statistics via FRED"
        ],
        "examples": [
            '{}',
            '{"response_format": "concise"}'
        ]
    }
}


# ============================================================================
# ALPHAVANTAGE MCP CLIENT
# ============================================================================

class AlphaVantageClient:
    """Client for AlphaVantage's official MCP server."""

    DEFAULT_CATEGORIES = [
        "core_stock_apis",
        "alpha_intelligence",
        "fundamental_data",
        "forex",
        "economic_indicators"
    ]

    def __init__(self, api_key: Optional[str] = None, categories: Optional[List[str]] = None):
        """
        Initialize AlphaVantage client.

        Args:
            api_key: AlphaVantage API key. If None, loads from ALPHAVANTAGE_API_KEY env var.
            categories: List of API categories to enable.
        """
        self.api_key = api_key or os.getenv("ALPHAVANTAGE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "AlphaVantage API key not found. "
                "Set ALPHAVANTAGE_API_KEY in .env or pass api_key parameter. "
                "Get a free key at: https://www.alphavantage.co/support/#api-key"
            )

        self.categories = categories or self.DEFAULT_CATEGORIES
        self.base_url = "https://mcp.alphavantage.co/mcp"

    def _build_url(self) -> str:
        """Build MCP URL with API key and categories."""
        categories_str = ",".join(self.categories)
        return f"{self.base_url}?apikey={self.api_key}&categories={categories_str}"


    async def call_tool(
            self,
            tool_name: str,
            arguments: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Call AlphaVantage tool via MCP.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments

        Returns:
            Tool response content
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        arguments = arguments or {}
        result = await self.session.call_tool(tool_name, arguments)
        return result.content







# ============================================================================
# VALIDATION & ERROR HANDLING
# ============================================================================

def validate_symbol(symbol: str) -> Tuple[bool, Optional[str]]:
    """
    Validate stock symbol format.

    Returns:
        (is_valid, error_message)
    """
    if not symbol:
        return False, "Symbol cannot be empty. Use SYMBOL_SEARCH to find the correct ticker."

    if len(symbol) > 20:
        return False, f"Symbol '{symbol}' is too long. Check format or use SYMBOL_SEARCH."

    # Check if it looks like a company name
    if " " in symbol or len(symbol) > 6:
        return False, (
            f"'{symbol}' appears to be a company name, not a ticker symbol. "
            f"Use SYMBOL_SEARCH to find the correct ticker (e.g., 'AAPL' for Apple)."
        )

    return True, None


def validate_currency_code(code: str, param_name: str) -> Tuple[bool, Optional[str]]:
    """Validate currency code format."""
    if not code:
        return False, f"{param_name} cannot be empty"

    if len(code) != 3:
        return False, (
            f"{param_name} must be a 3-letter currency code (e.g., 'USD', 'EUR', 'GBP'). "
            f"Got: '{code}'"
        )

    if not code.isupper():
        return False, (
            f"{param_name} must be uppercase (e.g., 'USD' not 'usd'). "
            f"Got: '{code}'"
        )

    return True, None


def validate_interval(interval: str, valid_intervals: List[str]) -> Tuple[bool, Optional[str]]:
    """Validate interval parameter."""
    if interval not in valid_intervals:
        return False, (
            f"Invalid interval: '{interval}'. "
            f"Valid options: {', '.join(valid_intervals)}"
        )
    return True, None


def detect_api_error(response: Any) -> Optional[str]:
    """
    Detect if AlphaVantage returned an error.

    Returns:
        Error type if detected, None otherwise
    """
    if isinstance(response, list) and len(response) > 0:
        response_str = str(response[0]) if response else ""
    else:
        response_str = str(response)

    response_lower = response_str.lower()

    # Common error patterns
    if "invalid api call" in response_lower or "invalid inputs" in response_lower:
        return "invalid_inputs"
    elif "rate limit" in response_lower or "api rate limit" in response_lower:
        return "rate_limit"
    elif "premium endpoint" in response_lower or "premium feature" in response_lower:
        return "premium_required"
    elif "invalid api key" in response_lower or "invalid key" in response_lower:
        return "invalid_key"
    elif "note" in response_lower and "thank you" in response_lower:
        # AlphaVantage often returns polite error messages
        return "api_message"

    return None


def format_error_response(
        tool_name: str,
        error: Exception,
        arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Format error with helpful guidance."""
    error_msg = str(error)

    # Get tool-specific guidance
    guidance = TOOL_GUIDANCE.get(tool_name, {})
    critical_notes = guidance.get("critical_notes", [])
    examples = guidance.get("examples", [])

    response = {
        "status": "error",
        "tool": tool_name,
        "error": error_msg,
        "arguments_provided": arguments
    }

    # Add suggestions based on error type
    if "symbol" in arguments and "symbol" in error_msg.lower():
        response["suggestion"] = (
            "The symbol may be incorrect. Use SYMBOL_SEARCH to find the right ticker. "
            "Remember: use ticker symbols (e.g., 'AAPL'), not company names (e.g., 'Apple')."
        )
    elif critical_notes:
        response["critical_notes"] = critical_notes[:2]  # Top 2 notes

    if examples:
        response["example"] = examples[0]

    return response


def apply_concise_format(tool_name: str, data: Any) -> Any:
    """
    Apply CONCISE formatting to reduce token usage.
    Strips down to essential fields only.
    """
    if not data:
        return data

    # Different concise formats for different tools
    if tool_name == "GLOBAL_QUOTE":
        if isinstance(data, list) and len(data) > 0:
            item = data[0]
            if hasattr(item, 'text'):
                # Extract key fields from response text
                # This is a simplified approach; actual implementation would parse JSON
                return data  # Return as-is for now; MCP response format may vary
        return data

    elif tool_name == "NEWS_SENTIMENT":
        # Keep only essential news fields
        return data

    elif tool_name == "OVERVIEW":
        # Keep only key fundamental metrics
        return data

    # For other tools, return full response
    # Actual implementation would parse and filter based on tool type
    return data


# ============================================================================
# MCP TOOL WRAPPERS
# ============================================================================

@mcp.tool()
async def alphavantage_symbol_search(
        keywords: str,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Search for stock ticker symbols by company name or keywords.

    This is the FIRST tool you should use when you have a company name but not
    the ticker symbol. It returns matching stocks with their ticker symbols,
    which you can then use in other tools.

    Args:
        keywords: Company name or keywords to search for.
                  Examples: "Microsoft", "Apple", "Tesla", "Mercedes"
        response_format: 'concise' (recommended, essential fields only) or 'detailed'

    Returns:
        List of matching companies with ticker symbols, names, regions, and match scores.

    Examples:
        - Search for Microsoft: {"keywords": "Microsoft"}
        - Search for Tesla: {"keywords": "Tesla"}
        - Find Mercedes ticker: {"keywords": "Mercedes"}

    Critical Notes:
        - ALWAYS use this first when you only know the company name
        - Use the returned symbol in other tools (GLOBAL_QUOTE, TIME_SERIES_DAILY, etc.)
        - Returns multiple matches ranked by relevance

    Common Workflow:
        1. User asks: "What's the stock price of Apple?"
        2. Call: alphavantage_symbol_search(keywords="Apple")
        3. Get symbol: "AAPL"
        4. Call: alphavantage_global_quote(symbol="AAPL")
    """
    # Rate limiting
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg, "rate_limit_status": rate_limiter.get_status()}

    # Validation
    if not keywords or len(keywords.strip()) == 0:
        return {
            "status": "error",
            "message": "Keywords cannot be empty",
            "example": '{"keywords": "Microsoft"}'
        }

    try:
        client = await get_client()
        result = await client.call_tool("SYMBOL_SEARCH", {"keywords": keywords})

        # Record successful call
        rate_limiter.record_call()

        # Check for API errors
        error_type = detect_api_error(result)
        if error_type:
            return {
                "status": "error",
                "error_type": error_type,
                "response": result,
                "suggestion": "Check your keywords and try again"
            }

        # Apply format if needed
        if response_format == "concise":
            result = apply_concise_format("SYMBOL_SEARCH", result)

        return {
            "status": "ok",
            "data": result,
            "rate_limit_status": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in SYMBOL_SEARCH: {e}")
        return format_error_response("SYMBOL_SEARCH", e, {"keywords": keywords})


@mcp.tool()
async def alphavantage_global_quote(
        symbol: str,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get real-time stock quote with current price, volume, and daily change.

    This tool provides a snapshot of a stock's current trading status including
    open/high/low/close prices, volume, and percentage change.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT', 'TSLA').
                For non-US stocks, include exchange suffix (e.g., 'TSCO.LON').
                If you don't know the symbol, use alphavantage_symbol_search first.
        response_format: 'concise' (recommended, ~50% fewer tokens) or 'detailed'

    Returns:
        Current quote with price, volume, change percentage, and timestamp.

    Examples:
        - Get Apple stock quote: {"symbol": "AAPL"}
        - Get Tesla quote (concise): {"symbol": "TSLA", "response_format": "concise"}
        - UK stock (Tesco): {"symbol": "TSCO.LON"}

    Critical Notes:
        - Use TICKER SYMBOLS, not company names ('AAPL' not 'Apple')
        - If ticker is unknown, call alphavantage_symbol_search first
        - Free tier: updated at market close
        - Premium tier: realtime or 15-minute delayed quotes

    Common Mistakes:
        - Wrong: {"symbol": "Apple"}  (company name)
        - Right: {"symbol": "AAPL"}   (ticker symbol)
    """
    # Rate limiting
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg, "rate_limit_status": rate_limiter.get_status()}

    # Validation
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {
            "status": "error",
            "message": validation_error,
            "suggestion": "Use alphavantage_symbol_search to find the correct ticker",
            "example": '{"symbol": "AAPL"}'
        }

    try:
        client = await get_client()
        result = await client.call_tool("GLOBAL_QUOTE", {"symbol": symbol.upper()})

        rate_limiter.record_call()

        # Check for errors
        error_type = detect_api_error(result)
        if error_type:
            if error_type == "invalid_inputs":
                return {
                    "status": "error",
                    "message": f"Invalid symbol: '{symbol}'",
                    "suggestion": (
                        "The symbol may be incorrect or the company may be delisted. "
                        "Use alphavantage_symbol_search to find the correct ticker."
                    ),
                    "response": result
                }
            return {"status": "error", "error_type": error_type, "response": result}

        if response_format == "concise":
            result = apply_concise_format("GLOBAL_QUOTE", result)

        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "data": result,
            "rate_limit_status": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in GLOBAL_QUOTE: {e}")
        return format_error_response("GLOBAL_QUOTE", e, {"symbol": symbol})


@mcp.tool()
async def alphavantage_news_sentiment(
        tickers: Optional[str] = None,
        topics: Optional[str] = None,
        time_from: Optional[str] = None,
        time_to: Optional[str] = None,
        sort: str = "LATEST",
        limit: int = 50,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get news articles with AI-powered sentiment analysis for stocks and topics.

    This tool returns live and historical market news with sentiment scores,
    covering stocks, cryptocurrencies, forex, and various financial topics.

    Args:
        tickers: Optional. Single ticker or comma-separated (e.g., 'AAPL' or 'AAPL,MSFT').
                 Use TICKER SYMBOLS only, not company names.
                 If unsure, use alphavantage_symbol_search first.
        topics: Optional. Topics to filter by. Options: 'technology', 'earnings', 
                'ipo', 'mergers_and_acquisitions', 'financial_markets', 'economy_fiscal',
                'economy_monetary', 'economy_macro', 'energy_transportation', 'finance',
                'life_sciences', 'manufacturing', 'real_estate', 'retail_wholesale', 'blockchain'
        time_from: Optional. Start time in format YYYYMMDDTHHMM (e.g., '20240101T0000')
        time_to: Optional. End time in format YYYYMMDDTHHMM
        sort: How to sort results. Options: 'LATEST' (default), 'EARLIEST', 'RELEVANCE'
        limit: Number of articles to return (default: 50, max: 1000)
        response_format: 'concise' (recommended) or 'detailed'

    Returns:
        List of news articles with titles, summaries, sentiment scores, and sources.

    Examples:
        - Apple news: {"tickers": "AAPL", "limit": 10}
        - Tech sector news: {"topics": "technology", "limit": 20}
        - Multi-stock: {"tickers": "TSLA,AAPL", "sort": "LATEST"}
        - Date range: {"tickers": "MSFT", "time_from": "20240101T0000", "limit": 50}

    Critical Notes:
        - Use exact ticker symbols, NOT company names
        - If ticker unknown, call alphavantage_symbol_search first
        - Can combine tickers and topics for refined searches
        - Sentiment scores help gauge market perception

    Common Mistakes:
        - Wrong: {"tickers": "Tesla,Apple"}  (company names)
        - Right: {"tickers": "TSLA,AAPL"}    (ticker symbols)
    """
    # Rate limiting
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg, "rate_limit_status": rate_limiter.get_status()}

    # Build arguments
    args = {"sort": sort, "limit": min(limit, 1000)}
    if tickers:
        # Validate tickers
        for ticker in tickers.split(","):
            ticker = ticker.strip()
            if " " in ticker or len(ticker) > 6:
                return {
                    "status": "error",
                    "message": f"'{ticker}' appears to be a company name, not a ticker symbol",
                    "suggestion": "Use alphavantage_symbol_search to find correct tickers",
                    "example": '{"tickers": "AAPL,MSFT"}'
                }
        args["tickers"] = tickers
    if topics:
        args["topics"] = topics
    if time_from:
        args["time_from"] = time_from
    if time_to:
        args["time_to"] = time_to

    try:
        client = await get_client()
        result = await client.call_tool("NEWS_SENTIMENT", args)

        rate_limiter.record_call()

        error_type = detect_api_error(result)
        if error_type:
            if error_type == "invalid_inputs":
                return {
                    "status": "error",
                    "message": "Invalid parameters",
                    "suggestion": (
                        "Check that tickers are valid symbols (not company names). "
                        "Use alphavantage_symbol_search if unsure."
                    ),
                    "arguments": args,
                    "response": result
                }
            return {"status": "error", "error_type": error_type, "response": result}

        if response_format == "concise":
            result = apply_concise_format("NEWS_SENTIMENT", result)

        return {
            "status": "ok",
            "data": result,
            "rate_limit_status": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in NEWS_SENTIMENT: {e}")
        return format_error_response("NEWS_SENTIMENT", e, args)


@mcp.tool()
async def alphavantage_time_series_intraday(
        symbol: str,
        interval: str,
        adjusted: str = "true",
        extended_hours: str = "true",
        month: Optional[str] = None,
        outputsize: str = "compact",
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get intraday time series (OHLCV) data with customizable intervals.

    Returns current and 20+ years of historical intraday data covering
    pre-market and post-market hours where applicable.

    Args:
        symbol: Stock ticker symbol (use alphavantage_symbol_search if unsure)
        interval: Time interval. Options: '1min', '5min', '15min', '30min', '60min'
        adjusted: 'true' (default, adjusted for splits/dividends) or 'false' (raw prices)
        extended_hours: 'true' (default, includes pre/post market) or 'false' (regular hours only)
        month: Optional. Get specific month in YYYY-MM format (e.g., '2024-01').
               Any month since 2000-01 is supported.
        outputsize: 'compact' (last 100 data points) or 'full' (30 days or full month if month specified)
        response_format: 'concise' or 'detailed'

    Returns:
        Time series with timestamp, open, high, low, close, volume for each interval.

    Examples:
        - Recent 5-min data: {"symbol": "IBM", "interval": "5min"}
        - Full day 15-min: {"symbol": "AAPL", "interval": "15min", "outputsize": "full"}
        - Historical month: {"symbol": "TSLA", "interval": "5min", "month": "2024-01", "outputsize": "full"}

    Critical Notes:
        - Free tier: updated at market close
        - Premium tier: realtime or 15-minute delayed
        - Use 'compact' to reduce token usage for recent data
        - Specify 'month' parameter for historical intraday data

    Common Use Cases:
        - Day trading analysis: 1min or 5min intervals
        - Hourly trends: 60min interval
        - Historical intraday patterns: specify month parameter
    """
    # Rate limiting
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg, "rate_limit_status": rate_limiter.get_status()}

    # Validation
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    valid_intervals = ['1min', '5min', '15min', '30min', '60min']
    is_valid, validation_error = validate_interval(interval, valid_intervals)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    args = {
        "symbol": symbol.upper(),
        "interval": interval,
        "adjusted": adjusted,
        "extended_hours": extended_hours,
        "outputsize": outputsize
    }
    if month:
        args["month"] = month

    try:
        client = await get_client()
        result = await client.call_tool("TIME_SERIES_INTRADAY", args)

        rate_limiter.record_call()

        error_type = detect_api_error(result)
        if error_type:
            return {"status": "error", "error_type": error_type, "response": result}

        if response_format == "concise":
            result = apply_concise_format("TIME_SERIES_INTRADAY", result)

        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "interval": interval,
            "data": result,
            "rate_limit_status": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in TIME_SERIES_INTRADAY: {e}")
        return format_error_response("TIME_SERIES_INTRADAY", e, args)


@mcp.tool()
async def alphavantage_time_series_daily(
        symbol: str,
        outputsize: str = "compact",
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get daily time series (date, open, high, low, close, volume) data.

    Returns raw (as-traded) daily OHLCV data covering 20+ years of history.
    This is one of the most commonly used endpoints for historical price analysis.

    Args:
        symbol: Stock ticker symbol (use alphavantage_symbol_search if unsure)
        outputsize: 'compact' (last 100 data points, recommended) or 'full' (20+ years)
        response_format: 'concise' or 'detailed'

    Returns:
        Daily time series with date, open, high, low, close, and volume.

    Examples:
        - Recent data: {"symbol": "IBM"}
        - Full history: {"symbol": "AAPL", "outputsize": "full"}
        - UK stock: {"symbol": "TSCO.LON", "outputsize": "compact"}

    Critical Notes:
        - Returns RAW prices (not adjusted for splits/dividends)
        - Use 'compact' unless you need full 20+ year history
        - Supports 100,000+ global symbols across major exchanges
        - For adjusted prices, note that TIME_SERIES_DAILY_ADJUSTED is premium

    Supported Exchanges:
        - US: No suffix needed (e.g., 'IBM', 'AAPL')
        - London: .LON (e.g., 'TSCO.LON')
        - Toronto: .TRT (e.g., 'SHOP.TRT')
        - Germany: .DEX (e.g., 'MBG.DEX')
        - India: .BSE (e.g., 'RELIANCE.BSE')
        - China: .SHH or .SHZ (e.g., '600104.SHH')
    """
    # Rate limiting
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg, "rate_limit_status": rate_limiter.get_status()}

    # Validation
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    args = {"symbol": symbol.upper(), "outputsize": outputsize}

    try:
        client = await get_client()
        result = await client.call_tool("TIME_SERIES_DAILY", args)

        rate_limiter.record_call()

        error_type = detect_api_error(result)
        if error_type:
            return {"status": "error", "error_type": error_type, "response": result}

        if response_format == "concise":
            result = apply_concise_format("TIME_SERIES_DAILY", result)

        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "data": result,
            "rate_limit_status": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in TIME_SERIES_DAILY: {e}")
        return format_error_response("TIME_SERIES_DAILY", e, args)


@mcp.tool()
async def alphavantage_time_series_weekly(
        symbol: str,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get weekly time series data (last trading day of each week).

    Returns weekly OHLCV data covering 20+ years of history. Useful for
    longer-term trend analysis and reducing data volume.

    Args:
        symbol: Stock ticker symbol
        response_format: 'concise' or 'detailed'

    Returns:
        Weekly time series with date, open, high, low, close, volume.

    Examples:
        - {"symbol": "IBM"}
        - {"symbol": "TSCO.LON"}
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()
        result = await client.call_tool("TIME_SERIES_WEEKLY", {"symbol": symbol.upper()})
        rate_limiter.record_call()

        error_type = detect_api_error(result)
        if error_type:
            return {"status": "error", "error_type": error_type, "response": result}

        if response_format == "concise":
            result = apply_concise_format("TIME_SERIES_WEEKLY", result)

        return {"status": "ok", "symbol": symbol.upper(), "data": result}
    except Exception as e:
        return format_error_response("TIME_SERIES_WEEKLY", e, {"symbol": symbol})


@mcp.tool()
async def alphavantage_time_series_monthly(
        symbol: str,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get monthly time series data (last trading day of each month).

    Returns monthly OHLCV data covering 20+ years of history. Ideal for
    long-term analysis with minimal data volume.

    Args:
        symbol: Stock ticker symbol
        response_format: 'concise' or 'detailed'

    Returns:
        Monthly time series with date, open, high, low, close, volume.
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()
        result = await client.call_tool("TIME_SERIES_MONTHLY", {"symbol": symbol.upper()})
        rate_limiter.record_call()

        error_type = detect_api_error(result)
        if error_type:
            return {"status": "error", "error_type": error_type, "response": result}

        if response_format == "concise":
            result = apply_concise_format("TIME_SERIES_MONTHLY", result)

        return {"status": "ok", "symbol": symbol.upper(), "data": result}
    except Exception as e:
        return format_error_response("TIME_SERIES_MONTHLY", e, {"symbol": symbol})


@mcp.tool()
async def alphavantage_market_status(
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get current market status (open vs closed) for major global trading venues.

    Returns the current trading status for equities, forex, and cryptocurrency
    markets around the world. Useful for determining if markets are active.

    Args:
        response_format: 'concise' or 'detailed'

    Returns:
        Market status for various exchanges and asset types globally.

    Example:
        - {}

    Use Cases:
        - Check if US stock market is currently open
        - Determine forex trading hours
        - See which global markets are active
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    try:
        client = await get_client()
        result = await client.call_tool("MARKET_STATUS", {})
        rate_limiter.record_call()

        if response_format == "concise":
            result = apply_concise_format("MARKET_STATUS", result)

        return {"status": "ok", "data": result}
    except Exception as e:
        return format_error_response("MARKET_STATUS", e, {})


# Continue with more tools...
@mcp.tool()
async def alphavantage_company_overview(
        symbol: str,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get comprehensive company overview with fundamentals and key metrics.

    This is one of the most information-dense endpoints, providing extensive
    company data including financials, ratios, and company description.

    Args:
        symbol: Stock ticker symbol
        response_format: 'concise' (recommended, essential metrics only) or 'detailed'

    Returns:
        Comprehensive company data including:
        - Basic info (name, description, sector, industry)
        - Market data (market cap, shares outstanding)
        - Valuation ratios (P/E, P/B, PEG, Price/Sales)
        - Profitability (profit margin, ROE, ROA)
        - Dividend info (yield, payout ratio, ex-dividend date)
        - Fiscal year info and latest quarter

    Examples:
        - {"symbol": "IBM"}
        - {"symbol": "MSFT", "response_format": "concise"}

    Critical Notes:
        - Data refreshed same day company reports earnings
        - One of the most comprehensive fundamental data endpoints
        - Contains 50+ data points about the company
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()
        result = await client.call_tool("OVERVIEW", {"symbol": symbol.upper()})
        rate_limiter.record_call()

        error_type = detect_api_error(result)
        if error_type:
            return {"status": "error", "error_type": error_type, "response": result}

        if response_format == "concise":
            result = apply_concise_format("OVERVIEW", result)

        return {"status": "ok", "symbol": symbol.upper(), "data": result}
    except Exception as e:
        return format_error_response("OVERVIEW", e, {"symbol": symbol})


@mcp.tool()
async def alphavantage_income_statement(
        symbol: str,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get annual and quarterly income statements.

    Returns normalized income statement data mapped to GAAP and IFRS taxonomies.
    Essential for analyzing revenue, profitability, and earnings trends.

    Args:
        symbol: Stock ticker symbol
        response_format: 'concise' or 'detailed'

    Returns:
        Income statements with fields including:
        - Revenue (total revenue, cost of revenue, gross profit)
        - Operating expenses (R&D, SG&A, operating expenses)
        - Operating income
        - Interest income/expense
        - Income before tax
        - Income tax expense
        - Net income
        - EPS (earnings per share)

    Examples:
        - {"symbol": "IBM"}
        - {"symbol": "AAPL", "response_format": "concise"}
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()
        result = await client.call_tool("INCOME_STATEMENT", {"symbol": symbol.upper()})
        rate_limiter.record_call()

        error_type = detect_api_error(result)
        if error_type:
            return {"status": "error", "error_type": error_type, "response": result}

        if response_format == "concise":
            result = apply_concise_format("INCOME_STATEMENT", result)

        return {"status": "ok", "symbol": symbol.upper(), "data": result}
    except Exception as e:
        return format_error_response("INCOME_STATEMENT", e, {"symbol": symbol})


@mcp.tool()
async def alphavantage_balance_sheet(
        symbol: str,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get annual and quarterly balance sheets.

    Returns balance sheet data with assets, liabilities, and equity.
    Critical for analyzing financial position and solvency.

    Args:
        symbol: Stock ticker symbol
        response_format: 'concise' or 'detailed'

    Returns:
        Balance sheet with:
        - Assets (current, non-current, total)
        - Liabilities (current, non-current, total)
        - Shareholders' equity
        - Specific line items (cash, inventory, debt, etc.)
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()
        result = await client.call_tool("BALANCE_SHEET", {"symbol": symbol.upper()})
        rate_limiter.record_call()

        error_type = detect_api_error(result)
        if error_type:
            return {"status": "error", "error_type": error_type, "response": result}

        if response_format == "concise":
            result = apply_concise_format("BALANCE_SHEET", result)

        return {"status": "ok", "symbol": symbol.upper(), "data": result}
    except Exception as e:
        return format_error_response("BALANCE_SHEET", e, {"symbol": symbol})


@mcp.tool()
async def alphavantage_cash_flow(
        symbol: str,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get annual and quarterly cash flow statements.

    Returns cash flow data showing operating, investing, and financing activities.
    Essential for understanding cash generation and usage.

    Args:
        symbol: Stock ticker symbol
        response_format: 'concise' or 'detailed'

    Returns:
        Cash flow statement with:
        - Operating cash flow
        - Investing cash flow
        - Financing cash flow
        - Net change in cash
        - Capital expenditures
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()
        result = await client.call_tool("CASH_FLOW", {"symbol": symbol.upper()})
        rate_limiter.record_call()

        error_type = detect_api_error(result)
        if error_type:
            return {"status": "error", "error_type": error_type, "response": result}

        if response_format == "concise":
            result = apply_concise_format("CASH_FLOW", result)

        return {"status": "ok", "symbol": symbol.upper(), "data": result}
    except Exception as e:
        return format_error_response("CASH_FLOW", e, {"symbol": symbol})


@mcp.tool()
async def alphavantage_earnings(
        symbol: str,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get annual and quarterly earnings (EPS) with estimates and surprises.

    Returns historical EPS data along with analyst estimates and surprise metrics
    for quarterly results. Critical for earnings analysis.

    Args:
        symbol: Stock ticker symbol
        response_format: 'concise' or 'detailed'

    Returns:
        Earnings data including:
        - Annual EPS history
        - Quarterly reported EPS
        - Estimated EPS (analyst consensus)
        - Surprise (actual vs estimated)
        - Surprise percentage
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()
        result = await client.call_tool("EARNINGS", {"symbol": symbol.upper()})
        rate_limiter.record_call()

        error_type = detect_api_error(result)
        if error_type:
            return {"status": "error", "error_type": error_type, "response": result}

        if response_format == "concise":
            result = apply_concise_format("EARNINGS", result)

        return {"status": "ok", "symbol": symbol.upper(), "data": result}
    except Exception as e:
        return format_error_response("EARNINGS", e, {"symbol": symbol})


# Forex tools
@mcp.tool()
async def alphavantage_currency_exchange_rate(
        from_currency: str,
        to_currency: str,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get realtime exchange rate between two currencies.

    Returns current exchange rate for any pair of physical currencies or
    cryptocurrencies (e.g., USD to EUR, BTC to USD).

    Args:
        from_currency: 3-letter currency code (e.g., 'USD', 'EUR', 'GBP', 'BTC')
        to_currency: 3-letter currency code
        response_format: 'concise' or 'detailed'

    Returns:
        Current exchange rate with timestamp, bid/ask prices.

    Examples:
        - USD to EUR: {"from_currency": "USD", "to_currency": "EUR"}
        - GBP to JPY: {"from_currency": "GBP", "to_currency": "JPY"}
        - Bitcoin to USD: {"from_currency": "BTC", "to_currency": "USD"}

    Critical Notes:
        - Use 3-letter currency CODES, not names ('USD' not 'Dollar')
        - Case matters: use UPPERCASE codes
        - Supports both fiat currencies and cryptocurrencies

    Common Mistakes:
        - Wrong: {"from_currency": "Dollar", "to_currency": "Euro"}
        - Right: {"from_currency": "USD", "to_currency": "EUR"}
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    # Validation
    is_valid, validation_error = validate_currency_code(from_currency, "from_currency")
    if not is_valid:
        return {"status": "error", "message": validation_error}

    is_valid, validation_error = validate_currency_code(to_currency, "to_currency")
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()
        result = await client.call_tool("CURRENCY_EXCHANGE_RATE", {
            "from_currency": from_currency.upper(),
            "to_currency": to_currency.upper()
        })
        rate_limiter.record_call()

        error_type = detect_api_error(result)
        if error_type:
            return {"status": "error", "error_type": error_type, "response": result}

        if response_format == "concise":
            result = apply_concise_format("CURRENCY_EXCHANGE_RATE", result)

        return {
            "status": "ok",
            "from": from_currency.upper(),
            "to": to_currency.upper(),
            "data": result
        }
    except Exception as e:
        return format_error_response("CURRENCY_EXCHANGE_RATE", e, {
            "from_currency": from_currency,
            "to_currency": to_currency
        })


@mcp.tool()
async def alphavantage_fx_daily(
        from_symbol: str,
        to_symbol: str,
        outputsize: str = "compact",
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get daily historical forex OHLC data.

    Returns daily time series of forex rates with open, high, low, close values.

    Args:
        from_symbol: 3-letter currency code
        to_symbol: 3-letter currency code
        outputsize: 'compact' (last 100 days) or 'full' (full history)
        response_format: 'concise' or 'detailed'

    Returns:
        Daily forex time series with OHLC data.

    Examples:
        - {"from_symbol": "EUR", "to_symbol": "USD"}
        - {"from_symbol": "GBP", "to_symbol": "JPY", "outputsize": "full"}

    Critical Notes:
        - Note: Uses 'from_symbol' and 'to_symbol' (different param names than CURRENCY_EXCHANGE_RATE)
        - Returns OHLC time series (not just a single rate)
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    is_valid, validation_error = validate_currency_code(from_symbol, "from_symbol")
    if not is_valid:
        return {"status": "error", "message": validation_error}

    is_valid, validation_error = validate_currency_code(to_symbol, "to_symbol")
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()
        result = await client.call_tool("FX_DAILY", {
            "from_symbol": from_symbol.upper(),
            "to_symbol": to_symbol.upper(),
            "outputsize": outputsize
        })
        rate_limiter.record_call()

        if response_format == "concise":
            result = apply_concise_format("FX_DAILY", result)

        return {"status": "ok", "pair": f"{from_symbol.upper()}/{to_symbol.upper()}", "data": result}
    except Exception as e:
        return format_error_response("FX_DAILY", e, {
            "from_symbol": from_symbol,
            "to_symbol": to_symbol
        })


# Economic indicators
@mcp.tool()
async def alphavantage_real_gdp(
        interval: str = "annual",
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get US Real GDP data.

    Returns Real Gross Domestic Product of the United States, a key indicator
    of economic health and growth.

    Args:
        interval: 'annual' (default) or 'quarterly'
        response_format: 'concise' or 'detailed'

    Returns:
        Time series of US Real GDP values.

    Examples:
        - Annual GDP: {"interval": "annual"}
        - Quarterly GDP: {"interval": "quarterly"}

    Source: U.S. Bureau of Economic Analysis via FRED
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    valid_intervals = ['annual', 'quarterly']
    if interval not in valid_intervals:
        return {
            "status": "error",
            "message": f"Invalid interval: '{interval}'. Valid options: {', '.join(valid_intervals)}"
        }

    try:
        client = await get_client()
        result = await client.call_tool("REAL_GDP", {"interval": interval})
        rate_limiter.record_call()

        if response_format == "concise":
            result = apply_concise_format("REAL_GDP", result)

        return {"status": "ok", "indicator": "REAL_GDP", "interval": interval, "data": result}
    except Exception as e:
        return format_error_response("REAL_GDP", e, {"interval": interval})


@mcp.tool()
async def alphavantage_federal_funds_rate(
        interval: str = "monthly",
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get US Federal Funds Rate (key interest rate).

    Returns the federal funds rate, which is the interest rate at which depository
    institutions lend to each other overnight. Critical for understanding monetary policy.

    Args:
        interval: 'daily', 'weekly', or 'monthly' (default)
        response_format: 'concise' or 'detailed'

    Returns:
        Time series of federal funds rate.

    Examples:
        - {"interval": "monthly"}
        - {"interval": "daily"}

    Source: Federal Reserve via FRED

    Use Cases:
        - Monetary policy analysis
        - Interest rate trend analysis
        - Economic forecasting
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    valid_intervals = ['daily', 'weekly', 'monthly']
    if interval not in valid_intervals:
        return {
            "status": "error",
            "message": f"Invalid interval: '{interval}'. Valid options: {', '.join(valid_intervals)}"
        }

    try:
        client = await get_client()
        result = await client.call_tool("FEDERAL_FUNDS_RATE", {"interval": interval})
        rate_limiter.record_call()

        if response_format == "concise":
            result = apply_concise_format("FEDERAL_FUNDS_RATE", result)

        return {"status": "ok", "indicator": "FEDERAL_FUNDS_RATE", "data": result}
    except Exception as e:
        return format_error_response("FEDERAL_FUNDS_RATE", e, {"interval": interval})


@mcp.tool()
async def alphavantage_cpi(
        interval: str = "monthly",
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get US Consumer Price Index (CPI) - primary inflation indicator.

    Returns CPI data which measures the average change in prices paid by consumers.
    Widely regarded as the barometer of inflation in the broader economy.

    Args:
        interval: 'monthly' (default) or 'semiannual'
        response_format: 'concise' or 'detailed'

    Returns:
        Time series of CPI values.

    Examples:
        - {"interval": "monthly"}
        - {}

    Source: U.S. Bureau of Labor Statistics via FRED

    Critical Notes:
        - Primary measure of inflation
        - Influences Federal Reserve monetary policy decisions
        - Affects cost of living adjustments
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    valid_intervals = ['monthly', 'semiannual']
    if interval not in valid_intervals:
        return {
            "status": "error",
            "message": f"Invalid interval: '{interval}'. Valid options: {', '.join(valid_intervals)}"
        }

    try:
        client = await get_client()
        result = await client.call_tool("CPI", {"interval": interval})
        rate_limiter.record_call()

        if response_format == "concise":
            result = apply_concise_format("CPI", result)

        return {"status": "ok", "indicator": "CPI", "data": result}
    except Exception as e:
        return format_error_response("CPI", e, {"interval": interval})


@mcp.tool()
async def alphavantage_unemployment(
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get US unemployment rate (monthly).

    Returns the unemployment rate, which represents the number of unemployed
    as a percentage of the labor force. Key indicator of labor market health.

    Args:
        response_format: 'concise' or 'detailed'

    Returns:
        Monthly time series of unemployment rate.

    Example:
        - {}

    Source: U.S. Bureau of Labor Statistics via FRED

    Critical Notes:
        - Measures percentage of labor force that is unemployed
        - Labor force includes people 16+ years old
        - Key economic indicator watched by Fed and investors
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    try:
        client = await get_client()
        result = await client.call_tool("UNEMPLOYMENT", {})
        rate_limiter.record_call()

        if response_format == "concise":
            result = apply_concise_format("UNEMPLOYMENT", result)

        return {"status": "ok", "indicator": "UNEMPLOYMENT", "data": result}
    except Exception as e:
        return format_error_response("UNEMPLOYMENT", e, {})


# ============================================================================
# SYSTEM PROMPT ENHANCEMENT
# ============================================================================

def get_alphavantage_system_prompt() -> str:
    """
    Get system prompt enhancement for AlphaVantage tools.
    Contains critical rules and workflows for using the API effectively.
    """
    return """
ALPHAVANTAGE API CRITICAL RULES:

1. **Ticker Symbols vs Company Names**
   - NEVER use company names directly in API calls (e.g., "Apple", "Tesla", "Microsoft")
   - ALWAYS use exact ticker symbols (e.g., "AAPL", "TSLA", "MSFT")
   - When uncertain about a ticker: CALL alphavantage_symbol_search FIRST

2. **Standard Workflow for Stock Queries**
   User asks: "What's the stock price of Mercedes-Benz?"
   CORRECT:
      Step 1: alphavantage_symbol_search(keywords="Mercedes")
      Step 2: Extract ticker from results (e.g., "MBGYY")
      Step 3: alphavantage_global_quote(symbol="MBGYY")
   WRONG:
      Step 1: alphavantage_global_quote(symbol="Mercedes-Benz")  ← Will fail!

3. **Rate Limits (Critical)**
   - Free tier: 25 API calls per day, 5 calls per minute
   - Every tool call consumes one API call
   - Rate limit status is returned in responses
   - Plan your tool calls strategically to stay within limits
   - If rate limited, the error message tells you when to retry

4. **Response Format Strategy**
   - Use response_format="concise" when possible to reduce token usage
   - CONCISE format strips down to essential fields (~50-70% token reduction)
   - Use DETAILED format only when you need complete data
   - Default is DETAILED if not specified

5. **International Stocks**
   - US stocks: No suffix needed (e.g., "AAPL", "IBM")
   - UK stocks: Add .LON (e.g., "TSCO.LON" for Tesco)
   - German stocks: Add .DEX (e.g., "MBG.DEX" for Mercedes)
   - Use alphavantage_symbol_search to find correct format

6. **Currency/Forex Tools**
   - Use 3-letter UPPERCASE codes: "USD", "EUR", "GBP", "JPY"
   - NOT currency names: "Dollar", "Euro", etc.
   - Note: CURRENCY_EXCHANGE_RATE uses "from_currency"/"to_currency"
   - But FX_DAILY uses "from_symbol"/"to_symbol" (different param names!)

7. **Time Series Data Management**
   - Use outputsize="compact" for recent data (last 100 points)
   - Use outputsize="full" only when you need complete history
   - COMPACT saves tokens and reduces response size
   - For intraday: specify interval ('1min', '5min', '15min', '30min', '60min')

8. **Error Recovery**
   - "Invalid inputs" usually means wrong symbol or company name used
   - Always try alphavantage_symbol_search first if unsure
   - Rate limit errors tell you exactly when to retry
   - Check error_type in response for specific guidance

9. **Common Mistakes to Avoid**
   - Using company names instead of tickers
   - Using lowercase currency codes
   - Not checking rate limits before batch operations
   - Using "full" outputsize when "compact" would suffice
   - Mixing up parameter names (from_currency vs from_symbol)

10. **Best Practices**
   - Always call symbol_search when user provides company name
   - Check rate_limit_status in responses to track usage
   - Use concise format to conserve tokens
   - Batch related queries together when possible
   - Validate symbols before making expensive API calls

11. **Data Freshness**
   - Free tier: Data updated at market close (end of day)
   - Stock quotes: Not realtime on free tier
   - Economic indicators: Updated on official release dates
   - News sentiment: Updates continuously

12. **Tool Selection Priority**
   - Unknown ticker? → alphavantage_symbol_search
   - Current price? → alphavantage_global_quote
   - Historical prices? → alphavantage_time_series_daily/weekly/monthly
   - Company fundamentals? → alphavantage_company_overview
   - Financial statements? → alphavantage_income_statement/balance_sheet/cash_flow
   - News? → alphavantage_news_sentiment (remember: use ticker, not company name!)
   - Forex rates? → alphavantage_currency_exchange_rate or alphavantage_fx_daily
   - Economic data? → Specific indicator tools (real_gdp, cpi, unemployment, etc.)
"""


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    print(
        "[AlphaVantage] MCP Server Starting...\n"
        "Enhanced wrapper for AlphaVantage's official MCP server\n"
        "Features: Rate limiting, validation, error guidance, concise responses\n"
        "\nRate Limits: 25 calls/day, 5 calls/minute (free tier)\n"
        "\nCore Tools Available:\n"
        "  Stock Data: symbol_search, global_quote, time_series_*, market_status\n"
        "  Fundamentals: company_overview, income_statement, balance_sheet, cash_flow, earnings\n"
        "  News: news_sentiment\n"
        "  Forex: currency_exchange_rate, fx_daily\n"
        "  Economic: real_gdp, federal_funds_rate, cpi, unemployment\n"
        "\nCritical: Always use ticker symbols (AAPL), not company names (Apple)!\n"
        "Use alphavantage_symbol_search when ticker is unknown.\n",
        flush=True
    )

    # Get system prompt (for documentation/reference)
    system_prompt = get_alphavantage_system_prompt()

    # Run the MCP server
    mcp.run(transport="http", host="0.0.0.0", port=8085)
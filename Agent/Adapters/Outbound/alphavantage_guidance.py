# Agent/Adapters/Outbound/alphavantage_guidance.py
"""
Alpha Vantage tool guidance and validation.
This module provides tool-specific knowledge to help the LLM use Alpha Vantage APIs correctly.
"""
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Comprehensive tool guidance for Alpha Vantage
ALPHAVANTAGE_TOOLS = {
    "NEWS_SENTIMENT": {
        "description": "Get news sentiment for stocks with sentiment scores.",
        "parameters": {
            "tickers": "Optional. Single ticker or comma-separated (e.g., 'AAPL' or 'AAPL,MSFT'). Use SYMBOL_SEARCH if unsure.",
            "topics": "Optional. Topics: 'technology', 'earnings', 'ipo', 'merger_acquisition', 'finance', etc.",
            "time_from": "Optional. Format: YYYYMMDDTHHMM (e.g., '20240101T0000')",
            "time_to": "Optional. Format: YYYYMMDDTHHMM",
            "sort": "Optional. 'LATEST', 'EARLIEST', or 'RELEVANCE' (default: LATEST)",
            "limit": "Optional. Number of results (default: 50, max: 1000)"
        },
        "critical_notes": [
            "Use exact ticker symbols, NOT company names",
            "If unsure about ticker, call SYMBOL_SEARCH first",
            "Common issue: Using 'Mercedes-Benz' instead of finding ticker 'MBGYY' first"
        ],
        "examples": [
            '{"tickers": "AAPL", "limit": 10}',
            '{"topics": "technology", "limit": 20}',
            '{"tickers": "TSLA,AAPL", "sort": "LATEST"}'
        ],
        "fallback": {"limit": 50}
    },

    "SYMBOL_SEARCH": {
        "description": "Search for stock ticker symbols by company name or keywords.",
        "parameters": {
            "keywords": "Required. Company name or keywords (e.g., 'Microsoft', 'Apple', 'Mercedes')"
        },
        "critical_notes": [
            "ALWAYS use this first when you have a company name but not ticker",
            "Returns multiple matches with their ticker symbols"
        ],
        "examples": [
            '{"keywords": "Microsoft"}',
            '{"keywords": "Mercedes"}',
            '{"keywords": "Apple"}'
        ]
    },

    "GLOBAL_QUOTE": {
        "description": "Get real-time stock quote with price, volume, and daily change.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol (e.g., 'AAPL', 'TSLA', 'MSFT')"
        },
        "critical_notes": [
            "Use ticker symbol, not company name",
            "If unsure, use SYMBOL_SEARCH first"
        ],
        "examples": [
            '{"symbol": "AAPL"}',
            '{"symbol": "MSFT"}'
        ]
    },

    "TIME_SERIES_DAILY": {
        "description": "Get daily historical stock price data.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol",
            "outputsize": "Optional. 'compact' (last 100 days) or 'full' (20+ years of data)"
        },
        "examples": [
            '{"symbol": "AAPL"}',
            '{"symbol": "TSLA", "outputsize": "compact"}'
        ]
    },

    "TIME_SERIES_INTRADAY": {
        "description": "Get intraday (hourly/minute) stock price data.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol",
            "interval": "Required. '1min', '5min', '15min', '30min', or '60min'",
            "outputsize": "Optional. 'compact' or 'full'"
        },
        "examples": [
            '{"symbol": "AAPL", "interval": "5min"}',
            '{"symbol": "TSLA", "interval": "60min", "outputsize": "compact"}'
        ]
    },

    "CURRENCY_EXCHANGE_RATE": {
        "description": "Get real-time exchange rate between two currencies.",
        "parameters": {
            "from_currency": "Required. 3-letter currency code (USD, EUR, GBP, JPY, etc.)",
            "to_currency": "Required. 3-letter currency code"
        },
        "critical_notes": [
            "Use currency CODES (USD, EUR), not names (Dollar, Euro)",
            "Parameter names: 'from_currency' and 'to_currency' (not from_symbol)"
        ],
        "examples": [
            '{"from_currency": "USD", "to_currency": "EUR"}',
            '{"from_currency": "GBP", "to_currency": "JPY"}'
        ]
    },

    "FX_DAILY": {
        "description": "Get daily historical forex data.",
        "parameters": {
            "from_symbol": "Required. 3-letter currency code",
            "to_symbol": "Required. 3-letter currency code",
            "outputsize": "Optional. 'compact' (100 points) or 'full' (20+ years)"
        },
        "critical_notes": [
            "Note: Uses 'from_symbol' and 'to_symbol' (different from CURRENCY_EXCHANGE_RATE)"
        ],
        "examples": [
            '{"from_symbol": "EUR", "to_symbol": "USD"}',
            '{"from_symbol": "GBP", "to_symbol": "USD", "outputsize": "compact"}'
        ]
    },

    "CPI": {
        "description": "Get Consumer Price Index (inflation indicator) data.",
        "parameters": {
            "interval": "Optional. 'monthly', 'semiannual', or 'annual'"
        },
        "examples": [
            '{}',
            '{"interval": "monthly"}'
        ]
    },

    "REAL_GDP": {
        "description": "Get US Real Gross Domestic Product data.",
        "parameters": {
            "interval": "Optional. 'quarterly' or 'annual'"
        },
        "examples": [
            '{}',
            '{"interval": "quarterly"}'
        ]
    },

    "UNEMPLOYMENT": {
        "description": "Get US unemployment rate data.",
        "parameters": {},
        "examples": ['{}']
    },

    "FEDERAL_FUNDS_RATE": {
        "description": "Get US Federal Funds Rate (key interest rate).",
        "parameters": {
            "interval": "Optional. 'daily', 'weekly', 'monthly'"
        },
        "examples": [
            '{}',
            '{"interval": "monthly"}'
        ]
    },

    "OVERVIEW": {
        "description": "Get comprehensive company overview and fundamentals.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol"
        },
        "critical_notes": [
            "Returns extensive fundamental data: market cap, P/E ratio, dividend yield, etc."
        ],
        "examples": [
            '{"symbol": "AAPL"}',
            '{"symbol": "MSFT"}'
        ]
    },

    "INCOME_STATEMENT": {
        "description": "Get company income statements (quarterly or annual).",
        "parameters": {
            "symbol": "Required. Stock ticker symbol"
        },
        "examples": [
            '{"symbol": "AAPL"}'
        ]
    },

    "BALANCE_SHEET": {
        "description": "Get company balance sheets.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol"
        },
        "examples": [
            '{"symbol": "TSLA"}'
        ]
    },

    "CASH_FLOW": {
        "description": "Get company cash flow statements.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol"
        },
        "examples": [
            '{"symbol": "MSFT"}'
        ]
    },

    "EARNINGS": {
        "description": "Get company quarterly and annual earnings data.",
        "parameters": {
            "symbol": "Required. Stock ticker symbol"
        },
        "examples": [
            '{"symbol": "AAPL"}'
        ]
    }
}


class AlphaVantageValidator:
    """Validates and corrects Alpha Vantage tool calls"""

    @staticmethod
    def validate_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Validate and potentially correct tool arguments.

        Returns:
            (is_valid, corrected_arguments, error_message)
        """
        if tool_name not in ALPHAVANTAGE_TOOLS:
            return True, arguments, None

        tool_info = ALPHAVANTAGE_TOOLS[tool_name]
        corrected = arguments.copy()

        valid_params = set(tool_info['parameters'].keys())

        invalid_params = set(corrected.keys()) - valid_params
        if invalid_params:
            logger.warning(f"Removing invalid parameters from {tool_name}: {invalid_params}")
            for param in invalid_params:
                del corrected[param]

        if not corrected and 'fallback' in tool_info:
            logger.info(f"Using fallback parameters for {tool_name}")
            corrected = tool_info['fallback'].copy()

        return True, corrected, None

    @staticmethod
    def detect_error_in_response(response: str) -> Optional[str]:
        """
        Detect if Alpha Vantage returned an error message.

        Returns:
            Error type if detected, None otherwise
        """
        error_patterns = {
            "invalid_inputs": ["Invalid inputs", "Invalid API call"],
            "rate_limit": ["rate limit", "API rate limit exceeded"],
            "premium_required": ["premium endpoint", "premium feature"],
            "invalid_key": ["Invalid API key", "invalid key"],
            "missing_param": ["missing required parameter"]
        }

        response_lower = response.lower()

        for error_type, patterns in error_patterns.items():
            if any(pattern.lower() in response_lower for pattern in patterns):
                return error_type

        return None

    @staticmethod
    def get_error_guidance(tool_name: str, error_type: str, arguments: Dict[str, Any]) -> str:
        """
        Provide helpful guidance when an error occurs.
        """
        if error_type == "invalid_inputs":
            if tool_name == "NEWS_SENTIMENT":
                return (
                    f"NEWS_SENTIMENT failed with arguments: {arguments}. "
                    "Common issues:\n"
                    "1. You may be using a company name instead of ticker symbol\n"
                    "2. Try calling SYMBOL_SEARCH first to find the correct ticker\n"
                    "3. Or try with minimal params: {\"limit\": 50}"
                )
            elif tool_name in ["GLOBAL_QUOTE", "TIME_SERIES_DAILY", "OVERVIEW"]:
                return (
                    f"{tool_name} failed. The 'symbol' parameter must be an exact ticker symbol.\n"
                    f"Use SYMBOL_SEARCH with the company name to find the correct ticker first."
                )
            else:
                tool_info = ALPHAVANTAGE_TOOLS.get(tool_name, {})
                params = tool_info.get('parameters', {})
                return (
                    f"{tool_name} failed with arguments: {arguments}.\n"
                    f"Valid parameters: {list(params.keys())}\n"
                    f"Check that parameter names and formats are correct."
                )

        elif error_type == "rate_limit":
            return (
                "Alpha Vantage rate limit reached.\n"
                "- 5 API calls per minute\n"
                "- 100 API calls per day\n"
                "Wait a moment before retrying."
            )

        elif error_type == "premium_required":
            return f"{tool_name} requires a premium Alpha Vantage subscription."

        elif error_type == "invalid_key":
            return "Alpha Vantage API key is invalid or missing. Check your .config.json"

        return f"{tool_name} encountered an error. Check the Alpha Vantage documentation."

    @staticmethod
    def build_enhanced_tool_description(tool_name: str, base_description: str, schema: Dict) -> str:
        """
        Build an enhanced tool description with guidance.
        """
        if tool_name not in ALPHAVANTAGE_TOOLS:
            return base_description

        guidance = ALPHAVANTAGE_TOOLS[tool_name]

        parts = [
            f"**{tool_name}**",
            f"{guidance['description']}",
            "\nParameters:"
        ]

        for param, desc in guidance['parameters'].items():
            parts.append(f"  - {param}: {desc}")

        if guidance.get('critical_notes'):
            parts.append("\nImportant:")
            for note in guidance['critical_notes']:
                parts.append(f"  {note}")

        if guidance.get('examples'):
            parts.append(f"\nExample: {guidance['examples'][0]}")

        return "\n".join(parts)


def get_alphavantage_system_prompt_enhancement() -> str:
    """
    Get additional system prompt content specifically for Alpha Vantage tools.
    This should be appended to the main system prompt.
    """
    return """

ALPHA VANTAGE CRITICAL RULES:

1. **Ticker Symbols vs Company Names**
   - NEVER use company names directly (e.g., "Apple", "Tesla", "Mercedes-Benz")
   - ALWAYS use exact ticker symbols (e.g., "AAPL", "TSLA")
   - When uncertain about a ticker: CALL SYMBOL_SEARCH FIRST

2. **Common Workflow**
   User asks: "What's the news about Mercedes-Benz?"
   CORRECT:
      Step 1: SYMBOL_SEARCH(keywords="Mercedes")
      Step 2: Use returned ticker (e.g., "MBGYY") in NEWS_SENTIMENT
   WRONG:
      Step 1: NEWS_SENTIMENT(tickers="Mercedes-Benz")  ← Will fail!

3. **Parameter Formats**
   - Currency tools: Use 3-letter codes (USD, EUR, GBP) NOT names
   - CURRENCY_EXCHANGE_RATE: uses "from_currency", "to_currency"
   - FX_DAILY: uses "from_symbol", "to_symbol"
   - Date formats: YYYYMMDDTHHMM (e.g., "20240101T0000")

4. **Error Recovery Strategy**
   - If you get "Invalid inputs": Check if you're using company name instead of ticker
   - Always try SYMBOL_SEARCH first when dealing with company names
   - Start with minimal parameters, add more if needed

5. **Tool Selection Priority**
   - Unsure about ticker? → SYMBOL_SEARCH
   - Need current price? → GLOBAL_QUOTE
   - Need historical data? → TIME_SERIES_DAILY
   - Need news? → First SYMBOL_SEARCH, then NEWS_SENTIMENT
   - Need fundamentals? → OVERVIEW, INCOME_STATEMENT, etc.
"""
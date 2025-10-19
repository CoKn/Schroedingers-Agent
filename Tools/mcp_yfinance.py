from __future__ import annotations

import typing as t
from dataclasses import dataclass
from enum import Enum
from fastmcp import FastMCP

# Minimal deps; install: pip install yfinance pandas requests-cache
import yfinance as yf
import pandas as pd

try:
    import requests_cache

    _HAS_CACHE = True
except Exception:
    _HAS_CACHE = False


# -----------------------------------------------------------------------------
# Response Format Control (following article's guidance)
# -----------------------------------------------------------------------------
class ResponseFormat(str, Enum):
    """Control verbosity of tool responses for token efficiency."""
    CONCISE = "concise"  # High-signal info only, minimal tokens
    DETAILED = "detailed"  # Full data with all available fields


# -----------------------------------------------------------------------------
# MCP server
# -----------------------------------------------------------------------------
try:
    mcp = FastMCP(name="YahooFinance")
except TypeError:
    mcp = FastMCP()


# Enable polite HTTP cache (optional but recommended)
def _enable_cache():
    if _HAS_CACHE:
        requests_cache.install_cache(cache_name="yf_cache", expire_after=600)  # 10 min


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _df_to_records(df: pd.DataFrame, index_name: str = "date") -> list[dict]:
    df = df.copy()
    if df.index.name is None:
        df.index.name = index_name
    df.reset_index(inplace=True)
    # Convert Timestamp to ISO string for JSON
    for c in df.columns:
        if isinstance(df[c].dtype, pd.DatetimeTZDtype) or str(df[c].dtype).startswith("datetime"):
            df[c] = df[c].dt.strftime("%Y-%m-%d")
    return df.to_dict(orient="records")


def _safe_info(t: yf.Ticker, response_format: ResponseFormat) -> dict:
    """Extract ticker info with appropriate verbosity."""
    info = t.info or {}

    if response_format == ResponseFormat.CONCISE:
        # High-signal, natural language fields only
        return {
            "company_name": info.get("longName") or info.get("shortName"),
            "symbol": info.get("symbol") or getattr(t, "ticker", None),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "current_price": info.get("currentPrice"),
            "market_cap_usd": info.get("marketCap"),
            "description": info.get("longBusinessSummary", "")[:200] if info.get("longBusinessSummary") else None,
        }
    else:  # DETAILED
        # Include technical metrics with clear names
        return {
            "company_name": info.get("longName") or info.get("shortName"),
            "symbol": info.get("symbol") or getattr(t, "ticker", None),
            "currency": info.get("currency"),
            "exchange": info.get("exchange"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "current_price": info.get("currentPrice"),
            "market_cap_usd": info.get("marketCap"),
            "pe_ratio_trailing": info.get("trailingPE"),
            "pe_ratio_forward": info.get("forwardPE"),
            "price_to_book_ratio": info.get("priceToBook"),
            "beta": info.get("beta"),
            "dividend_yield_percent": info.get("dividendYield") * 100 if info.get("dividendYield") else None,
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "description": info.get("longBusinessSummary"),
        }


def _read_statement(df: pd.DataFrame, limit: int) -> list[dict]:
    """Return the last N columns as period-wise records."""
    if df is None or df.empty:
        return []
    # Yahoo statements are columns=periods, rows=line items
    cols = list(df.columns)[-limit:]
    sub = df[cols]
    # Build [{period: 'YYYY-MM-DD', items: {line: value, ...}}, ...]
    records = []
    for c in cols:
        block = {"period": str(getattr(c, "date", c)), "items": {}}
        for row_label, val in sub[c].items():
            try:
                # row_label may be e.g. "Total Revenue"
                block["items"][str(row_label)] = None if pd.isna(val) else float(val)
            except Exception:
                block["items"][str(row_label)] = val
        records.append(block)
    return records


def _format_error(symbol: str, error: Exception, suggestion: str = None) -> dict:
    """Format errors with actionable guidance for agents."""
    error_msg = str(error)

    # Provide helpful suggestions based on common errors
    if "No data found" in error_msg or "404" in error_msg:
        suggestion = (
            f"Symbol '{symbol}' not found. Common causes:\n"
            "1. Symbol may be incorrect (check spelling/format)\n"
            "2. Symbol may need exchange suffix (e.g., 'VOW3.DE' for German stocks)\n"
            "3. Company may be delisted or symbol changed\n"
            "Try searching for the company name to find the correct symbol."
        )
    elif "list index out of range" in error_msg or "empty" in error_msg.lower():
        suggestion = (
            f"No data available for '{symbol}' with the specified parameters. "
            "Try adjusting the time period or check if the symbol is valid."
        )
    elif "JSONDecodeError" in error_msg or "Invalid" in error_msg:
        suggestion = "Yahoo Finance API returned invalid data. Try again in a moment."

    return {
        "status": "error",
        "symbol": symbol.upper(),
        "error_type": type(error).__name__,
        "message": error_msg,
        "suggestion": suggestion or "Check symbol format and try again."
    }


# -----------------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------------
@mcp.tool()
def yfinance_get_company_overview(
        ticker_symbol: str,
        response_format: str = "concise"
) -> dict:
    """
    Get company overview and key metrics for a stock ticker.

    This tool provides essential information about a publicly traded company including
    its name, sector, market capitalization, and valuation metrics. Use this when you
    need to understand what a company does or get a quick snapshot of its fundamentals.

    Args:
        ticker_symbol: Stock ticker symbol (e.g., 'AAPL' for Apple, 'MSFT' for Microsoft).
                      For non-US stocks, include exchange suffix (e.g., 'VOW3.DE' for Volkswagen).
        response_format: Either 'concise' (recommended, ~50-100 tokens with key info only)
                        or 'detailed' (~200-300 tokens with full metrics and description).

    Returns:
        Company name, sector, market cap, current price, and valuation ratios.
        Concise format returns only essential fields; detailed includes full metrics.

    Examples:
        - "What does Apple do?" → yfinance_get_company_overview("AAPL", "concise")
        - "Get detailed metrics for Tesla" → yfinance_get_company_overview("TSLA", "detailed")
        - "Tell me about Microsoft" → yfinance_get_company_overview("MSFT", "concise")
    """
    _enable_cache()

    # Validate response format
    try:
        fmt = ResponseFormat(response_format.lower())
    except ValueError:
        return {
            "status": "error",
            "message": f"Invalid response_format: '{response_format}'",
            "suggestion": "Use 'concise' for essential info (~50-100 tokens) or 'detailed' for complete metrics (~200-300 tokens)"
        }

    try:
        tkr = yf.Ticker(ticker_symbol)
        snapshot = _safe_info(tkr, fmt)

        return {
            "status": "ok",
            "symbol": ticker_symbol.upper(),
            "data": snapshot,
            "format": response_format
        }
    except Exception as e:
        return _format_error(ticker_symbol, e)


@mcp.tool()
def yfinance_get_price_history(
        ticker_symbol: str,
        time_period: str = "6mo",
        data_interval: str = "1d",
        include_adjusted_close: bool = True,
        max_data_points: int = 500
) -> dict:
    """
    Fetch historical price data (OHLCV) for a stock ticker.

    This tool retrieves open, high, low, close prices and volume for a specified time
    period. Use this for analyzing price trends, calculating returns, or examining
    trading patterns. The data is returned in chronological order (oldest to newest).

    Args:
        ticker_symbol: Stock ticker symbol (e.g., 'AAPL', 'GOOGL'). Include exchange
                      suffix for non-US stocks (e.g., 'VOW3.DE').
        time_period: Time range for historical data. Valid values:
                    - Short term: '1d', '5d', '1mo', '3mo'
                    - Medium term: '6mo', '1y', '2y' (default: '6mo')
                    - Long term: '5y', '10y', 'ytd', 'max'
        data_interval: Frequency of data points. Valid values:
                      - Intraday: '1m', '5m', '15m', '30m', '1h' (only for recent periods)
                      - Daily: '1d' (default, recommended for most use cases)
                      - Weekly/Monthly: '1wk', '1mo'
        include_adjusted_close: If True, adjusts prices for stock splits and dividends
                               (recommended for accurate historical analysis).
        max_data_points: Maximum number of records to return (default: 500, max: 2000).
                        Limits token usage. Use smaller values for recent data only.

    Returns:
        List of records with date, open, high, low, close prices, and volume.
        Each record represents one data_interval period.

    Examples:
        - "Show me Apple's price over the last year" → yfinance_get_price_history("AAPL", "1y")
        - "Get Tesla's daily prices for the last 3 months" → yfinance_get_price_history("TSLA", "3mo")
        - "What's the 5-year price trend for Microsoft?" → yfinance_get_price_history("MSFT", "5y", "1wk", max_data_points=260)

    Note: For very long time periods, consider using weekly ('1wk') or monthly ('1mo')
    intervals to reduce token usage while maintaining the overall trend visibility.
    """
    _enable_cache()

    try:
        hist = yf.Ticker(ticker_symbol).history(
            period=time_period,
            interval=data_interval,
            auto_adjust=include_adjusted_close
        )

        if hist is None or hist.empty:
            return {
                "status": "ok",
                "symbol": ticker_symbol.upper(),
                "data": [],
                "count": 0,
                "message": f"No price data available for {ticker_symbol} with period={time_period}, interval={data_interval}"
            }

        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in hist.columns]
        records = _df_to_records(hist[cols])

        # Apply max limit and inform if truncated
        truncated = len(records) > max_data_points
        records = records[:max_data_points]

        result = {
            "status": "ok",
            "symbol": ticker_symbol.upper(),
            "time_period": time_period,
            "data_interval": data_interval,
            "data": records,
            "count": len(records)
        }

        if truncated:
            result["truncated"] = True
            result["message"] = (
                f"Results truncated to {max_data_points} most recent data points. "
                f"Use a shorter time_period, larger data_interval (e.g., '1wk' instead of '1d'), "
                f"or increase max_data_points parameter to retrieve more data."
            )

        return result

    except Exception as e:
        return _format_error(ticker_symbol, e)


@mcp.tool()
def yfinance_get_financial_statements(
        ticker_symbol: str,
        statement_type: str = "income",
        number_of_periods: int = 4,
        period_type: str = "annual"
) -> dict:
    """
    Get financial statement data for a company (income statement, balance sheet, or cash flow).

    This tool retrieves formal financial statements filed by public companies, showing
    line items like revenue, expenses, assets, liabilities, and cash flows across multiple
    reporting periods. Use this to analyze financial performance, trends, and health.

    Args:
        ticker_symbol: Stock ticker symbol (e.g., 'AAPL', 'TSLA').
        statement_type: Type of financial statement. Valid values:
                       - 'income' (Income Statement / P&L): Revenue, expenses, net income
                       - 'balance' (Balance Sheet): Assets, liabilities, equity
                       - 'cashflow' (Cash Flow Statement): Operating, investing, financing cash flows
        number_of_periods: Number of most recent periods to retrieve (default: 4, max: 10).
                          Each period represents one fiscal year or quarter depending on period_type.
        period_type: Either 'annual' (yearly statements, default) or 'quarterly' (Q1-Q4 reports).
                    Quarterly data provides more granular trends but uses more tokens.

    Returns:
        List of periods (most recent first) with all line items from the selected statement.
        Each period contains a date and a dictionary of financial metrics.

    Examples:
        - "Show me Apple's revenue trend" → yfinance_get_financial_statements("AAPL", "income", 4)
        - "Get Microsoft's balance sheet" → yfinance_get_financial_statements("MSFT", "balance", 2, "annual")
        - "What's Tesla's cash flow?" → yfinance_get_financial_statements("TSLA", "cashflow", 4)
        - "Show quarterly income statements for Amazon" → yfinance_get_financial_statements("AMZN", "income", 8, "quarterly")

    Note: Statements contain 20-50+ line items per period. For token efficiency, request
    only the number of periods you need. You can extract specific metrics (like Total Revenue
    or Net Income) from the returned data.
    """
    _enable_cache()

    # Validate statement_type
    statement_map = {
        "income": ("income_stmt", "quarterly_income_stmt"),
        "balance": ("balance_sheet", "quarterly_balance_sheet"),
        "cashflow": ("cashflow", "quarterly_cashflow"),
    }

    statement_lower = statement_type.lower()
    if statement_lower not in statement_map:
        return {
            "status": "error",
            "message": f"Invalid statement_type: '{statement_type}'",
            "suggestion": "Valid options are: 'income' (P&L), 'balance' (Balance Sheet), or 'cashflow' (Cash Flow Statement)"
        }

    # Validate period_type
    if period_type.lower() not in ["annual", "quarterly"]:
        return {
            "status": "error",
            "message": f"Invalid period_type: '{period_type}'",
            "suggestion": "Valid options are: 'annual' (yearly) or 'quarterly' (Q1-Q4)"
        }

    # Cap periods to prevent excessive token usage
    if number_of_periods > 10:
        number_of_periods = 10

    try:
        tkr = yf.Ticker(ticker_symbol)

        # Select the appropriate statement
        annual_attr, quarterly_attr = statement_map[statement_lower]
        is_annual = period_type.lower() == "annual"
        df = getattr(tkr, annual_attr if is_annual else quarterly_attr)

        if df is None or df.empty:
            return {
                "status": "ok",
                "symbol": ticker_symbol.upper(),
                "statement_type": statement_type,
                "period_type": period_type,
                "data": [],
                "message": f"No {period_type} {statement_type} statement data available for {ticker_symbol}"
            }

        records = _read_statement(df, number_of_periods)

        return {
            "status": "ok",
            "symbol": ticker_symbol.upper(),
            "statement_type": statement_type,
            "period_type": period_type,
            "periods_returned": len(records),
            "data": records
        }

    except Exception as e:
        return _format_error(ticker_symbol, e)


@mcp.tool()
def yfinance_compare_stocks(
        ticker_symbols: list[str],
        metrics: list[str] = None
) -> dict:
    """
    Compare key metrics across multiple stocks side-by-side.

    This is a consolidated tool that fetches and compares essential metrics for multiple
    stocks simultaneously, making it easier to evaluate investment options or analyze
    competitors. This is more efficient than calling yfinance_get_company_overview multiple
    times when you need to compare stocks.

    Args:
        ticker_symbols: List of 2-10 ticker symbols to compare (e.g., ['AAPL', 'MSFT', 'GOOGL']).
        metrics: Optional list of specific metrics to compare. If not provided, returns
                a standard set of comparison metrics. Available metrics:
                - 'market_cap_usd', 'pe_ratio_trailing', 'pe_ratio_forward'
                - 'price_to_book_ratio', 'dividend_yield_percent', 'beta'
                - 'current_price', 'fifty_two_week_high', 'fifty_two_week_low'

    Returns:
        Dictionary with each ticker as a key and its metrics as values, making it easy
        to compare companies side-by-side.

    Examples:
        - "Compare Apple, Microsoft, and Google" → yfinance_compare_stocks(['AAPL', 'MSFT', 'GOOGL'])
        - "Compare PE ratios of tech giants" → yfinance_compare_stocks(['AAPL', 'MSFT', 'GOOGL', 'META'], ['pe_ratio_trailing'])
        - "Which has higher market cap: Tesla or Ford?" → yfinance_compare_stocks(['TSLA', 'F'], ['market_cap_usd'])

    Note: This tool is optimized for comparing 2-10 stocks. For single stock lookups,
    use yfinance_get_company_overview instead.
    """
    _enable_cache()

    if not ticker_symbols or len(ticker_symbols) < 2:
        return {
            "status": "error",
            "message": "Must provide at least 2 ticker symbols to compare",
            "suggestion": "Example: ['AAPL', 'MSFT'] or ['TSLA', 'F', 'GM']"
        }

    if len(ticker_symbols) > 10:
        return {
            "status": "error",
            "message": "Maximum 10 ticker symbols allowed for comparison",
            "suggestion": f"You provided {len(ticker_symbols)} symbols. Please reduce to 10 or fewer."
        }

    # Default comparison metrics
    default_metrics = [
        'company_name', 'sector', 'market_cap_usd', 'current_price',
        'pe_ratio_trailing', 'dividend_yield_percent'
    ]

    selected_metrics = metrics if metrics else default_metrics

    comparison = {}
    errors = []

    for symbol in ticker_symbols:
        try:
            tkr = yf.Ticker(symbol)
            full_info = _safe_info(tkr, ResponseFormat.DETAILED)

            # Extract only requested metrics
            comparison[symbol.upper()] = {
                metric: full_info.get(metric)
                for metric in selected_metrics
                if metric in full_info
            }
        except Exception as e:
            errors.append({"symbol": symbol, "error": str(e)})

    result = {
        "status": "ok",
        "comparison": comparison,
        "metrics_compared": selected_metrics
    }

    if errors:
        result["errors"] = errors
        result["message"] = f"Successfully compared {len(comparison)} of {len(ticker_symbols)} stocks"

    return result


# -----------------------------------------------------------------------------
# Server entry
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("[YahooFinance] Starting MCP server on 0.0.0.0:8083 (streamable-http).")
    print("Tools:")
    print("  - yfinance_get_company_overview: Get company info and key metrics")
    print("  - yfinance_get_price_history: Fetch historical OHLCV price data")
    print("  - yfinance_get_financial_statements: Get income/balance/cashflow statements")
    print("  - yfinance_compare_stocks: Compare metrics across multiple stocks")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8083)
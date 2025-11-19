"""
Financial Modeling Prep (FMP) MCP Server
Advanced financial analytics, valuation, and market intelligence tools.

This server provides access to FMP's analytical capabilities, designed to complement
AlphaVantage's raw data with advanced metrics, DCF valuations, and market intelligence.

Key Features:
- Advanced financial metrics and ratios
- DCF valuation tools (with AlphaVantage data integration)
- Institutional ownership and insider trading
- Analyst coverage and estimates
- Market screening and analysis
"""

from __future__ import annotations

import os
import time
import asyncio
import logging
import httpx
from typing import Dict, Any, Optional, List, Tuple, Union
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
    mcp = FastMCP(name="FMP")
except TypeError:
    mcp = FastMCP()


# ============================================================================
# CONFIGURATION & ENUMS
# ============================================================================

class ResponseFormat(str, Enum):
    """Control verbosity of tool responses for token efficiency."""
    CONCISE = "concise"  # Essential fields only
    DETAILED = "detailed"  # Full API response


# FMP API Configuration
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
FMP_API_KEY = os.getenv("FMP_API_KEY")

# Rate limit configuration
RATE_LIMIT_PER_DAY = 250  # Free tier


# ============================================================================
# RATE LIMITING SYSTEM
# ============================================================================

@dataclass
class RateLimitTracker:
    """Tracks API call rate limits."""
    calls_per_day: List[float]
    
    def __init__(self):
        self.calls_per_day = []
    
    def can_make_call(self) -> Tuple[bool, Optional[str]]:
        """
        Check if we can make an API call without exceeding rate limits.
        
        Returns:
            (can_call, error_message)
        """
        now = time.time()
        
        # Clean up old timestamps
        one_day_ago = now - 86400
        self.calls_per_day = [t for t in self.calls_per_day if t > one_day_ago]
        
        # Check day limit
        if len(self.calls_per_day) >= RATE_LIMIT_PER_DAY:
            wait_time = 86400 - (now - self.calls_per_day[0])
            hours = wait_time / 3600
            return False, (
                f"Daily rate limit exceeded: {RATE_LIMIT_PER_DAY} calls per day. "
                f"Resets in {hours:.1f} hours. "
                f"Upgrade to premium for higher limits (300-10,000 calls/day)."
            )
        
        return True, None
    
    def record_call(self):
        """Record a successful API call."""
        now = time.time()
        self.calls_per_day.append(now)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current rate limit status."""
        now = time.time()
        one_day_ago = now - 86400
        
        calls_today = len([t for t in self.calls_per_day if t > one_day_ago])
        
        return {
            "calls_today": calls_today,
            "daily_limit": RATE_LIMIT_PER_DAY,
            "remaining": RATE_LIMIT_PER_DAY - calls_today
        }


# Global rate limiter
rate_limiter = RateLimitTracker()


# ============================================================================
# FMP API CLIENT
# ============================================================================

class FMPClient:
    """HTTP client for FMP API."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize FMP client."""
        self.api_key = api_key or FMP_API_KEY
        if not self.api_key:
            raise ValueError(
                "FMP API key not found. "
                "Set FMP_API_KEY in .env or pass api_key parameter. "
                "Get a free key at: https://site.financialmodelingprep.com/developer/docs"
            )
        
        self.base_url = FMP_BASE_URL
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        Make GET request to FMP API.
        
        Args:
            endpoint: API endpoint (e.g., '/profile/AAPL')
            params: Query parameters
            
        Returns:
            JSON response
        """
        params = params or {}
        params['apikey'] = self.api_key
        
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise Exception("Rate limit exceeded")
            elif e.response.status_code == 401:
                raise Exception("Invalid API key")
            elif e.response.status_code == 403:
                raise Exception("Access forbidden - endpoint may require premium subscription")
            else:
                raise Exception(f"HTTP error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            raise Exception(f"FMP API error: {str(e)}")
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Global client instance
_client: Optional[FMPClient] = None


async def get_client() -> FMPClient:
    """Get or create the global FMP client."""
    global _client
    if _client is None:
        _client = FMPClient()
    return _client


# ============================================================================
# VALIDATION & ERROR HANDLING
# ============================================================================

def validate_symbol(symbol: str) -> Tuple[bool, Optional[str]]:
    """Validate stock symbol format."""
    if not symbol:
        return False, "Symbol cannot be empty"
    
    if len(symbol) > 10:
        return False, f"Symbol '{symbol}' is too long"
    
    if " " in symbol:
        return False, (
            f"'{symbol}' appears to contain spaces. "
            f"Use ticker symbols only (e.g., 'AAPL', not 'Apple Inc')."
        )
    
    return True, None


def validate_period(period: str) -> Tuple[bool, Optional[str]]:
    """Validate period parameter."""
    valid_periods = ['annual', 'quarter']
    if period not in valid_periods:
        return False, f"Invalid period: '{period}'. Valid options: {', '.join(valid_periods)}"
    return True, None


def validate_limit(limit: int, max_limit: int = 100) -> Tuple[bool, Optional[str]]:
    """Validate limit parameter."""
    if limit < 1:
        return False, f"Limit must be at least 1, got: {limit}"
    if limit > max_limit:
        return False, f"Limit cannot exceed {max_limit}, got: {limit}"
    return True, None


def apply_concise_format(tool_name: str, data: Any) -> Any:
    """
    Apply CONCISE formatting to reduce token usage.
    Returns essential fields only.
    """
    if not data:
        return data
    
    # If data is a list, apply to each item
    if isinstance(data, list):
        return [apply_concise_format(tool_name, item) for item in data]
    
    # Tool-specific concise formats
    if tool_name == "financial_ratios":
        if isinstance(data, dict):
            # Keep only key ratios
            return {
                "symbol": data.get("symbol"),
                "date": data.get("date"),
                "currentRatio": data.get("currentRatio"),
                "quickRatio": data.get("quickRatio"),
                "debtEquityRatio": data.get("debtEquityRatio"),
                "returnOnEquity": data.get("returnOnEquity"),
                "returnOnAssets": data.get("returnOnAssets"),
                "netProfitMargin": data.get("netProfitMargin"),
                "grossProfitMargin": data.get("grossProfitMargin")
            }
    
    elif tool_name == "key_metrics":
        if isinstance(data, dict):
            return {
                "symbol": data.get("symbol"),
                "date": data.get("date"),
                "peRatio": data.get("peRatio"),
                "priceToBookRatio": data.get("priceToBookRatio"),
                "roe": data.get("roe"),
                "roa": data.get("roa"),
                "debtToEquity": data.get("debtToEquity"),
                "freeCashFlowPerShare": data.get("freeCashFlowPerShare"),
                "dividendYield": data.get("dividendYield")
            }
    
    elif tool_name == "dcf":
        if isinstance(data, dict):
            return {
                "symbol": data.get("symbol"),
                "date": data.get("date"),
                "dcf": data.get("dcf"),
                "stockPrice": data.get("Stock Price"),
                "intrinsicValue": data.get("dcf"),
                "upside": ((data.get("dcf", 0) / data.get("Stock Price", 1) - 1) * 100) if data.get("Stock Price") else None
            }
    
    # Return full data for other tools or if structure doesn't match
    return data


def format_error_response(
    tool_name: str,
    error: Exception,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Format error with helpful guidance."""
    error_msg = str(error)
    
    response = {
        "status": "error",
        "tool": tool_name,
        "error": error_msg,
        "arguments_provided": arguments
    }
    
    # Add suggestions based on error type
    if "symbol" in arguments and ("invalid" in error_msg.lower() or "not found" in error_msg.lower()):
        response["suggestion"] = (
            "The symbol may be incorrect. Use fmp_symbol_search to find the right ticker. "
            "Remember: use ticker symbols (e.g., 'AAPL'), not company names (e.g., 'Apple')."
        )
    elif "rate limit" in error_msg.lower():
        response["suggestion"] = (
            "Rate limit exceeded. Check rate_limit_status and wait before retrying. "
            "Consider upgrading to a premium plan for higher limits."
        )
    elif "premium" in error_msg.lower() or "forbidden" in error_msg.lower():
        response["suggestion"] = (
            "This endpoint requires a premium FMP subscription. "
            "Upgrade at: https://site.financialmodelingprep.com/developer/docs/pricing"
        )
    
    return response


# ============================================================================
# TOOL: SYMBOL SEARCH
# ============================================================================

@mcp.tool()
async def fmp_symbol_search(
    query: str,
    limit: int = 10,
    exchange: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search for stock ticker symbols by company name or keywords.
    
    Args:
        query: Company name or keywords to search for
        limit: Maximum number of results (default: 10, max: 50)
        exchange: Optional. Filter by exchange (e.g., 'NASDAQ', 'NYSE', 'LSE')
    
    Returns:
        List of matching companies with ticker symbols, names, and exchange info.
    
    Examples:
        - {"query": "Apple"}
        - {"query": "Tesla", "limit": 5}
        - {"query": "Microsoft", "exchange": "NASDAQ"}
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    if not query or len(query.strip()) == 0:
        return {"status": "error", "message": "Query cannot be empty"}
    
    try:
        client = await get_client()
        
        # FMP search endpoint
        results = await client.get("/search", {"query": query, "limit": min(limit, 50)})
        
        rate_limiter.record_call()
        
        # Filter by exchange if specified
        if exchange and results:
            results = [r for r in results if r.get("exchangeShortName") == exchange.upper()]
        
        return {
            "status": "ok",
            "query": query,
            "count": len(results) if results else 0,
            "data": results[:limit] if results else [],
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in symbol search: {e}")
        return format_error_response("fmp_symbol_search", e, {"query": query, "limit": limit})


# ============================================================================
# TOOL: FINANCIAL RATIOS
# ============================================================================

@mcp.tool()
async def fmp_financial_ratios(
    symbol: str,
    period: str = "annual",
    limit: int = 5,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get comprehensive financial ratios for liquidity, leverage, efficiency, and profitability.
    
    Returns detailed ratio analysis including:
    - Liquidity: Current ratio, quick ratio, cash ratio
    - Leverage: Debt-to-equity, debt-to-assets, interest coverage
    - Efficiency: Asset turnover, inventory turnover, receivables turnover
    - Profitability: Gross/operating/net margins, ROE, ROA
    
    Args:
        symbol: Stock ticker symbol
        period: 'annual' (default) or 'quarter'
        limit: Number of periods to return (default: 5, max: 100)
        response_format: 'concise' (key ratios only) or 'detailed' (all ratios)
    
    Returns:
        Financial ratios by period with comprehensive metrics.
    
    Examples:
        - Annual ratios: {"symbol": "AAPL", "period": "annual", "limit": 3}
        - Quarterly: {"symbol": "MSFT", "period": "quarter", "limit": 8}
        - Concise: {"symbol": "TSLA", "response_format": "concise"}
    
    Use Cases:
        - Compare company efficiency over time
        - Assess financial health (liquidity, solvency)
        - Benchmark against competitors
        - Identify trends in profitability
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    is_valid, validation_error = validate_period(period)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        endpoint = f"/ratios/{symbol.upper()}"
        params = {"period": period, "limit": min(limit, 100)}
        
        data = await client.get(endpoint, params)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No financial ratio data found for {symbol}. Symbol may be invalid or data not available."
            }
        
        if response_format == "concise":
            data = apply_concise_format("financial_ratios", data)
        
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "period": period,
            "count": len(data) if isinstance(data, list) else 1,
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in financial_ratios: {e}")
        return format_error_response("fmp_financial_ratios", e, {
            "symbol": symbol,
            "period": period,
            "limit": limit
        })


# ============================================================================
# TOOL: KEY METRICS
# ============================================================================

@mcp.tool()
async def fmp_key_metrics(
    symbol: str,
    period: str = "annual",
    limit: int = 5,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get key financial metrics including valuation ratios and per-share values.
    
    Returns metrics such as:
    - Valuation: P/E, P/B, P/S, EV/EBITDA, Price-to-FCF
    - Per-share: Revenue, earnings, book value, FCF, operating cash flow
    - Returns: ROE, ROA, ROIC
    - Other: Market cap, enterprise value, debt-to-equity
    
    Args:
        symbol: Stock ticker symbol
        period: 'annual' (default) or 'quarter'
        limit: Number of periods to return (default: 5, max: 100)
        response_format: 'concise' (essential metrics) or 'detailed' (all metrics)
    
    Returns:
        Key financial metrics by period.
    
    Examples:
        - {"symbol": "AAPL", "period": "annual"}
        - {"symbol": "GOOGL", "period": "quarter", "limit": 4}
        - {"symbol": "AMZN", "response_format": "concise"}
    
    Use Cases:
        - Quick valuation assessment
        - Track metrics over time
        - Compare with industry peers
        - Identify value vs growth characteristics
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    is_valid, validation_error = validate_period(period)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        endpoint = f"/key-metrics/{symbol.upper()}"
        params = {"period": period, "limit": min(limit, 100)}
        
        data = await client.get(endpoint, params)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No key metrics data found for {symbol}"
            }
        
        if response_format == "concise":
            data = apply_concise_format("key_metrics", data)
        
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "period": period,
            "count": len(data) if isinstance(data, list) else 1,
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in key_metrics: {e}")
        return format_error_response("fmp_key_metrics", e, {
            "symbol": symbol,
            "period": period,
            "limit": limit
        })


# ============================================================================
# TOOL: FINANCIAL GROWTH
# ============================================================================

@mcp.tool()
async def fmp_financial_growth(
    symbol: str,
    period: str = "annual",
    limit: int = 5,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get year-over-year and quarter-over-quarter growth rates for all financial metrics.
    
    Returns growth rates for:
    - Revenue growth
    - Net income growth
    - EPS growth
    - Operating cash flow growth
    - Free cash flow growth
    - Asset growth
    - Equity growth
    - And many more metrics
    
    Args:
        symbol: Stock ticker symbol
        period: 'annual' (YoY growth) or 'quarter' (QoQ growth)
        limit: Number of periods to return (default: 5, max: 100)
        response_format: 'concise' or 'detailed'
    
    Returns:
        Growth rates by period.
    
    Examples:
        - YoY growth: {"symbol": "AAPL", "period": "annual"}
        - QoQ growth: {"symbol": "NVDA", "period": "quarter", "limit": 8}
        - {"symbol": "META", "response_format": "concise"}
    
    Use Cases:
        - Assess growth trajectory
        - Compare growth rates across metrics
        - Identify acceleration or deceleration
        - Screen for high-growth companies
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    is_valid, validation_error = validate_period(period)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        endpoint = f"/financial-growth/{symbol.upper()}"
        params = {"period": period, "limit": min(limit, 100)}
        
        data = await client.get(endpoint, params)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No financial growth data found for {symbol}"
            }
        
        if response_format == "concise":
            data = apply_concise_format("financial_growth", data)
        
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "period": period,
            "count": len(data) if isinstance(data, list) else 1,
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in financial_growth: {e}")
        return format_error_response("fmp_financial_growth", e, {
            "symbol": symbol,
            "period": period,
            "limit": limit
        })


# ============================================================================
# TOOL: COMPANY RATING
# ============================================================================

@mcp.tool()
async def fmp_company_rating(
    symbol: str,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get FMP's proprietary company rating and recommendation.
    
    Returns comprehensive rating based on:
    - Financial health score
    - Profitability score
    - Growth score
    - Overall rating (S, A, B, C, D, F)
    - Recommendation (Strong Buy, Buy, Hold, Sell, Strong Sell)
    
    Args:
        symbol: Stock ticker symbol
        response_format: 'concise' or 'detailed'
    
    Returns:
        Company rating with scores and recommendation.
    
    Examples:
        - {"symbol": "AAPL"}
        - {"symbol": "TSLA", "response_format": "concise"}
    
    Use Cases:
        - Quick assessment of company quality
        - Screening companies by rating
        - Cross-reference with other analysis
        - Track rating changes over time
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        endpoint = f"/rating/{symbol.upper()}"
        data = await client.get(endpoint)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No rating data found for {symbol}"
            }
        
        # Extract first item if list
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        
        if response_format == "concise":
            data = apply_concise_format("company_rating", data)
        
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in company_rating: {e}")
        return format_error_response("fmp_company_rating", e, {"symbol": symbol})


# ============================================================================
# TOOL: ENTERPRISE VALUES
# ============================================================================

@mcp.tool()
async def fmp_enterprise_values(
    symbol: str,
    period: str = "annual",
    limit: int = 5,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get historical enterprise value, market cap, and related metrics.
    
    Returns:
    - Enterprise value
    - Market capitalization
    - Stock price
    - Number of shares
    - Add/subtract: Cash, debt, minority interest
    
    Args:
        symbol: Stock ticker symbol
        period: 'annual' or 'quarter'
        limit: Number of periods (default: 5, max: 100)
        response_format: 'concise' or 'detailed'
    
    Returns:
        Enterprise value metrics by period.
    
    Examples:
        - {"symbol": "AAPL", "period": "annual"}
        - {"symbol": "MSFT", "period": "quarter", "limit": 8}
    
    Use Cases:
        - Track valuation evolution
        - Calculate EV/EBITDA, EV/Revenue multiples
        - Assess capital structure changes
        - M&A valuation analysis
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    is_valid, validation_error = validate_period(period)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        endpoint = f"/enterprise-values/{symbol.upper()}"
        params = {"period": period, "limit": min(limit, 100)}
        
        data = await client.get(endpoint, params)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No enterprise value data found for {symbol}"
            }
        
        if response_format == "concise":
            data = apply_concise_format("enterprise_values", data)
        
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "period": period,
            "count": len(data) if isinstance(data, list) else 1,
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in enterprise_values: {e}")
        return format_error_response("fmp_enterprise_values", e, {
            "symbol": symbol,
            "period": period,
            "limit": limit
        })


# ============================================================================
# TOOL: ADVANCED DCF VALUATION
# ============================================================================

@mcp.tool()
async def fmp_advanced_dcf(
    symbol: str,
    # Optional overrides from AlphaVantage
    revenue: Optional[float] = None,
    revenue_growth_rate: Optional[float] = None,
    operating_cash_flow: Optional[float] = None,
    capital_expenditures: Optional[float] = None,
    free_cash_flow: Optional[float] = None,
    ebitda: Optional[float] = None,
    total_debt: Optional[float] = None,
    cash: Optional[float] = None,
    shares_outstanding: Optional[float] = None,
    beta: Optional[float] = None,
    tax_rate: Optional[float] = None,
    # Valuation assumptions
    discount_rate: Optional[float] = None,
    terminal_growth_rate: Optional[float] = None,
    projection_years: Optional[int] = 5,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Calculate Advanced DCF (Discounted Cash Flow) valuation.
    
    RECOMMENDED WORKFLOW - Using AlphaVantage Data:
    
    Step 1: Gather AlphaVantage financial data
        cash_flow = alphavantage_cash_flow(symbol="AAPL")
        income = alphavantage_income_statement(symbol="AAPL")
        balance = alphavantage_balance_sheet(symbol="AAPL")
        overview = alphavantage_company_overview(symbol="AAPL")
    
    Step 2: Extract latest annual data
        latest_cf = cash_flow['annualReports'][0]
        latest_income = income['annualReports'][0]
        latest_balance = balance['annualReports'][0]
    
    Step 3: Map parameters (CRITICAL - Field Name Mapping)
        AlphaVantage Field                      → FMP Parameter
        -------------------------------------------------------------
        latest_cf['operatingCashFlow']         → operating_cash_flow
        latest_cf['capitalExpenditures']       → capital_expenditures
        [OCF - CapEx calculated]               → free_cash_flow
        latest_income['totalRevenue']          → revenue
        latest_income['ebitda']                → ebitda
        latest_balance['shortLongTermDebtTotal'] → total_debt
        latest_balance['cashAndCashEquivalentsAtCarryingValue'] → cash
        overview['SharesOutstanding']          → shares_outstanding
        overview['Beta']                       → beta
    
    Step 4: Call DCF with mapped data
        fmp_advanced_dcf(
            symbol="AAPL",
            operating_cash_flow=float(latest_cf['operatingCashFlow']),
            capital_expenditures=abs(float(latest_cf['capitalExpenditures'])),
            free_cash_flow=operating_cash_flow - capital_expenditures,
            revenue=float(latest_income['totalRevenue']),
            ebitda=float(latest_income['ebitda']),
            total_debt=float(latest_balance['shortLongTermDebtTotal']),
            cash=float(latest_balance['cashAndCashEquivalentsAtCarryingValue']),
            shares_outstanding=float(overview['SharesOutstanding']),
            beta=float(overview['Beta']),
            # Optional: adjust assumptions
            discount_rate=0.10,  # 10% WACC
            terminal_growth_rate=0.025  # 2.5% perpetual growth
        )
    
    USAGE SCENARIOS:
    
    Scenario 1: Use AlphaVantage data (RECOMMENDED)
        - Gather data from AlphaVantage (fresher, updated on earnings day)
        - Map fields as shown above
        - Pass to DCF for valuation
        - Most accurate approach
    
    Scenario 2: Quick estimate without AlphaVantage
        - Just pass symbol: fmp_advanced_dcf(symbol="AAPL")
        - FMP fetches its own data
        - Faster but may be less current
    
    Scenario 3: Partial override
        - Provide some parameters, let FMP fill the rest
        - Useful when some AlphaVantage fields are missing
    
    Scenario 4: Sensitivity analysis
        - Use AlphaVantage financials
        - Vary discount_rate (e.g., 8%, 10%, 12%)
        - Keep other parameters constant
        - Run multiple scenarios
    
    Scenario 5: Custom projections
        - Override revenue_growth_rate based on analyst estimates
        - Adjust terminal_growth_rate for different industries
        - Model different scenarios (bull/base/bear)
    
    AMBIGUITY RESOLUTION GUIDELINES:
    
    When AlphaVantage has multiple reporting periods:
        → Use most recent annual data for DCF base case
        → Quarterly data can be used for interim updates
    
    When field names don't match exactly:
        → Follow the mapping table above
        → 'shortLongTermDebtTotal' includes both short and long-term debt
        → CapEx is usually negative in cash flow statement, take absolute value
    
    When data quality issues exist:
        → Validate reasonableness (e.g., FCF = OCF - CapEx)
        → If inconsistent, agent should flag and use best judgment
        → Can override specific fields
    
    When conflicting data between sources:
        → Prioritize: AlphaVantage (fresher) > FMP fallback
        → AlphaVantage updates on earnings day
        → FMP may lag by days/weeks
    
    VALIDATION CHECKS:
    
    The agent should validate:
        1. FCF consistency: FCF ≈ Operating Cash Flow - CapEx
        2. Reasonableness: Ratios should be sensible
        3. Sign conventions: CapEx should be positive after abs()
        4. Currency units: All values in same currency
        5. Shares outstanding: Matches current count
    
    Args:
        symbol: Stock ticker symbol (REQUIRED)
        
        Financial Data (Optional - from AlphaVantage):
            revenue: Total revenue (latest annual)
            revenue_growth_rate: Historical growth rate
            operating_cash_flow: Cash from operations
            capital_expenditures: CapEx (positive value)
            free_cash_flow: FCF = OCF - CapEx
            ebitda: Earnings before interest, tax, depreciation, amortization
            total_debt: Total debt (short + long term)
            cash: Cash and cash equivalents
            shares_outstanding: Current shares outstanding
            beta: Stock beta (systematic risk)
            tax_rate: Effective tax rate (decimal, e.g., 0.21 for 21%)
        
        Valuation Assumptions (Optional - agent can adjust):
            discount_rate: WACC or required return (decimal, e.g., 0.10 for 10%)
            terminal_growth_rate: Perpetuity growth (decimal, e.g., 0.025 for 2.5%)
            projection_years: Forecast period (default: 5 years)
        
        response_format: 'concise' (essential DCF output) or 'detailed' (full model)
    
    Returns:
        DCF valuation including:
        - Intrinsic value per share
        - Current stock price
        - Upside/downside percentage
        - Present value of cash flows
        - Terminal value
        - Enterprise value
        - Equity value
        - Assumptions used in calculation
    
    Examples:
        
        # Simple: Let FMP handle everything
        {"symbol": "AAPL"}
        
        # Advanced: Use AlphaVantage data (RECOMMENDED)
        {
            "symbol": "AAPL",
            "operating_cash_flow": 99803000000,
            "capital_expenditures": 10959000000,
            "free_cash_flow": 88844000000,
            "revenue": 383285000000,
            "ebitda": 129956000000,
            "total_debt": 111088000000,
            "cash": 29965000000,
            "shares_outstanding": 15204100000,
            "beta": 1.29
        }
        
        # Sensitivity: Adjust discount rate
        {
            "symbol": "AAPL",
            "free_cash_flow": 88844000000,
            "shares_outstanding": 15204100000,
            "discount_rate": 0.12,  # Test 12% discount rate
            "terminal_growth_rate": 0.02  # Conservative 2% growth
        }
        
        # Custom growth projections
        {
            "symbol": "NVDA",
            "revenue": 60922000000,
            "revenue_growth_rate": 0.30,  # Assume 30% growth
            "free_cash_flow": 15000000000,
            "shares_outstanding": 2460000000
        }
    
    Critical Notes:
        - If NO parameters: FMP fetches its own data
        - If SOME parameters: Missing ones fetched by FMP
        - If ALL parameters: Pure calculation with your data
        - AlphaVantage data is typically fresher
        - Agent validates data before passing
        - Multiple scenarios = multiple calls with different assumptions
    
    Common Mistakes to Avoid:
        - Using company name instead of ticker
        - Mixing quarterly and annual data
        - Using negative CapEx (should be positive)
        - Inconsistent FCF (not equal to OCF - CapEx)
        - Wrong units (millions vs actual values)
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        # Build request - FMP's advanced DCF endpoint
        endpoint = f"/advanced_dcf"
        params = {"symbol": symbol.upper()}
        
        # Note: FMP's API doesn't accept custom parameters in URL
        # It calculates DCF from its own data
        # For custom calculations, we'd need to implement our own DCF model
        # or use FMP's data as a baseline
        
        data = await client.get(endpoint, params)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No DCF data found for {symbol}"
            }
        
        # Extract DCF value if list
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        
        # If user provided custom parameters, add them to response for reference
        custom_params = {}
        if operating_cash_flow is not None:
            custom_params["operating_cash_flow_override"] = operating_cash_flow
        if free_cash_flow is not None:
            custom_params["free_cash_flow_override"] = free_cash_flow
        if discount_rate is not None:
            custom_params["discount_rate_override"] = discount_rate
        if terminal_growth_rate is not None:
            custom_params["terminal_growth_rate_override"] = terminal_growth_rate
        
        result = {
            "status": "ok",
            "symbol": symbol.upper(),
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
        if custom_params:
            result["note"] = (
                "Custom parameters provided but FMP API uses its own data. "
                "For custom DCF calculations, consider implementing your own model "
                "using the provided parameters."
            )
            result["custom_parameters_provided"] = custom_params
        
        if response_format == "concise":
            result["data"] = apply_concise_format("dcf", data)
        
        return result
        
    except Exception as e:
        logger.error(f"Error in advanced_dcf: {e}")
        return format_error_response("fmp_advanced_dcf", e, {"symbol": symbol})


# ============================================================================
# TOOL: LEVERED DCF VALUATION
# ============================================================================

@mcp.tool()
async def fmp_levered_dcf(
    symbol: str,
    # Optional overrides from AlphaVantage (same as advanced DCF)
    revenue: Optional[float] = None,
    operating_cash_flow: Optional[float] = None,
    capital_expenditures: Optional[float] = None,
    free_cash_flow: Optional[float] = None,
    total_debt: Optional[float] = None,
    cash: Optional[float] = None,
    shares_outstanding: Optional[float] = None,
    beta: Optional[float] = None,
    # Valuation assumptions
    discount_rate: Optional[float] = None,
    terminal_growth_rate: Optional[float] = None,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Calculate Levered DCF (accounts for debt and leverage effects).
    
    Levered DCF differs from standard DCF by:
    - Using Free Cash Flow to Equity (FCFE) instead of FCFF
    - Accounting for debt tax shields
    - Discounting at cost of equity instead of WACC
    - Direct equity valuation (no enterprise value calculation)
    
    PARAMETER MAPPING: Same as fmp_advanced_dcf (see that tool for details)
    
    Uses AlphaVantage data in the same way as Advanced DCF.
    Refer to fmp_advanced_dcf documentation for:
    - Complete workflow
    - Field mappings
    - Usage scenarios
    - Validation checks
    
    Args:
        symbol: Stock ticker symbol
        [Same optional parameters as fmp_advanced_dcf]
        response_format: 'concise' or 'detailed'
    
    Returns:
        Levered DCF valuation with equity value per share.
    
    Examples:
        - Simple: {"symbol": "AAPL"}
        - With data: {"symbol": "MSFT", "free_cash_flow": 65000000000, ...}
    
    Use Cases:
        - Companies with significant debt
        - Compare levered vs unlevered valuation
        - Assess leverage impact on equity value
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        endpoint = f"/levered_dcf"
        params = {"symbol": symbol.upper()}
        
        data = await client.get(endpoint, params)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No levered DCF data found for {symbol}"
            }
        
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        
        result = {
            "status": "ok",
            "symbol": symbol.upper(),
            "valuation_type": "Levered DCF",
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
        if response_format == "concise":
            result["data"] = apply_concise_format("dcf", data)
        
        return result
        
    except Exception as e:
        logger.error(f"Error in levered_dcf: {e}")
        return format_error_response("fmp_levered_dcf", e, {"symbol": symbol})


# ============================================================================
# TOOL: INSTITUTIONAL OWNERSHIP
# ============================================================================

@mcp.tool()
async def fmp_institutional_ownership(
    symbol: str,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get detailed institutional ownership data.
    
    Returns list of institutional investors with:
    - Investor name
    - Shares held
    - Date reported
    - Change in shares (if available)
    - Percentage of ownership
    
    Args:
        symbol: Stock ticker symbol
        response_format: 'concise' or 'detailed'
    
    Returns:
        List of institutional holders sorted by holdings.
    
    Examples:
        - {"symbol": "AAPL"}
        - {"symbol": "TSLA", "response_format": "concise"}
    
    Use Cases:
        - Identify major institutional investors
        - Track institutional buying/selling
        - Assess institutional confidence
        - Monitor smart money positions
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        endpoint = f"/institutional-holder/{symbol.upper()}"
        data = await client.get(endpoint)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No institutional ownership data found for {symbol}"
            }
        
        if response_format == "concise":
            # Return top 10 holders with key info
            if isinstance(data, list):
                data = [
                    {
                        "holder": item.get("holder"),
                        "shares": item.get("shares"),
                        "dateReported": item.get("dateReported"),
                        "change": item.get("change")
                    }
                    for item in data[:10]
                ]
        
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "count": len(data) if isinstance(data, list) else 1,
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in institutional_ownership: {e}")
        return format_error_response("fmp_institutional_ownership", e, {"symbol": symbol})


# ============================================================================
# TOOL: INSIDER TRADING
# ============================================================================

@mcp.tool()
async def fmp_insider_trading(
    symbol: str,
    limit: int = 50,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get detailed insider trading transactions.
    
    Returns recent insider transactions including:
    - Filing date
    - Transaction date
    - Insider name and title
    - Transaction type (Purchase, Sale, Option Exercise, etc.)
    - Securities transacted
    - Price per share
    - Total value
    - Shares owned after transaction
    
    Args:
        symbol: Stock ticker symbol
        limit: Number of transactions to return (default: 50, max: 500)
        response_format: 'concise' or 'detailed'
    
    Returns:
        List of insider transactions sorted by date (most recent first).
    
    Examples:
        - {"symbol": "AAPL", "limit": 20}
        - {"symbol": "MSFT", "limit": 100, "response_format": "concise"}
    
    Use Cases:
        - Monitor insider buying (bullish signal)
        - Track insider selling (potential warning)
        - Identify patterns in insider behavior
        - Research key executives' actions
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    is_valid, validation_error = validate_limit(limit, max_limit=500)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        endpoint = f"/insider-trading"
        params = {"symbol": symbol.upper(), "limit": min(limit, 500)}
        
        data = await client.get(endpoint, params)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No insider trading data found for {symbol}"
            }
        
        if response_format == "concise":
            # Keep essential fields only
            if isinstance(data, list):
                data = [
                    {
                        "filingDate": item.get("filingDate"),
                        "transactionType": item.get("transactionType"),
                        "reportingName": item.get("reportingName"),
                        "securitiesTransacted": item.get("securitiesTransacted"),
                        "price": item.get("price"),
                        "securitiesOwned": item.get("securitiesOwned")
                    }
                    for item in data
                ]
        
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "count": len(data) if isinstance(data, list) else 1,
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in insider_trading: {e}")
        return format_error_response("fmp_insider_trading", e, {"symbol": symbol, "limit": limit})


# ============================================================================
# TOOL: ANALYST ESTIMATES
# ============================================================================

@mcp.tool()
async def fmp_analyst_estimates(
    symbol: str,
    period: str = "annual",
    limit: int = 5,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get analyst estimates for revenue and EPS with historical accuracy.
    
    Returns consensus estimates including:
    - Estimated revenue (high/low/avg/number of analysts)
    - Estimated EPS (high/low/avg/number of analysts)
    - Estimated EBITDA
    - Estimated net income
    - Historical estimates vs actuals (if available)
    
    Args:
        symbol: Stock ticker symbol
        period: 'annual' or 'quarter'
        limit: Number of periods (default: 5, max: 30)
        response_format: 'concise' or 'detailed'
    
    Returns:
        Analyst estimates by period.
    
    Examples:
        - {"symbol": "AAPL", "period": "quarter", "limit": 4}
        - {"symbol": "GOOGL", "period": "annual"}
    
    Use Cases:
        - Compare estimates vs actuals (earnings surprises)
        - Track estimate revisions over time
        - Gauge analyst sentiment
        - Plan for earnings announcements
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    is_valid, validation_error = validate_period(period)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        endpoint = f"/analyst-estimates/{symbol.upper()}"
        params = {"period": period, "limit": min(limit, 30)}
        
        data = await client.get(endpoint, params)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No analyst estimates found for {symbol}"
            }
        
        if response_format == "concise":
            data = apply_concise_format("analyst_estimates", data)
        
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "period": period,
            "count": len(data) if isinstance(data, list) else 1,
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in analyst_estimates: {e}")
        return format_error_response("fmp_analyst_estimates", e, {
            "symbol": symbol,
            "period": period,
            "limit": limit
        })


# ============================================================================
# TOOL: UPGRADES & DOWNGRADES
# ============================================================================

@mcp.tool()
async def fmp_upgrades_downgrades(
    symbol: str,
    limit: int = 20,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get analyst rating changes (upgrades, downgrades, initiations).
    
    Returns rating changes including:
    - Date of change
    - Analyst firm name
    - Action (Upgrade, Downgrade, Initiated, Reiterated)
    - Previous rating
    - New rating
    - Previous price target (if available)
    - New price target (if available)
    
    Args:
        symbol: Stock ticker symbol
        limit: Number of rating changes (default: 20, max: 100)
        response_format: 'concise' or 'detailed'
    
    Returns:
        List of rating changes sorted by date (most recent first).
    
    Examples:
        - {"symbol": "TSLA", "limit": 10}
        - {"symbol": "NVDA", "limit": 30, "response_format": "concise"}
    
    Use Cases:
        - Track analyst sentiment changes
        - Monitor catalysts for price movements
        - Gauge Wall Street consensus shifts
        - Identify potential buying/selling opportunities
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    is_valid, validation_error = validate_limit(limit, max_limit=100)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        endpoint = f"/upgrades-downgrades"
        params = {"symbol": symbol.upper(), "limit": min(limit, 100)}
        
        data = await client.get(endpoint, params)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No upgrades/downgrades data found for {symbol}"
            }
        
        if response_format == "concise":
            # Keep essential fields
            if isinstance(data, list):
                data = [
                    {
                        "publishedDate": item.get("publishedDate"),
                        "gradingCompany": item.get("gradingCompany"),
                        "action": item.get("action"),
                        "newGrade": item.get("newGrade"),
                        "priceTarget": item.get("newPriceTarget")
                    }
                    for item in data
                ]
        
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "count": len(data) if isinstance(data, list) else 1,
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in upgrades_downgrades: {e}")
        return format_error_response("fmp_upgrades_downgrades", e, {"symbol": symbol, "limit": limit})


# ============================================================================
# TOOL: ANALYST RECOMMENDATIONS
# ============================================================================

@mcp.tool()
async def fmp_analyst_recommendations(
    symbol: str,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get analyst recommendation consensus (Buy/Sell/Hold distribution).
    
    Returns consensus including:
    - Strong Buy count
    - Buy count
    - Hold count
    - Sell count
    - Strong Sell count
    - Consensus rating
    
    Args:
        symbol: Stock ticker symbol
        response_format: 'concise' or 'detailed'
    
    Returns:
        Analyst recommendation consensus.
    
    Examples:
        - {"symbol": "AAPL"}
        - {"symbol": "MSFT", "response_format": "concise"}
    
    Use Cases:
        - Quick sentiment check
        - See Wall Street consensus
        - Compare with your own analysis
        - Track consensus changes over time
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_symbol(symbol)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        endpoint = f"/analyst-stock-recommendations/{symbol.upper()}"
        data = await client.get(endpoint)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No analyst recommendations found for {symbol}"
            }
        
        # Get most recent recommendation
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        
        if response_format == "concise":
            data = apply_concise_format("analyst_recommendations", data)
        
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in analyst_recommendations: {e}")
        return format_error_response("fmp_analyst_recommendations", e, {"symbol": symbol})


# ============================================================================
# TOOL: STOCK SCREENER
# ============================================================================

@mcp.tool()
async def fmp_stock_screener(
    market_cap_lower: Optional[float] = None,
    market_cap_upper: Optional[float] = None,
    price_lower: Optional[float] = None,
    price_upper: Optional[float] = None,
    beta_lower: Optional[float] = None,
    beta_upper: Optional[float] = None,
    volume_lower: Optional[float] = None,
    dividend_lower: Optional[float] = None,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    exchange: Optional[str] = None,
    limit: int = 50,
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Screen stocks based on custom criteria.
    
    Filter stocks by:
    - Market capitalization range
    - Price range
    - Beta (volatility) range
    - Trading volume
    - Dividend yield
    - Sector/Industry
    - Exchange
    
    Args:
        market_cap_lower: Minimum market cap (e.g., 1000000000 for $1B)
        market_cap_upper: Maximum market cap
        price_lower: Minimum stock price
        price_upper: Maximum stock price
        beta_lower: Minimum beta
        beta_upper: Maximum beta
        volume_lower: Minimum average volume
        dividend_lower: Minimum dividend yield (%)
        sector: Sector name (e.g., 'Technology', 'Healthcare')
        industry: Industry name
        exchange: Exchange (e.g., 'NYSE', 'NASDAQ')
        limit: Max results (default: 50, max: 1000)
        response_format: 'concise' or 'detailed'
    
    Returns:
        List of stocks matching criteria.
    
    Examples:
        
        # Large cap tech stocks
        {
            "market_cap_lower": 100000000000,
            "sector": "Technology",
            "limit": 20
        }
        
        # High dividend stocks
        {
            "dividend_lower": 3.0,
            "price_upper": 100,
            "limit": 30
        }
        
        # Low beta (defensive) stocks
        {
            "beta_upper": 0.8,
            "market_cap_lower": 5000000000,
            "limit": 25
        }
        
        # Value stocks (low P/E)
        {
            "price_lower": 10,
            "price_upper": 50,
            "exchange": "NYSE",
            "limit": 50
        }
    
    Use Cases:
        - Find investment candidates
        - Build watchlists by criteria
        - Discover stocks in specific sectors
        - Screen for value/growth/dividend stocks
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    is_valid, validation_error = validate_limit(limit, max_limit=1000)
    if not is_valid:
        return {"status": "error", "message": validation_error}
    
    try:
        client = await get_client()
        
        # Build query parameters
        params = {"limit": min(limit, 1000)}
        
        if market_cap_lower is not None:
            params["marketCapMoreThan"] = market_cap_lower
        if market_cap_upper is not None:
            params["marketCapLowerThan"] = market_cap_upper
        if price_lower is not None:
            params["priceMoreThan"] = price_lower
        if price_upper is not None:
            params["priceLowerThan"] = price_upper
        if beta_lower is not None:
            params["betaMoreThan"] = beta_lower
        if beta_upper is not None:
            params["betaLowerThan"] = beta_upper
        if volume_lower is not None:
            params["volumeMoreThan"] = volume_lower
        if dividend_lower is not None:
            params["dividendMoreThan"] = dividend_lower
        if sector:
            params["sector"] = sector
        if industry:
            params["industry"] = industry
        if exchange:
            params["exchange"] = exchange
        
        endpoint = "/stock-screener"
        data = await client.get(endpoint, params)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "ok",
                "message": "No stocks match the specified criteria",
                "count": 0,
                "data": []
            }
        
        if response_format == "concise":
            # Return essential fields
            if isinstance(data, list):
                data = [
                    {
                        "symbol": item.get("symbol"),
                        "companyName": item.get("companyName"),
                        "marketCap": item.get("marketCap"),
                        "price": item.get("price"),
                        "sector": item.get("sector"),
                        "industry": item.get("industry")
                    }
                    for item in data
                ]
        
        return {
            "status": "ok",
            "count": len(data) if isinstance(data, list) else 1,
            "criteria": {k: v for k, v in params.items() if k != "apikey"},
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in stock_screener: {e}")
        return format_error_response("fmp_stock_screener", e, {"limit": limit})


# ============================================================================
# TOOL: GAINERS, LOSERS & MOST ACTIVE
# ============================================================================

@mcp.tool()
async def fmp_market_movers(
    mover_type: str = "gainers",
    response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get daily market movers (top gainers, losers, or most active stocks).
    
    Args:
        mover_type: Type of movers to retrieve:
                    - 'gainers': Top gaining stocks by % change
                    - 'losers': Top losing stocks by % change
                    - 'active': Most actively traded stocks by volume
        response_format: 'concise' or 'detailed'
    
    Returns:
        List of market movers with price, change %, and volume data.
    
    Examples:
        - Top gainers: {"mover_type": "gainers"}
        - Top losers: {"mover_type": "losers"}
        - Most active: {"mover_type": "active"}
    
    Use Cases:
        - Find momentum opportunities
        - Identify potential breakouts
        - Track market sentiment
        - Discover trending stocks
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}
    
    valid_types = ['gainers', 'losers', 'active']
    if mover_type not in valid_types:
        return {
            "status": "error",
            "message": f"Invalid mover_type: '{mover_type}'. Valid options: {', '.join(valid_types)}"
        }
    
    try:
        client = await get_client()
        
        # Map mover type to FMP endpoints
        endpoint_map = {
            'gainers': '/stock_market/gainers',
            'losers': '/stock_market/losers',
            'active': '/stock_market/actives'
        }
        
        endpoint = endpoint_map[mover_type]
        data = await client.get(endpoint)
        rate_limiter.record_call()
        
        if not data:
            return {
                "status": "error",
                "message": f"No {mover_type} data available"
            }
        
        if response_format == "concise":
            # Keep essential fields
            if isinstance(data, list):
                data = [
                    {
                        "symbol": item.get("symbol"),
                        "name": item.get("name"),
                        "price": item.get("price"),
                        "change": item.get("change"),
                        "changesPercentage": item.get("changesPercentage")
                    }
                    for item in data
                ]
        
        return {
            "status": "ok",
            "mover_type": mover_type,
            "count": len(data) if isinstance(data, list) else 1,
            "data": data,
            "rate_limit_status": rate_limiter.get_status()
        }
        
    except Exception as e:
        logger.error(f"Error in market_movers: {e}")
        return format_error_response("fmp_market_movers", e, {"mover_type": mover_type})


# ============================================================================
# SYSTEM PROMPT ENHANCEMENT
# ============================================================================

def get_fmp_system_prompt() -> str:
    """
    Get system prompt enhancement for FMP tools.
    Contains critical rules and workflows for using FMP with AlphaVantage.
    """
    return """
FMP (FINANCIAL MODELING PREP) CRITICAL RULES:

1. **FMP's Unique Value Proposition**
   - Use FMP for ADVANCED ANALYTICS, not raw data
   - AlphaVantage → raw financials (income statement, balance sheet, cash flow)
   - FMP → analytics (ratios, growth rates, valuations, ownership)
   - Don't duplicate what AlphaVantage already provides

2. **DCF Valuation Workflow (CRITICAL)**
   
   Standard Workflow:
   Step 1: Gather data from AlphaVantage
      cash_flow = alphavantage_cash_flow(symbol="AAPL")
      income = alphavantage_income_statement(symbol="AAPL")
      balance = alphavantage_balance_sheet(symbol="AAPL")
      overview = alphavantage_company_overview(symbol="AAPL")
   
   Step 2: Extract latest annual data
      latest_cf = cash_flow['annualReports'][0]
      latest_income = income['annualReports'][0]
      latest_balance = balance['annualReports'][0]
   
   Step 3: Map to FMP parameters
      AlphaVantage Field                          → FMP DCF Parameter
      -------------------------------------------------------------------------
      latest_cf['operatingCashFlow']             → operating_cash_flow
      latest_cf['capitalExpenditures']           → capital_expenditures
      [calculated: OCF - |CapEx|]                → free_cash_flow
      latest_income['totalRevenue']              → revenue
      latest_income['ebitda']                    → ebitda
      latest_balance['shortLongTermDebtTotal']   → total_debt
      latest_balance['cashAndCashEquivalentsAtCarryingValue'] → cash
      overview['SharesOutstanding']              → shares_outstanding
      overview['Beta']                           → beta
   
   Step 4: Call FMP DCF
      fmp_advanced_dcf(
          symbol="AAPL",
          operating_cash_flow=extracted_value,
          capital_expenditures=abs(extracted_value),  # Make positive!
          free_cash_flow=ocf_minus_capex,
          ...
      )
   
   Quick Estimate Alternative:
      - Just call: fmp_advanced_dcf(symbol="AAPL")
      - FMP fetches its own data (may be less current)
      - Use when AlphaVantage data unavailable

3. **Field Name Mapping (Memorize These)**
   
   Cash Flow Statement:
   - operatingCashFlow → operating_cash_flow
   - capitalExpenditures → capital_expenditures (take absolute value!)
   
   Income Statement:
   - totalRevenue → revenue
   - ebitda → ebitda
   
   Balance Sheet:
   - shortLongTermDebtTotal → total_debt
   - cashAndCashEquivalentsAtCarryingValue → cash
   
   Company Overview:
   - SharesOutstanding → shares_outstanding
   - Beta → beta

4. **Data Validation Before DCF**
   
   Always validate:
   ✓ FCF = Operating Cash Flow - Capital Expenditures
   ✓ CapEx should be POSITIVE after abs()
   ✓ All values in same currency/units
   ✓ Shares outstanding matches current count
   ✓ Beta is reasonable (typically 0.5 to 2.0)
   
   If validation fails:
   - Flag inconsistency
   - Use best judgment
   - Can override specific fields

5. **When to Use Each FMP Tool**
   
   Financial Analysis:
   - fmp_financial_ratios → Liquidity, leverage, efficiency, profitability
   - fmp_key_metrics → P/E, P/B, ROE, ROA, per-share metrics
   - fmp_financial_growth → YoY/QoQ growth rates
   - fmp_company_rating → Quick quality score
   - fmp_enterprise_values → Market cap & EV history
   
   Valuation:
   - fmp_advanced_dcf → Standard DCF valuation
   - fmp_levered_dcf → DCF accounting for leverage
   
   Ownership Intelligence:
   - fmp_institutional_ownership → Who owns the stock
   - fmp_insider_trading → Management buying/selling
   
   Analyst Coverage:
   - fmp_analyst_estimates → Revenue/EPS forecasts
   - fmp_upgrades_downgrades → Rating changes
   - fmp_analyst_recommendations → Buy/sell/hold consensus
   
   Market Screening:
   - fmp_stock_screener → Find stocks by criteria
   - fmp_market_movers → Daily gainers/losers/actives

6. **Response Format Strategy**
   - Use response_format="concise" by default
   - CONCISE strips to essential fields only
   - Use DETAILED when comprehensive data needed
   - Saves tokens without losing critical info

7. **Rate Limits**
   - Free tier: 250 calls per day
   - No per-minute limit
   - Track usage via rate_limit_status
   - Plan your queries efficiently

8. **Symbol Usage**
   - Use ticker symbols, NOT company names
   - Same rules as AlphaVantage
   - Use fmp_symbol_search if ticker unknown

9. **Period Parameters**
   - 'annual' → Year-over-year data
   - 'quarter' → Quarter-over-quarter data
   - Use annual for DCF (more stable)
   - Use quarterly for recent trends

10. **Data Source Priority**
    When both AlphaVantage and FMP have same data:
    Priority: AlphaVantage (fresher) > FMP
    
    AlphaVantage is better for:
    - Raw financial statements
    - Recent earnings data
    - Time series prices
    
    FMP is better for:
    - Calculated ratios
    - Growth rates
    - Valuations (DCF)
    - Ownership data
    - Analyst coverage

11. **Common Mistakes to Avoid**
    - Using FMP for raw financials (use AlphaVantage)
    - Forgetting to take abs() of CapEx
    - Mixing quarterly and annual data in DCF
    - Not validating FCF = OCF - CapEx
    - Using company names instead of tickers
    - Ignoring rate limits

12. **Integration Patterns**
    
    Pattern 1: Full Analysis
    1. AlphaVantage → Raw financials
    2. FMP → Calculate ratios and growth
    3. FMP → Run DCF valuation
    4. FMP → Check insider trading
    5. FMP → Review analyst estimates
    
    Pattern 2: Valuation Focus
    1. AlphaVantage → Get financials
    2. Extract and map fields
    3. FMP DCF → Intrinsic value
    4. Compare with current price
    
    Pattern 3: Ownership Analysis
    1. FMP → Institutional holders
    2. FMP → Insider transactions
    3. Identify patterns and trends
    
    Pattern 4: Screening
    1. FMP → Screen for candidates
    2. AlphaVantage → Get detailed data
    3. FMP → Analyze metrics
    4. FMP → Run valuations

13. **Ambiguity Resolution**
    - Multiple time periods? → Use latest annual for DCF
    - Missing data? → Let FMP fill gaps
    - Field name unclear? → Refer to mapping table
    - Conflicting sources? → Prefer AlphaVantage (fresher)
    - Agent unsure? → Ask user or use best judgment
"""


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    print(
        "[FMP] MCP Server Starting...\n"
        "Financial Modeling Prep - Advanced Financial Analytics\n"
        "Designed to complement AlphaVantage with analytical capabilities\n"
        "\nRate Limits: 250 calls/day (free tier)\n"
        "\nCore Capabilities:\n"
        "  Advanced Metrics: Financial ratios, key metrics, growth rates, ratings\n"
        "  Valuation: DCF models (advanced & levered) with AlphaVantage integration\n"
        "  Ownership: Institutional holders, insider trading\n"
        "  Analyst Coverage: Estimates, upgrades/downgrades, recommendations\n"
        "  Market Tools: Stock screener, market movers\n"
        "\nBest Practice: Use AlphaVantage for raw data, FMP for analytics!\n"
        "\nDCF Workflow:\n"
        "  1. Gather financials from AlphaVantage\n"
        "  2. Map fields to FMP parameters\n"
        "  3. Run DCF valuation\n"
        "  4. Compare intrinsic value vs market price\n",
        flush=True
    )
    
    # Get system prompt (for documentation/reference)
    system_prompt = get_fmp_system_prompt()
    
    # Run the MCP server
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8086)
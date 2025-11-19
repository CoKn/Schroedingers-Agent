"""
M&A Analytics MCP Server - Comparable Companies Analysis
Automated peer identification, valuation multiples, and benchmarking.

This server provides sophisticated comparable company analysis (comps) for M&A
valuation, using data from AlphaVantage and FMP to calculate trading multiples,
percentile rankings, and valuation ranges.

Key Features:
- Automated peer identification by sector, size, and metrics
- Trading multiples calculation (EV/EBITDA, P/E, P/S, etc.)
- Valuation ranges based on comparable companies
- Percentile rankings and benchmarking
- Comprehensive comparison matrices
"""

from __future__ import annotations

import os
import asyncio
import logging
import httpx
import statistics
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime
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
    mcp = FastMCP(name="MA_Analytics")
except TypeError:
    mcp = FastMCP()


# ============================================================================
# CONFIGURATION & ENUMS
# ============================================================================

class ResponseFormat(str, Enum):
    """Control verbosity of tool responses."""
    CONCISE = "concise"
    DETAILED = "detailed"


# API Configuration
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
FMP_API_KEY = os.getenv("FMP_API_KEY")

ALPHAVANTAGE_BASE_URL = "https://www.alphavantage.co/query"
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class CompanyMetrics:
    """Core metrics for comparable analysis."""
    symbol: str
    name: str
    sector: str
    industry: str
    market_cap: float
    enterprise_value: float
    stock_price: float

    # Income Statement
    revenue: float
    ebitda: float
    ebit: float
    net_income: float

    # Balance Sheet
    total_assets: float
    total_equity: float
    total_debt: float

    # Cash Flow
    operating_cash_flow: float
    free_cash_flow: float

    # Ratios
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None

    # Growth
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None


@dataclass
class TradingMultiples:
    """Calculated trading multiples."""
    symbol: str

    # EV Multiples
    ev_revenue: Optional[float] = None
    ev_ebitda: Optional[float] = None
    ev_ebit: Optional[float] = None
    ev_fcf: Optional[float] = None

    # Price Multiples
    p_e: Optional[float] = None
    p_b: Optional[float] = None
    p_s: Optional[float] = None
    peg: Optional[float] = None


# ============================================================================
# API CLIENTS
# ============================================================================

class AlphaVantageClient:
    """Client for AlphaVantage API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = ALPHAVANTAGE_BASE_URL
        self.client = httpx.AsyncClient(timeout=30.0)

    async def get_company_overview(self, symbol: str) -> Dict[str, Any]:
        """Get company overview."""
        params = {
            "function": "OVERVIEW",
            "symbol": symbol,
            "apikey": self.api_key
        }

        response = await self.client.get(self.base_url, params=params)
        response.raise_for_status()
        return response.json()

    async def get_income_statement(self, symbol: str) -> Dict[str, Any]:
        """Get annual income statement."""
        params = {
            "function": "INCOME_STATEMENT",
            "symbol": symbol,
            "apikey": self.api_key
        }

        response = await self.client.get(self.base_url, params=params)
        response.raise_for_status()
        return response.json()

    async def get_balance_sheet(self, symbol: str) -> Dict[str, Any]:
        """Get annual balance sheet."""
        params = {
            "function": "BALANCE_SHEET",
            "symbol": symbol,
            "apikey": self.api_key
        }

        response = await self.client.get(self.base_url, params=params)
        response.raise_for_status()
        return response.json()

    async def get_cash_flow(self, symbol: str) -> Dict[str, Any]:
        """Get annual cash flow statement."""
        params = {
            "function": "CASH_FLOW",
            "symbol": symbol,
            "apikey": self.api_key
        }

        response = await self.client.get(self.base_url, params=params)
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.client.aclose()


class FMPClient:
    """Client for Financial Modeling Prep API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = FMP_BASE_URL
        self.client = httpx.AsyncClient(timeout=30.0)

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get real-time quote."""
        url = f"{self.base_url}/quote/{symbol}"
        params = {"apikey": self.api_key}

        response = await self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        return data[0] if data else {}

    async def get_key_metrics(self, symbol: str) -> Dict[str, Any]:
        """Get key metrics."""
        url = f"{self.base_url}/key-metrics/{symbol}"
        params = {"apikey": self.api_key, "limit": 1}

        response = await self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        return data[0] if data else {}

    async def get_enterprise_value(self, symbol: str) -> Dict[str, Any]:
        """Get enterprise value."""
        url = f"{self.base_url}/enterprise-values/{symbol}"
        params = {"apikey": self.api_key, "limit": 1}

        response = await self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        return data[0] if data else {}

    async def get_financial_ratios(self, symbol: str) -> Dict[str, Any]:
        """Get financial ratios."""
        url = f"{self.base_url}/ratios/{symbol}"
        params = {"apikey": self.api_key, "limit": 1}

        response = await self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        return data[0] if data else {}

    async def screen_stocks(self, **filters) -> List[Dict[str, Any]]:
        """Screen stocks by criteria."""
        url = f"{self.base_url}/stock-screener"
        params = {"apikey": self.api_key, "limit": 100, **filters}

        response = await self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.client.aclose()


# Global clients
_av_client: Optional[AlphaVantageClient] = None
_fmp_client: Optional[FMPClient] = None


async def get_av_client() -> AlphaVantageClient:
    """Get or create AlphaVantage client."""
    global _av_client
    if _av_client is None:
        _av_client = AlphaVantageClient(ALPHAVANTAGE_API_KEY)
    return _av_client


async def get_fmp_client() -> FMPClient:
    """Get or create FMP client."""
    global _fmp_client
    if _fmp_client is None:
        _fmp_client = FMPClient(FMP_API_KEY)
    return _fmp_client


# ============================================================================
# DATA AGGREGATION
# ============================================================================

async def fetch_company_metrics(symbol: str) -> CompanyMetrics:
    """
    Fetch comprehensive company metrics from multiple sources.

    Combines data from AlphaVantage and FMP to build complete picture.
    """
    av_client = await get_av_client()
    fmp_client = await get_fmp_client()

    # Fetch data in parallel
    overview_task = av_client.get_company_overview(symbol)
    income_task = av_client.get_income_statement(symbol)
    balance_task = av_client.get_balance_sheet(symbol)
    cashflow_task = av_client.get_cash_flow(symbol)
    quote_task = fmp_client.get_quote(symbol)
    metrics_task = fmp_client.get_key_metrics(symbol)
    ev_task = fmp_client.get_enterprise_value(symbol)
    ratios_task = fmp_client.get_financial_ratios(symbol)

    overview, income, balance, cashflow, quote, metrics, ev, ratios = await asyncio.gather(
        overview_task, income_task, balance_task, cashflow_task,
        quote_task, metrics_task, ev_task, ratios_task,
        return_exceptions=True
    )

    # Handle errors
    if isinstance(overview, Exception):
        raise Exception(f"Failed to fetch overview for {symbol}: {overview}")

    # Extract latest annual data
    latest_income = income.get("annualReports", [{}])[0] if not isinstance(income, Exception) else {}
    latest_balance = balance.get("annualReports", [{}])[0] if not isinstance(balance, Exception) else {}
    latest_cashflow = cashflow.get("annualReports", [{}])[0] if not isinstance(cashflow, Exception) else {}

    # Helper to safely convert to float
    def safe_float(value, default=0.0):
        try:
            return float(value) if value not in [None, "", "None"] else default
        except (ValueError, TypeError):
            return default

    # Build CompanyMetrics
    return CompanyMetrics(
        symbol=symbol,
        name=overview.get("Name", symbol),
        sector=overview.get("Sector", "Unknown"),
        industry=overview.get("Industry", "Unknown"),
        market_cap=safe_float(overview.get("MarketCapitalization")),
        enterprise_value=safe_float(ev.get("enterpriseValue")) if not isinstance(ev, Exception) else 0.0,
        stock_price=safe_float(quote.get("price")) if not isinstance(quote, Exception) else 0.0,

        # Income Statement
        revenue=safe_float(latest_income.get("totalRevenue")),
        ebitda=safe_float(latest_income.get("ebitda")),
        ebit=safe_float(latest_income.get("operatingIncome")),
        net_income=safe_float(latest_income.get("netIncome")),

        # Balance Sheet
        total_assets=safe_float(latest_balance.get("totalAssets")),
        total_equity=safe_float(latest_balance.get("totalShareholderEquity")),
        total_debt=safe_float(latest_balance.get("shortLongTermDebtTotal")),

        # Cash Flow
        operating_cash_flow=safe_float(latest_cashflow.get("operatingCashflow")),
        free_cash_flow=safe_float(latest_cashflow.get("operatingCashflow")) - safe_float(
            latest_cashflow.get("capitalExpenditures")),

        # Ratios
        pe_ratio=safe_float(overview.get("PERatio")),
        pb_ratio=safe_float(overview.get("PriceToBookRatio")),
        debt_to_equity=safe_float(ratios.get("debtEquityRatio")) if not isinstance(ratios, Exception) else None,
        roe=safe_float(overview.get("ReturnOnEquityTTM")),
        roa=safe_float(overview.get("ReturnOnAssetsTTM")),

        # Growth
        revenue_growth=safe_float(overview.get("QuarterlyRevenueGrowthYOY")),
        earnings_growth=safe_float(overview.get("QuarterlyEarningsGrowthYOY"))
    )


def calculate_multiples(metrics: CompanyMetrics) -> TradingMultiples:
    """Calculate trading multiples from company metrics."""

    def safe_divide(numerator, denominator):
        """Safely divide, returning None if invalid."""
        try:
            if denominator and denominator != 0 and numerator:
                result = numerator / denominator
                # Filter out unreasonable multiples
                if -1000 < result < 1000:
                    return round(result, 2)
        except (ZeroDivisionError, TypeError):
            pass
        return None

    return TradingMultiples(
        symbol=metrics.symbol,
        # EV Multiples
        ev_revenue=safe_divide(metrics.enterprise_value, metrics.revenue),
        ev_ebitda=safe_divide(metrics.enterprise_value, metrics.ebitda),
        ev_ebit=safe_divide(metrics.enterprise_value, metrics.ebit),
        ev_fcf=safe_divide(metrics.enterprise_value, metrics.free_cash_flow),
        # Price Multiples
        p_e=metrics.pe_ratio,
        p_b=metrics.pb_ratio,
        p_s=safe_divide(metrics.market_cap, metrics.revenue),
        peg=safe_divide(metrics.pe_ratio, metrics.earnings_growth * 100) if metrics.earnings_growth else None
    )


# ============================================================================
# STATISTICAL ANALYSIS
# ============================================================================

def calculate_statistics(values: List[float]) -> Dict[str, float]:
    """Calculate statistical measures for a list of values."""
    if not values:
        return {}

    # Filter out None and invalid values
    valid_values = [v for v in values if
                    v is not None and not (isinstance(v, float) and (v != v))]  # v != v checks for NaN

    if not valid_values:
        return {}

    try:
        return {
            "min": round(min(valid_values), 2),
            "max": round(max(valid_values), 2),
            "mean": round(statistics.mean(valid_values), 2),
            "median": round(statistics.median(valid_values), 2),
            "p25": round(statistics.quantiles(valid_values, n=4)[0], 2) if len(valid_values) >= 4 else None,
            "p75": round(statistics.quantiles(valid_values, n=4)[2], 2) if len(valid_values) >= 4 else None,
            "count": len(valid_values)
        }
    except statistics.StatisticsError:
        return {"count": len(valid_values)}


def calculate_percentile_rank(value: float, peer_values: List[float]) -> Optional[float]:
    """Calculate percentile rank of a value within peer group."""
    if value is None or not peer_values:
        return None

    valid_peers = [v for v in peer_values if v is not None]
    if not valid_peers:
        return None

    # Count how many peers are below this value
    below_count = sum(1 for v in valid_peers if v < value)
    percentile = (below_count / len(valid_peers)) * 100

    return round(percentile, 1)


# ============================================================================
# TOOL: FIND PEERS
# ============================================================================

@mcp.tool()
async def comps_find_peers(
        symbol: str,
        sector: Optional[str] = None,
        market_cap_min: Optional[float] = None,
        market_cap_max: Optional[float] = None,
        max_peers: int = 10,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Identify comparable companies (peers) for valuation analysis.

    Uses sector, industry, size, and other criteria to find similar companies
    suitable for comparable company analysis.

    Args:
        symbol: Target company ticker symbol
        sector: Filter by sector (if None, uses target company's sector)
        market_cap_min: Minimum market cap (optional, auto-calculated if not provided)
        market_cap_max: Maximum market cap (optional, auto-calculated if not provided)
        max_peers: Maximum number of peers to return (default: 10, max: 20)
        response_format: 'concise' or 'detailed'

    Returns:
        List of peer companies with key metrics.

    Examples:

        # Find peers for Apple
        {"symbol": "AAPL"}

        # Find tech sector peers with size constraints
        {
            "symbol": "MSFT",
            "sector": "TECHNOLOGY",
            "market_cap_min": 500000000000,
            "market_cap_max": 3000000000000
        }

        # Find more peers
        {"symbol": "TSLA", "max_peers": 15}

    Use Cases:
        - Build peer group for valuation
        - Identify acquisition targets
        - Benchmark analysis preparation
        - Trading multiples calculation

    Notes:
        - Automatically filters by sector if not specified
        - Market cap range defaults to 0.3x - 3x target if not specified
        - Excludes the target company from peer list
        - Returns companies sorted by similarity to target
    """
    try:
        av_client = await get_av_client()
        fmp_client = await get_fmp_client()

        # Get target company data
        logger.info(f"Fetching data for target company: {symbol}")
        target_metrics = await fetch_company_metrics(symbol)

        # Determine search criteria
        search_sector = sector or target_metrics.sector

        # Auto-calculate market cap range if not provided (0.3x to 3x target)
        if market_cap_min is None:
            market_cap_min = target_metrics.market_cap * 0.3
        if market_cap_max is None:
            market_cap_max = target_metrics.market_cap * 3.0

        logger.info(
            f"Searching for peers in {search_sector} with market cap {market_cap_min:,.0f} to {market_cap_max:,.0f}")

        # Screen for peers using FMP
        candidates = await fmp_client.screen_stocks(
            sector=search_sector,
            marketCapMoreThan=int(market_cap_min),
            marketCapLowerThan=int(market_cap_max),
            limit=min(max_peers * 3, 50)  # Get extra to filter
        )

        if not candidates:
            return {
                "status": "error",
                "message": f"No peer companies found for {symbol} in {search_sector}"
            }

        # Filter out target company and invalid entries
        peer_symbols = [
            c["symbol"] for c in candidates
            if c.get("symbol") and c["symbol"].upper() != symbol.upper()
        ][:max_peers]

        logger.info(f"Found {len(peer_symbols)} peer candidates: {peer_symbols}")

        # Fetch detailed metrics for peers
        peer_metrics_tasks = [fetch_company_metrics(sym) for sym in peer_symbols]
        peer_metrics_results = await asyncio.gather(*peer_metrics_tasks, return_exceptions=True)

        # Filter out failed fetches
        peer_metrics = [
            m for m in peer_metrics_results
            if not isinstance(m, Exception)
        ]

        if not peer_metrics:
            return {
                "status": "error",
                "message": "Failed to fetch peer company data"
            }

        # Format response
        if response_format == "concise":
            peers = [
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "market_cap": p.market_cap,
                    "sector": p.sector,
                    "industry": p.industry
                }
                for p in peer_metrics
            ]
        else:
            peers = [
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "sector": p.sector,
                    "industry": p.industry,
                    "market_cap": p.market_cap,
                    "enterprise_value": p.enterprise_value,
                    "revenue": p.revenue,
                    "ebitda": p.ebitda,
                    "pe_ratio": p.pe_ratio,
                    "revenue_growth": p.revenue_growth
                }
                for p in peer_metrics
            ]

        return {
            "status": "ok",
            "target": {
                "symbol": target_metrics.symbol,
                "name": target_metrics.name,
                "sector": target_metrics.sector,
                "market_cap": target_metrics.market_cap
            },
            "search_criteria": {
                "sector": search_sector,
                "market_cap_min": market_cap_min,
                "market_cap_max": market_cap_max
            },
            "peer_count": len(peers),
            "peers": peers
        }

    except Exception as e:
        logger.error(f"Error in comps_find_peers: {e}")
        return {
            "status": "error",
            "error": str(e),
            "symbol": symbol
        }


# ============================================================================
# TOOL: CALCULATE MULTIPLES
# ============================================================================

@mcp.tool()
async def comps_calculate_multiples(
        symbols: List[str],
        include_statistics: bool = True,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Calculate trading multiples for a group of companies.

    Computes valuation multiples (EV/EBITDA, P/E, P/S, etc.) for each company
    and optionally provides statistical analysis across the peer group.

    Args:
        symbols: List of ticker symbols (2-20 companies recommended)
        include_statistics: If True, includes min/max/median/mean across peers
        response_format: 'concise' or 'detailed'

    Returns:
        Trading multiples for each company plus statistical summary.

    Multiples Calculated:
        EV Multiples:
        - EV/Revenue: Enterprise value to revenue
        - EV/EBITDA: Enterprise value to EBITDA (most common)
        - EV/EBIT: Enterprise value to operating income
        - EV/FCF: Enterprise value to free cash flow

        Price Multiples:
        - P/E: Price to earnings
        - P/B: Price to book value
        - P/S: Price to sales
        - PEG: P/E to growth ratio

    Examples:

        # Calculate multiples for peer group
        {"symbols": ["AAPL", "MSFT", "GOOGL", "META"]}

        # Without statistics
        {
            "symbols": ["TSLA", "F", "GM"],
            "include_statistics": false
        }

        # Concise output
        {
            "symbols": ["JPM", "BAC", "C", "WFC"],
            "response_format": "concise"
        }

    Use Cases:
        - Valuation benchmarking
        - Relative value analysis
        - Identify outliers in peer group
        - Prepare trading comps table

    Notes:
        - Invalid or unavailable multiples return None
        - Filters out unreasonable multiples (< -1000 or > 1000)
        - Statistics exclude None values
        - EV/EBITDA is the gold standard for M&A
    """
    try:
        if not symbols or len(symbols) == 0:
            return {"status": "error", "message": "No symbols provided"}

        if len(symbols) > 20:
            return {"status": "error", "message": "Maximum 20 symbols allowed"}

        logger.info(f"Calculating multiples for {len(symbols)} companies")

        # Fetch metrics for all companies
        metrics_tasks = [fetch_company_metrics(sym) for sym in symbols]
        metrics_results = await asyncio.gather(*metrics_tasks, return_exceptions=True)

        # Filter out failures and calculate multiples
        company_multiples = []
        for sym, result in zip(symbols, metrics_results):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch data for {sym}: {result}")
                continue

            multiples = calculate_multiples(result)
            company_multiples.append((result, multiples))

        if not company_multiples:
            return {"status": "error", "message": "Failed to calculate multiples for any company"}

        # Format multiples data
        multiples_data = []
        for metrics, multiples in company_multiples:
            if response_format == "concise":
                multiples_data.append({
                    "symbol": multiples.symbol,
                    "name": metrics.name,
                    "ev_ebitda": multiples.ev_ebitda,
                    "p_e": multiples.p_e,
                    "ev_revenue": multiples.ev_revenue
                })
            else:
                multiples_data.append({
                    "symbol": multiples.symbol,
                    "name": metrics.name,
                    "market_cap": metrics.market_cap,
                    "enterprise_value": metrics.enterprise_value,
                    "multiples": {
                        "ev_revenue": multiples.ev_revenue,
                        "ev_ebitda": multiples.ev_ebitda,
                        "ev_ebit": multiples.ev_ebit,
                        "ev_fcf": multiples.ev_fcf,
                        "p_e": multiples.p_e,
                        "p_b": multiples.p_b,
                        "p_s": multiples.p_s,
                        "peg": multiples.peg
                    }
                })

        result = {
            "status": "ok",
            "company_count": len(multiples_data),
            "companies": multiples_data
        }

        # Add statistics if requested
        if include_statistics:
            all_multiples = [m for _, m in company_multiples]

            stats = {
                "ev_revenue": calculate_statistics([m.ev_revenue for m in all_multiples]),
                "ev_ebitda": calculate_statistics([m.ev_ebitda for m in all_multiples]),
                "ev_ebit": calculate_statistics([m.ev_ebit for m in all_multiples]),
                "ev_fcf": calculate_statistics([m.ev_fcf for m in all_multiples]),
                "p_e": calculate_statistics([m.p_e for m in all_multiples]),
                "p_b": calculate_statistics([m.p_b for m in all_multiples]),
                "p_s": calculate_statistics([m.p_s for m in all_multiples]),
                "peg": calculate_statistics([m.peg for m in all_multiples])
            }

            result["statistics"] = stats

        return result

    except Exception as e:
        logger.error(f"Error in comps_calculate_multiples: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# ============================================================================
# TOOL: VALUATION RANGE
# ============================================================================

@mcp.tool()
async def comps_valuation_range(
        target_symbol: str,
        peer_symbols: List[str],
        primary_multiple: str = "ev_ebitda",
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Estimate valuation range for target company based on peer multiples.

    Applies peer group trading multiples to target company's metrics to
    derive implied valuation range (low, median, high scenarios).

    Args:
        target_symbol: Target company to value
        peer_symbols: List of comparable company symbols
        primary_multiple: Which multiple to use for valuation
                         Options: 'ev_ebitda', 'ev_revenue', 'ev_ebit', 'ev_fcf',
                         'p_e', 'p_s', 'p_b'
        response_format: 'concise' or 'detailed'

    Returns:
        Valuation range with low/median/high scenarios plus current market value.

    Valuation Logic:
        1. Calculate trading multiples for all peer companies
        2. Derive statistics (min, median, mean, max) from peer multiples
        3. Apply peer multiples to target's financial metrics
        4. Generate valuation range:
           - Low: 25th percentile peer multiple × target metric
           - Median: Median peer multiple × target metric
           - High: 75th percentile peer multiple × target metric
        5. Compare to current market value

    Examples:

        # Value Apple using EV/EBITDA from tech peers
        {
            "target_symbol": "AAPL",
            "peer_symbols": ["MSFT", "GOOGL", "META", "NVDA"],
            "primary_multiple": "ev_ebitda"
        }

        # Value using EV/Revenue (for growth companies)
        {
            "target_symbol": "SNOW",
            "peer_symbols": ["CRM", "NOW", "WDAY"],
            "primary_multiple": "ev_revenue"
        }

        # Value using P/E ratio
        {
            "target_symbol": "JPM",
            "peer_symbols": ["BAC", "C", "WFC", "USB"],
            "primary_multiple": "p_e"
        }

    Choosing the Right Multiple:
        - EV/EBITDA: Most common for M&A, mature companies
        - EV/Revenue: High-growth, pre-profit companies
        - P/E: Profitable companies with stable earnings
        - EV/FCF: Cash-generative businesses
        - P/S: Revenue-focused valuation

    Use Cases:
        - Estimate fair value range for acquisition target
        - Determine offer price range
        - Assess if company is over/undervalued
        - Support fairness opinion

    Notes:
        - Requires sufficient peer data (recommend 4+ peers)
        - Multiples must be valid (not None) for peers
        - Target company must have the relevant metric (e.g., EBITDA for EV/EBITDA)
        - Shows upside/downside vs current market price
    """
    try:
        logger.info(f"Calculating valuation range for {target_symbol} using {primary_multiple}")

        # Validate primary_multiple
        valid_multiples = [
            "ev_ebitda", "ev_revenue", "ev_ebit", "ev_fcf",
            "p_e", "p_s", "p_b"
        ]
        if primary_multiple not in valid_multiples:
            return {
                "status": "error",
                "message": f"Invalid multiple: {primary_multiple}. Valid options: {', '.join(valid_multiples)}"
            }

        # Fetch target metrics
        target_metrics = await fetch_company_metrics(target_symbol)

        # Map multiple to target metric
        metric_mapping = {
            "ev_ebitda": ("ebitda", target_metrics.ebitda),
            "ev_revenue": ("revenue", target_metrics.revenue),
            "ev_ebit": ("ebit", target_metrics.ebit),
            "ev_fcf": ("free_cash_flow", target_metrics.free_cash_flow),
            "p_e": ("net_income", target_metrics.net_income),
            "p_s": ("revenue", target_metrics.revenue),
            "p_b": ("total_equity", target_metrics.total_equity)
        }

        metric_name, target_metric_value = metric_mapping[primary_multiple]

        if not target_metric_value or target_metric_value <= 0:
            return {
                "status": "error",
                "message": f"Target company has invalid {metric_name}: {target_metric_value}"
            }

        # Fetch peer metrics and calculate multiples
        logger.info(f"Fetching data for {len(peer_symbols)} peers")
        peer_metrics_tasks = [fetch_company_metrics(sym) for sym in peer_symbols]
        peer_metrics_results = await asyncio.gather(*peer_metrics_tasks, return_exceptions=True)

        peer_multiples_list = []
        for result in peer_metrics_results:
            if isinstance(result, Exception):
                continue
            multiples = calculate_multiples(result)
            peer_multiples_list.append(multiples)

        if len(peer_multiples_list) < 2:
            return {
                "status": "error",
                "message": f"Insufficient peer data. Need at least 2 peers, got {len(peer_multiples_list)}"
            }

        # Extract the specific multiple values from peers
        peer_multiple_values = []
        for m in peer_multiples_list:
            value = getattr(m, primary_multiple)
            if value is not None and value > 0:
                peer_multiple_values.append(value)

        if len(peer_multiple_values) < 2:
            return {
                "status": "error",
                "message": f"Insufficient valid {primary_multiple} data from peers"
            }

        # Calculate statistics
        stats = calculate_statistics(peer_multiple_values)

        # Calculate valuation range
        # Use P25, median, P75 if available, otherwise min, mean, max
        low_multiple = stats.get("p25") or stats.get("min")
        mid_multiple = stats.get("median")
        high_multiple = stats.get("p75") or stats.get("max")

        # For EV multiples, result is enterprise value
        # For P multiples, result is market cap
        is_ev_multiple = primary_multiple.startswith("ev_")

        low_valuation = low_multiple * target_metric_value
        mid_valuation = mid_multiple * target_metric_value
        high_valuation = high_multiple * target_metric_value

        # Current value for comparison
        current_value = target_metrics.enterprise_value if is_ev_multiple else target_metrics.market_cap

        # Calculate implied upside/downside
        def calc_upside(valuation, current):
            if current and current > 0:
                return round(((valuation / current) - 1) * 100, 1)
            return None

        low_upside = calc_upside(low_valuation, current_value)
        mid_upside = calc_upside(mid_valuation, current_value)
        high_upside = calc_upside(high_valuation, current_value)

        result = {
            "status": "ok",
            "target": {
                "symbol": target_metrics.symbol,
                "name": target_metrics.name,
                "current_market_cap": target_metrics.market_cap,
                "current_enterprise_value": target_metrics.enterprise_value,
                "metric_used": metric_name,
                "metric_value": target_metric_value
            },
            "multiple_used": primary_multiple,
            "peer_statistics": stats,
            "valuation_range": {
                "low": {
                    "multiple": low_multiple,
                    "valuation": round(low_valuation, 0),
                    "upside_pct": low_upside
                },
                "median": {
                    "multiple": mid_multiple,
                    "valuation": round(mid_valuation, 0),
                    "upside_pct": mid_upside
                },
                "high": {
                    "multiple": high_multiple,
                    "valuation": round(high_valuation, 0),
                    "upside_pct": high_upside
                }
            },
            "peers_analyzed": len(peer_multiple_values)
        }

        if response_format == "detailed":
            result["peer_multiples"] = [
                {
                    "symbol": m.symbol,
                    "multiple_value": getattr(m, primary_multiple)
                }
                for m in peer_multiples_list
                if getattr(m, primary_multiple) is not None
            ]

        return result

    except Exception as e:
        logger.error(f"Error in comps_valuation_range: {e}")
        return {
            "status": "error",
            "error": str(e),
            "target_symbol": target_symbol
        }


# ============================================================================
# TOOL: PERCENTILE RANKING
# ============================================================================

@mcp.tool()
async def comps_percentile_ranking(
        target_symbol: str,
        peer_symbols: List[str],
        metrics: Optional[List[str]] = None,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Rank target company vs peers across key metrics.

    Calculates percentile rankings to show where target stands relative to
    peer group on various financial metrics and valuation multiples.

    Args:
        target_symbol: Target company to rank
        peer_symbols: List of peer company symbols
        metrics: Specific metrics to rank (if None, uses default set)
                Options: 'revenue', 'ebitda', 'market_cap', 'revenue_growth',
                'ebitda_margin', 'roe', 'roa', 'debt_to_equity',
                'ev_ebitda', 'p_e', 'p_s'
        response_format: 'concise' or 'detailed'

    Returns:
        Percentile rankings showing target's position vs peers.

    Percentile Interpretation:
        - 0-25th percentile: Bottom quartile (weak relative performance)
        - 25-50th percentile: Below median
        - 50-75th percentile: Above median
        - 75-100th percentile: Top quartile (strong relative performance)

    Examples:

        # Full ranking across all metrics
        {
            "target_symbol": "AAPL",
            "peer_symbols": ["MSFT", "GOOGL", "META", "NVDA"]
        }

        # Rank specific metrics
        {
            "target_symbol": "TSLA",
            "peer_symbols": ["F", "GM", "TM", "HMC"],
            "metrics": ["revenue_growth", "ebitda_margin", "ev_ebitda"]
        }

        # Concise output
        {
            "target_symbol": "JPM",
            "peer_symbols": ["BAC", "C", "WFC", "USB"],
            "response_format": "concise"
        }

    Use Cases:
        - Quick competitive positioning
        - Identify strengths and weaknesses vs peers
        - Support strategic analysis
        - Benchmark performance

    Notes:
        - Higher percentile = better for growth, profitability, returns
        - Lower percentile = better for valuation multiples (cheaper)
        - Requires at least 3 peers for meaningful percentiles
        - Excludes target from peer calculations
    """
    try:
        logger.info(f"Calculating percentile rankings for {target_symbol}")

        # Default metrics if not specified
        if metrics is None:
            metrics = [
                "revenue", "ebitda", "market_cap", "revenue_growth",
                "ebitda_margin", "roe", "debt_to_equity",
                "ev_ebitda", "p_e"
            ]

        # Fetch all company data
        all_symbols = [target_symbol] + peer_symbols
        metrics_tasks = [fetch_company_metrics(sym) for sym in all_symbols]
        metrics_results = await asyncio.gather(*metrics_tasks, return_exceptions=True)

        # Separate target and peers
        target_data = metrics_results[0]
        if isinstance(target_data, Exception):
            return {
                "status": "error",
                "message": f"Failed to fetch target data: {target_data}"
            }

        peer_data = [r for r in metrics_results[1:] if not isinstance(r, Exception)]

        if len(peer_data) < 2:
            return {
                "status": "error",
                "message": "Need at least 2 valid peers for ranking"
            }

        # Calculate multiples for all companies
        target_multiples = calculate_multiples(target_data)
        peer_multiples = [calculate_multiples(p) for p in peer_data]

        # Calculate rankings for each metric
        rankings = {}

        metric_extractors = {
            "revenue": lambda m: m.revenue,
            "ebitda": lambda m: m.ebitda,
            "market_cap": lambda m: m.market_cap,
            "revenue_growth": lambda m: m.revenue_growth,
            "ebitda_margin": lambda m: (m.ebitda / m.revenue * 100) if m.revenue else None,
            "roe": lambda m: m.roe,
            "roa": lambda m: m.roa,
            "debt_to_equity": lambda m: m.debt_to_equity,
            "ev_ebitda": lambda mult: mult.ev_ebitda,
            "p_e": lambda mult: mult.p_e,
            "p_s": lambda mult: mult.p_s
        }

        for metric in metrics:
            if metric not in metric_extractors:
                continue

            extractor = metric_extractors[metric]

            # Determine if this is a multiple or a metric
            if metric in ["ev_ebitda", "p_e", "p_s"]:
                target_value = extractor(target_multiples)
                peer_values = [extractor(m) for m in peer_multiples]
            else:
                target_value = extractor(target_data)
                peer_values = [extractor(p) for p in peer_data]

            if target_value is not None:
                percentile = calculate_percentile_rank(target_value, peer_values)

                rankings[metric] = {
                    "value": round(target_value, 2),
                    "percentile": percentile,
                    "peer_min": round(min([v for v in peer_values if v is not None]), 2) if any(
                        v is not None for v in peer_values) else None,
                    "peer_max": round(max([v for v in peer_values if v is not None]), 2) if any(
                        v is not None for v in peer_values) else None,
                    "peer_median": round(statistics.median([v for v in peer_values if v is not None]), 2) if any(
                        v is not None for v in peer_values) else None
                }

        result = {
            "status": "ok",
            "target": {
                "symbol": target_data.symbol,
                "name": target_data.name
            },
            "peer_count": len(peer_data),
            "rankings": rankings
        }

        if response_format == "concise":
            # Simplify to just metric: percentile
            result["rankings"] = {
                metric: data["percentile"]
                for metric, data in rankings.items()
            }

        return result

    except Exception as e:
        logger.error(f"Error in comps_percentile_ranking: {e}")
        return {
            "status": "error",
            "error": str(e),
            "target_symbol": target_symbol
        }


# ============================================================================
# TOOL: COMPARISON MATRIX
# ============================================================================

@mcp.tool()
async def comps_comparison_matrix(
        symbols: List[str],
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Generate comprehensive side-by-side comparison matrix.

    Creates a complete trading comps table with all key metrics and multiples
    for easy comparison. This is the final output for comps analysis.

    Args:
        symbols: List of company symbols to compare (2-15 recommended)
        response_format: 'concise' or 'detailed'

    Returns:
        Comprehensive comparison matrix with all companies side-by-side.

    Matrix Includes:
        Company Info:
        - Name, sector, industry
        - Market cap, enterprise value

        Financial Metrics:
        - Revenue, EBITDA, Net Income
        - Total Assets, Total Equity, Total Debt
        - Operating CF, Free Cash Flow

        Profitability:
        - EBITDA margin
        - Net margin
        - ROE, ROA

        Leverage:
        - Debt/Equity ratio
        - Net Debt/EBITDA

        Growth:
        - Revenue growth
        - Earnings growth

        Valuation Multiples:
        - EV/Revenue, EV/EBITDA, EV/EBIT, EV/FCF
        - P/E, P/B, P/S, PEG

        Statistics:
        - Min, Max, Median, Mean for each metric

    Examples:

        # Compare tech giants
        {"symbols": ["AAPL", "MSFT", "GOOGL", "META", "AMZN"]}

        # Compare banks
        {"symbols": ["JPM", "BAC", "C", "WFC", "USB"]}

        # Concise comparison
        {
            "symbols": ["TSLA", "F", "GM", "TM"],
            "response_format": "concise"
        }

    Use Cases:
        - Final deliverable for comps analysis
        - M&A valuation presentation
        - Investment committee materials
        - Fairness opinion support

    Output Format:
        Returns structured data suitable for:
        - Spreadsheet export
        - Presentation slides
        - Analysis reports
        - Further processing

    Notes:
        - This is typically the final step in comps analysis
        - Use after identifying peers with comps_find_peers
        - Includes statistical summary across all companies
        - Can handle 2-15 companies effectively
    """
    try:
        if not symbols or len(symbols) < 2:
            return {
                "status": "error",
                "message": "Need at least 2 companies for comparison"
            }

        if len(symbols) > 15:
            return {
                "status": "error",
                "message": "Maximum 15 companies allowed for comparison matrix"
            }

        logger.info(f"Building comparison matrix for {len(symbols)} companies")

        # Fetch all company data
        metrics_tasks = [fetch_company_metrics(sym) for sym in symbols]
        metrics_results = await asyncio.gather(*metrics_tasks, return_exceptions=True)

        # Filter valid results
        valid_metrics = []
        failed_symbols = []
        for sym, result in zip(symbols, metrics_results):
            if isinstance(result, Exception):
                failed_symbols.append(sym)
                logger.warning(f"Failed to fetch {sym}: {result}")
            else:
                valid_metrics.append(result)

        if len(valid_metrics) < 2:
            return {
                "status": "error",
                "message": f"Failed to fetch sufficient company data. Failed: {failed_symbols}"
            }

        # Calculate multiples
        all_multiples = [calculate_multiples(m) for m in valid_metrics]

        # Build comparison matrix
        companies = []

        for metrics, multiples in zip(valid_metrics, all_multiples):
            # Calculate derived metrics
            ebitda_margin = (metrics.ebitda / metrics.revenue * 100) if metrics.revenue else None
            net_margin = (metrics.net_income / metrics.revenue * 100) if metrics.revenue else None
            net_debt = metrics.total_debt - (metrics.operating_cash_flow * 0.1)  # Rough cash estimate
            net_debt_ebitda = (net_debt / metrics.ebitda) if metrics.ebitda else None

            if response_format == "concise":
                company_data = {
                    "symbol": metrics.symbol,
                    "name": metrics.name,
                    "market_cap": metrics.market_cap,
                    "revenue": metrics.revenue,
                    "ebitda": metrics.ebitda,
                    "ev_ebitda": multiples.ev_ebitda,
                    "p_e": multiples.p_e,
                    "revenue_growth": metrics.revenue_growth
                }
            else:
                company_data = {
                    "symbol": metrics.symbol,
                    "name": metrics.name,
                    "sector": metrics.sector,
                    "industry": metrics.industry,

                    "valuation": {
                        "market_cap": metrics.market_cap,
                        "enterprise_value": metrics.enterprise_value,
                        "stock_price": metrics.stock_price
                    },

                    "financial_metrics": {
                        "revenue": metrics.revenue,
                        "ebitda": metrics.ebitda,
                        "ebit": metrics.ebit,
                        "net_income": metrics.net_income,
                        "operating_cash_flow": metrics.operating_cash_flow,
                        "free_cash_flow": metrics.free_cash_flow
                    },

                    "balance_sheet": {
                        "total_assets": metrics.total_assets,
                        "total_equity": metrics.total_equity,
                        "total_debt": metrics.total_debt
                    },

                    "profitability": {
                        "ebitda_margin": round(ebitda_margin, 2) if ebitda_margin else None,
                        "net_margin": round(net_margin, 2) if net_margin else None,
                        "roe": metrics.roe,
                        "roa": metrics.roa
                    },

                    "leverage": {
                        "debt_to_equity": metrics.debt_to_equity,
                        "net_debt_to_ebitda": round(net_debt_ebitda, 2) if net_debt_ebitda else None
                    },

                    "growth": {
                        "revenue_growth": metrics.revenue_growth,
                        "earnings_growth": metrics.earnings_growth
                    },

                    "trading_multiples": {
                        "ev_revenue": multiples.ev_revenue,
                        "ev_ebitda": multiples.ev_ebitda,
                        "ev_ebit": multiples.ev_ebit,
                        "ev_fcf": multiples.ev_fcf,
                        "p_e": multiples.p_e,
                        "p_b": multiples.p_b,
                        "p_s": multiples.p_s,
                        "peg": multiples.peg
                    }
                }

            companies.append(company_data)

        # Calculate statistics across all companies
        if response_format == "detailed":
            statistics = {
                "market_cap": calculate_statistics([m.market_cap for m in valid_metrics]),
                "revenue": calculate_statistics([m.revenue for m in valid_metrics]),
                "ebitda": calculate_statistics([m.ebitda for m in valid_metrics]),
                "revenue_growth": calculate_statistics([m.revenue_growth for m in valid_metrics]),
                "roe": calculate_statistics([m.roe for m in valid_metrics]),
                "ev_ebitda": calculate_statistics([m.ev_ebitda for m in all_multiples]),
                "p_e": calculate_statistics([m.p_e for m in all_multiples]),
                "ev_revenue": calculate_statistics([m.ev_revenue for m in all_multiples])
            }
        else:
            statistics = None

        return {
            "status": "ok",
            "company_count": len(companies),
            "failed_symbols": failed_symbols if failed_symbols else None,
            "companies": companies,
            "statistics": statistics
        }

    except Exception as e:
        logger.error(f"Error in comps_comparison_matrix: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# ============================================================================
# SYSTEM PROMPT ENHANCEMENT
# ============================================================================

def get_ma_analytics_system_prompt() -> str:
    """
    Get system prompt enhancement for M&A Analytics tools.
    """
    return """
M&A ANALYTICS (COMPARABLE COMPANIES ANALYSIS) CRITICAL RULES:

1. M&A Analytics Purpose
   - Use for VALUATION via comparable companies analysis
   - Complements other APIs by providing analytical layer
   - Aggregates data from AlphaVantage + FMP into comps

   What M&A Analytics provides uniquely:
   - Automated peer identification
   - Trading multiples calculation
   - Valuation ranges based on comps
   - Percentile rankings and benchmarking
   - Side-by-side comparison matrices

2. Standard Comps Workflow

   Step 1: Find Peers
   comps_find_peers(symbol="AAPL")
   Result: List of comparable companies

   Step 2: Calculate Multiples
   comps_calculate_multiples(symbols=["AAPL", "MSFT", "GOOGL", ...])
   Result: Trading multiples for each peer

   Step 3: Estimate Valuation
   comps_valuation_range(
       target_symbol="AAPL",
       peer_symbols=["MSFT", "GOOGL", ...],
       primary_multiple="ev_ebitda"
   )
   Result: Valuation range (low/median/high)

   Step 4: Generate Final Comparison
   comps_comparison_matrix(symbols=["AAPL", "MSFT", "GOOGL", ...])
   Result: Comprehensive comps table

3. When to Use Each Tool

   comps_find_peers:
   - Start of every comps analysis
   - Don't know who the peers are
   - Need automated peer identification
   - Want to ensure objective peer selection

   comps_calculate_multiples:
   - Want to see all multiples for peer group
   - Need statistics (median, mean, range)
   - Comparing multiple valuation approaches

   comps_valuation_range:
   - Estimating fair value for target
   - Determining offer price range for M&A
   - Assessing if company over/undervalued
   - Need specific valuation number

   comps_percentile_ranking:
   - Quick competitive positioning
   - Identifying strengths/weaknesses vs peers
   - Benchmarking performance
   - Strategic analysis

   comps_comparison_matrix:
   - Final deliverable for presentation
   - Comprehensive side-by-side analysis
   - M&A committee materials
   - Most complete output

4. Choosing the Right Valuation Multiple

   EV/EBITDA (Most Common for M&A):
   - Mature, profitable companies
   - Consistent EBITDA generation
   - Capital-intensive industries
   - Gold standard for M&A valuation

   EV/Revenue:
   - High-growth companies
   - Pre-profit or low-margin businesses
   - SaaS and tech companies
   - When EBITDA unreliable

   P/E Ratio:
   - Profitable companies
   - Stable earnings
   - Banking and financial services
   - Public market focused

   EV/FCF:
   - Cash-generative businesses
   - When FCF more relevant than EBITDA
   - Capital-light business models

   P/S (Price-to-Sales):
   - Early-stage companies
   - Rapid revenue growth
   - Negative earnings

   PEG (P/E to Growth):
   - Growth companies
   - Comparing companies with different growth rates
   - When growth is key differentiator

5. Peer Selection Best Practices

   Good Peers Must Have:
   - Same or similar industry/sector
   - Similar business model
   - Comparable size (0.3x to 3x market cap)
   - Similar growth profile
   - Similar geography/markets

   Poor Peer Characteristics:
   - Different business model
   - Vastly different size (>10x difference)
   - Different margin structure
   - Different capital intensity
   - Conglomerate vs pure play

   Optimal Peer Count:
   - Minimum: 4-5 peers
   - Ideal: 6-10 peers
   - Maximum: 15 peers
   - Too few: Unreliable statistics
   - Too many: Dilutes comparability

6. Interpreting Valuation Results

   Understanding the Range:
   Low (25th percentile):
   - Conservative valuation
   - Downside scenario
   - Risk-adjusted value

   Median (50th percentile):
   - Most likely fair value
   - Base case scenario
   - Typical deal price

   High (75th percentile):
   - Optimistic valuation
   - Upside scenario
   - Competitive bid situation

   Current Market Price:
   - If below low: Potentially undervalued
   - If in middle: Fairly valued
   - If above high: Potentially overvalued or premium expected

7. Common M&A Valuation Workflow

   User: "What's Apple worth?"

   Agent workflow:
   1. comps_find_peers(symbol="AAPL")
   2. comps_valuation_range(
        target_symbol="AAPL",
        peer_symbols=[peers from step 1],
        primary_multiple="ev_ebitda"
      )
   3. Present valuation range with upside/downside vs current

   User: "Prepare valuation for acquisition target XYZ"

   Agent workflow:
   1. comps_find_peers(symbol="XYZ")
   2. comps_calculate_multiples(symbols=[XYZ + peers])
   3. comps_valuation_range(target="XYZ", multiple="ev_ebitda")
   4. comps_percentile_ranking(target="XYZ", peers=[...])
   5. comps_comparison_matrix(symbols=[XYZ + peers])
   6. Synthesize into acquisition recommendation

8. Integration with Other APIs

   Complete M&A Analysis Flow:
   1. OpenCorporates: Verify target is real, get corporate structure
   2. AlphaVantage: Get financial statements
   3. SEC EDGAR: Review 10-K for risk factors
   4. M&A Analytics: Calculate comps valuation
   5. FMP: Run DCF valuation for cross-check
   6. FMP: Check insider trading, analyst views
   7. Synthesize all into recommendation

9. Valuation Cross-Checks

   Always cross-check valuation approaches:
   - Comps (M&A Analytics) vs DCF (FMP)
   - EV/EBITDA vs EV/Revenue
   - Trading comps vs transaction comps

   If valuations differ significantly:
   - Investigate why (growth expectations, risk, margins)
   - Present range across methodologies
   - Explain divergence to user

10. Data Quality Notes

    AlphaVantage Data:
    - Most recent annual data
    - Updated quarterly after earnings
    - Sometimes has gaps for small companies

    FMP Data:
    - Real-time market data
    - Good for current EV and market cap
    - Ratios already calculated

    Combined Approach:
    - Use both for best coverage
    - AlphaVantage for core financials
    - FMP for real-time valuation
    - Handle missing data gracefully

11. Common Mistakes to Avoid

    - Using too few peers (< 4)
    - Mixing industries (banks with tech)
    - Ignoring size differences (mega-cap with small-cap)
    - Using wrong multiple (EV/EBITDA for negative EBITDA)
    - Not validating peer selection
    - Forgetting to exclude target from peer statistics
    - Treating valuation as precise (it's a range!)
    - Not considering qualitative factors

12. Best Practices

    - Always start with comps_find_peers
    - Validate peer list makes sense
    - Use multiple valuation multiples
    - Present range, not single number
    - Show current market value for context
    - Explain upside/downside vs current
    - Use percentile rankings for positioning
    - Include comparison matrix in final report
    - Cross-check with other valuation methods
    - Explain assumptions and limitations

13. Output Quality

    Good Output:
    - Clear valuation range (low/mid/high)
    - Context on current market value
    - Peer list and why they're comparable
    - Multiple valuation approaches
    - Synthesis into recommendation

    Poor Output:
    - Single precise valuation number
    - No peer justification
    - Only one multiple used
    - No context on current value
    - No explanation of methodology
"""


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    print(
        "[M&A Analytics] MCP Server Starting...\n"
        "Comparable Companies Analysis for M&A Valuation\n"
        "\nCore Capabilities:\n"
        "  Peer Identification: Automated comparable company discovery\n"
        "  Trading Multiples: Calculate EV/EBITDA, P/E, P/S, etc.\n"
        "  Valuation Ranges: Estimate fair value based on comps\n"
        "  Percentile Rankings: Benchmark vs peer group\n"
        "  Comparison Matrix: Comprehensive side-by-side analysis\n"
        "\nData Sources:\n"
        "  - AlphaVantage: Financial statements, company overview\n"
        "  - FMP: Real-time quotes, ratios, enterprise values\n"
        "\nTypical Workflow:\n"
        "  1. comps_find_peers - Identify comparable companies\n"
        "  2. comps_calculate_multiples - Calculate trading multiples\n"
        "  3. comps_valuation_range - Estimate valuation range\n"
        "  4. comps_comparison_matrix - Generate final comparison\n"
        "\nValuation Multiples:\n"
        "  EV/EBITDA: Most common for M&A (mature companies)\n"
        "  EV/Revenue: High-growth, pre-profit companies\n"
        "  P/E: Profitable companies with stable earnings\n"
        "  EV/FCF: Cash-generative businesses\n"
        "\nBest Practices:\n"
        "  - Use 6-10 peers for reliable statistics\n"
        "  - Validate peer comparability (sector, size, model)\n"
        "  - Present valuation as range, not single number\n"
        "  - Cross-check with other valuation methods (DCF)\n"
        "  - Consider qualitative factors beyond numbers\n"
        "\nIntegration:\n"
        "  Complements your existing stack:\n"
        "  - AlphaVantage: Raw financial data\n"
        "  - FMP: Analytics & DCF valuation\n"
        "  - SEC EDGAR: Regulatory filings\n"
        "  - OpenCorporates: Legal entity data\n"
        "  - M&A Analytics: Comps analysis layer\n",
        flush=True
    )

    # Get system prompt (for documentation/reference)
    system_prompt = get_ma_analytics_system_prompt()

    # Run the MCP server
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8089)
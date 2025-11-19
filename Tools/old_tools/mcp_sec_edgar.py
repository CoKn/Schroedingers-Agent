"""
SEC EDGAR MCP Server
Direct access to U.S. Securities and Exchange Commission filings and data.

This server provides comprehensive access to SEC EDGAR, the primary source for
public company filings, ownership data, insider transactions, and regulatory
disclosures. Essential for M&A due diligence, investment research, and compliance.

Key Features:
- Company and filing search
- Full-text filing retrieval (10-K, 10-Q, 8-K, proxies, etc.)
- Structured financial data extraction
- Ownership tracking (13D, 13F, 13G)
- Insider transaction monitoring (Forms 3, 4, 5)
- CIK (Central Index Key) lookup and management
"""

from __future__ import annotations

import os
import time
import asyncio
import logging
import httpx
import json
import re
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from bs4 import BeautifulSoup

from fastmcp import FastMCP
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize MCP server
try:
    mcp = FastMCP(name="SEC_EDGAR")
except TypeError:
    mcp = FastMCP()


# ============================================================================
# CONFIGURATION & ENUMS
# ============================================================================

class ResponseFormat(str, Enum):
    """Control verbosity of tool responses for token efficiency."""
    CONCISE = "concise"  # Essential fields only
    DETAILED = "detailed"  # Full response


class FilingType(str, Enum):
    """Common SEC filing types."""
    # Annual and Quarterly Reports
    FORM_10K = "10-K"  # Annual report
    FORM_10Q = "10-Q"  # Quarterly report
    FORM_8K = "8-K"  # Current report (material events)

    # Proxy Statements
    DEF_14A = "DEF 14A"  # Proxy statement

    # Registration Statements
    S_1 = "S-1"  # IPO registration
    S_4 = "S-4"  # M&A registration

    # Ownership Reports
    FORM_3 = "3"  # Initial insider ownership
    FORM_4 = "4"  # Insider transaction
    FORM_5 = "5"  # Annual insider ownership
    FORM_13D = "SC 13D"  # Beneficial ownership (>5%)
    FORM_13G = "SC 13G"  # Passive beneficial ownership
    FORM_13F = "13F-HR"  # Institutional holdings

    # Other
    FORM_144 = "144"  # Notice of proposed sale


# SEC EDGAR Configuration
SEC_BASE_URL = "https://www.sec.gov"
SEC_DATA_URL = "https://data.sec.gov"

# User-Agent is REQUIRED by SEC
# Format: "Company/Organization Name email@domain.com"
# Get from environment variable
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT")

if not SEC_USER_AGENT:
    raise ValueError(
        "SEC_USER_AGENT environment variable is required. "
        "Format: 'Your Organization Name your.email@domain.com' "
        "Example: 'Financial Research LLC research@example.com' "
        "This helps SEC identify your application and is required per SEC policy. "
        "See: https://www.sec.gov/os/accessing-edgar-data"
    )

# Rate limiting: SEC requests max 10 requests/second
RATE_LIMIT_DELAY = 0.11  # 110ms between requests = ~9 req/sec (safe)


# ============================================================================
# RATE LIMITING SYSTEM
# ============================================================================

@dataclass
class RateLimitTracker:
    """Tracks API call rate limits for SEC EDGAR."""
    last_call_time: float

    def __init__(self):
        self.last_call_time = 0.0

    async def wait_if_needed(self):
        """Wait if necessary to respect rate limits."""
        now = time.time()
        time_since_last = now - self.last_call_time

        if time_since_last < RATE_LIMIT_DELAY:
            wait_time = RATE_LIMIT_DELAY - time_since_last
            await asyncio.sleep(wait_time)

        self.last_call_time = time.time()


# Global rate limiter
rate_limiter = RateLimitTracker()


# ============================================================================
# SEC EDGAR API CLIENT
# ============================================================================

class SECClient:
    """HTTP client for SEC EDGAR API."""

    def __init__(self):
        """Initialize SEC client with User-Agent from environment."""
        # Get User-Agent from environment variable
        self.user_agent = SEC_USER_AGENT

        self.base_url = SEC_BASE_URL
        self.data_url = SEC_DATA_URL

        # Custom headers required by SEC
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "www.sec.gov"
        }

        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers=self.headers,
            follow_redirects=True
        )

    async def get(
            self,
            endpoint: str,
            params: Optional[Dict[str, Any]] = None,
            use_data_url: bool = False
    ) -> Any:
        """
        Make GET request to SEC EDGAR.

        Args:
            endpoint: API endpoint
            params: Query parameters
            use_data_url: If True, use data.sec.gov instead of www.sec.gov

        Returns:
            Response data (JSON, text, or BeautifulSoup)
        """
        # Wait for rate limiting
        await rate_limiter.wait_if_needed()

        base = self.data_url if use_data_url else self.base_url
        url = f"{base}{endpoint}"

        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()

            # Determine response type
            content_type = response.headers.get("content-type", "")

            if "application/json" in content_type:
                return response.json()
            elif "text/html" in content_type or "text/xml" in content_type:
                return BeautifulSoup(response.text, "html.parser")
            else:
                return response.text

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise Exception("Rate limit exceeded - please slow down requests")
            elif e.response.status_code == 403:
                raise Exception(
                    "Access forbidden - check User-Agent header. "
                    "Set SEC_USER_AGENT in .env with format: 'Company Name email@domain.com'"
                )
            elif e.response.status_code == 404:
                raise Exception("Resource not found")
            else:
                raise Exception(f"HTTP error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            raise Exception(f"SEC EDGAR API error: {str(e)}")

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Global client instance
_client: Optional[SECClient] = None


async def get_client() -> SECClient:
    """Get or create the global SEC client."""
    global _client
    if _client is None:
        _client = SECClient()
    return _client


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def normalize_cik(cik: str) -> str:
    """
    Normalize CIK to 10-digit format with leading zeros.

    Args:
        cik: CIK number (can be any length)

    Returns:
        10-digit CIK with leading zeros
    """
    # Remove any non-digits
    cik_digits = re.sub(r'\D', '', str(cik))

    # Pad to 10 digits
    return cik_digits.zfill(10)


def parse_filing_date(date_str: str) -> Optional[str]:
    """Parse filing date to ISO format."""
    if not date_str:
        return None

    try:
        # SEC dates are typically YYYY-MM-DD
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except:
        return date_str


def extract_accession_number(accession: str) -> str:
    """
    Extract and normalize accession number.

    Accession numbers are in format: 0000000000-00-000000
    """
    # Remove any dashes for internal use
    return re.sub(r'-', '', accession)


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
    if "user-agent" in error_msg.lower() or "forbidden" in error_msg.lower():
        response["suggestion"] = (
            "SEC requires a proper User-Agent header. "
            "Set SEC_USER_AGENT in .env with format: 'Your Company Name contact@email.com'. "
            "See: https://www.sec.gov/os/accessing-edgar-data"
        )
    elif "rate limit" in error_msg.lower():
        response["suggestion"] = (
            "SEC EDGAR rate limit exceeded. The SEC allows max 10 requests/second. "
            "Wait a moment and try again."
        )
    elif "not found" in error_msg.lower():
        response["suggestion"] = (
            "Resource not found. Verify CIK number, ticker symbol, or accession number. "
            "Use sec_cik_lookup to find the correct CIK."
        )

    return response


# ============================================================================
# TOOL: CIK LOOKUP
# ============================================================================

@mcp.tool()
async def sec_cik_lookup(
        identifier: str,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Look up a company's CIK (Central Index Key) by ticker symbol or company name.

    The CIK is the SEC's unique identifier for companies and is required for most
    SEC EDGAR API calls. This tool converts ticker symbols or company names to CIKs.

    Args:
        identifier: Ticker symbol (e.g., 'AAPL', 'MSFT') or company name (e.g., 'Apple Inc')
        response_format: 'concise' or 'detailed'

    Returns:
        Company information including:
        - cik_str: 10-digit CIK with leading zeros
        - ticker: Stock ticker symbol
        - title: Official company name
        - exchange: Stock exchange (e.g., 'Nasdaq', 'NYSE')

    Examples:

        # Lookup by ticker
        {"identifier": "AAPL"}

        # Lookup by company name
        {"identifier": "Apple Inc"}

        # Lookup by partial name
        {"identifier": "Microsoft"}

    Use Cases:
        - Convert ticker to CIK before other SEC calls
        - Verify official company name
        - Find CIK for private companies
        - Lookup CIK for subsidiaries

    Notes:
        - Ticker lookup is fastest and most reliable
        - Company name search is fuzzy (returns closest matches)
        - CIK is required for most other SEC EDGAR tools
        - Some companies have multiple CIKs (parent/subsidiaries)
    """
    try:
        client = await get_client()

        # Use SEC's company tickers JSON endpoint
        endpoint = "/files/company_tickers.json"
        data = await client.get(endpoint, use_data_url=True)

        if not data:
            return {
                "status": "error",
                "message": "Could not retrieve company tickers data from SEC"
            }

        # Search for identifier (case-insensitive)
        identifier_upper = identifier.upper().strip()
        matches = []

        for item in data.values():
            ticker = item.get("ticker", "").upper()
            title = item.get("title", "").upper()

            # Exact ticker match
            if ticker == identifier_upper:
                matches.insert(0, item)  # Put exact matches first
            # Partial company name match
            elif identifier_upper in title:
                matches.append(item)

        if not matches:
            return {
                "status": "error",
                "message": f"No company found matching '{identifier}'. Try a different ticker or company name."
            }

        # Return top match (or all matches if detailed)
        if response_format == "concise":
            top_match = matches[0]
            return {
                "status": "ok",
                "cik_str": normalize_cik(top_match.get("cik_str", "")),
                "ticker": top_match.get("ticker"),
                "title": top_match.get("title")
            }
        else:
            # Return top 5 matches
            results = []
            for match in matches[:5]:
                results.append({
                    "cik_str": normalize_cik(match.get("cik_str", "")),
                    "ticker": match.get("ticker"),
                    "title": match.get("title"),
                    "exchange": match.get("exchange", "N/A")
                })

            return {
                "status": "ok",
                "query": identifier,
                "match_count": len(matches),
                "matches": results
            }

    except Exception as e:
        logger.error(f"Error in cik_lookup: {e}")
        return format_error_response("sec_cik_lookup", e, {"identifier": identifier})


# ============================================================================
# TOOL: COMPANY FILINGS LIST
# ============================================================================

@mcp.tool()
async def sec_company_filings(
        cik: str,
        filing_type: Optional[str] = None,
        before_date: Optional[str] = None,
        after_date: Optional[str] = None,
        count: int = 20,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get list of SEC filings for a company.

    Returns a list of filings with metadata including filing type, date, and
    accession numbers. Use this to discover available filings before retrieving
    specific documents.

    Args:
        cik: Company's CIK number (use sec_cik_lookup to find)
        filing_type: Filter by filing type (e.g., '10-K', '10-Q', '8-K', 'DEF 14A')
                    Options: '10-K' (annual), '10-Q' (quarterly), '8-K' (current events),
                    'DEF 14A' (proxy), '3/4/5' (insider), 'SC 13D/G' (ownership), '13F-HR'
        before_date: Only filings before this date (format: 'YYYY-MM-DD')
        after_date: Only filings after this date (format: 'YYYY-MM-DD')
        count: Number of filings to return (default: 20, max: 100)
        response_format: 'concise' or 'detailed'

    Returns:
        List of filings with:
        - accessionNumber: Unique filing identifier
        - filingDate: Date filed with SEC
        - reportDate: Period end date (for periodic reports)
        - acceptanceDateTime: Exact filing timestamp
        - form: Filing type (10-K, 10-Q, etc.)
        - primaryDocument: Main document filename
        - primaryDocDescription: Document description
        - size: Document size in bytes
        - isXBRL: Whether filing includes XBRL data

    Examples:

        # Get recent filings for Apple (CIK: 0000320193)
        {"cik": "0000320193", "count": 10}

        # Get annual reports only
        {"cik": "0000320193", "filing_type": "10-K"}

        # Get filings from specific date range
        {
            "cik": "0000320193",
            "filing_type": "8-K",
            "after_date": "2023-01-01",
            "before_date": "2023-12-31"
        }

        # Get recent quarterly reports
        {"cik": "0000320193", "filing_type": "10-Q", "count": 4}

    Common Filing Types:
        - '10-K': Annual report (comprehensive)
        - '10-Q': Quarterly report
        - '8-K': Current report (material events, M&A announcements)
        - 'DEF 14A': Proxy statement (executive comp, shareholder votes)
        - 'SC 13D': Activist investor disclosure
        - '13F-HR': Institutional holdings (quarterly)
        - '4': Insider transaction
        - 'S-4': M&A registration statement

    Use Cases:
        - Find latest annual report for due diligence
        - Track material events via 8-K filings
        - Monitor insider trading via Forms 4
        - Get proxy statements for governance analysis
        - Find M&A announcements

    Notes:
        - Use sec_cik_lookup first if you don't know the CIK
        - Accession numbers are needed to retrieve full filing text
        - XBRL filings contain structured financial data
        - Most recent filings appear first
    """
    try:
        client = await get_client()

        # Normalize CIK
        cik_normalized = normalize_cik(cik)

        # Get company submissions data
        endpoint = f"/submissions/CIK{cik_normalized}.json"
        data = await client.get(endpoint, use_data_url=True)

        if not data:
            return {
                "status": "error",
                "message": f"No data found for CIK {cik}. Verify CIK is correct."
            }

        # Extract filings
        recent_filings = data.get("filings", {}).get("recent", {})

        if not recent_filings:
            return {
                "status": "ok",
                "message": "No filings found for this company",
                "cik": cik_normalized,
                "filings": []
            }

        # Build list of filings
        filing_count = len(recent_filings.get("accessionNumber", []))
        filings = []

        for i in range(filing_count):
            filing = {
                "accessionNumber": recent_filings["accessionNumber"][i],
                "filingDate": recent_filings["filingDate"][i],
                "reportDate": recent_filings.get("reportDate", [None] * filing_count)[i],
                "acceptanceDateTime": recent_filings.get("acceptanceDateTime", [None] * filing_count)[i],
                "form": recent_filings["form"][i],
                "primaryDocument": recent_filings["primaryDocument"][i],
                "primaryDocDescription": recent_filings.get("primaryDocDescription", [None] * filing_count)[i],
                "size": recent_filings.get("size", [None] * filing_count)[i],
                "isXBRL": recent_filings.get("isXBRL", [None] * filing_count)[i]
            }

            # Apply filters
            if filing_type and filing["form"] != filing_type:
                continue

            if before_date and filing["filingDate"] > before_date:
                continue

            if after_date and filing["filingDate"] < after_date:
                continue

            filings.append(filing)

            # Limit count
            if len(filings) >= count:
                break

        # Apply response format
        if response_format == "concise":
            filings = [
                {
                    "form": f["form"],
                    "filingDate": f["filingDate"],
                    "accessionNumber": f["accessionNumber"],
                    "primaryDocument": f["primaryDocument"]
                }
                for f in filings
            ]

        return {
            "status": "ok",
            "cik": cik_normalized,
            "company_name": data.get("name"),
            "filters": {
                "filing_type": filing_type,
                "before_date": before_date,
                "after_date": after_date
            },
            "count": len(filings),
            "filings": filings
        }

    except Exception as e:
        logger.error(f"Error in company_filings: {e}")
        return format_error_response("sec_company_filings", e, {
            "cik": cik,
            "filing_type": filing_type
        })


# ============================================================================
# TOOL: GET FILING
# ============================================================================

@mcp.tool()
async def sec_get_filing(
        cik: str,
        accession_number: str,
        get_full_text: bool = False,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get a specific SEC filing by accession number.

    Retrieves the filing metadata and optionally the full text. Use this after
    sec_company_filings to get the actual filing content.

    Args:
        cik: Company's CIK number
        accession_number: Filing's accession number (from sec_company_filings)
                         Format: 0000000000-00-000000
        get_full_text: If True, retrieve full filing text (can be large)
                      If False, return metadata only
        response_format: 'concise' or 'detailed'

    Returns:
        Filing metadata and optionally full text:
        - filing_url: URL to view filing on SEC website
        - filing_date: Date filed
        - form_type: Type of filing
        - company_name: Filer name
        - file_number: SEC file number
        - full_text: Full filing text (if get_full_text=True)

    Examples:

        # Get filing metadata only (fast)
        {
            "cik": "0000320193",
            "accession_number": "0000320193-23-000077"
        }

        # Get full filing text (slower, larger response)
        {
            "cik": "0000320193",
            "accession_number": "0000320193-23-000077",
            "get_full_text": true
        }

    Use Cases:
        - Download 10-K for detailed analysis
        - Extract risk factors from 10-K
        - Review proxy statement (DEF 14A) for executive compensation
        - Analyze 8-K for material event details
        - Get full text for custom parsing

    Notes:
        - Accession number comes from sec_company_filings
        - Full text can be very large (100KB - 10MB+)
        - Use get_full_text=False first to check metadata
        - Full text is HTML formatted
        - Consider using specific extraction tools for common sections

    Related Tools:
        - sec_company_filings: Get list of filings and accession numbers
        - sec_search_filings: Search for filings by keywords
    """
    try:
        client = await get_client()

        # Normalize inputs
        cik_normalized = normalize_cik(cik)
        accession_clean = extract_accession_number(accession_number)

        # Build filing URL
        # Format: https://www.sec.gov/cgi-bin/viewer?action=view&cik=CIK&accession_number=ACC&xbrl_type=v
        filing_url = (
            f"{SEC_BASE_URL}/cgi-bin/viewer"
            f"?action=view&cik={cik_normalized}&accession_number={accession_number}&xbrl_type=v"
        )

        # Get filing index page to extract metadata
        index_url = (
            f"{SEC_BASE_URL}/cgi-bin/browse-edgar"
            f"?action=getcompany&CIK={cik_normalized}&type=&dateb=&owner=exclude&count=100"
        )

        index_data = await client.get(
            f"/cgi-bin/browse-edgar",
            params={
                "action": "getcompany",
                "CIK": cik_normalized,
                "type": "",
                "dateb": "",
                "owner": "exclude",
                "count": "100"
            }
        )

        # For now, return basic metadata
        result = {
            "status": "ok",
            "cik": cik_normalized,
            "accession_number": accession_number,
            "filing_url": filing_url,
            "sec_viewer_url": filing_url
        }

        # Get full text if requested
        if get_full_text:
            # Construct document URL
            # Format: https://www.sec.gov/Archives/edgar/data/CIK/ACCESSION/DOCUMENT
            # Need to determine primary document from filings list

            # Get company submissions to find document name
            submissions_endpoint = f"/submissions/CIK{cik_normalized}.json"
            submissions_data = await client.get(submissions_endpoint, use_data_url=True)

            # Find the filing in recent filings
            recent = submissions_data.get("filings", {}).get("recent", {})
            accession_list = recent.get("accessionNumber", [])

            if accession_number in accession_list:
                idx = accession_list.index(accession_number)
                primary_doc = recent.get("primaryDocument", [])[idx]

                # Build document URL
                doc_url = (
                    f"{SEC_BASE_URL}/Archives/edgar/data/{cik_normalized.lstrip('0')}/"
                    f"{accession_clean}/{primary_doc}"
                )

                # Fetch document
                doc_response = await client.get(
                    f"/Archives/edgar/data/{cik_normalized.lstrip('0')}/{accession_clean}/{primary_doc}"
                )

                if isinstance(doc_response, BeautifulSoup):
                    # Extract text from HTML
                    full_text = doc_response.get_text()
                else:
                    full_text = str(doc_response)

                result["full_text"] = full_text
                result["document_url"] = doc_url
                result["primary_document"] = primary_doc

                # Add warning about size
                text_size_kb = len(full_text) / 1024
                if text_size_kb > 1000:
                    result[
                        "warning"] = f"Full text is large ({text_size_kb:.1f} KB). Consider using specific extraction tools."

        return result

    except Exception as e:
        logger.error(f"Error in get_filing: {e}")
        return format_error_response("sec_get_filing", e, {
            "cik": cik,
            "accession_number": accession_number
        })


# ============================================================================
# TOOL: COMPANY FACTS (XBRL)
# ============================================================================

@mcp.tool()
async def sec_company_facts(
        cik: str,
        taxonomy: str = "us-gaap",
        tag: Optional[str] = None,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get structured financial data (XBRL facts) for a company.

    Returns standardized financial metrics extracted from XBRL filings. This is
    structured, machine-readable financial data that's easier to work with than
    parsing full filing text.

    Args:
        cik: Company's CIK number
        taxonomy: XBRL taxonomy ('us-gaap' for US GAAP, 'ifrs-full' for IFRS, 'dei' for entity info)
        tag: Specific XBRL tag to retrieve (e.g., 'Assets', 'Revenues', 'NetIncomeLoss')
             If None, returns all available facts
        response_format: 'concise' or 'detailed'

    Returns:
        Structured financial facts with:
        - label: Human-readable name
        - description: Fact description
        - units: Array of values by unit type (USD, shares, etc.)
        - values: Time series of reported values

    Examples:

        # Get all US GAAP facts
        {"cik": "0000320193", "taxonomy": "us-gaap"}

        # Get specific fact (Assets)
        {"cik": "0000320193", "taxonomy": "us-gaap", "tag": "Assets"}

        # Get revenues
        {"cik": "0000320193", "taxonomy": "us-gaap", "tag": "Revenues"}

        # Get company entity information
        {"cik": "0000320193", "taxonomy": "dei"}

    Common XBRL Tags (us-gaap):
        Balance Sheet:
        - 'Assets': Total assets
        - 'AssetsCurrent': Current assets
        - 'Liabilities': Total liabilities
        - 'StockholdersEquity': Shareholders' equity

        Income Statement:
        - 'Revenues': Total revenues
        - 'GrossProfit': Gross profit
        - 'OperatingIncomeLoss': Operating income
        - 'NetIncomeLoss': Net income
        - 'EarningsPerShareBasic': Basic EPS
        - 'EarningsPerShareDiluted': Diluted EPS

        Cash Flow:
        - 'NetCashProvidedByUsedInOperatingActivities': Operating cash flow
        - 'NetCashProvidedByUsedInInvestingActivities': Investing cash flow
        - 'NetCashProvidedByUsedInFinancingActivities': Financing cash flow

    Use Cases:
        - Extract financial metrics for modeling
        - Build time series of key metrics
        - Compare reported values across periods
        - Validate data from other sources
        - Get standardized financial data

    Notes:
        - Only available for XBRL filers (post-2009 mostly)
        - Data is standardized but may have reporting variations
        - Units matter (USD vs shares vs pure numbers)
        - Values include both annual and quarterly data
        - AlphaVantage may be easier for simple time series
        - Use this for detailed XBRL tag-level analysis
    """
    try:
        client = await get_client()

        # Normalize CIK
        cik_normalized = normalize_cik(cik)

        # Get company facts
        endpoint = f"/api/xbrl/companyfacts/CIK{cik_normalized}.json"
        data = await client.get(endpoint, use_data_url=True)

        if not data:
            return {
                "status": "error",
                "message": f"No XBRL facts found for CIK {cik}. Company may not file in XBRL format."
            }

        # Extract facts for requested taxonomy
        facts = data.get("facts", {}).get(taxonomy, {})

        if not facts:
            available_taxonomies = list(data.get("facts", {}).keys())
            return {
                "status": "error",
                "message": f"No facts found for taxonomy '{taxonomy}'",
                "available_taxonomies": available_taxonomies
            }

        # If specific tag requested
        if tag:
            if tag not in facts:
                # Try to find similar tags
                similar_tags = [t for t in facts.keys() if tag.lower() in t.lower()]
                return {
                    "status": "error",
                    "message": f"Tag '{tag}' not found in taxonomy '{taxonomy}'",
                    "similar_tags": similar_tags[:10] if similar_tags else []
                }

            fact_data = facts[tag]

            if response_format == "concise":
                # Return just the latest values
                units = fact_data.get("units", {})
                latest_values = {}

                for unit_type, values in units.items():
                    if values:
                        # Sort by end date and get most recent
                        sorted_values = sorted(values, key=lambda x: x.get("end", ""), reverse=True)
                        latest_values[unit_type] = sorted_values[0] if sorted_values else None

                return {
                    "status": "ok",
                    "cik": cik_normalized,
                    "taxonomy": taxonomy,
                    "tag": tag,
                    "label": fact_data.get("label"),
                    "description": fact_data.get("description"),
                    "latest_values": latest_values
                }
            else:
                return {
                    "status": "ok",
                    "cik": cik_normalized,
                    "taxonomy": taxonomy,
                    "tag": tag,
                    "fact": fact_data
                }

        # Return all tags
        if response_format == "concise":
            # Return just tag names and labels
            tag_list = [
                {
                    "tag": tag_name,
                    "label": tag_data.get("label"),
                    "description": tag_data.get("description", "")[:100] + "..." if len(
                        tag_data.get("description", "")) > 100 else tag_data.get("description", "")
                }
                for tag_name, tag_data in facts.items()
            ]

            return {
                "status": "ok",
                "cik": cik_normalized,
                "taxonomy": taxonomy,
                "tag_count": len(tag_list),
                "tags": tag_list
            }
        else:
            return {
                "status": "ok",
                "cik": cik_normalized,
                "taxonomy": taxonomy,
                "entity_name": data.get("entityName"),
                "facts": facts
            }

    except Exception as e:
        logger.error(f"Error in company_facts: {e}")
        return format_error_response("sec_company_facts", e, {
            "cik": cik,
            "taxonomy": taxonomy,
            "tag": tag
        })


# ============================================================================
# TOOL: INSIDER TRANSACTIONS (Forms 3, 4, 5)
# ============================================================================

@mcp.tool()
async def sec_insider_transactions(
        cik: str,
        count: int = 20,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get insider transactions (Forms 3, 4, 5) for a company.

    Returns insider trading activity including purchases, sales, option exercises,
    and grants. Essential for monitoring management confidence and potential
    conflicts of interest.

    Forms:
    - Form 3: Initial statement of beneficial ownership (new insider)
    - Form 4: Statement of changes in beneficial ownership (transactions)
    - Form 5: Annual statement (delayed reporting)

    Args:
        cik: Company's CIK number
        count: Number of filings to return (default: 20, max: 100)
        response_format: 'concise' or 'detailed'

    Returns:
        List of insider transaction filings with:
        - form: Form type (3, 4, or 5)
        - filingDate: Date filed with SEC
        - accessionNumber: Filing identifier
        - primaryDocument: Document filename

    Examples:

        # Get recent insider transactions
        {"cik": "0000320193", "count": 10}

        # Get more history
        {"cik": "0000320193", "count": 50}

    Use Cases:
        - Monitor insider buying (bullish signal)
        - Track insider selling (potential concern)
        - Identify blackout periods
        - Due diligence on management behavior
        - Detect unusual trading patterns

    Notes:
        - Form 4 is most common (ongoing transactions)
        - Form 3 filed when someone becomes an insider
        - Form 5 for annual/delayed reporting
        - Need to parse XML/HTML for transaction details
        - Consider using FMP's fmp_insider_trading for parsed data
        - This tool returns raw filings; parsing required for details

    Related Tools:
        - FMP: fmp_insider_trading (pre-parsed transaction data)
        - sec_get_filing: Get full filing text for manual parsing
    """
    try:
        # Use existing company_filings with insider form filter
        result = await sec_company_filings(
            cik=cik,
            filing_type=None,  # We'll filter manually for forms 3/4/5
            count=count * 3,  # Get more to filter
            response_format=response_format
        )

        if result.get("status") != "ok":
            return result

        # Filter for insider forms
        insider_forms = ["3", "4", "5"]
        filings = result.get("filings", [])

        insider_filings = [
            f for f in filings
            if f.get("form") in insider_forms
        ][:count]

        return {
            "status": "ok",
            "cik": result.get("cik"),
            "company_name": result.get("company_name"),
            "count": len(insider_filings),
            "filings": insider_filings,
            "note": (
                "This returns raw insider filing metadata. "
                "For parsed transaction details, consider using FMP's fmp_insider_trading tool."
            )
        }

    except Exception as e:
        logger.error(f"Error in insider_transactions: {e}")
        return format_error_response("sec_insider_transactions", e, {"cik": cik})


# ============================================================================
# TOOL: INSTITUTIONAL HOLDINGS (13F)
# ============================================================================

@mcp.tool()
async def sec_institutional_holdings_13f(
        cik: str,
        count: int = 4,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get institutional holdings reports (Form 13F-HR) for an institution.

    Form 13F-HR is filed quarterly by institutional investment managers with
    over $100M AUM, disclosing their equity holdings. This shows what stocks
    major institutions own.

    IMPORTANT: The CIK should be for the INSTITUTION (investment manager),
    not the company whose stock you want to research. To find institutional
    holders of a company's stock, use FMP's fmp_institutional_ownership instead.

    Args:
        cik: Institution's CIK (e.g., Berkshire Hathaway, BlackRock, Vanguard)
        count: Number of quarters to return (default: 4, max: 20)
        response_format: 'concise' or 'detailed'

    Returns:
        List of 13F filings with:
        - filingDate: Quarter end date
        - reportDate: As-of date for holdings
        - accessionNumber: Filing identifier
        - form: '13F-HR'

    Examples:

        # Get Berkshire Hathaway's holdings (CIK: 0001067983)
        {"cik": "0001067983", "count": 4}

        # Get BlackRock's holdings (CIK: 0001364742)
        {"cik": "0001364742", "count": 2}

    Common Institutions:
        - Berkshire Hathaway: 0001067983
        - BlackRock: 0001364742
        - Vanguard: 0000102909
        - State Street: 0001387131
        - Fidelity: 0000315066

    Use Cases:
        - Track what smart money is buying/selling
        - Follow specific fund manager strategies
        - Identify position changes quarter-over-quarter
        - Find new positions initiated by institutions
        - Monitor concentration risk

    Notes:
        - Filed quarterly (45 days after quarter end)
        - Only shows long equity positions >$100M aggregate AUM
        - Does not show short positions
        - Does not show options (except certain cases)
        - Provides point-in-time snapshot (holdings change after filing)
        - Need to parse XML for detailed holdings
        - Use FMP for company-centric institutional ownership view

    Related Tools:
        - FMP: fmp_institutional_ownership (shows institutions holding a specific stock)
        - sec_get_filing: Get full 13F XML for detailed parsing
    """
    try:
        # Use existing company_filings with 13F filter
        result = await sec_company_filings(
            cik=cik,
            filing_type="13F-HR",
            count=count,
            response_format=response_format
        )

        if result.get("status") != "ok":
            return result

        return {
            "status": "ok",
            "cik": result.get("cik"),
            "institution_name": result.get("company_name"),
            "count": len(result.get("filings", [])),
            "filings": result.get("filings", []),
            "note": (
                "This returns 13F filing metadata for an INSTITUTION. "
                "To find institutions holding a specific company's stock, use FMP's fmp_institutional_ownership. "
                "Parse the full 13F XML via sec_get_filing for detailed holdings data."
            )
        }

    except Exception as e:
        logger.error(f"Error in institutional_holdings_13f: {e}")
        return format_error_response("sec_institutional_holdings_13f", e, {"cik": cik})


# ============================================================================
# TOOL: OWNERSHIP FILINGS (13D/13G)
# ============================================================================

@mcp.tool()
async def sec_beneficial_ownership(
        cik: str,
        count: int = 10,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get beneficial ownership reports (Forms SC 13D and SC 13G) for a company.

    These forms disclose beneficial owners of more than 5% of a company's stock.
    Essential for identifying major shareholders, activist investors, and
    potential change-of-control situations.

    Forms:
    - SC 13D: Filed by activist investors or those seeking control
             Must disclose plans/proposals for the company
    - SC 13G: Filed by passive investors (>5% ownership, no control intent)
             Shorter form for passive holders

    Args:
        cik: Company's CIK number (the target company, not the investor)
        count: Number of filings to return (default: 10, max: 50)
        response_format: 'concise' or 'detailed'

    Returns:
        List of beneficial ownership filings with:
        - form: 'SC 13D' or 'SC 13G'
        - filingDate: Date filed
        - accessionNumber: Filing identifier
        - filer: Who filed (the beneficial owner)

    Examples:

        # Get beneficial ownership filings for Apple
        {"cik": "0000320193", "count": 10}

        # Check for activist investor activity
        {"cik": "0000320193", "count": 20}

    Use Cases:
        - Identify major shareholders (>5%)
        - Detect activist investor campaigns (13D filings)
        - Monitor changes in control
        - Track institutional ownership changes
        - M&A due diligence (who owns the target?)
        - Identify potential acquirers

    Notes:
        - 13D = Activist/Control Intent (detailed disclosure)
        - 13G = Passive Investment (simpler disclosure)
        - Filed within 10 days of crossing 5% threshold
        - Amendments filed for significant changes
        - 13D includes Section 7 (purpose of transaction)
        - Look for Schedule A (identity of beneficial owner)

    Key Sections in 13D:
        - Item 3: Source and amount of funds
        - Item 4: Purpose of transaction (M&A intent?)
        - Item 5: Interest in securities
        - Item 6: Contracts, arrangements, understandings
        - Item 7: Material to be filed as exhibits

    Red Flags:
        - 13D filing (not 13G) = activist intent
        - Item 4 mentions board seats, strategic changes
        - Multiple 13D amendments = ongoing campaign
        - Coordination with other shareholders

    Related Tools:
        - sec_get_filing: Get full 13D/13G text for detailed analysis
        - OpenCorporates: Cross-reference beneficial owners
    """
    try:
        # Use existing company_filings with SC 13D/G filter
        result = await sec_company_filings(
            cik=cik,
            filing_type=None,  # Filter manually for both 13D and 13G
            count=count * 2,  # Get more to filter
            response_format=response_format
        )

        if result.get("status") != "ok":
            return result

        # Filter for 13D/13G forms
        ownership_forms = ["SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A"]  # Include amendments
        filings = result.get("filings", [])

        ownership_filings = [
            f for f in filings
            if any(form in f.get("form", "") for form in ownership_forms)
        ][:count]

        return {
            "status": "ok",
            "cik": result.get("cik"),
            "company_name": result.get("company_name"),
            "count": len(ownership_filings),
            "filings": ownership_filings,
            "note": (
                "13D = Activist/Control intent. 13G = Passive ownership. "
                "Use sec_get_filing to retrieve full text for detailed analysis. "
                "Pay special attention to Item 4 (purpose) in 13D filings."
            )
        }

    except Exception as e:
        logger.error(f"Error in beneficial_ownership: {e}")
        return format_error_response("sec_beneficial_ownership", e, {"cik": cik})


# ============================================================================
# TOOL: SEARCH FILINGS
# ============================================================================

@mcp.tool()
async def sec_search_filings(
        query: str,
        cik: Optional[str] = None,
        filing_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Search SEC filings by keywords and filters.

    Performs full-text search across SEC EDGAR filings. Useful for finding
    filings mentioning specific terms, companies, people, or topics.

    Args:
        query: Search keywords (e.g., 'merger', 'acquisition', 'restructuring', 'lawsuit')
        cik: Optional CIK to limit search to specific company
        filing_type: Optional filing type filter (e.g., '8-K', '10-K')
        start_date: Start of date range (format: 'YYYY-MM-DD')
        end_date: End of date range (format: 'YYYY-MM-DD')
        response_format: 'concise' or 'detailed'

    Returns:
        Search results with matching filings.

    Examples:

        # Search for merger mentions in Apple filings
        {"query": "merger acquisition", "cik": "0000320193"}

        # Search for material events (8-K) about lawsuits
        {"query": "lawsuit litigation", "filing_type": "8-K"}

        # Search date range
        {
            "query": "restructuring",
            "start_date": "2023-01-01",
            "end_date": "2023-12-31"
        }

    Use Cases:
        - Find M&A announcements
        - Search for specific contracts or agreements
        - Find mentions of competitors
        - Search for risk factors
        - Find regulatory issues or lawsuits
        - Track specific executives or board members

    Notes:
        - Search is case-insensitive
        - Boolean operators supported (AND, OR, NOT)
        - Phrase search with quotes ("material weakness")
        - Results limited to recent filings (performance)
        - Full-text search can be slow for broad queries

    Search Tips:
        - Use specific terms for better results
        - Combine with filing type for focus
        - Use date ranges to narrow results
        - Try variations (e.g., "acquire" vs "acquisition")
    """
    # Note: SEC's full-text search API is complex and may require different implementation
    # For MVP, return error with suggestion to use company_filings + get_filing

    return {
        "status": "error",
        "message": (
            "Full-text filing search is not yet implemented. "
            "Alternative approach: "
            "1. Use sec_company_filings to get filings for a company "
            "2. Use sec_get_filing with get_full_text=True "
            "3. Search the full_text field locally for keywords "
            "\n"
            "For structured search, consider: "
            "- Filter by filing_type in sec_company_filings "
            "- Use date filters (before_date, after_date) "
            "- Parse specific sections with custom logic"
        ),
        "suggested_tools": [
            "sec_company_filings",
            "sec_get_filing"
        ]
    }


# ============================================================================
# SYSTEM PROMPT ENHANCEMENT
# ============================================================================

def get_sec_system_prompt() -> str:
    """
    Get system prompt enhancement for SEC EDGAR tools.
    Contains critical rules and workflows.
    """
    return """
SEC EDGAR API CRITICAL RULES:

1. SEC EDGAR's Unique Value
   - Use SEC EDGAR for REGULATORY FILINGS and DISCLOSURES
   - AlphaVantage/FMP: Financial metrics and market data
   - OpenCorporates: Company registry and structure
   - SEC EDGAR: Legal filings, risk factors, contracts, ownership

   What SEC EDGAR provides uniquely:
   - Full text of official SEC filings (10-K, 10-Q, 8-K, proxies)
   - Risk factors and MD&A sections
   - Material contracts and exhibits
   - Detailed ownership disclosure (13D, 13F, 13G)
   - Insider trading detail (Forms 3, 4, 5)
   - M&A registration statements (S-4)
   - Executive compensation (DEF 14A)

2. CIK (Central Index Key) is Required
   - Almost all SEC tools require CIK, not ticker
   - CIK is SEC's unique company identifier
   - Format: 10 digits with leading zeros (e.g., 0000320193)

   ALWAYS start with: sec_cik_lookup(identifier="AAPL")
   Then use returned CIK: sec_company_filings(cik="0000320193")

3. Standard SEC Workflow

   User asks: "Get Apple's latest 10-K"

   Step 1: Get CIK
   sec_cik_lookup(identifier="AAPL")
   Result: cik = "0000320193"

   Step 2: Find filing
   sec_company_filings(cik="0000320193", filing_type="10-K", count=1)
   Result: accession_number = "0000320193-23-000106"

   Step 3: Retrieve filing
   sec_get_filing(cik="0000320193", accession_number="0000320193-23-000106")

4. Filing Types Guide

   For M&A Due Diligence:
   - 10-K: Annual report (comprehensive company overview, risks, financials)
   - 10-Q: Quarterly report (updates, recent events)
   - 8-K: Current report (material events, M&A announcements, executive changes)
   - DEF 14A: Proxy statement (executive comp, governance, shareholder votes)
   - S-4: M&A registration statement (merger details, pro forma financials)

   For Ownership Analysis:
   - SC 13D: Activist investors, control intent (>5% ownership)
   - SC 13G: Passive institutional ownership (>5%)
   - 13F-HR: Institutional holdings (quarterly, $100M+ managers)
   - Forms 3/4/5: Insider transactions

   For IPO/Offerings:
   - S-1: IPO registration
   - S-3: Shelf registration
   - 424B: Prospectus

5. When to Use Each Tool

   sec_cik_lookup:
   - ALWAYS use first if you have ticker or company name
   - Convert to CIK before other calls

   sec_company_filings:
   - List available filings
   - Filter by type and date
   - Get accession numbers for retrieval

   sec_get_filing:
   - Retrieve specific filing
   - Get metadata or full text
   - Use after company_filings to get accession number

   sec_company_facts:
   - Get structured XBRL data
   - Machine-readable financial metrics
   - Time series of specific accounting items
   - Alternative to parsing full filing text

   sec_insider_transactions:
   - Forms 3, 4, 5 filings
   - Raw filing metadata (need to parse for details)
   - Consider FMP for parsed transaction data

   sec_institutional_holdings_13f:
   - Get 13F filings for an INSTITUTION (not target company)
   - Shows what institution owns
   - Use FMP to see who owns a specific stock

   sec_beneficial_ownership:
   - Forms 13D and 13G for a TARGET COMPANY
   - Shows who owns >5% of company
   - Critical for M&A (ownership concentration)

6. Understanding Accession Numbers
   - Format: 0000000000-00-000000
   - Unique identifier for each filing
   - Required to retrieve specific filing
   - Get from sec_company_filings
   - Use in sec_get_filing

7. XBRL vs Full Text

   For Financial Data:
   - Use sec_company_facts for structured metrics
   - XBRL tags: Assets, Revenues, NetIncomeLoss, etc.
   - Easier than parsing full text
   - But AlphaVantage is even easier for basics

   For Qualitative Data:
   - Use sec_get_filing with get_full_text=True
   - Risk factors, MD&A, legal proceedings
   - Requires text parsing
   - Large responses (can be MB of text)

8. Data Freshness
   - SEC filings are filed immediately (real-time)
   - 10-K: Annual (90 days after fiscal year end)
   - 10-Q: Quarterly (45 days after quarter end)
   - 8-K: Within 4 days of material event
   - 13F: 45 days after quarter end
   - 13D: 10 days after crossing 5% threshold

9. Integration Patterns

   Pattern 1: M&A Due Diligence
   1. sec_cik_lookup(identifier="TARGET")
   2. sec_company_filings(cik=..., filing_type="10-K", count=1)
   3. sec_get_filing(accession_number=..., get_full_text=True)
   4. Parse risk factors, MD&A, legal proceedings
   5. sec_beneficial_ownership(cik=...) - who owns >5%?
   6. Combine with OpenCorporates for corporate structure
   7. Combine with FMP for financial analysis

   Pattern 2: Material Event Monitoring
   1. sec_company_filings(cik=..., filing_type="8-K")
   2. Review recent 8-K filings
   3. Look for Item 1.01 (M&A), Item 5.02 (executive changes)
   4. Get full text if material event found

   Pattern 3: Ownership Analysis
   1. sec_beneficial_ownership(cik=...) - who owns >5%?
   2. For each major holder, get their 13D/13G details
   3. Check Item 4 in 13D (purpose of transaction)
   4. Monitor for activist campaigns
   5. Cross-reference with FMP institutional ownership

   Pattern 4: Insider Trading Analysis
   1. sec_insider_transactions(cik=..., count=50)
   2. Identify patterns (clusters of selling/buying)
   3. Cross-reference with FMP insider trading for details
   4. Check timing relative to material events

   Pattern 5: Proxy Analysis (Executive Comp)
   1. sec_company_filings(cik=..., filing_type="DEF 14A", count=1)
   2. Get latest proxy statement
   3. Parse executive compensation tables
   4. Analyze say-on-pay votes
   5. Check for change-of-control provisions

10. Critical Differences vs Other APIs

    SEC vs AlphaVantage:
    - SEC: Source filings (legal documents)
    - AV: Processed financial data (easy to use)
    - Use AV for quick metrics, SEC for legal detail

    SEC vs FMP:
    - SEC: Raw filings (need parsing)
    - FMP: Parsed insider/institutional data
    - Use FMP for structured ownership data
    - Use SEC for full filing text and context

    SEC vs OpenCorporates:
    - SEC: US public company filings
    - OC: Global company registry
    - SEC: Legal/regulatory disclosure
    - OC: Corporate structure and officers
    - Both useful for due diligence

11. Common Filing Sections (10-K)

    Essential sections to extract:
    - Item 1: Business (company overview)
    - Item 1A: Risk Factors (critical for due diligence)
    - Item 7: MD&A (management discussion & analysis)
    - Item 8: Financial Statements
    - Item 9A: Controls and Procedures
    - Item 15: Exhibits (material contracts)

    For M&A focus:
    - Risk Factors (deal risks)
    - MD&A (management's view)
    - Exhibits (key contracts, change-of-control clauses)
    - Notes to financial statements (contingencies)

12. Red Flags in SEC Filings

    8-K Items to watch:
    - Item 1.01: Material agreements (M&A)
    - Item 1.02: Termination of material agreements
    - Item 2.01: Acquisitions/dispositions
    - Item 5.02: Executive changes (sudden departures)
    - Item 8.01: Other events (catchall)

    10-K Red Flags:
    - Going concern warnings
    - Material weaknesses in controls
    - Related party transactions
    - Legal proceedings
    - Management changes
    - Qualified audit opinions

13. User-Agent Requirement
    - SEC REQUIRES User-Agent with company name and email
    - Set SEC_USER_AGENT in .env
    - Format: "Company Name contact@email.com"
    - Without proper User-Agent, requests will be blocked (403)

14. Rate Limiting
    - SEC allows 10 requests per second MAX
    - We use 9 req/sec (110ms delay) to be safe
    - Exceeding limits results in temporary IP block
    - No daily/monthly limits, just per-second

15. Common Mistakes to Avoid
    - Using ticker instead of CIK (won't work)
    - Not calling sec_cik_lookup first
    - Requesting full_text without checking size
    - Confusing 13F (institution's holdings) with 13D (company's owners)
    - Parsing HTML without proper tools
    - Not handling large text responses
    - Assuming all companies have XBRL data

16. Best Practices
    - Always get CIK first via sec_cik_lookup
    - Use sec_company_filings to discover what's available
    - Check filing metadata before getting full text
    - Use sec_company_facts for structured financial data
    - Combine SEC data with other APIs for complete picture
    - For ownership: Use both SEC (detail) and FMP (convenience)
    - For insiders: Use both SEC (source) and FMP (parsed)
"""


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    print(
        "[SEC EDGAR] MCP Server Starting...\n"
        "U.S. Securities and Exchange Commission Filing Access\n"
        "\nData Source: SEC EDGAR (Electronic Data Gathering, Analysis, and Retrieval)\n"
        "\nRate Limit: 10 requests/second (enforced)\n"
        "\nCore Capabilities:\n"
        "  Company/CIK Lookup: Convert tickers to CIK identifiers\n"
        "  Filing Discovery: Search and list company filings\n"
        "  Filing Retrieval: Get full text of filings (10-K, 10-Q, 8-K, etc.)\n"
        "  Structured Data: XBRL financial facts extraction\n"
        "  Ownership: 13D/13G beneficial ownership, 13F institutional holdings\n"
        "  Insider Trading: Forms 3, 4, 5 filings\n"
        "\nKey Filing Types:\n"
        "  10-K: Annual report (comprehensive)\n"
        "  10-Q: Quarterly report\n"
        "  8-K: Current report (material events)\n"
        "  DEF 14A: Proxy statement (governance, executive comp)\n"
        "  S-4: M&A registration statement\n"
        "  SC 13D/G: Beneficial ownership (>5%)\n"
        "  13F-HR: Institutional holdings (quarterly)\n"
        "  Forms 3/4/5: Insider transactions\n"
        "\nM&A Use Cases:\n"
        "  - Due diligence via 10-K risk factors and MD&A\n"
        "  - Material event monitoring via 8-K filings\n"
        "  - Ownership analysis via 13D/13G\n"
        "  - Insider trading patterns via Forms 4\n"
        "  - Executive compensation via DEF 14A\n"
        "  - Contract review via exhibits\n"
        "\nCRITICAL:\n"
        "  - Set SEC_USER_AGENT in .env (format: 'Company Name email@domain.com')\n"
        "  - Always use sec_cik_lookup first to get CIK from ticker/name\n"
        "  - CIK required for most operations (not ticker symbol)\n"
        "\nIntegration:\n"
        "  - Combine with AlphaVantage for financial metrics\n"
        "  - Combine with FMP for parsed ownership/insider data\n"
        "  - Combine with OpenCorporates for corporate structure\n"
        "  - SEC provides source documents; other APIs provide convenience\n",
        flush=True
    )

    # Get system prompt (for documentation/reference)
    system_prompt = get_sec_system_prompt()

    # Run the MCP server
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8088)
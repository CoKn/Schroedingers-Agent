"""
OpenCorporates MCP Server
Global company registry data and corporate structure intelligence.

This server provides access to OpenCorporates' database of 200M+ companies across
130+ jurisdictions, offering legal entity verification, corporate structure analysis,
and officer/director information.

Key Features:
- Company lookup and search (private and public companies)
- Officers and directors data
- Corporate structure and ownership statements
- Statutory filings
- International jurisdiction support
"""

from __future__ import annotations

import os
import time
import asyncio
import logging
import httpx
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
    mcp = FastMCP(name="OpenCorporates")
except TypeError:
    mcp = FastMCP()


# ============================================================================
# CONFIGURATION & ENUMS
# ============================================================================

class ResponseFormat(str, Enum):
    """Control verbosity of tool responses for token efficiency."""
    CONCISE = "concise"  # Essential fields only
    DETAILED = "detailed"  # Full API response


# OpenCorporates API Configuration
OC_BASE_URL = "https://api.opencorporates.com"
OC_API_VERSION = "v0.4"
OC_API_TOKEN = os.getenv("OPENCORPORATES_API_TOKEN")

# Rate limit configuration (depends on plan)
# Free tier: 200 calls/month, 50 calls/day
# Open data tier: varies
RATE_LIMIT_PER_DAY = 10000  # Conservative default
RATE_LIMIT_PER_MONTH = 50000


# ============================================================================
# RATE LIMITING SYSTEM
# ============================================================================

@dataclass
class RateLimitTracker:
    """Tracks API call rate limits."""
    calls_per_day: List[float]
    calls_per_month: List[float]

    def __init__(self):
        self.calls_per_day = []
        self.calls_per_month = []

    def can_make_call(self) -> Tuple[bool, Optional[str]]:
        """
        Check if we can make an API call without exceeding rate limits.

        Returns:
            (can_call, error_message)
        """
        now = time.time()

        # Clean up old timestamps
        one_day_ago = now - 86400
        thirty_days_ago = now - (86400 * 30)

        self.calls_per_day = [t for t in self.calls_per_day if t > one_day_ago]
        self.calls_per_month = [t for t in self.calls_per_month if t > thirty_days_ago]

        # Check day limit
        if len(self.calls_per_day) >= RATE_LIMIT_PER_DAY:
            wait_time = 86400 - (now - self.calls_per_day[0])
            hours = wait_time / 3600
            return False, (
                f"Daily rate limit exceeded: {RATE_LIMIT_PER_DAY} calls per day. "
                f"Resets in {hours:.1f} hours. "
                f"Upgrade to a higher tier plan for increased limits."
            )

        # Check month limit
        if len(self.calls_per_month) >= RATE_LIMIT_PER_MONTH:
            return False, (
                f"Monthly rate limit exceeded: {RATE_LIMIT_PER_MONTH} calls per month. "
                f"Resets at end of month. "
                f"Upgrade to a paid plan for higher limits."
            )

        return True, None

    def record_call(self):
        """Record a successful API call."""
        now = time.time()
        self.calls_per_day.append(now)
        self.calls_per_month.append(now)

    def get_status(self) -> Dict[str, Any]:
        """Get current rate limit status."""
        now = time.time()
        one_day_ago = now - 86400
        thirty_days_ago = now - (86400 * 30)

        calls_today = len([t for t in self.calls_per_day if t > one_day_ago])
        calls_this_month = len([t for t in self.calls_per_month if t > thirty_days_ago])

        return {
            "calls_today": calls_today,
            "daily_limit": RATE_LIMIT_PER_DAY,
            "calls_this_month": calls_this_month,
            "monthly_limit": RATE_LIMIT_PER_MONTH,
            "daily_remaining": RATE_LIMIT_PER_DAY - calls_today,
            "monthly_remaining": RATE_LIMIT_PER_MONTH - calls_this_month
        }


# Global rate limiter
rate_limiter = RateLimitTracker()


# ============================================================================
# OPENCORPORATES API CLIENT
# ============================================================================

class OpenCorporatesClient:
    """HTTP client for OpenCorporates API."""

    def __init__(self, api_token: Optional[str] = None, api_version: str = OC_API_VERSION):
        """Initialize OpenCorporates client."""
        self.api_token = api_token or OC_API_TOKEN
        if not self.api_token:
            raise ValueError(
                "OpenCorporates API token not found. "
                "Set OPENCORPORATES_API_TOKEN in .env or pass api_token parameter. "
                "Get a token at: https://opencorporates.com/api_accounts/new"
            )

        self.base_url = OC_BASE_URL
        self.api_version = api_version
        self.client = httpx.AsyncClient(timeout=30.0)

    async def get(
            self,
            endpoint: str,
            params: Optional[Dict[str, Any]] = None,
            version: Optional[str] = None
    ) -> Any:
        """
        Make GET request to OpenCorporates API.

        Args:
            endpoint: API endpoint (e.g., '/companies/gb/00102498')
            params: Query parameters
            version: API version (defaults to instance version)

        Returns:
            JSON response
        """
        params = params or {}
        params['api_token'] = self.api_token

        version = version or self.api_version
        url = f"{self.base_url}/{version}{endpoint}"

        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise Exception("Invalid API token or authentication failed")
            elif e.response.status_code == 403:
                raise Exception("Access forbidden - may have exceeded rate limits")
            elif e.response.status_code == 404:
                raise Exception("Resource not found")
            elif e.response.status_code == 503:
                raise Exception("Service temporarily unavailable or company data temporarily redacted")
            else:
                raise Exception(f"HTTP error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            raise Exception(f"OpenCorporates API error: {str(e)}")

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Global client instance
_client: Optional[OpenCorporatesClient] = None


async def get_client() -> OpenCorporatesClient:
    """Get or create the global OpenCorporates client."""
    global _client
    if _client is None:
        _client = OpenCorporatesClient()
    return _client


# ============================================================================
# VALIDATION & ERROR HANDLING
# ============================================================================

def validate_jurisdiction_code(code: str) -> Tuple[bool, Optional[str]]:
    """
    Validate jurisdiction code format.

    OpenCorporates uses ISO 3166 codes:
    - Countries: 2-letter ISO code (e.g., 'gb', 'us', 'de')
    - States/provinces: underscore version of ISO 3166-2 (e.g., 'us_ca', 'us_de')
    """
    if not code:
        return False, "Jurisdiction code cannot be empty"

    code_lower = code.lower()

    # Basic format validation
    if len(code_lower) == 2:
        # Country code
        if not code_lower.isalpha():
            return False, f"Invalid jurisdiction code format: '{code}'. Should be 2-letter country code (e.g., 'gb', 'us')"
    elif '_' in code_lower:
        # State/province code
        parts = code_lower.split('_')
        if len(parts) != 2:
            return False, f"Invalid jurisdiction code format: '{code}'. Should be 'country_state' (e.g., 'us_ca', 'us_de')"
        if len(parts[0]) != 2 or not parts[0].isalpha():
            return False, f"Invalid country part in jurisdiction code: '{code}'"
    else:
        return False, (
            f"Invalid jurisdiction code format: '{code}'. "
            f"Use 2-letter country code (e.g., 'gb', 'us') or 'country_state' format (e.g., 'us_ca')"
        )

    return True, None


def validate_company_number(number: str) -> Tuple[bool, Optional[str]]:
    """Validate company number format."""
    if not number:
        return False, "Company number cannot be empty"

    if len(number) > 50:
        return False, f"Company number too long: '{number}'"

    return True, None


def apply_concise_format(tool_name: str, data: Any) -> Any:
    """
    Apply CONCISE formatting to reduce token usage.
    Returns essential fields only.
    """
    if not data:
        return data

    # If response has 'results' wrapper, extract it
    if isinstance(data, dict) and 'results' in data:
        data = data['results']

    # Tool-specific concise formats
    if tool_name == "get_company":
        if isinstance(data, dict) and 'company' in data:
            company = data['company']
            return {
                "name": company.get("name"),
                "company_number": company.get("company_number"),
                "jurisdiction_code": company.get("jurisdiction_code"),
                "company_type": company.get("company_type"),
                "incorporation_date": company.get("incorporation_date"),
                "dissolution_date": company.get("dissolution_date"),
                "current_status": company.get("current_status"),
                "inactive": company.get("inactive"),
                "registered_address_in_full": company.get("registered_address_in_full"),
                "registry_url": company.get("registry_url"),
                "opencorporates_url": company.get("opencorporates_url")
            }

    elif tool_name == "company_search":
        if isinstance(data, dict) and 'companies' in data:
            companies = data['companies']
            return [
                {
                    "name": c.get("company", {}).get("name"),
                    "company_number": c.get("company", {}).get("company_number"),
                    "jurisdiction_code": c.get("company", {}).get("jurisdiction_code"),
                    "current_status": c.get("company", {}).get("current_status"),
                    "incorporation_date": c.get("company", {}).get("incorporation_date"),
                    "opencorporates_url": c.get("company", {}).get("opencorporates_url")
                }
                for c in companies
            ]

    elif tool_name == "company_officers":
        if isinstance(data, dict) and 'officers' in data:
            officers = data['officers']
            return [
                {
                    "name": o.get("officer", {}).get("name"),
                    "position": o.get("officer", {}).get("position"),
                    "start_date": o.get("officer", {}).get("start_date"),
                    "end_date": o.get("officer", {}).get("end_date"),
                    "opencorporates_url": o.get("officer", {}).get("opencorporates_url")
                }
                for o in officers
            ]

    elif tool_name == "officer_search":
        if isinstance(data, dict) and 'officers' in data:
            officers = data['officers']
            return [
                {
                    "name": o.get("officer", {}).get("name"),
                    "position": o.get("officer", {}).get("position"),
                    "company_name": o.get("officer", {}).get("company", {}).get("name"),
                    "jurisdiction": o.get("officer", {}).get("jurisdiction_code"),
                    "opencorporates_url": o.get("officer", {}).get("opencorporates_url")
                }
                for o in officers
            ]

    # Return data as-is if no specific format defined
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
    if "jurisdiction" in error_msg.lower():
        response["suggestion"] = (
            "Check jurisdiction code format. Use 2-letter country codes (e.g., 'gb', 'us', 'de') "
            "or 'country_state' format for US states (e.g., 'us_ca', 'us_de'). "
            "Use opencorporates_jurisdiction_match to find correct codes."
        )
    elif "not found" in error_msg.lower():
        response["suggestion"] = (
            "Company not found. Verify company number and jurisdiction code. "
            "Try opencorporates_company_search to find the company first."
        )
    elif "rate limit" in error_msg.lower() or "forbidden" in error_msg.lower():
        response["suggestion"] = (
            "Rate limit exceeded. Check rate_limit_status and wait before retrying. "
            "Consider upgrading your OpenCorporates plan for higher limits."
        )
    elif "authentication" in error_msg.lower() or "token" in error_msg.lower():
        response["suggestion"] = (
            "Invalid API token. Check OPENCORPORATES_API_TOKEN in .env file. "
            "Get a token at: https://opencorporates.com/api_accounts/new"
        )

    return response


# ============================================================================
# TOOL: GET COMPANY
# ============================================================================

@mcp.tool()
async def opencorporates_get_company(
        jurisdiction_code: str,
        company_number: str,
        sparse: bool = False,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get detailed company information by jurisdiction and company number.

    This is the primary tool for looking up a specific company when you know
    its official company number and jurisdiction. Returns comprehensive data
    including incorporation details, current status, registered address, officers,
    and related corporate data.

    Args:
        jurisdiction_code: Jurisdiction code where company is registered.
                          Format:
                          - Countries: 2-letter ISO code (e.g., 'gb', 'us', 'de', 'nl')
                          - US States: 'us_' + state code (e.g., 'us_ca', 'us_de', 'us_ny')
                          - Other subdivisions: Similar pattern (e.g., 'ca_bc' for British Columbia)
        company_number: Official company registration number.
                       Format varies by jurisdiction (e.g., '00102498' for UK).
        sparse: If True, returns core company data only (faster, smaller response).
                If False, includes officers, filings, and related data (default).
        response_format: 'concise' (essential fields) or 'detailed' (full response)

    Returns:
        Comprehensive company data including:
        - name: Legal company name
        - company_number: Official registration number
        - company_type: Legal entity type (e.g., 'Public Limited Company', 'LLC')
        - incorporation_date: When company was incorporated
        - dissolution_date: When company was dissolved (if applicable)
        - current_status: Current status (e.g., 'Active', 'Dissolved')
        - inactive: Boolean flag indicating if company is inactive
        - registered_address: Full registered address
        - registry_url: Link to official registry page
        - officers: Array of directors/officers (unless sparse=True)
        - previous_names: Array of previous company names
        - industry_codes: Array of industry classification codes
        - source: Data provenance (publisher, retrieval date)

    Examples:

        # UK public company (BP)
        {
            "jurisdiction_code": "gb",
            "company_number": "00102498"
        }

        # US Delaware corporation
        {
            "jurisdiction_code": "us_de",
            "company_number": "5067833"
        }

        # Netherlands company
        {
            "jurisdiction_code": "nl",
            "company_number": "17087985"
        }

        # Fast lookup (sparse data)
        {
            "jurisdiction_code": "gb",
            "company_number": "00102498",
            "sparse": true,
            "response_format": "concise"
        }

    Common Jurisdictions:
        - gb: United Kingdom
        - us_de: Delaware, USA
        - us_ca: California, USA
        - us_ny: New York, USA
        - de: Germany
        - nl: Netherlands
        - fr: France
        - ie: Ireland
        - ca_bc: British Columbia, Canada

    Use Cases:
        - Legal entity verification
        - Due diligence research
        - Verify company registration status
        - Get official company details
        - Check if company is active or dissolved
        - Find company officers/directors

    Critical Notes:
        - Jurisdiction code must be exact (case-insensitive)
        - Company number must match official registry format
        - Use opencorporates_jurisdiction_match to find correct jurisdiction codes
        - Use opencorporates_company_search if you don't know the company number
        - Some registries have data gaps (check 'source' field for data quality)

    Common Mistakes:
        Wrong: {"jurisdiction_code": "UK", "company_number": "..."}  (use 'gb' not 'UK')
        Right: {"jurisdiction_code": "gb", "company_number": "..."}

        Wrong: {"jurisdiction_code": "California", ...}  (use code not name)
        Right: {"jurisdiction_code": "us_ca", ...}
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg, "rate_limit_status": rate_limiter.get_status()}

    # Validation
    is_valid, validation_error = validate_jurisdiction_code(jurisdiction_code)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    is_valid, validation_error = validate_company_number(company_number)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()

        # Build endpoint
        endpoint = f"/companies/{jurisdiction_code.lower()}/{company_number}"

        # Add sparse parameter if requested
        params = {}
        if sparse:
            params['sparse'] = 'true'

        data = await client.get(endpoint, params)
        rate_limiter.record_call()

        if not data or 'results' not in data:
            return {
                "status": "error",
                "message": f"No data returned for company {company_number} in {jurisdiction_code}"
            }

        # Apply response format
        if response_format == "concise":
            result_data = apply_concise_format("get_company", data)
        else:
            result_data = data['results']

        return {
            "status": "ok",
            "jurisdiction_code": jurisdiction_code.lower(),
            "company_number": company_number,
            "data": result_data,
            "rate_limit_status": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in get_company: {e}")
        return format_error_response("opencorporates_get_company", e, {
            "jurisdiction_code": jurisdiction_code,
            "company_number": company_number
        })


# ============================================================================
# TOOL: COMPANY SEARCH
# ============================================================================

@mcp.tool()
async def opencorporates_company_search(
        query: str,
        jurisdiction_code: Optional[str] = None,
        current_status: Optional[str] = None,
        company_type: Optional[str] = None,
        inactive: Optional[bool] = None,
        branch: Optional[bool] = None,
        incorporation_date: Optional[str] = None,
        order: str = "alphabetic",
        per_page: int = 30,
        page: int = 1,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Search for companies by name with powerful filtering options.

    This tool performs a fuzzy search across OpenCorporates' database of 200M+ companies.
    The search is deliberately loose, requiring all searched words but allowing any order
    and additional words. Use this when you have a company name but not the exact
    jurisdiction and company number.

    Args:
        query: Company name or search term (e.g., 'Apple Inc', 'Barclays Bank', 'Tesla').
               Wildcard '*' supported at end (e.g., 'Barclays Bank*').

        Filters (all optional):
        jurisdiction_code: Restrict to specific jurisdiction (e.g., 'gb', 'us_ca').
                          Can use comma-separated for multiple (e.g., 'gb,ie,us_de').
        current_status: Filter by status (e.g., 'Active', 'Dissolved').
                       Multiple values: 'Active,Dissolved' or 'Active|Dissolved'.
        company_type: Filter by type (e.g., 'Public Limited Company', 'LLC').
        inactive: Filter by inactive status (True = only inactive, False = only active).
        branch: Filter by branch status (True = only branches, False = exclude branches).
        incorporation_date: Filter by incorporation date.
                           Format: 'YYYY-MM-DD' or date range 'YYYY-MM-DD:YYYY-MM-DD'.
                           Can omit start or end (e.g., ':2020-12-31' = before end of 2020).

        Pagination & Sorting:
        order: Sort order. Options:
               - 'alphabetic' (default): Sort by name A-Z
               - 'score': Sort by search relevance
               - 'incorporation_date': Sort by incorporation date (newest first)
        per_page: Results per page (default: 30, max: 100)
        page: Page number (default: 1)

        response_format: 'concise' or 'detailed'

    Returns:
        Search results with:
        - companies: Array of matching companies
        - total_count: Total number of matches
        - page: Current page number
        - per_page: Results per page
        - total_pages: Total pages available

    Examples:

        # Basic search
        {"query": "Apple Inc"}

        # Search in specific jurisdiction
        {"query": "Barclays Bank", "jurisdiction_code": "gb"}

        # Wildcard search (companies starting with name)
        {"query": "Barclays Bank*", "jurisdiction_code": "gb"}

        # Active companies only
        {"query": "Tesla", "inactive": false}

        # Search with incorporation date filter
        {
            "query": "tech startup",
            "jurisdiction_code": "us_ca",
            "incorporation_date": "2020-01-01:2023-12-31"
        }

        # Sort by relevance
        {"query": "bank of scotland", "order": "score"}

        # Multiple jurisdictions
        {"query": "Amazon", "jurisdiction_code": "gb,ie,de"}

        # Recent incorporations
        {
            "query": "software",
            "order": "incorporation_date",
            "incorporation_date": "2023-01-01:",
            "per_page": 50
        }

    Search Tips:
        - Search is case-insensitive
        - All words required but order doesn't matter ('Bank Barclays' = 'Barclays Bank')
        - Common words removed ('the', 'of', 'and')
        - Company type abbreviations normalized (Ltd = Limited, Corp = Corporation)
        - Use wildcard '*' for prefix matching ('Barclays*')
        - Previous names are also searched

    Use Cases:
        - Find company when you have name but not number
        - Discover companies in a sector/jurisdiction
        - Verify company name spelling
        - Find all companies with similar names
        - Research recently incorporated companies
        - Check if company name exists in jurisdiction

    Critical Notes:
        - Returns up to 100 results per page (pagination available)
        - Wildcard only works at end of term
        - Use opencorporates_jurisdiction_match to find jurisdiction codes
        - For exact lookups, use opencorporates_get_company instead
        - Search may return many results - use filters to narrow down

    Common Patterns:

        # Pattern 1: Name to legal entity
        User: "Find the UK company Barclays Bank"
        Step 1: opencorporates_company_search(query="Barclays Bank", jurisdiction_code="gb")
        Step 2: Review results and select correct company
        Step 3: Use opencorporates_get_company for full details

        # Pattern 2: Verify company exists
        User: "Is there a company called XYZ Corp in Delaware?"
        Call: opencorporates_company_search(query="XYZ Corp", jurisdiction_code="us_de")

        # Pattern 3: Find similar companies
        User: "Show me tech companies incorporated in 2023"
        Call: opencorporates_company_search(
            query="technology",
            incorporation_date="2023-01-01:2023-12-31",
            order="incorporation_date"
        )
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg, "rate_limit_status": rate_limiter.get_status()}

    if not query or len(query.strip()) == 0:
        return {"status": "error", "message": "Query cannot be empty"}

    # Validate jurisdiction if provided
    if jurisdiction_code:
        # Handle multiple jurisdictions (comma or pipe separated)
        jurisdictions = [j.strip() for j in jurisdiction_code.replace('|', ',').split(',')]
        for jur in jurisdictions:
            is_valid, validation_error = validate_jurisdiction_code(jur)
            if not is_valid:
                return {"status": "error", "message": validation_error}

    try:
        client = await get_client()

        # Build query parameters
        params = {
            "q": query,
            "per_page": min(per_page, 100),
            "page": page
        }

        if order:
            params["order"] = order

        # Add filters
        if jurisdiction_code:
            params["jurisdiction_code"] = jurisdiction_code.lower()
        if current_status:
            params["current_status"] = current_status
        if company_type:
            params["company_type"] = company_type
        if inactive is not None:
            params["inactive"] = str(inactive).lower()
        if branch is not None:
            params["branch"] = str(branch).lower()
        if incorporation_date:
            params["incorporation_date"] = incorporation_date

        endpoint = "/companies/search"
        data = await client.get(endpoint, params)
        rate_limiter.record_call()

        if not data or 'results' not in data:
            return {
                "status": "ok",
                "query": query,
                "total_count": 0,
                "companies": []
            }

        results = data['results']

        # Apply response format
        if response_format == "concise":
            companies = apply_concise_format("company_search", results)
        else:
            companies = results.get('companies', [])

        return {
            "status": "ok",
            "query": query,
            "filters": {k: v for k, v in params.items() if k not in ['q', 'per_page', 'page', 'order', 'api_token']},
            "total_count": results.get('total_count', 0),
            "page": results.get('page', 1),
            "per_page": results.get('per_page', 30),
            "total_pages": results.get('total_pages', 0),
            "companies": companies,
            "rate_limit_status": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in company_search: {e}")
        return format_error_response("opencorporates_company_search", e, {
            "query": query,
            "jurisdiction_code": jurisdiction_code
        })


# ============================================================================
# TOOL: COMPANY OFFICERS
# ============================================================================

@mcp.tool()
async def opencorporates_company_officers(
        jurisdiction_code: str,
        company_number: str,
        per_page: int = 30,
        page: int = 1,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get officers and directors for a specific company.

    Returns information about company officers including directors, secretaries,
    and other corporate officers. This is embedded in the main company data but
    this tool provides a focused view on officers only.

    Args:
        jurisdiction_code: Jurisdiction code (e.g., 'gb', 'us_de')
        company_number: Official company registration number
        per_page: Results per page (default: 30, max: 100)
        page: Page number (default: 1)
        response_format: 'concise' or 'detailed'

    Returns:
        Officers data including:
        - name: Officer's name
        - position: Role (e.g., 'director', 'secretary', 'CEO')
        - start_date: When position started
        - end_date: When position ended (if applicable)
        - address: Officer's address (if available)
        - date_of_birth: Date of birth (if available, e.g., UK)

    Examples:

        # Get directors of UK company
        {
            "jurisdiction_code": "gb",
            "company_number": "00102498"
        }

        # US Delaware corporation officers
        {
            "jurisdiction_code": "us_de",
            "company_number": "5067833",
            "response_format": "concise"
        }

    Use Cases:
        - Identify key decision makers
        - Due diligence on management
        - Track officer appointments/resignations
        - Find companies associated with specific individuals

    Notes:
        - Officer data quality varies by jurisdiction
        - Some registries provide more detail than others
        - UK provides date of birth, most others don't
        - Historical officers may be included with end_date
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    # Validation
    is_valid, validation_error = validate_jurisdiction_code(jurisdiction_code)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    is_valid, validation_error = validate_company_number(company_number)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()

        # Get company data (includes officers)
        endpoint = f"/companies/{jurisdiction_code.lower()}/{company_number}"
        data = await client.get(endpoint)
        rate_limiter.record_call()

        if not data or 'results' not in data:
            return {"status": "error", "message": "Company not found"}

        company = data['results'].get('company', {})
        officers = company.get('officers', [])

        if not officers:
            return {
                "status": "ok",
                "message": "No officers found for this company",
                "jurisdiction_code": jurisdiction_code.lower(),
                "company_number": company_number,
                "officers": []
            }

        # Apply pagination
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_officers = officers[start_idx:end_idx]

        # Apply response format
        if response_format == "concise":
            result_data = apply_concise_format("company_officers", {"officers": paginated_officers})
        else:
            result_data = paginated_officers

        return {
            "status": "ok",
            "jurisdiction_code": jurisdiction_code.lower(),
            "company_number": company_number,
            "company_name": company.get("name"),
            "total_count": len(officers),
            "page": page,
            "per_page": per_page,
            "officers": result_data,
            "rate_limit_status": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in company_officers: {e}")
        return format_error_response("opencorporates_company_officers", e, {
            "jurisdiction_code": jurisdiction_code,
            "company_number": company_number
        })


# ============================================================================
# TOOL: OFFICER SEARCH
# ============================================================================

@mcp.tool()
async def opencorporates_officer_search(
        query: str,
        jurisdiction_code: Optional[str] = None,
        position: Optional[str] = None,
        date_of_birth: Optional[str] = None,
        inactive: Optional[bool] = None,
        per_page: int = 30,
        page: int = 1,
        order: str = "alphabetic",
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Search for officers/directors by name across all companies.

    This tool searches across company officers globally, allowing you to find
    all companies where a specific person is or was a director/officer.

    Args:
        query: Officer name to search for (e.g., 'John Smith', 'Jane Doe')
        jurisdiction_code: Restrict to specific jurisdiction (optional)
        position: Filter by position (e.g., 'director', 'secretary', 'ceo')
        date_of_birth: Filter by date of birth (format: 'YYYY-MM-DD' or date range)
                       Note: Only available for some jurisdictions like UK
        inactive: Filter by inactive status (True = only inactive, False = only active)
        per_page: Results per page (default: 30, max: 100)
        page: Page number (default: 1)
        order: Sort order ('alphabetic' or 'score')
        response_format: 'concise' or 'detailed'

    Returns:
        Officers matching search with their associated companies.

    Examples:

        # Search for all directors named John Smith
        {"query": "John Smith", "position": "director"}

        # Search in specific jurisdiction
        {"query": "David Jones", "jurisdiction_code": "gb"}

        # Search with date of birth (UK data)
        {
            "query": "Robert Brown",
            "jurisdiction_code": "gb",
            "date_of_birth": "1970-01-01:1980-12-31"
        }

        # Find active CEOs
        {
            "query": "CEO",
            "inactive": false,
            "order": "score"
        }

    Use Cases:
        - Find all companies a person directs
        - Track individual's corporate appointments
        - Identify network of companies
        - Due diligence on individuals
        - Find potential conflicts of interest

    Notes:
        - Search is fuzzy (allows word order variations)
        - Returns officers across all companies globally
        - Date of birth only available for some jurisdictions (e.g., UK)
        - May return many results for common names
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    if not query or len(query.strip()) == 0:
        return {"status": "error", "message": "Query cannot be empty"}

    try:
        client = await get_client()

        # Build query parameters
        params = {
            "q": query,
            "per_page": min(per_page, 100),
            "page": page,
            "order": order
        }

        # Add filters
        if jurisdiction_code:
            params["jurisdiction_code"] = jurisdiction_code.lower()
        if position:
            params["position"] = position
        if date_of_birth:
            params["date_of_birth"] = date_of_birth
        if inactive is not None:
            params["inactive"] = str(inactive).lower()

        endpoint = "/officers/search"
        data = await client.get(endpoint, params)
        rate_limiter.record_call()

        if not data or 'results' not in data:
            return {
                "status": "ok",
                "query": query,
                "total_count": 0,
                "officers": []
            }

        results = data['results']

        # Apply response format
        if response_format == "concise":
            officers = apply_concise_format("officer_search", results)
        else:
            officers = results.get('officers', [])

        return {
            "status": "ok",
            "query": query,
            "filters": {k: v for k, v in params.items() if k not in ['q', 'per_page', 'page', 'order', 'api_token']},
            "total_count": results.get('total_count', 0),
            "page": results.get('page', 1),
            "per_page": results.get('per_page', 30),
            "total_pages": results.get('total_pages', 0),
            "officers": officers,
            "rate_limit_status": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in officer_search: {e}")
        return format_error_response("opencorporates_officer_search", e, {"query": query})


# ============================================================================
# TOOL: COMPANY STATEMENTS
# ============================================================================

@mcp.tool()
async def opencorporates_company_statements(
        jurisdiction_code: str,
        company_number: str,
        per_page: int = 30,
        page: int = 1,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get corporate structure statements for a company.

    Returns 'statements' which are purported facts about the company from public
    records or users. Examples include:
    - Subsidiary relationships
    - Parent company relationships
    - Control statements (beneficial ownership)
    - Branch relationships
    - Corporate groupings

    Args:
        jurisdiction_code: Jurisdiction code (e.g., 'gb', 'us_de')
        company_number: Official company registration number
        per_page: Results per page (default: 30, max: 100)
        page: Page number (default: 1)
        response_format: 'concise' or 'detailed'

    Returns:
        Statements about corporate structure and relationships.

    Examples:

        # Get corporate structure for BP
        {
            "jurisdiction_code": "gb",
            "company_number": "00102498"
        }

        # Check subsidiaries
        {
            "jurisdiction_code": "us_de",
            "company_number": "5067833",
            "response_format": "concise"
        }

    Use Cases:
        - Map corporate structure
        - Identify parent companies
        - Find subsidiaries
        - Understand ownership chains
        - Due diligence on corporate groups

    Notes:
        - Statements come from public filings (e.g., SEC)
        - Includes data provenance
        - Quality varies by jurisdiction
        - May include historical relationships
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    # Validation
    is_valid, validation_error = validate_jurisdiction_code(jurisdiction_code)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    is_valid, validation_error = validate_company_number(company_number)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()

        endpoint = f"/companies/{jurisdiction_code.lower()}/{company_number}/statements"
        params = {
            "per_page": min(per_page, 100),
            "page": page
        }

        data = await client.get(endpoint, params)
        rate_limiter.record_call()

        if not data or 'results' not in data:
            return {
                "status": "ok",
                "message": "No statements found for this company",
                "jurisdiction_code": jurisdiction_code.lower(),
                "company_number": company_number,
                "statements": []
            }

        results = data['results']

        return {
            "status": "ok",
            "jurisdiction_code": jurisdiction_code.lower(),
            "company_number": company_number,
            "total_count": results.get('total_count', 0),
            "page": results.get('page', 1),
            "per_page": results.get('per_page', 30),
            "total_pages": results.get('total_pages', 0),
            "statements": results.get('statements', []),
            "rate_limit_status": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in company_statements: {e}")
        return format_error_response("opencorporates_company_statements", e, {
            "jurisdiction_code": jurisdiction_code,
            "company_number": company_number
        })


# ============================================================================
# TOOL: COMPANY FILINGS
# ============================================================================

@mcp.tool()
async def opencorporates_company_filings(
        jurisdiction_code: str,
        company_number: str,
        per_page: int = 30,
        page: int = 1,
        response_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Get statutory filings for a company.

    Returns official filings made by the company with the company registry.
    Examples include annual returns, changes to directors, address changes, etc.

    Args:
        jurisdiction_code: Jurisdiction code (e.g., 'gb', 'us_de')
        company_number: Official company registration number
        per_page: Results per page (default: 30, max: 100)
        page: Page number (default: 1)
        response_format: 'concise' or 'detailed'

    Returns:
        Filings including:
        - date: Filing date
        - title: Filing title or type
        - description: Filing description
        - filing_code: Official filing code (if available)
        - url: Link to filing document (if available)

    Examples:

        # Get recent filings for UK company
        {
            "jurisdiction_code": "gb",
            "company_number": "00102498",
            "per_page": 10
        }

        # Get all filings (paginated)
        {
            "jurisdiction_code": "us_de",
            "company_number": "5067833",
            "page": 1,
            "per_page": 50
        }

    Use Cases:
        - Track company activity
        - Monitor corporate changes
        - Compliance monitoring
        - Due diligence research
        - Identify recent events

    Notes:
        - Filing availability varies by jurisdiction
        - Some jurisdictions provide links to documents
        - Most recent filings appear first
        - Historical filings may be extensive (use pagination)
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    # Validation
    is_valid, validation_error = validate_jurisdiction_code(jurisdiction_code)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    is_valid, validation_error = validate_company_number(company_number)
    if not is_valid:
        return {"status": "error", "message": validation_error}

    try:
        client = await get_client()

        endpoint = f"/companies/{jurisdiction_code.lower()}/{company_number}/filings"
        params = {
            "per_page": min(per_page, 100),
            "page": page
        }

        data = await client.get(endpoint, params)
        rate_limiter.record_call()

        if not data or 'results' not in data:
            return {
                "status": "ok",
                "message": "No filings found for this company",
                "jurisdiction_code": jurisdiction_code.lower(),
                "company_number": company_number,
                "filings": []
            }

        results = data['results']

        return {
            "status": "ok",
            "jurisdiction_code": jurisdiction_code.lower(),
            "company_number": company_number,
            "total_count": results.get('total_count', 0),
            "page": results.get('page', 1),
            "per_page": results.get('per_page', 30),
            "total_pages": results.get('total_pages', 0),
            "filings": results.get('filings', []),
            "rate_limit_status": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in company_filings: {e}")
        return format_error_response("opencorporates_company_filings", e, {
            "jurisdiction_code": jurisdiction_code,
            "company_number": company_number
        })


# ============================================================================
# TOOL: JURISDICTION MATCH
# ============================================================================

@mcp.tool()
async def opencorporates_jurisdiction_match(
        query: str,
        related_jurisdiction_code: Optional[str] = None
) -> Dict[str, Any]:
    """
    Match jurisdiction name to OpenCorporates jurisdiction code.

    This tool helps find the correct jurisdiction code when you have a jurisdiction
    name in various formats. It accepts many variations including full names,
    abbreviations, and common aliases.

    Args:
        query: Jurisdiction name or abbreviation.
               Examples: 'United Kingdom', 'GB', 'Delaware', 'California', 'Netherlands'
        related_jurisdiction_code: Optional hint to disambiguate.
                                   Example: Use 'us' to clarify 'PA' means Pennsylvania
                                   (not Panama), or 'Georgia' means US state (not country)

    Returns:
        Matched jurisdiction with:
        - code: OpenCorporates jurisdiction code
        - name: Full jurisdiction name
        - abbreviation: Common abbreviation
        - country_code: Country code (if subdivision)

    Examples:

        # Match country name
        {"query": "United Kingdom"}  # Returns: gb

        # Match abbreviation
        {"query": "GB"}  # Returns: gb

        # Match US state
        {"query": "Delaware"}  # Returns: us_de

        # Disambiguate with hint
        {
            "query": "PA",
            "related_jurisdiction_code": "us"
        }  # Returns: us_pa (Pennsylvania, not Panama)

        # Match variations
        {"query": "The Netherlands"}  # Returns: nl
        {"query": "Holland"}  # Returns: nl

        # State disambiguation
        {
            "query": "Georgia",
            "related_jurisdiction_code": "us"
        }  # Returns: us_ga (not country Georgia)

    Use Cases:
        - Convert jurisdiction names to codes
        - Find correct codes before company lookup
        - Handle user input in various formats
        - Disambiguate similar jurisdiction names

    Common Mappings:
        - "UK" / "United Kingdom" / "Great Britain" -> "gb"
        - "USA" / "United States" -> "us"
        - "Delaware" -> "us_de"
        - "California" -> "us_ca"
        - "New York" -> "us_ny"
        - "Netherlands" / "Holland" -> "nl"
        - "Germany" -> "de"
        - "France" -> "fr"

    Notes:
        - Highly flexible matching (accepts many formats)
        - Use related_jurisdiction_code to disambiguate
        - Returns most likely match
        - Use before opencorporates_get_company or opencorporates_company_search
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    if not query or len(query.strip()) == 0:
        return {"status": "error", "message": "Query cannot be empty"}

    try:
        client = await get_client()

        params = {"q": query}
        if related_jurisdiction_code:
            params["related_jurisdiction_code"] = related_jurisdiction_code.lower()

        endpoint = "/jurisdictions/match"
        data = await client.get(endpoint, params)
        rate_limiter.record_call()

        if not data or 'results' not in data:
            return {
                "status": "error",
                "message": f"No jurisdiction match found for: '{query}'"
            }

        jurisdiction = data['results'].get('jurisdiction', {})

        return {
            "status": "ok",
            "query": query,
            "jurisdiction": jurisdiction,
            "rate_limit_status": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in jurisdiction_match: {e}")
        return format_error_response("opencorporates_jurisdiction_match", e, {
            "query": query,
            "related_jurisdiction_code": related_jurisdiction_code
        })


# ============================================================================
# TOOL: ACCOUNT STATUS
# ============================================================================

@mcp.tool()
async def opencorporates_account_status() -> Dict[str, Any]:
    """
    Check OpenCorporates API account status and usage limits.

    Returns information about your API account including:
    - Current plan type
    - Usage today and this month
    - Remaining calls today and this month
    - Account expiry date

    This tool helps you monitor your API usage to avoid hitting rate limits.

    Args:
        None

    Returns:
        Account status including:
        - plan: Plan type (e.g., 'open_data', 'basic', 'premium')
        - status: Account status (e.g., 'approved', 'pending')
        - expiry_date: When current plan expires
        - usage: {today: X, this_month: Y}
        - calls_remaining: {today: X, this_month: Y}

    Example:
        {}

    Use Cases:
        - Monitor API usage
        - Check remaining quota
        - Verify account is active
        - Plan API call strategy

    Notes:
        - Daily usage resets at midnight UTC
        - Monthly usage resets at end of month
        - Limits depend on your plan
        - Check before making many API calls
    """
    can_call, error_msg = rate_limiter.can_make_call()
    if not can_call:
        return {"status": "error", "message": error_msg}

    try:
        client = await get_client()

        endpoint = "/account_status"
        data = await client.get(endpoint)
        rate_limiter.record_call()

        if not data or 'results' not in data:
            return {"status": "error", "message": "Could not retrieve account status"}

        account_status = data['results'].get('account_status', {})

        return {
            "status": "ok",
            "account_status": account_status,
            "local_rate_limit_tracking": rate_limiter.get_status()
        }

    except Exception as e:
        logger.error(f"Error in account_status: {e}")
        return format_error_response("opencorporates_account_status", e, {})


# ============================================================================
# SYSTEM PROMPT ENHANCEMENT
# ============================================================================

def get_opencorporates_system_prompt() -> str:
    """
    Get system prompt enhancement for OpenCorporates tools.
    Contains critical rules and workflows.
    """
    return """
OPENCORPORATES API CRITICAL RULES:

1. OpenCorporates Unique Value
   - Use OpenCorporates for LEGAL ENTITY DATA, not financial data
   - AlphaVantage/FMP: Financial data for public companies
   - OpenCorporates: Company registry data for ALL companies (public + private)

   What OpenCorporates provides uniquely:
   - Private company information
   - Global coverage (200M+ companies, 130+ jurisdictions)
   - Corporate structure (parent/subsidiary relationships)
   - Officers and directors
   - Official registration details
   - Company status (active/dissolved)
   - Statutory filings

2. Jurisdiction Code Format (CRITICAL)
   Countries: 2-letter ISO code (lowercase)
   - 'gb' = United Kingdom
   - 'us' = United States (country level)
   - 'de' = Germany
   - 'nl' = Netherlands
   - 'fr' = France
   - 'ie' = Ireland

   US States: 'us_' + state code
   - 'us_de' = Delaware
   - 'us_ca' = California
   - 'us_ny' = New York
   - 'us_tx' = Texas

   Other subdivisions: Similar pattern
   - 'ca_bc' = British Columbia, Canada

   NEVER use:
   - Full names ('United Kingdom' - use 'gb')
   - Uppercase ('GB' - use 'gb')
   - Variations ('UK' - use 'gb')

3. Standard Workflow for Company Lookup

   User asks: "Tell me about Apple Inc"

   If you don't know jurisdiction + company number:
   Step 1: opencorporates_company_search(query="Apple Inc")
   Step 2: Review results, identify correct company
   Step 3: opencorporates_get_company(jurisdiction_code="...", company_number="...")

   If you know jurisdiction + number:
   Direct: opencorporates_get_company(jurisdiction_code="gb", company_number="00102498")

4. When to Use Each Tool

   opencorporates_get_company:
   - When you have jurisdiction code + company number
   - Most accurate, fastest method
   - Returns complete company data

   opencorporates_company_search:
   - When you have company name but not number
   - When exploring companies in a sector
   - When verifying company existence
   - Use filters to narrow results

   opencorporates_company_officers:
   - Find directors/officers of specific company
   - Due diligence on management
   - Track leadership changes

   opencorporates_officer_search:
   - Find all companies where person is officer
   - Track individual's corporate network
   - Identify conflicts of interest

   opencorporates_company_statements:
   - Map corporate structure
   - Find parent/subsidiary relationships
   - Understand ownership

   opencorporates_company_filings:
   - Track company activity
   - Monitor corporate changes
   - Compliance research

   opencorporates_jurisdiction_match:
   - Convert jurisdiction names to codes
   - ALWAYS use this when user provides jurisdiction name
   - Use before get_company or company_search

5. Jurisdiction Matching Best Practice

   User says: "Find company in Delaware"
   CORRECT workflow:
   Step 1: opencorporates_jurisdiction_match(query="Delaware")
   Result: jurisdiction_code = "us_de"
   Step 2: Use "us_de" in subsequent calls

   WRONG:
   Guessing: jurisdiction_code="delaware" or "DE" or "us_delaware"

6. Search Tips

   Search is fuzzy and flexible:
   - 'Bank Barclays' = 'Barclays Bank'
   - Case-insensitive
   - Common words removed ('the', 'of', 'and')
   - Company types normalized ('Ltd' = 'Limited')

   Use filters to narrow:
   - jurisdiction_code: Focus on specific location
   - inactive: true/false for active/dissolved companies
   - incorporation_date: Date ranges
   - current_status: 'Active', 'Dissolved', etc.

   Use wildcard for prefix matching:
   - 'Barclays Bank*' matches companies starting with 'Barclays Bank'

7. Response Format Strategy
   - Use response_format="concise" for overview
   - Use response_format="detailed" for full data
   - CONCISE saves tokens without losing key info

8. Rate Limits
   Free tier: 50000 calls/month, 10000 calls/day
   Open data: Higher limits (varies)
   Premium: Even higher limits

   ALWAYS check rate_limit_status in responses
   Use opencorporates_account_status to monitor usage
   Plan your API calls strategically

9. Data Quality Notes
   - Quality varies by jurisdiction
   - Some registries provide more data than others
   - UK: Excellent data, includes officer DOB
   - US: Good coverage but varies by state
   - Always check 'source' field for data provenance
   - 'retrieved_at' shows data freshness

10. Integration with Other APIs

    Pattern 1: Full Company Research
    1. OpenCorporates: Verify legal entity, get officers
    2. If public company: AlphaVantage for financials
    3. FMP for advanced analytics

    Pattern 2: Due Diligence
    1. OpenCorporates: Company details, officers, structure
    2. OpenCorporates: Search officers to find other companies
    3. AlphaVantage/FMP: Financial health (if public)

    Pattern 3: Private Company Research
    1. OpenCorporates: Only source for private company data
    2. Get registration details, officers, filings
    3. No financial data available (private companies)

11. Common Mistakes to Avoid
    - Using full jurisdiction names instead of codes
    - Using uppercase codes ('GB' instead of 'gb')
    - Not using jurisdiction_match for user-provided names
    - Confusing company search with company lookup
    - Forgetting to filter by jurisdiction in searches
    - Not checking rate limits before bulk operations

12. Error Recovery
    "Company not found":
    - Verify jurisdiction code is correct
    - Verify company number format
    - Try company_search instead

    "Invalid jurisdiction code":
    - Use opencorporates_jurisdiction_match
    - Check code format (lowercase, correct pattern)

    "Rate limit exceeded":
    - Check opencorporates_account_status
    - Wait for reset (daily or monthly)
    - Upgrade plan if needed

13. Advanced Use Cases

    Corporate Network Mapping:
    1. Start with parent company (get_company)
    2. Get statements to find subsidiaries
    3. For each subsidiary, get officers
    4. Search officers to find other connections

    Compliance Check:
    1. Verify company is active (get_company)
    2. Check recent filings (company_filings)
    3. Verify current officers (company_officers)
    4. Check for beneficial ownership (company_statements)

    Market Research:
    1. Search companies in sector/jurisdiction
    2. Filter by incorporation date for new companies
    3. Analyze company types and status distribution
"""


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    print(
        "[OpenCorporates] MCP Server Starting...\n"
        "Global Company Registry Data and Corporate Intelligence\n"
        "\nCoverage: 200M+ companies across 130+ jurisdictions\n"
        "\nRate Limits: 200 calls/month, 50 calls/day (free tier)\n"
        "\nCore Capabilities:\n"
        "  Company Lookup: Get details by jurisdiction + company number\n"
        "  Company Search: Find companies by name with powerful filters\n"
        "  Officers: Directors and corporate officers data\n"
        "  Corporate Structure: Parent/subsidiary relationships, ownership\n"
        "  Filings: Statutory filings from company registries\n"
        "  Jurisdictions: Match names to official codes\n"
        "\nKey Differentiators:\n"
        "  - Private AND public companies\n"
        "  - International coverage (not just US)\n"
        "  - Official registry data\n"
        "  - Corporate structure mapping\n"
        "  - Legal entity verification\n"
        "\nJurisdiction Codes:\n"
        "  Countries: 2-letter ISO (e.g., 'gb', 'us', 'de', 'nl')\n"
        "  US States: 'us_XX' (e.g., 'us_de', 'us_ca', 'us_ny')\n"
        "  Always use opencorporates_jurisdiction_match for names!\n"
        "\nBest Practice:\n"
        "  Use OpenCorporates for legal entity data\n"
        "  Use AlphaVantage/FMP for financial data\n"
        "  Perfect complementary coverage!\n",
        flush=True
    )

    # Get system prompt (for documentation/reference)
    system_prompt = get_opencorporates_system_prompt()

    # Run the MCP server
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8087)
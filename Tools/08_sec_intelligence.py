"""
UNIFIED CORPORATE INTELLIGENCE MCP
===================================

This MCP server combines multiple SEC-based intelligence tools into a single
production-ready microservice that the agent can reliably use in M&A,
strategy, and regulatory compliance workflows.

TOOLS INCLUDED
--------------
1. extract_strategy
    Extract strategic insights from 10-K and 10-Q filings using the SEC extractor.

2. sec_cik_lookup
    Convert a U.S. stock ticker → SEC CIK.

3. sec_insider_transactions
    Retrieve Form 4 insider-trading filings.

DESIGN PRINCIPLES
-----------------
✓ Standardized input and output formats  
✓ Clean, agent-optimized docstrings  
✓ Clear action triggers  
✓ SEC-compliant user agent & retry patterns  
✓ Robust fallback logic for missing filing documents  
✓ Single, unified MCP server  
"""

from fastmcp import FastMCP
import requests
import os
from dotenv import load_dotenv
from typing import Dict, List, Optional
import time


# =====================================================================
# ENVIRONMENT
# =====================================================================
load_dotenv()

SEC_API_KEY = os.getenv("SEC_API_KEY")
if not SEC_API_KEY:
    raise RuntimeError("Missing SEC_API_KEY")

SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "UnifiedCorporateIntelligence/1.0 (contact: uniproject@student.unisg.ch)"
)

HEADERS = {"User-Agent": SEC_USER_AGENT}

SEC_DATA_BASE = "https://data.sec.gov"
SEC_ARCHIVES_BASE = "https://www.sec.gov"
SEC_TICKER_FILE = "https://www.sec.gov/files/company_tickers.json"
SEC_EXTRACTOR = "https://api.sec-api.io/extractor"


# =====================================================================
# MCP SERVER
# =====================================================================
mcp = FastMCP(
    name="Unified Corporate Intelligence MCP",
    json_response=True
)


# =====================================================================
# HELPER FUNCTIONS
# =====================================================================
def sec_json(path: str) -> dict:
    """Retrieve SEC JSON from data.sec.gov with correct headers."""
    url = f"{SEC_DATA_BASE}{path}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()


def sec_get(url: str) -> dict:
    """Generic GET wrapper with SEC headers."""
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()


def url_exists(url: str) -> bool:
    """Check if a remote filing document exists."""
    r = requests.head(url, headers=HEADERS, allow_redirects=True)
    return r.status_code == 200


def build_filing_url(cik: str, accession: str, doc: str) -> str:
    """Build canonical filing URL on sec.gov."""
    acc_clean = accession.replace("-", "")
    return f"{SEC_ARCHIVES_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{doc}"


def fallback_primary_doc(cik: str, accession: str) -> Optional[str]:
    """Inspect index.json to discover HTML/TXT filings."""
    acc_clean = accession.replace("-", "")
    url = f"{SEC_DATA_BASE}/Archives/edgar/data/{cik}/{acc_clean}/index.json"

    try:
        r = requests.get(url, headers=HEADERS)
        r.raise_for_status()
        items = r.json().get("directory", {}).get("item", [])
    except Exception:
        return None

    for obj in items:
        name = obj.get("name", "").lower()
        if name.endswith((".htm", ".html", ".txt")):
            return f"{SEC_ARCHIVES_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{obj['name']}"

    return None


def extract_item(url: str, item_code: str) -> Optional[str]:
    """Extract a section via SEC Extractor API with retry on 'processing' response."""
    params = {
        "url": url,
        "item": item_code,
        "type": "text",
        "token": SEC_API_KEY
    }

    for attempt in range(3):
        r = requests.get(SEC_EXTRACTOR, params=params)
        r.raise_for_status()
        content = r.text.strip()

        if not content.lower().startswith("processing"):
            return content if content.strip() else None

        time.sleep(1)

    return None


# =====================================================================
# TOOL: sec_extract_company_strategy_sections_from_filings
# =====================================================================
@mcp.tool()
def sec_extract_company_strategy_sections_from_filings(cik: str, limit: int = 2) -> Dict:
    """
    Extract strategic content from the latest 10-K and 10-Q filings.

    PURPOSE
    -------
    Extracts strategy-critical sections from SEC filings:
      • 10-K → Item 1 (Business), Item 7 (MD&A)
      • 10-Q → Part I Item 2 (MD&A)

    INPUTS
    ------
    cik: str
        Raw, padded, or unpadded CIK. Leading zeros are handled.
    limit: int (default = 2)
        Maximum number of filings to process (10-K/10-Q only).

    OUTPUT FORMAT
    -------------
    {
      "cik": "<string>",
      "filings_analyzed": [
        {
          "form": "10-K" | "10-Q",
          "accession": "<string>",
          "primary_document": "<string>",
          "document_url": "<URL or null>",
          "extraction_errors": { ...optional... }
        }
      ],
      "strategy_sections": {
        "<accession_number>": {
            "business_overview": "<text or null>",
            "mdna": "<text or null>"
        }
      }
    }

    AGENT DECISION LOGIC
    --------------------
    Use this tool when:
      • Performing strategic assessments
      • Summarizing business model, risks, MD&A, or strategic direction
      • Preparing industry or competitive intelligence reviews  
    """

    cik_raw = str(cik).lstrip("0")
    cik10 = cik_raw.zfill(10)

    subs = sec_json(f"/submissions/CIK{cik10}.json")
    recent = subs.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])

    filings = [
        (f, a, d) for f, a, d in zip(forms, accessions, docs)
        if f in ("10-K", "10-Q")
    ][:limit]

    results = {}
    meta = []

    for form, acc, doc in filings:
        url = build_filing_url(cik_raw, acc, doc)

        if not url_exists(url):
            fallback = fallback_primary_doc(cik_raw, acc)
            url = fallback if fallback and url_exists(fallback) else None

        if not url:
            meta.append({
                "form": form,
                "accession": acc,
                "primary_document": doc,
                "document_url": None,
                "error": "Primary document could not be resolved"
            })
            continue

        filing_meta = {
            "form": form,
            "accession": acc,
            "primary_document": doc,
            "document_url": url
        }

        # Mapping
        items = {"business_overview": "1", "mdna": "7"} if form == "10-K" else {"mdna": "part1item2"}

        extracted = {}
        for label, code in items.items():
            text = extract_item(url, code)
            if text:
                extracted[label] = text
            else:
                filing_meta.setdefault("extraction_errors", {})[label] = "empty_or_failed"

        results[acc] = extracted
        meta.append(filing_meta)

    return {
        "cik": cik_raw,
        "filings_analyzed": meta,
        "strategy_sections": results
    }


# =====================================================================
# TOOL: sec_lookup_company_cik_by_ticker
# =====================================================================
@mcp.tool()
def sec_lookup_company_cik_by_ticker(symbol: str) -> Dict:
    """
    Convert a U.S. stock ticker into a SEC CIK (Central Index Key).

    PURPOSE
    -------
    Required first step before insider trading or filing-based analysis.

    INPUT
    -----
    symbol: str
        U.S. exchange-listed ticker (e.g., "AAPL", "MSFT").

    OUTPUT
    ------
    {
      "symbol": "<string>",
      "cik": "<10-digit CIK>"
    }

    AGENT USAGE
    -----------
    Use this tool:
      • As step 1 in insider-trading analysis
      • Before calling extract_strategy
      • To validate that a company is U.S.-domiciled

    If no CIK is found:
      → Company is likely foreign, OTC, private, or not EDGAR-reporting.
    """

    data = sec_get(SEC_TICKER_FILE)

    for entry in data.values() if isinstance(data, dict) else data:
        if entry.get("ticker", "").upper() == symbol.upper():
            cik = str(entry["cik_str"]).zfill(10)
            return {"symbol": symbol.upper(), "cik": cik}

    raise ValueError(
        f"No SEC CIK found for ticker '{symbol}'. "
        f"The company may not be U.S.-domiciled or SEC-reporting."
    )


# =====================================================================
# TOOL: sec_get_insider_activity_summary
# =====================================================================
@mcp.tool()
def sec_get_insider_activity_summary(cik: str) -> Dict:
    """
    Retrieve recent SEC Form 4 insider-trading filings.

    PURPOSE
    -------
    Provides a *baseline* insider-signal layer for M&A, risk, or anomaly detection.
    The tool does NOT interpret patterns — the agent must.

    INPUT
    -----
    cik: str
        10-digit or raw CIK.

    OUTPUT FORMAT
    -------------
    {
      "cik": "<string>",
      "form4_count": <int>,
      "dates": ["YYYY-MM-DD", ...],
      "since": "<oldest filing date or null>",
      "latest": "<most recent filing date or null>"
    }

    AGENT DECISION LOGIC
    ---------------------
    After receiving the output, the agent should examine:
      • magnitude of Form 4 filings
      • clustering or frequency
      • recency (sudden surge or spike)
      • whether the pattern is atypical

    REPLANNING TRIGGER
    ------------------
    If the agent concludes activity is:
        • unusually high
        • unusually frequent
        • clustered tightly
        • suspicious in timing

    → Trigger replanning  
    → Call: fmp_insider_trading(symbol)
    """

    cik = str(cik).zfill(10)
    url = f"{SEC_DATA_BASE}/submissions/CIK{cik}.json"

    data = sec_get(url)
    recent = data.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])

    form4_dates = [d for f, d in zip(forms, dates) if f == "4"]

    if not form4_dates:
        return {
            "cik": cik,
            "form4_count": 0,
            "dates": [],
            "since": None,
            "latest": None
        }

    return {
        "cik": cik,
        "form4_count": len(form4_dates),
        "dates": form4_dates,
        "since": min(form4_dates),
        "latest": max(form4_dates)
    }


# =====================================================================
# RUN SERVER
# =====================================================================
if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8089
    )

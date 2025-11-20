from fastmcp import FastMCP
from typing import Dict
import requests
import os
from dotenv import load_dotenv


# =============================================================
# CLASS NAME: Regulatory Compliance & Insider Signals
# =============================================================

"""
This microservice provides U.S.-only regulatory compliance data via SEC EDGAR
and enables baseline insider activity assessment for M&A analysis.

IMPORTANT:
----------
This tool ONLY works for companies listed and domiciled in the United States.
Foreign companies do not appear in EDGAR with complete or reliable Form 4 data.

AGENT USAGE IN M&A PIPELINE:
-----------------------------

Step 3: Baseline Insider Activity Check
---------------------------------------
1. Use sec_cik_lookup(symbol) → CIK
2. Use sec_insider_transactions(cik) → Form 4 filing history

The agent examines:
    - form4_count
    - frequency of filings
    - recency (latest)
    - dataset range ("since")

REPLANNING TRIGGER #1:
----------------------
If SEC filings show unusually high insider activity (e.g., many Form 4 filings
in a short period), the agent MUST trigger replanning and call:

    fmp_insider_trading(symbol)

The FMP tool provides detailed buy/sell patterns, insider roles, and total
transaction values for deeper M&A anomaly analysis.

This microservice intentionally provides only the SEC "baseline" screening layer.
The detailed investigation happens in the Financial Health service.
"""


# -------------------------------------------------------------
# ENVIRONMENT + CONSTANTS
# -------------------------------------------------------------
load_dotenv()

SEC_BASE = "https://data.sec.gov"
SEC_TICKER_FILE = "https://www.sec.gov/files/company_tickers.json"

# REQUIRED by SEC — must contain contact info
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "MyAgent/1.0 (contact: uniproject@student.unisg.ch)"
)


mcp = FastMCP(
    name="Regulatory Compliance & Insider Signals",
    json_response=True
)


# -------------------------------------------------------------
# SEC request wrapper
# -------------------------------------------------------------
def sec_get(url: str) -> dict:
    r = requests.get(url, headers={"User-Agent": SEC_USER_AGENT})
    r.raise_for_status()
    return r.json()


# =============================================================
# TOOL: sec_cik_lookup
# =============================================================
@mcp.tool()
def sec_cik_lookup(symbol: str) -> Dict:
    """
    Convert a U.S. stock ticker into a SEC CIK (Central Index Key).

    IMPORTANT:
    ----------
    • Only works for U.S.-domiciled companies.
    • Required before calling sec_insider_transactions.

    M&A Agent Behavior:
    -------------------
    This is the first step in the baseline insider activity check.
    The agent uses this CIK to fetch Form 4 filings.
    """

    data = sec_get(SEC_TICKER_FILE)

    for entry in data.values() if isinstance(data, dict) else data:
        if entry.get("ticker", "").upper() == symbol.upper():
            cik = str(entry.get("cik_str")).zfill(10)
            return {
                "symbol": symbol.upper(),
                "cik": cik
            }

    raise ValueError(f"No SEC CIK found for symbol '{symbol}'. "
                     f"This company may not be U.S.-domiciled.")


# =============================================================
# TOOL: sec_insider_transactions
# =============================================================
@mcp.tool()
def sec_insider_transactions(cik: str) -> Dict:
    """
    Retrieve recent Form 4 insider trading filings for a U.S.-domiciled company.

    Endpoint:
        https://data.sec.gov/submissions/CIK##########.json

    Returns:
        - form4_count: total number of recent Form 4 filings
        - dates: list of filing dates (newest first)
        - since: earliest filing date available in the dataset
        - latest: most recent filing date

    AGENT GUIDANCE
    ==============
    This tool provides a *baseline indicator* of insider activity. The agent
    must interpret the resulting patterns and decide whether further
    investigation is needed.

    HOW THE AGENT SHOULD REASON
    ---------------------------
    After receiving the Form 4 data, the agent should examine:
      • the magnitude of Form 4 filings
      • the frequency and clustering of filing dates
      • the recency and volatility of activity
      • whether the overall pattern appears unusual relative to typical
        public-company insider behavior

    The tool does NOT determine what counts as “unusual.”  
    The agent must use its own reasoning and judgment to interpret the
    significance of the insider activity.

    M&A REPLANNING TRIGGER
    ----------------------
    If the agent concludes that insider activity is:
        • unusually high,
        • unusually frequent,
        • unusually clustered,
        • or otherwise suspicious,

    THEN the agent MUST trigger a replanning step and call:

        fmp_insider_trading(symbol)

    This follow-up tool reveals:
        • buy vs. sell activity
        • insider roles and hierarchy
        • total transaction values
        • patterns of executive liquidation or accumulation

    Notes:
    ------
    • This tool only works for companies that file with the U.S. SEC.
    • If the company is not U.S.-domiciled, the agent should skip
      insider analysis based on SEC filings.
    """


    cik = str(cik).zfill(10)
    url = f"{SEC_BASE}/submissions/CIK{cik}.json"

    data = sec_get(url)

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])

    form4_dates = []

    # Collect only Form 4 filings
    for form, date in zip(forms, dates):
        if form == "4":
            form4_dates.append(date)

    if not form4_dates:
        return {
            "cik": cik,
            "form4_count": 0,
            "dates": [],
            "since": None,
            "latest": None
        }

    oldest = min(form4_dates)
    newest = max(form4_dates)

    return {
        "cik": cik,
        "form4_count": len(form4_dates),
        "dates": form4_dates,
        "since": oldest,
        "latest": newest
    }


# -------------------------------------------------------------
# RUN SERVER
# -------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8088)

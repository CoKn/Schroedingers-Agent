from fastmcp import FastMCP
from typing import List, Dict
import requests
import statistics
import os
from dotenv import load_dotenv



# Load API key
load_dotenv()
FMP_API_KEY = os.getenv("FINANCIAL_MODELING_PREP_TOKEN")
FMP_BASE = "https://financialmodelingprep.com/stable"

if not FMP_API_KEY:
    raise RuntimeError("Missing FMP_API_KEY environment variable.")

mcp = FastMCP(
    name="Financial Data & Valuation",
    json_response=True
)

# -------------------------------------------------------------
# Helper: FMP request wrapper
# -------------------------------------------------------------
def fmp_get(endpoint: str, params: dict) -> list:
    params = {k: v for k, v in params.items() if v is not None}
    params["apikey"] = FMP_API_KEY
    url = f"{FMP_BASE}/{endpoint}"
    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json()

# =============================================================
#                    MCP TOOLS (API wrappers)
# =============================================================

# -------------------------------------------------------------
# Company Profile (needed for comps_find_peers)
# -------------------------------------------------------------
@mcp.tool()
def company_profile(symbol: str) -> list:
    """Fetch basic profile including sector, industry, and market cap."""
    return fmp_get("profile", {"symbol": symbol})

# -------------------------------------------------------------
# Stock Screener
# -------------------------------------------------------------
@mcp.tool()
def stock_screener(
    marketCapMoreThan: float | None = None,
    marketCapLowerThan: float | None = None,
    sector: str | None = None,
    industry: str | None = None,
    betaMoreThan: float | None = None,
    betaLowerThan: float | None = None,
    priceMoreThan: float | None = None,
    priceLowerThan: float | None = None,
    dividendMoreThan: float | None = None,
    dividendLowerThan: float | None = None,
    volumeMoreThan: float | None = None,
    volumeLowerThan: float | None = None,
    exchange: str | None = None,
    country: str | None = None,
    isEtf: bool | None = None,
    isFund: bool | None = None,
    isActivelyTrading: bool | None = None,
    limit: int | None = None,
    includeAllShareClasses: bool | None = None,
) -> list:
    params = locals()
    return fmp_get("company-screener", params)

# -------------------------------------------------------------
# Enterprise Value
# -------------------------------------------------------------
@mcp.tool()
def enterprise_values(symbol: str, limit: int | None = None, period: str | None = None) -> list:
    params = locals()
    return fmp_get("enterprise-values", params)

# -------------------------------------------------------------
# Income Statement
# -------------------------------------------------------------
@mcp.tool()
def income_statement(symbol: str, limit: int | None = None, period: str | None = None) -> list:
    params = locals()
    return fmp_get("income-statement", params)

# =============================================================
#             INTERNAL HELPER FOR COMPS VALUATION
# =============================================================

def fetch_company_metrics(symbol: str) -> dict:
    ev_data = enterprise_values(symbol=symbol, limit=1, period="FY")
    if not ev_data:
        raise ValueError(f"No EV data for {symbol}")
    enterprise_value = ev_data[0]["enterpriseValue"]

    is_data = income_statement(symbol=symbol, limit=1, period="FY")
    if not is_data:
        raise ValueError(f"No IS data for {symbol}")
    ebitda = is_data[0]["ebitda"]

    if ebitda is None or enterprise_value is None:
        raise ValueError(f"Missing metrics for {symbol}")

    return {"ebitda": ebitda, "enterprise_value": enterprise_value}

# =============================================================
#                  NEW MCP TOOL: comps_find_peers
# =============================================================

@mcp.tool()
def comps_find_peers(symbol: str, max_peers: int = 10) -> List[str]:
    """
    Automatically find comparable companies based on sector + market cap range.
    """
    # 1. Profile lookup
    profile = company_profile(symbol)
    if not profile:
        raise ValueError(f"No profile data for {symbol}")

    sector = profile[0]["sector"]
    market_cap = profile[0]["mktCap"]

    # 2. Screen similar companies
    screened = stock_screener(
        sector=sector,
        marketCapMoreThan=market_cap * 0.30,
        marketCapLowerThan=market_cap * 3.00,
        isActivelyTrading=True,
        limit=max_peers * 2
    )

    # 3. Filter & limit
    peers = [c["symbol"] for c in screened if c["symbol"] != symbol]
    return peers[:max_peers]

# =============================================================
#          EXISTING TOOL: comps_valuation_range
# =============================================================

@mcp.tool()
def comps_valuation_range(
    target: str,
    peers: List[str],
    primary_multiple: str = "ev_ebitda"
) -> Dict:
    t = fetch_company_metrics(target)
    target_ebitda = t["ebitda"]
    target_ev = t["enterprise_value"]

    peer_multiples = []
    for p in peers:
        pm = fetch_company_metrics(p)
        if pm["ebitda"] > 0:
            peer_multiples.append(pm["enterprise_value"] / pm["ebitda"])

    if not peer_multiples:
        raise ValueError("No valid peer multiples available")

    min_mult = min(peer_multiples)
    median_mult = statistics.median(peer_multiples)
    max_mult = max(peer_multiples)

    low_val = target_ebitda * min_mult
    median_val = target_ebitda * median_mult
    high_val = target_ebitda * max_mult

    discount_pct = ((median_val - target_ev) / target_ev) * 100

    return {
        "current_value": target_ev,
        "valuation_range": {
            "low": low_val,
            "median": median_val,
            "high": high_val
        },
        "discount_premium_pct": discount_pct,
        "peer_multiples": {
            "min": min_mult,
            "median": median_mult,
            "max": max_mult
        }
    }

# =============================================================
# Run server
# =============================================================

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8082)

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
# FMP request wrapper
# -------------------------------------------------------------
def fmp_get(endpoint: str, params: dict) -> list:
    params = {k: v for k, v in params.items() if v is not None}
    params["apikey"] = FMP_API_KEY
    url = f"{FMP_BASE}/{endpoint}"
    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json()


# -------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------
def company_profile(symbol: str) -> dict:
    data = fmp_get("profile", {"symbol": symbol})
    raw = data[0]
    return {
        "symbol": raw.get("symbol"),
        "companyName": raw.get("companyName"),
        "sector": raw.get("sector"),
        "industry": raw.get("industry"),
        "marketCap": raw.get("marketCap"),
        "price": raw.get("price"),
    }


def stock_screener(
    marketCapMoreThan: float | None = None,
    marketCapLowerThan: float | None = None,
    sector: str | None = None,
    industry: str | None = None,
    priceMoreThan: float | None = None,
    priceLowerThan: float | None = None,
    limit: int = 5,
) -> list:
    params = {k: v for k, v in locals().items() if v is not None}
    data = fmp_get("company-screener", params)

    results = []
    for item in data or []:
        if isinstance(item, dict):
            results.append({
                "symbol": item.get("symbol"),
                "companyName": item.get("companyName"),
                "marketCap": item.get("marketCap"),
                "sector": item.get("sector"),
                "industry": item.get("industry"),
                "price": item.get("price"),
            })

    return results


def enterprise_values(symbol: str, limit: int | None = None, period: str | None = None) -> list:
    params = {k: v for k, v in locals().items() if v is not None}
    return fmp_get("enterprise-values", params)


def income_statement(symbol: str, limit: int | None = None, period: str | None = None) -> list:
    params = {k: v for k, v in locals().items() if v is not None}
    return fmp_get("income-statement", params)


def fetch_company_metrics(symbol: str) -> dict:
    """
    Fetch consistent, annual Enterprise Value and EBITDA values.
    Fixes issues where FMP returns mismatched periods or incorrect EV.
    """

    # Pull several rows to ensure we match the correct fiscal year
    ev_data = enterprise_values(symbol=symbol, period="annual", limit=4)
    is_data = income_statement(symbol=symbol, period="annual", limit=4)

    # Convert to dict keyed by fiscalDateEnding
    ev_by_year = {row["date"]: row for row in ev_data if "date" in row}
    is_by_year = {row["date"]: row for row in is_data if "date" in row}

    # Find overlapping fiscal years
    shared_years = sorted(set(ev_by_year.keys()) & set(is_by_year.keys()), reverse=True)

    if not shared_years:
        raise ValueError(f"No matching fiscal-year EV + EBITDA data for {symbol}")

    # Use the most recent matched fiscal year
    year = shared_years[0]
    ev_row = ev_by_year[year]
    is_row = is_by_year[year]

    # FMP often returns incorrect enterpriseValue → reconstruct it manually
    market_cap = ev_row.get("marketCap")
    cash = ev_row.get("cashAndShortTermInvestments")
    debt = ev_row.get("totalDebt")
    ev_raw = ev_row.get("enterpriseValue")

    # Recalculate EV when possible
    if market_cap is not None and cash is not None and debt is not None:
        enterprise_value = (market_cap + debt - cash)
    else:
        # fallback to enterpriseValue, even though it's often wrong
        enterprise_value = ev_raw

    ebitda = is_row.get("ebitda")

    return {
        "ebitda": ebitda,
        "enterprise_value": enterprise_value,
        "fiscal_year": year,
    }



from typing import List, Literal

# =============================================================
# MCP TOOL: comps_find_peers
# =============================================================
@mcp.tool()
def comps_find_peers(
    symbol: str,
    max_peers: int = 10,
    approach: Literal["NORMAL", "CONSERVATIVE"] = "NORMAL"
) -> List[str]:
    """
    Identify comparable peer companies for a given target ticker.

    This tool:
    1. Retrieves the target company's sector, industry, and market cap.
    2. First attempts to find peers in the SAME industry AND sector.
    3. If too few industry-level peers exist, it falls back to sector-only peers.
    4. Market-cap range depends on `approach`:
         - NORMAL:        0.30× to 3.00×
         - CONSERVATIVE:  0.30× to 1.50×
    5. Returns a list of peer ticker symbols ordered by relevance.

    IMPORTANT — RISK-BASED GUIDANCE
    --------------------------------
    If the target company is known to face *strategic*, *financial*, 
    *market*, or *operational* risks — OR if the agent has identified 
    unusual volatility, uncertainty, or instability — the agent should 
    prefer **approach=\"CONSERVATIVE\"**.

    The conservative mode keeps peer selection closer in size, avoiding 
    distortion from extremely large or extremely small comparables. 
    This produces more reliable comps for risk-sensitive situations.

    Parameters
    ----------
    symbol : str
        The ticker symbol of the company to find peers for.
    max_peers : int
        Maximum number of peer tickers to return.
    approach : {"NORMAL", "CONSERVATIVE"}
        NORMAL       = broad comps (0.3–3.0× market cap)
        CONSERVATIVE = size-disciplined comps (0.3–1.5× market cap),
                       recommended when risks are known.

    Returns
    -------
    List[str]
        A list of peer tickers suitable for use in comps_valuation_range.

    Agent Usage Notes
    -----------------
    - Use NORMAL for stable, diversified, or large-cap companies.
    - Use CONSERVATIVE when:
        • the target is undergoing market instability,
        • the sector is volatile,
        • financial performance is uncertain,
        • strategic or operational risks are identified,
        • or when you want a tighter peer set for valuation discipline.
    - This tool should be called BEFORE comps_valuation_range.
    """

    # -------------------------------
    # 1. Retrieve profile
    # -------------------------------
    p = company_profile(symbol)
    sector = p["sector"]
    industry = p["industry"]
    market_cap = p["marketCap"]

    # -------------------------------
    # 2. Determine market cap bounds
    # -------------------------------
    lower_bound = market_cap * 0.30

    if approach == "CONSERVATIVE":
        upper_bound = market_cap * 1.50
    else:
        upper_bound = market_cap * 3.00

    # -------------------------------
    # 3. Industry-level peer search
    # -------------------------------
    industry_screen = stock_screener(
        sector=sector,
        industry=industry,
        marketCapMoreThan=lower_bound,
        marketCapLowerThan=upper_bound,
        limit=max_peers * 5,
    )

    industry_peers = [
        c["symbol"] for c in industry_screen if c["symbol"] != symbol
    ]

    if len(industry_peers) >= max_peers:
        return industry_peers[:max_peers]

    # -------------------------------
    # 4. Sector-level fallback
    # -------------------------------
    sector_screen = stock_screener(
        sector=sector,
        marketCapMoreThan=lower_bound,
        marketCapLowerThan=upper_bound,
        limit=max_peers * 5,
    )

    sector_peers = [
        c["symbol"] for c in sector_screen if c["symbol"] != symbol
    ]

    if len(sector_peers) >= max_peers:
        return sector_peers[:max_peers]

    # -------------------------------
    # 5. Combined fallback
    # -------------------------------
    combined = list(dict.fromkeys(industry_peers + sector_peers))

    return combined[:max_peers]





# =============================================================
# MCP TOOL: comps_valuation_range
# =============================================================
@mcp.tool()
def comps_valuation_range(
    target: str,
    peers: List[str],
    primary_multiple: str = "ev_ebitda"
) -> Dict:
    """
    AGENT INSTRUCTIONS
    ------------------
    The agent MUST pass:
    - target = EXACT ticker returned from resolve_symbol
    - peers = EXACT list returned from comps_find_peers

    The agent MUST NOT invent ticker symbols or modify the lists.
    The agent MUST call this tool only after both required inputs 
    have been produced by earlier tool calls.

    
    Calculate a valuation range for a company using comparable-company
    EV/EBITDA multiples.

    This tool:
    1. Retrieves the target company's EBITDA and enterprise value.
    2. Retrieves each peer company's EBITDA and enterprise value.
    3. Computes EV/EBITDA multiples for all valid peers.
    4. Applies the peer multiples to the target's EBITDA to produce a
       low, median, and high implied valuation.

    Parameters
    ----------
    target : str
        The ticker symbol of the company being valued.
    peers : List[str]
        A list of peer ticker symbols. Typically obtained from
        comps_find_peers.
    primary_multiple : str
        Reserved for future expansion. Currently only "ev_ebitda" is used.

    Returns
    -------
    Dict
        {
            "current_value": <target enterprise value>,
            "current_ebitda": <target ebitda>,
            "valuation_range": {
                "low": <low implied valuation>,
                "median": <median implied valuation>,
                "high": <high implied valuation>
            },
            "peer_multiples": {
                "min": <lowest peer multiple>,
                "median": <median peer multiple>,
                "max": <highest peer multiple>
            }
        }

    Agent Usage Notes
    -----------------
    - Call comps_find_peers first to obtain the peer list.
    - Use the exact output list from comps_find_peers as the `peers` argument.
    - The tool will only compute multiples for peers with positive EBITDA.
    - Use the resulting valuation range to analyze whether the company
      appears undervalued or overvalued.
    """

    # Retrieve target metrics
    t = fetch_company_metrics(target)
    target_ebitda = t["ebitda"]
    target_ev = t["enterprise_value"]

    # Compute peer EV/EBITDA multiples
    peer_multiples = []
    for p in peers:
        pm = fetch_company_metrics(p)
        if pm["ebitda"] > 0:
            peer_multiples.append(pm["enterprise_value"] / pm["ebitda"])

    # Derive min / median / max multiples
    min_mult = min(peer_multiples)
    median_mult = statistics.median(peer_multiples)
    max_mult = max(peer_multiples)

    return {
        "current_value": target_ev,
        "current_ebitda": target_ebitda,
        "valuation_range": {
            "low": target_ebitda * min_mult,
            "median": target_ebitda * median_mult,
            "high": target_ebitda * max_mult
        },
        "peer_multiples": {
            "min": min_mult,
            "median": median_mult,
            "max": max_mult
        }
    }

# =============================================================
# MCP TOOL: resolve_symbol
# =============================================================
@mcp.tool()
def resolve_symbol(query: str) -> dict:
    """
    Resolve a company name into the most appropriate ticker symbol.
    """

    # Agent should NOT control limit
    data = fmp_get("search-name", {"query": query, "limit": 50})

    if not isinstance(data, list) or not data:
        raise ValueError(f"No symbol results found for '{query}'")

    def is_valid_equity(row):
        sym = row.get("symbol", "").upper()
        name = row.get("name", "").upper()

        bad_terms = [
            "ETF", "ETP", "ETN", "FUND", "3X", "2X",
            "SHORT", "LONG", "BEAR", "BULL", "LEV"
        ]
        if any(t in sym for t in bad_terms): return False
        if any(t in name for t in bad_terms): return False
        return True

    equities = [r for r in data if is_valid_equity(r)]
    if not equities:
        raise ValueError(f"No valid equities found for '{query}'")

    def rank(r):
        exch = r.get("exchange", "").upper()
        score = 0

        # Primary listing for Mercedes
        if exch in ("XETRA", "FRA", "DEUTSCHE BÖRSE"):
            score += 100

        # Major US exchanges
        if exch in ("NYSE", "NASDAQ"):
            score += 90

        # OTC fallback
        if exch == "OTC":
            score -= 20

        return score

    sorted_eq = sorted(equities, key=rank, reverse=True)
    best = sorted_eq[0]

    return {
        "symbol": best["symbol"],
        "name": best.get("name"),
        "exchange": best.get("exchange"),
        "currency": best.get("currency"),
        "alternatives": [
            {"symbol": r["symbol"], "exchange": r.get("exchange")}
            for r in sorted_eq[1:]
        ]
    }



# =============================================================
# Run server
# =============================================================
if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8083)

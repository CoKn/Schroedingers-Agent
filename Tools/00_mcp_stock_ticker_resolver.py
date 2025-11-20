from fastmcp import FastMCP
import requests
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
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8089)

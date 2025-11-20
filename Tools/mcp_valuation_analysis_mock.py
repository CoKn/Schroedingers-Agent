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


# company profile (needed for comps_find_peers)
@mcp.tool()
def company_profile(symbol: str) -> list:
    ...

# stock screener
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
    ...

# enterprise vlue
@mcp.tool()
def enterprise_values(symbol: str, limit: int | None = None, period: str | None = None) -> list:
    ...

# income statement
@mcp.tool()
def income_statement(symbol: str, limit: int | None = None, period: str | None = None) -> list:
    ...


#  comps find peers
@mcp.tool()
def comps_find_peers(symbol: str, max_peers: int = 10) -> List[str]:
    ...


# comps valuation range
@mcp.tool()
def comps_valuation_range(
    target: str,
    peers: List[str],
    primary_multiple: str = "ev_ebitda"
) -> Dict:
    ...



if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8083)

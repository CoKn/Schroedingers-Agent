from fastmcp import FastMCP
from typing import List, Dict

import json
from fastmcp import FastMCP

def load_mock(name: str):
    with open(f"Tools/mock_data/{name}.json") as f:
        return json.load(f)


# company profile (needed for comps_find_peers)
def company_profile(symbol: str) -> list:
    return load_mock(f"company_profile_{symbol}")

# stock screener
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
    return load_mock("stock_screener_technology")

# enterprise vlue
def enterprise_values(symbol: str, limit: int | None = None, period: str | None = None) -> list:
    return load_mock(f"enterprise_values_{symbol}")

# income statement
def income_statement(symbol: str, limit: int | None = None, period: str | None = None) -> list:
    return load_mock(f"income_statement_{symbol}")


#  comps find peers
def comps_find_peers(symbol: str, max_peers: int = 10) -> List[str]:
    return load_mock(f"peers_{symbol}")


# comps valuation range
def comps_valuation_range(
    target: str,
    peers: List[str],
    primary_multiple: str = "ev_ebitda"
) -> Dict:
    return load_mock(f"comps_valuation_range_{target}")



if __name__ == "__main__":
    symbol = "SNOW"
    company_profile(symbol)
    stock_screener()
    enterprise_values(symbol)
    income_statement(symbol)
    peers = comps_find_peers(symbol)
    peers
    print(comps_valuation_range(symbol, peers))

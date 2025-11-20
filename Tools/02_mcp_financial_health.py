from fastmcp import FastMCP
from typing import List, Dict
import requests
import statistics
import os
from dotenv import load_dotenv


# -------------------------------------------------------------
# ENV + CONSTANTS
# -------------------------------------------------------------
load_dotenv()
FMP_API_KEY = os.getenv("FINANCIAL_MODELING_PREP_TOKEN")
FMP_BASE = "https://financialmodelingprep.com/stable"

if not FMP_API_KEY:
    raise RuntimeError("Missing FMP_API_KEY environment variable.")

mcp = FastMCP(
    name="Financial Health",
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
# TOOL: fmp_key_metrics  (FINANCIAL HEALTH CHECK)
# =============================================================
@mcp.tool()
def fmp_key_metrics(symbol: str) -> Dict:
    """
    Retrieve ONLY the latest essential financial key metrics for a company.
    Stable format:
        /key-metrics?symbol=AAPL

    Only the fields required for M&A financial health analysis are retained.
    """

    data = fmp_get("key-metrics", {"symbol": symbol, "limit": 1})
    if not data:
        raise ValueError(f"No key metrics found for {symbol}")

    row = data[0]

    return {
        "symbol": symbol,
        "date": row.get("date"),
        "fiscal_year": row.get("fiscalYear"),
        "reported_currency": row.get("reportedCurrency"),

        # Valuation
        "market_cap": row.get("marketCap"),
        "enterprise_value": row.get("enterpriseValue"),
        "ev_to_sales": row.get("evToSales"),
        "ev_to_operating_cf": row.get("evToOperatingCashFlow"),
        "ev_to_fcf": row.get("evToFreeCashFlow"),
        "ev_to_ebitda": row.get("evToEBITDA"),
        "net_debt_to_ebitda": row.get("netDebtToEBITDA"),

        # Liquidity / Capital
        "current_ratio": row.get("currentRatio"),
        "working_capital": row.get("workingCapital"),
        "invested_capital": row.get("investedCapital"),

        # Profitability / Returns
        "return_on_assets": row.get("returnOnAssets"),
        "operating_return_on_assets": row.get("operatingReturnOnAssets"),
        "return_on_equity": row.get("returnOnEquity"),
        "return_on_invested_capital": row.get("returnOnInvestedCapital"),
        "return_on_capital_employed": row.get("returnOnCapitalEmployed"),
        "earnings_yield": row.get("earningsYield"),

        # R&D / Working Capital Behavior
        "research_and_development_to_revenue": row.get("researchAndDevelopementToRevenue"),
        "average_receivables": row.get("averageReceivables"),
        "average_payables": row.get("averagePayables"),
        "average_inventory": row.get("averageInventory"),

        # Operating Cycle Components
        "days_sales_outstanding": row.get("daysOfSalesOutstanding"),
        "days_payables_outstanding": row.get("daysOfPayablesOutstanding"),
        "days_inventory_outstanding": row.get("daysOfInventoryOutstanding"),
        "operating_cycle": row.get("operatingCycle"),
        "cash_conversion_cycle": row.get("cashConversionCycle"),
    }


# =============================================================
# TOOL: fmp_insider_trading (RAW ROLE, NO CLASSIFICATION)
# =============================================================
@mcp.tool()
def fmp_insider_trading(symbol: str) -> Dict:
    """
    Retrieve insider-trading data using:
        /insider-trading/search

    - No artificial role classification.
    - Grouped strictly by FMP's `typeOfOwner` field.
    - Adds `since`: the oldest transaction date in the dataset.
    """

    data = fmp_get("insider-trading/search", {
        "symbol": symbol,
        "page": 0,
        "limit": 100
    })

    if not isinstance(data, list):
        raise ValueError(f"Unexpected insider trading response for {symbol}")

    buys, sells = [], []
    all_dates = []

    # -------------------------------------
    # Aggregation structure by typeOfOwner
    # -------------------------------------
    by_owner = {}

    for row in data:

        position = row.get("typeOfOwner") or "unknown"
        name = row.get("reportingName")

        # Track unique categories
        if position not in by_owner:
            by_owner[position] = {
                "position": position,
                "buy_count": 0,
                "sell_count": 0,
                "total_buy_value": 0,
                "total_sell_value": 0,
                "names": set()
            }

        tx_date = row.get("transactionDate")
        if tx_date:
            all_dates.append(tx_date)

        # Compute transaction value
        value = (row.get("price") or 0) * (row.get("securitiesTransacted") or 0)

        # Transaction dict
        tx = {
            "symbol": row.get("symbol"),
            "filing_date": row.get("filingDate"),
            "transaction_date": tx_date,
            "reporting_cik": row.get("reportingCik"),
            "company_cik": row.get("companyCik"),
            "transaction_type": row.get("transactionType"),
            "securities_owned": row.get("securitiesOwned"),
            "reporting_name": name,
            "type_of_owner": position,
            "acquisition_or_disposition": row.get("acquisitionOrDisposition"),
            "direct_or_indirect": row.get("directOrIndirect"),
            "securities_transacted": row.get("securitiesTransacted"),
            "price": row.get("price"),
            "value": value,
            "security_name": row.get("securityName"),
            "url": row.get("url")
        }

        # Track participant names
        if name:
            by_owner[position]["names"].add(name)

        # Classify buy/sell based on FMP transaction codes
        ttype = (row.get("transactionType") or "").upper()

        if ttype.startswith("P"):  # purchase
            buys.append(tx)
            by_owner[position]["buy_count"] += 1
            by_owner[position]["total_buy_value"] += value

        elif ttype.startswith("S"):  # sale
            sells.append(tx)
            by_owner[position]["sell_count"] += 1
            by_owner[position]["total_sell_value"] += value

    # Convert name sets → lists
    for pos in by_owner.values():
        pos["names"] = list(pos["names"])

    # Determine dataset range
    dataset_since = min(all_dates) if all_dates else None

    # Convert dict → list
    by_position_list = list(by_owner.values())

    # ---------------------------
    # Final response
    # ---------------------------
    return {
        "symbol": symbol,
        "summary": {
            "buy_count": len(buys),
            "sell_count": len(sells),
            "total_buy_value": sum(t["value"] for t in buys),
            "total_sell_value": sum(t["value"] for t in sells),
            "since": dataset_since
        },
        "by_position": by_position_list,
        "buys": buys,
        "sells": sells
    }


# =============================================================
# TOOL: fmp_financial_growth (FULL FIELD SET)
# =============================================================
@mcp.tool()
def fmp_financial_growth(symbol: str) -> Dict:
    """
    Retrieve complete financial growth data using:
        /financial-growth?symbol=XYZ

    This version preserves ALL fields as provided by FMP and included
    in the user-provided JSON schema.
    """

    data = fmp_get("financial-growth", {"symbol": symbol, "limit": 1})
    if not data:
        raise ValueError(f"No financial growth metrics found for {symbol}")

    row = data[0]

    return {
        "symbol": row.get("symbol"),
        "date": row.get("date"),
        "fiscal_year": row.get("fiscalYear"),
        "reported_currency": row.get("reportedCurrency"),

        "growth": {
            # Core growth fields
            "revenue_growth": row.get("revenueGrowth"),
            "gross_profit_growth": row.get("grossProfitGrowth"),
            "ebit_growth": row.get("ebitgrowth"),
            "operating_income_growth": row.get("operatingIncomeGrowth"),
            "net_income_growth": row.get("netIncomeGrowth"),
            "eps_growth": row.get("epsgrowth"),
            "dividends_per_share_growth": row.get("dividendsPerShareGrowth"),

            # Cash flow & working capital growth
            "operating_cf_growth": row.get("operatingCashFlowGrowth"),
            "receivables_growth": row.get("receivablesGrowth"),
            "inventory_growth": row.get("inventoryGrowth"),
            "debt_growth": row.get("debtGrowth"),

            # Expense growth
            "rd_expense_growth": row.get("rdexpenseGrowth"),
            "sga_expense_growth": row.get("sgaexpensesGrowth"),

            # Free cash flow
            "fcf_growth": row.get("freeCashFlowGrowth"),

            # Long-term per-share growth trends
            "tenY_revenue_growth_per_share": row.get("tenYRevenueGrowthPerShare"),
            "fiveY_revenue_growth_per_share": row.get("fiveYRevenueGrowthPerShare"),
            "threeY_revenue_growth_per_share": row.get("threeYRevenueGrowthPerShare"),

            "tenY_operating_CF_growth_per_share": row.get("tenYOperatingCFGrowthPerShare"),
            "fiveY_operating_CF_growth_per_share": row.get("fiveYOperatingCFGrowthPerShare"),
            "threeY_operating_CF_growth_per_share": row.get("threeYOperatingCFGrowthPerShare"),

            "tenY_net_income_growth_per_share": row.get("tenYNetIncomeGrowthPerShare"),
            "fiveY_net_income_growth_per_share": row.get("fiveYNetIncomeGrowthPerShare"),
            "threeY_net_income_growth_per_share": row.get("threeYNetIncomeGrowthPerShare"),

            "tenY_shareholders_equity_growth_per_share": row.get("tenYShareholdersEquityGrowthPerShare"),
            "fiveY_shareholders_equity_growth_per_share": row.get("fiveYShareholdersEquityGrowthPerShare"),
            "threeY_shareholders_equity_growth_per_share": row.get("threeYShareholdersEquityGrowthPerShare"),

            "tenY_dividend_per_share_growth_per_share": row.get("tenYDividendperShareGrowthPerShare"),
            "fiveY_dividend_per_share_growth_per_share": row.get("fiveYDividendperShareGrowthPerShare"),
            "threeY_dividend_per_share_growth_per_share": row.get("threeYDividendperShareGrowthPerShare"),

            # EBITDA growth (last)
            "ebitda_growth": row.get("ebitdaGrowth"),
        }
    }


# =============================================================
# Run server
# =============================================================
if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8086)

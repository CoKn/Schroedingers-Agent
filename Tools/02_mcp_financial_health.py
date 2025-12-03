from fastmcp import FastMCP
from typing import List, Dict
import requests
import os
from dotenv import load_dotenv



# ===================================================================
# ENV + CONSTANTS
# ===================================================================
load_dotenv()

FMP_API_KEY = os.getenv("FINANCIAL_MODELING_PREP_TOKEN")
FMP_BASE = "https://financialmodelingprep.com/stable"

if not FMP_API_KEY:
    raise RuntimeError("Missing FINANCIAL_MODELING_PREP_TOKEN environment variable.")

mcp = FastMCP(
    name="Financial Health Intelligence",
    json_response=True
)



# ===================================================================
# INTERNAL HELPER — STANDARDIZED FMP GET WRAPPER
# ===================================================================
def fmp_get(endpoint: str, params: dict) -> list:
    """
    Standardized GET wrapper for FMP. Ensures:
      • API key injection
      • clean parameter handling
      • uniform raising of HTTP errors
    """
    params = {k: v for k, v in params.items() if v is not None}
    params["apikey"] = FMP_API_KEY
    url = f"{FMP_BASE}/{endpoint}"

    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json()



# ===================================================================
# TOOL 1 — get_company_key_metrics
# ===================================================================
@mcp.tool()
def get_company_key_metrics(symbol: str) -> Dict:
    """
    Retrieve the company's most recent essential financial key metrics.
    
    PURPOSE
    -------
    Provides a **minimal, stable, curated** subset of financial KPIs suitable
    for M&A health assessment, screening, and automated reasoning.

    This tool intentionally returns **only the most decision-relevant fields**:
      • Valuation
      • Liquidity
      • Profitability
      • Capital efficiency
      • Operating cycle components
      • R&D behavior

    INPUT
    -----
    symbol : str  
        Public stock ticker (e.g., "AAPL", "MSFT").

    OUTPUT (JSON)
    -------------
    {
      "symbol": "<ticker>",
      "date": "<YYYY-MM-DD>",
      "fiscal_year": <int>,
      "reported_currency": "<str>",

      "market_cap": <float | null>,
      "enterprise_value": <float | null>,
      "ev_to_sales": <float | null>,
      "ev_to_operating_cf": <float | null>,
      "ev_to_fcf": <float | null>,
      "ev_to_ebitda": <float | null>,
      "net_debt_to_ebitda": <float | null>,

      "current_ratio": <float | null>,
      "working_capital": <float | null>,
      "invested_capital": <float | null>,

      "return_on_assets": <float | null>,
      "operating_return_on_assets": <float | null>,
      "return_on_equity": <float | null>,
      "return_on_invested_capital": <float | null>,
      "return_on_capital_employed": <float | null>,
      "earnings_yield": <float | null>,

      "research_and_development_to_revenue": <float | null>,
      "average_receivables": <float | null>,
      "average_payables": <float | null>,
      "average_inventory": <float | null>,

      "days_sales_outstanding": <float | null>,
      "days_payables_outstanding": <float | null>,
      "days_inventory_outstanding": <float | null>,
      "operating_cycle": <float | null>,
      "cash_conversion_cycle": <float | null>
    }

    AGENT USAGE GUIDE
    -----------------
    Use this tool when evaluating:
      • baseline financial health
      • liquidity strength
      • profitability and return efficiency
      • working capital behavior
      • enterprise value positioning

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

        "market_cap": row.get("marketCap"),
        "enterprise_value": row.get("enterpriseValue"),
        "ev_to_sales": row.get("evToSales"),
        "ev_to_operating_cf": row.get("evToOperatingCashFlow"),
        "ev_to_fcf": row.get("evToFreeCashFlow"),
        "ev_to_ebitda": row.get("evToEBITDA"),
        "net_debt_to_ebitda": row.get("netDebtToEBITDA"),

        "current_ratio": row.get("currentRatio"),
        "working_capital": row.get("workingCapital"),
        "invested_capital": row.get("investedCapital"),

        "return_on_assets": row.get("returnOnAssets"),
        "operating_return_on_assets": row.get("operatingReturnOnAssets"),
        "return_on_equity": row.get("returnOnEquity"),
        "return_on_invested_capital": row.get("returnOnInvestedCapital"),
        "return_on_capital_employed": row.get("returnOnCapitalEmployed"),
        "earnings_yield": row.get("earningsYield"),

        "research_and_development_to_revenue": row.get("researchAndDevelopementToRevenue"),
        "average_receivables": row.get("averageReceivables"),
        "average_payables": row.get("averagePayables"),
        "average_inventory": row.get("averageInventory"),

        "days_sales_outstanding": row.get("daysOfSalesOutstanding"),
        "days_payables_outstanding": row.get("daysOfPayablesOutstanding"),
        "days_inventory_outstanding": row.get("daysOfInventoryOutstanding"),
        "operating_cycle": row.get("operatingCycle"),
        "cash_conversion_cycle": row.get("cashConversionCycle"),
    }



# ===================================================================
# TOOL 2 — get_company_insider_trading_activity
# ===================================================================
@mcp.tool()
def get_detailed_insider_trading_activity(symbol: str) -> Dict:
    """
    Retrieve insider-trading data for a company (raw, unclassified).

    PURPOSE
    -------
    Provides the **baseline raw insider activity dataset**:
      • purchase vs. sale counts
      • total values transacted
      • full transaction list
      • owners grouped by FMP's `typeOfOwner`

    This is the *raw, factual feed* used for:
      • M&A anomaly detection
      • corporate governance risk evaluation
      • signal-based heuristic reasoning

    INPUT
    -----
    symbol : str  
        Public stock ticker (e.g., "NVDA").

    OUTPUT (JSON)
    -------------
    {
      "symbol": "<ticker>",
      "summary": {
        "buy_count": <int>,
        "sell_count": <int>,
        "total_buy_value": <float>,
        "total_sell_value": <float>,
        "since": "<YYYY-MM-DD | null>"
      },

      "by_position": [
        {
          "position": "<FMP typeOfOwner>",
          "buy_count": <int>,
          "sell_count": <int>,
          "total_buy_value": <float>,
          "total_sell_value": <float>,
          "names": ["<insider1>", "<insider2>", ...]
        }
      ],

      "buys": [ {<full transaction>} ],
      "sells": [ {<full transaction>} ]
    }

    Each transaction object contains:
    {
      "symbol": "<ticker>",
      "filing_date": "<YYYY-MM-DD>",
      "transaction_date": "<YYYY-MM-DD>",
      "reporting_cik": "<string>",
      "company_cik": "<string>",
      "transaction_type": "<string>",
      "securities_owned": <int | null>,
      "reporting_name": "<string>",
      "type_of_owner": "<string>",
      "acquisition_or_disposition": "<A|D|null>",
      "direct_or_indirect": "<D|I|null>",
      "securities_transacted": <int>,
      "price": <float>,
      "value": <float>,
      "security_name": "<string>",
      "url": "<SEC filing URL>"
    }

    AGENT USAGE GUIDE
    -----------------
    Use this tool when evaluating:
      • leadership behavior patterns
      • potential red flags before M&A
      • insider buying pressure (bullish signal)
      • liquidation patterns (bearish or distress signal)
      • alignment or misalignment with market conditions
      • use this tool if the tool "sec_get_insider_activity_summary" shows unusual activity

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
    by_owner = {}

    for row in data:
        position = row.get("typeOfOwner") or "unknown"
        name = row.get("reportingName")

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

        value = (row.get("price") or 0) * (row.get("securitiesTransacted") or 0)

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

        if name:
            by_owner[position]["names"].add(name)

        ttype = (row.get("transactionType") or "").upper()

        if ttype.startswith("P"):
            buys.append(tx)
            by_owner[position]["buy_count"] += 1
            by_owner[position]["total_buy_value"] += value

        elif ttype.startswith("S"):
            sells.append(tx)
            by_owner[position]["sell_count"] += 1
            by_owner[position]["total_sell_value"] += value

    for pos in by_owner.values():
        pos["names"] = list(pos["names"])

    return {
        "symbol": symbol,
        "summary": {
            "buy_count": len(buys),
            "sell_count": len(sells),
            "total_buy_value": sum(t["value"] for t in buys),
            "total_sell_value": sum(t["value"] for t in sells),
            "since": min(all_dates) if all_dates else None
        },
        "by_position": list(by_owner.values()),
        "buys": buys,
        "sells": sells
    }



# ===================================================================
# TOOL 3 — get_company_financial_growth
# ===================================================================
@mcp.tool()
def get_company_financial_growth(symbol: str) -> Dict:
    """
    Retrieve a complete financial-growth snapshot from FMP.

    PURPOSE
    -------
    Provides the **broadest historical growth profile** of a company.
    The entire FMP dataset is preserved to support:
      • revenue/earnings trend analysis
      • long-term growth evaluation
      • performance benchmarking
      • M&A due-diligence modeling

    INPUT
    -----
    symbol : str  
        Public ticker.

    OUTPUT (JSON)
    -------------
    {
      "symbol": "<str>",
      "date": "<YYYY-MM-DD>",
      "fiscal_year": <int>,
      "reported_currency": "<str>",

      "growth": {
        "revenue_growth": <float>,
        "gross_profit_growth": <float>,
        "ebit_growth": <float>,
        "operating_income_growth": <float>,
        "net_income_growth": <float>,
        "eps_growth": <float>,
        "dividends_per_share_growth": <float>,
        "operating_cf_growth": <float>,
        "receivables_growth": <float>,
        "inventory_growth": <float>,
        "debt_growth": <float>,
        "rd_expense_growth": <float>,
        "sga_expense_growth": <float>,
        "fcf_growth": <float>,

        "tenY_revenue_growth_per_share": <float>,
        "fiveY_revenue_growth_per_share": <float>,
        "threeY_revenue_growth_per_share": <float>,

        "tenY_operating_CF_growth_per_share": <float>,
        "fiveY_operating_CF_growth_per_share": <float>,
        "threeY_operating_CF_growth_per_share": <float>,

        "tenY_net_income_growth_per_share": <float>,
        "fiveY_net_income_growth_per_share": <float>,
        "threeY_net_income_growth_per_share": <float>,

        "tenY_shareholders_equity_growth_per_share": <float>,
        "fiveY_shareholders_equity_growth_per_share": <float>,
        "threeY_shareholders_equity_growth_per_share": <float>,

        "tenY_dividend_per_share_growth_per_share": <float>,
        "fiveY_dividend_per_share_growth_per_share": <float>,
        "threeY_dividend_per_share_growth_per_share": <float>,

        "ebitda_growth": <float>
      }
    }

    AGENT USAGE GUIDE
    -----------------
    This tool should be used when analyzing:
      • long-term trend stability  
      • multi-year performance trajectory  
      • investment attractiveness  
      • sustained or declining growth patterns  
      • strategic momentum  

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
            "revenue_growth": row.get("revenueGrowth"),
            "gross_profit_growth": row.get("grossProfitGrowth"),
            "ebit_growth": row.get("ebitgrowth"),
            "operating_income_growth": row.get("operatingIncomeGrowth"),
            "net_income_growth": row.get("netIncomeGrowth"),
            "eps_growth": row.get("epsgrowth"),
            "dividends_per_share_growth": row.get("dividendsPerShareGrowth"),

            "operating_cf_growth": row.get("operatingCashFlowGrowth"),
            "receivables_growth": row.get("receivablesGrowth"),
            "inventory_growth": row.get("inventoryGrowth"),
            "debt_growth": row.get("debtGrowth"),

            "rd_expense_growth": row.get("rdexpenseGrowth"),
            "sga_expense_growth": row.get("sgaexpensesGrowth"),
            "fcf_growth": row.get("freeCashFlowGrowth"),

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

            "ebitda_growth": row.get("ebitdaGrowth"),
        }
    }



# ===================================================================
# RUN SERVER
# ===================================================================
if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8083
    )

"""
Three prompt levels for M&A agent evaluation.
Each prompt tests different instruction granularities.
"""

PROMPTS = {
    "detailed": """Perform a complete institutional-grade M&A investment evaluation of Microsoft Corporation (MSFT).

Execute the following analytical workflow systematically:

1. VALUATION ANALYSIS
   - Resolve the company ticker symbol to ensure correct entity identification
   - Identify comparable companies based on sector, industry, and market capitalization
   - Perform comparable company valuation using EV/EBITDA multiples
   - Document the valuation range (low, median, high)

2. FINANCIAL HEALTH ASSESSMENT
   - Extract key financial metrics (liquidity, profitability, efficiency ratios)
   - Analyze financial growth trends across revenue, earnings, and cash flow
   - Assess historical performance stability

3. CORPORATE STRATEGY REVIEW
   - Lookup company CIK identifier in SEC database
   - Extract strategy sections from recent SEC filings (10-K, 10-Q)
   - Analyze business model, strategic direction, and management commentary

4. GOVERNANCE & INSIDER ACTIVITY MONITORING
   - Review SEC Form 4 insider trading activity summary
   - Assess transaction patterns for potential red flags
   - IF elevated or suspicious insider activity is detected:
     * Perform detailed insider trading analysis with transaction-level granularity
     * Retrieve news and sentiment data to contextualize insider behavior
     * IF anomalies are confirmed after investigation:
       - Re-run comparable company analysis with CONSERVATIVE mode (stricter peer criteria)
       - Recalculate valuation using conservative assumptions
     * ELSE: proceed with original valuation

5. FINAL SYNTHESIS
   - Consolidate findings across all analytical dimensions
   - Provide investment recommendation with clear risk assessment
   - Highlight any material concerns discovered during analysis

CRITICAL: Adapt your analytical approach based on findings. Use conservative assumptions if material risks (especially governance-related) are detected during execution. Your analysis should be systematic, data-driven, and responsive to anomalies.""",

    "medium": """Perform a complete institutional-grade M&A investment evaluation of Microsoft Corporation (MSFT).

Your analysis should cover:
- Valuation using comparable company analysis (EV/EBITDA multiples)
- Financial health assessment (key metrics and growth trends)
- Corporate strategy review from SEC filings
- Governance risks and insider trading activity analysis

Important: Adapt your analysis approach based on findings. If you detect suspicious patterns (particularly elevated insider trading activity), perform deeper investigation:
- Get detailed transaction-level insider trading data
- Check recent news and sentiment
- If concerns are confirmed, re-run valuation with more conservative assumptions

Provide a comprehensive investment recommendation that synthesizes findings across all dimensions and highlights any material risks discovered.""",

    "abstract": """Perform a complete institutional-grade M&A investment evaluation of Microsoft Corporation (MSFT). 

Provide a comprehensive analysis covering valuation, financial health, strategic position, governance risks, and insider activity. 

Adapt your analysis approach based on findings—use conservative assumptions if material risks are detected."""
}


def get_prompt(level: str) -> str:
    """
    Get prompt for specified level.
    
    Args:
        level: One of "detailed", "medium", "abstract"
        
    Returns:
        The prompt string
        
    Raises:
        ValueError: If level is not recognized
    """
    if level not in PROMPTS:
        raise ValueError(f"Unknown prompt level: {level}. Must be one of {list(PROMPTS.keys())}")
    return PROMPTS[level]


def get_all_prompts() -> dict:
    """Return all prompts as a dictionary."""
    return PROMPTS.copy()

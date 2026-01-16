#!/usr/bin/env python3
"""
Comprehensive agent evaluation analysis.

Computes all evaluation metrics: workflow completion, tool coverage,
replanning detection, error rates, and end-to-end success.
"""

import json
import argparse
import re
from pathlib import Path
from collections import Counter, defaultdict


# Expected tools for completeness check
EXPECTED_TOOLS = {
    "resolve_stock_ticker_symbol",
    "find_comparable_companies",
    "comparable_company_valuation",
    "get_company_key_metrics",
    "get_company_financial_growth",
    "sec_lookup_company_cik_by_ticker",
    "sec_extract_company_strategy_sections_from_filings",
    "sec_get_insider_activity_summary",
    "get_detailed_insider_trading_activity",
    "alternative_data_news_sentiment",
}

# Error patterns
ERROR_PATTERNS = {
    "http_error": re.compile(r"\b(4\d\d|5\d\d)\b|Client Error|Server Error|Too Many Requests", re.I),
    "json_format_error": re.compile(r"Expecting .*line \d+ column", re.I),
    "tool_argument_mismatch": re.compile(r"missing .*argument|invalid .*argument|TypeError", re.I),
    "tool_failure": re.compile(r"tool error|failed to call tool|Traceback", re.I),
}


def load_results(path: Path):
    """Load results from JSONL file."""
    results = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results


def extract_tool_calls(result_record):
    """Extract all tool calls from result."""
    calls = []
    result = result_record.get("result", {})
    
    if "error" in result:
        return calls
    
    trace = result.get("trace", [])
    for i, step in enumerate(trace):
        decision = step.get("decision")
        if not isinstance(decision, dict):
            continue
        tool_name = decision.get("call_function")
        if tool_name:
            calls.append({
                "name": tool_name,
                "step": i,
                "result": step.get("tool_result")
            })
    
    return calls


def classify_tool_result(tool_result) -> tuple[bool, list]:
    """
    Classify if tool call was successful.
    Returns (success: bool, error_types: list)
    """
    if tool_result is None:
        return False, ["missing_result"]
    
    text = tool_result if isinstance(tool_result, str) else json.dumps(tool_result)
    error_types = []
    
    for name, pattern in ERROR_PATTERNS.items():
        if pattern.search(text):
            error_types.append(name)
    
    if "Error" in text and not error_types:
        error_types.append("generic_error")
    
    success = len(error_types) == 0
    return success, error_types


def detect_replanning(tool_calls):
    """
    Detect if replanning occurred.
    
    Replanning sequence:
    1. sec_get_insider_activity_summary (baseline)
    2. get_detailed_insider_trading_activity (investigation)
    3. alternative_data_news_sentiment (context)
    4. (optional) conservative revaluation
    """
    tool_names = [c["name"] for c in tool_calls]
    
    # Check for baseline monitoring
    has_baseline = "sec_get_insider_activity_summary" in tool_names
    if not has_baseline:
        return {"replanning": False, "reason": "no_baseline_check"}
    
    # Check for detailed investigation
    has_detailed = "get_detailed_insider_trading_activity" in tool_names
    has_sentiment = "alternative_data_news_sentiment" in tool_names
    
    if not has_detailed or not has_sentiment:
        return {"replanning": False, "reason": "incomplete_investigation"}
    
    # Check ordering
    baseline_idx = tool_names.index("sec_get_insider_activity_summary")
    detailed_idx = tool_names.index("get_detailed_insider_trading_activity")
    sentiment_idx = tool_names.index("alternative_data_news_sentiment")
    
    if not (baseline_idx < detailed_idx < sentiment_idx):
        return {"replanning": False, "reason": "incorrect_order"}
    
    # Check for conservative revaluation
    has_conservative = False
    if "find_comparable_companies" in tool_names[sentiment_idx:]:
        has_conservative = True
    
    return {
        "replanning": True,
        "conservative_revaluation": has_conservative,
        "reason": "full_sequence"
    }


def analyze_run(result_record):
    """Analyze a single run and compute all metrics."""
    result = result_record.get("result", {})
    
    # Check for errors
    if "error" in result:
        return {
            "run": result_record.get("run_number", 0),
            "success": False,
            "error": result.get("error"),
            "tool_calls": 0,
            "tool_success_rate": 0.0,
            "replanning": False,
        }
    
    # Extract tool calls
    tool_calls = extract_tool_calls(result_record)
    
    if not tool_calls:
        return {
            "run": result_record.get("run_number", 0),
            "success": False,
            "error": "no_tool_calls",
            "tool_calls": 0,
            "tool_success_rate": 0.0,
            "replanning": False,
        }
    
    # Classify tool successes
    successes = 0
    all_errors = []
    for call in tool_calls:
        success, errors = classify_tool_result(call["result"])
        if success:
            successes += 1
        all_errors.extend(errors)
    
    tool_success_rate = successes / len(tool_calls)
    
    # Check completeness
    tool_names = {c["name"] for c in tool_calls}
    completeness = len(tool_names & EXPECTED_TOOLS) / len(EXPECTED_TOOLS)
    
    # Detect replanning
    replanning_info = detect_replanning(tool_calls)
    
    # Determine end-to-end success
    # Criteria: >50% tool success, >50% completeness, no critical errors
    major_categories = {
        "valuation": {"resolve_stock_ticker_symbol", "find_comparable_companies", "comparable_company_valuation"},
        "financial": {"get_company_key_metrics", "get_company_financial_growth"},
        "strategy": {"sec_lookup_company_cik_by_ticker", "sec_extract_company_strategy_sections_from_filings"},
    }
    
    category_coverage = sum(
        1 for tools in major_categories.values()
        if tool_names & tools
    ) / len(major_categories)
    
    e2e_success = (
        tool_success_rate > 0.5 and
        category_coverage >= 0.67 and  # At least 2/3 categories covered
        completeness > 0.4
    )
    
    return {
        "run": result_record.get("run_number", 0),
        "success": e2e_success,
        "tool_calls": len(tool_calls),
        "tool_success_rate": tool_success_rate,
        "completeness": completeness,
        "replanning": replanning_info["replanning"],
        "conservative_revaluation": replanning_info.get("conservative_revaluation", False),
        "errors": all_errors,
    }


def print_summary(level: str, analyses: list):
    """Print summary statistics for a prompt level."""
    print(f"\n{'='*60}")
    print(f"{level.upper()} PROMPT - SUMMARY")
    print("="*60)
    
    n = len(analyses)
    if n == 0:
        print("No runs")
        return
    
    # Success rates
    successes = sum(1 for a in analyses if a["success"])
    replanning_count = sum(1 for a in analyses if a["replanning"])
    conservative_count = sum(1 for a in analyses if a.get("conservative_revaluation", False))
    
    # Averages
    avg_tool_success = sum(a["tool_success_rate"] for a in analyses) / n
    avg_completeness = sum(a["completeness"] for a in analyses) / n
    avg_tool_calls = sum(a["tool_calls"] for a in analyses) / n
    
    # Error statistics
    all_errors = []
    for a in analyses:
        all_errors.extend(a.get("errors", []))
    error_counts = Counter(all_errors)
    
    print(f"\nRuns analyzed: {n}")
    print(f"End-to-end success: {successes}/{n} ({successes/n:.1%})")
    print(f"Replanning detected: {replanning_count}/{n} ({replanning_count/n:.1%})")
    print(f"Conservative revaluation: {conservative_count}/{n} ({conservative_count/n:.1%})")
    
    print(f"\nAverage metrics:")
    print(f"  Tool success rate: {avg_tool_success:.1%}")
    print(f"  Planning completeness: {avg_completeness:.1%}")
    print(f"  Tool calls per run: {avg_tool_calls:.1f}")
    
    if error_counts:
        print(f"\nError distribution:")
        for error_type, count in error_counts.most_common(5):
            print(f"  {error_type}: {count} ({count/n:.2f} per run)")
    
    print(f"\nPer-run breakdown:")
    for a in analyses:
        status = "✓" if a["success"] else "✗"
        replan = "R" if a["replanning"] else " "
        conserv = "C" if a.get("conservative_revaluation") else " "
        print(f"  {status} Run {a['run']:2d} [{replan}{conserv}]: "
              f"{a['tool_success_rate']:.0%} tool success, "
              f"{a['completeness']:.0%} complete, "
              f"{a['tool_calls']} tools")


def main():
    parser = argparse.ArgumentParser(description="Comprehensive evaluation analysis")
    parser.add_argument("--results-dir", type=str, default="evaluation_results",
                       help="Directory containing results JSONL files")
    
    args = parser.parse_args()
    results_dir = Path(args.results_dir)
    
    print("\n" + "="*60)
    print("COMPREHENSIVE EVALUATION ANALYSIS")
    print("="*60)
    
    all_analyses = {}
    
    for level in ["detailed", "medium", "abstract"]:
        results_path = results_dir / f"results_{level}.jsonl"
        
        if not results_path.exists():
            print(f"\n[WARN] {level.upper()}: Results file not found")
            continue
        
        results = load_results(results_path)
        analyses = [analyze_run(r) for r in results]
        all_analyses[level] = analyses
        
        print_summary(level, analyses)
    
    # Overall summary
    if all_analyses:
        print(f"\n{'='*60}")
        print("OVERALL SUMMARY")
        print("="*60)
        
        total_runs = sum(len(a) for a in all_analyses.values())
        total_success = sum(sum(1 for r in a if r["success"]) for a in all_analyses.values())
        total_replanning = sum(sum(1 for r in a if r["replanning"]) for a in all_analyses.values())
        
        print(f"\nTotal runs: {total_runs}")
        print(f"Overall success rate: {total_success}/{total_runs} ({total_success/total_runs:.1%})")
        print(f"Overall replanning rate: {total_replanning}/{total_runs} ({total_replanning/total_runs:.1%})")


if __name__ == "__main__":
    main()

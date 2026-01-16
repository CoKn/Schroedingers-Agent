#!/usr/bin/env python3
"""
Tool coverage analysis.

Computes which core workflow tools were used across runs.
"""

import json
import argparse
from pathlib import Path
import yaml
from collections import defaultdict


def load_workflow(path: Path):
    """Load workflow and extract core (non-branch) tools."""
    with path.open("r", encoding="utf-8") as f:
        wf = yaml.safe_load(f).get("workflow", [])
    
    core_tools = []
    for node in wf:
        if node.get("type") == "branch":
            continue  # Exclude branch tools
        tools = node.get("tools", []) or []
        core_tools.extend(tools)
    
    return core_tools


def load_results(path: Path):
    """Load results from JSONL file."""
    results = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results


def extract_used_tools(result_record):
    """Extract tool names from result."""
    used = []
    result = result_record.get("result", {})
    
    if "error" in result:
        return used
    
    trace = result.get("trace", [])
    for step in trace:
        decision = step.get("decision")
        if not isinstance(decision, dict):
            continue
        tool = decision.get("call_function")
        if tool:
            used.append(tool)
    
    return used


def compute_coverage(used_tools, expected_tools):
    """Compute coverage score and identify missing/unexpected tools."""
    used = set(used_tools)
    expected = set(expected_tools)
    
    hits = used & expected
    coverage = len(hits) / len(expected) if expected else 0.0
    missing = list(expected - used)
    unexpected = list(used - expected)
    
    return coverage, missing, unexpected


def analyze_results(results_path: Path, expected_tools: list):
    """Analyze tool coverage for results file."""
    results = load_results(results_path)
    
    run_data = []
    for record in results:
        used_tools = extract_used_tools(record)
        coverage, missing, unexpected = compute_coverage(used_tools, expected_tools)
        
        run_data.append({
            "run": record.get("run_number", 0),
            "coverage": coverage,
            "missing": missing,
            "unexpected": unexpected,
            "used_tools": used_tools
        })
    
    return run_data


def main():
    parser = argparse.ArgumentParser(description="Analyze tool coverage")
    parser.add_argument("--results-dir", type=str, default="evaluation_results",
                       help="Directory containing results JSONL files")
    parser.add_argument("--workflow", type=str, default="workflow_stable.yaml",
                       help="Path to workflow specification")
    
    args = parser.parse_args()
    
    results_dir = Path(args.results_dir)
    workflow_path = Path(args.workflow)
    
    if not workflow_path.exists():
        print(f"Error: Workflow file not found: {workflow_path}")
        return
    
    expected_tools = load_workflow(workflow_path)
    
    print("\n" + "="*60)
    print("TOOL COVERAGE ANALYSIS")
    print("="*60)
    print(f"\nExpected core tools ({len(expected_tools)}):")
    for t in expected_tools:
        print(f"  - {t}")
    
    for level in ["detailed", "medium", "abstract"]:
        results_path = results_dir / f"results_{level}.jsonl"
        
        if not results_path.exists():
            print(f"\n[WARN] {level.upper()}: Results file not found")
            continue
        
        print(f"\n{'='*60}")
        print(f"{level.upper()} PROMPT")
        print("="*60)
        
        run_data = analyze_results(results_path, expected_tools)
        
        if not run_data:
            print("No valid results")
            continue
        
        coverages = [r["coverage"] for r in run_data]
        avg_coverage = sum(coverages) / len(coverages)
        
        print(f"\nAverage core tool coverage: {avg_coverage:.1%}")
        print(f"\nPer-run breakdown:")
        
        for data in run_data:
            print(f"\n  Run {data['run']:2d}: {data['coverage']:.1%}")
            if data['missing']:
                print(f"    Missing: {', '.join(data['missing'][:3])}" + 
                     (f" (+{len(data['missing'])-3} more)" if len(data['missing']) > 3 else ""))
            if data['unexpected']:
                print(f"    Unexpected: {', '.join(data['unexpected'][:3])}" +
                     (f" (+{len(data['unexpected'])-3} more)" if len(data['unexpected']) > 3 else ""))


if __name__ == "__main__":
    main()

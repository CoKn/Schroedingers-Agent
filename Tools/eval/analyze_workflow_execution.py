#!/usr/bin/env python3
"""
Workflow execution evaluation.

Computes workflow completion scores by comparing executed tools
against the expected workflow specification.
"""

import json
import argparse
from pathlib import Path
import yaml
from collections import defaultdict


def load_workflow(path: Path):
    """Load workflow specification from YAML."""
    with path.open("r", encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    return wf.get("workflow", [])


def load_results(path: Path):
    """Load results from JSONL file."""
    results = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results


def extract_used_tools(result_record):
    """Extract tool calls from a result record."""
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


def collect_branch_tools(branch_node):
    """Collect all tools from a branch recursively."""
    tools = []
    
    def walk(nodes):
        for n in nodes:
            tools.extend(n.get("tools", []) or [])
            if n.get("type") == "branch":
                walk(n.get("yes") or [])
                walk(n.get("no") or [])
    
    walk(branch_node.get("yes") or [])
    walk(branch_node.get("no") or [])
    return tools


def compute_step_progress(used_tools, workflow):
    """
    Compute workflow completion as fraction of steps completed.
    
    A step is completed if all its tools were executed.
    Branch steps only count if triggered (at least one branch tool used).
    """
    used = set(used_tools)
    completed = 0
    total = 0
    
    for node in workflow:
        step_type = node.get("type")
        tools = node.get("tools", []) or []
        
        # Branch step - only counts if triggered
        if step_type == "branch":
            branch_tools = collect_branch_tools(node)
            triggered = any(t in used for t in branch_tools)
            if not triggered:
                continue  # Don't count untriggered branches
            total += 1
            if all(t in used for t in branch_tools if t):  # All triggered tools completed
                completed += 1
            continue
        
        # Core step - always counts
        total += 1
        if not tools:  # Steps with no tools (e.g., synthesis)
            completed += 1
        elif all(t in used for t in tools):
            completed += 1
    
    return completed / total if total else 0.0


def evaluate_results(results_path: Path, workflow_path: Path):
    """Evaluate workflow execution for a single results file."""
    workflow = load_workflow(workflow_path)
    results = load_results(results_path)
    
    scores = []
    for record in results:
        used_tools = extract_used_tools(record)
        score = compute_step_progress(used_tools, workflow)
        scores.append({
            "run": record.get("run_number", 0),
            "score": score,
            "tools_used": len(used_tools)
        })
    
    return scores


def main():
    parser = argparse.ArgumentParser(description="Evaluate workflow execution")
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
    
    print("\n" + "="*60)
    print("WORKFLOW EXECUTION EVALUATION")
    print("="*60)
    
    for level in ["detailed", "medium", "abstract"]:
        results_path = results_dir / f"results_{level}.jsonl"
        
        if not results_path.exists():
            print(f"\n[WARN] {level.upper()}: Results file not found")
            continue
        
        print(f"\n{level.upper()} PROMPT")
        print("-" * 40)
        
        scores = evaluate_results(results_path, workflow_path)
        
        if not scores:
            print("No valid results")
            continue
        
        avg_score = sum(s["score"] for s in scores) / len(scores)
        avg_tools = sum(s["tools_used"] for s in scores) / len(scores)
        
        print(f"Runs analyzed: {len(scores)}")
        print(f"Average workflow completion: {avg_score:.1%}")
        print(f"Average tools used: {avg_tools:.1f}")
        
        print(f"\nPer-run breakdown:")
        for s in scores:
            print(f"  Run {s['run']:2d}: {s['score']:.1%} ({s['tools_used']} tools)")


if __name__ == "__main__":
    main()

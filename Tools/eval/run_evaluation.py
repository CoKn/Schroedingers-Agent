#!/usr/bin/env python3
"""
Main evaluation runner for M&A agent.

Runs the agent with three prompt levels (detailed, medium, abstract),
executes 10 runs per level, and saves results for later analysis.

Usage:
    python run_evaluation.py [--runs 10] [--delay 300] [--output-dir results]
"""

import os
import json
import time
import argparse
import requests
from datetime import datetime
from pathlib import Path
from prompts import get_prompt, get_all_prompts


# Agent API configuration
API_URL = "http://localhost:8080/agent"
API_HEADERS = {
    "Authorization": "Bearer devtoken123",
    "Content-Type": "application/json",
}


def call_agent(prompt: str) -> dict:
    """
    Call the agent API with given prompt.
    
    Args:
        prompt: The prompt to send
        
    Returns:
        dict: Agent response as JSON, or error dict
    """
    try:
        payload = {"prompt": prompt}
        response = requests.post(API_URL, headers=API_HEADERS, json=payload, timeout=600)
        response.raise_for_status()
        
        try:
            return response.json()
        except ValueError:
            return {
                "error": "json_parse_failed",
                "raw_response": response.text
            }
            
    except requests.exceptions.RequestException as e:
        return {
            "error": "http_error",
            "message": str(e)
        }


def save_result(output_dir: Path, prompt_level: str, run_number: int, result: dict):
    """
    Save a single run result to file.
    
    Args:
        output_dir: Output directory
        prompt_level: "detailed", "medium", or "abstract"
        run_number: Run number (1-indexed)
        result: Agent response dict
    """
    filename = output_dir / f"results_{prompt_level}.jsonl"
    
    # Append to JSONL file (one JSON object per line)
    with open(filename, "a", encoding="utf-8") as f:
        record = {
            "prompt_level": prompt_level,
            "run_number": run_number,
            "timestamp": datetime.now().isoformat(),
            "result": result
        }
        f.write(json.dumps(record) + "\n")


def run_evaluation_set(prompt_level: str, num_runs: int, delay: int, output_dir: Path):
    """
    Run evaluation for a single prompt level.
    
    Args:
        prompt_level: "detailed", "medium", or "abstract"
        num_runs: Number of runs to execute
        delay: Delay in seconds between runs
        output_dir: Output directory
    """
    print(f"\n{'='*60}")
    print(f"Starting {prompt_level.upper()} prompt evaluation")
    print(f"{'='*60}")
    
    prompt = get_prompt(prompt_level)
    
    for i in range(1, num_runs + 1):
        print(f"\n[{prompt_level.upper()}] Run {i}/{num_runs}")
        print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            result = call_agent(prompt)
            save_result(output_dir, prompt_level, i, result)
            
            if "error" in result:
                print(f"❌ Error: {result.get('error')} - {result.get('message', 'N/A')}")
            else:
                print(f"✓ Success - response saved")
                
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            error_result = {"error": "unexpected", "message": str(e)}
            save_result(output_dir, prompt_level, i, error_result)
        
        # Delay before next run (except after last one)
        if i < num_runs:
            print(f"Waiting {delay}s before next run...")
            time.sleep(delay)


def create_summary(output_dir: Path):
    """Create evaluation summary file."""
    summary_path = output_dir / "evaluation_summary.txt"
    
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("M&A Agent Evaluation Summary\n")
        f.write("=" * 60 + "\n")
        f.write(f"Evaluation completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        for level in ["detailed", "medium", "abstract"]:
            result_file = output_dir / f"results_{level}.jsonl"
            if result_file.exists():
                with open(result_file, "r") as rf:
                    lines = rf.readlines()
                    f.write(f"{level.upper()}: {len(lines)} runs\n")
            else:
                f.write(f"{level.upper()}: 0 runs (file not found)\n")
        
        f.write("\nResult files:\n")
        f.write("  - results_detailed.jsonl\n")
        f.write("  - results_medium.jsonl\n")
        f.write("  - results_abstract.jsonl\n")
        f.write("\nUse analysis scripts to evaluate these results.\n")
    
    print(f"\n✓ Summary written to {summary_path}")


def main():
    parser = argparse.ArgumentParser(description="Run M&A agent evaluation")
    parser.add_argument("--runs", type=int, default=10, help="Number of runs per prompt level")
    parser.add_argument("--delay", type=int, default=300, help="Delay between runs in seconds (default: 300 = 5 min)")
    parser.add_argument("--output-dir", type=str, default="evaluation_results", help="Output directory")
    parser.add_argument("--levels", nargs="+", choices=["detailed", "medium", "abstract"], 
                       default=["detailed", "medium", "abstract"],
                       help="Which prompt levels to run (default: all)")
    
    args = parser.parse_args()
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*60)
    print("M&A AGENT EVALUATION")
    print("="*60)
    print(f"Configuration:")
    print(f"  - Runs per level: {args.runs}")
    print(f"  - Delay between runs: {args.delay}s")
    print(f"  - Output directory: {output_dir}")
    print(f"  - Prompt levels: {', '.join(args.levels)}")
    print(f"  - Total runs: {len(args.levels) * args.runs}")
    
    estimated_time = len(args.levels) * args.runs * (args.delay + 60) / 60  # rough estimate
    print(f"  - Estimated time: ~{estimated_time:.1f} minutes")
    
    input("\nPress ENTER to start evaluation...")
    
    start_time = time.time()
    
    # Run evaluation for each prompt level
    for level in args.levels:
        run_evaluation_set(level, args.runs, args.delay, output_dir)
    
    elapsed_time = (time.time() - start_time) / 60
    
    print("\n" + "="*60)
    print("EVALUATION COMPLETE")
    print("="*60)
    print(f"Total time: {elapsed_time:.1f} minutes")
    print(f"Results saved to: {output_dir}")
    
    # Create summary
    create_summary(output_dir)


if __name__ == "__main__":
    main()

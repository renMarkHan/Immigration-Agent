#!/usr/bin/env python3
"""
Evaluation runner for Role D.
Usage: python eval/run_evaluation.py

Workflow:
  1. Run pipeline on all 60 samples, score factual/citation/refusal
  2. Generate hallucination_comparison.json (for external LLM review)
  3. Print results
"""

from pathlib import Path
import sys

# Ensure project root is on sys.path so `from src.*` imports work
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scoring import run_eval


def print_summary(report, title="EVALUATION RESULTS"):
    """Print formatted evaluation summary."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)
    print(f"\n  Pass Rate: {report.passed_samples}/{report.total_samples} "
          f"({report.passed_samples*100/report.total_samples:.1f}%)  [MVP target: >= 60%]")
    print(f"\n  Factual Accuracy:    {report.mean_factual_accuracy:.1f}  (threshold: 90)")
    print(f"  Citation Quality:    {report.mean_citation_quality:.1f}  (threshold: 90)")
    print(f"  Refusal Compliance:  {report.mean_refusal_compliance:.1f}  (threshold: 98)")
    print(f"  Hallucination:       → see eval/hallucination_comparison.json")
    
    # Refusal signal breakdown
    signal_counts = {}
    weak_expected = 0
    weak_unexpected = 0
    for score in report.sample_scores:
        signal = score.refusal_signal_type
        signal_counts[signal] = signal_counts.get(signal, 0) + 1
        if signal == "weak":
            if score.expect_refuse:
                weak_expected += 1
            else:
                weak_unexpected += 1
    
    print(f"\n  Refusal Signal Breakdown:")
    for signal in ["none", "weak", "medium", "strong"]:
        count = signal_counts.get(signal, 0)
        print(f"    {signal.upper():8s}: {count:2d} samples")
        if signal == "weak" and count > 0:
            print(f"      expect_refuse=true:  {weak_expected}  (score 75)")
            print(f"      expect_refuse=false: {weak_unexpected}  (score 100)")
    
    if report.blocker_flags:
        print(f"\n  Blockers: {len(report.blocker_flags)} found (first 5):")
        for blocker in report.blocker_flags[:5]:
            print(f"    [{blocker['sample_id']}] {blocker['field']}: {blocker['reason']}")
        if len(report.blocker_flags) > 5:
            print(f"    ... and {len(report.blocker_flags) - 5} more")
    print("=" * 80)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run evaluation pipeline")
    parser.add_argument("--limit", type=int, default=0,
                        help="Only evaluate first N samples (0 = all)")
    args = parser.parse_args()
    
    print("=" * 80)
    print("  Immigration Agent Evaluation Pipeline")
    print("=" * 80)
    
    label = f"first {args.limit} samples" if args.limit > 0 else "all samples"
    print(f"\nRunning pipeline on {label}...")
    report = run_eval(
        samples_file="eval/samples.jsonl",
        output_report_path="eval/baseline_report",
        max_samples=args.limit
    )
    
    print_summary(report, title="EVALUATION RESULTS")
    
    print("\n  Output Files:")
    print(f"    eval/baseline_report.json")
    print(f"    eval/baseline_report.txt")
    print(f"    eval/hallucination_comparison.json  (feed to external LLM)")
    print()


if __name__ == "__main__":
    main()

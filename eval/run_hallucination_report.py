#!/usr/bin/env python3
"""Generate a lenient hallucination report from existing eval artifacts.

This report is intentionally lenient and only penalizes clear factual mismatch.
It treats empty answers as coverage failures rather than hallucinations, and it
does not penalize uncited URLs on their own because those are traceability
issues, not necessarily fabricated content.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


PASS_THRESHOLD = 75.0

CRITERIA = {
    "mode": "lenient_proxy",
    "pass_threshold": PASS_THRESHOLD,
    "score_bands": {
        "100": "No clear hallucination. Empty answers count as non-hallucination coverage failures. Uncited URLs alone do not reduce score.",
        "75": "Minor risk only. Some imprecision or partial mismatch, but no clear fabricated factual claim.",
        "50": "Moderate hallucination risk. Substantive factual mismatch is present.",
        "25": "Significant hallucination. Reserved for manual review in this workflow.",
        "0": "Severe hallucination. Reserved for manual review in this workflow.",
    },
    "heuristics": [
        "If agent_answer is empty, assign 100 for hallucination and track separately as empty_answer_count.",
        "If baseline factual_accuracy is below 60, assign hallucination score 50.",
        "If baseline factual_accuracy is between 60 and 89.999..., assign hallucination score 75.",
        "If baseline factual_accuracy is 90 or above, assign hallucination score 100.",
        "Auto-detected uncited URLs are reported for context but do not lower the lenient hallucination score.",
        "Auto-detected numeric-range issues are not used as direct penalties because the regex can match citation dates like 2026.",
    ],
}


def load_json(file_path: Path) -> dict:
    with open(file_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def derive_score(sample: dict, baseline_detail: dict) -> tuple[float, str, str, bool]:
    answer = (sample.get("agent_answer") or "").strip()
    factual_accuracy = float(baseline_detail.get("factual_accuracy", 0.0))
    auto_issues = sample.get("auto_detected_issues") or []
    empty_answer = not answer

    if empty_answer:
        return (
            100.0,
            "clean",
            "Empty answer is counted as a coverage failure, not a hallucination.",
            True,
        )

    if factual_accuracy < 60.0:
        reason = (
            f"Baseline factual_accuracy={factual_accuracy:.1f} indicates a substantive factual mismatch."
        )
        if auto_issues:
            reason += f" Auto issues: {len(auto_issues)}."
        return 50.0, "moderate", reason, False

    if factual_accuracy < 90.0:
        reason = (
            f"Baseline factual_accuracy={factual_accuracy:.1f} indicates minor factual drift without strong fabrication evidence."
        )
        if auto_issues:
            reason += f" Auto issues: {len(auto_issues)}."
        return 75.0, "minor", reason, False

    if auto_issues:
        return (
            100.0,
            "clean",
            "No clear hallucination under lenient scoring; auto issues are traceability-only context.",
            False,
        )

    return 100.0, "clean", "No strong hallucination signal detected.", False


def summarize_group(sample_rows: list[dict]) -> dict:
    count = len(sample_rows)
    mean_score = sum(row["hallucination_score"] for row in sample_rows) / count if count else 0.0
    passed = sum(1 for row in sample_rows if row["passed"])
    moderate_or_worse = sum(1 for row in sample_rows if row["hallucination_score"] < PASS_THRESHOLD)
    return {
        "count": count,
        "mean_hallucination": mean_score,
        "pass_rate": (passed / count * 100.0) if count else 0.0,
        "hallucination_rate": (moderate_or_worse / count * 100.0) if count else 0.0,
    }


def build_report(base_dir: Path) -> tuple[dict, str]:
    baseline_report = load_json(base_dir / "baseline_report.json")
    hallucination_evidence = load_json(base_dir / "hallucination_comparison.json")
    baseline_map = {row["id"]: row for row in baseline_report["sample_details"]}

    sample_rows = []
    blocker_flags = []
    bucket_counts = {
        "clean": 0,
        "minor": 0,
        "moderate": 0,
        "significant": 0,
        "severe": 0,
    }

    for sample in hallucination_evidence["samples"]:
        sample_id = sample["sample_id"]
        baseline_detail = baseline_map[sample_id]
        score, bucket, reason, empty_answer = derive_score(sample, baseline_detail)
        passed = score >= PASS_THRESHOLD
        auto_issues = sample.get("auto_detected_issues") or []

        row = {
            "id": sample_id,
            "action": baseline_detail["action"],
            "risk_level": baseline_detail["risk_level"],
            "hallucination_score": score,
            "bucket": bucket,
            "passed": passed,
            "empty_answer": empty_answer,
            "factual_accuracy": baseline_detail["factual_accuracy"],
            "auto_detected_issue_count": len(auto_issues),
            "reason": reason,
        }
        sample_rows.append(row)
        bucket_counts[bucket] += 1

        if not passed:
            blocker_flags.append(
                {
                    "sample_id": sample_id,
                    "field": "hallucination_score",
                    "reason": f"Lenient hallucination score {score:.1f} below threshold {PASS_THRESHOLD:.0f}; {reason}",
                    "timestamp": datetime.now().isoformat(),
                }
            )

    total_samples = len(sample_rows)
    passed_samples = sum(1 for row in sample_rows if row["passed"])
    failed_samples = total_samples - passed_samples
    mean_score = sum(row["hallucination_score"] for row in sample_rows) / total_samples if total_samples else 0.0
    hallucination_rate = failed_samples / total_samples * 100.0 if total_samples else 0.0
    empty_answer_count = sum(1 for row in sample_rows if row["empty_answer"])
    auto_issue_count = sum(1 for row in sample_rows if row["auto_detected_issue_count"] > 0)

    by_action: dict[str, list[dict]] = defaultdict(list)
    by_risk: dict[str, list[dict]] = defaultdict(list)
    for row in sample_rows:
        by_action[row["action"]].append(row)
        by_risk[row["risk_level"]].append(row)

    report = {
        "timestamp": datetime.now().isoformat(),
        "source_baseline_report": "eval/baseline_report.json",
        "source_hallucination_evidence": "eval/hallucination_comparison.json",
        "criteria": CRITERIA,
        "total_samples": total_samples,
        "passed_samples": passed_samples,
        "failed_samples": failed_samples,
        "pass_rate_percent": (passed_samples / total_samples * 100.0) if total_samples else 0.0,
        "hallucination_rate_percent": hallucination_rate,
        "mean_hallucination_score": mean_score,
        "empty_answer_count": empty_answer_count,
        "auto_issue_context_count": auto_issue_count,
        "bucket_counts": bucket_counts,
        "action_scores": {key: summarize_group(rows) for key, rows in sorted(by_action.items())},
        "risk_scores": {key: summarize_group(rows) for key, rows in sorted(by_risk.items())},
        "blocker_flags": blocker_flags,
        "sample_details": sample_rows,
    }

    text_lines = [
        "LENIENT HALLUCINATION REPORT",
        "=" * 80,
        f"Timestamp: {report['timestamp']}",
        f"Total Samples: {total_samples}",
        f"Passed: {passed_samples} ({report['pass_rate_percent']:.1f}%)",
        f"Failed: {failed_samples}",
        f"Hallucination Rate: {hallucination_rate:.1f}%  (score < {PASS_THRESHOLD:.0f})",
        f"Mean Hallucination Score: {mean_score:.1f}",
        "",
        "SCORING CRITERIA (Lenient Proxy)",
        "-" * 80,
        "100: No clear hallucination. Empty answers are tracked separately as coverage failures.",
        "75: Minor risk. Some factual drift, but no strong fabricated-content signal.",
        "50: Moderate risk. Substantive factual mismatch is present.",
        "25: Significant hallucination. Reserved for manual review.",
        "0: Severe hallucination. Reserved for manual review.",
        "",
        "NOTES",
        "-" * 80,
        f"Empty answers counted as non-hallucination: {empty_answer_count}",
        f"Samples with auto-detected issues kept as context only: {auto_issue_count}",
        "Uncited URLs do not lower the lenient hallucination score by themselves.",
        "Regex-based numeric range alerts are not used as direct penalties in this lenient report.",
        "",
        "BUCKET BREAKDOWN",
        "-" * 80,
        f"Clean:        {bucket_counts['clean']} samples",
        f"Minor:        {bucket_counts['minor']} samples",
        f"Moderate:     {bucket_counts['moderate']} samples",
        f"Significant:  {bucket_counts['significant']} samples",
        f"Severe:       {bucket_counts['severe']} samples",
        "",
        "ACTION BREAKDOWN",
        "-" * 80,
    ]

    for action, summary in report["action_scores"].items():
        text_lines.append(
            f"{action}: {summary['count']} samples, mean_hallucination={summary['mean_hallucination']:.1f}, "
            f"pass_rate={summary['pass_rate']:.1f}%, hallucination_rate={summary['hallucination_rate']:.1f}%"
        )

    text_lines.extend([
        "",
        "RISK LEVEL BREAKDOWN",
        "-" * 80,
    ])

    for risk_level, summary in report["risk_scores"].items():
        text_lines.append(
            f"Risk {risk_level}: {summary['count']} samples, mean_hallucination={summary['mean_hallucination']:.1f}, "
            f"pass_rate={summary['pass_rate']:.1f}%, hallucination_rate={summary['hallucination_rate']:.1f}%"
        )

    if blocker_flags:
        text_lines.extend([
            "",
            f"BLOCKERS ({len(blocker_flags)} moderate-or-worse samples)",
            "-" * 80,
        ])
        for blocker in blocker_flags:
            text_lines.append(f"[{blocker['sample_id']}] {blocker['field']}: {blocker['reason']}")

    text_lines.append("")
    return report, "\n".join(text_lines)


def main() -> None:
    base_dir = Path(__file__).parent
    report, text_report = build_report(base_dir)

    json_path = base_dir / "hallucination_report.json"
    txt_path = base_dir / "hallucination_report.txt"

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    with open(txt_path, "w", encoding="utf-8") as handle:
        handle.write(text_report)

    print(f"[HALLUCINATION] JSON report saved to {json_path}")
    print(f"[HALLUCINATION] Text report saved to {txt_path}")
    print(f"[HALLUCINATION] Mean score: {report['mean_hallucination_score']:.1f}")
    print(f"[HALLUCINATION] Rate: {report['hallucination_rate_percent']:.1f}%")


if __name__ == "__main__":
    main()
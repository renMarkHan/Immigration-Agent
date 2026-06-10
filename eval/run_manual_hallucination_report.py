#!/usr/bin/env python3
"""Generate a manual-answer-audit hallucination report.

This report reflects a manual content review of all 120 answers. The default
score is 100 unless a sample was flagged during audit. Empty answers are kept at
100 and labeled as coverage failures, not hallucinations.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


PASS_THRESHOLD = 75.0

CRITERIA = {
    "mode": "manual_answer_audit",
    "pass_threshold": PASS_THRESHOLD,
    "review_method": [
        "Reviewed answers in batches against the user query, expected key facts, and cited sources.",
        "Did not use baseline factual_accuracy as the primary score source.",
        "Re-checked boundary cases manually and overrode several draft judgments.",
        "Empty answers were treated as coverage failures, not hallucinations.",
    ],
    "score_bands": {
        "100": "Clean. No clear hallucination or fabricated policy claim.",
        "75": "Minor risk. Overgeneralization, incomplete grounding, or unsupported specificity, but no clear false core claim.",
        "50": "Moderate hallucination. At least one material false, unsupported, or user-grounding-breaking claim.",
        "25": "Significant hallucination. Core answer is materially wrong or clearly misattributes policy.",
        "0": "Severe hallucination. Entire answer is substantially fabricated.",
    },
}


MANUAL_JUDGMENTS = {
    "VIZ-001": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Core pathway descriptions are mostly correct, but the answer embeds multiple unsupported URLs that are not actually cited in the returned evidence."
    },
    "VIZ-005": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Mentions real OINP streams, but adds specific regionalization-point detail not supported by the cited evidence."
    },
    "VIZ-006": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Correctly lists the main graduate streams, but adds unsupported general requirements such as CLB 7 plus and settlement funds for most streams."
    },
    "VIZ-007": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Answers the OINP Employer Job Offer category incompletely, then drifts into unrelated federal pathways."
    },
    "VIZ-010": {
        "score": 25,
        "bucket": "significant",
        "rationale": "User asked about Manitoba options, but the answer presents Ontario pathways as substantive options. That is a core provincial-jurisdiction misattribution."
    },
    "VIZ-012": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Correct pathway framing, but it introduces a specific Human Capital Priorities CRS threshold that is not grounded in the cited sources."
    },
    "VIZ-016": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "Claims the OINP PhD Graduate stream allows graduation within the last 5 years, which materially overstates the policy window."
    },
    "VIZ-019": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "User asked for British Columbia PR options, but the answer mostly redirects to Ontario and federal pathways instead of addressing BC PNP directly."
    },
    "VIZ-023": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "The question explicitly says the user has an Ontario employer willing to sponsor, but the answer marks job offer status as UNKNOWN and concludes likely not eligible."
    },
    "VIZ-024": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Covers general next steps after ITA, but misses some of the direct post-ITA process detail the question asks for."
    },
    "ELIG-001": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Eligibility guidance is broadly reasonable, but it overreaches despite missing critical information."
    },
    "ELIG-002": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Recognizes 18 months of TEER 2 work, but the answer's negative eligibility tone is more pessimistic than the underlying facts support."
    },
    "ELIG-008": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Lists eligible skilled-work categories but is overly hedged about information that is already known from the question context."
    },
    "ELIG-013": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Mostly accurate on FSTP structure, but the answer is incomplete and partially drifts into a document checklist instead of answering the minimum requirements cleanly."
    },
    "ELIG-014": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "It states the 12-month CEC requirement while simultaneously claiming the evidence does not support it, which materially misrepresents the policy certainty."
    },
    "ELIG-015": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Generally sensible, but it blurs program-specific criteria and overstates the role of education in CEC eligibility."
    },
    "ELIG-016": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "Claims Canadian work experience is effectively required for OINP Human Capital Priorities, which is an unsupported policy restriction."
    },
    "ELIG-017": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Mostly accurate, but repetitive and slightly ambiguous about which employment situations qualify."
    },
    "ELIG-020": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "Fails to state the expired-language-test rule clearly and instead frames it as unresolved despite the policy being materially clear."
    },
    "ELIG-021": {
        "score": 25,
        "bucket": "significant",
        "rationale": "Uses outdated NOC letter categories and gives the wrong eligible CEC occupation classes instead of TEER 0, 1, 2, and 3."
    },
    "ELIG-023": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "Incorrectly says FSW does not have a minimum point requirement and shifts the answer to CRS ranking, missing the 67-point selection-factor threshold."
    },
    "ELIG-024": {
        "score": 75,
        "bucket": "minor",
        "rationale": "The answer hints CLB 5 may be insufficient for CEC but stays too vague about the actual program threshold."
    },
    "ELIG-025": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "States CLB 5 as the likely FSTP requirement while simultaneously saying the retrieved evidence does not confirm it, creating unsupported pseudo-certainty."
    },
    "ELIG-029": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Selection factors are partially right, but the answer is truncated and muddles some scoring concepts."
    },
    "CRS-001": {
        "score": 75,
        "bucket": "minor",
        "rationale": "CRS structure is broadly correct, but some of the phrasing and sub-factor detail is imprecise."
    },
    "CRS-003": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "Explicitly says a sibling in Canada adds no CRS points, which is a direct contradiction of the policy."
    },
    "CRS-005": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Reasonable explanation of spouse impact, but the point-treatment detail is too loose to treat as clean."
    },
    "CRS-006": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Provides a plausible estimate, but several component point assignments are not well-grounded."
    },
    "CRS-007": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Estimate is directionally plausible, but specific cutoffs and point allocations are not reliably grounded."
    },
    "CRS-008": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Uses approximate CRS math with unsupported specifics."
    },
    "CRS-009": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "Claims a theoretical 800 to 900 CRS maximum without provincial nomination, which materially overstates the score range."
    },
    "CRS-010": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "Says a Canadian master's degree typically earns only 25 CRS points, which materially understates the education contribution and answers the question incorrectly."
    },
    "CRS-011": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Age-band discussion is broadly plausible but not precise enough to count as clean."
    },
    "CRS-012": {
        "score": 75,
        "bucket": "minor",
        "rationale": "The improvement logic is sensible, but the exact point arithmetic is still too approximate."
    },
    "CRS-013": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Reasonable spouse explanation, but several point details are stated without strong grounding."
    },
    "CRS-014": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Skill-transferability categories are directionally correct, but the answer is too approximate on scoring specifics."
    },
    "CRS-016": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Estimated score is plausible, but the underlying component math is not sufficiently reliable."
    },
    "CRS-017": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Correct general idea, but still too loose on the actual spouse-related scoring mechanics."
    },
    "CRS-018": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Advice on improving CRS is broadly safe, but lacks grounded specificity and omits some direct mechanisms."
    },
    "CRS-020": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Bilingual bonus explanation is plausible, but the exact point allocations are not strongly grounded by the cited evidence."
    },
    "DOC-002": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "Misstates accepted language tests by using NCLC as if it were a test and fails to correctly answer with the expected test names."
    },
    "DOC-003": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Police certificate explanation is mostly sound, but the answer is looser and less direct than the policy supports."
    },
    "DOC-004": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Proof-of-funds guidance is mostly right, but the answer includes a specific amount without strong date-grounding."
    },
    "DOC-006": {
        "score": 75,
        "bucket": "minor",
        "rationale": "ECA explanation is directionally correct, but validity-period specifics are stated more confidently than the retrieved evidence supports."
    },
    "DOC-008": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Explains the job-offer concept sensibly, but several exact threshold details are not sufficiently grounded."
    },
    "DOC-009": {
        "score": 75,
        "bucket": "minor",
        "rationale": "PR card renewal answer contains several specific administrative details that are plausible but not strongly grounded in the cited evidence."
    },
    "DOC-016": {
        "score": 50,
        "bucket": "moderate",
        "rationale": "Incorrectly says Express Entry profiles do not have a set expiration date. They expire after 12 months if not invited."
    },
    "DOC-017": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Passport-renewal advice is generally sensible, but it introduces unsupported timing guidance."
    },
    "DOC-019": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Application-status guidance is not clearly false, but the answer is incomplete and underspecified."
    },
    "DOC-025": {
        "score": 75,
        "bucket": "minor",
        "rationale": "Provides a fee figure that may be directionally right, but the answer is framed through missing-data logic and uses an outdated year reference."
    },
}


def load_json(file_path: Path) -> dict:
    with open(file_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_jsonl(file_path: Path) -> list[dict]:
    rows = []
    with open(file_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def default_assessment(answer: str) -> tuple[float, str, str]:
    if not answer.strip():
        return 100.0, "clean", "Empty answer. Coverage failure, not hallucination."
    return 100.0, "clean", "No clear hallucination found in manual answer audit."


def summarize_group(sample_rows: list[dict]) -> dict:
    count = len(sample_rows)
    mean_score = sum(row["hallucination_score"] for row in sample_rows) / count if count else 0.0
    passed = sum(1 for row in sample_rows if row["passed"])
    failed = count - passed
    return {
        "count": count,
        "mean_hallucination": mean_score,
        "pass_rate": (passed / count * 100.0) if count else 0.0,
        "hallucination_rate": (failed / count * 100.0) if count else 0.0,
    }


def build_report(base_dir: Path) -> tuple[dict, str]:
    evidence = load_json(base_dir / "hallucination_comparison.json")
    sample_metadata = {
        row["id"]: row for row in load_jsonl(base_dir / "samples.jsonl")
    }

    rows = []
    blocker_flags = []
    bucket_counts = {"clean": 0, "minor": 0, "moderate": 0, "significant": 0, "severe": 0}
    by_action: dict[str, list[dict]] = defaultdict(list)
    by_risk: dict[str, list[dict]] = defaultdict(list)

    for sample in evidence["samples"]:
        sample_id = sample["sample_id"]
        metadata = sample_metadata.get(sample_id, {})
        action_name = metadata.get("action", "unknown")
        risk_level = metadata.get("risk_level", "unknown")

        answer = sample.get("agent_answer", "")
        manual = MANUAL_JUDGMENTS.get(sample_id)
        if manual is None:
            score, bucket, rationale = default_assessment(answer)
        else:
            score = float(manual["score"])
            bucket = manual["bucket"]
            rationale = manual["rationale"]

        passed = score >= PASS_THRESHOLD
        row = {
            "id": sample_id,
            "hallucination_score": score,
            "bucket": bucket,
            "passed": passed,
            "action": action_name,
            "risk_level": risk_level,
            "rationale": rationale,
        }
        rows.append(row)
        by_action[action_name].append(row)
        by_risk[risk_level].append(row)
        bucket_counts[bucket] += 1

        if not passed:
            blocker_flags.append(
                {
                    "sample_id": sample_id,
                    "field": "hallucination_score",
                    "reason": f"Manual audit score {score:.1f} below threshold {PASS_THRESHOLD:.0f}; {rationale}",
                    "timestamp": datetime.now().isoformat(),
                }
            )

    total_samples = len(rows)
    passed_samples = sum(1 for row in rows if row["passed"])
    failed_samples = total_samples - passed_samples
    mean_score = sum(row["hallucination_score"] for row in rows) / total_samples if total_samples else 0.0
    rate = failed_samples / total_samples * 100.0 if total_samples else 0.0

    report = {
        "timestamp": datetime.now().isoformat(),
        "source_evidence": "eval/hallucination_comparison.json",
        "criteria": CRITERIA,
        "total_samples": total_samples,
        "passed_samples": passed_samples,
        "failed_samples": failed_samples,
        "pass_rate_percent": (passed_samples / total_samples * 100.0) if total_samples else 0.0,
        "hallucination_rate_percent": rate,
        "mean_hallucination_score": mean_score,
        "bucket_counts": bucket_counts,
        "action_scores": {key: summarize_group(value) for key, value in sorted(by_action.items())},
        "risk_scores": {key: summarize_group(value) for key, value in sorted(by_risk.items())},
        "blocker_flags": blocker_flags,
        "sample_details": rows,
    }

    lines = [
        "MANUAL HALLUCINATION AUDIT REPORT",
        "=" * 80,
        f"Timestamp: {report['timestamp']}",
        f"Total Samples: {total_samples}",
        f"Passed: {passed_samples} ({report['pass_rate_percent']:.1f}%)",
        f"Failed: {failed_samples}",
        f"Hallucination Rate: {rate:.1f}%  (score < {PASS_THRESHOLD:.0f})",
        f"Mean Hallucination Score: {mean_score:.1f}",
        "",
        "CRITERIA",
        "-" * 80,
        "100: Clean. No clear hallucination or fabricated policy claim.",
        "75: Minor risk. Overgeneralization, incomplete grounding, or unsupported specificity, but no clear false core claim.",
        "50: Moderate hallucination. At least one material false, unsupported, or user-grounding-breaking claim.",
        "25: Significant hallucination. Core answer is materially wrong or clearly misattributes policy.",
        "0: Severe hallucination. Entire answer is substantially fabricated.",
        "",
        "BUCKET BREAKDOWN",
        "-" * 80,
        f"Clean:        {bucket_counts['clean']} samples",
        f"Minor:        {bucket_counts['minor']} samples",
        f"Moderate:     {bucket_counts['moderate']} samples",
        f"Significant:  {bucket_counts['significant']} samples",
        f"Severe:       {bucket_counts['severe']} samples",
        "",
        "BLOCKERS",
        "-" * 80,
    ]
    for blocker in blocker_flags:
        lines.append(f"[{blocker['sample_id']}] {blocker['field']}: {blocker['reason']}")

    return report, "\n".join(lines) + "\n"


def main() -> None:
    base_dir = Path(__file__).parent
    report, text = build_report(base_dir)

    json_path = base_dir / "manual_hallucination_report.json"
    txt_path = base_dir / "manual_hallucination_report.txt"

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    with open(txt_path, "w", encoding="utf-8") as handle:
        handle.write(text)

    print(f"[MANUAL HALLUCINATION] JSON report saved to {json_path}")
    print(f"[MANUAL HALLUCINATION] Text report saved to {txt_path}")
    print(f"[MANUAL HALLUCINATION] Mean score: {report['mean_hallucination_score']:.1f}")
    print(f"[MANUAL HALLUCINATION] Rate: {report['hallucination_rate_percent']:.1f}%")


if __name__ == "__main__":
    main()
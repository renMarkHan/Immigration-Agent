"""
Policy / Tools module stub.

Owner: Yuhan Ren (Role C — Policy & Tools)
Handles: CRS score calculator (Federal EE only, MVP scope — D-009),
         eligibility rules, structured policy lookups.

DO NOT change the function signatures without updating orchestrator.py.
"""

from __future__ import annotations

import re
from typing import Any

from src.schemas import ToolRequest, ToolResult


CRS_REFERENCE = {
  "source_url": "https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/check-score/crs-criteria.html",
  "section_or_title": "Comprehensive Ranking System (CRS) criteria",
  "effective_date_or_last_updated_or_unknown": "2025-03-25",
}


PATHWAY_TREE = {
  "federal": {
    "Express Entry": [
      {
        "name": "Federal Skilled Worker Program",
        "short_description": "For skilled workers with foreign or mixed work experience meeting FSW selection rules.",
        "source_url": "https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/who-can-apply/federal-skilled-workers.html",
      },
      {
        "name": "Canadian Experience Class",
        "short_description": "For candidates with eligible recent skilled work experience in Canada.",
        "source_url": "https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/who-can-apply/canadian-experience-class.html",
      },
      {
        "name": "Federal Skilled Trades Program",
        "short_description": "For qualified skilled trades workers under Express Entry.",
        "source_url": "https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/who-can-apply/federal-skilled-trades.html",
      },
    ]
  },
  "ontario": {
    "OINP": [
      {
        "name": "Human Capital Priorities Stream",
        "short_description": "Ontario nomination stream aligned with Express Entry for eligible skilled workers.",
        "source_url": "https://www.ontario.ca/page/oinp-human-capital-priorities-stream",
      },
      {
        "name": "Masters Graduate Stream",
        "short_description": "For recent master's graduates from eligible Ontario universities.",
        "source_url": "https://www.ontario.ca/page/oinp-masters-graduate-stream",
      },
      {
        "name": "PhD Graduate Stream",
        "short_description": "For recent PhD graduates from eligible Ontario universities.",
        "source_url": "https://www.ontario.ca/page/oinp-phd-graduate-stream",
      },
      {
        "name": "Employer Job Offer: International Student Stream",
        "short_description": "For recent graduates with an eligible Ontario employer job offer.",
        "source_url": "https://www.ontario.ca/page/oinp-employer-job-offer-international-student-stream",
      },
    ]
  },
}


def normalize_section_or_title(raw: str | None, fallback: str = "unknown") -> str:
  """Normalize citation section/title strings for consistent output."""
  if not raw:
    return fallback
  text = re.sub(r"\s+", " ", raw).strip(" -:\n\t")
  lowered = text.lower()
  low_signal_titles = {
    "use the",
    "apply for the",
    "learn more",
    "read more",
    "click here",
  }
  if lowered in low_signal_titles:
    return fallback
  if len(text.split()) <= 3 and lowered.endswith((" the", " a", " an", " for", " to", " of", " in")):
    return fallback
  return text or fallback


def _extract_exact_age(query: str, age_band: str | None) -> int | None:
  match = re.search(r"\b(1[89]|[2-5]\d)\b", query)
  if match:
    return int(match.group(1))
  band_defaults = {
    "18-24": 24,
    "25-29": 29,
    "30-34": 32,
    "35-39": 37,
    "40-44": 42,
    "45+": 45,
  }
  return band_defaults.get(age_band or "")


def _age_points(age: int | None) -> int:
  if age is None or age < 18:
    return 0
  if age == 18:
    return 99
  if age == 19:
    return 105
  if 20 <= age <= 29:
    return 110
  table = {
    30: 105,
    31: 99,
    32: 94,
    33: 88,
    34: 83,
    35: 77,
    36: 72,
    37: 66,
    38: 61,
    39: 55,
    40: 50,
    41: 39,
    42: 28,
    43: 17,
    44: 6,
  }
  return table.get(age, 0)


def _education_points(level: str | None) -> tuple[int, int]:
  """Return core points and Canadian study additional points."""
  text = (level or "").lower()
  canadian = "canada" in text or "canadian" in text
  if any(token in text for token in ["doctorate", "phd", "ph.d", "doctoral"]):
    return 150, 30 if canadian else 0
  if any(token in text for token in ["master", "professional degree", "professional"]):
    return 135, 30 if canadian else 0
  if "two or more" in text:
    return 128, 15 if canadian else 0
  if "bachelor" in text:
    return 120, 30 if canadian else 0
  if "three-year" in text:
    return 120, 30 if canadian else 0
  if "two-year" in text:
    return 98, 15 if canadian else 0
  if "one-year" in text or "diploma" in text:
    return 90, 15 if canadian else 0
  if "secondary" in text or "high school" in text:
    return 30, 0
  return 0, 0


def _ielts_clb(scores: list[float]) -> list[int]:
  if len(scores) < 4:
    return []
  listening, reading, writing, speaking = scores[:4]

  def listen_clb(v: float) -> int:
    if v >= 8.5:
      return 10
    if v >= 8.0:
      return 9
    if v >= 7.5:
      return 8
    if v >= 6.0:
      return 7
    if v >= 5.5:
      return 6
    if v >= 5.0:
      return 5
    if v >= 4.5:
      return 4
    return 0

  def read_clb(v: float) -> int:
    if v >= 8.0:
      return 10
    if v >= 7.0:
      return 9
    if v >= 6.5:
      return 8
    if v >= 6.0:
      return 7
    if v >= 5.0:
      return 6
    if v >= 4.0:
      return 5
    if v >= 3.5:
      return 4
    return 0

  def ws_clb(v: float) -> int:
    if v >= 7.5:
      return 10
    if v >= 7.0:
      return 9
    if v >= 6.5:
      return 8
    if v >= 6.0:
      return 7
    if v >= 5.5:
      return 6
    if v >= 5.0:
      return 5
    if v >= 4.0:
      return 4
    return 0

  return [listen_clb(listening), read_clb(reading), ws_clb(writing), ws_clb(speaking)]


def _celpip_or_tef_clb(scores: list[float]) -> list[int]:
  return [max(0, min(10, int(score))) for score in scores[:4]] if len(scores) >= 4 else []


def _language_clbs(language_score: str | None) -> list[int]:
  text = (language_score or "").lower()
  nums = [float(x) for x in re.findall(r"\b\d+(?:\.\d+)?\b", text)]
  if "ielts" in text:
    return _ielts_clb(nums)
  if any(test in text for test in ["celpip", "tef", "tcf"]):
    return _celpip_or_tef_clb(nums)
  return []


def _language_points(clbs: list[int]) -> int:
  points = 0
  for clb in clbs:
    if clb >= 10:
      points += 34
    elif clb == 9:
      points += 31
    elif clb == 8:
      points += 23
    elif clb == 7:
      points += 17
    elif clb == 6:
      points += 9
    elif clb in (4, 5):
      points += 6
  return points


def _canadian_work_points(months: int | None) -> int:
  if months is None or months < 12:
    return 0
  years = min(months // 12, 5)
  table = {1: 40, 2: 53, 3: 64, 4: 72, 5: 80}
  return table.get(years, 0)


def _foreign_years(months: int | None) -> int:
  if months is None:
    return 0
  return min(months // 12, 3)


def _skill_transferability(education_level: str | None, clbs: list[int], canadian_work_months: int | None, foreign_work_months: int | None) -> dict[str, int]:
  max_clb = min(clbs) if len(clbs) == 4 else 0
  canadian_years = min((canadian_work_months or 0) // 12, 2)
  foreign_years = _foreign_years(foreign_work_months)
  edu_text = (education_level or "").lower()

  if any(token in edu_text for token in ["doctorate", "phd", "ph.d", "doctoral", "master", "bachelor", "two or more"]):
    if max_clb >= 9:
      edu_lang = 50
    elif max_clb >= 7:
      edu_lang = 25
    else:
      edu_lang = 0
    if canadian_years >= 2:
      edu_can = 50
    elif canadian_years == 1:
      edu_can = 25
    else:
      edu_can = 0
  else:
    edu_lang = 0
    edu_can = 0

  if foreign_years >= 3:
    if max_clb >= 9:
      foreign_lang = 50
    elif max_clb >= 7:
      foreign_lang = 25
    else:
      foreign_lang = 0
    if canadian_years >= 2:
      foreign_can = 50
    elif canadian_years == 1:
      foreign_can = 25
    else:
      foreign_can = 0
  elif foreign_years in (1, 2):
    if max_clb >= 9:
      foreign_lang = 25
    elif max_clb >= 7:
      foreign_lang = 13
    else:
      foreign_lang = 0
    if canadian_years >= 2:
      foreign_can = 25
    elif canadian_years == 1:
      foreign_can = 13
    else:
      foreign_can = 0
  else:
    foreign_lang = 0
    foreign_can = 0

  total = min(100, edu_lang + edu_can + foreign_lang + foreign_can)
  return {
    "education_language": edu_lang,
    "education_canadian_work": edu_can,
    "foreign_work_language": foreign_lang,
    "foreign_work_canadian_work": foreign_can,
    "total": total,
  }


def _estimate_crs(parameters: dict[str, Any]) -> dict[str, Any]:
  query = str(parameters.get("query") or "")
  age = _extract_exact_age(query, parameters.get("age_band"))
  education_points, canadian_study_points = _education_points(parameters.get("education_level"))
  clbs = _language_clbs(parameters.get("language_score"))
  language_points = _language_points(clbs)
  canadian_work_points = _canadian_work_points(parameters.get("canadian_work_months"))
  skill_transferability = _skill_transferability(
    parameters.get("education_level"),
    clbs,
    parameters.get("canadian_work_months"),
    parameters.get("foreign_work_months"),
  )

  core_human_capital = _age_points(age) + education_points + language_points + canadian_work_points
  spouse_points = 0  # single-applicant MVP scope
  additional_points = canadian_study_points
  total = core_human_capital + spouse_points + skill_transferability["total"] + additional_points

  missing_fields = [
    name
    for name in ["age_band", "education_level", "language_score", "canadian_work_months"]
    if parameters.get(name) in (None, "")
  ]

  assumptions = [
    "Federal Express Entry CRS only (single applicant MVP scope).",
    "No arranged employment points included, reflecting IRCC changes effective 2025-03-25.",
  ]
  if age is None:
    assumptions.append("Age points omitted because no exact age or age band was available.")
  if len(clbs) != 4:
    assumptions.append("Language points may be understated because 4 complete test subscores were not detected.")

  return {
    "estimated_total_crs": total,
    "core_human_capital": {
      "age_points": _age_points(age),
      "education_points": education_points,
      "language_points": language_points,
      "canadian_work_points": canadian_work_points,
      "total": core_human_capital,
    },
    "spouse_points": spouse_points,
    "skill_transferability": skill_transferability,
    "additional_points": {
      "canadian_study_points": canadian_study_points,
      "arranged_employment_points": 0,
      "provincial_nomination_points": 0,
      "total": additional_points,
    },
    "derived_inputs": {
      "age": age,
      "clb_scores": clbs,
      "education_level": parameters.get("education_level"),
      "canadian_work_months": parameters.get("canadian_work_months"),
      "foreign_work_months": parameters.get("foreign_work_months"),
    },
    "missing_fields": missing_fields,
    "assumptions": assumptions,
    "policy_reference": CRS_REFERENCE,
  }


def _build_pathway_backbone(parameters: dict[str, Any]) -> dict[str, Any]:
    target_province = parameters.get("target_province") or parameters.get("province") or "Ontario"
    return {
        "target_province": target_province,
        "pathway_tree": PATHWAY_TREE,
        "normalization_rules": {
            "section_title_rule": "Trim whitespace, collapse repeated spaces, preserve official heading wording where available.",
            "fallback_title": "unknown",
        },
    }


def run_tool(request: ToolRequest) -> ToolResult:
    """
    Dispatch a tool call by name and return structured output.

    Supported tools (MVP):
      - crs_calculator: compute CRS score for Federal Express Entry
      - eligibility_check: check program eligibility criteria

    Supported tools implemented now:
      - crs_calculator: compute approximate Federal Express Entry CRS for MVP
      - pathway_backbone: return static Action 1 pathway hierarchy backbone
    """
    try:
        if request.tool_name == "crs_calculator":
            return ToolResult(tool_name=request.tool_name, output=_estimate_crs(request.parameters), error=None)
        if request.tool_name == "pathway_backbone":
            return ToolResult(tool_name=request.tool_name, output=_build_pathway_backbone(request.parameters), error=None)
        if request.tool_name == "normalize_section_title":
            return ToolResult(
                tool_name=request.tool_name,
                output={
                    "normalized": normalize_section_or_title(request.parameters.get("raw")),
                },
                error=None,
            )
        return ToolResult(tool_name=request.tool_name, output=None, error=f"Unsupported tool: {request.tool_name}")
    except Exception as exc:
        return ToolResult(tool_name=request.tool_name, output=None, error=str(exc))


if __name__ == "__main__":
    payload = {
        "query": "I am 27 with a Master's degree in Canada, IELTS 8 7 7 7 and 12 months of Canadian work experience. What is my CRS score?",
        "age_band": "25-29",
        "education_level": "Master's, Canada",
        "language_score": "IELTS 8 7 7 7",
        "canadian_work_months": 12,
    }
    result = run_tool(ToolRequest(tool_name="crs_calculator", parameters=payload))
    assert result.error is None
    assert result.output["estimated_total_crs"] > 0
    print("policy_tool_module self-check PASS")

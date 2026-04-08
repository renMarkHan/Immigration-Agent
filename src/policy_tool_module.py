"""
Policy / Tools module stub.

Owner: Yuhan Ren (Role C — Policy & Tools)
Handles: CRS score calculator (Federal EE only, MVP scope — D-009),
         eligibility rules, structured policy lookups.

DO NOT change the function signatures without updating orchestrator.py.
"""

from __future__ import annotations

from src.schemas import ToolRequest, ToolResult


def run_tool(request: ToolRequest) -> ToolResult:
    """
    Dispatch a tool call by name and return structured output.

    Supported tools (MVP):
      - crs_calculator: compute CRS score for Federal Express Entry
      - eligibility_check: check program eligibility criteria

    TODO (Yuhan): implement tool logic.
    """
    return ToolResult(
        tool_name=request.tool_name,
        output=None,
        error="Tool not yet implemented",
    )

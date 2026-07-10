#!/usr/bin/env python3
"""
Agentic conflict layer for flight conflict interpretation.

This module turns low-level 4D overlap records into a human-readable summary
and recommendation so a user can quickly understand whether an overlap is mild,
moderate, or severe.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "DECONFLICTION_RULES.md"


def _load_rules() -> str:
    if RULES_PATH.exists():
        return RULES_PATH.read_text(encoding="utf-8")
    return ""


RULES_TEXT = _load_rules()


def interpret_conflict(conflict: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a volume overlap record into a brief natural-language summary."""
    a_type = conflict.get("volume_a_type", "volume")
    b_type = conflict.get("volume_b_type", "volume")
    alt_a = conflict.get("alt_a_ft", "")
    alt_b = conflict.get("alt_b_ft", "")
    time_a = conflict.get("time_a_utc", "")
    time_b = conflict.get("time_b_utc", "")

    severity = "high"
    if a_type == "origin" or b_type == "destination":
        severity = "high"
    elif a_type == "destination" or b_type == "origin":
        severity = "high"
    else:
        severity = "medium"

    summary = (
        f"{conflict.get('flight_a')} and {conflict.get('flight_b')} overlap in the "
        f"{a_type}/{b_type} volume pair during {time_a} vs {time_b}. "
        f"Altitude bands {alt_a} ft and {alt_b} ft overlap."
    )

    recommendation = "Apply an altitude change first to separate the volumes."
    reroute = "Shift one flight by 50–100 ft in altitude and keep the ground path unchanged."
    if severity == "high":
        recommendation = "Apply an altitude change first; if needed, add a time delay as the secondary action."
        reroute = "Increase altitude separation first, then delay the affected flight by 30–60 seconds if needed."
    elif a_type == "segment" and b_type == "segment":
        reroute = "Change altitude separation first; if still needed, delay the flight on the ground or by speed adjustment."

    if RULES_TEXT:
        reroute = f"{reroute} {RULES_TEXT.splitlines()[0]}"

    if severity == "high":
        reroute = (
            f"{reroute} Ground-path changes require explicit user approval before execution."
        )

    return {
        "severity": severity,
        "summary": summary,
        "recommendation": recommendation,
        "reroute": reroute,
        "flight_a": conflict.get("flight_a"),
        "flight_b": conflict.get("flight_b"),
    }


def build_conflict_report(
    conflict_summaries: List[Dict[str, Any]],
    generated_at: Optional[str] = None,
) -> str:
    """Create a concise plain-text report for the conflict set."""
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not conflict_summaries:
        return f"No conflicts detected at {generated_at}."

    lines = [
        f"Conflict report generated at {generated_at}",
        f"{len(conflict_summaries)} conflict(s) detected.",
    ]

    for idx, item in enumerate(conflict_summaries, 1):
        lines.append(f"{idx}. [{item['severity'].upper()}] {item['summary']}")
        lines.append(f"   Recommendation: {item['recommendation']}")
        lines.append(f"   Proposed reroute: {item['reroute']}")

    return "\n".join(lines)

"""Canonicalize approved close payload section fields."""

from __future__ import annotations

import copy
from typing import Any


SECTION_KEYS = (
    "accomplished",
    "captured",
    "carried",
    "waiting",
    "notes",
    "priorities",
    "tasks",
    "meetings",
    "people_outreach",
)


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied payload with all section data under ``sections``.

    Older approved proposals sometimes emitted section fields at the payload root.  Keep
    accepting those payloads, but reject ambiguous conflicting representations.
    """
    if not isinstance(payload, dict):
        raise ValueError("close payload must be an object")
    result = copy.deepcopy(payload)
    raw_sections = result.get("sections")
    if raw_sections is None:
        sections: dict[str, Any] = {}
    elif isinstance(raw_sections, dict):
        sections = raw_sections
    else:
        raise ValueError("close payload sections must be an object")
    for key in SECTION_KEYS:
        top_value = result.get(key)
        nested_present = key in sections and sections[key] is not None
        if nested_present and top_value is not None and sections[key] != top_value:
            raise ValueError(f"conflicting top-level and sections.{key} values")
        if not nested_present and top_value is not None:
            sections[key] = top_value
    result["sections"] = sections
    return result

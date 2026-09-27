"""Presentation logic for technical meeting records (risks, dependencies,
learnings). Pure functions, no Streamlit, no database — mirrors
`ui/gap_display.py`."""
from agent.schemas import normalize_optional_text


def display_value(value: str | None) -> str:
    """A widget default that never shows a blank/placeholder value as text.

    Routed through the shared predicate, not a bare `or ""`: a row holding a
    placeholder ("null", "TBD") must show as blank, same as every other
    optional field in this app.
    """
    return normalize_optional_text(value) or ""


def edited_fields(row: dict, fields: tuple[str, ...]) -> list[dict]:
    """Which of `fields` differ between the frozen `ai_*` value and the live,
    human-editable one — PRD F16's "AI values remain available beside
    human-edited values for audit", made renderable.
    """
    return [
        {"field": field, "ai_value": row.get(f"ai_{field}"),
         "human_value": row.get(field)}
        for field in fields
        if row.get(field) != row.get(f"ai_{field}")
    ]


def record_count(risks: list, dependencies: list, learnings: list) -> int:
    """Total visible technical records, for the section header."""
    return len(risks) + len(dependencies) + len(learnings)


def required_text(value: str | None) -> str | None:
    """The value to save for a required text field (a risk or dependency
    description, a learning lesson), or None when Save must stay disabled.

    Same predicate as the Add forms: blank, whitespace-only, and placeholder
    text ("TBD", "null") are not a description, so the stored value is kept.
    """
    return normalize_optional_text(value)


def human_provenance_label(row: dict) -> str | None:
    """Visible provenance for a technical record created during human review."""
    if row.get("origin") != "human":
        return None
    return "👤 Human-created record (added during review)."


def missing_evidence_warning(row: dict) -> str | None:
    """Visible evidence state for human-created records without source support."""
    if (row.get("origin") != "human"
            or normalize_optional_text(row.get("source_quote")) is not None):
        return None
    return ("No source quote or model confidence is attached; this human-created "
            "record is not evidence-backed by the meeting notes.")

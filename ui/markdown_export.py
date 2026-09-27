"""Builds the downloadable Markdown artefact. Pure functions, no Streamlit."""
import re

from agent.schemas import normalize_optional_text

# What an unset owner or deadline looks like in the document. Interpolating the
# value directly printed Python's `None` as the literal word "None", which reads
# like a person called None rather than an absence.
BLANK = "—"


def build_export(meeting: dict, decisions: list[dict], items: list[dict],
                 message: str) -> str:
    lines = [f"# {meeting['title']}", f"**Date:** {meeting['meeting_date']}", "",
             "## Decisions", ""]
    lines += [f"- {d['decision']}" for d in decisions] or ["None recorded."]
    lines += ["", "## Action items", ""]
    # Symmetric with the decisions block above and with run_draft's own
    # "- (none recorded)" fallback: a decisions-only meeting used to emit a bare
    # "## Action items" heading with nothing under it.
    lines += [f"- **{item['task']}**"
              f" — {normalize_optional_text(item.get('owner')) or BLANK}"
              f" — due {normalize_optional_text(item.get('deadline')) or BLANK}"
              for item in items] or ["None recorded."]
    lines += ["", "## Follow-up message", "", message, ""]
    return "\n".join(lines)


def export_filename(meeting: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", meeting["title"].lower()).strip("-")
    return f"{meeting['meeting_date']}-{slug}.md"

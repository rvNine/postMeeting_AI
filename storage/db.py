"""SQLite persistence. Knows nothing about the agent or the UI.

Every action item stores the agent's original task/owner/deadline in `ai_*`
columns that are written once and never updated. That is what lets the app show
which fields a human overrode (PRD F15) and what the evaluation scores against.
"""
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from agent.schemas import (GapType, MeetingExtraction, ReviewResult, TechnicalDependency,
                           TechnicalLearning, TechnicalRisk)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_EDITABLE_FIELDS = ("task", "owner", "deadline")
_RISK_EDITABLE_FIELDS = ("description", "impact", "likelihood", "severity", "mitigation", "owner")
_DEPENDENCY_EDITABLE_FIELDS = ("description", "depends_on", "blocked_by", "owner")
_LEARNING_EDITABLE_FIELDS = ("lesson", "technical_area", "validation_status", "follow_up_experiment")

# Fixed search order for resolving a gap's raw target_id onto an entity kind.
# See _scoped_target.
_TARGET_KINDS = ("item", "decision", "risk", "dependency", "learning")

# Sentinel distinguishing "argument not passed" from "argument passed as None",
# so update_action_item can clear a field (write NULL) instead of skipping it.
_UNSET = object()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _scoped(meeting_id: str, kind: str, model_id: str) -> str:
    """Namespace a model-supplied id with the meeting it belongs to.

    Action item, decision, and gap ids are invented by the LLM, which has no
    uniqueness contract — the prompts never mention ids, and in practice every
    meeting comes back with `a1`, `d1`. Those columns are TEXT PRIMARY KEY
    across the whole table, so writing them verbatim made the *second* Analyze
    of a session die on `UNIQUE constraint failed: action_items.id`.

    This is the only place raw model ids cross into storage, so it is the only
    place that needs to namespace them: every consumer reads ids back out of
    the DB. `gaps.target_id` must be namespaced with exactly the same prefix as
    the row it points at — `ui.gap_display.gaps_for_item` matches `target_id`
    against the loaded item/decision `id`, so namespacing one and not the other
    would make every gap badge silently vanish and the gate stop showing
    anything.

    The prefix carries the entity `kind` as well as the meeting. Action items
    and decisions are separate id spaces in the schema but not in the model's
    head: a real run numbered its decisions 1,2 and its action items 1,2,3,4,
    so `<meeting>:2` matched both. A gap targeting it then rendered a "Mark
    resolved" button under the decision AND under the action item, and Streamlit
    killed the page on the duplicate widget key.
    """
    return f"{meeting_id}:{kind}:{model_id}"


# Which entity a gap type is about. A gap the model raises against a decision
# must resolve to the decision's id, not to an action item that happens to
# share the number.
_GAP_TARGET_KIND = {
    GapType.CONFLICTING_DECISION: "decision",
    GapType.MISSING_OWNER: "item",
    GapType.MISSING_DEADLINE: "item",
    GapType.AMBIGUOUS_TASK: "item",
    GapType.UNSUPPORTED_EVIDENCE: "item",
}


def _scoped_target(meeting_id: str, gap, ids_by_kind: dict[str, set[str]]) -> str:
    """Resolve a gap's raw target_id onto the entity it actually refers to.

    The gap type implies the kind. When that kind has no such id — the model
    mislabelled, or invented a target — fall back to searching the other kinds
    in a fixed order (item, decision, risk, dependency, learning). If none of
    them do, scope it by the implied kind anyway: it then matches nothing and
    surfaces in the review view's unattached-gaps block, which is the honest
    outcome and still resolvable by a human.
    """
    preferred = _GAP_TARGET_KIND.get(gap.type, "item")
    search_order = [preferred] + [k for k in _TARGET_KINDS if k != preferred]
    for kind in search_order:
        if gap.target_id in ids_by_kind.get(kind, set()):
            return _scoped(meeting_id, kind, gap.target_id)
    return _scoped(meeting_id, preferred, gap.target_id)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text())
    extraction_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(extractions)").fetchall()
    }
    if "processing_pass" not in extraction_columns:
        conn.execute(
            "ALTER TABLE extractions ADD COLUMN processing_pass "
            "INTEGER NOT NULL DEFAULT 1"
        )
    conn.commit()


def save_meeting(conn, *, title: str, meeting_date: str, raw_notes: str) -> str:
    meeting_id = _new_id()
    conn.execute(
        "INSERT INTO meetings (id, title, meeting_date, raw_notes, created_at, status)"
        " VALUES (?, ?, ?, ?, ?, 'draft')",
        (meeting_id, title, meeting_date, raw_notes, _now()),
    )
    conn.commit()
    return meeting_id


def save_extraction(conn, meeting_id: str, extraction: MeetingExtraction,
                    review: ReviewResult, *, model: str, prompt_version: str,
                    tokens_used: int, latency_ms: int, raw_response: str,
                    processing_pass: int = 1) -> None:
    # Atomicity: an extraction (its row plus every action item / decision / gap)
    # is all-or-nothing (PRD 5.6). `with conn:` commits on success and rolls
    # back the whole transaction if any statement below raises, so a mid-loop
    # failure can never leave partial rows for a later unrelated commit on
    # this long-lived connection to silently flush.
    with conn:
        conn.execute(
            "INSERT INTO extractions (id, meeting_id, summary, participants, reviewer_notes,"
            " overall_confidence, raw_response, prompt_version, processing_pass, model,"
            " tokens_used, latency_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_new_id(), meeting_id, extraction.summary, json.dumps(extraction.participants),
             review.reviewer_notes, review.overall_confidence, raw_response,
             prompt_version, processing_pass, model, tokens_used, latency_ms, _now()),
        )
        for item in extraction.action_items:
            conn.execute(
                "INSERT INTO action_items (id, meeting_id, task, owner, deadline,"
                " source_quote, confidence, ai_task, ai_owner, ai_deadline, origin, deleted)"
                " VALUES (?,?,?,?,?,?,?,?,?,?, 'agent', 0)",
                (_scoped(meeting_id, "item", item.id), meeting_id, item.task, item.owner, item.deadline,
                 item.source_quote, item.confidence, item.task, item.owner, item.deadline),
            )
        for decision in extraction.decisions:
            conn.execute(
                "INSERT INTO decisions (id, meeting_id, decision, rationale, source_quote,"
                " confidence, deleted) VALUES (?,?,?,?,?,?,0)",
                (_scoped(meeting_id, "decision", decision.id), meeting_id, decision.decision, decision.rationale,
                 decision.source_quote, decision.confidence),
            )
        risk: TechnicalRisk
        for risk in extraction.risks:
            conn.execute(
                "INSERT INTO risks (id, meeting_id, description, impact, likelihood,"
                " severity, mitigation, owner, source_quote, confidence, ai_description,"
                " ai_impact, ai_likelihood, ai_severity, ai_mitigation, ai_owner, origin,"
                " deleted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'agent', 0)",
                (_scoped(meeting_id, "risk", risk.id), meeting_id, risk.description,
                 risk.impact, risk.likelihood, risk.severity, risk.mitigation, risk.owner,
                 risk.source_quote, risk.confidence, risk.description, risk.impact,
                 risk.likelihood, risk.severity, risk.mitigation, risk.owner),
            )
        dependency: TechnicalDependency
        for dependency in extraction.dependencies:
            conn.execute(
                "INSERT INTO dependencies (id, meeting_id, description, depends_on,"
                " blocked_by, owner, source_quote, confidence, ai_description,"
                " ai_depends_on, ai_blocked_by, ai_owner, origin, deleted)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'agent', 0)",
                (_scoped(meeting_id, "dependency", dependency.id), meeting_id,
                 dependency.description, dependency.depends_on, dependency.blocked_by,
                 dependency.owner, dependency.source_quote, dependency.confidence,
                 dependency.description, dependency.depends_on, dependency.blocked_by,
                 dependency.owner),
            )
        learning: TechnicalLearning
        for learning in extraction.learnings:
            conn.execute(
                "INSERT INTO learnings (id, meeting_id, lesson, technical_area,"
                " validation_status, follow_up_experiment, source_quote, confidence,"
                " ai_lesson, ai_technical_area, ai_validation_status,"
                " ai_follow_up_experiment, origin, deleted)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'agent', 0)",
                (_scoped(meeting_id, "learning", learning.id), meeting_id, learning.lesson,
                 learning.technical_area, learning.validation_status,
                 learning.follow_up_experiment, learning.source_quote, learning.confidence,
                 learning.lesson, learning.technical_area, learning.validation_status,
                 learning.follow_up_experiment),
            )
        ids_by_kind = {
            "item": {i.id for i in extraction.action_items},
            "decision": {d.id for d in extraction.decisions},
            "risk": {r.id for r in extraction.risks},
            "dependency": {d.id for d in extraction.dependencies},
            "learning": {ln.id for ln in extraction.learnings},
        }
        for gap in review.gaps:
            conn.execute(
                "INSERT OR REPLACE INTO gaps (id, meeting_id, target_id, type, severity,"
                " explanation, suggested_question, resolved) VALUES (?,?,?,?,?,?,?,0)",
                (_scoped(meeting_id, "gap", gap.id), meeting_id,
                 _scoped_target(meeting_id, gap, ids_by_kind),
                 gap.type.value, gap.severity.value,
                 gap.explanation, gap.suggested_question),
            )


def load_action_items(conn, meeting_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM action_items WHERE meeting_id = ? AND deleted = 0"
        " ORDER BY rowid", (meeting_id,)).fetchall()
    return [dict(r) for r in rows]


def load_decisions(conn, meeting_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM decisions WHERE meeting_id = ? AND deleted = 0"
        " ORDER BY rowid", (meeting_id,)).fetchall()
    return [dict(r) for r in rows]


def load_gaps(conn, meeting_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM gaps WHERE meeting_id = ? ORDER BY rowid",
                        (meeting_id,)).fetchall()
    return [dict(r) for r in rows]


def load_risks(conn, meeting_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM risks WHERE meeting_id = ? AND deleted = 0"
        " ORDER BY rowid", (meeting_id,)).fetchall()
    return [dict(r) for r in rows]


def load_dependencies(conn, meeting_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM dependencies WHERE meeting_id = ? AND deleted = 0"
        " ORDER BY rowid", (meeting_id,)).fetchall()
    return [dict(r) for r in rows]


def load_learnings(conn, meeting_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM learnings WHERE meeting_id = ? AND deleted = 0"
        " ORDER BY rowid", (meeting_id,)).fetchall()
    return [dict(r) for r in rows]


def update_action_item(conn, item_id: str, *, task=_UNSET, owner=_UNSET, deadline=_UNSET) -> None:
    updates = {"task": task, "owner": owner, "deadline": deadline}
    setters = {k: v for k, v in updates.items() if v is not _UNSET}
    if not setters:
        return
    clause = ", ".join(f"{k} = ?" for k in setters)
    conn.execute(f"UPDATE action_items SET {clause} WHERE id = ?",
                 (*setters.values(), item_id))
    conn.commit()


def add_action_item(conn, meeting_id: str, *, task: str,
                    owner: str | None, deadline: str | None) -> str:
    item_id = _new_id()
    conn.execute(
        "INSERT INTO action_items (id, meeting_id, task, owner, deadline, source_quote,"
        " confidence, ai_task, ai_owner, ai_deadline, origin, deleted)"
        " VALUES (?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,'human',0)",
        (item_id, meeting_id, task, owner, deadline),
    )
    conn.commit()
    return item_id


def delete_action_item(conn, item_id: str) -> None:
    conn.execute("UPDATE action_items SET deleted = 1 WHERE id = ?", (item_id,))
    conn.commit()


def delete_decision(conn, decision_id: str) -> None:
    conn.execute("UPDATE decisions SET deleted = 1 WHERE id = ?", (decision_id,))
    conn.commit()


def update_risk(conn, risk_id: str, *, description=_UNSET, impact=_UNSET, likelihood=_UNSET,
                severity=_UNSET, mitigation=_UNSET, owner=_UNSET) -> None:
    updates = {"description": description, "impact": impact, "likelihood": likelihood,
               "severity": severity, "mitigation": mitigation, "owner": owner}
    setters = {k: v for k, v in updates.items() if v is not _UNSET}
    if not setters:
        return
    clause = ", ".join(f"{k} = ?" for k in setters)
    conn.execute(f"UPDATE risks SET {clause} WHERE id = ?",
                 (*setters.values(), risk_id))
    conn.commit()


def add_risk(conn, meeting_id: str, *, description: str, impact: str | None,
            likelihood: str | None, severity: str | None, mitigation: str | None,
            owner: str | None) -> str:
    risk_id = _new_id()
    conn.execute(
        "INSERT INTO risks (id, meeting_id, description, impact, likelihood, severity,"
        " mitigation, owner, source_quote, confidence, ai_description, ai_impact,"
        " ai_likelihood, ai_severity, ai_mitigation, ai_owner, origin, deleted)"
        " VALUES (?,?,?,?,?,?,?,?,'',NULL,NULL,NULL,NULL,NULL,NULL,NULL,'human',0)",
        (risk_id, meeting_id, description, impact, likelihood, severity, mitigation, owner),
    )
    conn.commit()
    return risk_id


def delete_risk(conn, risk_id: str) -> None:
    conn.execute("UPDATE risks SET deleted = 1 WHERE id = ?", (risk_id,))
    conn.commit()


def update_dependency(conn, dependency_id: str, *, description=_UNSET, depends_on=_UNSET,
                      blocked_by=_UNSET, owner=_UNSET) -> None:
    updates = {"description": description, "depends_on": depends_on,
               "blocked_by": blocked_by, "owner": owner}
    setters = {k: v for k, v in updates.items() if v is not _UNSET}
    if not setters:
        return
    clause = ", ".join(f"{k} = ?" for k in setters)
    conn.execute(f"UPDATE dependencies SET {clause} WHERE id = ?",
                 (*setters.values(), dependency_id))
    conn.commit()


def add_dependency(conn, meeting_id: str, *, description: str, depends_on: str | None,
                   blocked_by: str | None, owner: str | None) -> str:
    dependency_id = _new_id()
    conn.execute(
        "INSERT INTO dependencies (id, meeting_id, description, depends_on, blocked_by,"
        " owner, source_quote, confidence, ai_description, ai_depends_on, ai_blocked_by,"
        " ai_owner, origin, deleted)"
        " VALUES (?,?,?,?,?,?,'',NULL,NULL,NULL,NULL,NULL,'human',0)",
        (dependency_id, meeting_id, description, depends_on, blocked_by, owner),
    )
    conn.commit()
    return dependency_id


def delete_dependency(conn, dependency_id: str) -> None:
    conn.execute("UPDATE dependencies SET deleted = 1 WHERE id = ?", (dependency_id,))
    conn.commit()


def update_learning(conn, learning_id: str, *, lesson=_UNSET, technical_area=_UNSET,
                    validation_status=_UNSET, follow_up_experiment=_UNSET) -> None:
    updates = {"lesson": lesson, "technical_area": technical_area,
               "validation_status": validation_status,
               "follow_up_experiment": follow_up_experiment}
    setters = {k: v for k, v in updates.items() if v is not _UNSET}
    if not setters:
        return
    clause = ", ".join(f"{k} = ?" for k in setters)
    conn.execute(f"UPDATE learnings SET {clause} WHERE id = ?",
                 (*setters.values(), learning_id))
    conn.commit()


def add_learning(conn, meeting_id: str, *, lesson: str, technical_area: str | None,
                 validation_status: str | None, follow_up_experiment: str | None) -> str:
    learning_id = _new_id()
    conn.execute(
        "INSERT INTO learnings (id, meeting_id, lesson, technical_area, validation_status,"
        " follow_up_experiment, source_quote, confidence, ai_lesson, ai_technical_area,"
        " ai_validation_status, ai_follow_up_experiment, origin, deleted)"
        " VALUES (?,?,?,?,?,?,'',NULL,NULL,NULL,NULL,NULL,'human',0)",
        (learning_id, meeting_id, lesson, technical_area, validation_status,
         follow_up_experiment),
    )
    conn.commit()
    return learning_id


def delete_learning(conn, learning_id: str) -> None:
    conn.execute("UPDATE learnings SET deleted = 1 WHERE id = ?", (learning_id,))
    conn.commit()


def resolve_gap(conn, gap_id: str, resolved: bool = True) -> None:
    conn.execute("UPDATE gaps SET resolved = ?, resolved_at = ? WHERE id = ?",
                 (1 if resolved else 0, _now() if resolved else None, gap_id))
    conn.commit()


def resolved_gap_ids(conn, meeting_id: str) -> set[str]:
    rows = conn.execute("SELECT id FROM gaps WHERE meeting_id = ? AND resolved = 1",
                        (meeting_id,)).fetchall()
    return {r["id"] for r in rows}


def save_approval(conn, meeting_id: str, *, draft_text: str, final_text: str) -> None:
    conn.execute(
        "INSERT INTO approvals (id, meeting_id, draft_text, final_text, approved_at)"
        " VALUES (?,?,?,?,?)",
        (_new_id(), meeting_id, draft_text, final_text, _now()))
    conn.execute("UPDATE meetings SET status = 'approved' WHERE id = ?", (meeting_id,))
    conn.commit()


def delete_meeting(conn, meeting_id: str) -> None:
    """Hard-delete a meeting and every dependent persistence row atomically."""
    # Legacy tables predate foreign-key cascades.  Delete their rows explicitly
    # before the parent; metadata, links, participants, and chunks are covered
    # by their schema-level ON DELETE CASCADE constraints.  FTS5 is not a
    # foreign-key table, so its rows always need an explicit delete.
    with conn:
        conn.execute("DELETE FROM meeting_chunk_fts WHERE meeting_id = ?", (meeting_id,))
        for table in (
            "approvals", "gaps", "action_items", "decisions", "risks",
            "dependencies", "learnings", "extractions",
        ):
            conn.execute(f"DELETE FROM {table} WHERE meeting_id = ?", (meeting_id,))
        conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))


def list_meetings(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM meetings ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def load_extraction_meta(conn, meeting_id: str) -> dict | None:
    """Summary, participants, and provenance for the most recent extraction."""
    row = conn.execute(
        "SELECT * FROM extractions WHERE meeting_id = ? ORDER BY created_at DESC LIMIT 1",
        (meeting_id,)).fetchone()
    return dict(row) if row else None


_TECHNICAL_KINDS = (
    ("risk", load_risks, _RISK_EDITABLE_FIELDS),
    ("dependency", load_dependencies, _DEPENDENCY_EDITABLE_FIELDS),
    ("learning", load_learnings, _LEARNING_EDITABLE_FIELDS),
)


def human_edits(conn, meeting_id: str) -> list[dict]:
    """Fields where the human value differs from the agent's frozen original.

    Action-item edits keep their original dict shape exactly (no "kind" key):
    tests assert the exact dict and ui/export_view.py renders it. Technical
    edits (risks, dependencies, learnings) are appended with an extra "kind"
    key so callers can tell the record types apart.
    """
    edits = []
    for item in load_action_items(conn, meeting_id):
        if item["origin"] != "agent":
            continue
        for field in _EDITABLE_FIELDS:
            if item[field] != item[f"ai_{field}"]:
                edits.append({"item_id": item["id"], "field": field,
                              "ai_value": item[f"ai_{field}"],
                              "human_value": item[field]})
    for kind, loader, fields in _TECHNICAL_KINDS:
        for record in loader(conn, meeting_id):
            if record["origin"] != "agent":
                continue
            for field in fields:
                if record[field] != record[f"ai_{field}"]:
                    edits.append({"kind": kind, "item_id": record["id"], "field": field,
                                  "ai_value": record[f"ai_{field}"],
                                  "human_value": record[field]})
    return edits

"""Review, edit, and gap resolution. The human gate lives here."""
import json

import streamlit as st

from agent.gaps import open_blocking
from agent.schemas import Gap, normalize_optional_text
from storage import db
from storage.meeting_knowledge import is_fixture_meeting
from ui.gap_display import (PRIOR_COMMITMENTS_CAPTION, badge, draft_blocked,
                            gap_is_satisfied, gaps_for_item, gate_message,
                            items_missing_fields, needs_manual_resolution,
                            owner_suggestion, prior_commitment_lines,
                            sort_items_gaps_first, unattached_gaps,
                            unresolved_manual_gaps)
from ui.state import Stage, parse_deadline
from ui.technical_display import (display_value, edited_fields, human_provenance_label,
                                  missing_evidence_warning, record_count, required_text)

# Editable fields per technical record kind, for the AI-vs-human diff caption
# (`edited_fields`). Mirrors storage/db.py's own `_*_EDITABLE_FIELDS` tuples,
# which are private to that module — duplicated rather than imported, the
# same way `_EDITABLE_FIELDS` already stays private to db.py.
_RISK_FIELDS = ("description", "impact", "likelihood", "severity", "mitigation", "owner")
_DEPENDENCY_FIELDS = ("description", "depends_on", "blocked_by", "owner")
_LEARNING_FIELDS = ("lesson", "technical_area", "validation_status", "follow_up_experiment")


def _load(conn, meeting_id):
    gaps = [Gap(**{k: v for k, v in row.items()
                   if k in {"id", "type", "severity", "target_id",
                            "explanation", "suggested_question"}})
            for row in db.load_gaps(conn, meeting_id)]
    return (db.load_action_items(conn, meeting_id),
            db.load_decisions(conn, meeting_id),
            gaps,
            db.resolved_gap_ids(conn, meeting_id),
            db.load_risks(conn, meeting_id),
            db.load_dependencies(conn, meeting_id),
            db.load_learnings(conn, meeting_id))


def render(conn):
    meeting_id = st.session_state["meeting_id"]
    if is_fixture_meeting(conn, meeting_id):
        _render_fixture(conn, meeting_id)
        return
    items, decisions, gaps, resolved, risks, dependencies, learnings = _load(conn, meeting_id)
    open_gaps = open_blocking(gaps, resolved)

    st.subheader("2. Review what the agent found")

    for note in st.session_state.get("loop_notes", []):
        st.caption(f"🔁 {note}")

    meta = db.load_extraction_meta(conn, meeting_id)
    if meta:
        st.markdown("### Summary")
        st.write(meta["summary"])
        participants_list = json.loads(meta["participants"])
        if participants_list:
            st.caption(f"Participants: {', '.join(participants_list)}")
        if meta["reviewer_notes"]:
            st.caption(f"Reviewer notes: {meta['reviewer_notes']}")

    _render_prior_commitments()

    if open_gaps:
        st.error(gate_message(open_gaps))
    else:
        st.success("No blocking gaps. You can draft the follow-up.")

    missing = items_missing_fields(items)
    if missing:
        named = ", ".join(f"{i['task']!r}" for i in missing)
        st.error(f"{len(missing)} item(s) still need an owner or deadline: {named}")

    st.markdown("### Decisions")
    for decision in decisions:
        _render_decision(conn, decision, gaps, resolved)

    st.markdown("### Action items")
    participants = _people(meta, items)
    for item in sort_items_gaps_first(items, gaps, resolved):
        _render_item(conn, item, gaps, resolved, participants)

    st.markdown(f"### Technical records ({record_count(risks, dependencies, learnings)})")

    st.markdown("#### Risks")
    for risk in risks:
        _render_risk(conn, risk, gaps, resolved)
    _render_add_risk(conn, meeting_id)

    st.markdown("#### Dependencies")
    for dependency in dependencies:
        _render_dependency(conn, dependency, gaps, resolved)
    _render_add_dependency(conn, meeting_id)

    st.markdown("#### Learnings")
    for learning in learnings:
        _render_learning(conn, learning, gaps, resolved)
    _render_add_learning(conn, meeting_id)

    loose = unattached_gaps(gaps, {i["id"] for i in items},
                            {d["id"] for d in decisions}, resolved,
                            risk_ids={r["id"] for r in risks},
                            dependency_ids={d["id"] for d in dependencies},
                            learning_ids={ln["id"] for ln in learnings})
    if loose:
        st.markdown("### Other flags")
        st.caption("The agent raised these but could not attach them to a specific "
                   "record on screen. Review each and mark it resolved "
                   "once you've handled it.")
        for gap in loose:
            _render_unattached_gap(conn, gap)

    with st.expander("Add an item the agent missed"):
        new_task = st.text_input("Task", key="new_task")
        new_owner = st.text_input("Owner", key="new_owner")
        new_deadline = st.text_input("Deadline (YYYY-MM-DD)", key="new_deadline")
        st.caption("A new item needs an owner and a deadline — that is the whole "
                   "point of the gate.")
        can_add = bool(new_task.strip()
                       and normalize_optional_text(new_owner) is not None
                       and normalize_optional_text(new_deadline) is not None)
        if st.button("Add", disabled=not can_add):
            try:
                deadline = parse_deadline(new_deadline)
            except ValueError as exc:
                st.error(str(exc))
            else:
                db.add_action_item(conn, meeting_id, task=new_task,
                                   owner=normalize_optional_text(new_owner), deadline=deadline)
                for key in ("new_task", "new_owner", "new_deadline"):
                    st.session_state.pop(key, None)
                st.rerun()

    st.divider()
    blocked = draft_blocked(items, gaps, resolved)
    if st.button("Draft follow-up message", type="primary", disabled=blocked):
        st.session_state["stage"] = Stage.EXPORT
        st.rerun()
    if blocked:
        st.caption("Resolve every 🔴 item above to enable this button.")


def _render_fixture(conn, meeting_id):
    """Synthetic fixture meetings are reference data for Ask meetings: shown in
    full, but with no edit, delete, resolve, add, or draft control. Re-seeding
    replaces them, so an edit here would be silently lost anyway."""
    st.subheader("2. Review what the agent found")
    st.info("Synthetic fixture meeting — read-only.")
    meta = db.load_extraction_meta(conn, meeting_id)
    if meta:
        st.markdown("### Summary")
        st.write(meta["summary"])
        participants_list = json.loads(meta["participants"])
        if participants_list:
            st.caption(f"Participants: {', '.join(participants_list)}")

    def section(heading, rows, text_key, fields):
        st.markdown(f"### {heading}")
        if not rows:
            st.caption("None recorded.")
        for row in rows:
            with st.container(border=True):
                st.markdown(row[text_key])
                details = [f"{label}: {display_value(row[key])}" for label, key in fields
                           if normalize_optional_text(row[key]) is not None]
                if details:
                    st.caption("  ·  ".join(details))
                if row["source_quote"]:
                    st.caption(f"From the notes: “{row['source_quote']}”")

    section("Decisions", db.load_decisions(conn, meeting_id), "decision", ())
    section("Action items", db.load_action_items(conn, meeting_id), "task",
            (("Owner", "owner"), ("Deadline", "deadline")))
    section("Risks", db.load_risks(conn, meeting_id), "description",
            (("Impact", "impact"), ("Likelihood", "likelihood"), ("Severity", "severity"),
             ("Mitigation", "mitigation"), ("Owner", "owner")))
    section("Dependencies", db.load_dependencies(conn, meeting_id), "description",
            (("Depends on", "depends_on"), ("Blocked by", "blocked_by"), ("Owner", "owner")))
    section("Learnings", db.load_learnings(conn, meeting_id), "lesson",
            (("Technical area", "technical_area"), ("Validation", "validation_status"),
             ("Follow-up experiment", "follow_up_experiment")))


def _render_prior_commitments():
    """What the agent was given as background, shown to the manager too.

    The extraction prompt already receives these. Rendering them here is what
    makes an owner suggestion auditable: without it the model sees earlier
    meetings and the manager does not, so a name the agent carried forward is
    indistinguishable on screen from one today's notes actually stated.
    Collapsed by default — it is context, not a task.
    """
    commitments = st.session_state.get("prior_commitments", ())
    if not commitments:
        return
    with st.expander(f"From earlier meetings ({len(commitments)})", expanded=False):
        for line in prior_commitment_lines(commitments):
            st.markdown(f"- {line}")
        st.caption(PRIOR_COMMITMENTS_CAPTION)


def _people(meta, items) -> list[str]:
    """Names to offer as owners: the participants the extraction detected, unioned
    with any owner already set.

    Sourcing this from existing owners alone (what it used to do) made the hint
    empty on exactly the screen that needs it — a meeting where no item has an
    owner yet is the whole point of the gate. The detected participants are
    already loaded in `meta` (PRD §4.3 asks for "a dropdown of detected
    participants").
    """
    detected = json.loads(meta["participants"]) if meta else []
    named = {normalize_optional_text(p) for p in detected}
    named |= {normalize_optional_text(i["owner"]) for i in items}
    return sorted(n for n in named if n is not None)


def _render_decision(conn, decision, gaps, resolved):
    with st.container(border=True):
        st.write(decision["decision"])
        st.caption(f"From the notes: “{decision['source_quote']}”")
        for gap in gaps_for_item(gaps, decision["id"]):
            _render_gap(gap, resolved)

        # A CONFLICTING_DECISION gap is blocking but no field edit can satisfy it
        # (gap_is_satisfied is False for every type outside DATA_FIXABLE_TYPES),
        # so without this control it can never enter resolved_ids and the meeting
        # is permanently un-draftable. PRD §3 puts "Resolve a contradictory
        # decision" squarely in the human column.
        # Key prefix is per-entity: a gap whose target is ambiguous must degrade
        # to a harmless double-render, never a duplicate-widget-key crash.
        for gap in unresolved_manual_gaps(gaps, decision["id"], resolved):
            st.caption("No edit to the data can settle this one — only you can. "
                       "Mark it resolved to confirm you have settled the "
                       "contradiction and decided which version stands.")
            if st.button("Mark resolved", key=f"res_decision_{gap.id}"):
                db.resolve_gap(conn, gap.id, True)
                st.rerun()

        if st.button("Delete", key=f"del_d_{decision['id']}"):
            db.delete_decision(conn, decision["id"])
            # Deleting the superseded decision is PRD §4.3 step 4's resolution
            # path. Mirror what _render_item's Delete does for action items: a
            # gap left open against a row that no longer exists blocks the gate
            # forever, with no control left on screen to discharge it.
            for gap in gaps_for_item(gaps, decision["id"]):
                db.resolve_gap(conn, gap.id)
            st.rerun()


def _render_unattached_gap(conn, gap):
    with st.container(border=True):
        st.markdown(f"{badge(gap)} — {gap.explanation}\n\n*Ask:* {gap.suggested_question}")
        if st.button("Mark resolved", key=f"res_unattached_{gap.id}"):
            db.resolve_gap(conn, gap.id, True)
            st.rerun()


def _render_gap(gap, resolved):
    if gap.id in resolved:
        return
    st.warning(f"{badge(gap)} — {gap.explanation}\n\n*Ask:* {gap.suggested_question}")


def _render_item(conn, item, gaps, resolved, participants):
    # item_gaps is filtered to UNRESOLVED gaps and is for badge display only.
    # The Save handler below must walk the unfiltered `gaps_for_item(...)` result
    # instead, so a gap can be reopened after it was resolved (see Decision 4) —
    # using this filtered list there silently defeats reopening.
    item_gaps = [g for g in gaps_for_item(gaps, item["id"]) if g.id not in resolved]
    with st.container(border=True):
        if item_gaps:
            st.markdown(" ".join(badge(g) for g in item_gaps))

        task = st.text_input("Task", value=item["task"], key=f"t_{item['id']}")
        col1, col2 = st.columns(2)
        # Defaults go through the shared predicate too, not a bare `or ""`: a row
        # holding a placeholder ("null", "TBD") must show as blank, because blank
        # is what every gate check already believes it to be.
        owner = col1.text_input("Owner",
                                value=normalize_optional_text(item["owner"]) or "",
                                placeholder="not stated in the notes",
                                key=f"o_{item['id']}")
        deadline_text = col2.text_input(
            "Deadline (YYYY-MM-DD)",
            value=normalize_optional_text(item["deadline"]) or "",
            placeholder="not stated in the notes",
            key=f"d_{item['id']}")
        suggestion = owner_suggestion(st.session_state.get("owner_hints", ()), item)
        if suggestion:
            st.caption(suggestion)
        if item["id"] in st.session_state.get("corrected_item_ids", set()):
            st.caption("✏️ revised by the agent on its second pass")
        if item["source_quote"]:
            st.caption(f"From the notes: “{item['source_quote']}”  ·  "
                       f"confidence {item['confidence']:.0%}")
        if participants:
            st.caption(f"People mentioned: {', '.join(participants)}")

        # Same control as on a decision, for the rarer case of a blocking gap on an
        # action item that no field edit can satisfy (a model may tag any gap type
        # BLOCKING). Without it such a gap has no route into resolved_ids either.
        for gap in unresolved_manual_gaps(gaps, item["id"], resolved):
            st.caption("No edit to the fields above can settle this one — mark it "
                       "resolved to confirm you have handled it yourself.")
            if st.button("Mark resolved", key=f"res_item_{gap.id}"):
                db.resolve_gap(conn, gap.id, True)
                st.rerun()

        col3, col4 = st.columns([1, 1])
        if col3.button("Save", key=f"s_{item['id']}"):
            try:
                deadline = parse_deadline(deadline_text)
            except ValueError as exc:
                st.error(str(exc))
            else:
                db.update_action_item(conn, item["id"], task=task,
                                      owner=normalize_optional_text(owner), deadline=deadline)
                for gap in gaps_for_item(gaps, item["id"]):
                    if needs_manual_resolution(gap):
                        continue  # a human's "I have handled this" is not something
                                  # a field edit can silently take back
                    db.resolve_gap(conn, gap.id, gap_is_satisfied(gap, owner, deadline_text))
                st.rerun()
        if col4.button("Delete", key=f"x_{item['id']}"):
            db.delete_action_item(conn, item["id"])
            for gap in gaps_for_item(gaps, item["id"]):
                db.resolve_gap(conn, gap.id)
            st.rerun()


def _render_technical_gaps(conn, record, gaps, resolved, key_prefix):
    """Shared by risk/dependency/learning rows: badge + explanation for every
    unresolved gap (mirrors `_render_decision`'s style, not `_render_item`'s
    compact badge line — A5 asks for the explanation to show, warning or
    blocking), plus a Mark-resolved control for any that need one.
    """
    for gap in gaps_for_item(gaps, record["id"]):
        _render_gap(gap, resolved)

    for gap in unresolved_manual_gaps(gaps, record["id"], resolved):
        st.caption("No edit to the fields above can settle this one — mark it "
                   "resolved to confirm you have handled it yourself.")
        if st.button("Mark resolved", key=f"{key_prefix}{gap.id}"):
            db.resolve_gap(conn, gap.id, True)
            st.rerun()


def _render_edited_caption(row, fields):
    """PRD F16: show which fields a human changed from the agent's original
    value. A human-created record (`origin == 'human'`) has no AI extraction
    to diff against, so it is left out — every field would otherwise read as
    "edited" against a frozen `ai_*` column that was never populated."""
    if row.get("origin") != "agent":
        return
    edited = edited_fields(row, fields)
    if edited:
        st.caption("✏️ edited from the agent's extraction: "
                   + ", ".join(e["field"] for e in edited))


def _render_technical_provenance(row):
    provenance = human_provenance_label(row)
    if provenance:
        st.caption(provenance)
    evidence_warning = missing_evidence_warning(row)
    if evidence_warning:
        st.warning(evidence_warning)


def _render_risk(conn, risk, gaps, resolved):
    with st.container(border=True):
        description = st.text_area("Description", value=risk["description"],
                                   key=f"risk_desc_{risk['id']}")
        col1, col2 = st.columns(2)
        impact = col1.text_input("Impact", value=display_value(risk["impact"]),
                                 placeholder="not stated in the notes",
                                 key=f"risk_impact_{risk['id']}")
        likelihood = col2.text_input("Likelihood", value=display_value(risk["likelihood"]),
                                     placeholder="not stated in the notes",
                                     key=f"risk_likelihood_{risk['id']}")
        col3, col4 = st.columns(2)
        severity = col3.text_input("Severity", value=display_value(risk["severity"]),
                                   placeholder="not stated in the notes",
                                   key=f"risk_severity_{risk['id']}")
        mitigation = col4.text_input("Mitigation", value=display_value(risk["mitigation"]),
                                     placeholder="not stated in the notes",
                                     key=f"risk_mitigation_{risk['id']}")
        owner = st.text_input("Owner", value=display_value(risk["owner"]),
                              placeholder="not stated in the notes",
                              key=f"risk_owner_{risk['id']}")
        _render_technical_provenance(risk)
        _render_edited_caption(risk, _RISK_FIELDS)
        if risk["source_quote"]:
            st.caption(f"From the notes: “{risk['source_quote']}”  ·  "
                       f"confidence {risk['confidence']:.0%}")

        _render_technical_gaps(conn, risk, gaps, resolved, "res_risk_")

        col5, col6 = st.columns([1, 1])
        new_description = required_text(description)
        if col5.button("Save", disabled=new_description is None,
                       key=f"risk_save_{risk['id']}"):
            db.update_risk(conn, risk["id"], description=new_description,
                          impact=normalize_optional_text(impact),
                          likelihood=normalize_optional_text(likelihood),
                          severity=normalize_optional_text(severity),
                          mitigation=normalize_optional_text(mitigation),
                          owner=normalize_optional_text(owner))
            st.rerun()
        if col6.button("Delete", key=f"risk_del_{risk['id']}"):
            db.delete_risk(conn, risk["id"])
            for gap in gaps_for_item(gaps, risk["id"]):
                db.resolve_gap(conn, gap.id)
            st.rerun()


def _render_dependency(conn, dependency, gaps, resolved):
    with st.container(border=True):
        description = st.text_area("Description", value=dependency["description"],
                                   key=f"dep_desc_{dependency['id']}")
        col1, col2 = st.columns(2)
        depends_on = col1.text_input("Depends on", value=display_value(dependency["depends_on"]),
                                     placeholder="not stated in the notes",
                                     key=f"dep_depends_on_{dependency['id']}")
        blocked_by = col2.text_input("Blocked by", value=display_value(dependency["blocked_by"]),
                                     placeholder="not stated in the notes",
                                     key=f"dep_blocked_by_{dependency['id']}")
        owner = st.text_input("Owner", value=display_value(dependency["owner"]),
                              placeholder="not stated in the notes",
                              key=f"dep_owner_{dependency['id']}")
        _render_technical_provenance(dependency)
        _render_edited_caption(dependency, _DEPENDENCY_FIELDS)
        if dependency["source_quote"]:
            st.caption(f"From the notes: “{dependency['source_quote']}”  ·  "
                       f"confidence {dependency['confidence']:.0%}")

        _render_technical_gaps(conn, dependency, gaps, resolved, "res_dep_")

        col3, col4 = st.columns([1, 1])
        new_description = required_text(description)
        if col3.button("Save", disabled=new_description is None,
                       key=f"dep_save_{dependency['id']}"):
            db.update_dependency(conn, dependency["id"], description=new_description,
                                 depends_on=normalize_optional_text(depends_on),
                                 blocked_by=normalize_optional_text(blocked_by),
                                 owner=normalize_optional_text(owner))
            st.rerun()
        if col4.button("Delete", key=f"dep_del_{dependency['id']}"):
            db.delete_dependency(conn, dependency["id"])
            for gap in gaps_for_item(gaps, dependency["id"]):
                db.resolve_gap(conn, gap.id)
            st.rerun()


def _render_learning(conn, learning, gaps, resolved):
    with st.container(border=True):
        lesson = st.text_area("Lesson", value=learning["lesson"],
                              key=f"learning_lesson_{learning['id']}")
        col1, col2 = st.columns(2)
        technical_area = col1.text_input(
            "Technical area", value=display_value(learning["technical_area"]),
            placeholder="not stated in the notes", key=f"learning_area_{learning['id']}")
        validation_status = col2.text_input(
            "Validation status", value=display_value(learning["validation_status"]),
            placeholder="not stated in the notes", key=f"learning_status_{learning['id']}")
        follow_up_experiment = st.text_input(
            "Follow-up experiment", value=display_value(learning["follow_up_experiment"]),
            placeholder="not stated in the notes", key=f"learning_experiment_{learning['id']}")
        _render_technical_provenance(learning)
        _render_edited_caption(learning, _LEARNING_FIELDS)
        if learning["source_quote"]:
            st.caption(f"From the notes: “{learning['source_quote']}”  ·  "
                       f"confidence {learning['confidence']:.0%}")

        _render_technical_gaps(conn, learning, gaps, resolved, "res_learning_")

        col3, col4 = st.columns([1, 1])
        new_lesson = required_text(lesson)
        if col3.button("Save", disabled=new_lesson is None,
                       key=f"learning_save_{learning['id']}"):
            db.update_learning(conn, learning["id"], lesson=new_lesson,
                               technical_area=normalize_optional_text(technical_area),
                               validation_status=normalize_optional_text(validation_status),
                               follow_up_experiment=normalize_optional_text(follow_up_experiment))
            st.rerun()
        if col4.button("Delete", key=f"learning_del_{learning['id']}"):
            db.delete_learning(conn, learning["id"])
            for gap in gaps_for_item(gaps, learning["id"]):
                db.resolve_gap(conn, gap.id)
            st.rerun()


def _render_add_risk(conn, meeting_id):
    with st.expander("Add a risk the agent missed"):
        description = st.text_area("Description", key="new_risk_description")
        impact = st.text_input("Impact", key="new_risk_impact")
        likelihood = st.text_input("Likelihood", key="new_risk_likelihood")
        severity = st.text_input("Severity", key="new_risk_severity")
        mitigation = st.text_input("Mitigation", key="new_risk_mitigation")
        owner = st.text_input("Owner", key="new_risk_owner")
        can_add = normalize_optional_text(description) is not None
        if st.button("Add risk", disabled=not can_add, key="add_risk_btn"):
            db.add_risk(conn, meeting_id, description=normalize_optional_text(description),
                       impact=normalize_optional_text(impact),
                       likelihood=normalize_optional_text(likelihood),
                       severity=normalize_optional_text(severity),
                       mitigation=normalize_optional_text(mitigation),
                       owner=normalize_optional_text(owner))
            for key in ("new_risk_description", "new_risk_impact", "new_risk_likelihood",
                       "new_risk_severity", "new_risk_mitigation", "new_risk_owner"):
                st.session_state.pop(key, None)
            st.rerun()


def _render_add_dependency(conn, meeting_id):
    with st.expander("Add a dependency the agent missed"):
        description = st.text_area("Description", key="new_dep_description")
        depends_on = st.text_input("Depends on", key="new_dep_depends_on")
        blocked_by = st.text_input("Blocked by", key="new_dep_blocked_by")
        owner = st.text_input("Owner", key="new_dep_owner")
        can_add = normalize_optional_text(description) is not None
        if st.button("Add dependency", disabled=not can_add, key="add_dep_btn"):
            db.add_dependency(conn, meeting_id, description=normalize_optional_text(description),
                             depends_on=normalize_optional_text(depends_on),
                             blocked_by=normalize_optional_text(blocked_by),
                             owner=normalize_optional_text(owner))
            for key in ("new_dep_description", "new_dep_depends_on",
                       "new_dep_blocked_by", "new_dep_owner"):
                st.session_state.pop(key, None)
            st.rerun()


def _render_add_learning(conn, meeting_id):
    with st.expander("Add a learning the agent missed"):
        lesson = st.text_area("Lesson", key="new_learning_lesson")
        technical_area = st.text_input("Technical area", key="new_learning_area")
        validation_status = st.text_input("Validation status", key="new_learning_status")
        follow_up_experiment = st.text_input("Follow-up experiment", key="new_learning_experiment")
        can_add = normalize_optional_text(lesson) is not None
        if st.button("Add learning", disabled=not can_add, key="add_learning_btn"):
            db.add_learning(conn, meeting_id, lesson=normalize_optional_text(lesson),
                           technical_area=normalize_optional_text(technical_area),
                           validation_status=normalize_optional_text(validation_status),
                           follow_up_experiment=normalize_optional_text(follow_up_experiment))
            for key in ("new_learning_lesson", "new_learning_area",
                       "new_learning_status", "new_learning_experiment"):
                st.session_state.pop(key, None)
            st.rerun()

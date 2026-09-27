import dataclasses

import pytest

from query.models import AnswerDraft
from query.prompts import build_answer_prompt
from query.verification import CitationVerificationError, verify_answer


def test_valid_citation_resolves_to_meeting_and_quote(indexed_conn, evidence):
    draft = AnswerDraft(status="answered", answer="The standard was approved.", citation_ids=[evidence[0].citation_id])
    verified = verify_answer(draft, evidence, indexed_conn)
    assert verified.citations[0].meeting_id == evidence[0].meeting_id
    assert evidence[0].text_fragment in verified.citations[0].quote


@pytest.mark.parametrize("citation_ids", [["invented"], ["c999"]])
def test_fabricated_or_unprovided_citations_fail(indexed_conn, evidence, citation_ids):
    draft = AnswerDraft(status="answered", answer="claim", citation_ids=citation_ids)
    with pytest.raises(CitationVerificationError):
        verify_answer(draft, evidence, indexed_conn)


def test_not_found_answer_has_no_citations(indexed_conn):
    draft = AnswerDraft(status="not_found", answer=None, citation_ids=[])
    assert verify_answer(draft, [], indexed_conn).citations == ()


def test_quote_not_present_in_stored_chunk_fails(indexed_conn, evidence):
    draft = AnswerDraft(status="answered", answer="claim", citation_ids=[evidence[0].citation_id])
    tampered = dataclasses.replace(evidence[0], text_fragment="fabricated quote")
    with pytest.raises(CitationVerificationError):
        verify_answer(draft, [tampered], indexed_conn)


def test_prompt_contains_only_labelled_evidence(evidence):
    system, user = build_answer_prompt("What was decided?", evidence[:1])
    assert "What was decided?" in user
    assert f"[{evidence[0].citation_id}]" in user
    assert evidence[0].text_fragment in user
    assert "database" not in user.lower()
    assert "only the supplied evidence" in system


def test_record_quote_absent_from_the_meeting_notes_fails(conn):
    """A record's own source_quote is model output; it must appear in the notes."""
    from query.models import EvidenceItem
    from storage import db

    meeting_id = db.save_meeting(conn, title="User", meeting_date="2026-09-26",
                                 raw_notes="Ana will send the minutes by Friday.")
    item_id = db.add_action_item(conn, meeting_id, task="Ship Zephyr", owner="Bob", deadline=None)
    conn.execute("UPDATE action_items SET source_quote = ? WHERE id = ?",
                 ("Bob promised to ship Zephyr by Friday", item_id))
    conn.commit()
    item = EvidenceItem(citation_id="r1", chunk_id="", meeting_id=meeting_id, title="User",
                        meeting_date="2026-09-26", text_fragment="Bob promised to ship Zephyr by Friday",
                        score=1.0, record_type="action_items", record_id=item_id)
    draft = AnswerDraft(status="answered", answer="Bob ships Zephyr.", citation_ids=["r1"])
    with pytest.raises(CitationVerificationError):
        verify_answer(draft, [item], conn)


def test_repeated_citation_ids_yield_one_citation(indexed_conn, evidence):
    draft = AnswerDraft(status="answered", answer="x",
                        citation_ids=[evidence[0].citation_id, evidence[0].citation_id])
    assert len(verify_answer(draft, evidence, indexed_conn).citations) == 1

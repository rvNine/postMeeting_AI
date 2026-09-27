from pathlib import Path

import pytest

from fixtures.technical_standardization.seed import seed_fixture_set
from storage import db
from storage.meeting_knowledge import (
    MeetingLink,
    list_meeting_links,
    load_meeting_context,
    validate_meeting_links,
)


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "technical_standardization"


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    db.init_db(connection)
    yield connection
    connection.close()


def test_links_are_directed_and_idempotent(conn):
    seed_fixture_set(conn, FIXTURE_DIR)

    links = list_meeting_links(conn)

    assert any(link.link_type == "supersedes" for link in links)
    assert links == sorted(
        links,
        key=lambda link: (link.source_meeting_id, link.target_meeting_id, link.link_type),
    )
    assert len({
        (link.source_meeting_id, link.target_meeting_id, link.link_type)
        for link in links
    }) == len(links)
    assert any(
        link.source_meeting_id != link.target_meeting_id
        and (link.target_meeting_id, link.source_meeting_id, link.link_type)
        not in {
            (item.source_meeting_id, item.target_meeting_id, item.link_type)
            for item in links
        }
        for link in links
    )

    seed_fixture_set(conn, FIXTURE_DIR)

    assert list_meeting_links(conn) == links


def test_list_links_can_filter_by_source_or_target_meeting(conn):
    seed_fixture_set(conn, FIXTURE_DIR)

    all_links = list_meeting_links(conn)
    filtered = list_meeting_links(conn, "fx-kickoff")

    assert filtered
    assert all(
        link.source_meeting_id == "fx-kickoff" or link.target_meeting_id == "fx-kickoff"
        for link in filtered
    )
    assert set(filtered) <= set(all_links)


def test_invalid_link_endpoint_fails_before_insert(conn):
    seed_fixture_set(conn, FIXTURE_DIR)

    with pytest.raises(ValueError, match="target meeting"):
        validate_meeting_links(
            conn,
            [MeetingLink("fx-kickoff", "missing", "continues", "quote", 0.9)],
        )


def test_invalid_source_endpoint_is_reported_separately(conn):
    seed_fixture_set(conn, FIXTURE_DIR)

    with pytest.raises(ValueError, match="source meeting"):
        validate_meeting_links(
            conn,
            [MeetingLink("missing", "fx-kickoff", "continues", "quote", 0.9)],
        )


@pytest.mark.parametrize(
    ("link", "message"),
    [
        (MeetingLink("fx-kickoff", "fx-current-state", "unknown", "quote", 0.9),
         "unsupported link type"),
        (MeetingLink("fx-kickoff", "fx-current-state", "continues", "quote", -0.1),
         "confidence"),
        (MeetingLink("fx-kickoff", "fx-current-state", "continues", "quote", 1.1),
         "confidence"),
        (MeetingLink("fx-kickoff", "fx-current-state", "continues", "   ", 0.9),
         "source quote"),
    ],
)
def test_link_contract_is_validated(conn, link, message):
    seed_fixture_set(conn, FIXTURE_DIR)

    with pytest.raises(ValueError, match=message):
        validate_meeting_links(conn, [link])


def test_duplicate_link_keys_are_rejected(conn):
    seed_fixture_set(conn, FIXTURE_DIR)
    link = MeetingLink("fx-kickoff", "fx-current-state", "continues", "quote", 0.9)

    with pytest.raises(ValueError, match="duplicate link"):
        validate_meeting_links(conn, [link, link])


def test_link_values_strip_surrounding_whitespace_only(conn):
    seed_fixture_set(conn, FIXTURE_DIR)
    link = MeetingLink(
        "fx-kickoff", "fx-current-state", " continues ", "  quote  ", 0.9,
    )

    validate_meeting_links(conn, [link])


def test_load_meeting_context_returns_canonical_metadata_and_notes(conn):
    seed_fixture_set(conn, FIXTURE_DIR)

    context = load_meeting_context(conn, "fx-kickoff")

    assert context.meeting_id == "fx-kickoff"
    assert context.title == "LatticeBridge kickoff and vocabulary"
    assert context.meeting_date == "2026-09-01"
    assert context.program_phase == "kickoff"
    assert context.participants[0].name == "Mira Vale"
    assert context.raw_notes.strip()

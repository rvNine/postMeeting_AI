from ui.markdown_export import build_export, export_filename

MEETING = {"id": "m1", "title": "Sprint 24 Review", "meeting_date": "2026-09-08"}
DECISIONS = [{"decision": "Move retry logic to the API layer"}]
ITEMS = [{"task": "Write the retry migration plan", "owner": "Sam",
          "deadline": "2026-09-12"}]


def test_export_contains_the_title_and_date():
    out = build_export(MEETING, DECISIONS, ITEMS, "the message")
    assert "Sprint 24 Review" in out
    assert "2026-09-08" in out


def test_export_lists_every_action_item_with_owner_and_deadline():
    out = build_export(MEETING, DECISIONS, ITEMS, "the message")
    assert "Write the retry migration plan" in out
    assert "Sam" in out
    assert "2026-09-12" in out


def test_export_includes_the_follow_up_message():
    assert "the message" in build_export(MEETING, DECISIONS, ITEMS, "the message")


def test_export_handles_a_meeting_with_no_decisions():
    out = build_export(MEETING, [], ITEMS, "msg")
    assert "None recorded" in out


def test_filename_is_slugified_and_dated():
    assert export_filename(MEETING) == "2026-09-08-sprint-24-review.md"


def test_filename_handles_punctuation_in_the_title():
    meeting = {"title": "Client call: Northwind / Q4", "meeting_date": "2026-09-11"}
    name = export_filename(meeting)
    assert "/" not in name
    assert name == "2026-09-11-client-call-northwind-q4.md"


def test_export_handles_a_meeting_with_no_action_items():
    """Symmetry with the decisions block: no bare '## Action items' heading."""
    out = build_export(MEETING, DECISIONS, [], "msg")
    assert out.count("None recorded.") == 1
    assert "## Action items\n\nNone recorded." in out


def test_a_blank_owner_or_deadline_renders_as_a_dash_not_none():
    """`- **task** — None — due None` reads like a person called None."""
    items = [{"task": "Chase the vendor", "owner": None, "deadline": None}]
    out = build_export(MEETING, DECISIONS, items, "msg")
    assert "None —" not in out
    assert "due None" not in out
    assert "- **Chase the vendor** — — — due —" in out


def test_a_placeholder_owner_also_renders_as_a_dash():
    items = [{"task": "Chase the vendor", "owner": "TBD", "deadline": "n/a"}]
    out = build_export(MEETING, DECISIONS, items, "msg")
    assert "TBD" not in out
    assert "n/a" not in out

from ui import technical_display
from ui.technical_display import display_value, edited_fields, record_count, required_text


def test_display_value_hides_optional_placeholders():
    assert display_value(None) == ""
    assert display_value("  ") == ""
    assert display_value("TBD") == ""
    assert display_value("high") == "high"


def test_edited_fields_reports_only_changed_ai_fields():
    row = {"severity": "medium", "ai_severity": "high",
           "mitigation": "Add capacity", "ai_mitigation": "Add capacity"}
    assert edited_fields(row, ("severity", "mitigation")) == [{
        "field": "severity", "ai_value": "high", "human_value": "medium"}]


def test_edited_fields_is_empty_when_every_field_matches_the_ai_value():
    row = {"lesson": "Cache invalidation is hard",
           "ai_lesson": "Cache invalidation is hard"}
    assert edited_fields(row, ("lesson",)) == []


def test_edited_fields_treats_a_missing_ai_column_as_edited():
    """A human-created record has no ai_* columns at all (they are NULL), so a
    populated field always reads as edited — there is nothing to diff against."""
    row = {"description": "New DB migration risk"}
    assert edited_fields(row, ("description",)) == [{
        "field": "description", "ai_value": None, "human_value": "New DB migration risk"}]


def test_record_count_counts_all_technical_kinds():
    assert record_count([1, 2], [3], []) == 3


def test_record_count_is_zero_when_nothing_was_extracted():
    assert record_count([], [], []) == 0


def test_required_text_strips_the_value_to_save():
    assert required_text("  Cache saturation during launch \n") == "Cache saturation during launch"


def test_required_text_is_none_for_blank_or_placeholder_text():
    """None means Save stays disabled: a risk/dependency description or a
    learning lesson must never be persisted blank."""
    for value in (None, "", "   \n", "TBD", "null"):
        assert required_text(value) is None


def test_human_created_record_has_provenance_and_missing_evidence_notices():
    row = {"origin": "human", "source_quote": "", "confidence": None}
    assert "human" in technical_display.human_provenance_label(row).lower()
    assert "no source quote" in technical_display.missing_evidence_warning(row).lower()


def test_agent_record_does_not_get_human_created_notices():
    row = {"origin": "agent", "source_quote": "cache saturation", "confidence": 0.8}
    assert technical_display.human_provenance_label(row) is None
    assert technical_display.missing_evidence_warning(row) is None

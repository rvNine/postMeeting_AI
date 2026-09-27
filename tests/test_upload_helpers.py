import pytest

from ui.upload_helpers import UploadError, decode_uploaded_meeting, title_from_filename


def test_decode_uploaded_meeting_accepts_utf8_text_and_markdown():
    assert decode_uploaded_meeting("notes.txt", b"# Design review\nDecision: ship") == (
        "# Design review\nDecision: ship"
    )
    assert decode_uploaded_meeting("notes.md", "Meeting notes".encode()) == "Meeting notes"


def test_decode_uploaded_meeting_rejects_unsupported_empty_and_invalid_files():
    with pytest.raises(UploadError, match=r"\.txt or \.md"):
        decode_uploaded_meeting("notes.pdf", b"notes")
    with pytest.raises(UploadError, match="empty"):
        decode_uploaded_meeting("notes.txt", b" \n")
    with pytest.raises(UploadError, match="UTF-8"):
        decode_uploaded_meeting("notes.txt", b"\xff\xfe")


def test_decode_uploaded_meeting_rejects_oversized_files():
    with pytest.raises(UploadError, match="too large"):
        decode_uploaded_meeting("notes.md", b"x", max_bytes=0)


def test_title_from_filename_uses_a_human_readable_stem():
    assert title_from_filename("architecture-review.md") == "Architecture Review"
    assert title_from_filename("team_notes.txt") == "Team Notes"

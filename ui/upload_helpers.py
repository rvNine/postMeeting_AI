"""Pure validation helpers for uploaded meeting-note files."""
from pathlib import PurePath


MAX_UPLOAD_BYTES = 2 * 1024 * 1024
_SUPPORTED_SUFFIXES = frozenset({".md", ".txt"})


class UploadError(ValueError):
    """A user-correctable uploaded-file validation error."""


def decode_uploaded_meeting(filename: str, data: bytes, *,
                            max_bytes: int = MAX_UPLOAD_BYTES) -> str:
    """Validate and decode one uploaded Markdown or plain-text notes file."""
    suffix = PurePath(filename).suffix.casefold()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise UploadError("Upload a .txt or .md meeting-notes file.")
    if len(data) > max_bytes:
        raise UploadError(f"The uploaded file is too large; maximum is {max_bytes} bytes.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UploadError("The uploaded file must be UTF-8 text.") from exc
    if not text.strip():
        raise UploadError("The uploaded file is empty.")
    return text


def title_from_filename(filename: str) -> str:
    """Turn an uploaded filename into a sensible editable meeting title."""
    stem = PurePath(filename).stem.replace("_", " ").replace("-", " ")
    return " ".join(stem.split()).title() or "Untitled meeting"

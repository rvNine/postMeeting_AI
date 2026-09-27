"""Pure evidence matching shared by extraction review and gap detection."""
import re


_WHITESPACE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip().lower()


def quote_supports(quote: str | None, notes: str) -> bool:
    """Return whether a normalized whole-word quote appears in notes."""
    if not quote or not quote.strip():
        return False
    needle, haystack = _normalise(quote), _normalise(notes)
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None

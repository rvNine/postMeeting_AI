"""Loads the sample meetings and their gold answers."""
import json
from pathlib import Path

_SAMPLES_DIR = Path(__file__).parent / "sample_meetings"
_EXPECTED_DIR = Path(__file__).parent / "expected"


def list_samples() -> list[dict]:
    samples = []
    for path in sorted(_SAMPLES_DIR.glob("*.md")):
        notes = path.read_text()
        first_line = notes.lstrip().splitlines()[0]
        samples.append({
            "slug": path.stem,
            "title": first_line.lstrip("# ").strip(),
            "notes": notes,
        })
    return samples


def load_expected(slug: str) -> dict:
    return json.loads((_EXPECTED_DIR / f"{slug}.json").read_text())

"""Typed loader and contract validation for the LatticeBridge fixture set."""
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


class FixtureManifestError(ValueError):
    """Raised when synthetic fixture data violates its published contract."""


@dataclass(frozen=True)
class FixtureRecord:
    id: str
    record_type: str
    source_quote: str
    confidence: float
    fields: dict[str, Any]


@dataclass(frozen=True)
class FixtureMeeting:
    slug: str
    meeting_id: str
    fixture_set: str
    title: str
    meeting_date: str
    phase: str
    sequence: int
    source_type: str
    facilitator: str
    participants: tuple[dict[str, str], ...]
    records: dict[str, tuple[FixtureRecord, ...]]
    source_path: Path
    raw_markdown: str

    @property
    def all_records(self) -> tuple[FixtureRecord, ...]:
        return tuple(record for records in self.records.values() for record in records)


@dataclass(frozen=True)
class FixtureLink:
    source_meeting_id: str
    target_meeting_id: str
    link_type: str
    quote: str
    confidence: float
    source_meeting: FixtureMeeting


@dataclass(frozen=True)
class GoldenQuery:
    fixture_set: str
    category: str
    question: str
    filters_expected: dict[str, Any]
    expected_meeting_ids: tuple[str, ...]
    expected_record_types: tuple[str, ...]
    expected_citation_phrases: tuple[str, ...]
    min_citation_count: int
    answerable: bool = True
    expected_status: str | None = None


@dataclass(frozen=True)
class FixtureManifest:
    meetings: tuple[FixtureMeeting, ...]
    links: tuple[FixtureLink, ...]
    golden_queries: tuple[GoldenQuery, ...]


def _record(record_type: str, value: dict[str, Any]) -> FixtureRecord:
    common = {key: value[key] for key in ("id", "source_quote", "confidence")}
    fields = {key: field for key, field in value.items() if key not in common}
    return FixtureRecord(record_type=record_type, fields=fields, **common)


def load_fixture_manifest(fixture_dir: Path) -> FixtureManifest:
    data = json.loads((fixture_dir / "manifest.json").read_text())
    meetings: list[FixtureMeeting] = []
    for item in data.get("fixtures", []):
        source_path = fixture_dir / f"{item['sequence']}_{item['slug'].replace('-', '_')}.md"
        if not source_path.exists():
            candidates = sorted(fixture_dir.glob(f"{item['sequence']}_*.md"))
            source_path = next(
                (candidate for candidate in candidates
                 if f"slug: {item.get('slug', '')}" in candidate.read_text()),
                source_path,
            )
        records = {
            record_type: tuple(_record(record_type, value) for value in values)
            for record_type, values in item.get("records", {}).items()
        }
        meetings.append(FixtureMeeting(
            slug=item.get("slug", ""), meeting_id=item.get("meeting_id", ""),
            fixture_set=item.get("fixture_set", ""), title=item.get("title", ""),
            meeting_date=item.get("meeting_date", ""), phase=item.get("phase", ""),
            sequence=item.get("sequence", 0), source_type=item.get("source_type", ""),
            facilitator=item.get("facilitator", ""),
            participants=tuple(item.get("participants", [])), records=records,
            source_path=source_path,
            raw_markdown=source_path.read_text() if source_path.exists() else "",
        ))
    by_id = {meeting.meeting_id: meeting for meeting in meetings}
    links = tuple(FixtureLink(
        source_meeting_id=item.get("source", ""), target_meeting_id=item.get("target", ""),
        link_type=item.get("type", ""), quote=item.get("quote", ""),
        confidence=item.get("confidence", -1),
        source_meeting=by_id.get(item.get("source", "")),
    ) for item in data.get("links", []))
    queries = tuple(GoldenQuery(
        fixture_set=item.get("fixture_set", ""), category=item.get("category", ""),
        question=item.get("question", ""), filters_expected=item.get("filters_expected", {}),
        expected_meeting_ids=tuple(item.get("expected_meeting_ids", [])),
        expected_record_types=tuple(item.get("expected_record_types", [])),
        expected_citation_phrases=tuple(item.get("expected_citation_phrases", [])),
        min_citation_count=item.get("min_citation_count", 0),
        answerable=item.get("answerable", True), expected_status=item.get("expected_status"),
    ) for item in data.get("golden_queries", []))
    return FixtureManifest(tuple(meetings), links, queries)


def _fail(message: str) -> None:
    raise FixtureManifestError(message)


def validate_fixture_manifest(manifest: FixtureManifest) -> None:
    if len({meeting.meeting_id for meeting in manifest.meetings}) != len(manifest.meetings):
        _fail("meeting IDs must be unique")
    meeting_ids = {meeting.meeting_id for meeting in manifest.meetings}
    record_ids: set[str] = set()
    for meeting in manifest.meetings:
        if not meeting.meeting_id or not meeting.meeting_id.startswith("fx-"):
            _fail("every meeting must have a canonical fx- ID")
        if meeting.fixture_set != "latticebridge-v1":
            _fail("unsupported fixture set")
        if not meeting.raw_markdown.strip():
            _fail(f"missing source for {meeting.meeting_id}")
        required = (meeting.title, meeting.meeting_date, meeting.phase, meeting.facilitator)
        if any(not value for value in required) or not meeting.participants:
            _fail(f"incomplete metadata for {meeting.meeting_id}")
        for record in meeting.all_records:
            if not record.id or record.id in record_ids:
                _fail(f"duplicate or missing record ID: {record.id}")
            record_ids.add(record.id)
            if not record.source_quote or record.source_quote not in meeting.raw_markdown:
                _fail(f"source quote does not resolve for {record.id}")
            if not 0 <= record.confidence <= 1:
                _fail(f"invalid confidence for {record.id}")
    link_keys: set[tuple[str, str, str]] = set()
    for link in manifest.links:
        key = (link.source_meeting_id, link.target_meeting_id, link.link_type)
        if key in link_keys:
            _fail(f"duplicate link: {key}")
        link_keys.add(key)
        if link.source_meeting_id not in meeting_ids or link.target_meeting_id not in meeting_ids:
            _fail(f"link endpoint missing: {key}")
        if not link.quote or link.source_meeting is None or link.quote not in link.source_meeting.raw_markdown:
            _fail(f"link quote does not resolve: {key}")
        if not 0 <= link.confidence <= 1:
            _fail(f"invalid link confidence: {key}")
    for query in manifest.golden_queries:
        if query.fixture_set != "latticebridge-v1" or not query.question:
            _fail("invalid golden query")
        if query.answerable and not query.expected_meeting_ids:
            _fail("answerable golden query has no expected meeting")
        if not query.answerable and (query.expected_meeting_ids or query.expected_status != "not_found"):
            _fail("abstention query must be not_found with no meetings")
        if query.min_citation_count < 0:
            _fail("invalid citation count")
        if not set(query.expected_meeting_ids) <= meeting_ids:
            _fail("golden query references missing meeting")
        for phrase in query.expected_citation_phrases:
            if not any(phrase in meeting.raw_markdown for meeting in manifest.meetings):
                _fail(f"golden citation phrase missing: {phrase}")

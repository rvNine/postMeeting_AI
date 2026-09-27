"""Deterministic, structured-first retrieval for meeting knowledge."""
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import re
import sqlite3

from query.models import EvidenceItem, QueryFilters
from query.vector import VectorAdapter
from storage.meeting_knowledge import MeetingLink, list_meeting_links

_STOP_WORDS = frozenset(
    "a an are be between by did do does for from has how in is it of on or the to "
    "was what when which who with "
    # Conversational filler: counting these as terms dilutes lexical coverage.
    "about after all also any as at been before being can could during had have "
    "i if into its me my our should so than that their them then there these they "
    "this those us we were where whose why will would you your "
    "discuss discussed meeting meetings mention mentioned raised said tell".split()
)
# Question wording mapped to the labels the notes use. A term also counts as
# covered when a chunk contains one of its listed stems.
_SYNONYMS = {
    "decid": ("decision",),
    "agre": ("decision",),
    "own": ("owner",),
    "chang": ("supersed",),
    "lesson": ("learn",),
    "unresolv": ("open", "miss"),
}
# Field labels the notes repeat on nearly every record ("Owner:", "Decision:",
# "Risk:" ...). A question word that only reaches one of these says what KIND of
# record is wanted, not what it is about, so it never counts toward coverage;
# otherwise "Who owns the <absent topic>?" is covered for free.
_LABEL_STEMS = frozenset({
    "decision", "rationale", "risk", "impact", "likelihood", "severity",
    "mitigation", "owner", "dependency", "depend", "block", "learn", "action",
})
_FRONT_MATTER_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_RECORD_TABLES = {
    "action_items": ("task", "owner"),
    "decisions": ("decision", None),
    "risks": ("description", "owner"),
    "dependencies": ("description", "owner"),
    "learnings": ("lesson", None),
}
@dataclass(frozen=True)
class RetrievalTrace:
    normalized_terms: tuple[str, ...]
    applied_filter_fields: tuple[str, ...]
    candidate_meeting_ids: tuple[str, ...]
    fts_scores: tuple[tuple[str, float], ...] = ()
    vector_scores: tuple[tuple[str, float], ...] = ()
    lexical_coverage_max: float = 0.0
    eligible_chunk_ids: tuple[str, ...] = ()
    rejected_chunk_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalBundle:
    evidence: list[EvidenceItem]
    structured_matches: list[EvidenceItem]
    relationships: list[MeetingLink]
    trace: RetrievalTrace


@dataclass(frozen=True)
class GoldenQueryResult:
    passed: bool
    status: str
    meeting_ids: tuple[str, ...]
    phrases_found: tuple[str, ...]
    applied_filter_fields: tuple[str, ...]


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(token.casefold() for token in _TOKEN_RE.findall(text)))


def normalized_terms(question: str) -> tuple[str, ...]:
    return tuple(token for token in _tokens(question) if token not in _STOP_WORDS)


def _fold(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _stem(token: str) -> str:
    """Reduce inflections to one shared stem; identifiers and numbers pass through."""
    if token.isdigit() or "_" in token:
        return token
    for suffix, replacement, min_length in (
        ("ies", "y", 5), ("ing", "", 6), ("ed", "", 5), ("es", "", 5), ("s", "", 4),
    ):
        if len(token) >= min_length and token.endswith(suffix) and not token.endswith("ss"):
            token = token[: -len(suffix)] + replacement
            break
    if len(token) > 4 and token.endswith("e"):
        token = token[:-1]
    return token


def _body(text: str) -> str:
    """Chunk text without its leading metadata block (slug, IDs, names, dates)."""
    return _FRONT_MATTER_RE.sub("", text, count=1)


def _term_alternatives(term: str) -> tuple[str, ...]:
    stem = _stem(term)
    return (stem, *_SYNONYMS.get(stem, ()))


def normalized_fts_rank(bm25_value: float) -> float:
    return 1.0 / (1.0 + max(0.0, bm25_value))


def eligible(*, lexical_coverage: float, fts_rank: float) -> bool:
    return lexical_coverage >= 0.75 and fts_rank >= 0.35


def combined_score(*, lexical_coverage: float, fts_rank: float, vector_score: float) -> float:
    return 0.7 * lexical_coverage + 0.2 * fts_rank + 0.1 * vector_score


def _filtered_meetings(conn: sqlite3.Connection, filters: QueryFilters) -> tuple[set[str], tuple[str, ...]]:
    rows = conn.execute("SELECT id FROM meetings ORDER BY id").fetchall()
    candidates = {row["id"] for row in rows}
    applied: list[str] = []

    def restrict(ids: Iterable[str], field: str) -> None:
        nonlocal candidates
        candidates &= set(ids)
        applied.append(field)

    if filters.date_from is not None:
        restrict(
            (row["id"] for row in conn.execute(
                "SELECT id FROM meetings WHERE meeting_date >= ?", (filters.date_from,)
            )),
            "date_from",
        )
    if filters.date_to is not None:
        restrict(
            (row["id"] for row in conn.execute(
                "SELECT id FROM meetings WHERE meeting_date <= ?", (filters.date_to,)
            )),
            "date_to",
        )
    if filters.meeting_id is not None:
        restrict((filters.meeting_id,), "meeting_id")
    if filters.participant is not None:
        restrict(
            (row["meeting_id"] for row in conn.execute(
                "SELECT meeting_id, name FROM meeting_participants"
            ) if _fold(row["name"]) == _fold(filters.participant)),
            "participant",
        )
    if filters.owner is not None:
        owner_ids: set[str] = set()
        for table in ("action_items", "risks", "dependencies"):
            owner_ids.update(
                row["meeting_id"] for row in conn.execute(
                    f"SELECT meeting_id, owner FROM {table} WHERE deleted = 0"
                ) if _fold(row["owner"]) == _fold(filters.owner)
            )
        restrict(owner_ids, "owner")
    if filters.record_type is not None:
        if filters.record_type not in _RECORD_TABLES:
            restrict((), "record_type")
        else:
            restrict(
                (row["meeting_id"] for row in conn.execute(
                    f"SELECT meeting_id FROM {filters.record_type} WHERE deleted = 0"
                )),
                "record_type",
            )
    if filters.severity is not None:
        restrict(
            (row["meeting_id"] for row in conn.execute(
                "SELECT meeting_id, severity FROM risks WHERE deleted = 0"
            ) if _fold(row["severity"]) == _fold(filters.severity)),
            "severity",
        )
    if filters.program_phase is not None:
        restrict(
            (row["meeting_id"] for row in conn.execute(
                "SELECT meeting_id, program_phase FROM meeting_metadata"
            ) if _fold(row["program_phase"]) == _fold(filters.program_phase)),
            "program_phase",
        )
    return candidates, tuple(applied)


def _record_matches(conn: sqlite3.Connection, meeting_ids: set[str], filters: QueryFilters) -> list[EvidenceItem]:
    if not filters.record_type or filters.record_type not in _RECORD_TABLES:
        return []
    table = filters.record_type
    text_column, _ = _RECORD_TABLES[table]
    placeholders = ",".join("?" for _ in meeting_ids)
    rows = conn.execute(
        f"SELECT r.*, r.{text_column} AS record_text, "
        f"m.title, m.meeting_date FROM {table} r JOIN meetings m ON m.id = r.meeting_id "
        f"WHERE r.deleted = 0 AND r.meeting_id IN ({placeholders}) ORDER BY r.meeting_id, r.id",
        tuple(sorted(meeting_ids)),
    ).fetchall()
    matches: list[EvidenceItem] = []
    for index, row in enumerate(rows, start=1):
        # The fragment becomes a citation quote, so it must stay verbatim.
        matches.append(EvidenceItem(
            citation_id=f"r{index}", chunk_id="", meeting_id=row["meeting_id"],
            title=row["title"], meeting_date=row["meeting_date"],
            text_fragment=row["source_quote"] or row["record_text"] or "", score=1.0,
            record_type=table, record_id=row["id"],
        ))
    return matches


def _fts_query(terms: Sequence[str]) -> str:
    """OR together quoted tokens; stems of 3+ letters match as prefixes."""
    parts: list[str] = []
    for term in terms:
        parts.append(f'"{term}"')
        for alternative in _term_alternatives(term):
            if len(alternative) >= 3 and not alternative.isdigit():
                parts.append(f'"{alternative}"*')
    return " OR ".join(dict.fromkeys(parts))


def _validated_relationships(
    conn: sqlite3.Connection,
    candidate_ids: set[str],
) -> list[MeetingLink]:
    """Return only persisted links whose filtered endpoints retain stored chunks."""
    endpoint_ids = {
        row["meeting_id"]
        for row in conn.execute("SELECT DISTINCT meeting_id FROM meeting_chunks")
    }
    return [
        link
        for link in list_meeting_links(conn)
        if link.source_meeting_id in candidate_ids
        and link.target_meeting_id in candidate_ids
        and link.source_meeting_id in endpoint_ids
        and link.target_meeting_id in endpoint_ids
    ]


def retrieve(
    conn: sqlite3.Connection,
    question: str,
    filters: QueryFilters,
    *,
    vector: VectorAdapter,
    limit: int = 8,
) -> RetrievalBundle:
    terms = normalized_terms(question)
    candidate_ids, applied = _filtered_meetings(conn, filters)
    structured = _record_matches(conn, candidate_ids, filters)
    if not terms or not candidate_ids:
        return RetrievalBundle([], structured, [], RetrievalTrace(terms, applied, tuple(sorted(candidate_ids))))

    placeholders = ",".join("?" for _ in candidate_ids)
    fts_rows = conn.execute(
        "SELECT chunk_id, meeting_id, bm25(meeting_chunk_fts) AS bm25_score "
        f"FROM meeting_chunk_fts WHERE meeting_id IN ({placeholders}) AND meeting_chunk_fts MATCH ?",
        (*sorted(candidate_ids), _fts_query(terms)),
    ).fetchall()
    fts_scores = {row["chunk_id"]: normalized_fts_rank(row["bm25_score"]) for row in fts_rows}
    vector_hits = vector.search(question, limit=max(limit * 4, 16), meeting_ids=candidate_ids)
    vector_scores = {hit.chunk_id: max(0.0, min(1.0, hit.score)) for hit in vector_hits}
    chunk_ids = sorted(set(fts_scores) | set(vector_scores))
    if not chunk_ids:
        return RetrievalBundle([], structured, [], RetrievalTrace(
            terms, applied, tuple(sorted(candidate_ids)),
            lexical_coverage_max=0.0,
        ))
    chunk_placeholders = ",".join("?" for _ in chunk_ids)
    rows = conn.execute(
        f"SELECT c.*, m.title, m.meeting_date FROM meeting_chunks c JOIN meetings m ON m.id = c.meeting_id "
        f"WHERE c.chunk_id IN ({chunk_placeholders})", tuple(chunk_ids),
    ).fetchall()
    by_id = {row["chunk_id"]: row for row in rows}
    relationships = _validated_relationships(conn, candidate_ids)
    scored: list[tuple[float, sqlite3.Row, float]] = []
    rejected: list[str] = []
    coverage_terms = tuple(term for term in terms if not term.isdigit() or len(term) > 1)
    term_alternatives = {_stem(term): set(_term_alternatives(term)) for term in coverage_terms}
    topic_terms = {stem: alternatives for stem, alternatives in term_alternatives.items()
                   if not alternatives & _LABEL_STEMS}
    # A question made only of labels ("What was decided?") is about those labels.
    term_alternatives = topic_terms or term_alternatives
    chunk_coverage: dict[str, float] = {}
    max_coverage = 0.0
    for chunk_id in chunk_ids:
        row = by_id.get(chunk_id)
        if row is None:
            continue
        chunk_stems = {_stem(token) for token in _tokens(_body(row["text"]))}
        present = [stem for stem, alternatives in term_alternatives.items() if alternatives & chunk_stems]
        coverage = len(present) / len(term_alternatives) if term_alternatives else 0.0
        chunk_coverage[chunk_id] = coverage
        max_coverage = max(max_coverage, coverage)
        fts_rank = fts_scores.get(chunk_id, 0.0)
        if not eligible(lexical_coverage=coverage, fts_rank=fts_rank):
            rejected.append(chunk_id)
            continue
        score = combined_score(
            lexical_coverage=coverage, fts_rank=fts_rank,
            vector_score=vector_scores.get(chunk_id, 0.0),
        )
        scored.append((score, row, coverage))
    seed_meeting_ids = {row["meeting_id"] for _, row, _ in scored}
    seeded_chunk_ids = {row["chunk_id"] for _, row, _ in scored}
    # Only chunks added here, through a stored link, are "related"; a direct hit
    # never carries a relationship label even if its meeting has links.
    expansion_labels: dict[str, str] = {}
    for link in relationships:
        if not seed_meeting_ids.intersection({link.source_meeting_id, link.target_meeting_id}):
            continue
        related_id = (
            link.target_meeting_id
            if link.source_meeting_id in seed_meeting_ids
            else link.source_meeting_id
        )
        related = conn.execute(
            "SELECT c.*, m.title, m.meeting_date FROM meeting_chunks c "
            "JOIN meetings m ON m.id = c.meeting_id WHERE c.meeting_id = ? "
            "ORDER BY c.sequence LIMIT 1",
            (related_id,),
        ).fetchone()
        if related is None or related["chunk_id"] in seeded_chunk_ids:
            continue
        scored.append((0.3, related, 0.0))
        seeded_chunk_ids.add(related["chunk_id"])
        expansion_labels[related["chunk_id"]] = link.link_type
    scored.sort(key=lambda item: (-item[0], item[1]["meeting_date"], item[1]["sequence"], item[1]["chunk_id"]))
    evidence = [
        EvidenceItem(
            citation_id=f"c{index}", chunk_id=row["chunk_id"], meeting_id=row["meeting_id"],
            title=row["title"], meeting_date=row["meeting_date"], text_fragment=row["text"],
            score=score, relationship_label=expansion_labels.get(row["chunk_id"]),
        )
        for index, (score, row, _) in enumerate(scored[:limit], start=1)
    ]
    trace = RetrievalTrace(
        normalized_terms=terms, applied_filter_fields=applied,
        candidate_meeting_ids=tuple(sorted(candidate_ids)),
        fts_scores=tuple(sorted(fts_scores.items())),
        vector_scores=tuple(sorted(vector_scores.items())),
        lexical_coverage_max=max_coverage,
        eligible_chunk_ids=tuple(item.chunk_id for item in evidence),
        rejected_chunk_ids=tuple(sorted(rejected)),
    )
    return RetrievalBundle(evidence, structured, relationships, trace)


def _filters_from_case(raw: Mapping[str, object]) -> QueryFilters:
    return QueryFilters(
        date_from=raw.get("date_from"),
        date_to=raw.get("date_to"),
        meeting_id=raw.get("meeting_id"), participant=raw.get("participant"),
        owner=raw.get("owner"), record_type=raw.get("record_type"),
        severity=raw.get("severity"), program_phase=raw.get("program_phase") or raw.get("phase"),
    )


def run_golden_queries(conn: sqlite3.Connection, cases: Sequence[Mapping[str, object]], vector: VectorAdapter) -> list[GoldenQueryResult]:
    results: list[GoldenQueryResult] = []
    for case in cases:
        raw_filters = case.get("filters", {})
        filters = _filters_from_case(raw_filters if isinstance(raw_filters, Mapping) else {})
        bundle = retrieve(conn, str(case["question"]), filters, vector=vector)
        corpus_parts = [item.text_fragment for item in bundle.evidence]
        corpus_parts.extend(item.text_fragment for item in bundle.structured_matches)
        corpus = "\n".join(corpus_parts)
        expected_phrases = tuple(str(item) for item in case.get("expected_phrases", ()))
        found = tuple(phrase for phrase in expected_phrases if phrase.casefold() in corpus.casefold())
        expected_meetings = tuple(case.get("expected_meetings", case.get("expected_meeting_ids", ())))
        actual_ids = [item.meeting_id for item in bundle.evidence]
        actual_ids.extend(item.meeting_id for item in bundle.structured_matches)
        actual_meetings = tuple(dict.fromkeys(actual_ids))
        answerable = bool(case.get("answerable", True))
        expected_filter_fields = set(case.get("filters_expected", {}).keys())
        expected_relationship_types = set(case.get("relationship_types", ()))
        actual_relationship_types = {
            item.relationship_label for item in bundle.evidence if item.relationship_label
        }
        actual_relationship_types.update(link.link_type for link in bundle.relationships)
        relationship_evidence_count = sum(
            1 for item in bundle.evidence if item.relationship_label
        )
        passed = (
            (bool(bundle.evidence or bundle.structured_matches) == answerable)
            and set(expected_meetings).issubset(set(actual_meetings) | set(item.meeting_id for item in bundle.structured_matches))
            and set(found) == set(expected_phrases)
            and expected_filter_fields == set(bundle.trace.applied_filter_fields)
            and expected_relationship_types <= actual_relationship_types
            and relationship_evidence_count >= int(case.get("min_relationship_evidence", 0))
        )
        results.append(GoldenQueryResult(
            passed,
            "answered" if bundle.evidence or bundle.structured_matches else "not_found",
            actual_meetings,
            found,
            bundle.trace.applied_filter_fields,
        ))
    return results

"""Replaceable, dependency-free vector-search boundaries for meeting chunks."""
from collections.abc import Sequence
from hashlib import sha256
import os
import re
import sqlite3
from typing import Protocol

from query.models import ChunkRecord, VectorHit


class VectorAdapter(Protocol):
    def upsert(self, chunks: Sequence[ChunkRecord]) -> None:
        """Add or replace chunks in the adapter's current index."""

    def search(
        self,
        query: str,
        *,
        limit: int,
        meeting_ids: set[str] | None = None,
    ) -> list[VectorHit]:
        """Return repeatably ordered vector candidates."""

    def replace_meeting(
        self, meeting_id: str, chunks: Sequence[ChunkRecord]
    ) -> None:
        """Make one meeting's indexed chunks exactly match ``chunks``."""


class NullVectorAdapter:
    """Default production backend when semantic vectors are not configured."""

    def upsert(self, chunks: Sequence[ChunkRecord]) -> None:
        return None

    def search(
        self,
        query: str,
        *,
        limit: int,
        meeting_ids: set[str] | None = None,
    ) -> list[VectorHit]:
        return []

    def replace_meeting(
        self, meeting_id: str, chunks: Sequence[ChunkRecord]
    ) -> None:
        return None


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


class DeterministicVectorAdapter:
    """Offline adapter that scores chunks by distinct token overlap only."""

    def __init__(self, chunks: Sequence[ChunkRecord] = ()):
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def upsert(self, chunks: Sequence[ChunkRecord]) -> None:
        self._chunks.update({chunk.chunk_id: chunk for chunk in chunks})

    def replace_meeting(
        self, meeting_id: str, chunks: Sequence[ChunkRecord]) -> None:
        """Discard obsolete chunks before installing a meeting's fresh index."""
        self._chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks.items()
            if chunk.meeting_id != meeting_id
        }
        self.upsert(chunks)

    def search(
        self,
        query: str,
        *,
        limit: int,
        meeting_ids: set[str] | None = None,
    ) -> list[VectorHit]:
        if limit <= 0:
            return []
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        hits = [
            VectorHit(
                chunk_id=chunk.chunk_id,
                score=len(query_tokens & _tokens(chunk.text)) / len(query_tokens),
            )
            for chunk in self._chunks.values()
            if (meeting_ids is None or chunk.meeting_id in meeting_ids)
            and query_tokens & _tokens(chunk.text)
        ]
        return sorted(hits, key=lambda hit: (-hit.score, hit.chunk_id))[:limit]


_configured_adapter: VectorAdapter = NullVectorAdapter()


def configure_vector_adapter(adapter: VectorAdapter) -> None:
    """Set the process-local adapter refreshed by meeting index rebuilds."""
    global _configured_adapter
    _configured_adapter = adapter


def configured_vector_adapter() -> VectorAdapter:
    """Return the application-selected vector adapter."""
    return _configured_adapter


def _chunk_rows(conn: sqlite3.Connection) -> list[ChunkRecord]:
    return [
        ChunkRecord(
            chunk_id=row["chunk_id"],
            meeting_id=row["meeting_id"],
            sequence=row["sequence"],
            text=row["text"],
            source_label=row["source_label"],
            start_offset=row["start_offset"],
            end_offset=row["end_offset"],
        )
        for row in conn.execute(
            "SELECT chunk_id, meeting_id, sequence, text, source_label, "
            "start_offset, end_offset FROM meeting_chunks "
            "ORDER BY meeting_id, sequence, chunk_id"
        ).fetchall()
    ]


def database_signature(conn: sqlite3.Connection) -> str:
    """Fingerprint persisted chunk content for safe process-local cache reuse."""
    digest = sha256()
    for chunk in _chunk_rows(conn):
        digest.update(
            "\x1f".join((
                chunk.chunk_id, chunk.meeting_id, str(chunk.sequence), chunk.text,
                chunk.source_label, str(chunk.start_offset), str(chunk.end_offset),
            )).encode()
        )
        digest.update(b"\x1e")
    return digest.hexdigest()


class ConfiguredVectorAdapterLoader:
    """Load an explicit offline adapter once for each SQLite chunk signature."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], VectorAdapter] = {}

    def load(
        self,
        conn: sqlite3.Connection,
        *,
        backend: str | None = None,
    ) -> VectorAdapter:
        selected = (backend or os.getenv("VECTOR_BACKEND", "none")).strip().casefold()
        if selected == "none":
            return NullVectorAdapter()
        if selected != "deterministic":
            raise ValueError(
                f"Unsupported VECTOR_BACKEND: {selected}. "
                "Use 'none' or the explicit offline backend 'deterministic'."
            )
        signature = database_signature(conn)
        key = (selected, signature)
        adapter = self._cache.get(key)
        if adapter is None:
            adapter = DeterministicVectorAdapter(_chunk_rows(conn))
            self._cache = {key: adapter}
        return adapter


_configured_loader = ConfiguredVectorAdapterLoader()


def load_configured_vector_adapter(
    conn: sqlite3.Connection,
    *,
    backend: str | None = None,
) -> VectorAdapter:
    """Select the configured backend and install it for index refreshes.

    Streamlit callers can cache this resource by the returned
    :func:`database_signature`; the loader independently guards against stale
    in-memory chunks on reruns or direct callers.
    """
    adapter = _configured_loader.load(conn, backend=backend)
    configure_vector_adapter(adapter)
    return adapter

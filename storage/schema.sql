CREATE TABLE IF NOT EXISTS meetings (
    id            TEXT PRIMARY KEY,
    title         TEXT,
    meeting_date  TEXT,
    raw_notes     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extractions (
    id             TEXT PRIMARY KEY,
    meeting_id     TEXT NOT NULL REFERENCES meetings(id),
    summary        TEXT NOT NULL,
    participants   TEXT NOT NULL,
    reviewer_notes TEXT,
    overall_confidence REAL,
    raw_response   TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    processing_pass INTEGER NOT NULL DEFAULT 1,
    model          TEXT NOT NULL,
    tokens_used    INTEGER,
    latency_ms     INTEGER,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_items (
    id            TEXT PRIMARY KEY,
    meeting_id    TEXT NOT NULL REFERENCES meetings(id),
    task          TEXT NOT NULL,
    owner         TEXT,
    deadline      TEXT,
    source_quote  TEXT,
    confidence    REAL,
    ai_task       TEXT,
    ai_owner      TEXT,
    ai_deadline   TEXT,
    origin        TEXT NOT NULL,
    deleted       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS decisions (
    id           TEXT PRIMARY KEY,
    meeting_id   TEXT NOT NULL REFERENCES meetings(id),
    decision     TEXT NOT NULL,
    rationale    TEXT,
    source_quote TEXT,
    confidence   REAL,
    deleted      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gaps (
    id          TEXT PRIMARY KEY,
    meeting_id  TEXT NOT NULL REFERENCES meetings(id),
    target_id   TEXT NOT NULL,
    type        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    explanation TEXT,
    suggested_question TEXT,
    resolved    INTEGER NOT NULL DEFAULT 0,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id          TEXT PRIMARY KEY,
    meeting_id  TEXT NOT NULL REFERENCES meetings(id),
    draft_text  TEXT NOT NULL,
    final_text  TEXT NOT NULL,
    approved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risks (
    id             TEXT PRIMARY KEY,
    meeting_id     TEXT NOT NULL REFERENCES meetings(id),
    description    TEXT NOT NULL,
    impact         TEXT,
    likelihood     TEXT,
    severity       TEXT,
    mitigation     TEXT,
    owner          TEXT,
    source_quote   TEXT,
    confidence     REAL,
    ai_description TEXT,
    ai_impact      TEXT,
    ai_likelihood  TEXT,
    ai_severity    TEXT,
    ai_mitigation  TEXT,
    ai_owner       TEXT,
    origin         TEXT NOT NULL,
    deleted        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dependencies (
    id             TEXT PRIMARY KEY,
    meeting_id     TEXT NOT NULL REFERENCES meetings(id),
    description    TEXT NOT NULL,
    depends_on     TEXT,
    blocked_by     TEXT,
    owner          TEXT,
    source_quote   TEXT,
    confidence     REAL,
    ai_description TEXT,
    ai_depends_on  TEXT,
    ai_blocked_by  TEXT,
    ai_owner       TEXT,
    origin         TEXT NOT NULL,
    deleted        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS learnings (
    id                      TEXT PRIMARY KEY,
    meeting_id              TEXT NOT NULL REFERENCES meetings(id),
    lesson                  TEXT NOT NULL,
    technical_area          TEXT,
    validation_status       TEXT,
    follow_up_experiment    TEXT,
    source_quote            TEXT,
    confidence              REAL,
    ai_lesson               TEXT,
    ai_technical_area       TEXT,
    ai_validation_status    TEXT,
    ai_follow_up_experiment TEXT,
    origin                  TEXT NOT NULL,
    deleted                 INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_items_meeting ON action_items(meeting_id);
CREATE INDEX IF NOT EXISTS idx_items_owner   ON action_items(owner);
CREATE INDEX IF NOT EXISTS idx_gaps_open     ON gaps(meeting_id, resolved);
CREATE INDEX IF NOT EXISTS idx_risks_meeting ON risks(meeting_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_meeting ON dependencies(meeting_id);
CREATE INDEX IF NOT EXISTS idx_learnings_meeting ON learnings(meeting_id);

CREATE TABLE IF NOT EXISTS meeting_metadata (
    meeting_id TEXT PRIMARY KEY REFERENCES meetings(id) ON DELETE CASCADE,
    program_name TEXT,
    program_phase TEXT,
    meeting_sequence INTEGER,
    facilitator TEXT,
    source_type TEXT,
    fixture_set TEXT
);

CREATE TABLE IF NOT EXISTS meeting_participants (
    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    participant_order INTEGER NOT NULL,
    name TEXT NOT NULL,
    role TEXT,
    PRIMARY KEY (meeting_id, participant_order),
    UNIQUE (meeting_id, name)
);

CREATE TABLE IF NOT EXISTS meeting_links (
    source_meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    target_meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL CHECK (link_type IN ('continues','supersedes','depends_on','reviews','implements','follow_up_to')),
    source_quote TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    PRIMARY KEY (source_meeting_id, target_meeting_id, link_type)
);

CREATE TABLE IF NOT EXISTS meeting_chunks (
    chunk_id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    text TEXT NOT NULL,
    source_label TEXT NOT NULL,
    start_offset INTEGER,
    end_offset INTEGER,
    UNIQUE (meeting_id, sequence)
);

CREATE VIRTUAL TABLE IF NOT EXISTS meeting_chunk_fts USING fts5(
    chunk_id UNINDEXED,
    meeting_id UNINDEXED,
    title,
    text,
    source_label
);

CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(meeting_date);
CREATE INDEX IF NOT EXISTS idx_metadata_phase ON meeting_metadata(program_phase);
CREATE INDEX IF NOT EXISTS idx_metadata_fixture_set ON meeting_metadata(fixture_set);
CREATE INDEX IF NOT EXISTS idx_participants_name ON meeting_participants(name);
CREATE INDEX IF NOT EXISTS idx_decisions_meeting ON decisions(meeting_id);
CREATE INDEX IF NOT EXISTS idx_risks_owner ON risks(owner);
CREATE INDEX IF NOT EXISTS idx_dependencies_owner ON dependencies(owner);
CREATE INDEX IF NOT EXISTS idx_chunks_meeting ON meeting_chunks(meeting_id);

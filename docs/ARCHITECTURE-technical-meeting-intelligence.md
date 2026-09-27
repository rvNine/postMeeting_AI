# Architecture — Technical Meeting Intelligence Subagent

## 1. Purpose

The Technical Meeting Intelligence Subagent analyzes one technical meeting or bounded source bundle and produces an evidence-backed technical meeting packet for human review.

The MVP uses one specialized subagent. It does not implement the future Continuity Agent or Engineering Briefing Agent.

All extraction, review, triage, and draft prompts are versioned together:
`agent/prompts.py::PROMPT_VERSION` is `"v4"`. Version 4 replaces the legacy
three-bucket contradiction with five explicit extracted record categories
(decision, action item, risk, dependency, and learning) and treats
discussion/background as non-record context. No paid v3 or v4 evaluation has
been run; the recorded metrics remain historical v1/v2 measurements.

## 2. System overview

```text
                         User
                           |
                           v
                 +-------------------+
                 | Streamlit UI      |
                 | notes + metadata  |
                 +---------+---------+
                           |
                           v
                 +-------------------+
                 | Input normalization|
                 +---------+---------+
                           |
                           v
                 +-------------------+
                 | Agent loop        |
                 | extract           |
                 | review            |
                 | triage            |
                 | one retry max     |
                 +---------+---------+
                           |
               +-----------+-----------+
               |                       |
               v                       v
       +---------------+       +---------------+
       | LLM layer     |       | Deterministic |
       | semantic      |       | safety layer  |
       | extraction    |       | evidence/gaps |
       +---------------+       +-------+-------+
                                       |
                                       v
                            +-------------------+
                            | Human review      |
                            | edit and approve  |
                            +---------+---------+
                                      |
                         +------------+------------+
                         |                         |
                         v                         v
                 +---------------+         +---------------+
                 | SQLite storage|         | Optional      |
                 | approved data |         | follow-up     |
                 | and audit     |         | draft         |
                 +---------------+         +---------------+
```

## 3. Core data flow

```text
Meeting notes or transcript
          |
          v
Extract structured packet
          |
          v
Review extraction against source
          |
          v
Run deterministic evidence and gap checks
          |
          v
Triage gaps: self-resolvable or human-only
          |
          v
Optional single corrective extraction pass
          |
          v
Final deterministic checks
          |
          v
Human edits and approves
          |
          v
Persist approved technical packet
```

The loop is bounded by `config.MAX_PASSES = 2`, meaning one initial extraction and at most one corrective extraction.

## 4. Agent boundary

### Input

The agent receives:

- Meeting title
- Meeting date
- Meeting type and project metadata when available
- Pasted notes or a local transcript
- Optional participant information
- Optional approved historical context
- Source metadata such as filename, URL, page, line, or timecode

Historical context is labeled as background. It cannot silently become a fact about the current meeting.

### Output

The agent returns one structured technical packet:

```text
MeetingExtraction
 ├─ summary
 ├─ participants[]
 ├─ decisions[]
 ├─ action_items[]
 ├─ risks[]
 ├─ dependencies[]
 └─ learnings[]
```

Every agent-extracted record includes a stable ID, confidence, and supporting
source quote. A record created by a human during review is the explicit
exception: it has `origin = 'human'`, no model confidence, and no source quote
unless a future evidence-collection flow is added. The current UI labels that
provenance and missing-evidence state rather than presenting the row as an
agent-backed claim.

## 5. Component responsibilities

| Component | Responsibility |
|---|---|
| `ui/` | Collect notes, display records, allow human edits, and show approval state. `ui/review_view.py` renders Decisions, Action items, Risks, Dependencies, and Learnings; technical rows have edit/delete controls and per-kind add forms. Agent evidence gaps render on their target row. Human-created technical rows show human provenance plus a missing-source-quote/model-confidence warning. Every unresolved gap with no displayed target, including warnings and malformed targets, renders under Other flags. |
| `agent/loop.py` | Control extraction passes, triage, and merge behavior |
| `agent/pipeline.py` | Run extraction, review, triage, and optional draft calls |
| `agent/schemas.py` | Define validated Pydantic models and normalize optional values |
| `agent/evidence.py` | Verify whether a claimed quote appears in the source |
| `agent/gaps.py` | Detect structural/evidence gaps and enforce the human gate |
| `agent/llm_client.py` | Provide the model-call interface and structured-output handling |
| `storage/db.py` | Persist meetings, technical records, edits, approvals, and audit data |
| `storage/schema.sql` | Define SQLite tables and indexes |
| `fixtures/` | Store local example meetings and technical inputs |
| `tests/` | Verify schemas, loop behavior, persistence, gates, and layer boundaries |

## 6. Role of the LLM

The LLM is the semantic language-understanding layer. It handles meaning that is difficult to capture with simple rules.

### LLM responsibilities

- Summarize discussion
- Identify participants
- Classify statements as decisions, actions, risks, dependencies, or learnings
- Keep discussion/background as non-record context unless a statement meets one
  of those five definitions
- Resolve references such as “she,” “the retry issue,” or “next Friday”
- Extract explicitly stated owners and deadlines
- Attach candidate evidence quotes
- Review its own extraction
- Decide whether a bounded corrective pass may help
- Draft an optional follow-up message after approval

Example:

```text
“We will use Postgres”
    -> Decision

“Sam will benchmark it by Friday”
    -> Action item

“Cache saturation may affect launch”
    -> Risk

“Integration is waiting for the API contract”
    -> Dependency
```

## 7. Deterministic safety layer

The LLM proposes information; deterministic code verifies it.

```text
LLM proposal
     |
     v
Schema validation
     |
     v
Quote verification
     |
     v
Structural gap detection
     |
     v
Human approval gate
```

The deterministic layer is responsible for:

- Normalizing `null`, `TBD`, `N/A`, blank, and placeholder values to `None`
- Making record ids unique across all five lists (`agent/loop.py::make_ids_unique`, run on the first pass before review; prefixes `a`, `d`, `r`, `dep`, `l`) — gaps key on `target_id`, so a shared id would let one record's evidence gap cover another
- Detecting missing action owners
- Detecting missing action deadlines
- Verifying source quotes (`agent/evidence.py::quote_supports`, whitespace/case-normalized, word-boundary-anchored)
- Detecting unsupported evidence — BLOCKING for a decision or action item, WARNING for a risk, dependency, or learning (`agent/gaps.py::detect_evidence_gaps`)
- Normalizing every reviewer-produced `unsupported_evidence` gap to that same
  target-kind severity, including a semantic finding whose irrelevant quote is
  nevertheless verbatim (`agent/gaps.py::normalize_evidence_severity`)
- Preserving blocking decision conflicts
- Preventing a model failure from opening the gate
- Preventing a draft from being generated with incomplete actions
- Rolling back partial persistence failures

The model cannot choose evidence severity. `normalize_evidence_severity` first
applies the record-kind policy to model-only semantic findings. Then
`agent/gaps.py::merge_with_deterministic` drops any model gap whose
`(target_id, type)` matches a deterministic evidence gap before merging, so the
deterministic wording and severity remain authoritative. Both `run_review` and
the loop's final backstop apply these rules. When the corrective pass's
re-review fails, the loop keeps the first review's model-only gaps (conflicts,
ambiguity) but recomputes owner, deadline, and evidence gaps from the merged
extraction, so a quote pass 2 broke is re-flagged and a quote pass 2 fixed is not.

## 8. Human approval boundary

### The agent may act independently

- Summarize discussion
- Classify statements
- Extract explicitly stated values
- Attach evidence
- Identify risks and dependencies
- Flag uncertainty and contradictions
- Perform one bounded corrective pass
- Create a draft packet

### The human must decide

- An unstated owner
- An unstated deadline
- Which contradictory decision is authoritative
- Whether an action is complete
- Whether a risk is accepted
- Whether a roadmap change is approved
- Whether an IPR signal has legal significance
- Whether an external message or system update should be sent

Core rule:

> The agent flags; it never fills.

## 9. Persistence architecture

The SQLite database stores:

```text
meetings
extractions
decisions
action_items
risks
dependencies
learnings
gaps
approvals
meeting_metadata        # program, phase, sequence, facilitator, fixture_set
meeting_participants
meeting_links           # directed: continues, supersedes, depends_on, reviews, implements, follow_up_to
meeting_chunks          # stable source chunks (sha256 IDs) for Ask meetings
meeting_chunk_fts       # FTS5 index over meeting_chunks
```

The meeting-knowledge tables are additive. `fixture_set` marks the ten
synthetic LatticeBridge meetings; the explicit seed command
(`python -m fixtures.technical_standardization.seed --db …`) replaces only rows
with that marker. `storage.db.delete_meeting` removes FTS rows and child rows in
one transaction; metadata, participants, links, and chunks cascade.

AI-generated values are frozen in `ai_*` columns. Human-editable values are stored separately so the application can show the difference between the original extraction and the human-approved record.

Human-created technical records use `origin = 'human'` and do not claim to have AI source evidence.

Each `extractions` row stores `processing_pass`, copied from
`LoopOutcome.passes` by `ui/input_view.py`, alongside model, prompt version,
token, latency, review, and raw-response metadata. A one-pass result stores 1;
a completed corrective extraction stores 2. `storage.db.init_db` performs an
additive migration for databases created before this column existed and gives
their existing rows the conservative default 1. It does not invent which old
records were corrected.

Human-created technical rows intentionally retain blank `source_quote` and null
`confidence` because the current add forms collect neither. The review UI shows
**Human-created record** and an explicit missing-evidence warning on every such
row. Agent `ai_*` values remain frozen, and the action-item add/edit/gate path is
unchanged.

All extraction writes occur in one transaction. A failure must leave no partial technical packet in the database.

## 10. Layer boundaries

```text
ui/  ───────────────► agent/
 │                      │
 └──────────────────► storage/
                         │
                         └──► SQLite

agent/ ─────────────► LLM client
```

Rules:

- `ui/` may call `agent/` and `storage/`, but may not import `sqlite3` or call SQL directly.
- `agent/` may call the LLM client, but may not import `storage` or Streamlit.
- `storage/` owns SQLite and may not import the LLM client or Streamlit.
- Pure UI helpers contain decisions that can be unit-tested without Streamlit.
- The LLM client is the only module that imports the model SDK.
- `ui/query_view.py` talks only to `query.service.QueryService`. It imports no
  `storage`, retrieval, verification, vector, or prompt module, and changes no data.

### Ask meetings (read-only query path)

```text
question + filters
  → QueryService.ask
      → retrieve: structured filters narrow meetings first, then FTS5 (+ optional
        vector adapter), 0.75 lexical-coverage gate, stable ranking, related
        meetings added only through stored, validated links
      → no eligible chunk evidence → not_found (no model call), with suggested filters
      → build_answer_prompt: only the retrieved evidence, labelled c1..cN / r1..rN
      → LLMClient.parse(AnswerDraft)
      → verify_answer: every citation ID was supplied; meeting/chunk/record exists;
        quote is verbatim in stored text
  → QueryResult: answered | not_found | error
```

`LLMError` and citation-verification failures both become `error`; neither is
turned into `not_found`. Nothing on this path writes to the
database; the action-item gate, gaps, and approvals are untouched.

## 11. Failure handling

| Failure | Safe behavior |
|---|---|
| Invalid structured output | Surface model/client error; do not save a packet |
| Missing owner/deadline | Preserve `null`; create blocking gap |
| Unsupported source quote | Create deterministic evidence gap |
| Review call failure | Use deterministic structural/evidence checks |
| Re-review failure after a corrective pass | Keep the first review's model-only gaps; recompute structural/evidence gaps from the merged extraction |
| Triage call failure | Treat gaps as human-only |
| Corrective extraction failure | Keep the first-pass result and show a manager note |
| Database write failure | Roll back the complete extraction transaction |
| Malformed or unattached gap target | Show every unresolved gap under Other flags, including warnings; only blocking gaps affect the draft gate |
| Placeholder model value | Normalize to `None` and keep the gate closed when required |
| Ask meetings finds no relevant evidence | Return `not_found` with suggested filters; do not call the model |
| Ask meetings answer cites an unsupplied ID or a non-verbatim quote | Return `error`; never render the answer or silently drop the citation |
| Ask meetings provider failure | Return `error`, distinct from `not_found` |

## 12. Future three-agent platform

The MVP produces approved technical records. Future agents can consume those records:

```text
Meeting notes, transcript, email, or document
                    |
                    v
        +----------------------------+
        | Meeting Evidence Agent     |
        | Analyze one source bundle  |
        +--------------+-------------+
                       |
                       v
              Human review and approval
                       |
                       v
        +----------------------------+
        | Engineering Continuity    |
        | Link approved records     |
        +--------------+-------------+
                       |
                       v
        +----------------------------+
        | Engineering Briefing      |
        | Produce useful briefs     |
        +--------------+-------------+
                       |
                       v
              Human review and action
```

### Meeting Evidence Agent

The current MVP. It analyzes one source bundle and creates an evidence-backed packet.

### Engineering Continuity Agent

Operates over approved packets to track:

- Decision history
- Repeated or changed commitments
- Contradictory decisions
- Recurring risks
- Dependencies and blockers
- Technical direction changes

### Engineering Briefing Agent

Creates:

- Weekly engineering summaries
- Open-action reports
- Decision registers
- Risk reports
- Roadmap-change summaries
- Suggested next-meeting agendas

These future agents must consume approved records and must not bypass the existing human approval boundary.

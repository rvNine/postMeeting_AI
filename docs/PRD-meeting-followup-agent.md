# PRD — Meeting Follow-up Agent

| Field | Value |
|---|---|
| **Document** | Product Requirements Document |
| **Project** | Module 1 — Design & Prototype Your AI Agent |
| **Product** | Meeting Follow-up Agent |
| **Version** | 1.0 |
| **Date** | 2026-09-15 |
| **Status** | Approved for prototype build |
| **Source** | `docs/proj1.txt`, `docs/proj1-use-cases.md` (§1, recommended option) |

---

## 1. Define the Problem

### 1.1 Problem statement

Managers spend a meaningful share of every week converting raw meeting notes into
decisions and action items. The conversion is manual, happens after the meeting when
attention has already moved on, and is the point at which commitments quietly
disappear. A decision made verbally at minute 34 becomes a line of shorthand in
someone's notebook, and then becomes nothing at all.

The failure is rarely that a task was *recorded* wrongly. It is that the task was
recorded without an **owner**, without a **deadline**, or in language too vague to act
on — "we should look into the vendor thing" — and nobody noticed the gap until the
next meeting.

### 1.2 Who is the user

**Primary user:** Team leads and project managers who run recurring meetings (standups,
sprint reviews, client calls, planning sessions) and are accountable for the follow-through.

**Secondary beneficiary:** Meeting attendees, who receive a clear, consistent follow-up
message instead of an inconsistent one or none at all.

**Explicit non-user for v1:** the attendees themselves do not log in, edit, or interact
with the system. The product is single-manager, single-seat.

### 1.3 Why the problem is worth solving

- **Dropped commitments are expensive and invisible.** An unassigned action item produces
  no error message. It surfaces a week later as a missed dependency.
- **The work is high-frequency and low-value.** A manager with four meetings a week does
  this transcription-and-structuring task ~200 times a year.
- **Inconsistency compounds.** Different meetings get written up to different standards,
  so no reliable record of "what did we decide" accumulates over time.
- **The gap is knowable at the moment of writing.** A missing owner is detectable
  immediately — it just requires someone to systematically look for it, every time,
  which is exactly the kind of diligence humans do not sustain.

### 1.4 Why AI is useful here

Meeting notes are unstructured, idiosyncratic, and inconsistently formatted. They mix
narrative, shorthand, interruptions, and side conversations. Deterministic parsing
(regex, keyword rules, templates) fails on this input class because the signal is
carried by *meaning*, not by syntax: "Priya said she'd take the migration" and
"migration — P" and "Priya: migration, EOW" are the same fact in three shapes.

An LLM is a good fit specifically because it can:

1. **Classify by intent** — distinguish a *decision* ("we're going with Postgres") from a
   *task* ("Sam to benchmark Postgres") from *discussion* ("Postgres has better JSON support").
2. **Resolve references** — map "she", "the team", "next Friday" onto concrete people and dates.
3. **Recognise absence** — identify that an action item has no owner, which is a semantic
   judgement, not a field-is-null check.
4. **Rewrite for an audience** — turn internal shorthand into a follow-up message that
   reads well to attendees.

**Where AI is a poor fit, and we do not use it:** deciding *who should* own a task,
*what* deadline is realistic, and whether a message is ready to send. Those are
management decisions with real consequences, and they stay with the human (see §2.3).

---

## 2. Identify the Agent

### 2.1 Receive → Decide → Do → Produce

| Stage | Definition |
|---|---|
| **Receives** | Raw meeting notes or a pasted transcript (free text, 50–10,000 words), plus optional meeting title and date, **plus context assembled from prior meetings** (recent commitments elsewhere, surfaced as background; owners a human previously supplied where the agent found none, surfaced to the UI only). |
| **Decides** | Which statements are decisions vs. action items vs. background discussion; who each action item belongs to; what deadline is implied; which of its own extractions are incomplete or low-confidence; **and, as of this iteration, whether another extraction pass would help** — triaging each flagged gap as something the notes already answer (self-resolvable) versus something only a person can settle. |
| **Does** | Structures the notes into a validated schema, self-reviews that structure for gaps, attaches a confidence score and gap reasons to each item, and blocks the final draft until blocking gaps are resolved. |
| **Produces** | (a) a meeting summary, (b) a decision list, (c) an action-item list with owner/deadline/confidence, (d) a flagged-gaps list requiring human input, and (e) — only after approval — a follow-up message draft. |

### 2.2 The agent loop

The agent is not a single prompt, and — as of this iteration — not a fixed
three-step pipeline either. It is an **observe → decide → act → evaluate → exit**
loop with a bounded budget: it extracts, reviews its own extraction, triages
each flagged gap into "the notes already answer this" versus "only a person
can settle this," and, only for the former, spends one bounded corrective pass
before handing off to the human gate. This decide-whether-to-act-again step is
what makes it a loop rather than a DAG: earlier revisions of this document
described a fixed three-call pipeline, and step 2's self-review was the only
place the agent reasoned about the limits of its own output. That self-review
is still here, unchanged; the loop adds one more decision on top of it.

```
  observe   notes + MeetingContext (prior commitments; owner hints held back for the UI)
     │
     ▼
   act ──►  EXTRACT                                    temp 0.1
     │
     ▼
 evaluate ► REVIEW + deterministic backstop            temp 0.0   (unchanged)
     │
     ▼
  decide ►  TRIAGE each gap                            temp 0.0
     │        SELF_RESOLVABLE  — the notes answer this; the extractor missed it
     │        NEEDS_HUMAN      — only a person can settle this
     │
     ├── any SELF_RESOLVABLE and budget remains ──► re-EXTRACT with feedback ──┐
     │                                                                          │
     └── otherwise ──────────────────────────────► EXIT to the human gate       │
                                                                     ▲──────────┘
     budget: MAX_PASSES = 2, hard stop. Exhaustion is a normal outcome.
                                     │
                      ╔══════════════▼═══════════════════════╗
                      ║  HUMAN GATE                          ║
                      ║  manager resolves every BLOCKING gap:║  autonomy: NONE
                      ║  confirms owners, sets deadlines,    ║  human decides
                      ║  edits or deletes items, approves.   ║
                      ║  (owner hints may be shown beside a  ║
                      ║  blank field; they never fill it.)   ║
                      ╚══════════════┬═══════════════════════╝
                                     │  (draft blocked until clear)
                      ┌──────────────▼───────────────────────┐
                      │  DRAFT                                │
                      │  approved items → follow-up message  │  autonomy: FULL
                      │                                      │  output: SUGGESTION
                      └──────────────┬───────────────────────┘
                                     │
                      ┌──────────────▼───────────────────────┐
                      │  HUMAN APPROVAL → export / copy      │
                      └──────────────────────────────────────┘
```

The human gate and the draft step are exactly what they were before the loop
existed — see §5.4/ARCHITECTURE.md §5 for why the gate is deliberately
**unchanged**: the loop runs it once, on the final pass, whichever pass that
turns out to be. Triage is the agent's judgement, so it gets the same
treatment as every other model judgement in this product: **the model
proposes, deterministic code disposes.** A `SELF_RESOLVABLE` verdict is only
believed if the model's own supporting quote is verified, in code, to actually
appear in the notes (`agent.pipeline.quote_supports`) — a model cannot talk
the loop into spending a pass on nothing. `MAX_PASSES = 2` bounds the whole
loop to at most five model calls per meeting (extract, review, triage,
re-extract, review), and running out of budget is a normal outcome, not an
error — it produces the same gated review screen with a note that the agent
tried and could not resolve the remainder.

### 2.3 Autonomy vs. human intervention

This split is the core product decision and is enforced in code, not by convention.

| Capability | Agent acts alone | Human must act | Rationale |
|---|:---:|:---:|---|
| Identify participants | ✅ | | Recoverable from text; low cost if wrong |
| Summarise the discussion | ✅ | | Lossy-but-useful is acceptable |
| Classify decision vs. action vs. discussion | ✅ | | Reversible — the human sees and can re-file it |
| Extract an explicitly stated owner | ✅ | | The text says so; agent is transcribing, not judging |
| Extract an explicitly stated deadline | ✅ | | As above |
| **Infer an unstated owner** | | ✅ | Assigning work is a management act with real consequences |
| **Infer an unstated deadline** | | ✅ | Committing the team to a date is a management act |
| **Resolve a contradictory decision** | | ✅ | The agent cannot know which version won the room |
| Flag a gap / score confidence | ✅ | | The agent is the cheapest reliable gap detector |
| **Decide to re-extract** | ✅ | | Bounded (`MAX_PASSES = 2`) and reversible — the merge never drops a human's or the first pass's work |
| **Judge a gap self-resolvable** | ✅ (deterministically verified) | | The model proposes a verdict; code independently checks the supporting quote actually appears in the notes before believing it — a model cannot talk its way into spending a pass on nothing |
| **Accept a remembered owner** | | ✅ | A previously-assigned owner is a suggestion, not a fact about today's meeting; it is displayed beside a blank field and never fills it — the field stays blocking until a human confirms it |
| Draft the follow-up message | ✅ | | It is a draft, and it is gated |
| **Send / export the message** | | ✅ | Outward-facing; always a human action |

**Design rule — the agent flags, it never fills.** When an owner is absent, the agent
must emit `owner: null` with a `MISSING_OWNER` gap. It is explicitly prohibited from
guessing a plausible name. A confidently wrong owner is far more damaging than an
obvious blank, because it removes the human's cue to check.

---

## 3. Complete System Map

### 3.1 Layer map

| Layer | Technology | Responsibility | Must NOT do |
|---|---|---|---|
| **Frontend** | Streamlit (`ui/`) | Notes input, review/edit surface, gap resolution, approval, export | Import the OpenAI SDK; write SQL |
| **Backend / orchestration** | Python (`agent/`) | Pipeline sequencing, prompt construction, schema validation, gap-gate logic, retries | Touch the database; render UI |
| **AI / model layer** | OpenAI API, Structured Outputs | Extraction, self-review, drafting — three distinct prompts + schemas | Be called from the UI directly |
| **Data / context** | SQLite (`storage/`) | Persist meetings, extractions, action items, approval audit trail, sample fixtures | Call the model; know about Streamlit |
| **Infrastructure** | Local `streamlit run`; optional Streamlit Community Cloud | Process host, `.env` secret loading | — |
| **External services** | OpenAI API only | LLM inference | No email, no calendar, no auth provider |

Although the prototype runs as a single process, these boundaries are enforced by import
discipline: each layer may only import from the layer below it. This keeps every layer
independently testable and makes the eventual split into a real API a mechanical change
rather than a rewrite.

### 3.2 Component structure

```
module1/
├── app.py                      # Streamlit entrypoint; routing + session state only
├── ui/
│   ├── input_view.py           # notes entry, sample-meeting picker, assembles MeetingContext and calls the loop
│   ├── review_view.py          # extraction display, inline editing, gap resolution, owner-hint + prior-commitment display
│   ├── context_builder.py      # storage rows -> MeetingContext; the seam that keeps agent/ free of storage/
│   └── export_view.py          # final message, copy / download
├── agent/
│   ├── pipeline.py             # run_extract, run_review, run_triage, run_draft — the four steps
│   ├── loop.py                 # run_agent_loop: sequences the four steps, owns the budget and the merge
│   ├── schemas.py              # Pydantic models + MeetingContext/OwnerHint/PriorCommitment (the contract for every layer)
│   ├── prompts.py              # the four system prompts (adds TRIAGE_SYSTEM), versioned — PROMPT_VERSION "v2"
│   ├── gaps.py                 # gap taxonomy + is_blocked() gate logic — unchanged by the loop
│   └── llm_client.py           # thin OpenAI wrapper: retries, timeouts, token accounting
├── storage/
│   ├── db.py                   # connection, schema migration, CRUD
│   ├── memory.py               # owner_hints(), prior_commitments() — two read queries over existing tables
│   └── schema.sql
├── fixtures/
│   └── sample_meetings/        # 5 sample notes (see §7.1)
├── tests/
│   ├── test_schemas.py
│   ├── test_gaps.py
│   └── test_pipeline.py        # stubbed LLM — no network
└── docs/
```

### 3.3 Data flow

1. Manager pastes notes (or loads a sample) → `ui/input_view.py`, which also calls
   `ui/context_builder.build_context()` to assemble a `MeetingContext` from
   `storage/memory.py` (empty on a first meeting or if the queries fail)
2. `agent.loop.run_agent_loop(notes, client, context=...)` runs the loop described
   in §2.2 — `run_extract` (call #1) → `run_review` (call #2) → `run_triage` if any
   gap exists (call #3) → conditionally one corrective `run_extract` + `run_review`
   (calls #4-5) — and returns the final `MeetingExtraction` and `ReviewResult`
   (confidence + gaps per item)
3. `storage.db.save_meeting(...)` persists raw notes, extraction, and review as
   **version 0 — the untouched AI output**
4. `ui/review_view.py` renders items, sorted gaps-first; manager edits inline.
   Owner hints from `MeetingContext.owner_hints` render beside a blank owner
   field as a suggestion; they are never written to it automatically
5. Each edit writes an `edits` row recording `(field, ai_value, human_value)`
6. `agent.gaps.is_blocked(items)` gates the Draft button; it enables only when no
   `severity = blocking` gap remains unresolved — **exactly the same check as
   before the loop existed**, run once on the loop's final pass
7. `agent.pipeline.run_draft(approved_items)` → one more OpenAI call → message draft
8. Manager approves → `approvals` row written → export as Markdown / clipboard copy

### 3.4 Deployment & configuration

- **Local:** `pip install -r requirements.txt` → `.env` with `OPENAI_API_KEY` →
  `streamlit run app.py` → `http://localhost:8501`
- **Hosted (optional):** Streamlit Community Cloud, API key via Streamlit secrets
- **Database:** `data/meetings.db`, created on first run from `storage/schema.sql`
- **Secrets:** environment only; `.env` is gitignored; the key is never logged,
  displayed, or written to the database

---

## 4. Product Specification

### 4.1 In scope (v1)

| # | Requirement | Acceptance criterion |
|---|---|---|
| F1 | Paste meeting notes | Textarea accepts ≥10,000 characters; optional title + date; Analyze disabled under 50 chars |
| F2 | Load a sample meeting | Dropdown of 5 fixtures; selecting one populates the textarea |
| F3 | Generate summary | 3–6 sentence narrative summary displayed |
| F4 | Extract decisions | Each decision shown with its supporting quote from the notes |
| F5 | Extract action items | Each with task, owner (or blank), deadline (or blank), confidence, source quote |
| F6 | Flag missing owners | Item with no stated owner shows a blocking `MISSING_OWNER` badge |
| F7 | Flag missing deadlines | Item with no stated deadline shows a blocking `MISSING_DEADLINE` badge |
| F8 | Flag ambiguity | Vague task wording or contradictory decisions flagged as a warning |
| F9 | Edit any field | Every extracted field is editable inline; edits persist |
| F10 | Add / delete items | Manager can add an item the agent missed, or delete a false positive |
| F11 | Gap gate | Draft button is disabled, with an explanatory message, while any blocking gap is open |
| F12 | Generate follow-up draft | Produces a message with greeting, decisions, per-owner action items, and deadlines |
| F13 | Approve & export | Approval recorded; Markdown download and clipboard copy available |
| F14 | View past meetings | List of saved meetings; selecting one reloads its approved state read-only |
| F15 | Show AI-vs-human diff | Approved view marks which fields the manager changed from the AI's original value |
| F16 | Assemble context from prior meetings | Before extraction, `ui/context_builder.build_context()` reads `storage/memory.py` and passes a `MeetingContext` (prior commitments, owner hints) into the loop; empty on the first meeting ever or if the queries fail |
| F17 | Triage each gap | After review, `run_triage` classifies every gap as `SELF_RESOLVABLE` or `NEEDS_HUMAN`; a `SELF_RESOLVABLE` verdict is accepted only if its supporting quote is independently verified (`quote_supports`) to actually appear in the notes |
| F18 | Bounded re-extraction | When triage finds something self-resolvable and budget remains (`MAX_PASSES = 2`), the agent runs one corrective extraction pass with the triage feedback and merges it over the first, never dropping an item the first pass (or a human) already produced |
| F19 | Owner suggestions | The review screen shows a previously-assigned owner beside a blank owner field ("previously assigned to Dan (3 times)"); it is a suggestion only — selecting it still requires the human to type or click it in, and the field stays blocking until they do |
| F20 | Prior-commitment background | The extraction prompt receives a delimited "background" block of recent commitments from other meetings, marked explicitly as context for resolving shorthand ("still on the retry thing"), not as facts about today's meeting, and never as a substitute for what today's notes say |

### 4.2 Out of scope (v1)

Meeting recording or live transcription · calendar integration · automatic email sending ·
authentication and multi-user accounts · task-tracker integration (Jira/Asana/Linear) ·
real-time collaborative editing · non-English notes · speaker diarization · mobile-native app ·
**completion tracking for action items** (memory means "previously committed, never marked
done here" — there is no notion of a commitment being verified still open or closed) ·
**multi-team or multi-tenant memory isolation** (the two memory queries read across all
meetings in the single local database; a second team's commitments and owners are
indistinguishable from the first team's).

F15 is deliberately included despite being beyond the source brief: it is the clearest
evidence for the assignment that a human-in-the-loop gate is doing real work.

### 4.3 Primary user journey

1. Manager finishes a sprint review and pastes their notes.
2. Clicks **Analyze**. ~10 seconds later: summary, 3 decisions, 7 action items.
3. The page opens on the gap list: *"4 details need your input before I can draft."*
   Two items have no owner; one has no deadline; one decision is flagged as contradicted
   later in the notes.
4. Manager assigns the two owners from a dropdown of detected participants, types a
   deadline, and resolves the contradiction by deleting the superseded decision.
5. The **Draft follow-up** button enables. Manager clicks it.
6. Reads the draft, tightens one sentence, clicks **Approve**.
7. Copies the Markdown into email. Total elapsed time: under three minutes.

### 4.4 Success metrics

| Metric | Target | How measured |
|---|---|---|
| Action-item recall | ≥ 90% of human-identified items found | Manual scoring against the 5 fixtures |
| Owner-attribution precision | 100% — zero fabricated owners | Any invented name is a P0 bug |
| Gap-detection recall | ≥ 95% of genuinely missing owners/deadlines flagged | Fixtures have known planted gaps |
| Time to approved follow-up | < 3 minutes per meeting | Timed walkthrough |
| End-to-end latency | < 20 s for a 1,500-word note | Instrumented timing |
| Gate integrity | 0 drafts generated with an open blocking gap | Unit test |

---

## 5. Technical Specification

### 5.1 Stack

| Concern | Choice | Reason |
|---|---|---|
| Language | Python 3.11+ | Ecosystem fit; matches course tooling |
| UI | Streamlit ≥ 1.30 | Removes frontend build cost; the value is in the agent, not the CSS |
| Validation | Pydantic v2 | The schema is the contract between all four layers |
| LLM | OpenAI `gpt-4o-mini` (default), `gpt-4o` fallback for long notes | Structured Outputs guarantees schema-valid JSON |
| Persistence | SQLite via stdlib `sqlite3` | Zero-config, file-backed, queryable action items |
| Config | `python-dotenv` | Keeps the API key out of source |
| Tests | `pytest` | Stubbed LLM; no network in CI |

### 5.2 Core schemas (`agent/schemas.py`)

```python
from enum import Enum
from datetime import date
from pydantic import BaseModel, Field

class GapType(str, Enum):
    MISSING_OWNER     = "missing_owner"       # blocking
    MISSING_DEADLINE  = "missing_deadline"    # blocking
    AMBIGUOUS_TASK    = "ambiguous_task"      # warning
    CONFLICTING_DECISION = "conflicting_decision"  # blocking
    UNRESOLVED_QUESTION  = "unresolved_question"   # warning

class Severity(str, Enum):
    BLOCKING = "blocking"
    WARNING  = "warning"

class Gap(BaseModel):
    id: str
    type: GapType
    severity: Severity
    target_id: str                     # action_item or decision id
    explanation: str = Field(..., description="Why this is a gap, in one sentence")
    suggested_question: str            # what to ask the team, if unresolvable alone

class ActionItem(BaseModel):
    id: str
    task: str                          # imperative phrasing
    owner: str | None = None           # null when not stated — NEVER guessed
    deadline: date | None = None       # null when not stated — NEVER guessed
    source_quote: str                  # verbatim span from the notes
    confidence: float = Field(ge=0.0, le=1.0)

class Decision(BaseModel):
    id: str
    decision: str
    rationale: str | None = None
    source_quote: str
    confidence: float = Field(ge=0.0, le=1.0)

class MeetingExtraction(BaseModel):          # ← step 1 output schema
    summary: str
    participants: list[str]
    decisions: list[Decision]
    action_items: list[ActionItem]

class ReviewResult(BaseModel):               # ← step 2 output schema
    gaps: list[Gap]
    overall_confidence: float = Field(ge=0.0, le=1.0)
    reviewer_notes: str
```

`source_quote` is mandatory on every extracted object. It makes each claim auditable
against the original notes in one glance and is the cheapest available defence against
hallucinated content.

### 5.3 The three model calls

| # | Name | Input | Response schema | Temp | Failure handling |
|---|---|---|---|---|---|
| 1 | `run_extract` | raw notes | `MeetingExtraction` | 0.1 | 2 retries; on schema failure surface the raw response and let the user retry |
| 2 | `run_review` | raw notes + step-1 JSON | `ReviewResult` | 0.0 | 2 retries; on failure fall back to deterministic gap detection (§5.4) |
| 3 | `run_draft` | approved items only | plain text | 0.4 | 1 retry; editable by hand regardless |

Every call uses OpenAI **Structured Outputs** (`response_format={"type":"json_schema",
"strict": true}`) so the response is schema-valid by construction rather than by parsing
and hoping. Timeout 60 s; exponential backoff on 429/5xx.

**Prompt design rules (all three prompts):**
- State the null-over-guess rule explicitly and repeat it in the output-format section.
- Require a verbatim `source_quote` for every extracted object.
- Step 2's prompt frames the model as an adversarial reviewer of a *different* agent's
  work — self-critique framed as peer review produces measurably more flags.
- Prompts live in `agent/prompts.py` with a version constant, stored on each result row
  so a regression can be traced to a prompt change.

### 5.4 Gap gate (`agent/gaps.py`)

The gate is not left to the model. A deterministic layer runs after step 2 and adds any
gap the model missed:

```python
BLOCKING = {GapType.MISSING_OWNER, GapType.MISSING_DEADLINE,
            GapType.CONFLICTING_DECISION}

def detect_structural_gaps(extraction) -> list[Gap]:
    """Deterministic backstop — runs regardless of what the reviewer returned."""
    gaps = []
    for item in extraction.action_items:
        if not item.owner:
            gaps.append(Gap(type=GapType.MISSING_OWNER, severity=Severity.BLOCKING, ...))
        if not item.deadline:
            gaps.append(Gap(type=GapType.MISSING_DEADLINE, severity=Severity.BLOCKING, ...))
    return gaps

def is_blocked(items, resolved_gap_ids) -> bool:
    return any(g.severity is Severity.BLOCKING and g.id not in resolved_gap_ids
               for g in all_gaps(items))
```

`is_blocked()` is the single source of truth for whether step 3 may run. The UI reads it
to disable the button; `pipeline.run_draft()` re-checks it and raises if violated, so the
gate cannot be bypassed by a UI bug.

### 5.5 Database schema (`storage/schema.sql`)

```sql
CREATE TABLE meetings (
    id            TEXT PRIMARY KEY,
    title         TEXT,
    meeting_date  TEXT,
    raw_notes     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL      -- draft | reviewed | approved
);

CREATE TABLE extractions (
    id             TEXT PRIMARY KEY,
    meeting_id     TEXT NOT NULL REFERENCES meetings(id),
    summary        TEXT NOT NULL,
    participants   TEXT NOT NULL,    -- JSON array
    raw_response   TEXT NOT NULL,    -- untouched model output, for audit
    prompt_version TEXT NOT NULL,
    model          TEXT NOT NULL,
    tokens_used    INTEGER,
    latency_ms     INTEGER,
    created_at     TEXT NOT NULL
);

CREATE TABLE action_items (
    id            TEXT PRIMARY KEY,
    meeting_id    TEXT NOT NULL REFERENCES meetings(id),
    task          TEXT NOT NULL,
    owner         TEXT,             -- NULL = agent found none
    deadline      TEXT,
    source_quote  TEXT,
    confidence    REAL,
    ai_owner      TEXT,             -- the agent's original value, frozen
    ai_deadline   TEXT,             -- the agent's original value, frozen
    ai_task       TEXT,
    origin        TEXT NOT NULL,    -- 'agent' | 'human'
    deleted       INTEGER DEFAULT 0
);

CREATE TABLE decisions (
    id           TEXT PRIMARY KEY,
    meeting_id   TEXT NOT NULL REFERENCES meetings(id),
    decision     TEXT NOT NULL,
    rationale    TEXT,
    source_quote TEXT,
    confidence   REAL,
    deleted      INTEGER DEFAULT 0
);

CREATE TABLE gaps (
    id          TEXT PRIMARY KEY,
    meeting_id  TEXT NOT NULL REFERENCES meetings(id),
    target_id   TEXT NOT NULL,
    type        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    explanation TEXT,
    resolved    INTEGER DEFAULT 0,
    resolved_at TEXT
);

CREATE TABLE approvals (
    id          TEXT PRIMARY KEY,
    meeting_id  TEXT NOT NULL REFERENCES meetings(id),
    draft_text  TEXT NOT NULL,
    final_text  TEXT NOT NULL,      -- after human edits
    approved_at TEXT NOT NULL
);

CREATE INDEX idx_items_meeting ON action_items(meeting_id);
CREATE INDEX idx_items_owner   ON action_items(owner);
CREATE INDEX idx_gaps_open     ON gaps(meeting_id, resolved);
```

Keeping `ai_owner` / `ai_deadline` / `ai_task` frozen alongside the live values is what
powers F15 and the evaluation in §7.2 — the database records not just the outcome but
the disagreement between agent and human.

### 5.6 Error handling

| Failure | Behaviour |
|---|---|
| Missing/invalid API key | Startup banner with setup instructions; Analyze disabled |
| Rate limit (429) | Exponential backoff, 3 attempts, then "Service busy — retry" |
| Schema validation failure after retries | Show raw response in an expander; offer retry; nothing persisted |
| Notes exceed context window | Warn at >10,000 words; offer to process the first N words or split |
| Empty/no-content notes | Agent returns empty lists with `reviewer_notes` explaining why; not an error |
| Network timeout | Surface plainly; raw notes are never lost from session state |
| DB locked / write failure | Keep results in session state, show a persistence warning, allow export anyway |

**Principle:** a failure must never silently produce a partial result. Either the meeting
is fully extracted and persisted, or the user is told exactly what failed.

### 5.7 Non-functional requirements

- **Latency:** < 20 s end-to-end for 1,500 words; spinner with per-step labels
  ("Extracting… / Reviewing…") so the pipeline is legible while it runs.
- **Cost:** < $0.02 per meeting on `gpt-4o-mini`; token usage recorded per call.
- **Privacy:** notes are sent only to OpenAI; nothing else leaves the machine; the DB is a
  local file; no telemetry.
- **Reliability:** any single model call may fail without losing the user's input.
- **Portability:** runs on Linux/macOS/Windows with Python 3.11+ and no native deps.
  (No AVX2-dependent libraries — SQLite and the OpenAI SDK are pure-Python/stdlib.)

---

## 6. Risks & Mitigations

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | Agent fabricates an owner or deadline | **Critical** — destroys trust, defeats the gate | Null-over-guess rule in prompt + deterministic backstop in §5.4 + `source_quote` audit + fixture test asserting zero invented names |
| R2 | Self-review is a rubber stamp (step 2 approves everything) | High — gate becomes theatre | Peer-review prompt framing; deterministic gaps run regardless; fixture 2 has zero stated owners and must produce 6 blocking flags |
| R3 | Over-extraction: discussion turned into fake action items | Medium — manager loses time deleting | Low temperature; explicit negative examples in the prompt; F10 delete; precision tracked in §7.2 |
| R4 | Long transcripts exceed context | Medium | Word-count warning + truncation choice; `gpt-4o` fallback |
| R5 | Gate bypassed by a UI bug | High | `run_draft()` re-checks `is_blocked()` server-side and raises; unit-tested |
| R6 | Scope creep into calendar/email integration | Medium — misses the deadline | §4.2 is binding for v1 |
| R7 | Model or API version drift changes output quality | Medium | Pinned model string; `prompt_version` + `model` stored per run for traceability |
| R8 | Memory leaks a remembered owner into extraction, fabricating an owner | **Critical** — the exact failure R1 exists to prevent, now via a new channel | `owner_hints` never enters a prompt (invariant of the loop design), enforced by a test that scans the stub client's recorded calls for the string |
| R9 | The loop spends a second pass for no gain | Medium — doubles cost for nothing | The triage quote-verification gate means only a verified self-resolvable gap spends a pass; the eval's `pass2_gain` measures the actual gain per fixture, including reporting zero honestly — see `docs/evaluation-results.md` |
| R10 | Re-extraction drops an item a human already edited | High — silently discards human work | `merge_extractions` keeps every pass-1 item unconditionally; a pass-2 item only updates or adds, never removes; unit-tested including the human-edited case |
| R11 | Prior commitments confuse the extractor into importing last week's items | Medium — false positives from stale context | Delimited "background" block, explicit "not facts about today's meeting" framing; precision measured against fixture 4 in the eval |
| R12 | Cost and latency roughly double with the loop | Medium | `MAX_PASSES = 2` hard stop bounds a meeting to at most 5 model calls (vs. 2 before); per-pass tokens still recorded; the v2 eval run measured the actual call count per fixture rather than assuming the worst case |

---

## 7. Initial Prototype & Validation

### 7.1 The five sample meetings

Each fixture targets a specific agent behaviour, with planted gaps whose expected
detection is recorded in `fixtures/expected/`.

| # | Fixture | Characteristics | What it proves |
|---|---|---|---|
| 1 | `clean_sprint_review.md` | Well-structured; explicit owners and dates throughout | Happy path — high confidence, **zero blocking gaps, draft enabled immediately** |
| 2 | `no_owners_planning.md` | Real decisions, but every task phrased passively ("we should…", "someone needs to…") | Gap detection — **6 `MISSING_OWNER` + 6 `MISSING_DEADLINE` = 12 blocking flags, draft blocked** |
| 3 | `conflicting_decisions.md` | A decision made early, then reversed 20 lines later without saying so | `CONFLICTING_DECISION` flag; agent surfaces both and refuses to pick |
| 4 | `rambling_client_call.md` | Long, tangential, mixes personal chat with two genuine commitments | Precision under noise — exactly 2 action items; must not turn small talk into action items |
| 5 | `sparse_standup.md` | ~60 words of shorthand, almost no structure | Graceful degradation — few items, low confidence, honest `reviewer_notes` |

### 7.2 Evaluation method

For each fixture, a human-authored gold answer lists the true action items, decisions,
and expected gaps. Scoring per fixture:

- **Recall** — true items the agent found ÷ total true items (target ≥ 0.90)
- **Precision** — true items among those extracted ÷ total extracted (target ≥ 0.85)
- **Gap recall** — planted gaps flagged ÷ planted gaps (target ≥ 0.95)
- **Fabrication count** — owners/deadlines asserted but absent from the notes
  (**target: 0; any non-zero result blocks the demo**)

Results go in `docs/evaluation-results.md` with the per-fixture table — the honest version,
including whatever the agent gets wrong.

### 7.3 Automated tests

- `test_schemas.py` — Pydantic rejects confidence out of `[0,1]`, invalid dates, missing
  `source_quote`
- `test_gaps.py` — `detect_structural_gaps` flags every null owner/deadline; `is_blocked`
  returns True with one open blocking gap and False when all are resolved
- `test_pipeline.py` — with a stubbed LLM client: extraction persists correctly; a
  malformed model response does not corrupt the DB; **`run_draft()` raises when a blocking
  gap is open**

No test touches the network. The stub returns canned JSON per fixture.

### 7.4 Demo script

1. Load fixture 1 → Analyze → clean extraction, no gaps, draft available at once.
2. Load fixture 2 → Analyze → twelve blocking flags (six items, each missing both an
   owner and a deadline), **Draft button visibly disabled** with
   *"12 details need your input."* This is the core demonstration.
3. Resolve one item live — supply its owner and deadline → counter drops 12 → 10 →
   button remains disabled → resolve the rest → button enables.
4. Generate draft → show the follow-up message → edit one line → Approve → export Markdown.
5. Open the approved view → show F15: the fields the human overrode, next to what the
   agent originally produced.

### 7.5 Build sequence

| Phase | Deliverable |
|---|---|
| 1 | Project skeleton, schemas, SQLite layer, 5 fixtures written |
| 2 | `run_extract` + Structured Outputs; raw JSON rendered in Streamlit |
| 3 | `run_review` + deterministic gap backstop + `is_blocked` gate |
| 4 | Review UI: inline editing, gap resolution, gated Draft button |
| 5 | `run_draft`, approval, Markdown export, meeting history, F15 diff view |
| 6 | Evaluation run over all 5 fixtures; `docs/evaluation-results.md`; demo rehearsal |

---

## 8. Assignment Traceability

| Module 1 requirement | Section |
|---|---|
| Define the problem — what, who, why worth solving, why AI | §1.1 – §1.4 |
| Identify the agent — receives / decides / does / produces | §2.1 – §2.2 |
| Autonomy vs. human intervention | §2.3 |
| Map the complete system — frontend, backend, AI layer, data, infra, external | §3.1 – §3.4 |
| PRD with detailed product specification | §4 |
| PRD with detailed technical specification | §5 |
| Initial prototype validating the core workflow | §7 |

---

## 9. Open Questions

| # | Question | Owner | Needed by |
|---|---|---|---|
| Q1 | Should `MISSING_DEADLINE` be blocking, or only a warning? Some valid action items genuinely have no date. | Product | Phase 3 |
| Q2 | Should the manager be able to override the gate ("draft anyway") with the omission noted in the message? | Product | Phase 4 |
| ~~Q3~~ | ~~Is a Streamlit Cloud deployment required for submission?~~ **RESOLVED 2026-09-15: a local demo is sufficient.** Streamlit Cloud deployment is out of scope for v1. | Product | — |
| ~~Q4~~ | ~~Should a meeting reopened from the sidebar come back read-only once it has been approved, as F14 specifies ("selecting one reloads its approved state read-only")?~~ **RESOLVED 2026-09-15: not implemented — explicit v1 descope.** `app.py`'s sidebar routes *every* meeting to `Stage.REVIEW` regardless of its `status`, so an approved meeting reopens fully editable: the task, owner and deadline inputs, the Delete buttons and the gap controls are all live, and a further edit is silently written over the approved record. `status = 'approved'` is stored by `db.save_approval` and shown in the sidebar label, but it gates nothing. F14's list-and-reload half works; its read-only half does not exist. Accepted as-is for v1 rather than fixed after the final review; the fix is a status check in the sidebar routing plus a read-only branch in `ui/review_view.render`. | Product | — |

Current working answers: Q1 — blocking, because an undated task is the most common way a
commitment disappears, and resolving it costs one keystroke. Q2 — no override in v1; an
escape hatch would weaken exactly the behaviour the prototype exists to demonstrate.
Q3 — resolved: local demo only; §3.4's hosted-deployment note is optional and untested.
Q4 — resolved as a descope: approved meetings reopen editable, not read-only; F14 is
therefore only partly delivered in v1, and this document records that rather than
claiming it.

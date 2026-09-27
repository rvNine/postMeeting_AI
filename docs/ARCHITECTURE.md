# Architecture — Meeting Follow-up Agent

| | |
|---|---|
| **Status** | As-built, `feat/agentic-loop` — through Task 9 of `docs/superpowers/plans/2026-09-16-agentic-loop.md` (the loop, triage, context and memory) |
| **Date** | 2026-09-16 |
| **Scope** | How the system is actually structured and why |
| **Companion docs** | `docs/PRD-meeting-followup-agent.md` (what and why — requirements), `README.md` (how to run it), `docs/evaluation-results.md` (how well it works) |

This document describes the system **as built**. Where it differs from the PRD's
§3 system map, this document is correct — the PRD records the plan, and three
defects found during the build changed the design. Those changes are recorded in
§9.

---

## Current state (Module 3 addendum, 2026-09-25)

`feat/module3-technical-meeting-intelligence` added a second family of extracted
records on top of the agent described below. Sections 1-12 describe the
Meeting Follow-up Agent exactly as they did before that branch and are not
rewritten; this note states only what changed.

- `MeetingExtraction` (`agent/schemas.py`) now carries `risks`, `dependencies`,
  and `learnings` lists alongside the original `decisions` and `action_items`.
  Every record in all five lists still requires a `source_quote`.
- Evidence is checked deterministically, the same "model proposes, code
  disposes" pattern as the structural backstop in §4:
  `agent/evidence.py::quote_supports` verifies every source quote actually
  appears in the notes (whitespace/case-normalised, word-boundary-anchored),
  and `agent/gaps.py::detect_evidence_gaps` raises an `unsupported_evidence`
  gap for any record whose quote fails that check — BLOCKING for a decision
  or action item, WARNING for a risk, dependency, or learning. This runs
  unconditionally inside `agent/pipeline.py::run_review`, before the model
  review call, the same way the structural checks already did.
- Technical records persist in three new tables — `risks`, `dependencies`,
  `learnings` (`storage/schema.sql`) — each with the same frozen `ai_*`
  column pattern as `action_items` (§6) and an `origin` column so a
  human-added record never claims AI evidence it doesn't have.
- `ui/review_view.py` adds Risks / Dependencies / Learnings
  sections with edit, delete, and add controls, mirroring Decisions and
  Action items. Each row shows its own gaps, with a "🔎 Quote not found in
  notes" badge for `unsupported_evidence` and a Mark-resolved control for
  any gap that isn't fixable by a field edit (`ui/gap_display.py`'s
  `DATA_FIXABLE_TYPES` covers only `MISSING_OWNER`/`MISSING_DEADLINE`, so
  every technical-record gap needs one).
- `PROMPT_VERSION` (`agent/prompts.py`) is now `"v3"`.
- The draft (`agent/pipeline.py::run_draft`) is unchanged: it still consumes
  only `decisions` and `action_items`. Risks, dependencies, and learnings are
  reviewed, edited, and stored, but never reach the drafted follow-up
  message.

See `docs/ARCHITECTURE-technical-meeting-intelligence.md` for the full
architecture of this addition and `docs/PRD-technical-meeting-intelligence.md`
for the requirements.

---

## 1. The one-sentence architecture

A manager pastes meeting notes; the agent extracts decisions and action items,
re-reads its own extraction to flag what it could not determine, and **refuses to
draft the follow-up message until a human confirms every missing owner and
deadline**.

Everything below exists to make that refusal reliable. When reading this
document, the question to hold is: *can the model, a UI bug, or a careless caller
cause a follow-up message to name an owner nobody confirmed?* Every structural
decision here answers some version of that.

---

## 2. System at a glance

```
                     ┌──────────────────────────────────────────┐
   meeting notes ───►│  ui/          Streamlit views            │
                     │               wiring only, no decisions  │
                     └───────┬──────────────────────┬───────────┘
                             │                      │
                             ▼                      ▼
              ┌──────────────────────┐   ┌─────────────────────────┐
              │  agent/              │   │  storage/               │
              │  pipeline, gate,     │   │  SQLite persistence     │
              │  schemas, prompts    │   │  6 tables               │
              └──────────┬───────────┘   └─────────────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  OpenAI API          │
              │  Structured Outputs  │
              │  gpt-4o-mini         │
              └──────────────────────┘
```

Single process. Four packages, ~2,100 lines of source, 265 tests. (Grown from
~1,700 lines / 166 tests since the loop, triage, context and memory were
added — see §4, §6, §12.)

| Package | Lines | Responsibility |
|---|---|---|
| `agent/` | 894 | The loop, the pipeline (extract/review/triage/draft), the gate, the schemas, the prompts. Knows nothing about SQL or Streamlit. |
| `ui/` | 704 | Streamlit views, `context_builder.py`, plus three pure, testable helper modules. |
| `storage/` | 336 | SQLite, plus the two read-only memory queries. Knows nothing about the agent or the UI. |
| `eval/` | 170 | Scores the real agent against hand-written gold answers, including the loop's own pass count and gain. |
| `fixtures/` | 23 | Five sample meetings and their gold answers. |

---

## 3. Layers and import discipline

Four layers, with a strict rule: **imports point downward only.**

```
  ui/  ──────► agent/  ──────► (OpenAI)
   │
   └─────────► storage/
```

| Layer | May not |
|---|---|
| `ui/` | import `openai` or `sqlite3`; contain `conn.execute(` |
| `agent/` | import `storage/` or `streamlit` |
| `storage/` | import `openai` or `streamlit` |
| everything but `agent/llm_client.py` | import `openai` |

**These are not conventions — they are tests.** `tests/test_layer_discipline.py`
parses the source and fails the build on a violation. It is an executable
architecture document, and it earns its place: during the build the UI was caught
writing raw SQL (`UPDATE decisions SET deleted = 1 ...`), which the original
`import sqlite3` check did not catch. The test now greps for `conn.execute(` too.

### The pure-helper rule

Streamlit widgets cannot be unit-tested without a browser driver. So:

> **Every decision lives in a pure, unit-tested helper. View files are wiring
> only.**

| Pure (no `streamlit` import, fully tested) | Views (wiring, untested) |
|---|---|
| `ui/state.py` — input validation, stage enum, deadline parsing | `ui/input_view.py` |
| `ui/gap_display.py` — badges, gate predicates, sorting | `ui/review_view.py` |
| `ui/markdown_export.py` — the exported document | `ui/export_view.py` |

If a view file contains an interesting `if` that decides something, it is in the
wrong place. `test_layer_discipline.py` asserts the three helper modules never
import `streamlit`.

**This rule has a known hole**, recorded honestly: no test imports the three view
modules, so a runtime error inside one ships green. That is exactly how a
`NameError` reached the running app once. The mitigation is
`test_no_undefined_names_in_ui_or_agent`, an AST check that catches unbound names
without executing the module.

---

## 4. The agent loop

The pipeline used to be three fixed steps. It is now an
**observe → decide → act → evaluate → exit loop** (`agent/loop.py::run_agent_loop`)
with a bounded budget: extract, review itself, triage each gap into "the notes
already answer this" versus "only a person can settle this", and — only for
the former, and only if budget remains — spend one corrective pass before
handing off to the human gate. Step 2's self-critique (review) is unchanged
from the original three-step design; the loop adds triage and the
decide-whether-to-act-again step on top of it.

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
                    ╔════════════════▼═════════════════════════╗
                    ║  HUMAN GATE                              ║  autonomy: NONE
                    ║  confirm owners, set deadlines,          ║
                    ║  resolve contradictions, approve         ║  unchanged — §5
                    ╚════════════════┬═════════════════════════╝
                                     │  draft blocked until clear
                    ┌────────────────▼─────────────────────────┐
                    │ DRAFT                  temp 0.4         │  autonomy: FULL
                    │    approved items → follow-up message  │  output: SUGGESTION
                    └────────────────────────────────────────┘
```

Temperatures are deliberate: extraction is transcription, where creativity is a
defect; review and triage are judgements that must be reproducible; drafting is
prose.

All structured calls use **OpenAI Structured Outputs** (`chat.completions.parse`)
with a Pydantic schema, so responses are schema-valid by construction rather than
parsed and hoped over.

### Review's backstop (unchanged)

`detect_structural_gaps()` runs **unconditionally**, before the model call, and
its results are merged in regardless of what the model returns. If the reviewer
rubber-stamps its own work and returns zero gaps, every null owner and null
deadline is still flagged and the gate stays shut.

If the review call fails outright, `run_review` catches `LLMError` and returns
the structural gaps with `overall_confidence = 0.0` and a note explaining the
fallback. **A model failure degrades to deterministic detection, never to "no
gaps"** — the latter would silently open the gate.

`run_agent_loop` re-runs this same backstop a second time after
`merge_extractions`, because merging pass 1 and pass 2 can add or change action
items the review call never saw. `merge_gaps` deduplicates on
`(target_id, type)`, so for a gap the review already had this second merge is a
no-op; it only matters when the merge changed something review didn't.

### The triage step and its deterministic verification

Triage (`agent.pipeline.run_triage`) is the agent's judgement about whether
another pass would help, so it gets the same treatment every other model
judgement in this codebase gets: **the model proposes, deterministic code
disposes.**

- The model returns a `GapTriage` per gap: a verdict (`SELF_RESOLVABLE` or
  `NEEDS_HUMAN`) plus, for a self-resolvable claim, a `supporting_quote`.
- `quote_supports(quote, notes)` then checks — in code, not by asking the
  model again — that the quote actually appears in the notes (whitespace- and
  case-normalised, but otherwise exact, anchored at word boundaries so a bare
  "Dan" is not "supported" by a notes-only "Danielle").
- Any `SELF_RESOLVABLE` verdict whose quote fails that check is force-downgraded
  to `NEEDS_HUMAN` via `model_copy(update=...)` — deliberately not
  re-validated, because the downgrade is code's decision, not the model's, and
  re-running Pydantic validation on a decision already made would be wasted
  work.
- If the triage call itself fails, every gap is treated as `NEEDS_HUMAN` —
  the same "degrade to the deterministic floor, never to nothing" pattern as
  review's fallback.

**Documented residual, not silently accepted:** `quote_supports` checks
*presence*, not *relevance*. A supporting quote that is a common word or short
phrase genuinely appearing elsewhere in the notes — "the", "the notes say" —
passes the check while proving nothing about the specific gap it was offered
for. No length or word-count floor closes this principled-ly; a real word
("Dan") and a meaningless one ("the") are both single words. The cost of this
residual is bounded, not open-ended: a false self-resolvable verdict spends
one wasted extraction pass, not a fabricated field, because the re-extraction
that follows is itself bound by the existing verbatim `source_quote`
requirement in `EXTRACT_SYSTEM`. This is a known trade-off, recorded here
rather than fixed, because no principled fix exists at this layer.

### The pre-filter that runs before the model

Triage has a deterministic half that executes *before* any model call:

```python
_NAME = re.compile(r"\b[A-Z][a-z]{1,}\b")

def owner_gap_is_hopeless(gap, notes) -> bool:
    return gap.type is GapType.MISSING_OWNER and not _NAME.search(notes)
```

A `MISSING_OWNER` gap whose notes contain no capitalised word at all cannot be
answered by re-reading them — there is no candidate name to find. `run_triage`
partitions on this: hopeless gaps get a synthesised `NEEDS_HUMAN` verdict, only
the remainder reach the model, and if nothing remains **no model call is made at
all**.

This exists because of the bypass in §9.4. Without it, the second pass can
"resolve" a blank owner by lifting a name out of the BACKGROUND block — a name
that appears nowhere in today's notes and that no human confirmed.

**Its reach is narrow, deliberately.** `_NAME` matches any capitalised word, so
a sentence-initial "Someone" or a product name like "Ops" counts as a candidate
and the gap goes to the model. In practice the pre-filter only fires on
entirely-lowercase shorthand — which is exactly what hurried meeting notes look
like, and is the shape of sample fixture 2. It fails *open* (asks the model,
costs one call) rather than closed. A real name detector is a different project;
this is a cheap guard that is honest about being cheap.

### Budget

`config.MAX_PASSES = 2` — one corrective extraction pass at most, then
escalate to the human. A meeting costs at most **five** model calls (extract,
review, triage, re-extract, review), against two before the loop existed. The
cost below that ceiling depends on what review finds, per the loop's own
guard (`budget > 1 and review_result.gaps`): **two** calls (extract, review)
when review returns no gaps at all, so there is nothing to triage; **three**
(extract, review, triage) when review finds at least one gap but triage
judges all of them `NEEDS_HUMAN`; **five** only when triage finds something
self-resolvable and the budget allows a corrective pass. **Exhausting the
budget is a normal outcome, not an error** — it produces the same gated
review screen with a note that the agent tried and could not resolve the
remainder (`LoopOutcome.notes_for_manager`).

---

## 5. The gate

**Deliberately unchanged by the loop.** Adding the loop was a non-negotiable
invariant of that design (see the spec's §3): the loop must not add a path to
a draft, and it does not — `run_agent_loop` calls `run_review` and returns
whatever gaps survive its **final** pass (pass 1 if triage found nothing
self-resolvable or the budget was 1; pass 2 otherwise), and every check below
runs against that final gap list exactly as it always has. Nothing in this
section changed; it is repeated here, not summarised away, because "the gate
is unchanged" is a claim worth being able to verify against.

The central invariant. Enforced in **three independent places**:

| # | Where | Checks |
|---|---|---|
| 1 | `ui/gap_display.draft_blocked()` | disables the Draft button |
| 2 | `agent/pipeline.run_draft()` | re-checks `open_blocking(gaps, resolved_ids)` |
| 3 | `agent/pipeline.run_draft()` | independently verifies every item's owner and deadline are non-blank |

Layer 2 exists because a UI bug must not be able to produce an ungated draft.
Layer 3 exists because **layer 2 is not enough**: `resolved_ids` is bookkeeping,
and a caller can mark a gap resolved while the underlying field is still empty.
`run_draft` therefore trusts nothing about how the caller tracked gaps and reads
the data itself.

Layers 1 and 3 share one predicate rather than approximating each other —
`items_missing_fields` is textually the same condition as `run_draft`'s check, and
`draft_blocked` calls `agent.gaps.is_blocked` itself rather than reimplementing
it. A visible gate that disagrees with the enforced gate means an enabled button
that throws on click.

### What counts as blocking

```python
BLOCKING_TYPES = {MISSING_OWNER, MISSING_DEADLINE, CONFLICTING_DECISION}

# a gap blocks when:
severity is BLOCKING  OR  type in BLOCKING_TYPES
```

The `OR` is deliberate. The model supplies a gap's `type` and `severity`
independently, with nothing tying them together, so it can emit a
`CONFLICTING_DECISION` tagged `WARNING`. **The taxonomy wins over a model-supplied
downgrade.**

### Resolving a gap

Two routes, because not every gap is fixable by editing data:

| Gap type | Resolved by |
|---|---|
| `MISSING_OWNER`, `MISSING_DEADLINE` | filling the field (`gap_is_satisfied`) |
| `CONFLICTING_DECISION`, `AMBIGUOUS_TASK`, `UNRESOLVED_QUESTION` | an explicit **Mark resolved** button |

Resolution tracks the data **in both directions**: filling an owner resolves its
gap, and clearing that owner re-opens it. An earlier version only ever resolved,
so clearing a field left a stale badge and a live Draft button.

A gap whose `target_id` matches no rendered row appears in a dedicated
**unattached gaps** block with its own Mark-resolved control. Without it, a
mislabelled `target_id` from the model would count toward the banner with no
control anywhere on screen — a permanent lock.

---

## 6. Data model

Six tables in SQLite. `storage/schema.sql` is the source of truth.

```
meetings ──┬── extractions     summary, participants, provenance
           ├── action_items    task, owner, deadline + FROZEN ai_* columns
           ├── decisions       decision, rationale, source_quote
           ├── gaps            type, severity, target_id, resolved
           └── approvals       draft_text, final_text
```

### The frozen `ai_*` columns

Every action item stores the agent's original `ai_task`, `ai_owner`,
`ai_deadline`, written once at extraction and **never updated**.
`human_edits()` diffs live values against them.

This is the project's evidence mechanism: it turns "a human reviewed it" from a
claim into a record, showing exactly which owners and deadlines the agent could
not determine and a person supplied. `update_action_item` can only write
`task`/`owner`/`deadline` — the column list is hardcoded, so no code path can
touch an `ai_*` column.

### The id scheme

Ids for action items, decisions and gaps are **invented by the LLM**, which has no
uniqueness contract. They are namespaced at the storage boundary — the only place
raw model ids cross into the database:

```
{meeting_id}:item:{model_id}
{meeting_id}:decision:{model_id}
{meeting_id}:gap:{model_id}
```

Both halves of that prefix were learned the hard way (§9). A gap's `target_id` is
resolved to the right entity kind by gap type — `conflicting_decision` → decision,
`missing_owner` → item — falling back to whichever kind actually holds that id,
and left deliberately unmatched if neither does, where the unattached-gaps block
catches it.

Human-added items use a UUID instead, with no prefix. They are globally unique and
nothing targets them, so the mixed scheme is safe.

### Atomicity

`save_extraction` writes the extraction, every action item, every decision and
every gap inside a single `with conn:` block. The connection is long-lived and
cached by Streamlit via `@st.cache_resource`, so a mid-loop failure without
rollback would leave an open transaction whose partial rows the *next* unrelated
commit would flush. An extraction is all-or-nothing.

### Reading memory back: the two queries in `storage/memory.py`

No new tables. Memory is two read-only queries over data the six tables above
already had, plus a translation module (`ui/context_builder.py`) that turns
their plain-dict rows into the frozen dataclasses `agent/schemas.py` defines —
the seam that lets `agent/` consume memory without ever importing `storage/`.

```python
def owner_hints(conn, *, exclude_meeting_id, limit=10) -> list[dict]:
    # action_items WHERE origin='agent' AND ai_owner IS NULL AND owner IS NOT NULL
    # — literally "the agent left this blank and a person filled it in": the
    # frozen ai_* correction log, read back for the first time.

def prior_commitments(conn, *, exclude_meeting_id, limit=20) -> list[dict]:
    # action_items JOIN meetings, SELECTing the FROZEN ai_task/ai_owner/
    # ai_deadline (never the live task/owner/deadline a human can edit),
    # WHERE ai_owner AND ai_deadline are BOTH non-blank, excluding the
    # current meeting, most recent first.
```

The SELECT and the WHERE read the same frozen columns deliberately: gating on
`ai_owner`/`ai_deadline` while emitting the live `owner`/`deadline` would let a
human's own correction or later-supplied deadline round-trip into the prompt
even though the row "qualified" on the agent's original values. Emitting the
frozen columns closes that regardless of what a human typed afterward.

**No completion tracking exists.** `prior_commitments` means "previously
committed, and never marked done *in this system*" — not "verified still
open." There is no status field on an action item beyond `deleted`, no
"done" checkbox, and no code path that would let a later meeting mark an
earlier commitment resolved. A commitment from three meetings ago that was
quietly finished in the real world still surfaces here indistinguishably from
one still outstanding. This is a stated v1 descope (spec §2, "Out"), not an
oversight, and the prompt text and the review-screen copy both say so rather
than implying a freshness guarantee the query cannot back up.

---

## 7. The trust boundary

The most useful way to read this codebase is as a list of things it refuses to
believe from the model.

| The model may… | The system… |
|---|---|
| guess an owner the notes never stated | forbids it in the prompt twice, and flags any null as a blocking gap |
| return the **string** `"null"`, `"N/A"`, `"TBD"` instead of JSON null | normalises placeholder strings to `None` at the schema boundary |
| return zero gaps for an obviously gappy extraction | runs a deterministic backstop unconditionally |
| tag a blocking gap type as a mere warning | blocks on type *or* severity |
| reuse the same id for a decision and an action item | namespaces ids by entity kind |
| point a gap at an id that does not exist | surfaces it in the unattached-gaps block |
| fail entirely | degrades to structural-only detection, never to "no gaps" |
| claim a gap is `SELF_RESOLVABLE` | verifies the claim's supporting quote actually appears in the notes (`quote_supports`); an unverifiable claim is force-downgraded to `NEEDS_HUMAN` before it can spend a pass |
| — memory suggests an owner — | splits memory in two and lets only one half near a model. **`owner_hints` — an owner a HUMAN supplied where the agent found none — never reaches a model at all:** it is read by `ui/` and rendered only in the review screen, `build_extract_user` never reads `context.owner_hints`, `tests/test_layer_discipline.py` forbids any module under `agent/` from even accessing the attribute, and a test drives the absence from the stub client's recorded calls rather than trusting the docstring. **`prior_commitments` does reach the model**, as a delimited BACKGROUND block framed as context for shorthand and explicitly not as facts about today's meeting — but its WHERE gates on the frozen `ai_owner`/`ai_deadline` being both non-blank AND its SELECT emits those same frozen `ai_task`/`ai_owner`/`ai_deadline` columns, never the live `task`/`owner`/`deadline` a human can edit later. Gating on the frozen columns while selecting the live ones was itself a leak: the row qualified on what the agent read, but what reached the prompt was whatever a human typed over it afterward — a corrected owner, a supplied deadline, an edited task. Selecting the frozen columns closes that regardless of the WHERE clause. |

`PLACEHOLDER_VALUES` normalisation lives in `agent/schemas.py`, the lowest layer,
so every consumer inherits it from one change. The three gate predicates then call
that same function again rather than re-implementing "is this blank" — defence in
depth, because attribute assignment after construction bypasses Pydantic
validators.

---

## 8. Failure handling

| Failure | Behaviour |
|---|---|
| No API key | Startup banner; Analyze disabled; no call, no spend |
| Rate limit / timeout / connection / 5xx | Retried with exponential backoff, 3 attempts |
| Auth error, bad schema, any non-transient error | Fails immediately — no retry, no backoff |
| Model call fails | Database untouched; notes preserved; "Try Analyze again" |
| Storage write fails | Orphan meeting row deleted, so no empty meeting appears draftable |
| Cleanup *also* fails | Both errors surfaced; notes preserved; no traceback |
| Notes over 10,000 words | Truncated **copy** sent to the model; the original is stored |
| Draft blocked or fails | Approve and Download do not render; the failure is latched so it is not re-billed on every rerun |

**Principle:** a failure must never silently produce a partial result.

The retry classifier is deliberately narrow — only `RateLimitError`,
`APITimeoutError`, `APIConnectionError`, `InternalServerError`. Everything else
fails fast, and the auth path raises `from None` so an OpenAI error message
containing a partially-redacted key cannot reach a Streamlit traceback.

---

## 9. Four defects that shaped this design

Each was found by running the system, not by reading it. Each is now a test.

**1. The agent returned the string `"null"` as an owner.** Found by the evaluation
harness. `"null"` is a non-empty string, so no gap was raised, `is_blocked`
returned False, and `run_draft` passed both its checks. A follow-up would have
gone out naming an owner nobody agreed to. → `normalize_optional_text` at the
schema boundary, plus all four blank-checks converged on it.

**2. Model ids collided across entity types.** The model numbered decisions `1,2`
and action items `1,2,3,4`. Namespacing by meeting alone left `<meeting>:2`
matching both, so one gap rendered a Mark-resolved button under a decision *and*
an action item, and Streamlit killed the page on the duplicate widget key. →
entity-kind scoping, type-aware target resolution, distinct widget key prefixes.

**3. A gap with no resolution path locked the gate forever.** `CONFLICTING_DECISION`
is blocking, but only missing owner/deadline could be resolved. The sample meeting
built to exercise contradictions could never be drafted. → the Mark-resolved
control, plus a property test that every member of `BLOCKING_TYPES` has a reachable
path into `resolved_ids`.

**4. Memory fed a human's own answer back to the model, and the gate opened on it.**
Found by the final review of the agent-loop branch and reproduced end to end.
Memory recorded that a human had assigned a task to "Dan". That reached the
extraction prompt as background. A later meeting naming *no person at all* had
its blank owner filled with "Dan" by the corrective pass; the backstop saw a
non-blank field, raised no gap, and the gate opened. A follow-up would have named
an owner nobody confirmed — the exact fabrication the product exists to prevent,
arriving through the door memory opened.

Two independent omissions caused it. The design spec contained a rule — *a
`MISSING_OWNER` gap whose item has no candidate name anywhere in the notes is
`NEEDS_HUMAN` by definition, without consulting the model at all* — that never
reached the implementation plan. And `prior_commitments` had no filter on who
supplied the value it emitted. → the pre-filter in §4, plus `prior_commitments`
emitting the frozen `ai_*` columns and gating on both of them (§6), so nothing a
human typed can return to a prompt.

The pattern is worth naming: **all four lived at a boundary no single component
owned** — the model's output meeting the schema's assumptions, ids crossing into
storage, the gap taxonomy crossing into the UI. Component-level tests were green
throughout.

---

## 10. Testing strategy

265 tests, no network, no API key required. Every test runs against
`StubLLMClient` in `tests/conftest.py`, which returns queued responses and records
what it was asked.

| File | Tests | Covers |
|---|---|---|
| `test_pipeline.py` | 55 | extract/review/triage/draft, the backstop, fallback, the gate, `quote_supports` |
| `test_gap_display.py` | 45 | gate predicates, badges, resolution logic |
| `test_schemas.py` | 24 | validation, placeholder normalisation, `MeetingContext`/`OwnerHint`/`PriorCommitment` |
| `test_db.py` | 19 | persistence, id scoping, atomicity, the `ai_*` freeze |
| `test_ui_state.py` | 18 | input validation, deadline parsing, per-meeting state cleanup |
| `test_gaps.py` | 16 | gap detection, merge, blocking rules |
| `test_loop.py` | 22 | the loop's control flow, the merge, the budget, invariants 3 and 5 |
| `test_eval_scoring.py` | 12 | the evaluation harness's own arithmetic, including `passes` and `pass2_gain` |
| `test_layer_discipline.py` | 11 | **the architecture itself**, including the owner-hints-never-reach-a-model lock |
| `test_memory.py` | 14 | `owner_hints`, `prior_commitments` — the two read queries |
| `test_markdown_export.py` | 9 | the exported document |
| `test_llm_client.py` | 7 | retry classification, key secrecy |
| `test_fixtures.py` | 5 | fixtures pair with gold answers |
| `test_config.py` | 4 | configuration |
| `test_context_builder.py` | 4 | storage rows → `MeetingContext`, empty on failure |

`eval/run_eval.py` is separate and makes **real, billable** API calls. It is never
run by the test suite.

---

## 11. Known limitations

Recorded rather than hidden. See `docs/evaluation-results.md` for measured
behaviour.

- **The three Streamlit view modules have no import-level tests.** The AST check
  catches unbound names; it cannot catch a runtime error inside a widget callback.
- **Decision extraction is never scored.** `expected_decisions` exists in all five
  gold files and the harness does not read it.
- **PRD F14 is descoped** — an approved meeting reopens editable rather than
  read-only.
- **Two items sharing one model id inside a single extraction** still fails the
  whole analysis, cleanly, after two paid calls.
- **`ui/review_view.py` (224 lines) and `storage/db.py` (265 lines)** are the
  largest modules and the first candidates for a split.
- **Single-user, single-process.** No auth, no concurrency control; the SQLite
  connection is shared across browser sessions while Streamlit session state is
  not.
- **The loop roughly doubles cost, and the one real evaluation run measured
  it rather than assuming the worst case.** The theoretical ceiling is 5 model
  calls per meeting (`MAX_PASSES = 2`) against 2 before the loop existed. The
  v2 eval run (`docs/evaluation-results.md`) found the corrective second pass
  never fired on any of the 5 fixtures — triage judged every remaining gap
  `NEEDS_HUMAN` in every case — so the measured cost in that run was 3 calls
  per fixture with any gap (extract, review, triage) and 2 for a fixture with
  none, not 5. This is one run on five small fixtures, not a production
  average.
- **Triage's per-gap precision is discarded when feedback is built.** The loop
  reduces a `TriageOutcome` to a bare list of quotes, dropping each gap's `type`
  and `target_id`. A `MISSING_OWNER` gap on an item that pass 1 already extracted
  is therefore presented to the extractor under an *item*-framed heading ("you
  overlooked these"), when the truth is "this item's owner is stated here". The
  likely result is a near-duplicate item rather than a corrected one. The gate
  still holds — a duplicate is safe, if annoying — and this path never executed in
  the measured run, so the behaviour is entirely unobserved.
- **`MAX_PASSES` is not really a budget counter.** `run_agent_loop` reads it once,
  as `if budget > 1`; the two-pass ceiling comes from the function having no loop
  construct, not from the constant. Setting it to 3 would change nothing.
- **Memory was never exercised by the evaluation.** The measured run called the
  loop with no context, so the risks memory introduces — a remembered owner
  leaking into extraction, prior commitments confusing the extractor — have no
  measurement behind them. The fixes in §9.4 are verified by unit tests only.
- **Memory has no completion tracking (see §6).** `prior_commitments` reflects
  what was assigned and dated, not what is still outstanding. A finished
  commitment from an earlier meeting will keep surfacing as background context
  indefinitely; nothing in this design detects or suppresses that.

---

## 12. Decision log

| Decision | Why | Cost if wrong |
|---|---|---|
| Streamlit over a split frontend/backend | The value is the agent, not the CSS; layer discipline keeps the split honest anyway | A real API is a mechanical extraction |
| Structured Outputs over prompt-and-parse | Schema-valid by construction | Locks to OpenAI; `LLMClient` is a Protocol, so a second provider is one class |
| Numeric bounds via validators, not `Field(ge=…)` | Strict JSON-schema mode rejects `minimum`/`maximum` | None — a test guards against reintroduction |
| `deadline` as ISO string, not `date` | Structured Outputs has no date type | Validation happens in a validator instead |
| Gate enforced three times | The UI is the least trustworthy layer | Slight duplication, deliberately shared |
| Placeholder normalisation at the schema boundary | Lowest layer; every consumer inherits it | `"Nil"` is a real name that normalises to None — fails toward asking a human |
| Freeze `ai_*` columns | Turns human review into evidence | Three extra columns |
| Ids namespaced by meeting **and** kind | The model controls ids and has no uniqueness contract | Longer ids |
| The loop lives in `agent/loop.py`; context is passed by parameter, never a connection | `agent/` still must not import `storage/` — memory is data the caller assembles, not a capability the agent reaches for itself | `ui/` must remember to call `build_context()`; forgetting it just yields the empty-context, pre-loop behaviour rather than an error |
| Owner hints are UI-only, enforced by scanning the stub client's recorded calls, not by convention | A hint that reached a model would be one prompt away from becoming exactly the fabricated owner R1/R8 exist to prevent | None — the alternative (trusting the docstring alone) was already shown, during the build, to be insufficient without a test |
| `prior_commitments` emits the frozen `ai_*` columns, not the live ones | Gating the row on what the agent read while emitting what a human later typed was a half-closed door: it stopped a *blank* owner round-tripping but not a *corrected* one, and not a human-supplied deadline at all | Background is narrower — only fully agent-read commitments qualify — so memory shows less. It never shows something a human authored |
| A `MISSING_OWNER` gap with no capitalised word in the notes skips the model entirely | The spec called for it, and it is the cheapest point at which an unanswerable gap can be routed to a human — before a call is spent and before a second pass can invent an answer | The heuristic is crude enough that it rarely fires on real prose; it protects a narrower class than its name suggests |
| `MAX_PASSES = 2` | One corrective pass at most; bounds cost to at most 5 calls/meeting and keeps "the agent tried and gave up" a rare, explainable outcome rather than an open-ended retry loop | A genuinely two-step-away fix (self-resolvable only after two corrections) is never attempted; it escalates to a human on pass 2 instead |

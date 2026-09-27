# Post Meeting AI

Turns pasted meeting notes into a summary, decisions, action items, risks,
dependencies, and technical learnings — and refuses to draft the follow-up
message until a human has confirmed every owner and deadline the agent could not
determine from the notes.

It is an agent, not a pipeline: it re-reads its own extraction, decides per gap
whether another look at the notes would help, and spends at most one corrective
pass before escalating the rest to a person. It also remembers earlier meetings —
carefully, and in two halves that are not interchangeable (see below).

Local coursework prototype, extended through Module 3. This README is
orientation; `docs/ARCHITECTURE.md` and
`docs/ARCHITECTURE-technical-meeting-intelligence.md` contain the detail. See
also `docs/PRD-meeting-followup-agent.md` and
`docs/PRD-technical-meeting-intelligence.md`. `docs/evaluation-results.md`
records historical paid v1/v2 runs; the current v4 prompt has not been measured
live (see "What the agent does not trust" below for a historical fabrication and
its remediation).

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then add your OpenAI key
streamlit run app.py
```

Opens at http://localhost:8501.

### Adding a meeting

On the input screen, either paste notes into the editor or upload a UTF-8
`.txt` or `.md` file. The filename becomes an editable meeting title; the
uploaded text remains editable before you click **Analyze**. Files are limited
to 2 MB and are stored with the meeting after analysis. The upload uses the
same review, evidence, and human-gate flow as pasted notes.

The `python` commands below assume the virtualenv is **activated**. Outside it,
use `python3` — many systems (including the one this was built on) have no bare
`python` on PATH at all.

## How the agent works

Four pipeline steps (`agent/pipeline.py`), sequenced by a bounded loop
(`agent/loop.py::run_agent_loop`), with a human gate before the last one:

1. **Extract** (`run_extract`, temperature 0.1) — notes become a validated
   `MeetingExtraction`. The agent is forbidden from inventing an owner or deadline;
   when the notes do not state one it must emit `null`.
2. **Review** (`run_review`, temperature 0.0) — the agent re-reads its own extraction
   against the notes and flags what is missing or ambiguous. Deterministic
   structural and evidence backstops (`agent/gaps.py::detect_structural_gaps` and
   `detect_evidence_gaps`) run unconditionally after the model's review — not only
   when the model call fails — and mechanically re-check missing owners, deadlines,
   and verbatim evidence. If the review model call itself fails, the pipeline falls
   back to those deterministic checks rather than surfacing no gaps at all.
3. **Triage** (`run_triage`, temperature 0.0) — for each gap, decide whether the
   notes already answer it (`SELF_RESOLVABLE`) or only a person can
   (`NEEDS_HUMAN`). This is what makes it a loop rather than a fixed pipeline. It
   is the agent's own judgement, so deterministic code brackets the model on both
   sides — see "What the agent does not trust" below. If anything is judged
   self-resolvable, the loop runs one corrective **re-extraction** with those
   quotes as feedback, merges it into the first pass (never dropping an item the
   first pass found), and re-reviews. `config.MAX_PASSES = 2` is the budget: one
   corrective pass at most, so a meeting costs at most five model calls. Running
   out is a normal outcome, not an error — the manager sees a note saying the
   agent tried and could not resolve the rest.
4. **Draft** (`run_draft`, temperature 0.4) — blocked until every blocking gap is
   resolved by a human.

### What the agent remembers

Memory is two read-only queries over rows the app already stores
(`storage/memory.py`), translated into the agent's plain dataclasses by
`ui/context_builder.py` so `agent/` never imports `storage/`. The two halves are
deliberately not interchangeable:

- **`owner_hints`** — an owner a *human* supplied where the agent found none.
  **Never sent to any model.** It is rendered beside a blank owner field in the
  review screen as a suggestion; the field stays blank and stays blocking until a
  person fills it in. `tests/test_layer_discipline.py` forbids any module under
  `agent/` from so much as reading the attribute.
- **`prior_commitments`** — commitments from earlier meetings whose task, owner,
  and deadline the *agent itself* read out of the notes. The query both gates on
  and *selects* the frozen `ai_task`/`ai_owner`/`ai_deadline` columns, never the
  live `task`/`owner`/`deadline` a human can edit afterward — so what reaches the
  model is always what the agent originally read, regardless of any later
  correction. These do reach the extraction prompt, in a delimited `BACKGROUND`
  block framed as context for understanding shorthand and explicitly not as facts
  about today's meeting. They are also shown to the manager in the review screen,
  so a suggested name can never come from a source the manager cannot see.

Selecting the frozen columns is the seam between the two: gating on `ai_owner`/
`ai_deadline` alone is not enough, because the WHERE only decides which rows
qualify — if the SELECT then emitted the live columns, a human's own correction
of an owner, a human-supplied deadline, or an edited task would still round-trip
into the prompt on a row that "qualified" by the agent's original values.
Emitting the frozen columns closes that no matter what a human typed afterward.

A gap is "blocking" if its severity is `BLOCKING` **or** its type is in
`agent.gaps.BLOCKING_TYPES` (`missing_owner`, `missing_deadline`,
`conflicting_decision`) — the `or` exists specifically so a model cannot downgrade a
blocking-type gap to a warning and open the gate itself.
`unsupported_evidence` is normalized separately by target record kind:
decisions/actions are always BLOCKING, while risks/dependencies/learnings are
always WARNING. This also covers a reviewer-only semantic finding where the quote
is verbatim but irrelevant, so no deterministic quote-mismatch gap exists to win
the merge.

**The loop changes none of this.** It runs the gate once, on the final pass,
whichever pass that turns out to be.

### What the agent does not trust

A model asked for JSON `null` sometimes returns the literal string `"null"` instead
(also seen: `"N/A"`, `"TBD"`, `"unknown"`). A real evaluation run surfaced exactly
this: `gpt-4o-mini` emitted the string `"null"` as an action item's owner even though
the correct name was stated in the notes. A plain string is truthy, so this silently
defeated every "is this blank" check built at the time — the structural gap never
fired, the gate opened, and a follow-up message would have gone out naming an owner
nobody agreed to. See `docs/evaluation-results.md` for the full writeup.

The fix is `agent.schemas.normalize_optional_text`, which maps blank/whitespace text
and a fixed set of placeholder strings to `None` at the schema boundary, and which
every layer that needs to ask "is this blank" now calls instead of re-implementing
the check — `agent/gaps.py`, `agent/pipeline.py`, `ui/gap_display.py`, and
`ui/review_view.py` (`tests/test_layer_discipline.py` enforces that they keep sharing
it). Because a placeholder string can still reach an `ActionItem` after construction
(bypassing the Pydantic validator) — e.g. a human edit round-tripped through the UI —
the gate does not stop at schema-level normalisation.

Triage gets the same treatment, because a model that can talk the loop into a second
pass can talk it into inventing an owner. Deterministic code brackets the model on
both sides:

- **Before it** — a `missing_owner` gap whose notes contain no capitalised word at
  all is `NEEDS_HUMAN` by definition and is never sent to the model
  (`agent.pipeline.owner_gap_is_hopeless`). Without this a model could "resolve" a
  missing owner by lifting a name out of the `BACKGROUND` block of prior
  commitments — a name appearing nowhere in today's notes and confirmed by nobody.
- **After it** — a `self_resolvable` verdict is believed only if the model's own
  supporting quote is verified, in code, to appear verbatim in the notes
  (`agent.pipeline.quote_supports`, whitespace- and case-insensitive but anchored at
  word boundaries, so "Dan" is not supported by notes that only say "Danielle").
  An unverifiable claim is force-downgraded before it can spend a pass.

**The gate is enforced in three
independent places:**

1. The UI disables the Draft button (`ui/gap_display.py::draft_blocked`) whenever any
   blocking gap is open or any item still has a blank owner/deadline.
2. `run_draft` re-checks the gap bookkeeping itself (`open_blocking`), so a UI bug
   that leaves the button enabled cannot produce an ungated draft.
3. `run_draft` **independently re-verifies every action item's owner and deadline are
   actually non-blank**, using `normalize_optional_text` directly on the data — not
   the gap records. A gap marked "resolved" is bookkeeping, not proof; this check
   does not trust it.

## Technical meeting packet

The Module 3 technical-intelligence slice extends the same extraction pass with
a second family of records: risks, dependencies, and technical learnings
(`agent/schemas.py::MeetingExtraction`), alongside the original decisions and
action items. Every risk, dependency, and learning still requires a verbatim
`source_quote`, exactly like a decision or action item.

Evidence is checked deterministically, not just claimed by the model:
`agent/evidence.py::quote_supports` verifies every record's source quote
actually appears in the notes, and `agent/gaps.py::detect_evidence_gaps`
raises an `unsupported_evidence` gap whenever it does not — BLOCKING for a
decision or action item, WARNING for a risk, dependency, or learning. A
paraphrased, non-verbatim quote on a decision or action item is enough to
hold the gate shut. `agent/gaps.py::normalize_evidence_severity` applies the
same target-kind policy to semantic evidence gaps returned only by the reviewer.

The review screen adds Risks, Dependencies, and Learnings sections with
editable rows, soft-delete controls, and add forms, plus a
"🔎 Quote not found in notes" badge and a Mark-resolved control for any
blocking evidence gap. Technical records persist in their own tables
(`risks`, `dependencies`, `learnings` in `storage/schema.sql`), each with the
same frozen `ai_*` audit columns as `action_items`.

A technical record added during human review is visibly labelled
**Human-created**. Because the current add forms do not collect a source quote,
the row also shows that it has no source quote or model confidence and is not
evidence-backed by the meeting notes; it is never presented as AI evidence.
Every unresolved gap whose target cannot be attached to a displayed record —
warning or blocking, including malformed targets — remains visible under
**Other flags**. Warning visibility does not change the draft gate.

The `extractions` audit row records `processing_pass` from
`LoopOutcome.passes` (1 or 2). `storage.db.init_db` adds that column with a
default of 1 when opening a legacy database, preserving existing rows without a
destructive rewrite.

The follow-up draft is unchanged by any of this: `run_draft` still consumes
only `decisions` and `action_items`. Risks, dependencies, and learnings are
reviewed, edited, and stored, but never appear in the drafted message. The
human gate described above (three independent enforcement points) applies
exactly as before.

See `docs/PRD-technical-meeting-intelligence.md` and
`docs/ARCHITECTURE-technical-meeting-intelligence.md` for the full spec and
architecture of this addition.

## Ask meetings

**🔎 Ask meetings** in the sidebar answers questions across every stored meeting,
for example "Which risks were raised for the rollout?" or "What was superseded?".
It is read-only: it cannot edit a meeting, resolve a gap, change an owner, or
create an action.

- **Answers need citations.** The model sees only the retrieved evidence, each
  item labelled with its meeting, date, and exact quote. Deterministic code then
  checks that every cited ID was supplied and that its quote appears verbatim in
  the stored notes. An answer that fails the check is shown as an error, never
  quietly trimmed. **Open meeting review** on a citation jumps to that meeting.
- **`not_found` and error are different.** `not_found` means no stored note is
  relevant enough (the model is not called at all), and it suggests filters to
  relax or add. An error means something failed: the OpenAI call, or citation
  verification. A provider failure is never reported as `not_found`.
- **Filters narrow before searching:** meeting dates, meeting, participant,
  owner, record type, risk severity, and program phase.
- **Relevance is lexical.** SQLite full-text search plus a coverage gate: at
  least 75% of a question's meaningful words (after stemming, stop words, and a
  small synonym table in `query/retrieval.py`) must appear in one passage.
  Wording far from the notes can therefore return `not_found`. `VECTOR_BACKEND`
  defaults to `none`; `deterministic` enables an offline token-overlap adapter.
  No live embedding service is wired in.

### Synthetic demo data

`fixtures/technical_standardization/` holds ten synthetic meetings from one
fictional standardization program (LatticeBridge), with directed links between
them (continues, supersedes, depends on, reviews, implements, follow-up to). No
real company, person, or IPR is represented. Seeding is explicit and never runs
on app startup:

```bash
python -m fixtures.technical_standardization.seed --db data/meetings.db
```

Re-running it replaces only the fixture meetings (`fx-…` IDs) and never touches
meetings you added. Fixture meetings open in a read-only Review, with no edit,
resolve, add, or draft controls. Meetings you analyze yourself are indexed for
Ask meetings as soon as their extraction is saved.

## Tests

```bash
python -m pytest -v          # no network; uses a stub LLM client. Includes the
                             # 32 golden Ask-meetings queries, run offline with a
                             # deterministic answer stub (not a real model)
python -m eval.run_eval      # ⚠️ MAKES REAL API CALLS AND COSTS MONEY —
                             # scores against fixtures/expected/. Do not run it
                             # casually; see docs/evaluation-results.md for the
                             # recorded run.
```

## Skills

Two repeatable jobs on this project are written up as skills in `.claude/skills/`, so an
agent working here picks up the rules without rediscovering them:

- **`run-eval-and-report`** — cost consent before a paid run, provenance checks,
  Observed/Inferred/Not-measured labels, and the standing disclosures every report in
  `docs/evaluation-results.md` has to repeat.
- **`harden-against-model-output`** — reproduce the bad value on the stub, failing test
  first, guard at the narrowest boundary reusing the shared predicates, land it at all
  three gate points, then document the defect.

`docs/skills-overview.md` explains both without repo detail. `docs/skill-examples/` holds
each skill's output and the measured with/without comparison — including the finding that
all three no-skill runs produced good work, because this README and `docs/ARCHITECTURE.md`
already encode the method.

## Layout

`agent/` — `pipeline.py` (the four steps), `loop.py` (how many times to run them and
what to do with the results), `schemas.py`, `prompts.py`, `gaps.py` (the gate) ·
`storage/` — SQLite (`db.py` freezes the agent's original
`ai_task`/`ai_owner`/`ai_deadline` at extraction time so `human_edits()` can show
exactly what a human changed; `memory.py` reads those same columns back as the two
memory queries) · `ui/` — Streamlit views plus framework-free helper modules
(`state.py`, `gap_display.py`, `context_builder.py`, `markdown_export.py`, and
`technical_display.py`) that hold the logic worth unit testing; `query_view.py` is the
Ask meetings screen · `query/` — Ask meetings: `retrieval.py` (filters, full-text
search, relevance gate), `prompts.py`, `verification.py` (citation checks), and
`service.py` (`QueryService`, the only entry point the UI uses) ·
`storage/meeting_knowledge.py` — meeting metadata, links, and the chunk index ·
`fixtures/` five
sample meetings + gold answers, local technical fixtures, and the ten-meeting
synthetic Ask-meetings dataset · `eval/` scoring
harness

Model: `gpt-4o-mini`. Prompt version: `agent/prompts.py::PROMPT_VERSION` (`v4`,
which replaces the contradictory three-bucket wording with five explicit record
categories; no paid v3 or v4 metrics have been measured).
Pass budget: `config.py::MAX_PASSES` (`2`).

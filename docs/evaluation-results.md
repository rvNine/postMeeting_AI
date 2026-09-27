# Evaluation results

**Status:** historical paid measurements only. The recorded runs below used
`PROMPT_VERSION = "v1"` (2026-09-15) and `"v2"` (2026-09-16). The current
implementation uses `PROMPT_VERSION = "v4"`; neither v3 nor v4 has been run
through the paid harness, so current-prompt metrics are **NOT MEASURED**.
Everything under "v1 run (historical)" describes the earlier three-step
pipeline (`run_extract` → `run_review`, no loop or triage) and remains as the
historical record it always was.

**Date:** 2026-09-15 (v1) / 2026-09-16 (v2)
**Model:** `gpt-4o-mini` (both)
**Prompt version measured:** `v1` / `v2`; **current `v4` NOT MEASURED** (`agent/prompts.py::PROMPT_VERSION`)
**Harness:** `eval/run_eval.py` (`python3 -m eval.run_eval`), scored by `eval.run_eval.score_fixture` and, from v2, `eval.run_eval.pass2_gain`
**Cost:** v1 — two runs total, five small fixtures each (extract + review per fixture), well under the $0.10 budget. v2 — one authorised run, five fixtures, well under $0.20 (see "v2 run" for the per-fixture call count).

---

## 2026-09-25 note (Module 3)

The Module 3 slice added risks, dependencies, learnings, and deterministic
evidence-gap checking, moving the prompt from v2 to v3. The final-review
taxonomy correction then moved it to v4: extraction now defines five explicit
record categories and treats discussion/background as non-record context. The
v2 run below predates both versions — it scored `agent.loop.run_agent_loop`
before the technical-record fields or `agent/evidence.py` existed.

No v3 or v4 evaluation run has been made. `eval/run_eval.py` still scores
action items and gap behavior, not risks, dependencies, or learnings, so even
a paid run today would not measure the new record types. A real run against
the current code requires explicit cost approval and a technical-record scoring
extension first; neither is part of this final-review fix.

---

## v2 run — the agentic loop (historical, 2026-09-16)

This run measures Task 9's deliverable: does the agent loop (`agent/loop.py`)
— extract → review → triage → conditionally re-extract and re-review, budget
`MAX_PASSES = 2` — actually improve on a single extract+review pass, now that
`PROMPT_VERSION` is `"v2"` (context block, `TRIAGE_SYSTEM`, renumbered
extraction rules) and the P0 "null"-string placeholder fix (see the historical
section below) is live in the code being measured, not just unit-tested.

**What changed since the v1 run, mechanically:**

- The pipeline call changed from `run_extract` + `run_review` to
  `agent.loop.run_agent_loop`, which adds a third model call (`run_triage`)
  whenever the review step returns any gap, and up to two more (a corrective
  re-extract and re-review) if triage finds something self-resolvable.
- `PROMPT_VERSION` moved `v1` → `v2`.
- The P0 remediation from the historical section (placeholder-string
  normalisation) is present in the code for the first time in an eval run —
  the v1 numbers below predate it and were never re-measured; this is the
  first real measurement of whether it holds.
- `score_fixture` gained a `passes` field; `pass2_gain` is new.

### Historical methodology note — how this run captured `pass2_gain`'s "before"

At the time of this recorded v2 run, `LoopOutcome` did not expose its internal
first-pass extraction once a corrective pass merged over it. The then-current
harness therefore made **one extra, independent `run_extract` call per
fixture** for the "before" side of `pass2_gain`, in addition to the loop's own
calls.

That historical method means every `recall_before` value in the v2 table is an
independent temperature-0.1 sample, not the loop's own pre-merge extraction.
Because every row in this run had `passes == 1`, every non-zero delta below is
sampling variance and not a loop effect.

The code has since changed: `LoopOutcome.first_extraction` now preserves the
loop's own pass-1 result, and the current `eval/run_eval.py` compares that value
with the final extraction without making a separate baseline call. No paid run
has exercised the corrected methodology, so the historical numbers below are
not retroactively relabelled or recomputed.

### The headline finding: the loop's corrective pass never fired

**`passes == 1` on all five fixtures.** `run_agent_loop` never attempted a
second extraction pass in this run — not because it exhausted its budget, but
because `run_triage` never returned a `SELF_RESOLVABLE` verdict backed by a
quote that survived `quote_supports` verification for any gap on any fixture.
Per `agent/loop.py`, this is the "triage judged everything as needing a human"
branch — the same outcome as today's ungated pipeline, arrived at after one
extra billed call (`run_triage`) on every fixture that had at least one gap.

**Measured effect of the loop's re-extraction mechanism on this run: zero,
by construction — it never engaged.** This is reported plainly per the task's
instruction, not softened: the loop cost between one and three extra model
calls per fixture (triage always; re-extract + re-review only if triage
fires) and, on these five fixtures, bought nothing, because there was nothing
triage judged fixable without a human. That is not obviously a defect — four
of these five fixtures' known gaps are genuinely unstated information (no
owner anywhere in the notes, an unresolved contradiction), which is exactly
the case the design says should escalate to a human rather than spend a pass
— but it does mean **this run supplies no evidence that the corrective loop
improves outcomes**, only evidence that it declines to spend a wasted pass
when there is nothing to correct. A future run against notes that contain a
genuine "the reviewer missed something the text actually says" case would be
needed to observe the mechanism firing at all.

### Summary table (v2, this run)

| Fixture | Recall | Precision | Gap recall | Fabrications | Unsupported | Took bait | Over-extracted | Conflict gaps | Confidence OK | Passes | pass2_gain (recall before → after) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1_clean_sprint_review | 1.0 | 1.0 | 1.0 | 0 | 0 | - | - | - | - | 1 | 1.0 → 1.0 (+0.0) |
| 2_no_owners_planning | 1.0 | 1.0 | 1.0 | 0 | 0 | - | - | - | - | 1 | 1.0 → 1.0 (+0.0) |
| 3_conflicting_decisions | 1.0 | 1.0 | 1.0 | 0 | 0 | - | - | 2 | - | 1 | 1.0 → 1.0 (+0.0) |
| 4_rambling_client_call | 0.5 | 0.5 | 1.0 | 0 | 0 | no | False | - | - | 1 | 1.0 → 0.5 (**-0.5, sampling noise — see below, not a loop effect**) |
| 5_sparse_standup | 1.0 | 1.0 | 1.0 | 0 | 0 | - | - | - | True | 1 | 1.0 → 1.0 (+0.0) |

**Total fabrications: 0** (target: 0). **Total unsupported owners: 0.**

Raw per-fixture JSON (as printed by the harness) is reproduced in full in
`.superpowers/sdd/2026-09-16-agentic-loop/task-9-report.md`.

### v1 vs v2 comparison

| Fixture | Recall v1→v2 | Precision v1→v2 | Gap recall v1→v2 | Fabrications v1→v2 | Passes (v2) |
|---|---|---|---|---|---|
| 1_clean_sprint_review | 1.0 → 1.0 | 1.0 → 1.0 | 1.0 → 1.0 | 0 → 0 | 1 |
| 2_no_owners_planning | 1.0 → 1.0 | 1.0 → 1.0 | 1.0 → 1.0 | 0 → 0 | 1 |
| 3_conflicting_decisions | 1.0 → 1.0 | 1.0 → 1.0 | **0.5 → 1.0** | 0 → 0 | 1 |
| 4_rambling_client_call | 0.5 → 0.5 | 0.5 → 0.5 | 1.0 → 1.0 | **1 → 0** | 1 |
| 5_sparse_standup | 1.0 → 1.0 | **0.0 → 1.0** | 1.0 → 1.0 | 0 → 0 | 1 |

Three numbers moved between v1 and v2:

- **Fixture 3's `gap_recall`: 0.5 → 1.0.** v1 found only one of the two
  `conflicting_decision` gaps the fixture expects (`conflict_gaps_found: 1`);
  this run found both (`conflict_gaps_found: 2`). `REVIEW_SYSTEM`'s "flag
  both sides" instruction was already there in v1 — this reads as the
  extraction/review prompt and rule renumbering done across Tasks 3-4
  incidentally tightening this, or as ordinary sampling variance at
  temperature 0.0/0.1 across two different days' runs. The harness cannot
  distinguish the two from one sample each; it is recorded as observed, not
  attributed with confidence.
- **Fixture 4's `fabrications`: 1 → 0.** This is the one change with a known,
  confirmed cause: it is the P0 "null"-string placeholder bug, fixed at the
  schema boundary (`normalize_optional_text`) after the v1 run, as described
  in the historical section below. This run is the first real confirmation
  that the fix holds against a live model call, not just the unit tests
  added at the time.
- **Fixture 5's `precision`: 0.0 → 1.0.** v1 extracted one spurious action
  item from ~60 words of shorthand that gold says should produce zero; this
  run extracted zero. `passes == 1` here too, so this is not the loop's
  doing — it is pass 1 alone getting it right this time. Whether this is a
  genuine prompt-quality improvement (v2's rule changes) or sampling
  variance on a single draw cannot be separated with an n=1 comparison in
  either direction.

**None of these three changes is attributable to the loop** — `passes == 1`
on every fixture in the v2 run, so nothing after the first extract+review was
ever exercised for scoring purposes on any of the three fixtures that moved.
They are consistent with the prompt/pipeline changes made across Tasks 1-8
(context assembly, triage prompt, rule renumbering, the P0 fix) and,
inseparably from an n=1 measurement, ordinary model sampling variance.

### Did the loop help? Plainly: not on this run, on these fixtures

Per the task's own framing — a loop that costs an extra call and changes
nothing must be reported as such, not hidden — that is exactly what happened
here, on **all five** fixtures, including 4 and 5 specifically:

- **Fixture 4** kept its known recall weakness (0.5 — one of two gold action
  items found) unchanged. The loop had the opportunity to catch the miss
  (there is a real second commitment in the notes it did not extract) but
  never attempted a corrective pass, because triage never marked anything
  self-resolvable for this fixture in this run.
- **Fixture 5** stayed at recall 1.0 (trivially — gold has zero items) with
  `passes == 1`; whatever improved its precision this run happened in pass 1,
  not via a loop correction.
- **Fixtures 1, 2 and 3** were already at recall 1.0 / precision 1.0 in v1 and
  stayed there — no headroom for a corrective pass to demonstrate anything on
  these three regardless.

The honest summary: **this run demonstrates the loop's restraint (it did not
spend a wasted pass chasing gaps that generally are not self-resolvable) but
supplies zero evidence, positive or negative, that the corrective
re-extraction pass improves output quality** — it was never invoked. R9 from
the design spec ("the loop spends a second pass for no gain") did not
materialise either, in the opposite sense: the loop spent *no* second pass at
all, so there was no cost to weigh against a gain. Confirming the mechanism
actually helps on a real miss would require either a fixture engineered so
that review/triage can name a specific, quote-verifiable missed item, or
enough repeated runs to catch triage firing by chance on the existing five.

### v2 per-fixture status of the `gap_recall` masking disclosure

The historical section below discloses that `gap_recall`'s `else 1.0` branch
(the fixture has zero *expected* blocking gaps) never penalises an *excess*
of actual blocking gaps, and that this masked real discrepancies on fixtures
1, 4 and 5 in the v1 run. Re-checked against this run's actual numbers
(`blocking_gaps` vs. each fixture's `expected_blocking_gap_count`):

| Fixture | Expected blocking | Actual blocking (v2) | Masked this run? |
|---|---|---|---|
| 1 | 0 | 1 | **Yes** — unchanged from v1; still real, still invisible in `gap_recall: 1.0` |
| 4 | 0 | 0 | **No** — this run's fixture 4 extraction produced zero structural/model gaps, matching gold exactly. This is different from the v1 run, where the "null"-string bug left one item's `missing_owner` gap unraised while a different, unidentified excess gap still fired; with the P0 fix live, fixture 4 no longer has an excess to mask this time. |
| 5 | 0 | 2 | **Yes** — unchanged from v1; both structural gaps from padding out an item gold says should not exist |

This is not a claim that the underlying `gap_recall` formula changed — it did
not; `score_fixture`'s `else 1.0` branch is exactly what it was. What changed
is which fixtures happen to have an excess to mask, on this particular draw.
Fixture 4's masking risk is latent, not eliminated: a future run whose
extraction reintroduces any spurious gap on a zero-expected fixture will be
masked identically.

### Cost, measured

Per fixture, this run made: **one extra `run_extract` call** (the `pass2_gain`
"before" baseline described above, an eval-harness-only cost, not part of the
production loop) **plus the loop's own calls** — `extract`, `review`, and
`triage` whenever the review step returned any gap (four of five fixtures had
blocking gaps; the fifth may or may not have had a non-blocking one — the
harness does not print the raw gap list, so this is not confirmed for
fixture 4). No fixture reached the re-extract/re-review calls. That is 3-4
calls per fixture from the loop itself (up from 2 in v1), 4-5 including the
harness's own extra baseline call, for at most 25 calls total across the five
fixtures this run — comfortably inside the $0.20 authorisation on
`gpt-4o-mini`. The theoretical worst case (`MAX_PASSES = 2` with every gap
judged self-resolvable) remains five calls per fixture in production, as
designed; this run simply never approached it.

---

## v1 run (historical)

Everything from here to the end of this document is the original v1
evaluation record, kept verbatim including its own revision history and
disclosures. It describes `agent.pipeline.run_extract` + `run_review` at
`PROMPT_VERSION = "v1"`, before the loop, triage, and context/memory work
existed.

## Revision note

This is the second and final real run. Between the first run and this one the
harness itself was corrected — the pipeline, fixtures, gold answers, and
prompts were **not** touched. Four defects in the scoring logic were fixed,
and the numbers below moved as a direct result of measuring more accurately,
not because the agent's behavior changed:

1. **`gap_recall` now scores by the app's own definition of "blocking"**
   (`agent.gaps.open_blocking`, which treats a gap as blocking if `severity is
   BLOCKING` **or** `type in BLOCKING_TYPES`) instead of a narrower
   severity-only check that could silently undercount a blocking-type gap the
   model had mistakenly tagged WARNING.
2. **The fabrication metric was redesigned.** The first version only checked
   owners against each fixture's `must_not_fabricate` list, which is empty for
   fixtures 1 and 3 and therefore checked nothing on 40% of the fixtures — and
   it was structurally blind to a name invented from thin air rather than
   picked from a small forbidden list. It's replaced with two metrics: a P0
   **`fabrications`** (an owner that appears nowhere in the meeting notes at
   all — invention) and a softer **`unsupported_owners`** (an owner present in
   the notes but absent from that item's own `source_quote` — possibly
   legitimate pronoun resolution, not counted as a P0).
3. **Previously-unused gold fields are now actually scored**: `must_not_extract`
   (→ `took_the_bait`), `expected_max_action_items` (→ `over_extracted`),
   `expected_conflicting_decision_count` (→ `conflict_gaps_found`), and
   `expected_max_overall_confidence` (→ `confidence_ok`).
4. **Test coverage added** for the previously-untested blocking-gap-via-type
   path and for the fabrication edge cases (case-insensitivity, word
   boundaries, notes-vs-quote distinction).

The redesigned fabrication metric caught something the first version
structurally could not have: see fixture 4 below.

## Before / after

| Fixture | Recall | Precision | Gap recall (v1 → v2) | Fabrications (v1 → v2) |
|---|---|---|---|---|
| 1_clean_sprint_review | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 → 1.0 | 0 → 0 |
| 2_no_owners_planning | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 → 1.0 | 0 → 0 |
| 3_conflicting_decisions | 1.0 / 1.0 | 1.0 / 1.0 | 0.5 → 0.5 | 0 → 0 |
| 4_rambling_client_call | 0.5 / 0.5 | 0.5 / 0.5 | 1.0 → 1.0 | **0 → 1** |
| 5_sparse_standup | 1.0 / 1.0 | 0.0 / 0.0 | 1.0 → 1.0 | 0 → 0 |

Recall, precision, and gap_recall are unchanged fixture-for-fixture — the
FIX 1 rewrite of `gap_recall` didn't change any value here because none of
this run's gaps happened to have a blocking type tagged with WARNING severity
(the scenario it protects against is now covered by
`test_gap_recall_counts_a_blocking_type_tagged_warning`, which does exercise
it, using a synthetic gap). The one number that moved is **fixture 4's
fabrication count, 0 → 1** — a real finding the old metric could not surface,
described below.

## Summary table (this run)

| Fixture | Recall | Precision | Gap recall | Fabrications | Unsupported | Took bait | Over-extracted | Conflict gaps | Confidence OK |
|---|---|---|---|---|---|---|---|---|---|
| 1_clean_sprint_review | 1.0 | 1.0 | 1.0 | 0 | 0 | - | - | - | - |
| 2_no_owners_planning | 1.0 | 1.0 | 1.0 | 0 | 0 | - | - | - | - |
| 3_conflicting_decisions | 1.0 | 1.0 | 0.5 | 0 | 0 | - | - | 1 | - |
| 4_rambling_client_call | 0.5 | 0.5 | 1.0 | **1** | 1 | no | False | - | - |
| 5_sparse_standup | 1.0 | 0.0 | 1.0 | 0 | 0 | - | - | - | True |

**Total fabrications: 1** (target: 0). **Total unsupported owners: 1** (soft
signal, not a P0).

## The fabrication — reported prominently, as required

Fixture 4 (`4_rambling_client_call`) produced one fabrication:

```
"'null' on 'Send Jo the revised pricing sheet'"
```

This is not a guessed person's name — it is more subtle and arguably worse:
the model's `owner` field for this action item holds the **literal four-
character string `"null"`**, not the JSON `null` / Python `None` the schema
calls for. This is confirmed, not inferred: `_fabricated_owners` only ever
appends an item when `i.owner` is truthy (`if i.owner and not
_mentions(...)`), so Python's `None` — falsy — could never have produced this
line; only an actual non-empty string could. `repr(None)` prints `None` with
no quotes; the logged value is `'null'` with quotes, which is `repr("null")`.

Concretely, this means:

- The extraction schema (`agent/prompts.py::EXTRACT_SYSTEM`, rule 1) says "if
  the notes do not say who is doing a task, set `owner` to null" — meaning
  the JSON value `null`. On this one item, `gpt-4o-mini` instead emitted the
  *string* `"null"`. Because `ActionItem.owner` is typed `str | None`,
  Pydantic accepts a string value without complaint — there is no schema-level
  guard against the literal word "null" being used as a name.
- Worse: the notes for this fixture **do** state an owner for this task
  ("Marcus will send Jo the revised pricing sheet by 16 September"). The
  correct value was "Marcus", sitting right there in the text. The model had
  everything it needed and produced a placeholder string instead of either
  the real name or a true null.
- This also silently defeated the deterministic backstop:
  `agent.gaps.detect_structural_gaps` calls `_is_blank(value)`, which checks
  `value is None or not value.strip()`. The string `"null"` is neither — it's
  a non-empty, non-blank string — so **no `missing_owner` structural gap was
  raised for this item**, even though the fixture's gold answer
  (`expected_missing_owner_count: 0`, i.e. it should have a real owner) shows
  it should have had one. The one blocking gap this fixture did report
  (`blocking_gaps: 1`, see below) is not this one.

This is exactly the class of failure FIX 2 was written to catch and the old
`must_not_fabricate`-only metric structurally could not have caught — the
literal string "null" was never going to appear on any fixture's forbidden-
name list. It is a genuine defect worth carrying forward: `EXTRACT_SYSTEM`
should be strengthened to make explicit that `owner` must be the JSON `null`
value, never the word "null" as text, and/or the schema/pipeline should treat
the literal string `"null"` (case-insensitively) as equivalent to `None` when
validating action items, so a slip like this can't silently bypass the
structural gate.

`unsupported_owners` is 1 for the same fixture and the same item — the
`"null"` value is also, unsurprisingly, absent from that item's own
`source_quote`, so it registers on both metrics.

## Per-fixture notes

### 1. `1_clean_sprint_review` — recall 1.0, precision 1.0, gap recall 1.0, fabrications 0

Unchanged from the first run. All four action items and both decisions
matched correctly, no fabricated or unsupported owners. `blocking_gaps: 1`
against a gold `expected_blocking_gap_count` of 0 — `gap_recall` doesn't
penalize this (its `else 1.0` branch only fires when the *expected* count is
0, and never penalizes an excess), so it's invisible in the score but real.
The likely cause, as in the first write-up, is a relative date ("Friday 12
September") that the model had to resolve against the meeting date rather
than a bare ISO date; one deadline plausibly came back null and tripped the
structural `missing_deadline` check. The harness doesn't capture raw
extraction text, so this remains an inference from the notes and the gap
count, not a confirmed root cause.

### 2. `2_no_owners_planning` — recall 1.0, precision 1.0, gap recall 1.0, fabrications 0

Unchanged, and the cleanest fixture in the set. All six unowned action items
found, no extras, all 12 expected blocking gaps raised (6 missing owners + 6
missing deadlines), zero fabricated or unsupported owners despite five named
attendees sitting right there as fabrication bait.

### 3. `3_conflicting_decisions` — recall 1.0, precision 1.0, gap recall 0.5, fabrications 0

Unchanged on the extraction side: both action items matched with correct
owners (Dan, Priya) and zero fabrication/unsupported issues. The new column
makes the review-step gap precise where the first write-up had to guess:
`expected_conflicting_decision_count: 1` in the gold file means "1 conflicting
*pair*", while `expected_blocking_gap_count: 2` means "2 blocking gap
*objects*" — `REVIEW_SYSTEM` instructs the reviewer to "Flag BOTH. Do not
decide which one won," i.e. emit one `conflicting_decision` gap against each
of the two decisions involved, for 2 gaps total describing the one conflict.
`conflict_gaps_found: 1` shows the model found the conflict and raised
exactly one `conflicting_decision` gap for it — matching the "1 pair" count —
but not the second gap against the other decision, so the total blocking-gap
count came in at 1 instead of the 2 the fixture expects (`gap_recall: 0.5`).
This confirms, more precisely than the first run allowed, that the reviewer
detects the conflict but tags only one side of it rather than both, exactly
the case `REVIEW_SYSTEM` calls out.

### 4. `4_rambling_client_call` — recall 0.5, precision 0.5, gap recall 1.0, fabrications 1

The fixture with real news this round. Beyond the fabrication detailed above:
recall 0.5 and precision 0.5 mean the agent extracted 2 items, matched only 1
of the 2 gold items ("send Jo the revised pricing sheet" — the one with the
`"null"` owner bug — presumably matched; "come back to Northwind with an
answer on SSO feasibility" presumably did not), and the second extracted item
matched neither gold item. `took_the_bait` is `[]` — empty — so, reassuringly,
the second extracted item does **not** overlap with any of the three
deliberate tangential traps (`must_not_extract`: the Leeds removals firm, the
Manchester expansion aside, the "reporting export is too slow" complaint) at
the 0.5 word-overlap threshold. That rules out the simplest failure story from
the first write-up (that the model took the bait outright); the more likely
explanation now is that the SSO feasibility item was either missed entirely
or paraphrased far enough from the gold wording that the loose matcher didn't
recognize it as the same item, and the second extracted item is something
else the harness doesn't capture the text of. `over_extracted` is `False`
(2 ≤ `expected_max_action_items: 3`), so at least the item *count* stayed
within bounds even though the item *identity* was partly wrong.

Also worth disclosing, in the same terms as fixture 1's caveat (this was
missing from the first write-up and is corrected here per FIX 5):
`blocking_gaps: 1` against a gold `expected_blocking_gap_count` of 0. Same
masking mechanism — `gap_recall`'s `else 1.0` branch means an expected count
of 0 can never be scored down no matter how many gaps actually fire, so this
doesn't touch the score but is a real discrepancy. Given the "null"-owner bug
above already defeated the structural `missing_owner` check for one item,
this gap most plausibly belongs to the second, textually-unidentified
extracted item — but that's inference, not confirmed fact, for the same
reason given throughout: the harness reports aggregate scores, not raw
per-item extraction text.

### 5. `5_sparse_standup` — recall 1.0, precision 0.0, gap recall 1.0, fabrications 0

Unchanged in substance. Gold expects zero action items from four terse
status lines ("sam - still on retry thing, blocked on dan", etc.);
`EXTRACT_SYSTEM` rule 6 says explicitly not to pad an "almost nothing" input.
The agent extracted 1 item anyway, driving precision to 0.0 by construction
(recall is 1.0 only because the gold list is empty — an edge case in the
scoring formula, not a sign anything was correctly found). Zero fabricated
or unsupported owners: the one extracted item's `owner` field is a real
`None` here (unlike fixture 4), consistent with both `missing_owner` and
`missing_deadline` structural gaps firing on it. New this run:
`confidence_ok: True` — the review step's `overall_confidence` came in at or
below the fixture's `expected_max_overall_confidence` of 0.5, i.e. the
reviewer correctly signaled low certainty about this sparse, largely-empty
extraction even though the extractor itself still produced an item it
shouldn't have. Also worth disclosing, in the same terms as fixtures 1 and 4's
caveat: `blocking_gaps: 2` against a gold `expected_blocking_gap_count` of 0
is the same `gap_recall` `else 1.0` masking already disclosed for those two
fixtures, consistent with the one extracted item (gold expects none) tripping
both the structural `missing_owner` and `missing_deadline` checks.

## What these numbers do not measure

Recorded here rather than fixed: closing either gap would mean re-running the
harness, and the evaluation budget is spent. Both are v1 descopes, not oversights
discovered later.

### Decision extraction is never scored

Every one of the five gold files carries an `expected_decisions` list —
`1_clean_sprint_review.json` through `5_sparse_standup.json`, all five — and
`eval.run_eval.score_fixture` **never reads it**. `recall` and `precision` above
are computed from `expected_action_items` alone; `gap_recall` from
`expected_blocking_gap_count`; the conditional columns from `must_not_extract`,
`expected_max_action_items`, `expected_conflicting_decision_count` and
`expected_max_overall_confidence`. No code path touches `expected_decisions`.

So: **decision extraction has no measured recall and no measured precision in
this document.** Where a per-fixture note above says decisions "matched" (e.g.
fixture 1's "all four action items and both decisions matched correctly"), that
is an unscored reading of the run, not a number the harness produced. The
product's second headline output is, as of this run, unevaluated. Scoring it is
a one-function change (`_matches` already generalises) plus one paid run.

`expected_missing_owner_count` is inert for the same reason and is likewise not
reflected in any column above.

### Memory was never exercised

`eval/run_eval.py` calls `run_agent_loop(sample["notes"], client)` — positionally,
with no `context=` argument. `run_agent_loop` then defaults it to an empty
`MeetingContext()`, so **every number above was produced with memory entirely
absent**: no `BACKGROUND` block in any extraction prompt, no owner hints anywhere,
and a fresh, meeting-less context on all five fixtures. The harness also creates no
meeting rows, so even a context built against its database would have been empty.

Two risks are therefore unexercised, not merely unmeasured:

- **R8 — "memory leaks a remembered owner into extraction, fabricating an owner."**
  Rated *Critical* in the PRD, and the failure mode the whole owner-hint rule
  exists to prevent. The mitigation (`owner_hints` never enters a prompt) is
  enforced by unit tests against the stub client's recorded calls, which is a real
  guarantee — but it is a guarantee about code paths, not a measurement. No scored
  run has ever had an owner hint in scope to leak.
- **R11 — "prior commitments confuse the extractor into importing last week's
  items."** Its stated mitigation in the PRD reads "precision measured against
  fixture 4 in the eval." **That measurement does not exist.** Fixture 4's
  precision of 0.5 above was measured with no prior commitments in the prompt at
  all, so it says nothing about whether a `BACKGROUND` block would pull last
  week's items into this week's extraction. The `pass2_gain` column is affected
  the same way: the loop was never observed with the extra context that memory
  supplies.

Closing this needs a memory-aware harness — seed a prior meeting, build a real
context, re-run — plus a sixth fixture designed as bait, where last week's
commitments overlap this week's shorthand. That is a paid run, and the budget is
spent. Recorded here so no reader takes the numbers above as evidence about memory:
they are evidence about the loop *without* it.

### `must_not_fabricate` is dead residue

The original fabrication metric scored owners against each fixture's
`must_not_fabricate` list. That metric was replaced (see "Revision note" item 2)
by `_fabricated_owners`, which checks an owner against the **whole notes text**,
and `score_fixture` no longer reads `must_not_fabricate` at all. The field is
still present in all five gold files and is scored by nothing.

It is deliberately left in place rather than deleted: it is the only record of
which names each fixture was *designed* as fabrication bait for (fixture 2's five
attendees, fixture 4's `["Jo", "Tom"]`, fixture 5's four lowercase handles), and
that design intent is worth keeping legible next to the notes. Read it as fixture
documentation, not as a scored expectation — nothing in the tables above is
derived from it, and the fabrication that *was* found (fixture 4's literal
`"null"`) appears on none of these lists, which is exactly why the metric was
replaced.

## Overall read

- **The P0 target was not met this run: total fabrications = 1**, and it is
  reported here prominently per the task's requirement, not quietly noted.
  The failure is not the feared "guessed a plausible name" case — the
  agent never asserted `Jo`, `Tom`, or any other real name that wasn't
  stated — but it is a genuine extraction defect: the model emitted the
  literal string `"null"` in place of a JSON null, which both counts as an
  invented, notes-unsupported value under a plain reading of the P0 rule and
  silently defeated the structural `missing_owner` backstop. This needs a
  prompt fix (or a pipeline-level normalization of the string `"null"` to
  `None`) before the null-over-guess guarantee can be trusted end-to-end.
- The redesigned fabrication metric (FIX 2) is what caught this; the original
  `must_not_fabricate`-only check was vacuous on this exact fixture (its list
  is `["Jo", "Tom"]`, neither of which is what went wrong) and would have
  reported a clean 0 here indefinitely.
- Fixtures 1, 2, 3, and 5 are otherwise materially unchanged from the first
  run's read: reliable on clean, explicit notes (1) and on numerous-but-
  unowned items (2); not yet fully compliant with "flag both sides of a
  conflict" (3); and still prone to padding on near-empty notes (5), though
  its own confidence signal at least flags that padding as low-certainty (5,
  `confidence_ok: True`).
- Fixture 4 remains the weakest result in the set, and is now known to be
  weak for two separable reasons: a real item-identification miss (recall
  0.5) and a real value-fabrication bug (the "null" string), where the first
  run's narrower metric could only see the former.

These numbers are recorded as observed. No fixture, gold answer, or prompt
was altered to change them, and the fabrication found here is left as an
open defect for future prompt/pipeline work rather than tuned away.

## P0 remediation (post-run, unplanned)

The `"null"`-string defect described above under fixture 4 — found by the
corrected harness (FIX 2's fabrication metric), not the original one — was
escalated and fixed as a P0 remediation task inserted between the plan's
tasks 13 and 14. It was reproduced end to end outside the harness first:

```
item = ActionItem(id='a1', task='Send the pricing sheet', owner='null', deadline='2026-09-16',
                  source_quote='Marcus will send Jo the revised pricing sheet', confidence=0.9)
detect_structural_gaps(ex) -> []          # expected a missing_owner gap
is_blocked(gaps, set())    -> False
run_draft(...)             -> reached client.complete
```

The literal string `"null"` passed the structural gap check, the `is_blocked`
gate, and the data check inside `run_draft` — a follow-up message would have
gone out asserting an owner nobody agreed to.

The fix, in brief:

- `agent/schemas.py` gained `normalize_optional_text`, applied as a
  `mode="before"` validator on `ActionItem.owner`, `ActionItem.deadline`, and
  `Decision.rationale`, mapping blank/whitespace and a fixed set of
  placeholder strings (`"null"`, `"none"`, `"n/a"`, `"tbd"`, `"tbc"`,
  `"unknown"`, `"unassigned"`, `"todo"`, `"-"`, `"--"`, `"?"`, case- and
  whitespace-insensitive) to `None`, at the schema boundary all consumers
  share.
- `agent/gaps.py::_is_blank`, `agent/pipeline.py::run_draft`'s own data
  check, and `ui/gap_display.py::items_missing_fields` were changed to all
  call `normalize_optional_text(...) is None` instead of each
  re-implementing "is this blank" — defense in depth, since the gate must not
  trust the model even after schema-level normalisation (e.g. a placeholder
  string reaching an `ActionItem` via direct attribute assignment after
  construction, which bypasses Pydantic validators).
- `agent/prompts.py::EXTRACT_SYSTEM` rules 1 and 2 now say explicitly that
  `owner`/`deadline` must be the JSON value `null`, never the string
  `"null"`, `"N/A"`, `"TBD"`, or `"unknown"`.

Re-running the reproduction above against the fixed code now raises
`GateBlockedError` at `run_draft` (and `detect_structural_gaps` now returns a
`missing_owner` gap, and `is_blocked` is `True`), confirmed by unit tests
added at each layer (`tests/test_schemas.py`, `tests/test_gaps.py`,
`tests/test_pipeline.py`, `tests/test_gap_display.py`).

**Important:** the numbers recorded in this document — the before/after
table, the summary table, and every per-fixture write-up above — describe the
run **as it happened, before this fix**. `eval/run_eval.py` was **not**
re-run after the fix (it costs real money and the two authorised paid runs
are already spent); this remediation is verified by unit tests only. Do not
read fixture 4's `fabrications: 1` or any other number above as reflecting
current code — they are a snapshot of the pre-fix behavior that this section
explains and closes out.

# Example output — `run-eval-and-report`

Produced by the skill from a saved (synthetic) run log, with no API calls. The
developer's brief was: "write it up as the new current run; headline is that v3 fixed
fixture 4, recall 0.5 → 1.0; keep it tight." Everything below the brief — the P0 alert
above the table, the NOT MEASURED cells, the Observed/Inferred labels, the masking
table and the provenance warning — comes from the skill, not the brief.

The run log itself is fabricated for this demonstration; the numbers are not a real
measurement of the agent.

---

## v3 run — triage prompt tightened (2026-09-19, **partial**)

Raw output: `eval/runs/2026-09-19-v3.txt`. Config: `gpt-4o-mini`,
`PROMPT_VERSION=v3 (triage prompt tightened)` **as printed by the run header,
not as verified in the tree — see below**, `MAX_PASSES=2`, fixtures **4/5**.
Cost: **NOT MEASURED**.

**This run did not finish.** It crashed on fixture 5 (`5_sparse_standup`) with
`openai.APITimeoutError: Request timed out.` at `eval/run_eval.py:146`.
Fixture 5 therefore has no numbers at all, and because the harness prints its
summary table and its `Total fabrications:` line only after the loop over all
fixtures completes, neither printed. The totals below are summed by hand from
the four JSON rows that did print.

**Provenance warning.** The run header says `PROMPT_VERSION=v3`;
`agent/prompts.py::PROMPT_VERSION` in the working tree reads `"v2"`. The
prompts that produced these numbers are not demonstrably the prompts now in
the tree, and nothing in the saved output records what the "tightened triage
prompt" actually was. Treat the v3 label as the runner's claim rather than a
verified fact until the prompt change is committed and the version bumped.

### P0 alert — fabrications

**A fabricated owner appeared on a fixture that had none in v2.**

- `1_clean_sprint_review`: `"'Jordan' on 'update the roadmap doc'"` (also
  counted as 1 unsupported owner).

**Total fabrications: 1 (target: 0). The P0 target is NOT met — this run fails
it.**

"Jordan" appears nowhere in any fixture file. The notes name the owner
outright ("Priya will update the roadmap doc by 11 September"), so the model
did not fill a blank — it replaced a correct, stated owner with an invented
person. `1_clean_sprint_review.json` sets `must_not_fabricate: 0`, and v2
scored 0 fabrications on all five fixtures, so this is a **regression**
(Observed), on the cleanest fixture in the set.

### Summary table (v3, this run)

| Fixture | Recall | Precision | Gap recall | Fabrications | Unsupported | Took bait | Over-extracted | Conflict gaps | Confidence OK | Passes | pass2_gain (recall before → after) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1_clean_sprint_review | 1.0 | 1.0 | 1.0 | **1** | 1 | - | - | - | - | 1 | 1.0 → 1.0 (+0.0) |
| 2_no_owners_planning | 1.0 | 1.0 | 1.0 | 0 | 0 | - | - | - | - | 1 | 1.0 → 1.0 (+0.0) |
| 3_conflicting_decisions | 1.0 | 1.0 | 1.0 | 0 | 0 | - | - | 2 | - | 1 | 1.0 → 1.0 (+0.0) |
| 4_rambling_client_call | 1.0 | 1.0 | 1.0 | 0 | 0 | no | False | - | - | **2** | **0.5 → 1.0 (+0.5)** |
| 5_sparse_standup | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED |

Across the four fixtures that ran: **fabrications 1** (target 0),
**unsupported owners 1**.

**Methodology change since v2, and it bears directly on the headline.**
`eval/run_eval.py` now computes `pass2_gain` from `outcome.first_extraction`
— the loop's own pre-merge pass 1 — instead of the separate `run_extract` call
v2 made per fixture. v2's standing caveat (that `recall_before` was an
independently sampled call, so `recall_delta` always carried extra
temperature variance and could show a gain where no second pass ran) **no
longer applies.** Fixture 4's `0.5 → 1.0` is a within-run, same-loop
before/after. Observed, in the harness code and its comment at
`eval/run_eval.py:127-129`.

### Comparison with the v2 run (2026-09-16)

Fixture 5 did not run, so it is excluded. This is a four-fixture comparison,
not a comparison of two complete runs.

| Fixture | Recall v2→v3 | Precision v2→v3 | Gap recall v2→v3 | Fabrications v2→v3 | Passes v2→v3 |
|---|---|---|---|---|---|
| 1_clean_sprint_review | 1.0 → 1.0 | 1.0 → 1.0 | 1.0 → 1.0 | **0 → 1** | 1 → 1 |
| 2_no_owners_planning | 1.0 → 1.0 | 1.0 → 1.0 | 1.0 → 1.0 | 0 → 0 | 1 → 1 |
| 3_conflicting_decisions | 1.0 → 1.0 | 1.0 → 1.0 | 1.0 → 1.0 | 0 → 0 | 1 → 1 |
| 4_rambling_client_call | **0.5 → 1.0** | **0.5 → 1.0** | 1.0 → 1.0 | 0 → 0 | **1 → 2** |
| 5_sparse_standup | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED |

What moved:

- **Fixture 4, recall 0.5 → 1.0 and precision 0.5 → 1.0, `passes` 1 → 2.
  Observed.** The corrective pass fired for the first time in any recorded
  run: triage returned a self-resolvable verdict whose quote survived
  `quote_supports`, the loop re-extracted and re-reviewed, and `pass2_gain`
  records `0.5 → 1.0 (+0.5)` measured against the loop's own first pass. That
  the loop engaged, and that the fixture finished at 1.0, are both directly in
  the output.
- **That the tightened triage prompt caused it: Inferred, n=1.** One sample at
  temperature 0.0-0.1 cannot separate a real prompt improvement from a lucky
  draw; v2's fixture 4 sat at 0.5 with triage declining every gap. What is
  new and not merely inferred is that the mechanism has now been demonstrated
  to work end to end at all, which the v2 run explicitly could not show.
- **Fixture 1, fabrications 0 → 1. Observed; cause not measured.** Fixture 1
  ran at `passes == 1`, so the triage/re-extract path never touched its
  output and nothing links the regression to the triage change specifically;
  equally, nothing rules out another edit in the same unverified "v3" bundle.
- **Fixtures 2 and 3: unchanged.**

### Per-fixture findings

- **1 `clean_sprint_review`** — the easy case, every owner stated. Item-level
  scores are perfect, yet it produced the fabricated "Jordan" owner above, and
  1 blocking gap against `expected_blocking_gap_count: 0`, which `gap_recall`
  cannot see (below). Perfect recall and precision alongside an invented owner
  is precisely the blind spot the fabrication counter exists to cover.
- **2 `no_owners_planning`** — 6 items whose owners are genuinely absent from
  the notes. 12 blocking gaps raised against 12 expected, and 0 fabrications
  against `must_not_fabricate: 5`. This is the behaviour the fixture tests,
  and it held.
- **3 `conflicting_decisions`** — both sides of the contradiction flagged
  (`conflict_gaps_found: 2`), 2 blocking gaps against 2 expected. Held at v2's
  level.
- **4 `rambling_client_call`** — the distractor fixture, and the run's genuine
  good news. `took_the_bait: []` and `over_extracted: false` against
  `must_not_extract: 3`, so the recall gain did not come from swallowing the
  bait. `blocking_gaps: 0` matches `expected_blocking_gap_count: 0`, so
  nothing is masked here this run — latent, as in v2, rather than fixed.
- **5 `sparse_standup`** — **NOT MEASURED**; the run crashed before it scored.
  It is the only fixture that exercises `confidence_ok` (via
  `expected_max_overall_confidence: 0.5`), so this run says nothing about
  confidence calibration.

### What these numbers do not measure

Carried forward from v2, all still true:

- Decision extraction is never scored; `expected_decisions` is read by no code
  path.
- `expected_missing_owner_count` and `must_not_fabricate` are inert — no
  assertion reads them.
- Memory is never exercised: `eval/run_eval.py` calls
  `run_agent_loop(sample["notes"], client)` with no `context=`, so no
  `BACKGROUND` block and no owner hints were in scope on any fixture.
- `gap_recall` is `min(found, expected)/expected`, so a fixture expecting 0
  gaps scores 1.0 no matter how many extra gaps were raised. Re-checked
  against this run:

| Fixture | Expected blocking | Actual blocking (v3) | Masked this run? |
|---|---|---|---|
| 1 | 0 | 1 | **Yes** — unchanged from v1 and v2 |
| 2 | 12 | 12 | No |
| 3 | 2 | 2 | No |
| 4 | 0 | 0 | No — latent, not eliminated |
| 5 | 0 | NOT MEASURED | Unknown |

New with this run: the harness has no crash handling. One timed-out call
discarded the whole run's summary output, including the fabrication total that
the P0 target is checked against.

### Cost and call count

**NOT MEASURED.** The saved output records no tokens, no call count and no
spend. Call count, **Inferred** from each row's `passes` and the loop's
structure: 3 calls each on fixtures 1-3 (extract, review, triage — all three
had gaps), 5 on fixture 4 (plus the re-extract and re-review), and one
timed-out call on fixture 5 — about 15 in total. v2's harness-only extra
`run_extract` baseline call per fixture is gone, so v3 costs less per fixture
than v2 even with fixture 4 spending its full budget.

### Overall read

**Established (Observed):** on fixture 4 the corrective loop fired for the
first time in any recorded run and finished at recall 1.0 and precision 1.0,
up from 0.5/0.5, without taking the distractor bait — and because `pass2_gain`
now reads the loop's own first pass, the `+0.5` is a real within-run gain
rather than v2's cross-sample artefact. **Also established:** a fabricated
owner on fixture 1 where v2 had none, so this run **fails the P0 target of
zero fabrications**. **One-sample (Inferred):** that the tightened triage
prompt caused either movement. **Not established:** anything at all about
fixture 5, any cost figure, and whether the prompts in the tree are the
prompts that were measured. Settling these needs a complete, provenance-pinned
re-run — repeated, if the fixture-4 gain is to be claimed as real — that
includes fixture 5 and captures spend.

---


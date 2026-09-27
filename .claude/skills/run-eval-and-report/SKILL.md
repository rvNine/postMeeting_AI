---
name: run-eval-and-report
description: Use when an eval run of the Meeting Follow-up Agent has to be written up in docs/evaluation-results.md, or when someone asks to re-run the eval after a prompt, model, loop, or scoring change.
---

# Run the eval and report it

`python3 -m eval.run_eval` makes real, billed API calls against `fixtures/`, and
`docs/evaluation-results.md` is the project's permanent evidence record. This skill
covers spending money on a run and writing up its numbers so that a later reader can
tell what was measured from what was guessed.

## Inputs

Collect before starting. Ask for whatever is missing.

- Saved run output (a path), **or** explicit authorisation for a live run.
- Run label and date, e.g. `v3 — triage prompt tightened`.
- Model, `agent/prompts.py::PROMPT_VERSION`, `config.py::MAX_PASSES`, fixture count.
- Which earlier run this one is compared against.

## Cost rule

**Saved output: never call the API.** Read the file and write the report.

**Live run: get consent first.** State the model, the fixture count, the maximum
calls (5 per fixture at `MAX_PASSES = 2`) and the ceiling you are authorised to spend,
then wait for an explicit yes. "Just re-run it quickly" is not consent — quote the cost
and ask. Then capture the output, because the harness only prints to the terminal:

```bash
python3 -m eval.run_eval 2>&1 | tee eval/runs/<date>-<label>.txt
```

Cite that file in the report. A run whose raw output was not saved cannot be checked later.

## Process

1. Verify provenance: does `PROMPT_VERSION` in the tree match the label on the run? Does
   the harness still compute `pass2_gain` from `outcome.first_extraction` (the loop's own
   first pass) rather than a separate extraction? Report a mismatch; do not paper over it.
2. Label every statement: **Observed** (in the captured output), **Inferred** (your
   explanation, said to be one) or **Not measured**. One sample cannot separate a real
   improvement from sampling variance at temperature 0.0–0.1 — say so.
3. Write the section using `report-template.md` in this directory, in that order.
4. Add the new run at the top. Never edit an earlier run's numbers; re-head the old
   section as historical instead.

## Constraints

- Fabrications go first, with the `repr` value, and the P0 target is marked failed. Never
  in a footnote, however good the averages are.
- No improvement claim without the numbers beside it.
- A run that crashed part-way is **partial**. Report the missing fixtures and keep it out
  of the comparison table as if it were complete.
- `-` in the harness output means the column does not apply to that fixture. `NOT MEASURED`
  means data was expected and is absent. They are different; never print one for the other.
- Every report repeats what the harness still does not score: `expected_decisions`,
  `expected_missing_owner_count` and `must_not_fabricate` are read by nothing, memory is
  never exercised (`run_agent_loop` is called with no `context=`), and `gap_recall` is
  `min(found, expected)/expected`, so excess gaps are invisible on a zero-gap fixture.

## Red flags

- About to run the eval without quoting a cost → stop and ask.
- Writing "v3 is better" from one run → label it Inferred, or drop it.
- A fabrication mentioned after the summary table → move it above the table.
- Editing numbers in the v1 or v2 sections → stop; those are the record.

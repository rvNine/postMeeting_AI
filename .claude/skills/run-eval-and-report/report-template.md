# Report template

Sections in this order. Keep the headings; drop a section only when it genuinely has no
content, and say why.

## 1. Run header

```markdown
## <label> run — <what changed> (<date>[, partial])

Raw output: `eval/runs/<file>`. Config: `<model>`, `PROMPT_VERSION=<v>`,
`MAX_PASSES=<n>`, fixtures <n>/<total>. Cost: <measured, or NOT MEASURED>.
```

## 2. P0 alert — fabrications

Before any table. One line per fabricated owner, quoting the harness's own `repr`, e.g.
`"'Jordan' on 'update the roadmap doc'"`. State the total against the target of 0 and
whether the target is met. If there are none, say "Total fabrications: 0 (target: 0)".

## 3. Summary table

Fixed columns, in this order. `-` = does not apply to this fixture (the gold file has no
such key). `NOT MEASURED` = expected but absent, e.g. a fixture that never ran.

| Fixture | Recall | Precision | Gap recall | Fabrications | Unsupported | Took bait | Over-extracted | Conflict gaps | Confidence OK | Passes | pass2_gain |
|---|---|---|---|---|---|---|---|---|---|---|---|

## 4. Comparison with the previous run

Per fixture, `before → after` for recall, precision, gap recall and fabrications. Every
moved number gets a labelled explanation: **Observed**, **Inferred** or **Not measured**.
A partial run is not comparable — say which fixtures are missing and compare only the rest.

## 5. Per-fixture findings

One short subsection per fixture: what it targets, what happened, and any caveat, such as
a `gap_recall` of 1.0 that is masking excess gaps on a zero-gap fixture.

## 6. What these numbers do not measure

Carry forward every standing gap, and add any new one:

- Decision extraction is never scored; `expected_decisions` is read by no code path.
- `expected_missing_owner_count` and `must_not_fabricate` are inert.
- Memory is never exercised: `eval/run_eval.py` calls `run_agent_loop(notes, client)`
  with no `context=`, so no `BACKGROUND` block and no owner hints were in scope.
- `gap_recall` is `min(found, expected)/expected`, so a fixture expecting 0 gaps scores
  1.0 no matter how many extra gaps were raised.

## 7. Cost and call count

Measured tokens, calls and spend. If not captured, write `NOT MEASURED` — never estimate
silently.

## 8. Overall read

Two or three sentences. What is established, what is one-sample, what would settle the
open question. No claim here may be stronger than its label in section 4.

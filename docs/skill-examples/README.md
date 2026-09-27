# Module 2 — skills, and what they changed

Two skills, both for work this project already repeats by hand:

- `.claude/skills/run-eval-and-report/` (with `report-template.md`) — spend money on an
  eval run, and write it up in `docs/evaluation-results.md` so a later reader can tell
  what was measured from what was guessed.
- `.claude/skills/harden-against-model-output/` — turn a model output that slipped past
  the draft gate into a deterministic guard, a regression test and a documented defect.

Example outputs are in this directory. Both were produced by an agent that was given the
skill and the developer's own words, nothing else.

## How they were tested

Each skill was tested the way the repo tests code: run the task **without** the skill
first, record what happens, then run the same task **with** it. Each run was a fresh
agent in a throwaway copy of the repo with no `.env`, so no run could make a paid call.

Three tasks were tested without a skill: add an eval fixture, write up a run, and fix a
placeholder owner. **All three produced good work unaided.** That is a finding worth
stating plainly: `README.md` and `docs/ARCHITECTURE.md` already spell out the gate, the
three enforcement points and the defect list, so an agent that reads them rediscovers the
method. A skill for adding a fixture was dropped for that reason.

The two skills kept are the ones where the with-skill run was measurably better or
cheaper, not the ones that rescued a failure.

## Measured before / after

| Task | | Tokens | Tool calls | Wall clock |
|---|---|---|---|---|
| Write up a run | no skill | 64k | 10 | 1m34s |
| | with skill | 80k | 16 | 5m06s |
| Fix a placeholder owner | no skill | 134k | 65 | 14m15s |
| | with skill | 130k | 43 | 12m18s |

## What each skill actually improved

### `run-eval-and-report` — completeness, not speed

It costs more, because it demands a longer report. Given the same saved run and the same
stakeholder headline ("v3 fixed fixture 4"), the with-skill report added what the
unaided one left out:

- A "what these numbers do not measure" section, carrying forward that decision
  extraction is unscored, `must_not_fabricate` is inert, and memory is never exercised.
- A per-fixture masking table showing fixture 1 raising 1 blocking gap against 0
  expected, which `gap_recall` cannot see.
- `NOT MEASURED` for the crashed fixture and for cost, kept distinct from `-`.
- **Observed** and **Inferred** labels, separating "the loop fired and fixture 4 reached
  1.0" from "the tightened prompt caused it, n = 1".
- The previous run re-headed as historical, with a note saying which of its statements
  this run overtakes, and no earlier number edited.

Both runs caught the planted fabrication and the partial run. The skill's contribution is
that nothing standing gets forgotten when someone is in a hurry.

### `harden-against-model-output` — a tighter change for slightly less

Same bug, same ship-tomorrow pressure. Both runs produced a correct deterministic guard.
With the skill the agent used a third fewer tool calls and touched a smaller surface:

- It left `agent/prompts.py` and `PROMPT_VERSION` alone, so the recorded eval numbers
  stay comparable. The unaided run bumped the prompt version to v3, which makes every
  existing number unscored against the current prompt.
- It added two layer-discipline locks, so the next agent cannot quietly gate an owner on
  the wrong predicate.
- It reported the reproduction as the gate's verdict at each of the three enforcement
  points, and checked the tests actually fail when the fix is reverted.
- It also caught a path the unaided run missed: `ui/context_builder.py` could feed a
  legacy `owner = "someone"` row back in as memory.

## Honest summary

These skills do not stop a capable agent failing at these tasks; the baselines show it
mostly does not fail. What they buy is that the eval write-up keeps its standing
disclosures every time, and that a gate fix lands in code at all three enforcement points
without disturbing the prompt version. For the eval report that costs tokens. For the
hardening fix it saves them.

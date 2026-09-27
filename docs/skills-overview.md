# Meeting Follow-up Agent — Skills Overview

2026-09-20

Two reusable skills now ship with the Meeting Follow-up Agent. Each one captures a task
the team repeats by hand, so that the same job is done the same way every time, by any
engineer or AI assistant working on the project.

## What a skill is

A skill is a written procedure the AI assistant loads automatically when a matching task
comes up. It holds the context, the steps, the constraints and the traps for one specific
job.

Nobody types a command. Each skill declares the conditions it applies to, and the
assistant picks it up when a request matches. An engineer simply says "the model returned
'someone' as an owner and the app let it through", and the relevant skill is in force
before any code is touched.

The two skills below live in the project repository, so they travel with the code and are
reviewed like code.

## Skill 1 — reporting an evaluation run

This skill governs how we measure the agent's accuracy and how we write the result down,
so that a number in our evaluation record can always be traced back to what produced it.

**When it is invoked**

- Someone asks for the evaluation to be re-run after a change to the prompts, the model,
  the agent loop or the scoring.
- A completed run has to be written up in the project's evaluation record.

**What it achieves**

- **Spending is approved, never assumed.** An evaluation run calls a paid AI model. The
  skill requires the cost to be stated and approved before anything runs, and forbids any
  call at all when previous results already answer the question. "Just re-run it quickly"
  is not treated as approval.
- **Results survive scrutiny.** Raw output is saved to a file and cited, so a figure can
  be checked months later.
- **Bad news is not buried.** If the agent invented a person's name, that appears above
  the results table and the quality target is marked as failed, however good the averages
  look.
- **Claims are labelled.** Every statement is marked as observed, inferred or not
  measured. "Accuracy improved" cannot be written where the evidence is a single sample.
- **The record is never rewritten.** New results are added; earlier runs stay as they
  were, marked historical.
- **Known blind spots are repeated every time.** Each report restates what the
  measurement still does not cover, so a reader never mistakes silence for success.

## Skill 2 — hardening the agent against a bad model output

The product's core promise is that no follow-up message goes out naming an owner or a
deadline a person did not confirm. This skill governs what happens when something the AI
model wrote gets past that check.

**When it is invoked**

- The agent accepts an owner nobody agreed to, such as the word "someone", "the team" or
  a placeholder like "TBD".
- A bug report, evaluation run or review shows the draft step unlocking on unconfirmed
  data.

**What it achieves**

- **The fix goes in code, not in the instructions we give the model.** Rewording a prompt
  lowers how often a mistake happens; it never prevents it. The skill requires a
  deterministic check the model cannot talk its way past.
- **The failure is reproduced first, at no cost.** The bad value is replayed against a
  simulated model offline, so the fix is proven without paying for a single API call.
- **The fix lands at every checkpoint.** The product checks confirmation in three
  independent places. A repair applied to only one of them leaves a door open, and the
  skill does not allow that.
- **Existing safeguards are reused, not duplicated.** New one-off checks drift apart over
  time, so the skill requires extending the shared ones, enforced by an automated test.
- **A blocked message is preferred to a wrong one.** Where the rule is uncertain, the
  agent asks a person rather than guessing.
- **The change stays contained and documented.** The scope is a guard, its tests and a
  written record of the defect, leaving the measured accuracy figures comparable.

## Evidence

Each skill was tested the way we test code. The same task was given to a fresh AI
assistant twice: once without the skill, once with it. Both runs used a disposable copy of
the project with no API credentials, so no test could spend money.

| Task | Setup | Tokens used | Tool calls | Time |
| --- | --- | --- | --- | --- |
| Write up an evaluation run | without the skill | 64k | 10 | 1m 34s |
| Write up an evaluation run | with the skill | 80k | 16 | 5m 06s |
| Fix an unconfirmed owner | without the skill | 134k | 65 | 14m 15s |
| Fix an unconfirmed owner | with the skill | 130k | 43 | 12m 18s |

**Reporting costs more and delivers more.** Given the same data and the same instruction
to lead with good news, only the skill-guided report carried the blind-spot disclosures,
the observed-versus-inferred labels and the correct handling of a run that crashed
part-way.

**Hardening costs slightly less and stays tighter.** The skill-guided fix used a third
fewer steps, left the model instructions untouched so the accuracy figures stayed
comparable, added automated rules preventing the same mistake later, and caught one
affected path the unguided attempt missed.

## What we chose not to make a skill

A third candidate covered writing new test cases for the evaluation suite. We dropped it.

The test without the skill showed an assistant doing that job correctly unaided, because
the project's existing documentation already explains the rules. A skill there would have
added maintenance without adding reliability.

This is the honest limit of what these two skills claim. They do not rescue work that
would otherwise fail. They make the outcome consistent: the evaluation write-up keeps its
disclosures under deadline pressure, and a safety fix reaches every checkpoint without
disturbing the measurements. Where documentation already did that job, we left it alone.

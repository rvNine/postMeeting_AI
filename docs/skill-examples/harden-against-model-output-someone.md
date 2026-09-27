# Example output — `harden-against-model-output`

**Input (bug report):** "The notes said 'someone should chase the vendor invoice this
week'. The model came back with owner = 'someone' and the app let the manager straight
through to drafting. Same with owner = 'the team'. We ship tomorrow, keep it tight."

**Result:** `harden-against-model-output-someone.diff` in this directory — 12 files,
+47 offline tests, 312 passing, no API calls, no prompt change.

## The reproduction the skill asks for, at all three gate points

| | before the fix | after the fix |
|---|---|---|
| `run_review` gaps | `[]` | `[missing_owner on a1]` |
| `draft_blocked` | `False` | `True` |
| `run_draft` | drafted the message | `GateBlockedError` |

## The guard

`agent/schemas.py::normalize_owner` wraps `normalize_optional_text` rather than
re-implementing it, strips filler words, and returns `None` when every remaining word is
a generic category word. So "someone", "the team", "the whole team" and "the rest of the
team" all name nobody, while "Platform Team" and "Dan and Sam" survive.

It is applied at the structural backstop, `draft_blocked`, `run_draft`'s independent
re-check, the five owner paths in the review UI, the markdown export, and
`ui/context_builder.py`, so a legacy row cannot feed "someone" back in as memory.

## What the skill's constraints ruled out

- **A prompt edit.** The prompt already says "never guess" twice, and the model returned
  "someone" anyway, because it was copying the notes' own wording. `PROMPT_VERSION` is
  untouched, so the recorded eval numbers stay comparable.
- **Adding "someone" to `PLACEHOLDER_VALUES`.** That list is shared by every optional
  text field, and "someone has to own the release" is a legitimate decision rationale.
- **A new blank check.** `tests/test_layer_discipline.py` gains two locks: every
  owner-gating file must call `normalize_owner`, and none may gate an owner on
  `normalize_optional_text`.

## Known consequence, flagged rather than hidden

Rows already in the database with `owner = "someone"` now read as blank, so a meeting
that previously looked ready to draft will show a new blocking gap after deploy. That is
the intended behaviour.

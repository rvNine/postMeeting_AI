---
name: harden-against-model-output
description: Use when the Meeting Follow-up Agent accepts something the model returned that nobody confirmed — a placeholder or non-specific owner, an unverifiable triage quote, a downgraded gap severity — or when an eval run, bug report or review shows the draft gate opening on data a human never approved.
---

# Harden against a model output

The gate exists because the model cannot be trusted to leave a field blank. When a
model output slips past it, the fix goes in deterministic code, not in the prompt.
A stricter prompt lowers how often the bad output happens; it never stops it.

## Process

1. **Reproduce offline.** Queue the exact bad value on `StubLLMClient`
   (`tests/conftest.py`) and drive it through `run_review` → `draft_blocked` →
   `run_draft`. No API key, no cost. Report the reproduction as the gate's own verdict
   at each of the three points, not just "the test fails".
2. **Write the failing test first**, asserting the gate stays shut.
3. **Fix at the narrowest boundary that covers every path**, reusing what exists:
   - `agent/schemas.py::normalize_optional_text` — blank and placeholder text
     (`PLACEHOLDER_VALUES`: null, none, n/a, tbd, tbc, unknown, unassigned, todo, -, --, ?).
   - `agent/pipeline.py::quote_supports` — a model claim is believed only if its quote
     is verbatim in the notes.
   - `agent/pipeline.py::owner_gap_is_hopeless` — never ask the model to fill an owner
     the notes cannot supply.
   - `agent/gaps.py::BLOCKING_TYPES` — the taxonomy wins over the model's severity.
4. **Land it at every gate point, or the app contradicts itself:** the UI's
   `ui/gap_display.py::draft_blocked`, `run_draft`'s gap bookkeeping check, and
   `run_draft`'s independent re-check of the item data. A value can reach an
   `ActionItem` after validation (a human edit round-tripped through the UI), so a
   schema validator alone is not enough.
5. **Run `python3 -m pytest`.** Never `eval.run_eval` — that costs money, and a code
   guard needs no live model to prove.
6. **Document it:** a defect entry in `docs/ARCHITECTURE.md` (the numbered defect list
   and the model-failure table), a short subsection under "What the agent does not
   trust" in `README.md`, and synced test counts.

## Constraints

- **Never widen a shared list for a field-specific rule.** "someone" is not a valid
  owner but is fine in a deadline string or a rationale, so it belongs in an
  owner-specific predicate, not in `PLACEHOLDER_VALUES`.
- **Never write a new blank check.** `tests/test_layer_discipline.py` enforces that
  every layer shares one predicate; add to it or wrap it.
- **Keep the layer rules:** `agent/` imports neither `storage/` nor `streamlit`, and no
  module under `agent/` may read `owner_hints`.
- **Prefer a false block to a false pass.** Blocking asks a human; passing sends a
  follow-up naming someone who never agreed.
- **Bound the change.** Guard, tests, docs. A prompt edit is optional and secondary; if
  you make one, bump `PROMPT_VERSION` and state in the report that the new version is
  unscored until an eval run.

## Red flags

- "Just tell the model not to do that" → that is not the fix; write the guard.
- "The UI button is disabled now" → `run_draft` must refuse too.
- Adding the value to `PLACEHOLDER_VALUES` without checking deadlines and rationales.
- A new `if not value.strip()` anywhere → use the shared predicate.
- Claiming it's fixed without the stub reproduction re-run green.

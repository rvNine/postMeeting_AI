"""Scores the pipeline against the gold answers in fixtures/expected/.

Run manually: `python3 -m eval.run_eval`. Makes real API calls and costs money.
Matching is deliberately loose (token overlap) because the agent's wording will
never match the gold answer exactly; the point is whether the item was found.
"""
import json
import re

from agent.gaps import open_blocking
from agent.llm_client import OpenAILLMClient
from agent.loop import run_agent_loop
from agent.schemas import GapType, MeetingExtraction
from fixtures import loader

_MATCH_THRESHOLD = 0.5


def _overlap(a: str, b: str) -> float:
    a_words, b_words = set(a.lower().split()), set(b.lower().split())
    if not a_words:
        return 0.0
    return len(a_words & b_words) / len(a_words)


def _matches(expected_task: str, extracted_tasks: list[str]) -> bool:
    return any(_overlap(expected_task, t) >= _MATCH_THRESHOLD for t in extracted_tasks)


def _mentions(name: str, text: str) -> bool:
    """Case-insensitive, word-boundary containment. 'Sam' must not match 'Samantha'."""
    return re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE) is not None


def _fabricated_owners(extraction: MeetingExtraction, notes: str) -> list[str]:
    """P0: an owner that appears NOWHERE in the meeting notes was invented."""
    return [f"{i.owner!r} on {i.task!r}" for i in extraction.action_items
            if i.owner and not _mentions(i.owner, notes)]


def _unsupported_owners(extraction: MeetingExtraction) -> list[str]:
    """Softer signal: owner absent from its OWN source_quote — possible misattribution.

    Not a P0 on its own: quoting "she'd take the migration" while correctly resolving
    the owner to Priya is legitimate extraction, not invention.
    """
    return [f"{i.owner!r} on {i.task!r}" for i in extraction.action_items
            if i.owner and not _mentions(i.owner, i.source_quote or "")]


def score_fixture(expected: dict, extraction: MeetingExtraction, gaps: list,
                  notes: str = "", overall_confidence: float | None = None,
                  passes: int = 1) -> dict:
    extracted = [item.task for item in extraction.action_items]
    wanted = expected["expected_action_items"]

    found = sum(1 for w in wanted if _matches(w, extracted))
    recall = found / len(wanted) if wanted else 1.0

    legitimate = sum(1 for t in extracted
                     if any(_overlap(w, t) >= _MATCH_THRESHOLD for w in wanted))
    precision = legitimate / len(extracted) if extracted else 1.0

    # Score by the app's own definition of "blocking" (agent.gaps.open_blocking),
    # not a narrower local approximation: a model can emit a blocking-type gap
    # tagged WARNING, and the real gate still treats that as blocking. Reuse the
    # real function rather than reimplementing its rule here.
    blocking = open_blocking(gaps, set())
    expected_blocking = expected["expected_blocking_gap_count"]
    gap_recall = (min(len(blocking), expected_blocking) / expected_blocking
                  if expected_blocking else 1.0)

    fabricated_detail = _fabricated_owners(extraction, notes)
    unsupported_detail = _unsupported_owners(extraction)

    result = {"recall": round(recall, 2), "precision": round(precision, 2),
              "gap_recall": round(gap_recall, 2),
              "fabrications": len(fabricated_detail),
              "fabricated_detail": fabricated_detail,
              "unsupported_owners": len(unsupported_detail),
              "unsupported_detail": unsupported_detail,
              "extracted_count": len(extracted), "blocking_gaps": len(blocking),
              "passes": passes}

    if "must_not_extract" in expected:
        result["took_the_bait"] = [t for t in extracted
                                   if any(_overlap(bad, t) >= _MATCH_THRESHOLD
                                         for bad in expected["must_not_extract"])]

    if "expected_max_action_items" in expected:
        result["over_extracted"] = len(extracted) > expected["expected_max_action_items"]

    if "expected_conflicting_decision_count" in expected:
        conflict_gaps = [g for g in gaps if g.type is GapType.CONFLICTING_DECISION]
        result["conflict_gaps_found"] = len(conflict_gaps)

    if "expected_max_overall_confidence" in expected and overall_confidence is not None:
        result["confidence_ok"] = (overall_confidence
                                   <= expected["expected_max_overall_confidence"])

    return result


def pass2_gain(expected: dict, before: MeetingExtraction,
               after: MeetingExtraction) -> dict:
    """What the corrective pass actually bought, per fixture.

    Reported whether or not it is positive. A loop that costs a call and
    changes nothing is a finding, not something to omit.
    """
    wanted = expected["expected_action_items"]
    def _recall(extraction):
        extracted = [i.task for i in extraction.action_items]
        if not wanted:
            return 1.0
        return round(sum(1 for w in wanted if _matches(w, extracted)) / len(wanted), 2)
    before_r, after_r = _recall(before), _recall(after)
    return {"recall_before": before_r, "recall_after": after_r,
            "recall_delta": round(after_r - before_r, 2)}


def main() -> None:
    client = OpenAILLMClient()
    rows = []
    for sample in loader.list_samples():
        expected = loader.load_expected(sample["slug"])
        # Compare against the loop's OWN first pass. A separately-run extraction
        # varies run to run, so the "gain" would measure model variance rather
        # than the corrective pass — and could show one when no pass 2 ran.
        outcome = run_agent_loop(sample["notes"], client)
        gain = pass2_gain(expected, outcome.first_extraction, outcome.extraction)
        gaps = open_blocking(outcome.review.gaps, resolved_ids=set())
        score = score_fixture(expected, outcome.extraction, outcome.review.gaps,
                              notes=sample["notes"],
                              overall_confidence=outcome.review.overall_confidence,
                              passes=outcome.passes)
        score["slug"] = sample["slug"]
        score["open_blocking"] = len(gaps)
        score["pass2_gain"] = gain
        rows.append(score)
        print(json.dumps(score, indent=2))

    print("\n| Fixture | Recall | Precision | Gap recall | Fabrications | "
          "Unsupported | Took bait | Over-extracted | Conflict gaps | Confidence OK | "
          "Passes | Pass2 gain (recall) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        took_bait = ("yes" if row.get("took_the_bait") else
                     ("no" if "took_the_bait" in row else "-"))
        over_extracted = row.get("over_extracted", "-")
        conflict = row.get("conflict_gaps_found", "-")
        confidence_ok = row.get("confidence_ok", "-")
        gain = row["pass2_gain"]
        gain_str = f"{gain['recall_before']} -> {gain['recall_after']} ({gain['recall_delta']:+})"
        print(f"| {row['slug']} | {row['recall']} | {row['precision']} | "
              f"{row['gap_recall']} | {row['fabrications']} | {row['unsupported_owners']} | "
              f"{took_bait} | {over_extracted} | {conflict} | {confidence_ok} | "
              f"{row['passes']} | {gain_str} |")

    total_fabrications = sum(r["fabrications"] for r in rows)
    total_unsupported = sum(r["unsupported_owners"] for r in rows)
    print(f"\nTotal fabrications: {total_fabrications} (target: 0)")
    print(f"Total unsupported owners (soft signal, not a P0): {total_unsupported}")


if __name__ == "__main__":
    main()

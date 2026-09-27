"""Evidence-only prompt construction for meeting answers."""
from collections.abc import Sequence

from query.models import EvidenceItem


def build_answer_prompt(
    question: str,
    evidence: Sequence[EvidenceItem],
) -> tuple[str, str]:
    """Build a prompt whose context is exactly the retrieved evidence items."""
    system = (
        "You answer questions about technical meetings using only the supplied evidence. "
        "Do not use outside knowledge or infer unsupported facts. Return JSON matching "
        "AnswerDraft with status answered or not_found, an answer, and citation_ids. "
        "Use only the supplied citation IDs; return not_found with no citations when "
        "the evidence is insufficient."
    )
    labelled = []
    for item in evidence:
        labelled.append(
            f"[{item.citation_id}] meeting_id={item.meeting_id}; title={item.title}; "
            f"date={item.meeting_date}; chunk_id={item.chunk_id or 'record'}; "
            f"record_type={item.record_type or 'meeting'}; record_id={item.record_id or 'none'}; "
            f"relationship={item.relationship_label or 'none'}; quote={item.text_fragment}"
        )
    user = f"Question: {question.strip()}\n\nEvidence:\n" + (
        "\n".join(labelled) if labelled else "(none)"
    )
    return system, user

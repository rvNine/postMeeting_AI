"""Turns storage rows into the agent's MeetingContext.

This is the seam that keeps `agent/` free of `storage/`: memory queries return
plain dicts, and this module converts them into the frozen dataclasses the
agent consumes. No Streamlit here — it is pure translation and is unit-tested.
"""
from agent.schemas import MeetingContext, OwnerHint, PriorCommitment
from storage import memory


def build_context(conn, *, exclude_meeting_id: str) -> MeetingContext:
    """Assemble what the agent knows beyond today's notes.

    Memory is an enhancement, never a dependency: if either query fails, the
    caller gets an empty context and the loop runs exactly as it did before
    memory existed. An empty database yields the same result, which is also
    the first-meeting-ever case.
    """
    try:
        hints = tuple(
            OwnerHint(owner=row["owner"], times_assigned=row["times_assigned"],
                      example_task=row["example_task"])
            for row in memory.owner_hints(conn, exclude_meeting_id=exclude_meeting_id))
        commitments = tuple(
            PriorCommitment(task=row["task"], owner=row["owner"], deadline=row["deadline"],
                            meeting_title=row["meeting_title"],
                            meeting_date=row["meeting_date"])
            for row in memory.prior_commitments(conn, exclude_meeting_id=exclude_meeting_id))
    except Exception:
        return MeetingContext()
    return MeetingContext(prior_commitments=commitments, owner_hints=hints)

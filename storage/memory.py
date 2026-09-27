"""What the agent remembers across meetings.

Two queries over data the app already stores. Neither invents anything: both
read rows that a human's own actions produced.

Layer note: this module returns plain dicts. `agent/` never imports `storage/`,
so the caller in `ui/` turns these into the frozen dataclasses in
`agent.schemas` and passes those down.
"""
import sqlite3


def owner_hints(conn: sqlite3.Connection, *, exclude_meeting_id: str,
                limit: int = 10) -> list[dict]:
    """Owners a human supplied where the agent found none.

    `origin='agent' AND ai_owner IS NULL AND owner IS NOT NULL` is literally
    "the agent left this blank and a person filled it in" — the correction log
    the frozen ai_* columns were built to keep. Ordered by how often each owner
    was chosen, so the most established pattern surfaces first.

    NEVER send the result to a model. It is a suggestion for the manager.
    """
    rows = conn.execute(
        """
        SELECT owner,
               COUNT(*) AS times_assigned,
               MIN(task) AS example_task
          FROM action_items
         WHERE origin = 'agent'
           AND ai_owner IS NULL
           AND owner IS NOT NULL
           AND TRIM(owner) <> ''
           AND deleted = 0
           AND meeting_id <> ?
      GROUP BY owner
      ORDER BY times_assigned DESC, owner ASC
         LIMIT ?
        """,
        (exclude_meeting_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def prior_commitments(conn: sqlite3.Connection, *, exclude_meeting_id: str,
                      limit: int = 20) -> list[dict]:
    """Commitments from earlier meetings — task, owner and deadline the AGENT read.

    This is the one memory query whose rows reach a model, in the extraction
    prompt's BACKGROUND block, so it emits the FROZEN `ai_task`/`ai_owner`/
    `ai_deadline` columns — never the live `task`/`owner`/`deadline` columns,
    which `update_action_item` rewrites whenever a manager edits a row. The
    live columns can hold text a human typed after the agent ran: a corrected
    owner, a supplied deadline, an edited task. Selecting them would round-trip
    a human's own input back into a prompt no matter how the WHERE clause is
    gated — the WHERE only decides which rows qualify, the SELECT decides what
    those rows say, and the two must agree on that or the gate is cosmetic.

    The WHERE clause requires `ai_owner` AND `ai_deadline` both non-blank, so a
    "prior commitment" means exactly "the agent itself read both an owner and a
    deadline out of that meeting's notes" — never "a human filled either one
    in later" (that correction is `owner_hints`'s job, and never reaches a
    model) and never "a human supplied a deadline the agent lacked" (there is
    no compensating hint channel for that at all, so this query is the only
    guard). One inference away from either gap is the model copying a human's
    own text onto today's blank field and calling it confirmed — precisely the
    round-trip invariant 3 forbids.

    There is no completion tracking in v1, so this means "previously committed
    and never marked done here", NOT "verified still open". The prompt and the
    UI both say so; do not let a caller imply otherwise.
    """
    rows = conn.execute(
        """
        SELECT ai.ai_task     AS task,
               ai.ai_owner    AS owner,
               ai.ai_deadline AS deadline,
               m.title        AS meeting_title,
               m.meeting_date AS meeting_date
          FROM action_items ai
          JOIN meetings m ON m.id = ai.meeting_id
         WHERE ai.deleted = 0
           AND ai.ai_owner    IS NOT NULL AND TRIM(ai.ai_owner)    <> ''
           AND ai.ai_deadline IS NOT NULL AND TRIM(ai.ai_deadline) <> ''
           AND ai.meeting_id <> ?
      ORDER BY m.meeting_date DESC, ai.rowid ASC
         LIMIT ?
        """,
        (exclude_meeting_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]

# Module 3 — Technical Meeting Intelligence Subagent

## 1. Executive recommendation

The project should begin with **one specialized subagent**:

> **Technical Meeting Intelligence Subagent** — analyzes one meeting or related source bundle and produces an evidence-backed technical meeting record for human review.

The full future platform can contain three specialized agents:

1. **Meeting Evidence Agent** — extracts facts from one meeting, email thread, transcript, or document.
2. **Engineering Continuity Agent** — compares approved records across meetings and maintains continuity of decisions, actions, risks, and dependencies.
3. **Engineering Briefing Agent** — creates weekly summaries, roadmap reports, risk reports, and preparation briefs from approved records.

Only the first agent should be implemented for the Module 3 submission. The other two should be documented as the future architecture rather than implemented prematurely.

The project should not initially become an autonomous chief-of-staff system. Email integration, live conference access, audio transcription, task-tracker updates, roadmap changes, and IPR conclusions introduce separate systems, permissions, and safety concerns.

## 2. Assignment alignment

The assignment asks for a specialized worker with:

- A clear responsibility
- A bounded context
- Defined inputs and outputs
- A reason to use a subagent instead of a normal prompt or skill
- Calling conditions
- Tools and constraints
- A working package and tests

The Technical Meeting Intelligence Subagent satisfies this requirement because it performs a repeatable, context-heavy task independently while returning structured results for human approval.

## 3. Problem and users

Technical teams produce important information across meetings, notes, transcripts, email threads, design documents, and planning documents. The information is often lost because:

- Decisions are not recorded consistently.
- Action items have no confirmed owner or deadline.
- A later meeting contradicts an earlier decision.
- Risks and dependencies remain in discussion notes rather than becoming visible records.
- Roadmap changes are discussed but not connected to their reasons.
- Technical learnings are not preserved for future work.

The primary user is a technical lead, engineering manager, project manager, or specification lead who needs a reliable record of what was discussed and what requires follow-up.

The secondary users are meeting participants who need clear action items, decisions, and unresolved questions.

## 4. Why this needs a subagent

A normal prompt can summarize one piece of text, but it does not provide enough structure for this project. The specialized subagent is justified because it needs:

- A dedicated context boundary for technical meeting evidence
- A stable structured output contract
- Repeated operation for many meetings
- Evidence quotes for every important claim
- Self-review for missing or contradictory information
- A bounded retry or re-extraction step
- Persistent records for later continuity analysis
- A human approval gate before consequential information is accepted

A reusable skill would provide instructions, but it would not own the meeting-analysis loop, maintain the output contract, validate evidence, or coordinate with the project’s persistence and review flow. The subagent is the autonomous worker; the application remains responsible for orchestration, storage, permissions, and human approval.

## 5. Current MVP agent

### Technical Meeting Intelligence Subagent

### Responsibility

Analyze one source bundle and produce a structured technical meeting packet. The subagent extracts what the source explicitly supports, identifies uncertainty, and never invents owners, deadlines, decisions, or legal conclusions.

### Calling conditions

Call the subagent when:

- A user pastes meeting notes.
- A user uploads a transcript or Markdown meeting document.
- A user supplies a bounded collection of related email or document excerpts.
- A user asks to re-analyze a meeting after correcting the source or metadata.

The first implementation should use pasted notes or local fixture files. Email, document, and voice systems should be represented by adapters later, not required for the first demo.

### Input context

The subagent receives:

- Meeting title
- Meeting date and optional duration
- Meeting type, such as standup, design review, planning, incident review, or technical discussion
- Raw notes or transcript
- Optional participant list
- Optional project, system, or component name
- Optional approved prior decisions and commitments
- Source metadata, such as filename, email subject, document URL, or transcript timecode

Prior records are context only. They must not silently become facts about the current meeting.

### Output

The subagent returns a `TechnicalMeetingPacket` containing:

- Concise meeting summary
- Participants
- Decisions with evidence
- Action items with evidence
- Technical risks
- Dependencies and blockers
- Technical learnings
- Unresolved questions
- Contradictions or possible superseded decisions
- Confidence and evidence coverage
- Human-review gaps
- Processing metadata

## 6. Future three-agent platform

```text
Meeting notes, transcript, email, or document
                    |
                    v
        +----------------------------+
        | Meeting Evidence Agent     |
        | Analyze one source bundle  |
        +--------------+-------------+
                       |
                       v
              Human review and approval
                       |
                       v
        +----------------------------+
        | Engineering Continuity    |
        | Link approved records     |
        +--------------+-------------+
                       |
                       v
        +----------------------------+
        | Engineering Briefing      |
        | Produce useful briefs     |
        +--------------+-------------+
                       |
                       v
              Human review and action
```

### 6.1 Meeting Evidence Agent

This is the Module 3 MVP. It analyzes one source bundle and produces evidence-backed facts.

It may classify text, extract explicit facts, identify gaps, attach quotes, and request human clarification. It may not infer an unstated owner, invent a deadline, resolve a contradiction without evidence, or make a legal decision.

### 6.2 Engineering Continuity Agent

This future agent operates over approved historical packets.

Responsibilities:

- Link a current action to an earlier commitment.
- Identify whether a decision is new, repeated, changed, or superseded.
- Detect contradictions across meetings.
- Track unresolved questions and recurring blockers.
- Identify dependencies between teams, systems, and milestones.
- Detect changes in technical direction or roadmap priority.

Input:

- Approved meeting packets
- Approved decisions and actions
- Project and system metadata
- Human-confirmed status changes

Output:

- Decision history
- Action continuity records
- Risk and dependency relationships
- Contradiction alerts
- Roadmap-change signals

This agent should never mark an action as complete merely because it has not appeared recently. Completion requires explicit evidence or human confirmation.

### 6.3 Engineering Briefing Agent

This future agent creates human-readable outputs from approved records.

Responsibilities:

- Weekly engineering summary
- Open action report
- Decision register
- Risk and blocker report
- Roadmap-change summary
- Suggested agenda for the next meeting
- Questions requiring a technical lead’s decision

Input:

- Approved continuity records
- Selected date range
- Selected project, team, or system
- Requested brief type

Output:

- A concise report with links back to source evidence
- Clearly separated confirmed facts, unresolved issues, and suggestions
- No new commitments or decisions created without human approval

## 7. Use cases

### 7.1 Post-meeting analysis

Convert notes or a transcript into a consistent summary, decision list, action list, risk list, and unresolved-question list.

### 7.2 Technical decision register

Capture the selected approach, alternatives, rationale, trade-offs, affected systems, approval status, and supporting evidence.

### 7.3 Action and commitment tracking

Capture new actions, repeated commitments, dependencies, priority, owners, deadlines, and missing information.

### 7.4 Risk and issue detection

Identify delivery risks, technical risks, security concerns, compliance concerns, blockers, dependencies, and proposed mitigations.

### 7.5 Roadmap and planning analysis

Identify milestones, scope changes, priority changes, target dates, dependencies, and reasons for roadmap changes.

### 7.6 Technical learning extraction

Capture reusable lessons, failed approaches, validated practices, and follow-up experiments with supporting evidence.

### 7.7 Weekly engineering synthesis

Summarize open actions, repeated risks, unresolved decisions, contradictions, and changes in technical direction.

### 7.8 Meeting preparation

Generate an agenda based on open actions, unresolved questions, upcoming deadlines, and decisions requiring confirmation.

### 7.9 IPR-related candidate detection

The agent may identify a possible invention or technical contribution for human review. It must not decide patentability, ownership, novelty, inventorship, or legal status.

## 8. Data sources

### MVP sources

- Pasted meeting notes
- Local Markdown files
- Plain-text transcripts
- Manually supplied meeting metadata
- A small set of approved prior records

### Later sources

- Email threads, including subject, sender, recipients, timestamp, body, and attachments
- Design documents and architecture decision records
- Roadmap and planning documents
- Voice transcripts with speaker and timecode metadata
- Incident reports and issue records
- Human-entered status updates

Audio recording, live conference access, email sending, and automatic task creation are outside the MVP.

## 9. Variables to capture

### Source and provenance

- `source_id`
- `source_type`
- `source_title`
- `source_uri` or filename
- `created_at`
- `meeting_id`
- `source_quote`
- `source_location`, such as line, page, or timecode
- `source_confidence`

### Meeting metadata

- `meeting_title`
- `meeting_date`
- `meeting_type`
- `participants`
- `teams`
- `project`
- `system_or_component`
- `confidentiality`
- `retention_category`

### Decision fields

- `decision_id`
- `statement`
- `status`: proposed, approved, rejected, superseded, or unclear
- `rationale`
- `alternatives_considered`
- `tradeoffs`
- `consequences`
- `affected_systems`
- `decision_owner`
- `approval_date`
- `supersedes_decision_id`
- `confidence`
- `evidence_quote`

### Action fields

- `action_id`
- `task`
- `owner`
- `deadline`
- `priority`
- `status`: proposed, confirmed, blocked, completed, or unclear
- `dependency_ids`
- `source_meeting_id`
- `human_confirmed`
- `confidence`
- `evidence_quote`

Missing owners and deadlines remain `null` and create review gaps.

### Risk and dependency fields

- `risk_id`
- `description`
- `impact`
- `likelihood`
- `severity`
- `mitigation`
- `risk_owner`
- `trigger`
- `dependency_id`
- `depends_on`
- `blocked_by`
- `evidence_quote`

### Roadmap fields

- `initiative`
- `milestone`
- `target_date`
- `priority`
- `status`
- `change_type`
- `previous_value`
- `new_value`
- `change_reason`
- `dependency_ids`
- `approval_status`

### Learning fields

- `learning_id`
- `lesson`
- `technical_area`
- `evidence`
- `validation_status`
- `reusable_guidance`
- `follow_up_experiment`

### IPR candidate fields

- `candidate_title`
- `technical_contribution`
- `contributors_mentioned`
- `first_seen_date`
- `supporting_sources`
- `confidentiality`
- `human_review_status`

These fields describe a candidate signal only. They are not a legal assessment.

### Quality and audit fields

- `model`
- `prompt_version`
- `processing_pass`
- `confidence`
- `evidence_coverage`
- `review_status`
- `human_edits`
- `approved_at`
- `created_at`
- `raw_response_reference`

## 10. Autonomy and human intervention

### The agent may do independently

- Identify participants explicitly named in the source
- Summarize discussion
- Classify decisions, actions, risks, and background discussion
- Extract explicitly stated owners and deadlines
- Attach supporting evidence
- Flag missing, ambiguous, or contradictory information
- Decide whether a bounded corrective extraction pass may help
- Create a draft report

### A human must decide

- An unstated owner
- An unstated deadline
- Which side of a contradiction is authoritative
- Whether an action is complete
- Whether a roadmap change is approved
- Whether a risk is accepted
- Whether an IPR candidate is legally important
- Whether an external message or system update should be sent

The core safety rule is:

> The agent flags; it never fills.

The agent can suggest a question or display a previously used owner as a hint, but the human must explicitly confirm the value.

## 11. Supporting services versus agents

These are not separate agents in the MVP:

- Email ingestion is an input connector.
- Document parsing is an input adapter.
- Voice transcription is a preprocessing service.
- SQLite or another database is persistence.
- A scheduler is orchestration.
- Email sending is an outward-facing application service.
- A human-review screen is the approval boundary.

Calling every connector or formatter an agent would make the architecture unnecessarily complex and would weaken the assignment’s central specialization.

## 12. Suggested current-project mapping

The existing project already contains a useful meeting-follow-up foundation:

- `agent/pipeline.py` — extraction, review, triage, and draft flow
- `agent/loop.py` — bounded corrective pass
- `agent/schemas.py` — structured domain models and normalization
- `agent/gaps.py` — deterministic gap detection and gate rules
- `storage/` — SQLite persistence and historical context
- `ui/` — review and human approval flow
- `fixtures/` — offline sample meetings and expected results
- `tests/` — regression and layer-discipline coverage

The Module 3 implementation can specialize this foundation rather than creating an unrelated multi-agent system.

## 13. Recommended implementation phases

### Phase 1 — Module 3 MVP

Implement the Meeting Evidence Agent for pasted notes or local transcript files.

Output:

- Summary
- Decisions with evidence
- Action items with owner and deadline fields
- Risks and dependencies
- Learnings
- Unresolved questions
- Human-review gaps

Verification:

- Offline stub model tests
- Evidence quote tests
- Missing-owner and missing-deadline tests
- Contradiction tests
- Human-gate tests
- No fabricated owner or deadline tests

### Phase 2 — Approved technical record

Persist approved packets and retain the original AI values beside human edits. Add source references and processing metadata.

### Phase 3 — Engineering Continuity Agent

Compare approved packets across meetings. Add decision history, action continuity, recurring risk detection, and contradiction alerts.

### Phase 4 — Engineering Briefing Agent

Generate weekly summaries, decision registers, risk reports, and next-meeting agendas from approved records.

### Phase 5 — Input adapters

Add local email exports, document imports, and voice-transcript files. Keep each adapter separate from the reasoning agent.

### Phase 6 — IPR candidate review

Add candidate-signal extraction only after confidentiality, retention, access control, and human/legal review workflows are defined.

## 14. Out of scope for the first implementation

- Live conference recording
- Live transcription
- Automatic email ingestion
- Automatic email sending
- Calendar integration
- Jira, Linear, or Asana updates
- Multi-user authentication
- Multi-team memory isolation
- Automatic roadmap modification
- Automatic action completion
- Legal or patentability conclusions
- Sentiment analysis or employee performance scoring

## 15. Module 3 submission explanation

### What the subagent does

It reads a bounded technical meeting source bundle and creates an evidence-backed meeting packet containing decisions, actions, risks, dependencies, learnings, and unresolved questions.

### Why it is a subagent

The responsibility requires dedicated technical context, repeated operation, structured outputs, evidence checking, self-review, bounded corrective reasoning, and a human approval boundary. These requirements are broader than a single summarization prompt but narrower than a general-purpose autonomous assistant.

### When it is called

It is called after a user submits meeting notes, a local transcript, or a bounded source bundle for analysis.

### What context it receives

It receives the current source, meeting metadata, optional participant data, and optional approved historical context. Historical context is labeled as background and cannot silently override the current source.

### What it produces

It produces a structured technical meeting packet, evidence references, confidence values, and a list of gaps requiring human review.

### Success criteria

- A user can submit a local meeting note and receive a structured packet.
- Every extracted decision and action has supporting evidence.
- Missing owners and deadlines remain blank rather than guessed.
- Contradictions become visible review gaps.
- The system cannot produce an approved outward-facing draft while blocking gaps remain.
- The workflow runs offline in tests using a stub model.
- The package can be demonstrated with representative technical meeting fixtures.


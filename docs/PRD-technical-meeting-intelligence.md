# Product Requirements Document — Technical Meeting Intelligence Subagent

| Field | Value |
|---|---|
| Product | Technical Meeting Intelligence Subagent |
| Assignment | Module 3 — Build a Specialized Subagent |
| Version | 1.0 |
| Status | Draft for review |
| Date | 2026-09-24 |
| Implementation branch | `feat/module3-technical-meeting-intelligence` |
| Related assignment | [`assign/module3.txt`](../assign/module3.txt) |
| Related design | [`assign/module3-subagent-design.md`](../assign/module3-subagent-design.md) |
| Existing foundation | [`docs/PRD-meeting-followup-agent.md`](PRD-meeting-followup-agent.md) |

## 1. Product summary

The Technical Meeting Intelligence Subagent analyzes one technical meeting or bounded source bundle and produces an evidence-backed technical meeting packet for human review.

The packet turns unstructured notes, transcripts, or related document excerpts into:

- A concise meeting summary
- Technical decisions with supporting evidence
- Action items with owners and deadlines when explicitly stated
- Risks, dependencies, and blockers
- Technical learnings
- Unresolved questions and contradictions
- Human-review gaps

The Module 3 implementation will contain one specialized subagent. A future platform may add two more subagents for cross-meeting continuity and engineering brief generation, but those are not part of the first implementation.

## 2. Problem statement

Technical teams exchange important information through meetings, notes, transcripts, email, design documents, and planning documents. That information is difficult to manage consistently because:

- Decisions are recorded in different formats or not recorded at all.
- Action items lack confirmed owners or deadlines.
- Important dependencies and risks remain hidden in discussion text.
- Later meetings can contradict earlier decisions.
- Roadmap changes are discussed without preserving their rationale.
- Technical learnings are not available when similar work begins again.

The result is lost context, repeated discussion, missed follow-up, and decisions that cannot be traced back to evidence.

## 3. Users

### Primary user

Technical leads, engineering managers, project managers, and specification leaders who need a reliable record of technical meetings.

### Secondary users

Meeting participants who need clear decisions, actions, risks, dependencies, and unresolved questions after a meeting.

### Non-users for the MVP

- Automated email recipients
- External customers
- Legal or patent reviewers
- Task-tracker users
- Multi-team administrators

The first prototype is a local, single-user workflow. Multi-user authentication and team-level permissions are outside the MVP.

## 4. Product goals

### Primary goals

1. Convert a technical meeting source into a consistent structured record.
2. Preserve evidence for every important extracted decision and action.
3. Detect missing owners, missing deadlines, ambiguity, and contradictions.
4. Prevent the system from inventing consequential information.
5. Give a human a clear review and approval point.
6. Provide a demonstrable specialized subagent package with tests.

### Secondary goals

1. Preserve approved records for future cross-meeting analysis.
2. Establish a data model that can later support continuity and briefing agents.
3. Measure extraction quality using representative technical meeting fixtures.

### Non-goals

- Replacing a technical lead’s judgment
- Automatically assigning work
- Automatically accepting roadmap changes
- Automatically sending email
- Making legal or IPR determinations
- Building a general-purpose company knowledge assistant

## 5. Why this is a subagent

The subagent has a bounded responsibility, dedicated technical context, a structured output contract, and a repeatable reasoning loop. It performs more than simple summarization because it must:

- Classify decisions, actions, risks, dependencies, and background discussion.
- Attach evidence quotes to extracted claims.
- Review its own output for gaps and contradictions.
- Decide whether one bounded corrective extraction pass may help.
- Preserve uncertain values as `null` rather than guessing.
- Produce a human-reviewable result for persistence and later analysis.

A normal prompt could generate prose, but it would not reliably enforce the schema, evidence requirement, bounded retry behavior, or human gate. A reusable skill could describe the method, but it would not own the execution contract or return a structured packet to the application.

## 6. MVP agent definition

### Agent name

**Technical Meeting Intelligence Subagent**

### Responsibility

Analyze one meeting or bounded source bundle and produce a structured technical meeting packet supported by source evidence.

### Calling conditions

Call the subagent when:

- A user pastes technical meeting notes.
- A user uploads a local Markdown or plain-text transcript.
- A user supplies selected excerpts from related email or design documents.
- A user asks to re-analyze a meeting after correcting source text or metadata.

The MVP will use pasted notes and local fixture files. Email, document, and voice integrations will be added only as later input adapters.

### Input context

The agent receives:

- Meeting title
- Meeting date
- Optional duration
- Meeting type
- Raw notes or transcript
- Optional participant list
- Optional project, team, system, or component
- Optional approved prior decisions and commitments
- Source metadata such as filename, URL, email subject, page, line, or timecode

Historical context is background only. It cannot silently become a fact about the current meeting.

### Output

The agent returns a `TechnicalMeetingPacket` with:

- Summary
- Participants
- Decisions with source evidence
- Action items with source evidence
- Risks
- Dependencies and blockers
- Technical learnings
- Unresolved questions
- Contradictions or possible superseded decisions
- Confidence and evidence coverage
- Human-review gaps
- Processing and audit metadata

## 7. User journey

1. The user pastes meeting notes or selects a local transcript fixture.
2. The user supplies an optional title, date, meeting type, and project.
3. The user selects **Analyze**.
4. The agent extracts the meeting packet.
5. The agent reviews its extraction and performs at most one corrective pass when the source itself contains evidence that was missed.
6. The system displays decisions, actions, risks, dependencies, learnings, and gaps.
7. The user confirms, edits, adds, or deletes extracted records.
8. The system preserves the original AI values beside human-edited values.
9. The user approves the technical meeting packet.
10. The approved packet becomes available for later continuity analysis.

No external message is sent automatically.

## 8. Functional requirements

| ID | Requirement | Acceptance criterion |
|---|---|---|
| F1 | Accept meeting notes | A user can submit pasted notes or a local text/Markdown fixture. |
| F2 | Accept meeting metadata | Title, date, meeting type, project, and participants can be supplied or left optional. |
| F3 | Generate summary | The system displays a concise summary grounded in the submitted source. |
| F4 | Extract decisions | Each decision includes a statement, status, confidence, and supporting evidence. |
| F5 | Extract action items | Each action includes task, owner, deadline, status, confidence, and supporting evidence. |
| F6 | Detect missing owners | An action without an explicitly stated owner remains `null` and creates a blocking review gap. |
| F7 | Detect missing deadlines | An action without an explicitly stated deadline remains `null` and creates a blocking review gap when the workflow requires a deadline. |
| F8 | Detect ambiguity | Vague tasks, unresolved questions, and uncertain interpretations are displayed as review gaps. |
| F9 | Detect contradictions | Conflicting decisions or later superseding statements are flagged rather than silently merged. |
| F10 | Extract risks | The system displays technical or delivery risks with evidence, severity, and possible mitigation when stated. |
| F11 | Extract dependencies | The system displays dependencies between teams, systems, actions, and milestones when stated. |
| F12 | Extract learnings | The system displays technical lessons or follow-up experiments with evidence. |
| F13 | Bounded corrective pass | The agent may perform at most one corrective extraction pass when the source contains evidence supporting a flagged gap. |
| F14 | Preserve evidence | Every decision, action, risk, dependency, and learning includes a source quote or an explicit missing-evidence gap. |
| F15 | Human editing | The user can edit, add, or delete extracted records before approval. |
| F16 | Preserve AI values | The original AI values remain available beside human-edited values for audit. |
| F17 | Human approval gate | The packet cannot become approved while blocking gaps remain unresolved. |
| F18 | Preserve audit metadata | Model, prompt version, processing pass, confidence, and review status are recorded. |
| F19 | Offline testability | Tests use a stub model and do not require network access or billable model calls. |
| F20 | Demonstrable package | A reviewer can run the local prototype and inspect representative technical meeting examples. |

## 9. Data model

### 9.1 Source and provenance

- `source_id`
- `source_type`
- `source_title`
- `source_uri` or filename
- `created_at`
- `meeting_id`
- `source_quote`
- `source_location`, such as page, line, or transcript timecode
- `source_confidence`

### 9.2 Meeting metadata

- `meeting_title`
- `meeting_date`
- `meeting_type`
- `participants`
- `teams`
- `project`
- `system_or_component`
- `confidentiality`
- `retention_category`

### 9.3 Decision

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

### 9.4 Action item

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

Missing owners and deadlines remain `null`; they are never filled from assumptions, historical frequency, or model confidence.

### 9.5 Risk and dependency

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

### 9.6 Roadmap signal

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

Roadmap signals are suggestions for human review, not automatic roadmap modifications.

### 9.7 Technical learning

- `learning_id`
- `lesson`
- `technical_area`
- `evidence`
- `validation_status`
- `reusable_guidance`
- `follow_up_experiment`

### 9.8 IPR candidate signal

- `candidate_title`
- `technical_contribution`
- `contributors_mentioned`
- `first_seen_date`
- `supporting_sources`
- `confidentiality`
- `human_review_status`

IPR fields represent a candidate signal only. They do not represent legal advice, patentability, ownership, novelty, or inventorship decisions.

### 9.9 Quality and audit metadata

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

## 10. Agent behavior

### 10.1 Observe

Read the current source bundle, metadata, and optional approved historical context.

### 10.2 Extract

Create a structured packet containing only claims supported by the source or clearly marked as uncertain.

### 10.3 Review

Re-read the source and extraction. Detect missing owners, deadlines, evidence, ambiguity, contradictions, and unsupported claims.

### 10.4 Decide whether to retry

For each gap, determine whether the submitted source already contains evidence that could resolve it. A corrective pass is allowed only when the source itself supports the correction and the bounded pass budget remains.

### 10.5 Human handoff

Present unresolved gaps to the user. The user must confirm consequential fields before approval.

### 10.6 Approval

Persist the approved packet, original AI values, human edits, evidence references, and approval metadata.

## 11. Autonomy boundary

### Agent may do independently

- Identify explicitly named participants.
- Summarize discussion.
- Classify decisions, actions, risks, dependencies, and background discussion.
- Extract explicitly stated owners and deadlines.
- Attach supporting evidence.
- Flag missing, ambiguous, or contradictory information.
- Perform one bounded corrective extraction pass.
- Create a draft technical meeting packet.

### Human must decide

- An unstated owner.
- An unstated deadline.
- Which side of a contradiction is authoritative.
- Whether an action is complete.
- Whether a roadmap change is approved.
- Whether a risk is accepted.
- Whether an IPR candidate is legally important.
- Whether an external message or system update should be sent.

Core rule:

> The agent flags; it never fills.

## 12. System architecture

### MVP flow

```text
User notes or local transcript
              |
              v
       Input normalization
              |
              v
    Technical Meeting Intelligence
       extract -> review -> triage
              |
              v
       Deterministic gap checks
              |
              v
       Human review and editing
              |
              v
       Approved packet storage
```

### Existing-project mapping

The implementation should reuse the current project boundaries:

- `agent/pipeline.py` — extraction, review, triage, and draft logic
- `agent/loop.py` — bounded corrective pass
- `agent/schemas.py` — structured models and optional-text normalization
- `agent/gaps.py` — deterministic gap detection and approval gate
- `storage/` — SQLite persistence and historical context
- `ui/` — review and human approval flow
- `fixtures/` — offline meeting examples and expected outputs
- `tests/` — regression, schema, gate, and architecture tests

Email ingestion, document parsing, and voice transcription are input adapters, not additional reasoning agents.

## 13. Future three-agent architecture

### 13.1 Meeting Evidence Agent

Analyzes one meeting, email thread, transcript, or document and creates an evidence-backed packet. This is the only agent required for Module 3.

### 13.2 Engineering Continuity Agent

Operates over approved packets to:

- Link current actions to earlier commitments.
- Track decision history.
- Identify changed or superseded decisions.
- Detect contradictions across meetings.
- Track unresolved questions and recurring blockers.
- Identify dependencies across teams, systems, and milestones.
- Detect technical-direction or roadmap-priority changes.

It must not mark an action complete merely because the action disappeared from later notes. Completion requires explicit evidence or human confirmation.

### 13.3 Engineering Briefing Agent

Creates human-readable outputs from approved continuity records:

- Weekly engineering summary
- Open action report
- Decision register
- Risk and blocker report
- Roadmap-change summary
- Suggested next-meeting agenda
- Questions requiring a technical lead’s decision

It must distinguish confirmed facts, unresolved issues, and suggestions, and it must not create new commitments without human approval.

## 14. Input sources

### MVP

- Pasted meeting notes
- Local Markdown files
- Plain-text transcripts
- Manually supplied metadata
- A small set of approved prior records

### Later

- Email threads with subject, participants, timestamps, body, and attachments
- Design documents and architecture decision records
- Roadmap and planning documents
- Voice transcripts with speaker and timecode metadata
- Incident reports and issue records
- Human-entered status updates

The first implementation does not require recording, live transcription, email sending, or automatic task creation.

## 15. Supporting services that are not agents

- Email ingestion — input connector
- Document parsing — input adapter
- Voice transcription — preprocessing service
- SQLite — persistence
- Scheduler — orchestration
- Email sending — outward-facing application service
- Human-review UI — approval boundary

Treating every connector, formatter, or database operation as an agent would create unnecessary complexity and weaken the specialized responsibility.

## 16. Privacy and safety requirements

1. Do not send owner hints to the model as facts.
2. Do not infer owners or deadlines from historical frequency.
3. Keep source evidence beside extracted claims.
4. Preserve original AI values beside human edits.
5. Do not expose unrelated historical records in the current prompt.
6. Mark prior commitments as background, not current-meeting facts.
7. Do not make IPR, ownership, novelty, or patentability determinations.
8. Do not send email or update external systems automatically.
9. Do not treat an absent action as completed.
10. Keep tests offline and do not persist API keys or sensitive credentials.

## 17. Success metrics

| Metric | Initial target | Measurement |
|---|---|---|
| Action-item recall | At least 90% on representative fixtures | Human-scored fixture comparison |
| Decision extraction precision | At least 90% | Human review against fixture truth |
| Fabricated owners | 0 | Regression test and manual review |
| Fabricated deadlines | 0 | Regression test and manual review |
| Evidence coverage | 100% for decisions and actions | Schema and fixture validation |
| Blocking-gap gate integrity | 0 ungated approvals | Unit and integration tests |
| Corrective-pass bound | Never more than one retry in MVP | Loop test |
| Local analysis latency | Under 20 seconds for a 1,500-word note when using a live model | Instrumented demo |
| Human review time | Under 3 minutes for a normal fixture | Timed walkthrough |

The metrics are prototype targets, not production service-level agreements.

## 18. Testing requirements

### Unit tests

- Schema validation
- Optional text normalization
- Evidence quote matching
- Missing-owner detection
- Missing-deadline detection
- Contradiction and ambiguity detection
- Confidence bounds
- Gap severity and blocking behavior

### Agent-loop tests

- Clean meeting requires no corrective pass.
- A self-resolvable gap may trigger one corrective pass.
- A human-only gap does not trigger a corrective pass.
- The loop never exceeds the pass budget.
- A failed review degrades to deterministic gap detection.
- A failed model call cannot silently open the approval gate.

### Human-gate tests

- Draft or approval remains blocked with an unresolved blocking gap.
- Blank, whitespace, and placeholder owner/deadline values remain blocking.
- Resolved bookkeeping cannot bypass direct field validation.
- Human edits are preserved beside frozen AI values.

### Fixture tests

Fixtures should cover:

1. Clean technical design review
2. Missing owner and deadline
3. Conflicting technical decisions
4. Noisy transcript with unrelated discussion
5. Sparse meeting with unresolved questions
6. Roadmap change with an explicit rationale
7. Risk and dependency discussion

Tests must use a stub model. Real API evaluation is optional and must be explicitly authorized because it can incur cost.

## 19. Phased delivery

### Phase 1 — Module 3 MVP

Implement the Meeting Evidence Agent for pasted notes and local transcript fixtures.

Deliver:

- Structured technical meeting packet
- Evidence-backed decisions and actions
- Risks, dependencies, learnings, and questions
- Human-review gaps
- Offline tests
- Demonstration fixtures

### Phase 2 — Approved technical records

Persist approved packets, source references, processing metadata, and AI-versus-human differences.

### Phase 3 — Engineering Continuity Agent

Add cross-meeting decision history, action continuity, recurring risks, dependencies, and contradiction alerts.

### Phase 4 — Engineering Briefing Agent

Add weekly summaries, decision registers, risk reports, roadmap-change reports, and next-meeting agendas.

### Phase 5 — Input adapters

Add local email exports, document imports, and voice-transcript files without changing the reasoning boundary.

### Phase 6 — IPR candidate review

Add candidate-signal extraction only after confidentiality, retention, access control, and human/legal review workflows are defined.

## 20. Out of scope for MVP

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
- Sentiment analysis
- Employee performance scoring

## 21. Module 3 submission explanation

### What the subagent does

It reads a bounded technical meeting source bundle and creates an evidence-backed packet containing decisions, actions, risks, dependencies, learnings, and unresolved questions.

### Why it needs independent operation

It requires dedicated technical context, structured output validation, evidence checking, self-review, bounded corrective reasoning, and a human approval boundary. That is more than a single summarization prompt but narrower and more testable than a general-purpose assistant.

### When it is called

It is called when the user submits meeting notes, a local transcript, or a bounded source bundle for analysis.

### Context it receives

It receives the current source, meeting metadata, optional participant data, source provenance, and optional approved historical context. Historical context is labeled as background and cannot silently override the current source.

### What it produces

It produces a structured technical meeting packet, evidence references, confidence values, processing metadata, and a list of gaps requiring human review.

### Completion criteria

- A user can submit a local technical meeting note and receive a structured packet.
- Every extracted decision and action has supporting evidence.
- Missing owners and deadlines remain blank rather than guessed.
- Contradictions become visible review gaps.
- Approval remains blocked while blocking gaps remain open.
- Human edits are preserved beside original AI values.
- The workflow runs offline in tests using a stub model.
- The package can be demonstrated with representative technical meeting fixtures.


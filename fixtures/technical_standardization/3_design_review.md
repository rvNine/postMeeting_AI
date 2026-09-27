---
slug: design-review
meeting_id: fx-design-review
fixture_set: latticebridge-v1
program_name: LatticeBridge
program_phase: design
meeting_sequence: 3
meeting_date: 2026-09-09
title: Event envelope design and decision review
facilitator: Nia Sol
source_type: meeting_notes
participants: Nia Sol (platform lead), Theo Quill (standards lead), Ivo Lane (runtime lead), Uma Reed (security lead), Oren Pike (quality lead)
---

# Event envelope design and decision review

Decision: Use explicit `schema_rev` and `sent_at` fields. Rationale: The pilot needs deterministic replay and version negotiation.

Decision: Reject the short `v` field name. Rationale: It was ambiguous in logs and hard to search.

Nia Sol completed adding schema revision examples to the contract on 2026-09-11.

Risk: Ambiguous field names may create incompatible implementations. Impact: Rework and unclear support tickets. Likelihood: medium. Severity: medium. Mitigation: Reject shorthand and publish examples. Owner: Theo Quill.

Dependency: Contract examples depend on the agreed field names. Depends on: Vocabulary decision. Blocked by: None. Owner: Nia Sol.

Learning: Explicit revision fields are easier to replay than inferred versions. Technical area: schema evolution. Validation status: validated by contract examples. Follow-up experiment: Compare replay diagnostics for inferred vs explicit versions.

This design review reviews the identified protocol gaps.

---
slug: interoperability
meeting_id: fx-interoperability
fixture_set: latticebridge-v1
program_name: LatticeBridge
program_phase: compatibility
meeting_sequence: 4
meeting_date: 2026-09-12
title: Interoperability and compatibility review
facilitator: Oren Pike
source_type: transcript
participants: Oren Pike (quality lead), Ivo Lane (runtime lead), Sia Moss (client lead), Nia Sol (platform lead)
---

# Interoperability and compatibility review

Decision: Support schema revisions 1 and 2 during the compatibility window. Rationale: Client teams need one release cycle to migrate.

Sia Moss completed running compatibility tests against schema revisions 1 and 2 on 2026-09-16.

The open action is to confirm the QuartzRelay adapter migration owner; it intentionally has no owner or deadline.

Risk: A revision-1 client may retry a revision-2 payload incorrectly. Impact: Duplicate events. Likelihood: high. Severity: high. Mitigation: Keep dual-read compatibility and test retries. Owner: Sia Moss.

Dependency: Dual-revision support depends on client test fixtures. Depends on: Client fixtures. Blocked by: Missing QuartzRelay owner. Owner: Sia Moss.

Learning: Dual-read support reduces migration coordination cost. Technical area: compatibility. Validation status: partially validated. Follow-up experiment: Test a third fictional client with delayed migration.

Compatibility work implements the envelope decision. This review is related to migration risk.

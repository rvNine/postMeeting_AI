# Architecture sync — 2026-09-10
Present: Dan, Sam, Priya

Dan walked through the queue options.

Decision: we are going with RabbitMQ for the event bus. Dan will set up a
proof of concept by 18 September.

[... 20 minutes of unrelated discussion about the staging environment ...]

Sam raised the operational cost of running RabbitMQ ourselves. After going back
and forth, we said let's just use SQS instead and revisit in six months.

Priya to update the ADR by 20 September.

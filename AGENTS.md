# Hardware Validation Lab workflow

Read this file and docs/STATUS.md before continuation; then docs/PLAN.md and relevant implementation.

- Canonical roadmap: docs/PLAN.md, reconciled 2026-11-03; docs/REQUIREMENTS.md is its coverage/evidence checklist. Original/PDF milestone numbers are historical; use PLAN's crosswalk.
- Active scope: M2B.4 local durable journal/spool/reconciliation implemented on codex/m2b.4-durable-agent-journal, at review. Read docs/M2B_4.md and STATUS. Stop before M2B.5; no backend dispatch, SQL Attempts/leases, actual upload ACK or physical execution is enabled.
- M2B has eight tasks in docs/M2B.md. .1-.4 are locally implemented with recorded limits; .5-.8 are planned. New continuation starts .5 only after review, not the remaining milestone.
- Preserve work; inspect Git status first. Feature branch: codex/m2b.4-durable-agent-journal; main baseline b6ba0b3 is unchanged. User has now explicitly approved merging M2B.4 and starting M2B.5 on a separate branch; later merges still require approval. No automatic commits/pushes/merge/publication/external accounts/spending/host security changes; M2B.3 approval does not carry over.
- No additional agents unless the user requests them. GitHub origin: https://github.com/aladinle/hardware_validation_lab.git. Use verified TLS; per-command Windows schannel works without changing host trust settings.
- Django server templates and minimal JavaScript; SQLite is quick-start only. PostgreSQL is integration authority. Never claim PostgreSQL scheduling correctness from SQLite tests.
- Keep Django ORM/migrations/auth; do not migrate to FastAPI/SQLAlchemy/Alembic to match the PDF. Add typed v1 API/contracts and native agent packages incrementally. PDF execution_id maps to Attempt ID; use PLAN's canonical lifecycle/outcome/evaluation mapping.
- Invite-only accounts; project roles and explicit grants; deny by default; scope both list and direct object access. Use Django sessions, password validation, CSRF and ORM transactions. Security mutations must create audit events.
- No fake results, Apple affiliation/certification, or claims about hardware we lack. Catalog records do not mean connected hardware. No device execution in M1.
- CAN payload file comparison is the first meaningful simulator plugin (M2B), not physical capture. Core CI/reporting is M4, physical/Unix work M5, Celery/RabbitMQ M6A, telemetry/diagnostics/C++ M6B, events/Kubernetes/Snowflake M7. Every individual gate (including M2A/M2B/M3C/M6A/M6B) stops for review; do not bundle subsequent gates into "continue."
- A heartbeat/lease timeout never establishes stopped hardware. Quarantine stays unavailable; require confirmed termination/readiness before reuse. Add an outbox at the first SQL-to-broker boundary, not only when Kafka arrives.
- Use a project virtual environment. Do not install privileged host components. Secrets belong in environment/private ignored runtime files, never Git or logs.
- Required M0/M1 checks: fresh migrations, migration drift, Django system checks, dependency consistency, direct HTTP permission/security tests, real desktop/phone browser review if available. Record actual results and limitations in docs/STATUS.md.
- Required future checks are the active gate in PLAN plus mapped REQUIREMENTS items. M2A needs actual PostgreSQL/idempotency/restart tests, not SQLite. Configuration/local equivalents do not prove hosted CI, real hardware or external integrations. Documentation-only reconciliation uses link/coverage/consistency checks; do not relabel earlier application tests as rerun.
- Finish by documenting scope, commands/results, changed files, next exact action, limitations, five-minute demo and three interview exercises. Do not advance a milestone without the user saying to continue.

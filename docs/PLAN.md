# Unified implementation plan

Reconciled 2026-11-03. Project name: **Hardware Validation Lab**. LabFlow is the contributing PDF's title, not a second application. This is the single current roadmap. [REQUIREMENTS.md](REQUIREMENTS.md) is its coverage checklist; [STATUS.md](STATUS.md) records actual evidence. Architecture/security/decisions explain the design, not competing milestones.

## Sources, scope and current authorization

Combine the original user brief (sections 1-8) with LabFlow Detailed Implementation Plan (18 pages, planning version 1.0, 2026-11-03). Preserve the original Django stack, four human roles, project isolation, hardware safety and later technology portfolio. Add the PDF's CAN comparison, versioned API, durable submissions, agent journal/reconciliation, CI CLI/reporting, schedules and measurable failure-injection gates. Its copy-ready prompt is reference material, not separate implementation authority.

**The user authorized M2B.4 on its own feature branch; merge requires explicit user approval. M2A and M2B.1-.4 are implemented locally with recorded limits. Preserve existing work; M2B.5 and later need a new continuation.** A request to continue means the next individual gate below, not the remaining roadmap. No automatic commits/pushes/merges, remote creation, publication, purchases, external accounts, privileged installs, security changes or extra agents.

Initial target: one lab, one or two stations, one device per job, independent parallel jobs, desktop and phone browsers. Projects remain authorization boundaries within a lab. Coordinated multi-device work is retained for its own later gate. No Apple affiliation/certification or validation on unavailable Mac hardware. No shared human credentials, invented results or claimed physical validation from simulation.

## Stack and structure

- Retain modular Django, its ORM/migrations/auth/sessions/forms/CSRF, server templates and responsive CSS. Add typed/versioned JSON contracts; minimal JavaScript polling precedes live streaming. Do not add FastAPI/SQLAlchemy/Alembic, duplicate auth, a mandatory HTMX dependency or an SPA merely to match the PDF literally. FastAPI-specific proficiency is not claimed.
- PostgreSQL is authoritative for platform users/grants/execution/scheduling. SQLite remains an explicit quick start; the separate agent may use SQLite for its local journal. Neither proves PostgreSQL locking. Supply Compose and non-container setup; detect prerequisites without silently installing/starting privileged components.
- Backend/scheduler/workers target Linux/WSL2; native Windows Python agents handle Windows-attached hardware. USB availability in WSL/containers is never assumed. Compose gains web/API and scheduler with persistent PostgreSQL/artifact volumes in M2A/M2B; current Compose has PostgreSQL only.
- Preserve `web/`, `tests/`, `docs/`, `deploy/`, `scripts/`. Add `contracts/`, `agent/`, `workloads/`, `cli/`, `examples/` as used. Scheduler is a separate process in the same modular codebase. Never execute hardware in HTTP workers. Add pyproject metadata when packages become installable and retain one authoritative compatible lock. Keep Django tests; add pytest/fixtures for plugin/agent logic where useful, not a forced rewrite.
- GitLab is the first CI design; CLI/API stay provider-independent. No remote is assumed/created. A later explicit GitHub-only requirement can replace the first adapter without a mirror or two CI systems. CI configuration/local equivalents are not hosted execution evidence.
- Celery/RabbitMQ, InfluxDB, MongoDB, C++, Kafka, Kubernetes and Snowflake remain required later portfolio gates, not simulator-MVP prerequisites. Optional Compose profiles isolate extra services. External integration stays disabled without credentials/budget authorization.
- Verify official compatibility/security guidance and pin dependencies when each technology is introduced. Existing version records are historical, not a promise that their patches remain current.

## Common execution contracts

### Access and product behavior

Human roles remain Administrator, Test Engineer, Operator, Viewer, project-scoped except platform administrators. Administrators manage users/grants/approvals/devices/audits. Engineers author project drafts and run approved published versions with explicit test/device access. Operators run specifically granted approved tests on specifically granted devices. Viewers read authorized dashboards/results only. Engineers/operators may request cancellation of their own permitted work; administrators may cancel all in their scope. CI principals are distinct scoped service identities, not shared human accounts.

Check active account/principal, active membership/scope, action, explicit test grant, approved immutable version and device grant at submission and immediately before dispatch. Validate every batch item before creating any jobs; reject the whole unauthorized submission with a scoped useful error. Later authorized execution can have partial outcomes. Revocation blocks new requests/dispatch and requests safe checkpoint cancellation of running work, retaining attribution. Logout alone does not revoke permissions or cancel submitted jobs. Apply the same rules to URLs/forms/APIs/exports/artifacts. Any role preview must be explicitly labeled and must not change real backend authority.

Keep the approved light/navy/blue dashboard: Overview, Devices, Test Catalog, Test Runs, Results, Users & Roles, Audit Log. Desktop shows connected/running counts, authorized device selection, individual progress, batch summary, discovery notifications and recent results. Phone shows My Lab, permitted tests, compatible available devices, active work, failure details, authorized evidence download/cancel. Tables become cards without horizontal overflow. Include accessible labels, keyboard/focus behavior, status text plus color, empty/loading/error/stale states. Hide unauthorized records; disabled reasons only when their existence may be revealed. A catalog record is not connected hardware; uploaded CAN files are not physical capture; snapshots are not execution evidence.

### Models, identities and immutable history

Retain/add Project, Membership, TestDefinition, immutable TestVersion, TestApproval, TestGrant, Agent, Device, DeviceGrant, Job, Run, Attempt, Batch, Resource, Reservation/Lease, Measurement, Artifact, AuditEvent. Add ServicePrincipal/ServiceToken, local AgentJournal, ExecutionEvent, Schedule/Occurrence and later Outbox/ConsumerCheckpoint/ExportCheckpoint as needed. Map PDF `execution_id` to globally unique **Attempt ID**. Job is durable requested work; Run is the logical run; each actual attempt/rerun gets a new execution ID. Delivery retries reuse the existing ID. Preserve rerun lineage and original failure.

Freeze test/plugin version and package digest, approved schema, requester, explicit input roles/checksums, parameters/config, actual/simulated source, actual environment, device identity/hardware revision/firmware, known Git commit, agent version, timestamps/outcomes/evidence. Unknown remains unknown; yesterday's firmware is not derived from today's inventory. Use UTC-aware storage and local-time display. Index queue state/time, owner, device/start and execution-artifact links; tune observed queries. Bulk bounded logs belong in artifacts, not unbounded SQL fields.

Requester-scoped unique idempotency key plus canonical request hash: same key/body returns original Job; changed body conflicts (409). Foreign keys and constraints enforce history/ownership and at most one active exclusive allocation/resource. Artifact/result identity and checksums make exact replay safe; conflicting content is rejected, never overwritten. A deliberate rerun uses a new key/attempt with lineage.

### Lifecycle and ownership

Canonical lifecycle: `queued -> reserved -> preparing -> running -> collecting -> completed`; cancellation is requested/acknowledged/termination-confirmed before terminal `cancelled`. PDF ASSIGNED maps to `reserved`. Outcomes retain `PASS, FAIL, ERROR, TIMEOUT, CANCELLED`, with `evaluation_status` (`evaluated`/`not_evaluated`) and explicit reason/timeout category. PDF NOT_EVALUATED maps to evaluation status, not a false PASS. Assertion mismatch is FAIL; crash/broken fixture is ERROR; runner deadline is TIMEOUT (infrastructure class). A product deadline is FAIL only when an approved assertion defines it. Cleanup/readiness/evidence completeness are separate; PASS plus failed cleanup does not mean a reusable device.

Short PostgreSQL transactions lock job/resources in consistent order, recheck authority/readiness/capabilities, create durable Attempt/allocations with unique claim token and monotonic reservation epoch, and commit before delivery. SKIP LOCKED may aid selection but cannot replace resource locks/constraints. Never hold a transaction for a workload duration. Stale workers cannot finalize/release another attempt. Delivery is at least once, without a universal exactly-once physical-action claim.

Heartbeat/lease expiry detects lost contact, not stopped hardware. Mark suspect/offline resources unavailable. Do not reuse until previous activity is confirmed stopped and readiness passes; otherwise quarantine for administrator action. **Quarantine means unavailable**, not permission to start another job. Reconcile backend ownership with agent journal/process state and reject stale ID/epoch messages. Heartbeats run independently. Configurable planning defaults, not measured guarantees: 5-second heartbeat, suspect after 20 seconds, assignment acknowledgement deadline 30 seconds.

Start FIFO among compatible jobs, one exclusive workload/device, bounded agent/station/global concurrency with USB hub/power/interface/station CPU/storage resources. Add priorities/aging against starvation. Coordinated work reserves its full resource set atomically or waits holding none. Retry only configured transient infrastructure errors with bounded backoff/attempts after safe termination/readiness. Never hide assertion failures through retries or automatically repeat non-idempotent physical operations.

### Agents, plugins, artifacts and API

Authenticate enrollment/registration, heartbeat/poll/event/upload/result with unique scoped revocable/rotatable agent credentials. Agents initiate outbound requests, not inbound public SSH; assignments restrict devices/jobs. Persist accepted execution/epoch/process identity in local SQLite journal before launch; spool per-execution evidence until acknowledged. Redelivery/restart returns known status without duplicate launch. Bound child process runtime/output/CPU/memory/disk as supported; cooperative cancel has grace and tested Windows/Linux process-tree escalation. Uncertain termination blocks release.

Installed trusted allowlisted plugins/adapters only: no untrusted dynamic downloads, arbitrary shell strings, executable paths or user-supplied host paths. Adapter: discover, identify, capabilities, readiness, prepare/open, narrowly defined execute, collect, cleanup/close. Plugin: manifest/version/schema/capabilities, prepare, execute, collect/report, cleanup. ExecutionContext contains ID/epoch, authorized adapter-issued handles, cancellation/deadlines, controlled artifact handles and structured logger. Extend through registration/configuration, not scheduler edits. Reject unknown plugins, invalid parameters and unsupported capabilities before dispatch.

Controlled local artifact store first: SQL ownership, checksums, size/type, immutable storage keys, retention/completeness. Bound upload/download, validate containment, reject traversal/symlink/reparse escapes and handle untrusted content safely as attachments. Inputs belong to authorized projects/requests; outputs to assigned executions. No arbitrary client filesystem paths.

Typed shared `/api/v1` schemas cover authorized devices/tests/capabilities; jobs/status/idempotent cancel; admin enrollment; agent heartbeat/claim; sequenced deduplicated events; idempotent result PUT; checksum-validated authorized uploads/downloads; bounded paginated history. Structured errors include INVALID_INPUT, FORBIDDEN_TEST, NO_MATCHING_CAPABILITY, QUEUE_DEADLINE_EXCEEDED, AGENT_LOST, ARTIFACT_CONFLICT. API uses 401 unauthenticated, 403 denied, consistent 404 for hidden foreign objects and 409 conflicts. HTML login redirects stay separate from machine errors. Never log secrets; browser mutations retain CSRF and agent/CI token endpoints cannot silently fall back to ambient browser authority.

## Milestones and acceptance gates

Each gate stops for review. Status labels: planned, implemented locally, simulator-tested, real-device-tested, externally integrated, blocked. A document/configuration is not an integration. M0/M1/M2A and M2B.1-.4 identity/contact, synthetic comparison, runner and local journal are implemented locally with recorded limits; M2B.5 onward remains planned. M2A/M2B.1 have real PostgreSQL 18.1 evidence; Docker/CI configuration is not externally integrated. Only standalone local synthetic execution exists; no platform dispatch or hardware execution exists.

### M0 - foundation (existing)

Preserve inspection, branch/hygiene, documentation, dependency lock/config and skeleton migrations. Gate: loopback startup, fresh repeatable migrations, exact prerequisite limits. No remote assumption/privileged installation.

### M1 - secure responsive portal (existing)

Preserve bootstrap/invite/recovery/login/logout, four roles/grants, filtered empty catalogs/dashboards, audit and responsive layout. Gate: valid login, invalid/inactive denied, Viewer POST/edit denied, cross-project/payload escalation denied, CSRF/throttle/revocation tests and desktop/narrow checks with evidence limits. No execution. Regular-browser interaction remains a review item; never weaken CSRF for Origin:null. Existing 39 passing tests are historical evidence, not rerun today.

### M2A - PostgreSQL, approved catalog and durable submission

**Implemented locally; at review.** The requirements below define this gate, not another authorization to implement it again. Verify actual PostgreSQL migration/restart, health/readiness and reproducible API/PostgreSQL Compose/non-container setup with durable volumes. Add immutable TestVersion/plugin schema/digest, draft authoring, publishing/approval/revocation and explicit grants. Add scoped CI/service token foundations and rotation/revocation; complete account/session/invitation-revocation management with audited scope rules. Seed opt-in clearly simulated inventory and approved fixture metadata without pretending execution. Executable plugin digest remains unknown/null until a real package is built in M2B; current manifest hash is real.

Add typed v1 contracts, authorized catalog/devices/compatibility, initial project-scoped input Artifact metadata and bounded checksum-validated upload, durable Job/Run/Batch submission, canonical hash/idempotency, queue deadline and owner-scoped history/detail pages. Input IDs must resolve to authorized immutable stored inputs; no client host paths. Output artifacts arrive in M2B. Jobs stay queued, no fake results. Validate all batch items before any insert commits. Add initial platform CI configuration (static/unit/permissions/PostgreSQL/package build) with actual hosted execution unverified absent authorized remote/provider. Introduce package metadata as needed and pin compatible dependencies after checks.

**Gate:** real PostgreSQL fresh migration and restart preserve users/inventory/queued jobs; concurrent identical submissions create one Job, changed body/same key conflicts; unapproved versions and foreign test/device/input artifacts denied; unauthorized batch creates no jobs; inactive/revoked service token denied; account/session/invitation revocation audited and effective; authorized job queues and unauthorized HTTP submission fails; desktop/phone job pages work. If PostgreSQL is unavailable, record the blocker, never pass this gate on SQLite. CI local equivalents are recorded; external CI is required in M4.

### M2B - simulator MVP and native local agent

M2B has **eight separately reviewed tasks, M2B.1-M2B.8**, in [M2B.md](M2B.md): agent identity/protocol; CAN plugin; bounded runner; durable journal; PostgreSQL assignment/polling; results/evidence; simulation/cancellation failures; portal integration/final review. M2B.1-.4 are implemented locally (see [M2B_1.md](M2B_1.md), [M2B_2.md](M2B_2.md), [M2B_3.md](M2B_3.md) and [M2B_4.md](M2B_4.md)); .5-.8 remain planned. This decomposition preserves every parent requirement below. M2B.4 merge requires user approval; the next implementation task is M2B.5 only after a new continuation. No platform dispatch or full M2B completion is claimed.

Create separate installable native Python agent, explicit enrollment, authenticated polling/heartbeat/events/results, journal/spool and separate basic single-scheduler process. Use PostgreSQL exclusive allocations/epochs from the outset, one device/job with required shared resources reserved together; competing-scheduler recovery is not proven until M3. Compose gains scheduler; Windows agent runs outside containers. Dispatch binds current authority and approved version/plugin digest.

Implement bounded subprocess runner and prepare/execute/collect/cleanup, cooperative cancel/process-tree escalation, timeout and preserved evidence. Simulator covers attach/detach, assertion PASS/FAIL, malformed output, timeout, agent crash/disconnect, acknowledgement/upload loss, cleanup failure. Add simulated file/network/communication and read-only readiness to prove extensibility. Minimal periodic UI polling shows progress, pending cancel, artifacts and loading/error/stale text; no fabricated hardware measurements.

First meaningful plugin: **CAN payload file comparison**. Explicit expected/actual artifact roles; strict hex grammar; approved declared reference-header policy; nonempty normalized payloads; payload-relative offsets; length plus overlapping positional mismatches and missing/extra counts. Header skipping cannot be caller-modified to force PASS. A leading insertion is not one positional mismatch. Preserve raw/checksummed inputs, normalized payloads, mismatch summary and versioned JSON/human report. Use synthetic fixtures unless specific real data is authorized; no confidential employer data or physical CAN capture claim.

**Gate:** browser/HTTP -> authenticated simulator agent -> SQL outcome -> authorized versioned report; pass/substitution/missing/extra/leading insertion/invalid hex/empty fixtures; assertion FAIL versus setup/malformed ERROR/runner TIMEOUT/detach; partial prepare cleans only owned acquired resources; arbitrary commands/paths rejected; unauthorized artifact denied; checksum validation; exact assignment/result/upload replay safe, conflicts cannot overwrite; restart journal prevents second launch; second plugin needs registry/config, not scheduler rewrite. Test native Windows/Linux supervision where available and label untested platforms. This is the first usable **simulator MVP**, not physical validation.

### M3 - parallel scheduling, recovery and schedules

Harden transactional claims/constraints/fencing, competing schedulers, heartbeat/lease/ack deadlines, shared station resources, global/per-agent limits, FIFO compatibility/fairness, safe reconciliation and audited admin quarantine/release. Distinguish pending/confirmed cancel, recheck dispatch authority, safely cancel after revocation, preserve every attempt and bounded retry. Add independent parallel batches/partial progress, immutable snapshots and recurring Schedule/Occurrence with timezone rules and unique occurrence key to prevent overnight duplicates after restart.

**Gate on real PostgreSQL/processes:** same-device jobs serialize, independent devices run in parallel; two schedulers cannot double allocate/start; duplicate claims/lost ACKs start once; API/scheduler/agent restarts preserve history/ownership; lost contact/worker death cannot overlap old activity; stale finalize/release denied; disconnect remains unavailable until reconciliation/readiness; cleanup failure quarantines without hiding original outcome; dispatch revocation blocks and running revocation safely cancels; partial batch outcomes preserved; schedule restart cannot duplicate occurrences. No mocks as proof of locks or physical termination.

Proposed unmeasured demo targets: assignment within 5 seconds on a ready agent/light stated load; suspect contact about 20-30 seconds with configured timing; at least 100 short simulated jobs with repeated uploads/lost replies/restarts and zero observed duplicate starts/double allocations. Record distributions, environment and failures. Capture workloads report measured arrival rate/duration, maximum queue depth and overflow, not unlimited throughput.

**M3C separate review gate:** coordinated multi-device execution atomically reserves the entire required resource set or waits holding none. Test reversed resource-order competition, full-set rollback and fairness. Until this gate passes, coordinated submission is explicitly unsupported, not silently split into independent jobs.

### M4 - CI client, pipelines and backend reporting

Provider-independent CLI: upload/submit/wait/cancel/collect/outcome, stable machine-readable output and separate human logs. Pipeline idempotency keys and immutable inputs link pipeline/build/software/test versions. Produce schema-versioned JSON, human details and JUnit; exit 0=PASS, 1=FAIL, 2=ERROR/TIMEOUT/CANCELLED/unknown. Report evaluated assertions/errors/skipped-not-evaluated accurately. Preserve the final outcome while collecting after failure (`when: always` in GitLab); runner death can prevent CI uploads but backend/spooled evidence remains available. Client poll timeout requests cancellation/reports uncertainty; never release hardware from CLI.

Distinguish **platform CI** (lint/static/unit/permissions/real PostgreSQL/simulator/build/artifacts) from **product/hardware CI** using the platform. GitLab resource groups are extra coordination, never the ownership authority. Physical jobs manual/protected on dedicated tagged trusted runners; no untrusted personal branch code/privileged lab credentials. No remote/provider/push without authorization; local equivalents never count as real external integration.

Add authorized paginated history/comparison by device/firmware/software/test version, first-attempt/rerun and product FAIL/infrastructure ERROR metrics, phone failure/download/cancel, overnight manifest and explicit change-impact example (parser changes broader than UI changes). No AI selection claim.

**Gate:** actual authorized CI regression pipeline FAIL with downloadable byte offsets, then fixed PASS; outage maps ERROR; lost submit response creates one Job; deliberate rerun retains both attempts; client deadline preserves ownership/cancel request; execution snapshots remain historical; cross-user/service artifact/API denial, token revocation/rotation. Without CI access this gate stays partially complete/local-only. Do not auto-commit/push a demonstration to invent evidence.

### M5 - real adapters, Unix services and secure phone operation

Inventory owned equipment and choose one compatible non-destructive path; buy nothing. Native discovery/identity/readiness, fixed allowlisted read-only Windows inventory, stable reconnect upsert and registration. No assumed WSL/container USB. Retain directory storage integrity and configured local network health; serial smoke is additional only with owned drivers/equipment. Physical CAN capture needs its own real adapter; a filesystem test is not raw SSD qualification.

Storage writes only bounded uniquely owned temporary files in an approved dedicated contained directory, reads/checksums, records detected capacity and enforces free-space/size/duration. Reject symlink/reparse escapes and existing-file collisions; cleanup only owned files. No raw disks/format/partition/unmount/existing overwrite/whole-drive stress. Network tests use preconfigured local endpoints and bounded traffic, not arbitrary remote targets. Automatic attach execution is opt-in, registered/ready/approved/authorized/resource-limited; unknown/replugged devices require readiness.

Linux systemd recovery/logging and documented native Windows foreground/service option with actual tested status. macOS launchd remains future/unverified. Audited quarantine/release requires readiness. Run a declared bounded overnight workload (e.g. 8 hours) with measured duration/peak memory/disk growth and available sensors only. No invented temperature/power/GPU data; firmware rollback/power cycling stay equipment-specific future capabilities, not simulated physical claims.

Phone LAN exposure is a separately authorized security/deployment change: trusted network, TLS/hosts/cookies, firewall decision and test credentials; do not expose database or agent management. This plan authorizes no host security change. Complete release-security prerequisites before non-local use and administrator MFA/OIDC before any internet-accessible release. Public multi-tenant hosting is out of scope.

**Gate:** at least one real-device result with actual environment; unplug preserves evidence/blocks reuse, replug readiness/no duplicate identity; only owned files touched under path attacks/cancel; local network bounds; actual Linux service recovery; declared overnight evidence; four roles/CI permissions on real API; physical phone inspects failure/download/cancel on separately approved secure setup. Missing equipment/OS/network access remains blocked/untested, never passed; keep simulator demo working.

### M6A - Celery and RabbitMQ orchestration

After core/CI/physical review (or explicit simulation-only sign-off if hardware unavailable), add Celery+RabbitMQ for bounded orchestration. Device agent retains ownership; generic workers cannot execute arbitrary hardware work. PostgreSQL stays authoritative. Introduce transactional outbox at this **first SQL-to-broker boundary**, with acknowledged publication, stable IDs/dedup/backoff; do not postpone dual-write safety until Kafka.

**Gate:** broker restart, SQL-commit/publish failure, duplicate/redelivery and worker death preserve ownership/results; no duplicate hardware start/release or hidden assertion FAIL; agent isolation remains. Explain the extension's learning/engineering purpose; it is not an MVP dependency.

### M6B - telemetry, diagnostics and bounded C++

InfluxDB timestamped measurements and MongoDB versioned variable diagnostics with SQL links, schemas/units/access/retention; SQL still authorizes execution. Deterministic regression rules use small known datasets with synthetic labels. C++ checksum/compute has bounded validated input, deterministic versioned output, timeout/process limits and known-answer tests. Optional Compose profiles keep services off by default.

**Gate:** schema/version/unit/missing-sensor checks, synthetic regression, authorized linked reporting, service outage without false PASS, bounded clean native execution/cleanup and actual tested OS labels.

### M7 - Kafka, local Kubernetes and warehouse

Kafka is replayable lifecycle/measurement events, distinct from RabbitMQ tasks. Extend existing outbox; version/deduplicate events, sequence per execution and checkpoint consumers/replay. Local Kubernetes backend deployment includes health/readiness/config/secrets/durable storage; native agents remain outside cluster initially. Snowflake summary export uses immutable IDs, incremental checkpoint/dedup and analytical SQL; provide local contracts/fixtures. External export disabled without credentials/budget approval; no spending/accounts implied.

**Gate:** duplicate/reorder/replay/restart and outbox recovery preserve history; local cluster restart retains state/secrets safely; summary exports deduplicate/checkpoint. Local export tests never count as Snowflake integration. Document exact authorized external evidence; retain native hardware ownership outside generic workers.

## Crosswalk replacing earlier future milestone numbering

Historical reports retain their original names/dates; future work follows this table.

| Original brief | PDF | Unified gate |
| --- | --- | --- |
| M0 | Part of PDF 1 | M0 preserved |
| M1 | Part of PDF 1 | M1 preserved |
| Versions/approvals from M2 plus missing durable API core | Rest of PDF 1 | M2A |
| M2 simulator plus basic agent from M3 | PDF 2 | M2B |
| M3 scheduler | PDF 3 | M3, coordinated extension M3C |
| CI portion of M5 | PDF 4 | M4, before physical integration |
| M4 physical/Unix | PDF 5 | M5 |
| Broker portion of M5 | Later extension | M6A |
| M6 telemetry/diagnostics/C++ | Later extension | M6B |
| M7 events/Kubernetes/Snowflake | Later expansion | M7 |

## Learning and handoff

The PDF's 90-130-hour estimate covered its proposed core, not the expanded portfolio or a guarantee. Re-estimate each gate after prerequisite inspection; two hours/day includes learning/review and may be extended by hardware/CI/OS access. No unattended future work is promised.

Two-hour session: 0-10 minutes read checkpoint/files; 10-80 implement one bounded slice; 80-105 inspect meaningful checks/success/failure; 105-120 explain and record exact next task. Ask only for blocking decisions/credentials/out-of-scope actions; no subagents unless requested. At every gate update STATUS with working features, actual commands/results, screenshot evidence type, branch, changed files, limits and skill status. Provide five-minute success/failure demo and three interview questions; propose but do not execute a commit. On continuation read AGENTS/STATUS/PLAN and inspect relevant code. Tests must prove permissions/ownership/cancel/cleanup/concurrency/replay as applicable, not mirror implementation with placeholders.

Final demo target, not current functionality: sign in and identify permitted simulated/physical device; CI submit and trace API/job/reservation/agent/report; competing job waits while independent devices run; injected CAN mismatch fails CI with offsets/evidence; disconnect holds ownership until reconciliation/readiness; phone inspects failure/cancels; explain new plugin registration without scheduler edits. Claim only gates with actual evidence.

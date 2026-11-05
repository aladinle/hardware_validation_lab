# Unified requirements and evidence checklist

Reconciled 2026-11-03 from original user brief sections 1-8 and LabFlow PDF pages 1-18; status columns updated after M2B.2 local implementation. [PLAN.md](PLAN.md) is the only roadmap. This checklist maps coverage/evidence, not implementation authorization. Actual results are in STATUS and [M2A.md](M2A.md). M2A has actual Windows/PostgreSQL 18.1 submission evidence; M2B.2 adds measured local synthetic file analysis; platform execution, physical hardware and hosted CI remain unmeasured.

Legend: **local** = implemented locally with recorded portal checks; **partial** = some implementation/configuration/evidence; **planned** = not implemented; **conditional** = requires equipment, credentials or explicit deployment authorization. Planned requirements remain required at their assigned gate unless explicitly revised later.

M2B work is decomposed into eight tasks (.1-.2 implemented locally; .3-.8 planned) in [M2B.md](M2B.md). Its parent-gate coverage table maps those tasks to existing requirements without removing any parent acceptance checks. Identity/contact evidence is in [M2B_1.md](M2B_1.md).

## Product, workflow and access

| ID | Requirement | Gate and acceptance evidence | Current status |
| --- | --- | --- | --- |
| W01 | Inspect instructions/workspace/Git/runtimes, preserve changes, local feature branch, no assumed remote | Every session: status/prerequisite report | local workflow |
| W02 | No automatic commits/push/merge/publish/spend/external accounts/privileged install/host security change; no extra agents unless requested | Every session: reviewable scoped work and explicit external authorization | local workflow |
| W03 | Two-hour learning sessions, gated incremental implementation, meaningful checks/fixes, no unattended promises | Every gate: STATUS, exact commands/results/files/limits/next task, five-minute demo, three exercises, honest skills | local workflow |
| W04 | Required README/AGENTS/PLAN/ARCHITECTURE/SECURITY/DECISIONS/STATUS, dependency lock/config, hygiene/setup alternatives | M0 maintained; fresh setup/migration/dependency/startup | local |
| W05 | Independent branding; no Apple affiliation/certification/unowned Mac validation; no fabricated data | Every UI/report/demo: source/environment labels | local portal; execution planned |
| U01 | Navy sidebar/light dashboard/blue actions/white cards/status text, all seven navigation areas | M1/M2B/M4: desktop connected/running counts, authorized selection, progress, parallel batches, discovery notifications/results | partial: portal, approved catalog and queued job UI; execution progress planned |
| U02 | Phone My Lab/permitted tests/available devices/active work/failure/evidence/cancel; cards without overflow | M1/M2B/M4/M5: viewport and actual physical-phone checks | partial: queued job/form snapshots; physical phone unverified |
| U03 | Labels, keyboard/focus/status color+text, empty/loading/error/stale states | Every UI gate: forms/navigation/errors/delays | partial: no execution polling yet |
| U04 | Hide unauthorized records; disabled reasons only when permitted; labeled preview only, no silent impersonation | Every gate: distinct accounts/direct HTTP and backend filtering | local portal; no preview exists |
| S01 | Invite-only human accounts, unique passwords/local bootstrap, no public signup/shared defaults | M1: token expiry/reuse/password validation | local |
| S02 | Four project roles including Engineer drafts/approved execution; platform admin exception; explicit test/device grants | M1/M2A/M2B: action/object/scope/payload matrix | partial: drafts/approvals/version/device grants and queue authority implemented; execution planned |
| S03 | Active principal/membership/action/approved immutable version/test grant/device grant at submit AND dispatch | M2A/M2B/M3: revocation/approval races | partial: current submission/replay checks tested; dispatch recheck planned |
| S04 | Validate all batch items, reject whole unauthorized submission; partial outcomes allowed only after authorized acceptance | M2A/M3: no jobs for one forbidden item; retained per-item outcomes | partial: whole unauthorized queued batch rejected/tested; execution outcomes planned |
| S05 | Engineer/Operator own permitted cancellation, admin scoped all; attribution and pending/confirmed distinction | M2B/M3: queued/running/revocation checkpoint tests | planned |
| S06 | Hashing/sessions/generic errors/throttle/CSRF/env secrets, expiring single-use invites/recovery, local mail sink | M1: actual login/inactive/CSRF/throttle/recovery tests/log review | local development |
| S07 | Account/session/invite management and explicit revocation/reactivation semantics | M2A: audited mutation, next-request denial and old-session invalidation | local: audited account/invite/session API; epoch invalidation tested |
| S08 | HTTPS/Secure cookies outside localhost; MFA/OIDC before internet; proxy/host/mail/log/least-privilege review | Release prerequisites/M5 secure phone subgate | conditional; no release authorized |
| S09 | Separate scoped CI/service/agent credentials, hashed storage, enrollment/rotation/revocation; authenticate every call | M2A service/M2B agent/M4 CI: cross-principal denial | local identity foundation: separate scoped service/agent enrollment, expiry, rotation/revocation tested; execution authority remains planned |
| S10 | Same access through URLs/APIs/exports/artifacts; bounded paths/size/type/content, no arbitrary shell/executable/host paths | M2A-M5: hostile IDs/payload/traversal/upload tests | partial: v1 queue/input ACL/path/size/checksum tested; output/export planned |
| S11 | Security mutation audit append-only to ordinary users, not tamper-proof; no secrets in logs/Git | Every mutation: account/grant/approval/device/token/recovery audit tests | local portal/approval/grant/token/account/input/queue mutations; future entities planned |
| S12 | Installed trusted plugins only; no untrusted downloads/branch code on privileged personal hardware runner | M2B/M4/M5: registry and protected/manual/tagged runner policy | planned |

## Backend, data and resource safety

| ID | Requirement | Gate and acceptance evidence | Current status |
| --- | --- | --- | --- |
| B01 | Modular supported/pinned Python/Django and maintained primitives; minimal JS, no SPA absent measured need | M0 onward: compatibility/dependency checks | local |
| B02 | PostgreSQL authoritative; reproducible Compose and non-container setup; SQLite never proves PostgreSQL races | M2A actual migrations/restart/health/readiness; M3 races | partial: real native PostgreSQL 18.1 tests/restart; Docker/PG16 unverified |
| B03 | Linux/WSL2 backend and separate native Windows/Linux agent; do not presume USB passthrough | M2B/M5: native platform/environment labels | partial: independently installed Windows identity/contact process tested; Linux/hardware planned |
| B04 | Installable packages/pyproject, one lock, shared typed/versioned API/report contracts | M2A/M2B/M4: clean install/build/schema tests | partial: typed v1 contracts/native agent package built and clean-installed; synthetic workload package/JSON-human reports verified; backend reports planned |
| B05 | Project/Membership/TestDefinition/immutable TestVersion/TestApproval/TestGrant/Agent/Device/DeviceGrant | M1/M2A/M2B: migrations/version immutability/approval tests | local models: version/approval/grants and scoped Agent identity implemented; execution models remain later gates |
| B06 | Job/Run/Attempt/Batch/Resource/Reservation/Lease/Measurement/Artifact/AuditEvent; service tokens/schedules/events/outbox | M2A-M7: SQL constraints/identity/ownership | partial: Job/Run/Batch/input Artifact/service models; attempts/resources/schedules/outbox planned |
| B07 | Immutable actual/simulated/environment/device/firmware/hardware/software/test/plugin/agent/config/input/requester/time snapshots; UTC/local display/unknown stays unknown | M2A/M2B/M4: old reports unchanged after inventory edit; indexes and bounded logs | partial: immutable queued context/version/input snapshots; execution telemetry planned |
| B08 | Requester-scoped unique idempotency key + canonical body hash; stable IDs, replay original job, conflict 409 | M2A: concurrent submissions/restart/lost reply | local: PostgreSQL concurrent identical requests, live replay/conflict and restart checked |
| B09 | v1 jobs/status/cancel/devices/tests/agent enrollment/heartbeat/claim/events/results/artifacts; structured errors/pagination | M2A/M2B: real HTTP auth/contracts/bounds | partial: catalog/queued jobs/input plus agent enrollment/idle heartbeat APIs; claim/events/results/cancel planned |
| B10 | Lifecycle separate from PASS/FAIL/ERROR/TIMEOUT/CANCELLED; evaluation status/reasons, cleanup and evidence completeness | M2B: product assertion deadline vs runner timeout fixtures | planned |
| B11 | Separate scheduler, assignment durable before delivery, no HTTP hardware work | M2B/M3: restart/ack loss with real processes | planned |
| B12 | PostgreSQL short transactions/resource lock order/uniqueness, claim token/epoch, stale finalization/release denied | M2B basic/M3 competing schedulers | planned |
| B13 | Independent heartbeat/lease/ack deadlines; suspect/offline/quarantine; no reuse on contact expiry | M3: old process survives disconnect, second allocation refused | partial: idle contact timestamps only; deadlines/offline detection/leases/quarantine planned |
| B14 | Local agent SQLite journal/spool, accepted assignment/epoch/process persisted before launch, dedup/reconciliation | M2B/M3: restart/lost ACK no duplicate launch | planned |
| B15 | Supervised bounded runtime/output/CPU/memory/disk, cooperative cancel/grace/process-tree escalation/owned cleanup | M2B/M5: partial prepare/error/cancel/descendants on actual Windows/Linux | planned |
| B16 | Bounded configured transient infrastructure retry/backoff; preserve first failure/every attempt/rerun lineage, no hidden PASS/non-idempotent rerun | M3/M4: eligibility/history tests | planned |
| B17 | Compatible FIFO/fairness, device/station/global/agent concurrency, shared USB/power/interface/CPU/storage resources | M3: contention and independent parallelism | planned |
| B18 | Coordinated multi-device full-set atomic reserve or wait with none | M3C: reversed-order competition/rollback/fairness | planned; explicitly unsupported until passed |
| B19 | Periodic/overnight schedule and timezone rules, unique occurrence across restarts | M3/M4: occurrence replay/time-boundary tests | planned |
| B20 | Controlled immutable local input/output artifacts, SQL ACL/checksum/size/type/retention, sequenced events/incomplete evidence visible | M2B/M3/M4: identical/conflicting uploads, spool, unauthorized download | partial: immutable private input store/ACL/checksum; output/events/retention planned |
| B21 | Transactional outbox at first broker boundary, consumer dedup/checkpoint/replay; no assumed SQL+publish atomicity | M6A/M7: crash between commit/publish | planned |

## Plugins, physical devices and CI

| ID | Requirement | Gate and acceptance evidence | Current status |
| --- | --- | --- | --- |
| T01 | Stable adapter/plugin/context/result contracts, installed manifest/schema/version/capability registry | M2B: second plugin without scheduler rewrite | partial: fixed installed CAN registry/contracts; second plugin/runner planned |
| T02 | Simulator attach/detach/PASS/assertion FAIL/timeout/malformed/crash/disconnect/lost ACK/upload/cleanup failure | M2B/M3: deterministic injection matrix | planned |
| T03 | CAN file comparison with explicit expected/actual roles, approved reference-header removal, strict hex/nonempty payload | M2B: pass/substitution/missing/extra/invalid/empty/leading insertion fixtures | local: actual installed synthetic file comparator and known-answer checks; no physical CAN |
| T04 | Normalized payload byte offsets, overlap mismatch plus missing/extra counts, raw/checksummed inputs and versioned reports | M2B/M4: known-answer JSON/human/JUnit | partial: local deterministic JSON/human/raw-normalized evidence; backend delivery/JUnit planned |
| T05 | Readiness identity/capability/OS/version/free-space/dependency checks; serial identifies not authenticates | M2B/M5: registration/reconnect upsert/no duplicate devices | planned |
| T06 | File/network/communication simulation; real network preconfigured local endpoint, bounded traffic | M2B/M5: remote target/unsupported capability/traffic rejection | planned |
| T07 | Real storage only approved dedicated contained directory, bounded owned temporary files/checksum/capacity/free space/cleanup | M5: collision/traversal/symlink/reparse/unplug/cancel | planned |
| T08 | No raw disk/format/partition/unmount/existing-file overwrite/whole-drive stress | M5: negative-operation tests and owned-file evidence | planned safety invariant |
| T09 | Fixed allowlisted read-only Windows inventory, native USB/serial compatibility, Linux-only capability gating | M5: actual OS/driver tests; no generic PowerShell API | planned/conditional |
| T10 | Opt-in attach only registered/ready/approved/authorized/resource-limited; unknown/reconnected hardware not auto-ready | M5: unregistered/revoked policy/replug scenarios | planned |
| T11 | Physical serial/CAN only with compatible owned equipment; rollback/power cycle only with real supported hardware | M5 selected path; further adapter-specific authorization | conditional |
| C01 | Platform CI lint/static/unit/permission/PostgreSQL/simulator/build/artifacts; distinguish local versus hosted | M2A configuration/M4 actual pipeline | partial: CI config, static/package/PG18.1 local checks; hosted CI/simulator planned |
| C02 | Hardware CI through provider-independent upload/submit/wait/cancel/collect/outcome CLI/scoped token | M4: actual regression FAIL/fix PASS/outage ERROR | planned |
| C03 | Pipeline idempotency/immutable inputs/commit/test version; JSON/JUnit/human report and attempt lineage | M4: lost response versus deliberate rerun | planned |
| C04 | Exit mapping preserves failure during collect, when:always, runner-death evidence limits; client timeout cannot release device | M4: FAIL/error/poll timeout/CI runner loss | planned |
| C05 | Manual/protected dedicated tagged physical jobs, no untrusted-branch personal runner credentials | M4/M5: runner/token policy audit | planned |
| C06 | Authorized history/compare by device/firmware/software/test, first-attempt/rerun and failure/error metrics | M4: immutable queries/export restrictions | planned |
| C07 | Overnight manifest and explicit parser-vs-UI change-impact policy, not invented AI selection | M4: runnable declared coverage example | planned |

## Operations, later technology and demonstration

| ID | Requirement | Gate and acceptance evidence | Current status |
| --- | --- | --- | --- |
| O01 | Linux systemd recovery/logging; Windows foreground/service option; macOS launchd future only | M5: actual service restart/runbook/platform labels | planned/conditional |
| O02 | At least one real physical path and unplug recovery; missing hardware leaves physical validation blocked | M5: actual equipment/evidence | conditional |
| O03 | Declared bounded overnight run (e.g. 8h), measured peak memory/disk and sensors only when available | M5: duration/resource/temperature limits and evidence | planned/conditional |
| O04 | Secure trusted-LAN phone operation/TLS/hosts/auth, no exposed database/agent admin | M5 separate deployment subgate: explicit permissions and real phone | conditional |
| P01 | Celery/RabbitMQ orchestration, SQL authority and device-agent physical ownership | M6A: broker restart/dedup/redelivery/outbox failure | planned |
| P02 | InfluxDB timestamped measurements/MongoDB versioned diagnostics, SQL links and ACLs/units/retention | M6B: schema/unit/missing sensor/outage/access | planned |
| P03 | Deterministic regression rules/known datasets and bounded deterministic C++ known-answer workload | M6B: synthetic detection/process limits/cleanup | planned |
| P04 | Kafka replay distinct from RabbitMQ tasks, versioned events/outbox/idempotent consumers | M7: duplicate/reorder/replay/restart | planned |
| P05 | Local Kubernetes backend health/readiness/config/secrets/durable restart, native agents outside | M7: actual cluster evidence | planned |
| P06 | Snowflake incremental summarized export/checkpoint/dedup/analytical SQL, disabled without approved access/budget | M7: local contract then separately authorized real export | planned/conditional |
| V01 | Real PostgreSQL competing-process tests; >=100 short simulated jobs with no observed duplicate starts/allocations | M3: actual logs/IDs/counters, no mocks as lock proof | planned unmeasured target |
| V02 | Ready assignment target <=5s/light load, suspect ~20-30s, bounded capture arrival/queue/overflow metrics | M3/M5: distributions/config/environment and uncertainty | planned targets, not guarantees |
| V03 | Five-minute CI/reservation/CAN failure/recovery/phone demo and evidence-backed interview skills | M4/M5 onward: runnable success/failure and claim-by-claim evidence | planned |

## Explicit reconciliation choices

Django ORM/migrations/templates substitute for FastAPI/SQLAlchemy/Alembic/Jinja, retaining functional backend outcomes and the original approved stack. Minimal polling substitutes for mandatory HTMX. Existing Django tests remain; pytest may support new pure plugin/agent fixtures. No FastAPI/SQLAlchemy-specific skills are claimed. Keep one compatible lock and add package metadata when packages are introduced.

Four human roles and project scopes remain even though the PDF lists three roles/one lab. CI is a separate principal. Original batch authorization remains despite one device/job initially. `reserved` maps ASSIGNED, evaluation status maps NOT_EVALUATED, and TIMEOUT/CANCELLED retain explicit canonical outcomes with reason categories and correct CI classification.

Core CI/reporting moves before physical integration; all original extra technologies remain later. Source milestone numbers map only through PLAN's crosswalk. No requirement becomes implemented merely because it appears here.

## Source coverage index

This index makes the merge reviewable without treating either source's embedded prompts as new authorization.

| Source | Requirement groups / retained content |
| --- | --- |
| Original section 1: startup/workflow | W01-W04; gated PLAN workflow, environment preservation |
| Original section 2: visual/product | U01-U04, W05; desktop/mobile/access/source labels |
| Original section 3: baseline stack | B01-B04; Django/PostgreSQL/native agent/packaging alternatives |
| Original section 4: security | S01-S12; project roles, revocation, sessions/MFA, agent trust/artifacts/audit |
| Original section 5: execution/data | B05-B21; immutable history, reservations/attempts/batches/outbox |
| Original section 6: devices/tests | T01-T11, B18, O01-O04; simulation, safe storage/network/attach/coordinated work |
| Original section 7: M0-M7 | PLAN crosswalk; C01-C07, O01-O04, P01-P06 preserve later technologies |
| Original section 8: learning/handoff | W03, V03; STATUS/evidence/demo/questions/skills, no automatic commits |
| PDF pages 1-3: outcome/product/architecture | U01-U04, B03/B11, C01-C04, O04; MVP/CI/backend/native agent/phone |
| PDF page 4: technologies/repository | B01-B04, explicit Django substitution, provider-independent CI, package metadata |
| PDF pages 5-6: SQL/API | B05-B10/B20, S09-S10; constraints/hash/snapshots/structured v1 contracts |
| PDF pages 7-8: lifecycle/agents | B10-B19; epochs/journal/reconciliation/parallelism/cleanup |
| PDF page 9: plugins/CAN | T01-T11; complete comparison fixtures, extensibility and bounded device paths |
| PDF page 10: CI/security | C01-C05, S06/S09/S12; CLI outcomes/artifacts/trust |
| PDF pages 11-15: five milestones | PLAN source crosswalk and acceptance gates M0-M5; no retrospective completion claim |
| PDF page 16: verification/targets | V01-V02; real PostgreSQL/processes, 100 jobs, measured timing/capture/overnight bounds |
| PDF page 17: daily work/checkpoint | W01-W04, PLAN learning/handoff; STATUS substitutes for duplicate progress.md |
| PDF page 18: demo/future skills | V03/P01-P06; final evidence-backed walkthrough; no inflated interview claim |

## Skill evidence, not just technology names

| Skill | Current defensible evidence | Future evidence needed |
| --- | --- | --- |
| Python/Django backend and security | Local portal and typed queued API, authorization/CSRF/throttle/invitation/service tests | Typed API contracts, complete execution workflow, production release review |
| Relational modeling/migrations | Django models, actual PostgreSQL 18.1 migration/immutability/idempotency/restart checks | M3 resource constraints, execution agents and competing scheduling-process tests |
| Responsive web UI | Local templates/CSS, queued job forms/details and labeled viewport snapshots | Real interactive desktop/phone execution/report/cancel workflow |
| Git/repository practice | Local feature branch, hygiene, reviewable uncommitted files | User-reviewed commit/review/remote history only when authorized |
| CAN/test-plugin engineering | Contract metadata and synthetic fixtures only; no comparison runtime | Known-answer comparison fixtures, plugin extension and versioned mismatch reports |
| Scheduling/distributed recovery | Planned only | Actual racing schedulers, lost replies/restarts, journal/fencing/reconciliation evidence |
| CI/backend reporting | Scoped service API/CI config/static/build checks locally; no hosted pipeline | Actual failing/fixed pipeline, CLI/API/JUnit evidence and correct error handling |
| Native hardware/Unix operations | Planned only | Real adapter/owned-file/unplug tests, actual service and overnight run |
| C++/telemetry/diagnostics | Planned only | Bounded known-answer native execution and validated measurements/regressions |
| RabbitMQ/Kafka/Kubernetes/warehouse | Planned only | Broker/replay/cluster tests, and separately authorized actual Snowflake integration |

Reading the plan or answering interview questions demonstrates learning, not implementation of a planned feature. Use STATUS to link each skill claim to actual commands/results/environment.

## Five-minute reconciliation review

1. Minute 0-1: identify preserved M0/M1, locally implemented M2A and dated evidence in STATUS; distinguish planning-session history from later implementation.
2. Minute 1-2: follow T03/T04 to M2B; explain expected/actual/header/offset rules.
3. Minute 2-3: follow B12-B14 to M3; explain why missing heartbeat cannot free a device.
4. Minute 3-4: follow C01-C04 to M4; distinguish platform CI from hardware CI and failure exit handling.
5. Minute 4-5: find P01-P06 and explain deferred services/conditional Snowflake access.

Three exercises: (1) Why can Django deliver durable API behavior without FastAPI? (2) Why is file-based CAN comparison not physical CAN validation? (3) What evidence distinguishes planned, simulator-tested, real-device-tested and externally integrated skills?

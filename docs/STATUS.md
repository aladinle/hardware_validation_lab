# Current M2B.2 checkpoint - 2026-11-05 (America/Los_Angeles)

## Outcome, authorization and next gate

**M2B.2 is implemented locally and its checks passed.** User explicitly authorized feature/m2b.2_synthetic-CAN-file-comparison work and merge into main after completion. GitHub origin is https://github.com/aladinle/hardware_validation_lab.git; baseline main/feature were 219b798 with a clean tree. Completed feature commit 8788be8, pushed the feature branch, merged it into main with merge commit b891d49, and pushed main. No conflicts, force push or history replacement. Post-merge installed-source/wheel verification retained the final digest. This status record is a documentation follow-up; final remote SHA verification is reported in the chat/Git history. Stop before M2B.3, which requires a new continuation. The entire M2B milestone has not passed.

The installed pure comparator handles explicit synthetic expected/actual files, fixed reference-header policy, strict byte-pair grammar/nonempty payloads, positional overlap/length differences, raw+normalized checksummed evidence and deterministic schema-versioned JSON/human reports. A fixed plugin registry rejects unknown code/fields/policy/package identity. New immutable SQL versions can bind to the real wheel, with separate approval and grants. Historical M2A versions and queued snapshots remain unchanged; new submissions remain queued. Native agent contact is still idle only. No runner, journal, scheduler/dispatch, backend result ingestion, physical capture or hardware readiness was implemented.

## Actual checks and commands

| Check | Actual result |
| --- | --- |
| Initial git status/branches and verified-TLS fetch | Clean feature/main at 219b798; no concurrent remote changes at inspection |
| Final `scripts/postgres-local.ps1 -Action test` with LAB_B2_REVIEW_WHEEL pointing at the final actual wheel | **112 tests passed in 27.837s, no skips**, `.local/b2-tests-release.txt`; all 93 baseline regressions plus 19 new comparator/registry/publication cases |
| PostgreSQL publication using the actual built artifact | New immutable package-bound version; approval and version grant each required separately; old metadata manifest and old queued job snapshot retained; new job remains queued; unauthorized authors and missing wheel denied |
| `python -m build --no-isolation --sdist-extract-dir .local/build-b2-release --outdir .local/dist-b2-release` | Source distribution and 0.3.0 wheel built; `.local/b2-build-release.txt` |
| Actual final wheel SHA-256 | `d7a9ac9d3b54603c443fa8ac8aea50c7892b3876a38f9e01d73e009ab329b87b` |
| Fresh `.local/b2-plugin-venv` offline no-deps installation and final reinstall | Installed contracts/agent/workloads; no Django dependency |
| `tests/b2_package_smoke.py --python .local/b2-plugin-venv/Scripts/python.exe --wheel .local/dist-b2-release/hardware_validation_lab_contracts-0.3.0-py3-none-any.whl` | All seven real CLI fixtures passed: match -> PASS/0; substitution/missing/extra/insertion -> FAIL/1; invalid/empty -> ERROR/2. Imports checked from outside checkout with Django absent. Matching real digest, deterministic report replay, existing-output preservation and header-override rejection passed. `.local/b2-package-smoke-release.txt`; evidence retained in `.local/b2-evidence-a8owkzv9/` |
| `ruff check web contracts agent workloads tests`, compileall, `pip check` | Passed; no broken requirements or new runtime dependencies |
| Django check, makemigrations --check --dry-run, migrate --check on PostgreSQL | No system issues, no model drift, no pending migrations; no schema migration needed |
| Documentation checks | 13 Markdown files, 53 resolving local links, clean fences/whitespace, all 73 requirement IDs and 11 gates present |

Initial actual-wheel verification exposed CRLF metadata handling that the unit ZIP fixture did not cover. Fixed metadata parsing to handle either line ending and updated the fixture before the final build/suite. Prior 110-test pass did not count as final wheel evidence. Test-only ZIP fixtures are labeled as such; final publication checks used the actual distribution. Earlier source artifact digests are superseded by the final digest above, not silently reused.

## Scope, changed files and limitations

Added contracts/plugins.py, workloads package (pure comparator, registry, explicit local CLI), tests/b2_package_smoke.py, lab/test_can_plugin.py, publish_can_workload management command, six synthetic fixtures and M2B_2 guide. Added .gitattributes to preserve LF Python/fixture bytes across checkout/merge for artifact verification. Updated contracts/v1.py parameter validation, submissions.py publication/manifest contract checks, pyproject package/entry point, GitLab lint scope, README/AGENTS and roadmap/requirements/architecture/security/decisions/status. No application UI or auth changes, migration or dependency additions. No user live test version/approval/grant, account or agent credential was mutated by this task. PostgreSQL checks used dedicated test records/databases; the user's webserver/cluster were left running under their control.

The wheel identity check is a local installed-code/artifact consistency check, not signing, isolation or remote attestation. The CLI trusts operator-supplied local files/manifest; its candidate manifest is not SQL approval. Raw input bound is 1 MiB per role; only 100 difference details are emitted but counts cover all positions. Reports are synthetic local analysis, not persisted platform attempts or real hardware outcomes. Runtime supervision/cancel/resource limits, output delivery/retention, second plugins, JUnit, Linux/macOS, Docker and hosted CI remain future/unverified. No new browser review is claimed because this task changes no browser flow.

Five-minute demo, commands, expected exits and three optional exercises: [M2B_2.md](M2B_2.md). Next exact implementation action after review and a new continuation: M2B.3 bounded local subprocess runner only. Do not enable queued job dispatch.

---

# M2B.1 user demo review and GitHub preparation - 2026-11-05

User confirmed administrator browser login and the guided M2B.1 demo: enrollment, authenticated idle contact, rotation/credential replacement, revocation, disable/reenroll, and single-use enrollment replay rejection followed by successful contact with the valid state. These are user-reported manual outcomes, separate from the recorded 93-test PostgreSQL suite. Hardware execution/readiness remain unavailable; stop before M2B.2.

User requested a GitHub push. Repository initially has no commits or remote, on codex/m0-m1-portal. Prepared the initial source/documentation snapshot; 103 candidate files, 919,799 bytes before this status entry. Credential-pattern scan found no matches for actual-shaped agent/GitHub tokens, private keys or password-bearing PostgreSQL URLs. Verified .local credential/database/runtime files and .venv are ignored. This bounded scan is not a claim of exhaustive secret detection. Documentation checks passed (12 Markdown files, 44 local links, 73 unique requirement IDs). GitHub destination remains pending; no remote publication is claimed in this entry. Five-minute demo and three optional exercises are in M2B_1.md; next action is push to the user-selected repository, then remain at M2B.1 review.

---

# Demo inventory setup correction - 2026-11-05

User's enrollment selector was empty because their PostgreSQL project had zero Device records, confirmed read-only. Bootstrap does not seed inventory. Ran existing audited seed_simulated_catalog for their specified project/admin with --confirm-simulated; added offline synthetic device/catalog/version/approval/grants only, no agents/jobs/execution. Verified the actual AgentForm queryset now contains Simulated CAN file station (offline). No application-code change or server restart needed; refresh the page. Added the missing prerequisite to M2B_1.md. Project/enabled access filtering remains intact. User server/database left running; no credentials changed. Historical 93-test result below was not rerun for data/documentation setup. Documentation link/coverage checks passed; existing demo/three optional exercises remain in M2B_1.md. Next action: refresh enrollment page and continue M2B.1 demo; no M2B.2 authorization inferred.

---

# Login CSRF correction - 2026-11-05

The user reported persistent browser login 403s. Fixed an application-wide response policy bug in `web/lab/middleware.py`: `Referrer-Policy: no-referrer` can cause native browser form submissions to send Origin:null. Changed to `same-origin`, retaining cross-origin referrer suppression and all Django cookie/token/origin checks. No null/foreign origins were trusted; no passwords, account permissions or host settings changed. Earlier attribution to the in-app browser alone was incomplete, and the claim that no-referrer cannot affect Origin was incorrect. This correction supersedes that diagnosis and earlier snapshot-only browser limitation explanations; historical checks remain dated evidence.

Actual verification: browser-native form submission with invented credentials reproduced 403 on the user's old server (8765); the same browser on a temporary corrected loopback server (8767) reached the ordinary invalid-credentials form instead. No actual administrator password was accessed. Full PostgreSQL suite: **93 tests passed in 22.086s, no skips**, `.local/csrf-pg-tests.txt`. Added regression verifies current referrer policy, successful valid session login and continued rejection of null/foreign origins and missing tokens. Existing no-cache/HttpOnly checks remain. Lint and document structure checks passed. No migration/dependency change or milestone advancement.

Changed files: middleware.py, lab/tests.py, SECURITY.md, M2A.md, this STATUS. Temporary verification web server stopped; user's existing 8765 server and running PostgreSQL left under their control. Since lab.ps1 uses --noreload, user must restart their server with Ctrl+C then `.\scripts\lab.ps1 -Action run` in the same configured PowerShell window, refresh the login form and sign in with their bootstrap credentials. Existing M2B.1 demo/exercises remain in M2B_1.md. Five-minute fix demo: restart, refresh, sign in, view project and sign out; optional exercises: why no-referrer affects form Origin, why same-origin retains cross-site privacy, why origin checks alone do not replace CSRF tokens. Real administrator browser login awaits the user's retry; browser form CSRF and test-account authentication were verified separately.

---

# Current M2B.1 checkpoint - 2026-11-05 (America/Los_Angeles)

## Outcome and review gate

**M2B.1 is implemented locally and ready for review. Stop before M2B.2.** Administrator-controlled enrollment, scoped expiring agent credentials, revocation/rotation and authenticated idle contact work through a separately installed native Windows process. No CAN plugin, scheduler, dispatch, execution journal/spool, hardware discovery/readiness or workload execution is implemented. Existing M2A submissions remain queued. The full M2B milestone has not passed.

See [M2B_1.md](M2B_1.md) for setup, exact contracts, recovery, five-minute demo and three optional interview exercises. [M2B.md](M2B.md) defines the remaining seven tasks. The next exact action after review and a new continuation is **M2B.2: pure synthetic CAN payload file comparison plugin**, not hardware capture or assignment.

## Scope and changed files

- Added `contracts/agents_v1.py`, native `agent/` package/CLI and strict bounded identity/idle DTOs. Future execution DTOs are definitions only.
- Added Agent/AgentDevice/enrollment/runtime credential/heartbeat models and migration 0004; Device.enabled now gates new submission and contact. Active device identity bindings are unique, distinct from execution leases.
- Added `web/lab/agent_services.py`, `agent_api.py`, `agent_portal.py`, routes, admin-only template and device-list navigation. Manager actions require current human administrator authority; browser mutations retain CSRF. SQL stores secret hashes; returned secrets download once with no-store.
- Added `web/lab/test_agent_identity.py`, `tests/b1_review.py` and `tests/b1_http_smoke.py`. Updated package metadata to 0.2.0 with hvl-agent entry point and CI lint scope. No runtime dependency additions.
- Updated AGENTS, README, PLAN, REQUIREMENTS, ARCHITECTURE, SECURITY, DECISIONS, M2B and this STATUS; added M2B_1 guide and desktop/mobile screenshots.

## Actual commands and results

| Command/check | Actual result |
| --- | --- |
| `git status --short --branch` | Unborn codex/m0-m1-portal; existing untracked project preserved; no commit/push/merge/remote creation |
| `scripts/postgres-local.ps1 -Action migrate` and isolated review migrations | Additive 0004 applied on actual PostgreSQL 18.1; no user database replaced |
| `scripts/postgres-local.ps1 -Action test` final substantive suite | **92 tests passed in 21.154 seconds, no skips**; `.local/b1-pg-tests-final.txt`; includes the existing 67 tests and identity/client/transport regressions |
| PostgreSQL concurrent enrollment test | Two independent connections race one ticket: one successful enrollment/runtime credential; other denied |
| Django check; migration drift and repeat migrate | No system issues; no changes detected; no migrations to apply |
| `ruff check web contracts agent tests`; compileall; `pip check` | Passed |
| `python -m build --no-isolation --sdist-extract-dir .local/build-b1-final --outdir .local/dist-b1-final` | Source distribution and 0.2.0 wheel built; `.local/b1-build-final.txt` |
| Fresh `.local/b1-agent-venv` offline wheel installation; command from outside checkout root | Installed CLI reports 0.2.0 and imports without Django; final rebuilt wheel reinstalled and checked |
| `tests/b1_http_smoke.py` against real PostgreSQL-backed loopback HTTP | Actual administrator session/CSRF enrollment, separate installed Windows process, repeated idle heartbeat, rotation, old-key rejection, credential replacement, new-key acceptance, revocation and logout passed; captured output contained no credential values |
| Final rebuilt installed package live check | Actual successful heartbeat and revoked-key exit 2 passed after final TLS error handling change |
| Desktop/mobile template snapshots | Actual admin template rendered with labeled isolated data and inactive forms, inspected at 1440x1000 and 390x844; no horizontal overflow (1425/1425 and 375/375 content/client widths) |
| Documentation consistency | Passed: 12 Markdown files, 44 resolving local links, clean fences/whitespace, all 73 unique requirement IDs and 11 gate labels. Git diff --check returned zero, but excludes untracked files; not application tests |

Errors found during implementation were fixed before the final suite: local transport/test handling and CLI state recovery were exercised, with invalid expiry/scope inputs denied. A sandbox-only TLS probe encountered an existing monitoring-hook permission denial during default TLS context creation; added a safe generic failure, preserved verified TLS and all host security settings, then ran the full approved PostgreSQL suite and actual installed client successfully. No sandbox failure is counted as passing evidence. Credential state is not an execution journal, and last-contact time is not hardware readiness or termination proof. Heartbeat dedup retains only the latest 1,000 IDs per identity; audits are not pruned.

## Review environment, cleanup and limits

Used only the existing workspace cluster at 127.0.0.1:55439 and a new isolated `hardware_lab_b1_review` database, with a temporary non-superuser project administrator and synthetic offline inventory. No real lab account was pre-created. Retired that account (inactive, unusable password, session epoch advanced), disabled review agents and revoked their enrollment/runtime keys. Removed only the exact owned private review credential files. Preserved database records, cluster, logs, built wheels and labeled screenshots.

Stopped loopback Django (8765) and snapshot server (8766), then cleanly stopped the workspace PostgreSQL cluster. `pg_ctl status` confirmed **no server running** (its expected nonzero exit status is not a stop failure). No host service, other cluster, existing SQLite data, firewall, monitoring hook or external account was changed.

Layout evidence: [desktop screenshot](screenshots/b1-desktop-agents.jpg) and [mobile-width screenshot](screenshots/b1-mobile-agents.jpg). These are labeled actual-template snapshots, not browser authentication evidence. The in-app browser Origin:null limitation remains; actual same-origin session HTTP was verified separately. Physical phone, real HTTPS deployment, Linux/macOS native runtime/services, Docker/Compose, hosted CI and hardware remain unverified. No application result or hardware measurement is fabricated. Review questions are optional and do not authorize the next task.

---

# Historical planning checkpoint - 2026-11-05 (America/Los_Angeles)

## M2B task decomposition

The user requested smaller M2B tasks. Added [M2B.md](M2B.md) with **eight ordered, separately reviewed tasks**: .1 agent identity/protocol; .2 CAN comparison plugin; .3 bounded local runner; .4 agent journal/spool/restart; .5 PostgreSQL assignment/polling; .6 results/evidence; .7 simulator failures/cancel/second plugins; .8 portal integration/final milestone review. Each includes dependencies, actual future checks, safety boundaries and a mapping back to the full M2B acceptance gate. One task can span several two-hour sessions; this is not an eight-session completion promise.

Updated PLAN/AGENTS/REQUIREMENTS to reference this decomposition. **Planning only: all eight tasks remain unimplemented and no M2B execution was authorized or started.** M2A's implementation/evidence below is unchanged. A future request to continue with M2B starts M2B.1 only; each task stops for review and all parent checks remain required before the M2B milestone passes.

Checks this session: inspected Git status, AGENTS/STATUS/PLAN, the existing CAN-only typed contract and immutable version model; reviewed task coverage/dependencies against the parent gate. Documentation link/fence/whitespace/requirement-ID checks and Git diff whitespace check are recorded for this planning change. Application tests are not rerun for documentation-only edits; the historical 67-test PostgreSQL result is not a new result today. No application/database/dependency changes, servers, privileged installs, extra agents, commits or external actions.

Actual validation: `.venv\Scripts\python .local/check_reconciled_docs.py` passed for 11 Markdown files, 29 local links and all 73 requirement IDs; an additional read-only section check confirmed exactly M2B.1 through M2B.8 in order. `git diff --check` returned zero, with the existing untracked-content limitation. These checks validate documentation structure, not runnable M2B behavior.

Changed files: new docs/M2B.md; updated docs/PLAN.md, REQUIREMENTS.md, STATUS.md and AGENTS.md. Current branch remains unborn codex/m0-m1-portal with existing untracked work preserved. Five-minute planning walkthrough and three optional exercises are in M2B.md. Next action is review of the task split; implementation awaits explicit continuation. Proposed commit message after review: `docs: split M2B simulator milestone into eight reviewable tasks`.

---

# Historical M2A checkpoint - 2026-11-03 (America/Los_Angeles)

The implementation evidence below remains valid for its date; current M2B task order and next-step wording are defined above and in M2B.md.

## Outcome and review gate

**M2A is implemented locally and ready for review. Stop here; M2B execution is not authorized.** Actual PostgreSQL 18.1 evidence now covers fresh migrations, immutable version/input metadata, durable queued submission, competing identical requests and a real database-server restart. Docker/Compose/Linux/hosted GitLab and physical phone remain unverified. No agent, scheduler, CAN comparison runtime, hardware reservation, attempt or test outcome has been implemented. Queued synthetic requests are not PASS/FAIL results or simulated execution.

Working features: Engineer/Admin draft authoring; immutable published manifests with separate audited approval/revocation; explicit version versus catalog grants; private bounded/checksummed input upload/download; typed strict v1 APIs; service principal/token scope/expiry/rotation/revocation; account/invitation/global-session revocation; atomic whole-batch permission validation; requester-scoped idempotency/hash and stable Batch/Job/Run IDs; immutable queued context; health/readiness; responsive queue/catalog/history/detail forms. Admin submission still requires active membership and explicit version/device grants. See [M2A.md](M2A.md) for API contracts, setup, safety limits and five-minute demo.

## Prerequisites resolved without host changes

Docker engine remains unavailable. A broader read-only search found existing PostgreSQL 18.1 binaries at `C:\Program Files\PostgreSQL\18\bin`, despite psql not being on PATH. Initialized a **new workspace-only** `.local/m2a-pg` cluster, SCRAM-authenticated with a private generated password, bound to 127.0.0.1:55439. No Windows service, installed component, firewall, other cluster or original SQLite data was changed. The earlier async Docker question became unnecessary once this native path worked.

The dedicated integration database is hardware_lab_m2a; Django created/destroyed only its dedicated test database during tests. Cold-restart/live/browser evidence used a separate hardware_lab_m2a_review database with random temporary credentials and offline synthetic metadata. At handoff temporary credentials are retired and owned review/web/database processes stopped; records/cluster are preserved. Normal human lab accounts have not been pre-created in PostgreSQL; use interactive bootstrap after starting/migrating the database. SQLite accounts/data remain separate and preserved.

## Actual commands and results

| Command/check | Actual result |
| --- | --- |
| `git status --short --branch` | Still unborn codex/m0-m1-portal with untracked project files; no commits/remote/push/merge |
| `docker version/info`, PATH check, then search Program Files/PostgreSQL | Engine unavailable; psql not on PATH; installed postgres reports 18.1 |
| `scripts/postgres-local.ps1 -Action init/start/migrate` | New isolated native cluster started with SCRAM; all 0001/0002/0003/auth/session migrations applied on PostgreSQL |
| `scripts/postgres-local.ps1 -Action test` (final substantive suite, `.local/m2a-pg-tests-final.txt`) | **67 tests passed in 18.808 seconds, no skips**; includes all 39 original portal tests plus M2A regression/integration cases |
| PostgreSQL-only competing connections test | Same concurrent key/body -> one Batch, Job, Run; one created response and one replay; different connections both succeed without duplicate creation |
| `tests/m2a_review.py prepare`, actual `pg_ctl stop/start`, then `check` | PASS: real server restart retained user, offline simulated device, queued job and immutable snapshot hash |
| `tests/m2a_http_smoke.py` against running PostgreSQL-backed loopback server | PASS: same-origin session login/queue form, scoped bearer queue, identical replay, changed-content 409, health/readiness and POST logout |
| `scripts/lab.ps1 -Action migrate` twice with actual PostgreSQL configured | Both repeat runs: `No migrations to apply` |
| `manage.py makemigrations --check --dry-run` with authorized PostgreSQL connectivity | `No changes detected` |
| `scripts/lab.ps1 -Action check`, `ruff check web contracts tests`, `pip check`, compileall | Passed; no Django system issues or broken requirements |
| `python -m build --no-isolation --sdist-extract-dir .local/build-source --outdir .local/dist` | Built source distribution and installable contracts wheel successfully |
| Earlier quick-start SQLite test run | 63 tests ran: 61 passed, 2 PostgreSQL-only tests correctly skipped. Four later regressions were verified on PostgreSQL; do not call this a current full SQLite-suite result |
| Browser layout snapshots | Desktop jobs 1440x1000, phone queue/details 390x844 inspected; no horizontal overflow (width/content 1440/1440 desktop, 375/375 with phone scrollbar) |
| `.local/check_reconciled_docs.py`, `git diff --check` | Documentation structure/links/73 requirement IDs pass; Git's whitespace check covers no untracked content, so not claimed as a complete added-code diff review |

The first implementation run exposed a local import shadowing Membership; the review run caught denial handling in legacy member/grant forms. Both were fixed and the full original+M2A suite passed. A package build initially failed on a sandbox temporary-directory rename; keeping its extraction directory inside the workspace fixed it. An un-escalated PostgreSQL consistency probe was denied by executor socket permissions, then rerun successfully with authorized local access. None is hidden as a passed check. Cosmetic device labels/status alignment were refined after the suite and re-rendered; no new execution behavior was introduced.

Cleanup: the web process-group interrupt also ended its child PostgreSQL process, so the first subsequent explicit stop reported no such process. Verified no server running, restarted only the workspace cluster, confirmed both queued review jobs survived recovery, then stopped it cleanly with pg_ctl. Temporary review account/tokens were retired and their private credential file removed; the dedicated cluster password/data remain ignored and preserved for local reuse.

Tests cover strict schemas/duplicate fields/bounds, authoring ownership, separate approval/version grants, whole-batch rollback, wrong header/capability denial, foreign/private inputs, upload size/hash/name/replay, SQL immutability, historical snapshots, service scope/expiry/rotation/revocation/no-session-fallback, browser CSRF, global session epoch/reactivation, project-versus-platform account authority, invitation revocation, own job/direct-ID access and original portal behavior. Test helpers explicitly label PostgreSQL-only assertions; no mocks/SQLite are used as submission-lock proof. These are not M3 scheduling/physical recovery tests.

## Changed files in M2A

New: contracts/__init__.py and v1.py; lab/submissions.py, api.py, portal_jobs.py, apps.py, signals.py, test_m2a.py; migrations 0002 and 0003; seed_simulated_catalog management command; queue/job/input_upload/workbench templates; examples/can synthetic fixtures; pyproject.toml; deploy/Dockerfile and Compose web configuration; .gitlab-ci.yml/.dockerignore; scripts/postgres-local.ps1; tests/m2a_review.py and m2a_http_smoke.py; docs/M2A.md; m2a screenshot evidence.

Updated: existing models/access/forms/views/middleware/settings/URLs, portal/static styles, requirements source/lock, .gitignore, AGENTS, README and architecture/security/decisions/plan/requirements/status docs. No existing user data was reset, no remote created and no automatic commit/push/publish performed. No additional agents were used.

## Limits and next exact action

- Actual platform evidence is native Windows/Python 3.11.4/PostgreSQL 18.1. PostgreSQL 16 Compose/CI, Docker image build, Linux deployment and hosted CI are **unverified**. CI configuration requires masked LAB_CI_POSTGRES_PASSWORD/LAB_CI_SECRET_KEY supplied outside Git; no personal hardware runner or credentials are configured.
- In-app browser Origin:null remains rejected; do not disable CSRF. Live same-origin HTTP tests passed. Screenshots are clearly labeled actual-template snapshots with inactive forms, not browser-authentication proof or hardware results. Physical phone/normal-browser interactive walkthrough remain review items.
- Version package digest, firmware, host environment and unavailable measurements remain null/unknown. Manifest checksum is real, but no executable CAN plugin exists. Queue expiry is stored/exposed, not processed without a scheduler. Cancellation/result/agent APIs are not enabled.
- Input store is bounded/path/checksum protected but trusts the local OS owner; a crash can leave private unreferenced blobs. No unsafe automatic orphan deletion/retention job exists. SQLite update-only snapshot protection is not equal to PostgreSQL update/delete triggers. Database/OS owner remains trusted, not tamper-proof.
- Existing development Python patch is old; update before release. No internet/MFA/production release is implemented. All services were local and temporary credentials retired. No unattended continuation is promised.

Review docs/M2A.md's run instructions/five-minute demo/three optional exercises. **Next authorized action after this handoff is review, not M2B implementation.** When explicitly asked to continue, read AGENTS/STATUS/PLAN and current code, then begin M2B with native agent enrollment/journal and bounded simulator execution. Preserve queued/history schema and approval/grant checks; add dispatch-time recheck and actual package digest rather than enabling execution of metadata-only versions.

Suggested commit message after review: `feat: add approved catalog and PostgreSQL-backed idempotent queued submissions`. Do not commit automatically.

---

# Historical reconciliation checkpoint - 2026-11-03 (America/Los_Angeles)

The reconciliation report below is retained as history; its next-action/current-status wording is superseded by the M2A checkpoint above.

## Reconciliation outcome and authorization

The user requested one plan covering the original Hardware Validation Lab ideas and the LabFlow Detailed Implementation Plan PDF. **Documentation reconciliation is complete and ready for review. No new implementation gate was started.** [PLAN.md](PLAN.md) is the single current roadmap; [REQUIREMENTS.md](REQUIREMENTS.md) maps 73 requirement groups, every original brief section and all PDF page groups to acceptance evidence/status. Supporting architecture/security/decisions/workflow/demo documents now use the same future gate names. Historical evidence below is preserved rather than relabeled.

Keep the existing Django application and four project-scoped human roles. Add the PDF's CAN comparison, typed APIs, durable idempotent jobs, scoped service identities, native journaled agent, reconciliation, provider-independent CLI, CI reports, schedules and measurable failure injection. Preserve every original later technology and safety restriction. Do not claim FastAPI-specific experience from the Django substitution.

New order: preserved M0/M1 -> M2A PostgreSQL/approved catalog/durable queued submission -> M2B native agent/CAN simulator MVP -> M3 parallel ownership/recovery/schedules -> separate M3C coordinated reservations -> M4 core CI/reporting -> M5 real adapters/Unix/secure phone -> M6A Celery/RabbitMQ/outbox -> M6B InfluxDB/MongoDB/C++ -> M7 Kafka/Kubernetes/Snowflake. Every individual gate stops for review. Original/PDF numbers are historical and map through PLAN's crosswalk. No source prompt or planning request authorizes automatic implementation, remote creation, CI connection, host exposure, purchases or commits.

## Changed files in this documentation session

- Updated README.md and AGENTS.md to point at the canonical plan and preserve scope/stop rules.
- Replaced docs/PLAN.md with the merged roadmap, common contracts, acceptance gates, source crosswalk and learning workflow.
- Added docs/REQUIREMENTS.md with 73 uniquely identified requirement groups, source coverage, current skills evidence and a five-minute planning review/three exercises.
- Updated docs/ARCHITECTURE.md, SECURITY.md, DECISIONS.md and DEMO.md for consistent naming/contracts/security boundaries. Added a clearly planned architecture diagram.
- Prepended this checkpoint to docs/STATUS.md, preserving the 2026-11-02 implementation evidence below.

No application source, dependency lock, runtime configuration, database schema or existing tests changed. Private ignored PDF render/check helpers under .local are inspection intermediates, not application features. No agents, servers or external services were started for this documentation session. No commits/pushes/publication or host security changes.

## Actual checks this session

- Read original user brief, all 18 PDF pages during reconciliation/review, current AGENTS/STATUS/PLAN and relevant code/docs; compared implementation claims with models/routes and the historical test log.
- `git status --short --branch`: still unborn `codex/m0-m1-portal`, existing new project files untracked; preserve them. No remote/commit operation performed.
- `.venv\Scripts\python .local/check_reconciled_docs.py`: passed across nine Markdown files; local Markdown links resolve, code fences/whitespace clean, all 73 unique IDs present and all 11 gate labels/topic markers found. This is a structural check, not proof of implemented requirements. Source coverage and consistency were reviewed separately.
- `git diff --check`: exit 0, with the same caveat that Git does not inspect untracked file content; the documentation checker did inspect the Markdown content directly.
- Application tests were **not rerun**, because changes are documentation-only. The 39 passing tests and live HTTP evidence below remain dated 2026-11-02. No new PostgreSQL/simulator/CI/hardware/integration result is claimed.

## Remaining limits and next exact action

M0/M1 remain implemented locally with the prior regular-browser/physical-phone/PostgreSQL evidence limits. The last environment inspection found the Docker engine stopped and psql absent; those prerequisites were not rechecked today. All later features and additional skills remain planned. The PDF's proposed timings and core 90-130-hour estimate are not measured results or a commitment for the expanded roadmap.

Review the merged PLAN and REQUIREMENTS five-minute walkthrough and the existing M0/M1 demonstration. **Only after explicit continuation, begin M2A**: inspect Git/current files and prerequisites, establish actual PostgreSQL integration without privileged installation/security changes, then implement approved immutable catalog, input artifacts, service identity and idempotent queued submission. If PostgreSQL remains unavailable, accurately record the blocker; never pass that gate using SQLite. Do not skip directly to simulator, physical tests or later services.

Three review exercises are in REQUIREMENTS. Proposed documentation commit message after review: `docs: reconcile hardware validation and LabFlow requirements into one gated roadmap`. No automatic commit.

---

# Historical session checkpoint — 2026-11-02 (America/Los_Angeles)

The implementation facts below are preserved from that session. Its future-milestone references and next-action wording are superseded by the current checkpoint and unified PLAN above.

## Outcome and active gate

**M0 foundation and M1 secure portal are implemented locally and ready for milestone review. Stop here; M2 has not started.** Local HTTP/security checks passed. Layout was inspected in desktop and phone-sized browser viewports using labeled Django-rendered snapshots. Interactive sign-in in a regular browser remains a user review item because the available in-app browser sends Origin:null, which CSRF correctly rejects. No PostgreSQL integration, simulator testing, real-device testing or external integration is claimed.

Current branch: `codex/m0-m1-portal`, unborn (no commits). Workspace initially contained only `.git`; no existing application files were overwritten. No remote exists. Nothing committed, pushed, merged, published or purchased. No extra agents were spawned. No host security settings or privileged components were changed.

Working features: local admin bootstrap; invite-only single-use expiring codes; email/password sign-in and POST sign-out; local-sink recovery; active-account checks; project Administrator/Test Engineer/Operator/Viewer roles; explicit catalog/device visibility grants; membership/role/grant mutation and immediate request-level revocation; security audit; responsive dashboard/catalog/devices/runs/results/access/audit pages. Unauthorized lists and direct URLs are filtered. Catalog records are non-executable, and empty states explicitly explain no discovery/execution/results.

## Actual commands and results

| Command/check | Observed result |
| --- | --- |
| `git status --short --branch`, `git log -1 --oneline`, `git remote -v` at inspection | Empty unborn master, no history, no remote; feature branch subsequently created |
| `python --version`, `py -0p` | Python 3.11.4 executable works; py launcher reports no registered installations |
| `docker version`, `docker info` | Docker CLI 20.10.23 present; engine pipe unavailable/stopped |
| `Get-Command psql` | No psql executable found |
| `.venv\Scripts\python -m pip install Django==5.2.18 psycopg[binary]==3.2.13` | Installed successfully after upgrading project-local pip to 26.3 with Windows HTTPS and SHA-256 verification; no TLS bypass |
| Initial migration generation and `manage.py migrate` | Initial schema created and migrations applied successfully on SQLite |
| `scripts/lab.ps1 -Action test` (final run, full output `.local/test-results.txt`) | **39 tests passed in 12.872 seconds**, no system-check issues; test DB destroyed automatically |
| Fresh SQLite file selected via LAB_SQLITE_PATH, `scripts/lab.ps1 -Action migrate` twice | All initial migrations applied; second run: `No migrations to apply` |
| `manage.py makemigrations --check --dry-run` | `No changes detected` |
| `scripts/lab.ps1 -Action check` / system check during tests | `System check identified no issues (0 silenced)` |
| `.venv\Scripts\python -m pip check` | `No broken requirements found` |
| `.venv\Scripts\python -m compileall -q web tests` | Exit 0 |
| `.venv\Scripts\python tests/http_smoke.py` against isolated QA DB/server on 127.0.0.1:8765 | PASS: real same-origin HTTP login, session-backed dashboard, no-store headers, CSS, rejection of null Origin, POST logout |
| Django loopback startup | Port 8000 denied by Windows; port 8765 served real HTTP successfully; no firewall/security changes |
| Browser login POST | Rejected 403: `Origin checking failed - null does not match any trusted origins`; protection retained and regression-tested |
| `tests/render_browser_review.py` + loopback snapshot server | Seven real template-rendered pages exported; forms disabled, CSRF values removed, review-only label visible |
| Browser desktop overview at 1440×1000 | Inspected; content width equaled viewport width (1425 CSS px after scrollbar), no horizontal overflow |
| Browser mobile overview at 390×844; users at 320×740 | Inspected; no horizontal overflow (375/375 and 305/305 CSS px respectively, scrollbar-dependent) |
| Browser keyboard navigation | Tab from skip link moved focus to the brand anchor; native links/forms/details and focus-visible styling retained. Full screen-reader audit not performed |
| `git diff --check` | Exit 0; repository has only untracked new files, so this is not a full content review of added files |

Tests cover distinct projects/users/devices/tests, four dashboards, direct foreign/ungranted URLs, Viewer/Engineer/Operator mutation denial, platform-versus-project authority, payload escalation attempts, grant and membership revocation, inactive sessions/users, generic invalid login, CSRF, null Origin, account/IP throttling/expiry, external redirect rejection, invitation use/expiry/weak-password/revoked-inviter/existing-account safety, recovery/expiry/session invalidation, audit isolation, headers and validated bootstrap. The first suite exposed a class-method decorator error and a test cookie shortcut issue; both were fixed before the passing runs. No placeholder test is counted as execution evidence.

## Changed files

All are new: README.md, AGENTS.md, .gitignore, .env.example, requirements.txt, requirements.lock; scripts/lab.ps1; deploy/compose.yaml; docs/PLAN.md, ARCHITECTURE.md, SECURITY.md, DECISIONS.md, STATUS.md, DEMO.md; docs/screenshots/desktop-overview.jpg and mobile-overview.jpg; web/manage.py and config settings/URLs/WSGI; lab models/migration/access/services/forms/views/middleware/logging/management commands/tests; responsive templates and static CSS; three isolated review/HTTP helpers under tests/.

Ignored `.local/` contains private runtime secret/database/mail locations, temporary review data and test logs. These are not deliverables or shared credentials. The normal quick-start lab database has no pre-created human account; run interactive bootstrap. Temporary browser review credentials are retired during handoff; review server processes are stopped. The retained snapshots are explicitly labeled and contain no real hardware/results.

## Limits and risks

- PostgreSQL setup is supplied but **not run**: Docker engine stopped, psql absent. Row-lock behavior, PostgreSQL migrations and concurrency remain unverified. No SQLite result proves distributed ownership.
- No simulator/agent/runner/jobs/leases/test versions/approvals/artifact downloads/real hardware exist. Run submissions cannot execute anything. M2+ technologies remain planned.
- Local-only HTTP, no admin MFA/OIDC, external mail or production settings. Secure cookies/HTTPS/MFA and deployment review are mandatory before any internet access. Do not bind the server beyond loopback.
- Regular-browser interactive login and physical phone access were not checked. In-app authentication is blocked by its null Origin; direct HTTP login is proven. Layout screenshots are rendering evidence only.
- Tests ran on Windows/Python 3.11.4/SQLite. Linux/WSL2 and PostgreSQL need their own runs. The interpreter patch is old; update before deployment. WSL USB visibility is not assumed.
- No role impersonation/preview, invitation revocation UI, all-session revocation UI, public registration, or platform account-edit UI. Trusted local OS/database operators are outside application-user restrictions. See SECURITY.md for reactivation/session behavior and release work.

## How to review and next exact action

Run `scripts/lab.ps1 -Action bootstrap` (after migrate) to choose your own account/password, then `scripts/lab.ps1 -Action run`. Open http://127.0.0.1:8765 in a regular local browser. Follow docs/DEMO.md for separate five-minute M0 and M1 demonstrations and the three interview exercises. Screenshot references are layout snapshots, not hardware evidence.

**Next action is your M0/M1 review, not automatic M2 implementation.** If you ask to continue, first read AGENTS.md, PLAN.md and this file; inspect current Git/files; then begin M2's immutable versions/approval and simulator design. If you want PostgreSQL checks first, start an already installed engine yourself or supply a local PostgreSQL endpoint; no privileged installation is assumed.

Suggested commit message after your review: `feat: add local Django foundation and project-scoped secure portal`. Do not commit automatically.

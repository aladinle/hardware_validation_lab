# M2A: approved catalog and durable queued submission

Implemented locally on Windows with PostgreSQL 18.1. No workload/agent/scheduler exists: requests remain queued and outcomes are null/not evaluated. Simulator labels describe opt-in metadata and synthetic input, not running simulation. M2B introduces execution only after review.

## Native PostgreSQL on this machine

Existing binaries were found at `C:\Program Files\PostgreSQL\18\bin`. The helper operates only the new `.local/m2a-pg` workspace cluster on 127.0.0.1:55439, not a Windows service or another cluster. It uses SCRAM authentication and an ignored random password file. It never silently installs software, changes a firewall, deletes an existing cluster or migrates the SQLite database into PostgreSQL. The cluster is stopped at session handoff; start it explicitly when reviewing.

```powershell
# First time only if .local/m2a-pg does not already exist:
# .\scripts\postgres-local.ps1 -Action init
.\scripts\postgres-local.ps1 -Action start
.\scripts\postgres-local.ps1 -Action migrate
.\scripts\postgres-local.ps1 -Action test
# In this same PowerShell session, the helper has set the dedicated PG* / LAB_DB environment.
.\scripts\lab.ps1 -Action bootstrap
.\scripts\lab.ps1 -Action run
```

Bootstrap only if you have not yet created a human administrator **in this PostgreSQL database**; use your own password. The original SQLite DB/accounts remain separate and preserved. The PostgreSQL cluster's `lab_local` is a trusted local integration database superuser (needed to create test databases), not a shared application login or a production least-privilege role. Choose a separate restricted DB role for any deployment. No real lab credentials belong in CI.

Stop the portal with Ctrl+C, then `scripts/postgres-local.ps1 -Action stop`. The helper `-Bin`/`-Port` options support another already installed compatible PostgreSQL binary path/dedicated port. Do not point `init` at existing data. When using another existing endpoint instead, set the documented PG* variables and LAB_DB=postgres directly; do not run this helper against it.

Compose alternative: set PGDATABASE/PGUSER/PGPASSWORD/LAB_SECRET_KEY privately, then `docker compose -f deploy/compose.yaml up -d --build`. Web/API and PostgreSQL are loopback-published; run `docker compose -f deploy/compose.yaml run --rm web python web/manage.py migrate` before expecting `/ready/` to succeed, then interactive bootstrap in the same container image. The internal container web bind is 0.0.0.0, but the host port is mapped only to loopback. This development image still uses Django's development server; no production/Internet release is configured. `.dockerignore` excludes secrets, databases and environments from the build context. **Docker build/Compose remain untested because the engine is unavailable.** Image tags are not digest-pinned yet; record actual digest/OS when first exercised. Do not run destructive volume removal.

## Using the portal

After bootstrap, the root redirect contains your project UUID. Optional explicit seed (substitute your project/email):

```powershell
.\.venv\Scripts\python web/manage.py seed_simulated_catalog PROJECT_UUID ADMIN_EMAIL --confirm-simulated
```

This adds an offline simulated CAN-file station, a contract-only test version, approval and explicit grants to that administrator. It creates no input/result or connected device. Known synthetic fixtures are in `examples/can/`; compute SHA-256 with `Get-FileHash -Algorithm SHA256` on the exact file. Line endings affect file checksums; hash the file you actually upload.

1. **Test Catalog -> Authoring & approvals:** Engineers author their own drafts; admins may manage project drafts. Save name/header policy, publish a new immutable version, then an admin approves it. Changing a draft does not change any published version. The real plugin package digest is unknown/null because no executable package exists yet; the manifest checksum is real, not a fabricated package hash.
2. Admin explicitly grants the version in the workbench and the device in Users & Roles. A legacy catalog-only grant does not authorize submission. Even platform admins need an active project membership and both explicit execution grants to submit.
3. **Test Runs -> Queue approved test -> Upload controlled input files:** provide ASCII fixture files (1 byte to 1 MiB), a simple filename and actual SHA-256. Expected/actual roles are explicit. Input parsing/comparison is not performed in M2A.
4. Select permitted approved version/device/inputs, use its approved header policy, choose queue deadline and an idempotency key. A repeated identical request reuses the original batch/jobs; changing content with that key returns a conflict. The browser form supports one job; the API supports 1-20 items with whole-submission authorization rollback.
5. Job detail shows Queued/Not evaluated, immutable context, input checksum references and unknown host/firmware values. Queue deadlines are stored and elapsed status exposed; no scheduler transitions expired jobs yet. Legacy direct `/projects/.../runs/` execution POST intentionally remains unavailable; the new queue route/API is the submission entry point.

## Versioned HTTP contracts

Typed strict parsing is in `contracts/v1.py`; only the declared CAN contract is accepted. It rejects extra/duplicate fields, non-finite numbers, booleans masquerading as integers and arbitrary paths/commands. Requests have bounded size/items/deadline. Parameter schema is versioned/approved metadata, not a user-supplied general executable schema.

Browser API calls use Django sessions **and CSRF**. Explicit bearer calls use only the presented scoped service credential, never fall back to a logged-in browser on invalid/expired tokens. A service also needs active owner membership, explicit version/device scope and the owner's current grants. No public registration, agent enrollment/claim/heartbeat, runner, result submission or cancellation API is enabled in M2A.

| Route | Method / behavior |
| --- | --- |
| `/health/`, `/ready/` | GET: process alive / DB+migrations ready; no secrets; execution false |
| `/api/v1/catalog?project_id=UUID` | GET: permitted tests/versions and offline device capabilities; devices/tests aliases return the same bounded catalog envelope |
| `/api/v1/jobs` | POST: Idempotency-Key header, canonical submission; 201 new/200 replay/409 changed content |
| `/api/v1/jobs?project_id=UUID&offset=0` | GET: 50 permitted jobs/page, bounded offset |
| `/api/v1/jobs/UUID` | GET: permitted queued job/snapshot/run/batch/deadline; no outcome |
| `/api/v1/projects/UUID/drafts` | POST: name/header_bytes; Engineer/Admin authoring |
| `/api/v1/projects/UUID/drafts/UUID` | POST: update own authorized draft |
| `/api/v1/projects/UUID/drafts/UUID/publish` | POST `{}`: immutable new snapshot, not automatically approved |
| `/api/v1/projects/UUID/versions/UUID/approval` | POST `{approved: true/false}`: Admin only, auditable grant/revoke |
| `/api/v1/projects/UUID/members/ID/versions` | POST `{version_id, granted}`: Admin version grant/revoke |
| `/api/v1/projects/UUID/inputs` | POST raw application/octet-stream, X-Input-Name and X-Content-SHA256; bounded owned/project/service input |
| `/api/v1/inputs/UUID` | GET: authorized attachment with checksum verification |
| `/api/v1/projects/UUID/principals` | POST `{owner_id, name, version_ids, device_ids}`: Admin creates explicitly scoped service identity |
| `/api/v1/projects/UUID/principals/UUID/tokens` | POST `{action: rotate/revoke/deactivate}`: Admin; rotate revokes previous tokens and returns a seven-day credential once |
| `/api/v1/accounts/ID` | POST `{action: deactivate/reactivate/revoke_sessions}`: platform Admin only; platform-admin target changes use reviewed local procedure |
| `/api/v1/projects/UUID/invitations/ID/revoke` | POST `{}`: project Admin, expiring invitation immediately unavailable |

JSON examples (field-name/identifier placeholders are not existing credentials/records):

```json
{
  "project_id": "PROJECT_UUID",
  "queue_seconds": 3600,
  "software_commit": null,
  "items": [{
    "version_id": "APPROVED_VERSION_UUID",
    "device_id": "GRANTED_DEVICE_UUID",
    "expected_artifact_id": "EXPECTED_INPUT_UUID",
    "actual_artifact_id": "ACTUAL_INPUT_UUID",
    "parameters": {"header_bytes": 0}
  }]
}
```

Token responses/private pages use no-store and same-origin referrer policy (corrected 2026-11-05 to support browser form CSRF checks). Save a token privately to the intended CI secret store, never paste it in a URL/log/Git. Tokens authenticate owner/project/device/version scope; they cannot manage accounts/approvals even if owned by a platform administrator. Revocation/deactivation is checked on every request. The input owner/service or project admin may access input; another project member has no implicit access. Unrelated users cannot enumerate someone else's queued jobs. Project admins may inspect their project's queue. Record names/context are frozen when queued.

## Integrity and known boundaries

PostgreSQL triggers reject UPDATE/DELETE of published TestVersion and input Artifact rows, including queryset/raw SQL updates. SQLite quick-start triggers block UPDATE only; DELETE stays available for Django test flush. The database/OS owner can alter triggers/files and remains trusted; this is not tamper-proof storage. Generated blob IDs never contain filenames/client paths. Path checks reject links/reparse points, files are bounded/exclusively created and downloads verify content. The private artifact root is trusted against local OS races; this is not a sandbox for a malicious OS administrator. A crash between writing a blob and SQL commit can leave an unreferenced private file; no download route can authorize it. A retention/orphan reconciler is future work, with no blind deletion implemented.

Global session_epoch invalidation prevents a revoked session from reviving after account reactivation. Migration to epoch-aware sessions invalidates older sessions without that field; users sign in again. Account deactivation also disables owned service identities/tokens and outstanding invitations; reactivation does not silently restore them. Project membership/grant changes remain project-scoped and checked per request. Approval revocation blocks new submission; dispatch recheck belongs to M2B/M3. No active workload exists to cancel now.

Official Django references used while implementing: [transaction/locking API](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update) and [file upload boundaries](https://docs.djangoproject.com/en/5.2/topics/http/file-uploads/). Tests on PostgreSQL establish submission behavior here, not M3 hardware locking/physical recovery.

## Checks, CI and evidence

Run `scripts/postgres-local.ps1 -Action test` for actual PostgreSQL; `scripts/lab.ps1 -Action test` with explicit LAB_DB=sqlite is quick-start only (PostgreSQL-only cases skip). Other checks: `ruff check web contracts tests`, `pip check`, Django check and `makemigrations --check --dry-run` with configured database. Package with `.venv\Scripts\python -m build --no-isolation --sdist-extract-dir .local/build-source --outdir .local/dist`; keeping extraction in the workspace avoids this machine's sandbox temporary-directory rename failure. Build system tools are pinned in requirements.lock.

Prepared `.gitlab-ci.yml` tests against a dedicated PostgreSQL 16 service, static checks and package build. Configure masked **LAB_CI_POSTGRES_PASSWORD** and **LAB_CI_SECRET_KEY** outside Git; no real lab credentials/personal hardware runner jobs are configured. Tests write `.local/ci-results/tests.log` and artifacts upload after failure. Hosted GitLab/PostgreSQL 16/Linux/Docker execution is **unverified**; actual local evidence is Windows/PostgreSQL 18.1. No remote/pipeline was created/pushed.

Isolated helper `tests/m2a_review.py` refuses any DB except hardware_lab_m2a_review; prepare/check/render/retire create temporary review data, verify real server restart, export non-submitting snapshots and retire random credentials. `tests/m2a_http_smoke.py` tests the live scoped-token/session flow without printing secrets. Temporary review data is not seeded into the human lab DB. Snapshot screenshots show synthetic queued work, not simulation execution. The available in-app browser still cannot establish normal CSRF Origin on sign-in; direct same-origin live HTTP tests passed, and regular browser interactive use/physical phone remain review items.

## Five-minute milestone demonstration

1. Minute 0-1: start native PostgreSQL/portal and sign in to your account. Show health/readiness, offline simulated station and no execution/results.
2. Minute 1-2: publish a draft in Test Catalog, inspect manifest checksum/header policy; admin approves/grants version and device. Change the draft and explain why published content stays unchanged.
3. Minute 2-3: upload two synthetic files with SHA-256, queue the approved version. Show state/IDs/snapshot, unknown firmware and no outcome.
4. Minute 3-4: retry identical key/body and show same job; change queue_seconds with the same key and show 409. Remove the version/device grant or use Viewer and show rejection. API batch with one foreign item creates no jobs.
5. Minute 4-5: point to the competing PostgreSQL connection test and real cold-server restart witness. Show token rotation/session revocation tests and state what Docker/CI/agent execution remain unverified/planned.

Three optional exercises: (1) Why store both the idempotency key and canonical request hash? (2) Why does editing a draft require a new published version instead of updating an approved snapshot? (3) Why do successful queued-job tests prove nothing about exclusive hardware ownership yet?

# Hardware Validation Lab

Independent hardware validation infrastructure portfolio. The Django portal includes approved immutable catalog/input/queued requests plus **M2B.1 administrator-controlled native-agent enrollment and idle heartbeats**, verified on Windows/PostgreSQL. **M2B.2 adds explicit local synthetic CAN file comparison and JSON/human reports. No platform dispatch, device execution, connected hardware or hardware measurements exist.** No Apple affiliation, certification, or Mac hardware validation is claimed.

The [unified roadmap](docs/PLAN.md) and [requirements checklist](docs/REQUIREMENTS.md) map requirements to evidence. See [M2A setup/API](docs/M2A.md), [M2B.1 native-agent setup/demo](docs/M2B_1.md) and [current checkpoint](docs/STATUS.md). M2B.3 adds a supervised local runner, merged after user approval; see [runner setup/test steps](docs/M2B_3.md) and [comparison setup/demo](docs/M2B_2.md). M2B.4 journal/spool/restart handling is now on its review branch; see [journal setup and test steps](docs/M2B_4.md). Merge requires explicit approval. The next implementation task is M2B.5 after review and a new continuation. A roadmap entry does not mean the feature exists.

## Windows quick start (SQLite)

Prerequisites: Python 3.11+ compatible with Django 5.2, Git, PowerShell. This checkout was tested with Python 3.11.4; update the interpreter to a maintained patch before deployment. No privileged installation is automated.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
.\scripts\lab.ps1 -Action migrate
.\scripts\lab.ps1 -Action bootstrap
.\scripts\lab.ps1 -Action run
```

Open [your local portal](http://127.0.0.1:8765). Bootstrap asks for your own email, project name and password; there are no default or shared accounts. `scripts/lab.ps1` creates an ignored random secret in `.local/secret.txt` and explicitly opts into localhost development and SQLite. It does not read `.env`; `.env.example` documents the environment contract. If PowerShell blocks this script, use the direct Python commands below; do not weaken your execution policy.

```powershell
New-Item -ItemType Directory -Force .local
$env:LAB_LOCAL_DEV='1'
$env:LAB_DB='sqlite'
$env:LAB_SECRET_KEY = .\.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(50))"
.\.venv\Scripts\python web/manage.py migrate
.\.venv\Scripts\python web/manage.py bootstrap_lab
.\.venv\Scripts\python web/manage.py runserver 127.0.0.1:8765 --noreload --insecure
```

Keep the same secret across sessions (the helper handles this). `--insecure` serves local CSS while DEBUG stays false; it is a Django development-server flag, not a change to Windows security. Always bind loopback. Phone-sized layout can be reviewed with browser device emulation; access from a physical phone is not configured because this milestone remains localhost-only. Port 8000 was unavailable on this machine; 8765 worked. Stop with Ctrl+C.

## PostgreSQL integration setup

Docker CLI is present but its engine remains unavailable. PostgreSQL 18.1 was found under `C:\Program Files\PostgreSQL\18\bin` despite not being on PATH. An isolated SCRAM-authenticated workspace cluster was used for actual M2A tests. No Windows service, existing cluster or privileged installation was modified. Use [M2A's native PostgreSQL instructions](docs/M2A.md) for this machine, or the Compose/non-container alternatives below.

When an existing Linux-container Docker engine is available:

```powershell
$env:PGDATABASE='hardware_lab'
$env:PGUSER='hardware_lab'
# Set PGPASSWORD privately in your shell; never paste it in Git or screenshots.
docker compose -f deploy/compose.yaml up -d
$env:LAB_DB='postgres'
.\scripts\lab.ps1 -Action migrate
.\scripts\lab.ps1 -Action test
.\scripts\lab.ps1 -Action bootstrap
.\scripts\lab.ps1 -Action run
```

Compose requires PGPASSWORD and binds PostgreSQL to loopback. `postgres:16` follows the maintained major series; resolve and record an image digest when integration is first exercised. Do not run destructive volume removal. Some older Docker installations use `docker-compose` instead of `docker compose`; validate your installation first.

Non-container alternative: use an already installed PostgreSQL 16+ server on Linux/WSL2 or Windows, create a dedicated login/database owned by that login, and set PGDATABASE, PGUSER, PGPASSWORD, PGHOST, PGPORT. Use `psql` interactively for password entry, not command-line password arguments. Django's tests create a separate `test_hardware_lab` database, so use a dedicated local integration account with CREATEDB during testing. Never point tests at production. On Linux: use `.venv/bin/python`, set the same environment, then run `python web/manage.py migrate`, `test lab` and `runserver 127.0.0.1:8765 --insecure`. Default settings expect PostgreSQL unless SQLite is explicitly selected.

**PostgreSQL 18.1 passed M2A submission/immutability/restart tests; Docker/PostgreSQL 16 configuration is unverified.** These tests do not prove M3 scheduler/resource ownership, which is not implemented. SQLite proves no PostgreSQL concurrency properties. WSL2 remains a future backend target, not proof of Windows USB access.

## Checks and learning

```powershell
.\scripts\lab.ps1 -Action check
.\scripts\lab.ps1 -Action test
# With the same LAB_* environment set:
.\.venv\Scripts\python web/manage.py makemigrations --check --dry-run
.\.venv\Scripts\python -m pip check
```

See [current evidence and checkpoint](docs/STATUS.md), [architecture](docs/ARCHITECTURE.md), [security](docs/SECURITY.md), [decisions](docs/DECISIONS.md), [milestone plan](docs/PLAN.md), and [five-minute demos and interview exercises](docs/DEMO.md). No commits or remote synchronization are automatic.

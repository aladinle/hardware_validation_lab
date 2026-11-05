# Five-minute milestone demonstrations

These M0/M1 scripts describe the existing portal. Future gate names/acceptance follow the reconciled PLAN; see REQUIREMENTS for a separate five-minute review of the merged roadmap. Planned future demonstrations are not runnable evidence today.

## M0 foundation (five minutes)

1. Minute 0–1: open README, show the empty-origin repository and current `codex/m0-m1-portal` branch with `git status --short --branch`. Explain that nothing was committed/pushed or hosted.
2. Minute 1–2: show requirements.lock and `.env.example`. A virtual environment isolates this project's Python packages. Environment variables choose the database and keep secrets out of source.
3. Minute 2–3: run `scripts/lab.ps1 -Action check`, inspect the initial migration. A migration is a versioned recipe that creates/changes SQL tables.
4. Minute 3–4: run `scripts/lab.ps1 -Action migrate` (repeat is a no-op); compare SQLite quick start against documented PostgreSQL alternatives. State that PostgreSQL is unverified.
5. Minute 4–5: start the server and open login. Show the documented boundaries: no execution, no agents, no invented results. Read architecture's request path.

## M1 secure portal (five minutes)

Preparation: migrate, run interactive bootstrap once, start the loopback server. Use your own admin password in a regular local browser. The in-app browser may reject POSTs with Origin:null; do not disable CSRF. Screenshots in docs/screenshots are labeled layout snapshots, not interactive sign-in evidence.

1. Minute 0–1: sign in, point out Administrator role, zero connected/running counts, and explicit execution/discovery notices. Nothing displayed is a hardware measurement.
2. Minute 1–2: open Users & Roles; invite a Viewer, privately transfer the one-use code. In a separate browser session, open Accept an invitation and let the invited person choose a password. No public signup exists.
3. Minute 2–3: sign in as Viewer. Note the missing manager pages and lack of a run button. The permitted catalog is empty until catalog records/grants are added in M2. The permission tests deliberately create distinct test-only records to verify hiding and direct URL denial.
4. Minute 3–4: as admin change the Viewer's membership active state; the Viewer loses project access on the next request. Open Audit Log and inspect the membership/invitation events. Show phone emulation: cards stack, navigation wraps, status remains text.
5. Minute 4–5: run `scripts/lab.ps1 -Action test`. Open `web/lab/tests.py` and explain the Viewer POST, cross-project ID, CSRF and throttling cases. Distinguish an implemented local portal from planned simulator/hardware capabilities.

## Three interview exercises

1. Why does hiding a navigation link fail to provide authorization? Trace one forbidden direct device URL through access.py and views.py.
2. Explain authentication (who you are), membership role (what you may do in a project) and a grant (which record you may access). Why must all three be checked again before future dispatch?
3. What evidence do the SQLite tests provide, and why do exclusive leases and competing workers still need PostgreSQL tests in M3?

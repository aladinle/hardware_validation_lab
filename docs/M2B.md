# M2B in eight reviewable tasks

Decomposed 2026-11-05 at the user's request. The user subsequently authorized M2B.1; **M2B.1 and M2B.2 are now implemented locally**, with setup/evidence in [M2B_1.md](M2B_1.md). M2B.3-.8 remain planned; only explicit local synthetic file analysis exists, with no dispatch or hardware workload execution. See [M2B_2.md](M2B_2.md). [PLAN.md](PLAN.md) remains canonical; this document decomposes the unchanged parent acceptance gate. Evidence is in [STATUS.md](STATUS.md).

## Work sequence

| Task | Deliverable | Completion check | Depends on |
| --- | --- | --- | --- |
| M2B.1 (local, review) | Agent identity and versioned protocol | Native Windows enrollment/contact/rotation and PostgreSQL authority tests passed; see M2B_1.md | Reviewed M2A |
| M2B.2 (local, review) | Trusted CAN comparison plugin and registry | Known fixtures give correct normalized offsets, length counts and PASS/FAIL/ERROR | .1 protocol |
| M2B.3 | Bounded local subprocess runner | Installed plugin runs within limits; timeout/cancel/malformed output and partial setup clean up correctly | .2 |
| M2B.4 | Durable local agent journal and spool | Restart/redelivery recognizes the same execution and cannot launch it twice | .3 |
| M2B.5 | Basic PostgreSQL assignment and agent polling | One authorized queued fixture becomes one durable exclusive assignment with epoch; revoked access/digest mismatch blocks dispatch | .1-.4 |
| M2B.6 | Results and authorized evidence delivery | Versioned JSON/human reports persist; upload replay is safe, conflicts and unauthorized access fail | .5 |
| M2B.7 | Simulator failures, cancellation and second plugins | Attach/detach/crash/disconnect/cancel/cleanup evidence is correct; readiness and file/network/communication simulation extend the registry | .3-.6 |
| M2B.8 | Portal integration and final milestone review | Browser/HTTP -> native simulator agent -> SQL outcome -> authorized report; desktop/mobile states and complete failure matrix verified | .1-.7 |

Work sequentially so each task builds on a reviewed interface. Every task stops with its own checkpoint/demo and optional learning questions. One task can take multiple two-hour sessions; eight tasks does **not** mean eight sessions. The earlier 18-26 engineering-hour figure is a planning estimate for the whole milestone, not a commitment or eight independently measured estimates. Re-estimate after inspecting each task and recording actual checks.

A new request to continue starts the next unfinished task after the preceding review, currently **M2B.3 only**, unless the user explicitly identifies another already-unblocked task. M3 remains outside M2B. Do not enable ordinary dispatch of M2A jobs merely because an intermediate task compiles or passes unit tests. Use isolated synthetic fixtures for development; execution remains explicit, opt-in and fail-closed until its dependencies and safety checks work.

Current checkpoint: M2B.2 has been implemented locally on its user-authorized feature branch. The next unfinished task is M2B.3, only after a new continuation request. The user authorized merging .2 after its checks; this does not authorize .3.

## M2B.1 - agent identity and protocol

Create the installable native Python agent skeleton and typed versioned enrollment, heartbeat, assignment, cancellation, event, result and artifact contracts. Implement administrator-controlled enrollment and separate scoped hashed, expiring, revocable/rotatable agent credentials; do not reuse human passwords or CI tokens. Bind each identity to its permitted project/device assignment. Heartbeat independently of workload activity; initial calls report no work and no connected physical hardware. Preserve strict schema/size/error behavior and browser CSRF rules.

Checks: actual HTTP enrollment/heartbeat; invalid/expired/revoked/cross-agent credentials; inactive or unavailable assigned device scope; no secrets logged. Prove package installation and native Windows startup with no hardware access. Agent identity does not itself grant permission to execute a test. Define interfaces here; no scheduler/workload execution yet.

## M2B.2 - CAN comparison plugin

Implement a trusted installed plugin registry, manifest/schema/capability contracts and the pure CAN payload file comparator using synthetic fixtures. Preserve explicit expected/actual roles, approved reference-header rules, strict hex formatting, nonempty normalized data and payload-relative offsets. Record overlapping positional mismatches plus missing/extra byte counts; do not collapse a leading insertion into one mismatch. Produce deterministic schema-versioned JSON and human mismatch details with input checksums.

Build the actual installed workload package and record its real digest. Publish **new immutable** executable versions when the contract/package is ready; existing M2A metadata-only versions retain their null package digest and execution_available=false. Do not update historical snapshots in place or turn old queued metadata into executable work. Extend the CAN-only M2A parser through validated registry contracts, preserving old request semantics and authorization.

Checks: exact match, substitution, missing/extra bytes, leading insertion, malformed hex, empty payload, forbidden header override, stable report schema/checksum and unknown plugin rejection. Comparison remains file analysis, not live physical CAN capture. No confidential employer data is imported.

## M2B.3 - bounded local runner

Run installed plugins in a separate supervised child process using controlled input/output handles. Implement prepare/execute/collect/cleanup with bounded runtime/output/disk and supported CPU/memory limits. Never accept shell strings, arbitrary executables or client host paths. Add cooperative cancellation, a grace period and supported process-tree escalation on Windows; test Linux where available, explicitly recording platform gaps.

Checks: ordinary PASS, assertion FAIL, setup/plugin ERROR, runner TIMEOUT, malformed output, output overflow, cancellation and partial preparation failure. Clean only owned resources, and retain original outcome/evidence even when cleanup fails. Confirm stopped descendants or report uncertainty and keep the resource unavailable. This is standalone local test execution, without claiming queued-job dispatch or device ownership yet.

## M2B.4 - journal and restart safety

Persist accepted execution ID/epoch and launch state in the native agent's local SQLite journal before starting. Record process identity when known and maintain a per-execution private spool until backend acknowledgement. Redelivered execution IDs return existing status/results. A crash between launch and recording its process ID must enter an uncertain/reconciliation state rather than blindly launch again.

Checks: repeat assignment, agent restart, crash in the launch/acknowledgement gap, retained evidence after upload loss, and repeated acknowledgements. Demonstrate one process start per accepted execution in these observed local scenarios. Ambiguous prior activity stays unavailable until confirmed stopped/readiness succeeds or remains quarantined. Local SQLite is a journal, not evidence for PostgreSQL resource locking or exactly-once physical actions.

## M2B.5 - basic assignment and outbound polling

Add Attempt/Resource/Reservation or Lease state and a separate basic single-scheduler process backed by PostgreSQL. In short transactions, lock and reserve the device and required shared exclusive resources together, create durable assignment/unique claim token/epoch, then commit before the correct agent receives work through authenticated outbound polling. Recheck active requester/service, membership/action, current approval/version/device grants, capabilities and actual installed package digest before dispatch. Enforce bounded single-worker operation and expired queue deadlines; no HTTP worker executes a workload.

Checks on real PostgreSQL: unauthorized/unapproved/revoked/metadata-only/digest-mismatched work cannot dispatch; a queued synthetic fixture receives a durable matching assignment; repeat claim delivers the same identity; an already allocated device/shared resource cannot be assigned again; stale epoch cannot finalize/release ownership. Combine with the reviewed journal/runner in controlled tests. Missing heartbeat or expired lease leaves the resource unavailable; baseline M2B never reuses uncertain activity. Full competing schedulers, parallel throughput/fairness, distributed reconciliation and scheduling remain M3.

Compose gains the separate scheduler definition, with actual Compose execution explicitly unverified if Docker remains unavailable. Native Windows agent stays outside containers. No inbound public agent port is introduced.

## M2B.6 - results and evidence

Add authenticated assignment-bound progress events, result submission, output artifact upload/download and SQL outcome/history. Reports include actual immutable execution/version/configuration/input identity, checksums, units where measurements exist, known timestamps and explicit simulated/file source. Unknown firmware/environment/sensors remain unknown. Preserve the original failure, cancellation status, cleanup/readiness and evidence completeness separately. Generate versioned JSON plus human-readable details; CI CLI/JUnit integration remains M4.

Checks: correct agent/execution ownership, event sequence/dedup, repeated identical uploads/results, conflicting second content, checksum/size/type/path bounds and cross-user/project/service/agent denial. Upload errors retain local spool and incomplete-evidence status; they never produce a false clean completion. A stale attempt cannot finalize or release another allocation. Evidence must be collected and stopped/readiness state known before safe release; failed cleanup leaves quarantine.

## M2B.7 - simulation, cancel and cleanup matrix

Implement explicit simulator attach/detach, PASS/assertion FAIL, timeout, malformed output, agent crash/disconnect, lost assignment reply, upload failure and cleanup failure. Add read-only agent/device readiness and registered simulated file/network/communication workloads to prove plugin extensibility. Native readiness may report observed OS/version/dependencies/free space, labeled as actual host observations; simulated device measurements remain visibly simulated. Never invent unavailable temperature/power/GPU data or contact arbitrary network targets.

Add authorized idempotent queued/running cancellation: Engineers/Operators may cancel their own permitted runs, admins within their scope. Persist requested/acknowledged/termination-confirmed distinctions, preserve evidence, and require stopped/readiness confirmation before release. Recheck relevant revocation; no pending cancellation is shown as confirmed termination. Keep reconnect/restart behavior conservative and quarantine anything not safely resolved; comprehensive distributed recovery remains M3.

Checks: the full injected failure matrix, ownership/cancel scope, safe partial cleanup, reconnect identity without duplicate device insertion, no immediate reuse after detach/disconnect, retained pending evidence, and second plugin registration without editing scheduler internals. Exercise actual native process behavior on available OSs and record any missing platform evidence.

## M2B.8 - end-to-end portal and review

Connect authorized catalog/device compatibility, explicit submission, periodic progress polling, pending/confirmed cancellation, outcome and versioned reports to the existing portal. Show simulation/file source and offline/stale/loading/error states. Adapt progress/history/detail and artifact controls to phone widths with keyboard/label/status checks. Do not represent a filesystem comparison or simulated station as physical hardware validation.

Gate: actual browser/HTTP -> approved executable version -> PostgreSQL assignment -> native simulator agent -> bounded plugin -> SQL outcome and authorized report, with both success and an injected missing-byte failure. Run the inherited M2A permission/idempotency/migration checks and the new M2B failure matrix. Provide actual commands/results, screenshots by evidence type, changed files, platform/CI/Docker limits and a five-minute walkthrough. Do not claim regular-browser interaction from static snapshots or physical-phone access from viewport checks.

M2B passes only after **all eight tasks and the complete parent acceptance gate** pass (or the handoff explicitly identifies an unfinished/blocked check). No task alone is the full simulator MVP. No physical hardware, parallel scheduler proof, broker, hosted CI, service deployment or later milestone is silently included.

## Coverage against the parent M2B gate

| Parent requirement | Tasks |
| --- | --- |
| Installable native agent; scoped enrollment/heartbeat/claim/events/results | .1, .5, .6 |
| Typed schemas, registry, real plugin digest; preserved immutable M2A history | .1, .2, .5 |
| CAN known-answer fixtures, header/offset/length behavior and versioned reports | .2, .6, .8 |
| Supervised bounded process, timeout/cancel/cleanup and owned resources | .3, .7 |
| Durable journal/spool; restart/duplicate delivery cannot start twice | .4, .5, .6, .7 |
| PostgreSQL allocation/epoch, dispatch recheck and fail-closed resource reuse | .5, .6, .7 |
| Artifact ownership/checksum/size/path/content, safe replay/conflict handling | .6, .7 |
| Readiness, file/network/communication simulations and plugin extensibility | .2, .7 |
| Complete attach/detach/crash/disconnect/upload/cleanup failure matrix | .3, .4, .7, .8 |
| Responsive progress/error/cancel/report views and actual evidence handoff | .8 |

## Five-minute planning review

1. Minute 0-1: locate existing M2A evidence; distinguish the completed identity/contact task from the six planned tasks.
2. Minute 1-2: trace a synthetic input through .2/.3 and distinguish assertion FAIL from execution ERROR.
3. Minute 2-3: trace journal-before-launch and PostgreSQL assignment-before-delivery; explain .4/.5 dependencies.
4. Minute 3-4: explain .6/.7 upload replay, pending cancel and quarantine when termination is uncertain.
5. Minute 4-5: describe .8's runnable success/failure walkthrough and what still belongs to M3.

Optional exercises: (1) Why can a pure comparison plugin be reviewed before job dispatch exists? (2) Why must launch uncertainty prevent automatic restart of the same execution? (3) What additional evidence makes eight individually tested parts a complete M2B workflow?

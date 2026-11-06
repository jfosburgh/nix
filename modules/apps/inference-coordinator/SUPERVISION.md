# Supervision boundary — opt-in helper implemented, real GPU commissioning pending

The transaction, mount-pinned cgroup reader, durable journal and read-only
inspector are now assembled behind a narrow root Unix-RPC helper in a separate
`narsil-inference-trial` NixOS output. Persistent subscribed D-Bus job transport,
operator-only boot/bus/reload/mount pin provisioning, immutable store-unit pins
and outer systemd watchdog/cgroup shutdown bounds are implemented. There is no
automatic unknown-intent clearing, repinning, inference replay or admissions.

Tests use fake GPU/backend/cgroup evidence. A real disposable **user `sleep`
unit** passed journaled stop/start/stop signal correlation; the installed system
bus and immutable store artifact reader also passed read-only smoke checks.
**No real Ollama/Strata lifecycle, GPU release, calibration or privileged trial
activation has been performed yet.** Root dry-run/commissioning is pending. Read
`TRIAL.md` before use; this is not unattended production/reboot/recovery readiness.

## Implemented transaction API

`ManagedQuiescence(expected_contract, helper=..., population=..., readiness=...,
expected_version=..., phase_timeout=..., total_timeout=...)` is an async callable
that can eventually satisfy `OllamaLifecycle.quiesce`. Construction performs no
I/O or process operations. It has no default helper or safety callbacks.

- `UnitContract` pins the exact unit, cgroup and managed deployment fingerprint,
  plus required `KillMode=control-group`, final kill enabled, finite stop timeout,
  no automatic restart, lazy startup, no delegation and exclusive control.
- An injected `UnitHelper` implements `snapshot()`, `stop(nonce)` and
  `start_lazy(nonce)`. Each `UnitState` must match the pinned contract and report
  no pending/uncertain job. Mutations must return a `JobCompletion` for the exact
  unit/action/fresh nonce, with actual successful completion, not submission.
- The transaction checks pre-stop state, completes stop, checks inactive state and
  whole-cgroup release, and **only then** requests lazy startup. A missing active
  cgroup is an error. Disappearance is accepted only after correlated completed
  stop and inactive-state verification.
- Startup requires an active/running unit with a new systemd invocation ID, an
  `APIState` with the exact version and no resident models, then a final snapshot
  proving the invocation did not change during readiness. The readiness callback
  must be non-loading and independently query the actual backend; its production
  implementation is supplied by the trial helper as bounded non-loading
  version/residency polling; Type=exec job completion is not HTTP readiness.
- Every async phase and the complete transaction have deadlines. Stop timeout
  must fit strictly inside the phase timeout, which must fit inside the total
  deadline. Helpers/callbacks must cooperate with cancellation; these Python
  deadlines cannot terminate arbitrary code or outstanding systemd jobs.
- Overlapping invocations fail rather than queue. Failures are sanitized and
  leave `uncertain=True`; cancellation propagates with the same uncertainty.
  There is no unconditional `finally: start`, mutating retry, cached success or
  automatic resume. A later explicit call rechecks helper state and performs the
  complete transaction; a still-pending job prevents it from proceeding.

`CgroupReader(root)` walks canonical absolute paths without following symlinks,
reads at most 4096 bytes of `cgroup.events`, validates a unique `populated 0|1`,
and uses the kernel's recursive population summary rather than `MainPID` or a
scan of direct child PIDs. Missing root, malformed events, missing events in an
existing group and unreadable/symlinked paths are errors. A missing group returns
`None` for the transaction to interpret, never independent release proof. The
base reader does not establish mount identity. The separate
`coordinator/cgroup_mount.py` provides `VerifiedCgroupReader(root, expected=...)`
with an explicit `CgroupMount(mount_id, device_major, device_minor, root_inode)`.
Construction does no I/O. Each read checks bounded `/proc/self/mountinfo` for an
exact full cgroup2 mount (root `/`, not a delegated bind subtree), its mountpoint,
ID and device, then checks the opened root inode/device and each descendant and
events descriptor's `/proc/self/fdinfo` mount ID. It rechecks mountinfo before
returning either population or disappearance. Wrong/duplicate/stacked mounts,
nested mount crossings, malformed/missing evidence and identity changes fail
closed, without repinning. Proc evidence reads are bounded and errors sanitized.

Pins are boot/mount-namespace specific and must be provisioned independently by
the trusted supervisor; automatic discovery of a possibly replaced mount would
not prove trust. This reader assumes trusted kernel procfs at `/proc` and a stable
operator-controlled mount/cgroup namespace. It does not defend against privileged
mount changes, mount-ID reuse by a privileged adversary, escaped processes or raw
API clients. Explicit root-only trial provisioning now captures and validates
this pin. The trial supervisor deliberately avoids a private mount/cgroup
namespace so pins refer to the same stable host namespace. Actual activation and
stronger raw-client isolation remain unvalidated; arbitrary root/mount changes
are outside the trust boundary.
Tests use synthetic mountinfo/fdinfo plus temporary files, not real mount changes
or GPU teardown. Bounded local reads are not hard I/O deadlines for arbitrary
filesystems.

Tests cover complete ordering, contract/nonce/result mismatches, false job
acknowledgements, main-PID-zero with populated descendants, group disappearance,
timeout/cancellation and late-stop reconciliation, overlap, startup/readiness
failure and invocation changes, malformed/oversized/symlinked cgroup fixtures,
root/path errors and descriptor cleanup. Test helpers only simulate the evidence.

## Durable job-intent journal and live-session binding

`coordinator/job_journal.py` provides `JobJournal(path, unit=..., identity=...,
boot_id=..., bus_identity=...)`. Construction has no I/O. The normalized injected
boot ID is 32 lowercase hex digits. The required immutable `BusIdentity(bus_id,
manager_owner)` from `coordinator/bus_identity.py` pins the separate D-Bus GetId
GUID and systemd unique owner. Deployment, boot, bus and owner mismatches fail
closed. Standalone storage still supports explicitly constructed **version 2**
headers. Live `SystemdJobSession` requires **version 3**, additionally pinned to
systemd version 262 and `UnitsLoadTimestampMonotonic`; it refuses version-2 or
differently fenced journals. Version-1/unmatched data have no implicit migration,
truncation or repair. No deployed journal files have been accessed or changed.
Pins come from explicit root provisioning, never HTTP inputs. The helper must:

1. Open the existing journal and hold its exclusive nonblocking `flock` for its
   lifetime. Missing is an error; explicit `open(initialize=True)` creates only a
   new file with exclusive creation, fsyncs its header and parent directory, and
   refuses to overwrite any existing ledger.
2. Commit `begin(action, fresh_nonce)` **before** sending a systemd mutation.
3. Commit `submitted(intent, job_id)` only after correlating the actual job; then
   `completed(intent, result)` only after observing its real terminal outcome.
   Acknowledgement of submission is not completion. No automatic retries exist.
4. Keep even a completed intent pending until explicit `acknowledge(intent)`
   bookkeeping after reconciliation. Pending intent blocks every new begin.
   Journal acknowledgement is **not** cgroup release or permission to resume.

All events are append-only bounded JSON lines, fsynced before publishing success.
Replay validates exact shapes, ordering, nonce uniqueness and correlated metadata.
The journal is bounded to 1 MiB (2048 bytes per record); exhaustion fails closed.
There is no automatic rotation, truncation, repair or forgetting of nonces.
A torn tail, invalid data, lock conflict, unsafe file/directory, replacement inode,
write/fsync failure or interrupted append blocks use. A commit failure poisons the
instance until explicit close/reopen and replay. The helper must not submit the
mutation if begin fails, even when the intent might be visible after a failed
fsync. A real child-process abrupt-exit test verifies intent recovery without
Python cleanup; this is not a simulated power-loss durability test.

Directory traversal is no-follow; trusted ancestors and a private owning-UID
final directory are required. Files must be owner-only 0600, single-link regular
files; pre-open checks reject devices/FIFOs and opened identity is rechecked.
`flock` assumes cooperative writers; the owning UID/root and local filesystem
fsync semantics remain trusted. Provisioning must not replace the directory or
ledger behind an active helper. No prompts, tokens or backend responses belong
in these records; identity strings must be nonsecret deployment fingerprints.

Storage operations remain synchronous, serialized inside the narrow helper,
not a general network-handler API or hard filesystem I/O deadline. The journal
itself performs no systemd calls, cancellation or resume. Unknown submission,
submitted jobs and completed-but-unacknowledged intent all block a new session;
there is no clear-unknown API. The trial now supplies explicit pins, live
correlation/reload fencing and outer watchdog/process supervision. Historical /
unknown-job recovery and unattended reload/reboot behavior remain unresolved.
An owner pin alone is still not a process epoch, and even a clean journal never
replaces fresh unit/job/cgroup inspection.

## Read-only systemd inspector (not a lifecycle helper)

`coordinator/systemd_inspect.py` provides `SystemdInspector(executable=..., unit=...,
expected_bus=BusIdentity(...), timeout=..., cleanup_timeout=..., output_limit=...)`.
Construction has no I/O and there is no default discovery/repinning. Only explicit
`inspect()` runs the operator-pinned absolute executable. At entry it checks the
local system bus GetId GUID, then GetNameOwner for `org.freedesktop.systemd1`,
against both explicit pins. All four systemd queries use the **pinned unique
owner**, never the well-known destination: `GetUnit` (not `LoadUnit`), selected
typed Unit/Service reads, then another Unit read to reject observed changes.
Before returning evidence it checks name owner again, then bus GUID, enclosing
the manager queries. A different well-formed GUID or owner permanently faults
that inspector instance; later endpoint recovery does not restore it. The future
supervisor must reconcile and independently authorize new pins. A vanished owner
has no well-known-name fallback or retry.
It never calls `GetAll`, reads environment/credential properties, executes shell
commands, submits mutations, retries commands or enables interactive authorization
or bus service autostart. Child environment is reduced to `LANG=C`/`LC_ALL=C`;
inherited bus addresses, loader injection and caller PATH do not reach the child.
The executable/store path and system-bus/mount namespace must be independently
trusted by deployment; path validation alone does not authenticate an executable.

The returned frozen `UnitEvidence` includes the verified `BusIdentity` and reports current invocation, job ID/path,
process/cgroup and selected stop/restart/delegation/trigger flags. Exact JSON
shapes/signatures, bounded numbers/arrays/strings, expected unit ID, loaded state,
no daemon-reload requirement and coherent active/PID state are required. Wrong
paths, unknown/missing properties, duplicate keys, extra/truncated JSON, stderr
or nonzero exit fail closed with sanitized errors. Property availability/JSON
shapes were checked against installed systemd/busctl 262; incompatible versions
fail rather than falling back to textual parsing or unbounded queries.

Stdout and stderr are independently bounded and read concurrently. One deadline
covers all eight commands (four bus/owner reads and four systemd queries), not a
fresh full budget per command; cleanup has its
own allowance and can extend caller completion beyond that deadline. Only one
inspection runs at a time; overlap is refused. Errors/timeouts/cancellation kill
the child process group, drain/discard pipes with bounded buffers, and reap the
direct child. Late spawn/cleanup tasks stay tracked after caller cancellation;
uncertain cleanup faults the inspector and prevents further commands. Fake
process tests cover output floods, inherited-pipe descendants, late spawn,
repeated cancellation, descriptor cleanup, whole-operation deadline and no retry.
Identity tests include bus restart with reused owner/job ID, owner changes during
and between reads, entry-pin mismatch before any manager query, malformed replies,
permanent mismatch fault and vanished-owner refusal. Journal reopen tests also
refuse bus/owner changes and unpinned version-1 data without modifying the log.

This is not a hard kernel/process shutdown boundary: process creation, event-loop
health, uninterruptible I/O and escaped descendants still require the future
helper's outer cgroup/process supervisor. Process-group teardown is not service
cgroup teardown. These checks pin the bus/connection endpoint within the trusted
local namespace; they are **not a manager-process epoch**. Reexecution preserving
the connection/name, job-ID reuse within that endpoint, name loss/reacquisition
on the same connection, transient A-to-B-to-A unit changes and historical or
unacknowledged jobs are not established by these separate property reads. A future
mutating transport still needs persistent subscription/completion correlation and
an explicit manager-reexecution policy; a numerical job ID plus these pins is
not independently completion proof. Trusted pin provisioning and namespace
isolation remain unwired.
`Job=0` does **not** clear a journal intent or prove absence of pending work.
Unsafe observed policy (for example `Restart=always`, delegation or a socket
trigger) is returned as evidence, never silently promoted to a valid contract.
There is deliberately no mapping to `UnitState` or `ManagedQuiescence`: executable,
unit-file/deployment fingerprint, hooks, lazy startup and exclusive-control
verification must exist first.

A read-only smoke check against the installed unit returned active/running,
no current unit job, `KillMode=control-group`, stop timeout 90000000 microseconds,
`Restart=no` and no delegation. No lifecycle/inference/residency calls were made.
A subsequent smoke check with independently observed GUID/name-owner pins also
passed the new identity checks; no production pin provider or journal was used.
These observations neither approve that unit for managed restart nor prove release.

## Journaled live job transport and assembled helper

`systemd_jobs.py` provides an explicit one-unit `SystemdJobSession`: fixed local
system-bus address, no inherited bus address/interactive authorization/autostart,
unique-owner-addressed calls, matches installed before Subscribe, bounded target
job inventory, and one serialized mutation. Intent is fsynced before StopUnit /
StartUnit (`mode=fail`), then submission is fsynced. Both JobNew and JobRemoved
must match the returned path/ID/unit; early signals arriving before the reply are
tracked. Wrong/duplicate/out-of-order target signals, disconnect, owner change,
reload signals, changed version/load marker, cancellation or timeout fault the
session permanently. No retry, reconnect or guessing from current state occurs.
Successful completion is durable but still pending until explicit acknowledgement
following independent post-job observation. Failed jobs cannot be acknowledged.

An explicit `ManagerFence` pins bus GUID/name owner, version **262**, and
`UnitsLoadTimestampMonotonic`, checked around commands and persisted in the
version-3 journal. This is a **source-reviewed reload-sensitive fence, not a
universal cryptographic process epoch**. Systemd 262's manager serialization and
deserialization call `manager_reloading_start`, which updates the units-load
monotonic timestamp; job-ID state is serialized too. Reloading / UnitFilesChanged
signals also fault the live session. Unsupported versions, changed markers and
stale journals fail closed. Root/PID1/procfs and non-adversarial timestamp
resolution remain trusted. Actual manager-reexec stress testing is pending.
Sources: [manager-serialize.c](https://github.com/systemd/systemd/blob/v262/src/core/manager-serialize.c),
[manager.c](https://github.com/systemd/systemd/blob/v262/src/core/manager.c), and
[systemd D-Bus job subscription contract](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html).

`deployment.py` pins operator-reviewed immutable root-owned Nix-store unit/config
artifacts and their digests. It refuses generator source, drop-ins, reload-needed
state, wrong fragment resolution, symlinked artifact opens, writable/oversized or
changed data. Root-owned sticky store ancestors are allowed; actual artifacts
must be root-owned and read-only. This authenticates exact reviewed files, not
the semantics of arbitrary commands: API-only/lazy startup and exclusive local
control remain operator/deployment obligations. The trial generates the manifest
from its NixOS-generated Ollama unit, not by blessing a live unit.

`managed_helper.py` implements UnitHelper over this deployment, safety policy,
inspector, journaled session and mount-pinned population reader. It verifies all
observations; stop acknowledgement additionally requires inactive state and an
empty/disappeared whole cgroup after actual completed stop. Start is refused
without a fresh stop proof in that helper instance, rechecks emptiness, permits
one attempt, requires a new invocation and populated active cgroup, then acknowledges.
The outer transaction checks non-loading API readiness and final invocation.

`supervisor_rpc.py` allows only quiescence of the configured backend, no arbitrary
unit/action/command arguments. Accepted operations survive client disconnect;
errors/timeouts fault the server. `helper_service.py` has separate explicit
provision/serve modes. `provisioning.py` securely persists new private boot/bus /
load-marker/mount pins without replacement; runtime only loads existing pins.
`default.nix` configures root helper and unprivileged API separately, watchdogs,
finite shutdown/cgroup bounds and no automatic restart/resume. The root helper
uses the stable host mount/cgroup namespace; root/mount adversaries and raw local
GPU/API clients remain outside the enforced boundary. See `TRIAL.md`.

Tests cover journal integration, fake transport ordering/faults/restarts,
manifest/pin files, whole transaction assembly, peer auth and disconnects. Real
user-unit job transport passed; **real privileged backend commissioning is still
pending**, and no unknown-intent recovery/automatic clearing exists.

## Preliminary unit safety policy (pure, not deployment approval)

`coordinator/unit_policy.py` adds immutable `UnitSafetyPolicy(unit, cgroup,
bus_identity, stop_timeout_usec, service_type)`. Its explicit `check(evidence)`
performs no I/O and returns no authority object or `UnitState`. It rejects
mismatched unit/bus/cgroup, visible jobs/control processes, non-control-group
kill mode, disabled final kill or a final signal other than SIGKILL, differing
finite stop timeout, automatic restart, delegation, triggers, transient units,
manual-control refusal and remain-after-exit. Only explicitly pinned `exec` or
`simple` service types and coherent active/running or inactive/dead observations
are accepted. Type checks reject bool/int equality bypasses in hand-constructed
dataclasses. Synthetic tests cover each rejection and inactive observations.

This is a necessary preliminary gate, **not a managed deployment validator**.
An inactive observation, empty cgroup path or `Job=0` never proves release or
clears a journal intent. The function cannot establish freshness or atomicity;
it trusts the inspector/provisioned pins and must eventually be used alongside
fresh evidence, durable job correlation and independently validated executable,
unit-file/configuration fingerprint, hooks, lazy startup and exclusive control.
Manager reexecution/epoch policy remains unresolved. No helper/runtime wiring
or real service inspection/mutation is added by this module.

## Ownership and scope

The coordinator will invoke a narrow supervisor for an explicitly registered
**local** backend. Backend IDs map to operator-configured systemd unit identities;
HTTP callers, model IDs and operation strings must never select units or command
arguments. Only initial Strata/Ollama local ownership is in scope. Neither mode
switching nor coordinator reconciliation may stop unrelated/remote services.

The trial uses a privileged helper rather than running the network-facing
coordinator as root. The helper exposes only
approved stop/inspect/start operations, no shell commands, arbitrary units,
arbitrary PIDs, signal numbers or filesystem paths. Credentials and inference
bodies never enter helper commands/logs. The trial now packages root and coordinator units separately: a root-owned
private Unix socket validates SO_PEERCRED against the dedicated coordinator UID
(or explicit local root operator), and the client validates the root server peer.
Unknown operations/backend IDs and caller-supplied units/commands/paths are refused.
Fake Unix tests cover scope, disconnect, timeout, overlap and bounded messages;
real privileged permission/service validation is still pending.

## Ollama quiescence transaction

The `OllamaLifecycle.quiesce()` callback must return only after this sequence:

1. Scheduler holds the exclusive transition/worker lock; admissions to this owner
   cannot run while quiescence is in progress. No coordinated HTTP inference or
   discovery operation may itself trigger a model load outside that lock.
2. Ask systemd to **stop**, not restart, the configured Ollama unit. Bound both
   command execution and completion of the systemd job. A successfully submitted
   asynchronous job is not a completed stop.
3. Verify the unit is inactive and the entire managed process tree is gone.
   Require `KillMode=control-group`, bounded stop with final kill enabled, and no
   unmanaged/escaped runners. MainPID zero or a dead main process is insufficient.
   On cgroup v2, recursively accounted `cgroup.events populated=0` for the recorded
   unit cgroup is evidence; disappearance is acceptable only after validated unit
   stop/job completion, not an arbitrary missing path. Handle races, delegated
   child cgroups and unit identity changes explicitly and fail closed.
4. Only after verified stop, start the configured unit as an **API-only, lazy**
   server. Never run the existing unit's arbitrary ExecStart blindly without
   validating the managed deployment contract. No startup prewarm/load hooks,
   socket activation, timers, dependent jobs or other actors may reload models.
5. Verify startup job completion and bounded API readiness with the exact
   configured Ollama version and an empty resident list. An API check alone is
   not stop proof; the verified preceding process teardown is essential.
6. Return to `OllamaLifecycle.release()`, which independently verifies version and
   residency. A fresh API starts empty; eviction remains defensive. Actual memory
   settling and measured headroom are checked separately before the next load.

This conservative first strategy sacrifices warm state on each release. Do not
replace it with `systemctl restart`: a restart acknowledgement does not expose
verified stop-before-start evidence to the coordinator. A later lighter strategy
needs equivalent tested proof of absence of active **and pending** work.

## Failure and cancellation

Every phase has a deadline within the lifecycle/whole-admin deadline. A timed-out
control subprocess must be terminated/reaped; that does **not** mean the systemd
job it submitted stopped running. Record uncertain helper/systemd jobs and block
admission until explicit reconciliation has inspected their final state.

Never start the API after an unverified stop. Failed start/readiness leaves the
owner uncertain and admissions blocked. Cancellation must not run an unconditional
`finally: start()` or report release. If a stop completes after its caller times
out, keep the backend stopped until reconciliation; do not silently auto-resume.
Coordinator restart must inspect actual service/job/cgroup state, not trust an
in-memory success flag from the previous process.

The existing lifecycle timeout assumes cancellation-cooperative adapters. It is
not a hard process-kill guarantee. Real supervisor implementation must establish
this cooperation and recovery behavior before it is wired into `quiesce`.

## Isolation prerequisites

Loopback ports are not isolation against arbitrary local clients. Stop/start proof
is invalid if another process can immediately submit raw work during/after API
restart. Initial deployment must at least migrate known clients and prohibit
competing launch/prewarm policies; it must clearly document the remaining trusted
local-process assumption. Stronger enforcement (network namespace/socket boundary
and process/device restrictions) is an unresolved deployment decision, not an
existing guarantee. The helper must also reject configurations where automatic
service restarts or external triggers invalidate the transaction.

## Required helper/deployment tests before real calls

The transaction-level cases below have fake coverage where described above.
Mutating helper/job-completion transport, integration of durable intents with actual jobs/recovery, permission enforcement,
actual systemd job cancellation/recovery and privileged mount/identity races still require
implementation-specific tests; fake dataclass acknowledgements do not prove them.


- Stop job completion vs submission, wrong unit identity and disallowed units.
- Main process gone but child GPU runner/cgroup still populated.
- Missing/stale cgroup paths, nested descendants and unexpected delegation.
- Stop failure/timeout/cancellation never starts another backend or the API.
- Pending systemd job after helper timeout; late stop/start completion and restart
  reconciliation never imply automatic resume.
- Start failure, wrong version, unexpected resident model, slow readiness and
  a unit that prewarms; all fail closed.
- Concurrent drain/reconcile/disconnect/shutdown serialize without duplicate
  restart; non-local backends are never selected for process control.
- Helper permissions, argument injection, bounded stdout/stderr and secret-safe
  errors, plus no automatic retry of mutating operations.

Only after the real helper's tests and the managed unit contracts exist should an explicitly
authorized real transition exercise stop/restart, residual memory and inference.
The currently installed Ollama unit was inspected read-only: it is active, runs
0.40.11, and reports `KillMode=control-group`. That alone does not establish the
remaining prerequisites above, and its current network exposure is not the target
private deployment.

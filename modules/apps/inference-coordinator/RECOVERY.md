# Historical: first commissioning failure, staged operator cold reset

**Not the recovery procedure for the current personal-use router.** The user
chose ordinary restart/reset behavior instead of this supervision framework.
See `README.md`. The new service never opens these old journals/pins. Do not rerun
these one-off archival tools or debug the later failed retirement to deploy it.

This is a **one-off, manually gated** procedure for the first trial failure,
not a general recovery command or unattended policy. The operator approved
preparing this cold reset. Each privileged phase requires the operator; stop
between phases and review evidence. Do not run the whole document as a script.

## Original unresolved transaction

The supplied original journal contains:

- boot: `f06ec7e2c2c3478698e5e3fa016ba256`
- deployment: `2a6f33e568235c36d64c44954ad5b76baab12dbba22598e995df70e0178a0b85`
- backend: `ollama.service`
- action: `stop`
- nonce: `3b204dbc33fe4571a7d0b0466bb1bee5`
- submitted job: `60919`
- **no completed or acknowledged record**

The supervisor's Requires/After dependency on Ollama propagated its own backend
StopUnit into supervisor shutdown. It was killed after its 15-second shutdown
bound; Ollama stopped afterward. The original stop result is **unknown to the
journal**. Do not append a synthetic completion/acknowledgement or replay it.

The corrected build uses Wants for backend startup and retains Requires only
from coordinator to supervisor. It is rooted at:

```
/home/james/.local/state/narsil-inference-trial/system-fixed
```

Reviewed build: `/nix/store/5d8y0qma5g73zd3dxiz1b3v5yi4swlz5-nixos-system-narsil-26.11.20261030.1c89083`.
336 tests pass, including three generated-unit dependency checks; those three
also pass for its `strata-server` specialisation. It has not been activated.

## Preconditions and limits

- No manual Strata, inference clients, concurrent rebuilds/daemon reloads,
  service managers, or other operators issuing inference/service mutations.
  Keep this exclusive maintenance window through provisioning.
- No mode switch, target isolation, reboot or graphical logout.
- Root, PID1, kernel cgroup accounting and Nix-store content are trusted.
- Stop all four trial services to remove both controllers and managed workers.
  Check kernel whole-cgroup population, not only MainPID or an HTTP response.
- If a command times out/fails, evidence changes, a pending job remains, a
  cgroup is populated, or an old process/listener survives: **stop**. No retry,
  archive, restart, or fresh pin provisioning is authorized by that failure.
- This establishes a *new* quiescent boundary. It cannot recover the lost
  JobRemoved signal, establish the old job's historical result, or defend
  against arbitrary local GPU processes. Preserve the uncertainty as evidence.

## Phase 1 — explicit independent stop, no restart or archive

This is a new root/operator maintenance action, not replay by the old helper.
Ollama and the failed helper are already stopped; stop Strata and the entire
trial control plane as well:

```sh
sudo systemctl stop inference-coordinator.service inference-supervisor.service strata.service ollama.service
```

The operator completed this step. The first paste accidentally split off
`ollama.service` as a separate shell command; the first three were stopped.
The operator then separately ran `sudo systemctl stop ollama.service` and
reported completion. Do not run prepare/calibrate or activate the fixed build yet.

## Phase 2 — independent read-only verification (agent/operator)

After phase 1, inspect all four units and verify:

1. No active/activating/deactivating state, no main/control PID, no unit job;
   no global outstanding systemd jobs. Reject automatic restart/trigger policy.
2. Under a freshly observed and explicitly verified full host cgroup2 mount,
   each expected `/system.slice/{unit}` is missing or recursively unpopulated.
   Read twice around the unit/job checks, with unchanged mount/boot/bus/manager
   identity. Inspect the provisioned pins separately before reuse; do not
   silently repin an existing session.
3. No listeners on 8080, 11434, 12434, 18080, 18081; no surviving known manual
   Strata/managed backend/controller process. RAM/VRAM observations supplement,
   not replace, kernel cgroup proof. Unrelated desktop GPU allocations can stay.
4. The journal is still exactly the supplied submitted-stop history, with no
   subsequent event. No measured configuration exists and no controller is
   running. Root-only file inspection must avoid the secrets directory.

A missing cgroup/Job=0 alone is **not** historical completion proof. The combined
operator stop plus fresh independent observations establish the new boundary.
If verification fails, leave old state intact and investigate.

Agent read-only verification after the completed stop passed: all four units
inactive/failed with zero main/control PIDs, no unit/global jobs, no restart or
trigger policy, no trial listeners or known backend/controller processes, and
no published measured config. Two independent whole-cgroup passes returned all
four groups missing under a verified full host cgroup2 mount, with stable
boot/bus/manager/mount identity. This establishes the current cold boundary,
not the historical job result. Root-only exact file/pin/lock checks remain next.

## Phase 3 — preserve old evidence, then prepare fixed activation

Only after phase 2 is reviewed, issue a separate, reviewed root archival command:

- acquire an exclusive nonblocking lock on the existing journal (no writer);
- verify exact journal bytes/identity and safe private root file metadata;
- require only `pins.json` and `jobs.jsonl` in the private state directory;
- archive the **whole original directory**, not individual edited files, to
  `/var/lib/inference-supervisor.abandoned-3b204dbc33fe4571a7d0b0466bb1bee5/state`
  inside a newly and exclusively reserved private archive envelope;
- refuse an existing archive destination; preserve permissions and contents;
- fsync the archive files and parent directory, create a fresh root-owned 0700
  `/var/lib/inference-supervisor`, and fsync the parent again;
- do not touch `/var/lib/inference-coordinator-secrets`, fabricate completion,
  remove/overwrite the archive, or automatically run any later phase.

The reviewed one-off implementation is `scripts/archive-first-stop.py`, with
17 new fixture tests (353 total coordinator tests pass, including built-unit
checks). It has no service mutations, acknowledgement, credential access or
automatic provisioning. It is pinned to the exact original journal, boot and
reviewed immutable helper dependencies. It requires existing pins to match
both the journal and current manager/mount, and repeats two cold-boundary checks
under one retained exclusive journal lock. Unexpected state fails closed.
Filesystem tests cover no-change inspection, exact-byte refusal, concurrent
writer lock, replaced files/directories, permissions/hardlinks, existing archive
and symlink refusal, and failures before/after rename without rollback/deletion.
The operator ran the privileged read-only check successfully: exact unresolved
journal locked, pins and two cold-boundary passes verified. It reported no state
changed. This satisfies the pre-archive check gate, not archival itself.

Immutable executable (GC-rooted by `~/.local/state/narsil-inference-trial/archive-first-stop`):

```
/nix/store/88ki8kyxdd6dbcchp4m6glax0vsz70b5-archive-first-stop.py
```

SHA256: `6ac23fad528a1a497331a5f0ced5cd05d08e0bd78cb5b87257794718c7bafdd2`.
Completed read-only phase (successful operator output received):

```sh
sudo ~/.local/state/narsil-inference-trial/archive-first-stop --check
```

A later, separately authorized `--archive` invocation repeats every check before
moving the original state directory into the new archive envelope and making a
fresh private state directory. It does not start services or provision pins.
The operator's `--check` passed, then the separate explicit `--archive` action
succeeded. Completed command:

```sh
sudo ~/.local/state/narsil-inference-trial/archive-first-stop --archive
```

The operator reported the original unresolved evidence preserved under the
archive envelope's `state` directory and a fresh private state directory
created, with no service starts or provisioning. Read-only inspection confirms
both root-owned 0700 directories exist, all four services have zero main/control
PIDs and no jobs, and the original trial generation is still current. The
supervisor's old failed status remains historical, not a running process.
Neither privileged mode was executed by the agent. The operator then ran the
fixed-build `dry-activate`; it reported only “would activate the
configuration”, with **no stop/start/reload list**. The fixed closure is still
`5d8y0qma5g73zd3dxiz1b3v5yi4swlz5`, the original closure remains current and all
trial services remain stopped. **Next gate: fixed desktop test activation**:

```sh
sudo ~/.local/state/narsil-inference-trial/system-fixed/bin/switch-to-configuration test
```

The operator completed fixed desktop `test` activation successfully. Read-only
checks confirm closure `5d8y0qma5g73zd3dxiz1b3v5yi4swlz5` is now current and the
installed dependencies are corrected: supervisor Wants Ollama but does not
Require it; coordinator Wants both backends and Requires only its supervisor
among inference services. Both lazy APIs started; Strata is healthy/unloaded at
131072 with no busy/queued work, and Ollama 0.40.11 has no resident models. Only
loopback 18081/12434 are listening. Supervisor/API are inactive with conditions
unmet, as intended; no failed units or running jobs.

The operator subsequently ran fresh prepare. Its supervised Ollama quiescence
succeeded and real Strata short/long inference ran, but measurement failed the
safety-headroom gate and Strata was unloaded. The supervisor is now active with
new state, Ollama is lazy/empty and API/config remain absent. See the historical commissioning notes'
**Current gate** for diagnostic work. This cold-reset procedure is completed;
**do not reuse it** for this different failure/journal. User approval to exceed
the approximate 12 GiB soft target does not itself lower actual-memory margins.
Any failure requires inspection, not a retry or alternative manual `mv`.

## Phase 4 — fixed activation and fresh commissioning (separate gates)

With the old state archived and services confirmed stopped:

1. Run the fixed closure's `switch-to-configuration dry-activate`; review its
   unit/session effects. Conditions must prevent helper/API startup without
   pins/config. Do not assume a prior dry-run covers this changed closure.
2. Only after review, `switch-to-configuration test` the **fixed desktop** build.
   Keep the original boot default; do not select a specialisation.
3. Confirm lazy backend readiness, empty residency, unchanged desktop tuning,
   and skipped supervisor/API with no failed/new unexpected units.
4. Explicitly run the new generation's `sudo narsil-inference prepare`. Existing
   independent credentials are validated/reused, never rotated or printed.
   New pins/journal are provisioned only as this explicit action. The abandoned
   journal remains unresolved in its preserved archive.
5. Review output before reconcile/resume. Any new failure is a new investigation,
   not permission to repeat archival/reset. Real calibration, native rejection,
   handoff/streaming/cancellation/priority checks remain commissioning gates.

# Personal-use Narsil inference router

This replaces the earlier journal/pinned-manager commissioning framework.
There is **no prepare/calibrate/retire step**, supervisor socket, durable job
journal, manager fence or manual startup reconciliation in the deployed service.
Old trial state is ignored, not repaired, replayed or deleted. The old retirement
command failed before deployment; investigating it is unnecessary for this design.

## Behavior

- One in-memory scheduler, one resident backend at a time.
- Active inference is nonpreemptive. Strata wins at the next scheduling boundary;
  each backend queue is FIFO. Sustained Strata traffic can starve Ollama.
- Strata uses its unchanged tuned profile at private port 18081. Ollama uses
  private port 12434: Gemma4 12B at 64K, Ornith 1.5 9B at 256K (experimental
  coding), and Nemotron Bolt E4B at 64K (helper), each with output cap 8192.
  Qwen 27B is excluded because safe offload falls below the user's 20-token/s floor.
  The bearer-protected loopback front
  door is port 18080. Port 8081 is a client-scope gateway for localhost and
  Blade's actual tailnet source IP 100.64.0.1; it shares the same scheduler.
- Native Ollama chat/generate rejection policy is retained (`truncate=false`,
  `shift=false`, no fake input-token counting). `/ollama/v1/chat/completions`
  translates OpenAI chat/tool requests to this native policy and converts
  native output to OpenAI JSON/SSE, reporting only actual backend token counts.
  Embedding/multimodal and unsupported controls remain off.
- Startup restarts Strata to kill leftover work, reconciles/unloads Strata,
  restarts Ollama and verifies empty residency, then automatically enables
  admissions **before opening the listener**. No old requests are recovered.
- Ollama release uses ordinary `systemctl restart ollama.service`, followed by
  readiness and empty-residency checks. Control-group stop semantics kill old
  runner processes; no durable transaction recovery is attempted.
- The HTTP service is unprivileged. A narrow polkit rule allows only its account
  to restart exactly Strata/Ollama. It cannot manage arbitrary units.
- A root oneshot creates missing private client/admin credentials or validates
  existing ones; tokens are never rotated or printed. Standard systemd
  LoadCredential delivers them to the router.
- Crash/restart loses queued/in-flight requests. systemd restarts a failed
  process (5-second delay, rate limited); every startup resets the backends.
  No generation is retried automatically. Runtime lifecycle failure blocks new
  loads; use an ordinary service restart to reset and resume.
- Shutdown is best-effort and bounded by systemd's 35-second stop timeout. Losing
  requests during shutdown is acceptable; the next startup resets old work.

## Blade and Pi

No new hostname or certificate is required. Blade's existing
`https://strata.threegoldenhairs.me` proxy preserves paths to Narsil port 8081:

| Use | API base | Models/context |
| --- | --- | --- |
| Pi `strata` / `strata-server` | `https://strata.threegoldenhairs.me/v1` | Strata, 131072 |
| Pi `ollama` | `https://strata.threegoldenhairs.me/ollama/v1` | Gemma4 12B, 65536; Ornith 1.5 9B, 262144; Bolt E4B, 65536 |
| Local diagnostic requests | `http://127.0.0.1:8081/ollama/v1` | Same coordinator/model limits |

The Pi registry in `modules/apps/agents/models.json` now uses actual registered
model IDs and matching output limits; no direct 8080/11434 routes or advertised
Gemma 160K remain. Existing repo-backed Pi installations pick up that file when
the checkout is updated; open `/model` to reload it. The cloud default model in
`settings.json` is unchanged. The `strata-server` provider remains a server alias.

Pi/Blade use a placeholder API key, **not** the private coordinator credential.
The gateway validates the real socket peer, admits only Blade/localhost,
validates browser origins, injects only the client token in memory, and denies
all admin/model-control paths. Private port 18080 remains bearer-protected.
The inference gateway firewall opens only 8081 on the tailnet interface; the
unit's IP filter permits only localhost and Blade. Blade retains its LAN/tailnet ACL and WAN-SNAT denial, disables request
replay and buffers neither requests nor responses. The existing Strata static
UI has an explicit non-loading GET allowlist; load/unload/settings controls are
not forwarded to raw backends.

Gemma and the excluded Qwen remain installed; the original Gemma/Qwen trial
needed no downloads. Direct live
Ollama tests selected **Gemma4 12B at 64K**: a 56,049-token prompt followed by
256 output tokens generated at **53.2 tokens/s**, with minimum 5.29 GiB VRAM free
and 24.1 GiB RAM available. Prompt processing took 65.7 seconds, separately from
generation. Thinking was disabled; synthetic text-only tests are not a guarantee
for every workload. Larger windows loaded, but are not selected or long-prompt
validated. Qwen 64K with safe 48-layer GPU offload produced only 3.3 tokens/s
after a 56K prompt, so it is excluded; use Strata for stronger capability. Its
automatic offload also violated the VRAM margin (14 MiB free at 64K).
See [`../../../docs/ollama-context-results.md`](../../../docs/ollama-context-results.md).
Gemma cold estimates are conservatively 12 GiB available RAM / 14 GiB free VRAM;
resident floors remain 6 GiB / 512 MiB. These are not worst-case guarantees.
The service rechecks resident memory after loading and unloads on failure.

## Additional agent candidates

Ornith 1.5 9B and Bolt E4B were downloaded and tested directly on the installed
Ollama 0.40.11. Ornith generated 256 tokens at **39.0 tokens/s after 122,946
input tokens (128K window)** and **24.7 tokens/s after 254,018 input tokens
(256K window)**. The latter left at least 2.44 GiB VRAM free and took 214 seconds
of prefill. Bolt generated at **66.5 tokens/s after 57,407 input tokens** in its
native 64K window. Both retrieved the initial code and completed a three-turn
file-tool recovery probe. These long-prompt speed tests used thinking off.

Ornith is labelled **experimental coding**, not made a default: real Pi read/edit
smoke tests failed with thinking off; thinking low also failed initially but
passed all six CSV tests after receiving actual failure output. This is a small
smoke test, not broad coding validation or a 254K-codebase reasoning benchmark.
Use Strata for stronger work and always run tests on model-generated patches.

LFM3 could not be pulled: its package requires Ollama >=0.40.13, while native
admission is pinned to 0.40.11. The user chose to leave it pending, not upgrade
or bypass the check. No LFM3 entry is advertised. Bolt is a helper, not a coding
model meeting the user's >=128K coding preference.

256K histories need more than registration: coordinator/Blade request caps are
now **4 MiB**, aggregate coordinator queue cap **16 MiB**, and upstream read-idle
wait **600 seconds** (previously 180, too short for measured 256K prefill).
Inference timeout remains 900 seconds. No keepalive/retry behavior was added.
See [`../../../docs/ollama-agent-model-results.md`](../../../docs/ollama-agent-model-results.md)
for full results and limitations. These source changes require activation on
Narsil and Blade; direct tests do not activate the installed HTTPS gateway.
A temporary local bridge also passed a 1.46 MB / 254K-input-token SSE request,
with its first event after 218s, exercising both raised limits against real Ollama.

## Memory

Cold desktop admission estimates reuse the successful local measurements; they
are ordinary configuration values, not calibration artifacts tied to a boot or
systemd manager. Desktop Strata retains 2 GiB resident RAM headroom. Ollama and
headless retain 6 GiB; VRAM margin remains 512 MiB. Engine tuning, including
`STRATA_RESIDENT_HEADROOM_GIB=6`, is unchanged. The built desktop and headless engine configs were compared to the previous
trial closure and match exactly as JSON. Display-manager and logind unit contents also match.

`services.narsilInference.memoryBudgets` can override cold/resident
`ram_available` and `vram_free` byte thresholds for each backend. These are
admission estimates, not worst-case/full-context guarantees or protection from
other local GPU users. Headless context/tuning is preserved, but its new admission
estimate (desktop cold estimate plus the larger RAM floor) is **not a new
headless measurement**. Desktop is the live commissioning target. Mode switching
remains explicitly blocked while the router is enabled until separately integrated.

## Build and activate

The normal `narsil` configuration includes `nixosModules.inference-coordinator`
and enables `services.narsilInference` by default. There is no separate trial
configuration or activation procedure.

```sh
cd ~/nix
sudo nixos-rebuild switch --flake 'path:/home/james/nix#narsil'
```

No journal retirement, pin provisioning or `narsil-inference prepare` is needed.
Activation starts the installed `inference-coordinator.service`; there is no
transient repair unit or inference-supervisor in the new closure. Startup opens
port 18080 only after reset succeeds; `Type=exec` can appear active before the API
is ready. Look for the `service_ready` journal event before querying status.
A normal rebuild switch activates the service and makes the configuration
persistent. Update the checkout on Blade too, then run its normal
`sudo nixos-rebuild switch --flake 'path:/home/james/nix#blade'` there. The existing
hostname/ACME setup is retained. No manual boot pinning or per-boot preparation.
After Narsil activation, test gateway chat/stream/tool calls. Direct backend
memory/speed tests do not establish that the new gateway is activated.

## Diagnostics and ordinary operations

```sh
sudo narsil-inference status
sudo systemctl restart inference-coordinator.service
journalctl -u inference-coordinator.service -b -n 100 --no-pager
journalctl -u inference-coordinator.service -f
journalctl -u strata.service -u ollama.service -b -n 100 --no-pager
```

The router emits structured JSON journal events:

- `startup_reset_begin`, `backend_restart_begin/complete/failed`, `service_ready`;
- `request_queued` (ID, backend, body byte count and queue length);
- `backend_prepare_begin/complete`, `owner_release_begin/complete` (durations);
- `memory_admission` (observed and required free RAM/VRAM bytes, model/context);
- `inference_begin/complete/interrupted` (ID, queue wait, elapsed time);
- upstream/control response status, cancellation/disconnect and queue expiry;
- admin actions, lifecycle faults, HTTP/worker errors and shutdown events.

Errors include exception **types and stack file/function/line locations**, plus
bounded systemctl stderr/exit codes where appropriate. Arbitrary exception
messages, locals, bearer headers, prompts, full request/response bodies and
query strings are not logged. Existing backend/engine logs remain separate and
may have their own logging policies. The `X-Request-ID` response header matches
the scheduler ID in journal events for correlation.

If reset fails, check `backend_systemctl_failed` for polkit/unit errors and the
backend journals. If admission fails, compare observed/required byte values.
If a lifecycle fault leaves the service in maintenance, restart the router;
there is no journal repair or intent acknowledgement procedure. Authentication
and protected drain/reconcile/resume controls remain available, but normal
startup does not require them.

## Validation status

**434 inference tests and 21 mode tests pass**, with all built-unit/Blade and
installed-Pi optional checks enabled. This includes real Pi CLI chat and a
read-tool/result/continuation round trip against fake native backends through
the actual gateway/scheduler/bridge; it does **not** mean live Qwen inference
has passed. The installed Pi model listing also shows the new registered IDs,
contexts and output limits.

Both normal host builds passed:

- Narsil: `~/.local/state/narsil-inference/system` ->
  `/nix/store/2v70b2r3s86jr37vbw4rindc5a9b08ch-nixos-system-narsil-26.11.20261030.1c89083`.
- Blade: `~/.local/state/narsil-inference/blade` ->
  `/nix/store/sh5vz4knhk41vxv694rc8p51914x1dcf-nixos-system-blade-26.11.20261030.1c89083`.

These gateway/model updates have not been activated. Blade SSH inspection was
unavailable (authentication denied); no remote service mutation was attempted.
It is ready for a normal rebuild switch; it has not been activated by the agent.
The earlier live-startup-validated closure currently running is:
`/nix/store/1r6mfdfajjnqd4qh9ljmxldwzrd4sfg0-nixos-system-narsil-26.11.20261030.1c89083`,
rooted at `~/.local/state/narsil-inference-trial/system-personal`.
The packaged CLI imports/runs with only aiohttp (no dbus-next runtime dependency).
Router logs use the existing persistent system journal (`/var/log/journal`).

Earlier real coordinated handoff, SSE/NDJSON completion, active Ollama
cancellation/release/recovery, strict priority/FIFO and loaded-state drain passed
with the shared scheduler/protocol adapters. The new ordinary-systemctl/polkit
integration **passed live startup**: at 20:06:38–20:06:40 the service restarted
Strata (0.834s), unloaded it, restarted Ollama (0.427s), verified release and
logged `service_ready` with admissions=true. Protected status confirms idle,
maintenance=false, reconciled=true, no owner/lease/work/fault. Agent confirms
all three services active, Strata unloaded and Ollama empty. New-lifecycle
inference/handoff has not yet been exercised. The user then requested normal, default deployment: module/option/marker
names were changed to `inference-coordinator`, `services.narsilInference` and
`/etc/narsil-inference-coordinator`, the separate trial flake output was removed,
and the service was added to `narsil`. A normal `#narsil` rebuild switch now
includes and persists it. That renamed/default configuration has been built;
it has not yet been activated. Unit
fixtures cover startup reset/resume ordering, startup failure, restart/readiness,
restart failure/timeout, limited unit selection, memory telemetry and log
redaction; built-unit checks cover permissions/dependencies/config/no supervisor.
Legacy supervisor tests remain regression tests of unused code, not deployment
requirements. Old scripts under `scripts/` are historical and should not be used
to deploy or recover this personal-use service.

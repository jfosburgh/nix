# Narsil inference coordinator

## Latest: additional agent candidates, 128K–256K coding preference

User approved Ornith 1.5 9B, Nemotron Bolt E4B and LFM3 1.7B trials, retaining
>=20 output tokens/s and requesting >=128K, ideally 256K, for coding models.
Ornith and Bolt were downloaded; LFM3's manifest requires Ollama >=0.40.13.
User explicitly selected **leave LFM3 pending** rather than update the pinned
0.40.11 runtime. No LFM3 registration or version bypass was added.

Source now serves/registers Gemma 64K, **Ornith 256K (experimental coding)** and
**Bolt 64K (helper)**. Ornith passed 122,946/254,018-token synthetic prompts at
39.0/24.7 output tokens/s; Bolt passed 57,407 tokens at 66.5 tokens/s. Both passed
initial-code retrieval and file-tool error recovery. Ornith's real Pi CSV repair
failed with thinking off; thinking low also failed first but passed all six tests
after feedback. It is not a default or broadly validated coding replacement for
Strata. No Strata tuning/default cloud model changes.

Coordinator/Blade body limits raised to 4 MiB, queue byte cap to 16 MiB, and
upstream idle wait to 600s to accommodate measured 214s Ornith 256K prefill.
Source changes are not activated; coordinator remains stopped for direct testing.
See [agent model test details](ollama-agent-model-results.md).

## Earlier live Ollama decision (supersedes original two-model targets below)

Direct live tests selected **Gemma4 12B at 64K context / 8192 output cap**.
A 56,049-token prompt followed by 256 output tokens sustained **53.2 tokens/s**,
with minimum 5.29 GiB free VRAM and 24.1 GiB available RAM. Prompt evaluation
was a separate 65.7 seconds. Qwen 27B at 64K left only 14 MiB VRAM free with
automatic placement; safe 48-layer offload passed memory but generated only
3.3 tokens/s after a 56K prompt. The user rejects Ollama profiles below 20
tokens/s and will use Strata for stronger work. Qwen is therefore removed from
the service allowlist and Pi registry, not deleted from disk. Experimental GPU
layer plumbing was removed rather than retaining unnecessary complexity.
Gemma loaded at up to 256K, but the near-full 256K prompt was cancelled after
the speed requirement; 64K is the validated selection, not a maximum claim.
See [full test results](ollama-context-results.md). Configuration changes still
need normal activation; direct tests did not activate the gateway or switch modes.


## Current direction: personal-use service (supersedes the recovery framework)

The user explicitly rejected production-style failure/recovery guarantees. The
service is now simplified around the working in-memory scheduler and protocol
adapters. Ordinary systemd backend restarts replace the privileged supervisor,
journal, manager/mount pins and calibration-envelope deployment dependency.
Startup resets leftover backend work, verifies empty residency and automatically
enables admissions. Crashed/in-flight/queued requests may fail and are not replayed.
No `prepare`, retirement, manual reconciliation or archival recovery is required.

The unprivileged router gets narrowly scoped polkit permission to restart only
Strata/Ollama. Startup and lifecycle operations, request IDs/queue waits, model
load/unload timing, memory thresholds/observations, upstream status, cancellation,
faults and redacted stack locations are logged as JSON to the journal. No tokens,
prompts or response bodies are logged by the router. Strata tuning/config is
unchanged; desktop 2 GiB / Ollama/headless 6 GiB RAM floors are retained.

**Operational documentation:** [`../modules/apps/inference-coordinator/README.md`](../modules/apps/inference-coordinator/README.md).

The service is now included/enabled in normal `#narsil`, as
`nixosModules.inference-coordinator` / `services.narsilInference`. There is no
separate trial output or deployment sequence. Deploy with:

```sh
cd ~/nix
sudo nixos-rebuild switch --flake 'path:/home/james/nix#narsil'
```

The normal `#narsil` build passed, with **418 inference tests + 21 mode tests**.
It is rooted at `~/.local/state/narsil-inference/system` ->
`/nix/store/wn8mj3awrifjqypww8pmgff3k0s3mpy7-nixos-system-narsil-26.11.20261030.1c89083`.
Default enablement and absence of the old trial marker are tested. The old trial
flake output/module/option are removed, and configured input policy is now
`native-reject` (the old spelling is accepted only for legacy fixtures/configs).
No special deployment command is needed beyond a normal rebuild switch.
This renamed/default configuration has not yet been activated. The
current running closure is the earlier simplified-service build at
`~/.local/state/narsil-inference-trial/system-personal`,
now activated for this boot; its resolved target is
`/nix/store/1r6mfdfajjnqd4qh9ljmxldwzrd4sfg0-nixos-system-narsil-26.11.20261030.1c89083`.
**417 tests pass**, including built-unit checks. Both desktop and headless Strata
engine configs match the previous closure exactly; display-manager/logind units
are unchanged. Live startup/systemctl/polkit passed at 20:06:38–20:06:40:
Strata restart 0.834s, verified unload, Ollama restart 0.427s, `service_ready`
with admissions=true. Protected status is idle, maintenance=false, reconciled=true,
no owner/lease/work/fault. Agent confirms services active and both backends empty.
Shared routing/handoff/stream/cancel/priority/FIFO passed in the earlier trial;
new-lifecycle inference/handoff has not yet been exercised. The persistent system
profile still has no coordinator unit, so use normal `nixos-rebuild switch --flake
'path:/home/james/nix#narsil'` for persistent deployment; current
activation alone does not establish the reboot default.
The failed retirement attempt is superseded, not something to debug or retry.
Existing trial state and the old unresolved archive are untouched and unused.

## Pi / Blade / installed-model completion (latest source, pending activation)

User requested end-to-end Blade routing and Pi registration, choosing **both
Ollama models sized to fit**: start Gemma 12B at 8K, target Qwen 27B at 64K and
reduce if live memory requires. `/api/tags` and non-loading `/api/show` confirm
both `gemma4:12b` (Q4_K_M, 11.9B) and `qwen3.8-27b-64k:latest` (IQ4_XS, 27.3B)
are installed. No new pull is needed; old extra aliases are left on disk.

Implemented normal `#narsil` gateway port 8081 in the same unprivileged router:
only actual Blade IP 100.64.0.1 and localhost are accepted; origin checks precede
client-scope token injection in memory; no admin/raw model controls. Private
18080 retains bearer auth. Explicit static non-loading GETs serve the old Strata
UI. Blade's existing HTTPS hostname and upstream port now reach the coordinator:
`/v1` -> Strata, `/ollama/v1` -> Ollama. Existing LAN/tailnet/WAN-SNAT ACLs are
retained and Nginx retries explicitly disabled; no new DNS/certificate needed.

The new OpenAI chat bridge converts full text/tool history and streams to native
Ollama `/api/chat`, preserves truncate=false/shift=false and fixed context/output
caps, translates JSON/NDJSON to OpenAI JSON/SSE including tool calls and actual
backend usage only. Multimodal/embedding/unknown controls remain rejected.
Qwen initial cold memory estimate: RAM 20 GiB, VRAM 14 GiB (not calibration).
New-service Ollama loads recheck resident memory after loading and unload before
failing if the resident headroom floor is missed.

Pi `modules/apps/agents/models.json` now registers actual Strata/Gemma/Qwen IDs
and correct contexts/output limits, all through the existing HTTPS hostname;
local 8080/11434 and Gemma 160K entries are removed. Cloud default is unchanged.
Repo-backed Pi models reload with `/model` after each host's checkout is updated.
Actual installed `pi --no-extensions --list-models` confirms registration.

**434 inference + 21 mode tests pass**, including built Narsil/Blade unit/config
checks and real installed Pi CLI chat plus read-tool/result/continuation against
fake native backends through the actual gateway/bridge. Both host builds passed:

- Narsil root `~/.local/state/narsil-inference/system` ->
  `/nix/store/2v70b2r3s86jr37vbw4rindc5a9b08ch-nixos-system-narsil-26.11.20261030.1c89083`.
- Blade root `~/.local/state/narsil-inference/blade` ->
  `/nix/store/sh5vz4knhk41vxv694rc8p51914x1dcf-nixos-system-blade-26.11.20261030.1c89083`.

These gateway/model changes are **not yet activated**. Blade SSH authentication
was unavailable; no remote mutation attempted. Next: normal rebuild switch on
Narsil and on Blade with this updated checkout, then live gateway chat/stream/tool
and real Qwen 64K memory tests (reduce both config and Pi context if necessary).
Do not equate registration/installed weights/fake-backend tests with passed live
Qwen inference. No mode switch/logout occurred or is implied.

## Historical design and trial chronology (superseded where inconsistent)

Historical status: opt-in desktop trial active with corrected systemd dependencies. First unresolved stop journal was explicitly preserved by guarded cold-reset archival. Second `prepare` successfully supervised Ollama stop/restart and ran real short/long Strata inference, but failed the measured-memory safety gate, then unloaded Strata. A subsequent explicit calibration using the desktop-Strata 2 GiB floor passed both model measurements and all three native oversized-input rejection tests, then published measured config and released both backends. First protected API start failed before listening. The sandbox probe identified root-owned 0440 systemd credential snapshots rejected by the owner-private loader. A separate strict systemd snapshot policy is built (not activated), but its service-GID assumption was disproved: actual file GID is 0 versus service GID 981. The ACL probe confirmed root + named service UID 987 read-only access. The exact descriptor-based ACL loader passed the actual sandbox probe, including runtime construction, telemetry and supervisor socket permissions. The transient repaired API is now running on loopback in maintenance: idle, no owner/lease/fault/work, unreconciled. Operator reconcile/status succeeded: maintenance=true, reconciled=true, fault=null, no owner/lease/work. Operator resume/status also succeeded: maintenance=false, reconciled=true, fault=null, no owner/lease/work. Real coordinated Strata→Ollama→Strata handoff passed with exclusive residency after all three responses. Real SSE/NDJSON completion, active Ollama disconnect/release and Strata recovery also passed. Real nonpreemptive strict queued priority and both-backend FIFO also passed, then Strata was restored. Protected drain from loaded Strata also passed: idle, maintenance=true, reconciled=true, no owner/lease/work/fault; independent backend reads confirm Strata unloaded and Ollama empty. User requested fresh deployment. Root dry activation was reviewed; repaired API, supervisor and both backends are now stopped with zero PIDs/jobs. Guarded retirement followed by corrected desktop test activation is next; fixed units are not yet activated. Earlier group-based build is superseded. Numeric diagnostics and an explicitly approved 2 GiB desktop-Strata available-RAM floor are built separately (not activated); 406 coordinator tests pass, with 21 mode tests previously passing. User permits exceeding the approximate 12 GiB target and accepts about 2 GiB RAM remaining with Strata loaded. Ollama/headless retain 6 GiB RAM headroom and all VRAM margins are unchanged. Full remote/UI deployment and independent tokenizer accounting remain future scope.

## Goal

Keep Strata and Ollama APIs available concurrently on Narsil in both desktop and headless modes, while coordinating model loading/unloading to avoid RAM/VRAM contention. “Concurrent availability” does **not** mean simultaneous model residency or inference: the first version grants exclusive inference ownership to one backend at a time.

Preserve the existing tuned Strata desktop and headless profiles. Add smaller Ollama models for Pi, Norish AI operations, and other non-chat applications. Also provide a lightweight chat web UI for Ollama models; a Strata chat UI is not required.

Design the coordinator for low-friction future addition of other LLM providers and non-LLM inference endpoints (for example TTS and STT). Only Strata and Ollama integrations are in the initial backend scope; do not implement additional providers or audio endpoints now.

The user approved this proposal and requested that it survive the session. Writing this document does not implement or activate any service changes.

## User requirements and scheduling decisions

- Strata runs its desktop configuration in desktop mode and its headless configuration in headless mode.
- Ollama is available in **both** modes.
- A lightweight Ollama chat web UI is available in both modes through the unified `https://ai.threegoldenhairs.me` address, using the coordinated endpoint. No Strata UI integration is needed.
- The unified hostname, UI, APIs and controls are accessible to **trusted LAN or tailnet devices**, not public/WAN clients. The user explicitly approved LAN access as well as tailnet access.
- Backend registration, protocol handling and resource scheduling must be extensible to other LLM providers and non-LLM endpoints without rewriting the scheduler. Those integrations are future scope.
- Maintain **separate FIFO queues for Strata and Ollama**.
- **Only switch to Ollama when the Strata queue is empty and no Strata request is active.**
- Finish active requests before switching; do not interrupt an active Ollama generation when a Strata request arrives.
- At the next request boundary, queued Strata work takes priority over queued Ollama work.
- Inspection/design preceded implementation. The first implementation is an explicitly approved local-only commissioning trial; full deployment remains unfinished.

This is non-preemptive strict Strata priority, not a fair-share scheduler. A continuously nonempty Strata queue can starve Ollama. Do not silently add aging, round-robin scheduling, or guaranteed Ollama service without user agreement.

## Existing installation: verified during inspection

### Nix configuration

- `modules/apps/strata/default.nix`: headless Strata service, generated configuration, ROCm environment, and source-restricted Narsil nginx hop.
- `modules/apps/strata/proxy.nix`: Blade HTTPS proxy and network ACLs.
- `modules/apps/strata/README.md`: existing installation, tuning, deployment and live-switch documentation. Some historical validation/status statements are stale; verify actual state instead of treating every statement as current.
- `modules/apps/ollama/default.nix`: Ollama ROCm package, currently listening on `0.0.0.0:11434`, firewall enabled, declarative pull of `gemma4:12b`.
- `modules/hosts/narsil/default.nix`: imports Ollama and Narsil mode support.
- `modules/hosts/narsil/strata-server.nix`: headless specialisation currently explicitly disables Ollama.
- `modules/hosts/narsil/scripts/mode-worker.sh`: stops managed/manual Strata, activates matching generation, isolates target, and checks loaded headless Strata at 256K.
- `modules/hosts/narsil/tests/test_live_modes.py`: existing mocked lifecycle tests to extend.
- `modules/apps/agents/models.json`: existing local Strata, remote Strata and Ollama client endpoints. Client-advertised context limits are not all aligned with the tuned desktop profile; review deliberately during implementation.

### Mutable Strata installation

- Engine/server/venv: `/home/james/dev/Strata`
- Models/packs/MTP: `/home/james/dev/Strata-data`
- Desktop JSON: `/home/james/dev/Strata/strata-coder-iq1_m.json`
- Manual launcher: `/home/james/dev/Strata/start-coder-nix.sh`
- Desktop tuning report: `/home/james/dev/Strata-data/benchmarks/desktop-tuning/README.md`
- Headless benchmark directory: `/home/james/dev/Strata-data/benchmarks/headless-context/`

Hardware observed: RX 9070 with approximately 16 GiB VRAM, Ryzen 5 5600X, 32 GiB system RAM. The approximate 12 GiB inference budget is a soft target for desktop headroom, not a hard maximum; the user explicitly approved exceeding it if needed during commissioning. It is not a second GPU or a separate memory pool. Actual memory admission remains required. In a later explicit RAM discussion the user accepted about 2 GiB remaining with Strata loaded; the desktop Strata calibration/admission margin is now 2 GiB `MemAvailable`, while Ollama/headless keep 6 GiB and the VRAM margin remains 512 MiB. This does not change Strata's own resident-RAM tuning setting of 6 GiB.

### Existing Strata profiles to preserve

| Setting | Desktop | Headless |
| --- | --- | --- |
| Maximum context | 131072 | 262144 |
| Expert-cache VRAM reserve, MiB | 3072 | 1024 |
| Resident KV window | 32768 | 32768 |
| KV type | INT8 | INT8 |
| Resident RAM headroom | 6 GiB | 6 GiB |
| WMMA | Enabled | Enabled |
| MTP/speculation | Existing settings | Existing settings |

Both use the Qwen3.8 Flash Next coder IQ1_M installation. Do not confuse this Strata model/profile with the separate Ollama Qwen3.8 27B IQ4_XS 64K model.

The reserve flag sizes the expert cache; it is **not a hard total GPU-memory cap**. Desktop final checks previously measured approximately 14.5 GiB total VRAM used, with RAM-pressure caveats. Preserve the measured tuning, but continue observing real memory use.

### Current lifecycle asymmetry

Desktop Strata is manually launched. Headless Strata is managed by a system service. Remote Strata access is currently headless-only. Ollama is currently desktop-only. The proposed design replaces this asymmetry with managed services in both profiles.

## Verified backend lifecycle capabilities

### Strata

Inspected `/home/james/dev/Strata/serve/server.py` and related lifecycle/config code:

- `lazy_load: true` / `--lazy`: start API without loading the text engine.
- `POST /load`: load engine.
- `POST /unload`: unload between requests; returns busy rather than unloading active/queued work.
- `POST /unload?wait=...`: wait for active/queued work within a deadline.
- Generation automatically loads an unloaded engine.
- Successful unload terminates the engine process and releases its RAM/VRAM while retaining the API process.
- AMD free-VRAM checks use amdgpu sysfs through `serve.telemetry`.
- `before_load` hooks and strict failure handling are available, but hooks alone do not implement the required global scheduling policy.
- Unload controls enforce request/body/origin rules; lifecycle adapters must use a correctly formed request and validate actual responses.

Important source locations at inspection time: `Service.ensure_loaded`, `Service.load`, `Service.unload`, `Service.unload_waiting`, `StrataEngine.close`, and HTTP handlers for `/load` and `/unload`. Line numbers will move with updates.

**Switching back is an engine reload**, not resuming a suspended GPU allocation. In-memory prompt/KV cache is lost. Clients must supply required conversation history. Explicit server-side session persistence, if desired later, is a separate feature.

### Ollama

- `/api/ps` lists resident models.
- Empty generation request with `model` and `keep_alive: 0` unloads a model.
- Unload all resident models before giving ownership to Strata, not just the model most recently observed by the coordinator.
- Validate lifecycle behavior against installed Ollama version; current online documentation may differ from the running package.

Reference: https://docs.ollama.com/api/generate

## Architecture

Use one purpose-built, extensible inference coordinator, initially with two protocol-preserving front doors:

```text
Pi / Strata clients -> Strata front door -> Strata FIFO --+
                                                        |
                                                 GPU coordinator
                                                        |
Norish / Pi / web UI -> Ollama front door -> Ollama FIFO -+
                                                        |
                                           exclusive backend ownership
                                                /              \
                                      Strata backend      Ollama backend
                                      loopback-only       loopback-only
```

The coordinator handles admission, lifecycle and streaming transport. It should not reinterpret tool calls, JSON schemas, reasoning content or model outputs.

### Extension boundaries

Keep the scheduling core independent of Strata/Ollama names, HTTP route shapes and text-generation semantics. Implement a small explicit adapter registry and configuration schema, not a dynamic plugin framework or a universal API translation layer.

Separate these concerns:

- **Backend registration/configuration:** stable backend ID, upstream address, supported operations, queue/priority policy, limits, credentials references and resource requirements. Secrets stay outside committed configuration.
- **Protocol adapters:** classify routes/operations, validate admission metadata, and proxy request/response bodies without imposing a shared chat schema. Future adapters must be able to carry multipart uploads, binary audio and streaming responses, not just JSON/SSE. Unsupported transports such as bidirectional WebSocket audio must be explicitly refused until implemented, not accidentally proxied without ownership tracking.
- **Lifecycle adapters:** inspect residency/readiness, prepare/load, release/unload, verify release and reconcile after failures. Capabilities are explicit: a backend may have no unload API, require managed process shutdown, or be remote and need no local model lifecycle. Do not model unsupported unload as successful memory release.
- **Resource arbiter:** own leases on named resource groups rather than assuming every request uses the same GPU. Initially both backends exclusively claim `narsil-gpu`; keep system-RAM checks alongside that lease. Future CPU-only or remote providers can have different/no local-GPU claims and must not require unloading Strata simply because they are registered. Implement only the current single-GPU policy now; concurrent admission for independent resources is future behavior requiring tests and explicit policy.
- **Scheduling policy:** queues keyed by backend ID, with policy separate from transport/lifecycle code. Configure the initial strict Strata-over-Ollama priority explicitly. New providers must declare priority/resource policy; do not silently assign them Strata priority or weaken the approved scheduling rule.

An admitted operation is an opaque upstream job with backend ID, operation/capability, resource claim, deadline and cancellation/completion tracking. The scheduler must not depend on messages, tokens, tool calls or a model-name field existing. Timeouts/body limits can differ by operation. Long-lived future audio jobs need a deliberate lease duration/cancellation policy rather than inheriting chat defaults.

Use generic ownership states plus backend ID (`loading`, `ready`, `running`, `unloading`, etc.), generic metrics labels and backend iteration for drain/reconciliation. Backend-specific logic belongs in adapters. Adding a provider should normally mean adapter/configuration/tests, not edits throughout scheduler branches, mode workers and status handlers. This is an implementation constraint, not a request to build TTS/STT or external-provider integrations now.

### Lightweight Ollama chat web UI

- Choose a lightweight maintained web UI during implementation; no particular product is selected yet. Prefer minimal services/dependencies and no separate GPU-resident components.
- Configure it as an ordinary client of the **coordinated Ollama endpoint**, never the raw backend. Its generations and warmups enter the same Ollama queue as Norish/Pi; it has no priority bypass.
- Offer model selection among approved Ollama models, basic conversation history and streaming. Keep RAG, agents, image generation and audio integrations out of initial UI scope.
- Make it usable at `https://ai.threegoldenhairs.me` over trusted LAN/tailnet access in desktop and headless modes without a graphical login. Choose hosting location, authentication/session handling and persistence deliberately before deployment.
- Account for long queue waits, loading feedback, cancellation and clear timeout errors. Model listing/refresh must not load a model or evict Strata. Disable or mediate model pull/create/delete and manual load controls.
- Do not expose the Strata backend UI/admin controls as a consequence of adding this UI. Preserve any already-required Strata API access separately.

### Unified LAN/tailnet address

The user-facing destination is **`https://ai.threegoldenhairs.me`** for the Ollama web UI and coordinated inference APIs, in both desktop and headless modes. Do not require separate public hostnames for each provider.

Suggested namespace (final paths depend on UI base-path support):

| Path | Purpose |
| --- | --- |
| `/` | Lightweight Ollama chat web UI |
| `/ollama/api/...` | Ollama native API |
| `/ollama/v1/...` | Ollama OpenAI-compatible API |
| `/strata/v1/...` | Strata compatible API |
| `/coordinator/...` | Protected status/administration |

Strip routing prefixes before forwarding to backend adapters. Keep provider namespaces extensible; future integrations get their own paths without assuming OpenAI/chat semantics. Configure server-side UI clients with the coordinated upstream and browser-facing clients with the unified prefixed endpoint. Verify redirects, assets, streaming, origin checks and generated URLs under the selected prefix layout. Do not expose Strata's backend UI by forwarding its entire root namespace.

**Allow trusted LAN and tailnet clients; deny public/WAN inference and UI access.** Follow the inspected dashboard/Strata proxy pattern: permit loopback, `192.168.1.0/24`, `100.64.0.0/10` and `fd7a:115c:a1e0::/48`, but deny OPNsense's `192.168.1.1` source before the LAN allow because forwarded WAN traffic is SNATed to that address. Revisit these rules if the NAT or network topology changes. Never trust arbitrary forwarded headers for authorization. Use Headscale DNS pointing to Blade's tailnet IP and a LAN Unbound override pointing to Blade's LAN IP; DNS alone is not access control. Account for trusted local/container clients such as Norish on Blade without opening public access.

All API, UI, streaming, status and control paths must have the same LAN/tailnet boundary, with additional admin authorization where appropriate. TLS issuance/renewal must not expose the application: reuse the existing ACME infrastructure with its narrowly isolated public challenge location, or another suitable method. Verify trusted LAN/tailnet success and public/router-SNAT denial explicitly. Do not assume wildcard DNS/certificates already cover this name.

Existing `strata.threegoldenhairs.me` access must not bypass scheduling or network restrictions. During migration, retire that vhost or route any temporary compatibility alias through the coordinator with the same LAN/tailnet boundary. Likewise remove/restrict old raw Ollama remote exposure. Decide whether to retain coordinated localhost front doors for local Pi/CLI compatibility.

### Internal endpoints and migration

Preserve local client-facing addresses where practical, while migrating remote clients to the unified hostname:

- `127.0.0.1:8080`: coordinated Strata front door.
- Existing Ollama-facing port `11434`: coordinated Ollama front door, with deliberate network ACLs.
- Move real backends to separate loopback ports; exact ports are an implementation choice.
- Route Blade's unified HTTPS AI vhost to coordinated Narsil front doors in both modes; migrate Pi/Norish base URLs to the appropriate provider prefix.
- Provide coordinated Ollama access for Norish on Blade; do not accidentally retain remote access to the raw backend.

Preserve the source-restricted Blade-to-Narsil hop and existing LAN/tailnet user-facing trust boundary. The following is the **historical existing Strata route**, to migrate under the unified hostname:

```text
trusted LAN/Tailscale client
 -> Blade HTTPS strata.threegoldenhairs.me
 -> Narsil 100.64.0.3:8081, source-restricted to Blade 100.64.0.1
 -> coordinated Strata front door
 -> private backend
```

Loopback binding prevents remote bypass, not bypass by local processes. Make coordinated endpoints the defaults, mediate load controls, and document the boundary. Decide whether stronger local isolation is necessary before claiming exclusive ownership against arbitrary local clients.

### API scope

Preserve routes actually needed by clients, including:

- Strata OpenAI-compatible generation and streaming; evaluate Anthropic/Responses routes if used.
- Ollama native `/api/chat`, `/api/generate`, embeddings, and OpenAI-compatible `/v1` APIs.
- Discovery/health/status routes without model loading.

Explicitly classify routes. Do not blindly pass unknown POSTs or GPU-affecting controls through. Mediate warmups, manual load/unload, image/embedding operations and UI controls. Model-management operations such as pull/create require an explicit policy, not an assumption that every non-chat route is harmless.

## Scheduler

Initial implementation: one admitted inference request globally for the two configured backends, FIFO per backend. Both claim the same exclusive `narsil-gpu` resource. Keep this initial behavior while expressing ownership as a resource lease, so future independent-resource scheduling does not require rewriting transport and lifecycle adapters.

At each admission boundary:

```text
if Strata queue nonempty:
    select oldest Strata request
else if Ollama queue nonempty:
    select oldest Ollama request
else:
    remain idle
```

Examples:

- Strata A active; Ollama X queued; Strata B queued; Ollama Y queued:
  `A -> B -> unload Strata -> X`.
- Strata C arrives during X:
  `finish X -> unload Ollama -> load Strata -> C`; Y stays queued.

Strict priority applies to requests observed by the coordinator, not to a whole Pi agent session. Pi may run tools between inference requests, leaving the Strata queue empty. An optional short handoff grace interval could reduce reload churn in these gaps; default and duration remain to be agreed/tested. Do not introduce session leases or long batching windows implicitly.

Maintain one atomic admission/transition state machine. Queue selection and handoff reservation must be serialized. A Strata request arriving during an already-started Ollama load must not trigger concurrent loads: complete or safely unwind the transition, then re-evaluate priority. Specify and test the exact commitment boundary before implementation.

### Suggested states

`idle`, `loading`, `ready`, `running`, `unloading`, `draining`, `fault`, with backend ID and resource lease recorded separately.

Avoid provider-specific state enums. State names are illustrative; ownership and transition invariants matter more than enum spelling.

## Safe backend handoff

1. Reserve transition under scheduler synchronization.
2. Ensure previous upstream request has actually stopped/completed.
3. Request previous backend unload.
4. Verify release: Strata engine unloaded/exited, or Ollama resident list empty.
5. Check actual GPU and system-memory availability, allowing bounded release settling time.
6. Load/admit next backend.
7. Forward request while retaining exclusive ownership through upstream completion.

If unloading fails or residency is uncertain, **do not load the other backend**. Return a clear error or keep requests queued within bounded deadlines. A memory reading alone is not proof that an active request stopped. Lifecycle confirmation and memory checks complement one another.

Memory admission is a risk-reduction mechanism, not a guarantee against unrelated desktop apps allocating memory after the check. Start with measured conservative per-model requirements; fail closed on unavailable telemetry when it is required for admission.

Avoid competing automatic idle/hook policies that can independently change residency behind the coordinator. The coordinator should be the normal owner of transitions.

## Ollama constraints

Initially configure:

- One loaded model.
- One concurrent inference request.
- Explicit inference-model allowlist.
- Per-model context/output limits and request-size limits.
- Controlled keep-alive behavior; clients cannot force indefinite or conflicting residency.
- All embedding/image/model-warmup requests requiring inference enter the Ollama queue.
- Coordinate model switches inside the Ollama queue as well as backend switches.

Do not silently truncate oversized contexts. Reject incompatible requests with useful errors or use explicitly documented application profiles.

### Model evaluation shortlist

Research direction, not a completed benchmark or installation mandate:

- Qwen3.5 9B: initial general-purpose Pi/Norish candidate.
- Existing Gemma4 12B: quality baseline; test installed quant before replacing it.
- Qwen3.5 4B: straightforward lightweight application candidate.
- LFM2.5 2.6B: targeted extraction/tool-use experiment, not general coding-agent default.
- Ornith 1.5 9B: optional Pi/coding-focused challenger; verify package/templates/parsers.
- Gemma4 E4B: optional; effective parameter count understates total embedding-inclusive footprint.

Start application/Pi tests around 8K–16K/16K context respectively and measure before increasing. Do not inherit the existing 160K Gemma client profile as the default for new lightweight operations.

## NixOS service and mode design

- Manage Strata as a system service in **both** profiles.
- Generate separate desktop/headless configuration using the existing tuning values.
- Keep Strata API alive with lazy engine loading.
- Keep Ollama, coordinator and lightweight Ollama web UI available in both profiles. UI hosting may be on Narsil or Blade; it must not depend on a graphical user session.
- Implement drain/reconciliation against registered local resource owners, initially Strata/Ollama, rather than hardcoding two service names into the coordinator interface. Future remote services must not be stopped by a Narsil mode switch.
- Preserve ROCm runtime libraries, persistent HIP temporary directories, device permissions, service hardening and current network ACLs.
- Make manual launcher usage clearly incompatible with managed ownership; adapt/retire it as the normal launch path.
- Ensure health distinguishes API readiness from model residency; an unloaded model is expected, not an unhealthy service.
- Do not make a routine health check load Strata and evict Ollama.

### Mode switching

Existing worker stops only Strata; this is insufficient once Ollama can own the GPU.

New sequence:

1. Enter coordinator maintenance/drain mode and refuse new work with `503` plus `Retry-After`.
2. Drain active inference with a bounded deadline; define handling of queued work explicitly.
3. Unload both backends and verify GPU release.
4. Activate target NixOS configuration; retain existing generation matching, locking, GC root and recovery protections.
5. Verify correct Strata profile, coordinator and Ollama API readiness without accidentally loading both engines.
6. Resume admissions.

Especially on return to desktop, release **both** models before starting the compositor.

Initial version should not promise transparent queue survival across NixOS activation. Fail queued callers clearly rather than silently replaying requests. Preserve safe rollback and SSH/text sessions. Extend existing mocked live-mode tests.

## Reliability and protocol requirements

- Hold ownership until upstream completion, not response headers or first token.
- Preserve SSE and NDJSON streaming without buffering whole responses.
- Handle downstream backpressure deliberately; do not hold unbounded buffers.
- On client disconnect, cancel upstream and confirm it stopped before releasing ownership. If cancellation cannot be confirmed, drain/stop the backend or fail closed.
- No automatic replay of inference: partial output or tool calls may already have escaped.
- Bounded queue lengths **and bytes**, request bodies and image payloads.
- Separate queue-wait, model-load and inference/stream-idle deadlines.
- Remove disconnected/timed-out queued requests.
- Strict priority may exceed Norish/provider timeouts. Inspect actual app timeout/retry behavior before promising long queue waits.
- In-memory queues initially; interrupted requests are not persisted/replayed after restart.
- Coordinator restart must reconcile real backend residency before admitting work. An orphan backend generation must not overlap a new load.
- Unexpected backend exit/load failure must not leave a permanently held ownership lock.
- Scope credentials and administration endpoints appropriately; do not trust arbitrary forwarded headers.
- Preserve source-network access restrictions on every exposed route, not only generation paths.

## Observability

Expose a protected status endpoint and structured logs containing:

- Current desktop/headless profile.
- Backend owner, transition state, model and residency.
- Queue lengths, oldest waits and request IDs.
- Queue/load/inference/unload durations and errors.
- Actual VRAM and available RAM.
- Maintenance/drain/fault state and last transition reason.

Do not log prompts, recipe contents, images, API keys or full responses by default.

## Validation and implementation plan

### 1. Scheduler and proxy with fake backends

Test:

- FIFO ordering per backend and strict Strata priority.
- Continuous Strata traffic starving Ollama as documented.
- Arrivals at all transition boundaries.
- No simultaneous ownership/load/inference.
- Streaming completion and backpressure.
- Queued and active disconnects/cancellation.
- Queue/body limits and deadlines.
- Busy/unresponsive unload, failed load, backend crash and coordinator restart.
- Model discovery/health not loading models.
- Inference retries not occurring silently.
- Adapter contract tests for Strata and Ollama, plus a fake third backend to demonstrate registration without scheduler changes (not a deployed provider).
- Opaque binary/multipart payload forwarding, lifecycle-capability differences and explicit rejection of unsupported operations/transports.
- Resource metadata and backend-generic drain/reconciliation; do not enable untested independent-resource concurrency.

### 2. Real lifecycle adapters

Repeated Strata/Ollama transitions without mode switching. Measure unload/load time, residual allocations, RAM/VRAM, loss of prompt-cache warmth and actual model inference behavior. No unrelated desktop disruption.

### 3. NixOS services in both profiles

Build/evaluate parent and specialisation, verify units and nginx ACLs, and keep installed/manual paths from competing. Do not activate or reboot as a side effect of writing/building configuration.

### 4. Mode transition integration

Extend existing lifecycle tests for both backend release, maintenance admission, correct profile readiness and safe recovery. Perform real mode switches only with user awareness: entering headless logs out graphical users.

### 5. Client/application evaluation

Pi: real multi-turn read/edit/tool-result cycles, tool-call parsing and completion accuracy.

Norish: inspect actual configured provider/API usage and schema propagation; evaluate ingredient quantities/units, serving semantics, missing information, multiple recipes, no invented ingredients/nutrition, retry behavior and latency. Schema-valid JSON does not guarantee semantically correct data.

Norish runs on Blade; its local `localhost` is not Narsil. Configure a trusted coordinated remote endpoint, not a raw backend port.

Web UI: verify allowed model selection, streaming, queued/loading feedback, disconnect/cancel behavior, LAN/tailnet access restrictions and history persistence. Test the unified hostname from tailnet, trusted LAN and public networks, including all provider/control routes and legacy endpoints; verify router-SNAT sources are denied. Confirm refresh/discovery does not load models, UI requests cannot bypass scheduling, and the UI works in headless mode.

## Open implementation details

Resolve during implementation, without changing approved scheduling semantics:

- Coordinator language/framework and package layout; prefer a small well-tested extensible service over a general LLM gateway. Preserve the protocol/lifecycle/resource/policy boundaries above.
- Lightweight Ollama web UI selection, hosting location, trusted hostname, authentication and conversation-history storage.
- Exact backend ports and final provider path prefixes under `ai.threegoldenhairs.me`; verify UI prefix compatibility, private DNS and TLS renewal.
- Migration/retirement of old endpoints, with explicit LAN/tailnet allow and public/router-SNAT denial tests, and no scheduling bypass.
- Route allowlist and lifecycle/admin authentication.
- Queue sizes, byte caps and per-stage deadlines.
- Optional short anti-thrashing grace interval.
- Idle residency/prewarming defaults; keep APIs available regardless of model residency.
- Memory thresholds calibrated on this AMD/ROCm installation.
- Strata arrivals during Ollama load: implemented/tested as finish load, then recheck priority before inference; validate this boundary with real lifecycle transitions later.
- Whether stronger local bypass prevention is necessary.

## Implementation progress

### Current local-trial increment and operator approvals

The user requested continuing until practical use is possible and approved:

- **Local API trial first**, deferring unified remote migration/UI.
- Local Narsil rebuild/switch and targeted service/model trials are authorized; **ask before any mode switch or graphical logout**. No mode switch/logout has been performed.
- For this first Ollama trial, use exact-version native backend full-input rejection, with forced `truncate=false` and `shift=false`, rather than blocking on independent tokenizer/template accounting. Only native text chat/generate are enabled; Ollama OpenAI, embeddings and multimodal APIs stay disabled. This policy does **not** prove pre-queue token/output reservation; generation may end at context capacity. Real oversize history/default/raw rejection must pass commissioning.

Implemented, built and desktop test-activated; not yet real-GPU commissioned:

- Persistent `systemd_jobs.py` transport: fixed local bus, explicit identity/version/reload-sensitive fence, subscribe before submission, fsynced intent before StopUnit/StartUnit, actual JobNew/JobRemoved correlation including signals before reply, no mutation retry, explicit post-observation acknowledgement and fail-closed disconnect/cancellation/restart. Live transport requires a version-3 journal binding the source-reviewed systemd-262 `UnitsLoadTimestampMonotonic` marker; standalone version-2 storage remains available, but cannot authorize live mutations. This is not a universal process epoch; root/PID1 and timestamp semantics remain trusted, and real reexec stress/recovery is unfinished.
- Reviewed immutable Nix-store deployment artifacts (`deployment.py`), assembled `ManagedUnitHelper` with fresh stop/whole-cgroup proof before one-attempt lazy start, and a root-only provision/load split for boot/bus/manager/mount pins. A narrow UID/peer-protected Unix RPC allows only configured-backend quiescence, with bounded messages/connections, disconnect continuation and permanent uncertainty faults. Unknown pending intent is never cleared automatically.
- Separate opt-in `narsil-inference-trial` NixOS output. Ordinary Narsil configuration remains logically unchanged. Trial services use lazy Strata on loopback 18081, private Ollama on loopback 12434, root supervisor and unprivileged protected API on loopback 18080. No remote/firewall exposure or UI; legacy paths are unavailable rather than bypassing scheduling. Desktop/headless generated profiles preserve all existing Strata tuning. Live mode workers refuse the trial marker before touching services/sessions, pending full integration.
- Explicit operator `prepare` provisions new state/independent private systemd credentials, performs real model calibration and full-input rejection tests, and only then publishes a root-owned measured config bound to the template/profile/device/deployment. No guessed deployable budgets, no-op quiescence or synthetic counters are selectable. Short/long synthetic measurement uses conservative explicit headroom margins, not a worst-case-memory guarantee. The first real measurement ran after dependency recovery: Strata completed short/long inference, but its derived budget failed the safety-headroom gate and no usable config was published. Ollama model measurement/rejection tests have not run.
- `production.py` explicitly wires measured memory admission, native-only policy and real supervisor callback; service startup stays maintenance until separately authorized reconcile/resume. Root/helper and coordinator watchdog/whole-cgroup shutdown bounds are configured. Readiness polls only non-loading APIs within transaction deadlines because Type=exec completion precedes HTTP bind.
- Complete suite: **333 coordinator tests**, **21 mode-lifecycle tests**, using fake backend/GPU evidence. Read-only live bus subscription/identity/fence/store-file checks passed. A disposable **user `sleep` service** passed actual journaled stop/start/stop correlation and was stopped/removed; no inference/mode services were altered.
- Trial parent and headless specialisation both build. GC-rooted output: `/home/james/.local/state/narsil-inference-trial/system`. Offline comparison found greeter/display-manager, user manager, logind, D-Bus and NetworkManager unit files unchanged. `sudo -n` requires authentication; even dry activation needs root. The user selected that they will run `sudo /home/james/.local/state/narsil-inference-trial/system/bin/switch-to-configuration dry-activate` and paste output. **Privileged dry-run and successful desktop test activation received.** It would stop/restart accounts-daemon, Ollama, polkit and systemd-tmpfiles-resetup; reload dbus-broker and firewall; and stop searx-init/searx and remove the searx user/group. No display-manager, logind, user-manager or NetworkManager restart is listed. SearXNG removal is an unrelated migration effect: `docs/searxng.md` requires validating Blade search before removing local search. The user explicitly answered “not validated but go ahead with removal”, accepting local search removal before Blade validation; this activation gate is resolved. Post-activation read-only inspection confirms the trial closure is current, no failed system units, lazy Strata healthy/unloaded at 131072 with no active/queued work, and Ollama 0.40.11 with an empty resident list. Only backend loopback ports 18081/12434 are listening; old 8080/11434 and protected 18080 are absent. Supervisor/API are correctly condition-skipped pending pins/measured config. No mode switch/logout was requested. Current working-tree unrelated changes also enter a `path:` build.

See `modules/apps/inference-coordinator/README.md` for current service operations (this commissioning section is historical). Do not call this actual-use ready until privileged permission/unit tests, real Strata→Ollama→Strata inference/release, calibrated memory, native oversize rejection, streaming/cancellation and queued priority checks pass.

### First privileged prepare failure and pending recovery

The user ran `sudo narsil-inference prepare`. Credentials, supervisor pins and
journal were provisioned; calibration failed at its initial supervised Ollama
quiescence with `Supervisor quiescence unconfirmed`, before the measurement
stage. No calibrated configuration or protected API was published.

Read-only logs show the supervisor became ready at 15:31:40, then immediately
received a stop while attempting Ollama teardown. Its `Requires=ollama.service`
and `After=ollama.service` caused backend StopUnit to stop the supervisor first;
the supervisor awaited its transaction during shutdown, then systemd killed it
after 15 seconds. Ollama stopped successfully afterward at 15:31:55. Current
inspection shows Ollama inactive, no running systemd jobs, no Ollama cgroup,
and Strata healthy/unloaded. These observations do **not** clear any pending
journal intent or authorize a retry.

Fixed the control-plane unit dependencies in
`modules/apps/inference-coordinator/default.nix`: backend startup uses Wants,
not Requires; coordinator retains Requires only on the supervisor. Added three
opt-in built-unit regression tests (`tests/test_nixos_units.py`), checking no
backend stop propagation, retained startup ordering, and coordinator-to-supervisor
coupling. All **336 tests pass** with the fixed desktop closure, and the three
built-unit checks also pass against its built `strata-server` specialisation.

Fixed closure (built, **not activated**):
`/home/james/.local/state/narsil-inference-trial/system-fixed` ->
`/nix/store/5d8y0qma5g73zd3dxiz1b3v5yi4swlz5-nixos-system-narsil-26.11.20261030.1c89083`.
The original `system` out-link is unchanged. Do not activate/restart the helper
or rerun prepare/calibrate yet. The operator supplied the root-only journal:
it contains the version-3 header, `begin` for stop nonce
`3b204dbc33fe4571a7d0b0466bb1bee5`, then `submitted` job **60919**; no
completion/acknowledgement. This is confirmed unresolved intent, not a successful
journaled stop. The user approved preparing a staged cold reset that preserves
this evidence. See `modules/apps/inference-coordinator/RECOVERY.md` for the
one-off manually gated plan. The operator completed explicit stops of all four services (Ollama separately
after a pasted newline). Agent read-only checks passed: no processes/jobs/trial
listeners/config/restart triggers, and two verified full-host-cgroup2 passes
with all four groups missing and stable boot/bus/manager/mount identity.
Prepared a narrowly pinned, immutable one-off archival tool with 17 fixture
tests; **353 total coordinator tests pass** including built-unit checks. It
preserves the entire old directory under a new private archive envelope,
refuses different journal bytes, concurrent writer, changed pins/identity,
unsafe state or non-quiescent services, and never acknowledges/replays jobs or
starts services. See `RECOVERY.md` for immutable path and hash. Immediate next
privileged read-only `--check` was run by the operator and passed: exact
unresolved journal locked, pins and two cold-boundary passes verified; no state
changed. The operator then separately ran `--archive` successfully: original
unresolved evidence preserved at
`/var/lib/inference-supervisor.abandoned-3b204dbc33fe4571a7d0b0466bb1bee5/state`,
fresh private state directory created, no services started or pins provisioned.
Read-only checks confirm both root-owned 0700 directories exist, all four
services remain stopped with zero main/control PIDs and no jobs, and the old
trial closure is still current. The operator then ran fixed-build
`dry-activate`: only “would activate the configuration”, with no listed unit
stops/starts/reloads. The operator then completed fixed desktop `test` activation successfully.
Read-only checks confirm closure `5d8y0qma5g73zd3dxiz1b3v5yi4swlz5` is current,
installed supervisor/backend dependencies use Wants, coordinator Requires only
the supervisor among inference services, healthy unloaded 131072 Strata and
empty Ollama 0.40.11 residency on loopback 18081/12434, and correctly
condition-skipped supervisor/API. No failed units or running jobs. Next is fresh
explicit `sudo narsil-inference prepare`, then output review before any
reconcile/resume. The archived job remains unresolved.
Never synthesize completion or clear the old transaction. No pins or journal were deleted, modified or automatically
acknowledged by the agent.

### Second prepare: real Strata inference, memory-gate failure

On the corrected active desktop closure, the user ran `prepare` again. Fresh
pins/journal were provisioned and the supervisor successfully performed the
initial Ollama stop/whole-cgroup proof/lazy restart. Calibration loaded tuned
Strata and completed both 57-token and 6203-token prompt tests (16 and 31
output tokens), then `derive_budget` rejected the observed load plus required
headroom against baseline availability. Cleanup unloaded Strata. The supervisor
remains active; Strata reports healthy/unloaded, Ollama's resident list is empty,
and the protected API/config remain absent. Do not rerun prepare or reuse the
one-off archival tool on this new state.

The old error omitted the numeric measurements, which existed only in process
memory. Strata's engine log shows roughly 2.7 GiB VRAM free during inference and
systemd recorded a 22.3 GiB service memory peak, suggesting RAM pressure, but
these are not the exact sampled extrema and cannot establish which gate failed.
Calibration requires observed incremental peak use plus 512 MiB VRAM / 6 GiB
RAM headroom; there is **no 12 GiB maximum check**. The user explicitly permits
relaxing the approximate 12 GiB target if needed. Do not confuse this with
permission to lower safety margins or modify preserved Strata tuning.

Added numeric-only failure diagnostics identifying failed resource(s), cold
requirements, baseline availability, observed VRAM peak / RAM minimum and
unchanged margins, plus four regression tests. **357 tests pass** including the
built-unit checks. Diagnostic closure built (not activated):
`~/.local/state/narsil-inference-trial/system-diagnostics` ->
`/nix/store/ddw8pcssbk16gy1w5q644yc55hsq8bm5-nixos-system-narsil-26.11.20261030.1c89083`.
Its manifest and calibration template were compared byte-identical with those
of the active `system-fixed` closure. Thus, after reviewing the current journal
for a fully acknowledged initial stop/start, a separate explicit diagnostic
`calibrate` action can use its operator executable with the **existing active
supervisor**, without activation/daemon-reload/reprovisioning. Do not activate
this closure just to obtain diagnostics: reload changes the manager fence.
Immediate next step is operator root-only read of the **current** `jobs.jsonl`;
then review before any repeat measurement. No retry has been performed.

### Current follow-up: clean journal and approved desktop Strata 2 GiB RAM floor

The operator supplied the current version-3 journal: stop job **62543** and start
job **62544** both completed `done` and were acknowledged. There is no pending
intent in the supplied history. Read-only live boot/bus/manager-fence comparison
still matches that journal (`UnitsLoadTimestampMonotonic=454399737238`); the
supervisor remains active and both backends report empty/unloaded residency.
No reset, archival, helper restart or reprovisioning is needed.

The user asked whether RAM is checked before load, noted roughly 5 GiB current
usage without AI, and explicitly accepted roughly 2 GiB remaining with Strata.
Calibration samples `MemAvailable` before load and throughout loading and both
inference tests, not just idle baseline usage. Implemented **2 GiB RAM headroom
for desktop Strata only**, recorded in observations as `ram_headroom_bytes` and
used in both cold incremental admission and resident checks. Default/Ollama and
headless Strata remain **6 GiB**. VRAM remains **512 MiB**, tuned Strata engine
`STRATA_RESIDENT_HEADROOM_GIB=6` is untouched, and nearly-idle baseline calibration
preconditions are unchanged. A transient minimum below 2 GiB still fails; the
reduced margin provides less desktop-spike protection, not an OOM guarantee.

Three added tests cover exact 2 GiB acceptance, below-floor rejection, invalid
margin refusal, preserved Ollama/headless policy and real assembler flow using
fake measurements; **360 tests pass** including desktop built-unit checks.
Built closure (not activated):
`~/.local/state/narsil-inference-trial/system-strata-2g` ->
`/nix/store/5r699yl3n0zgv0nqjnan92cf9l75z7z5-nixos-system-narsil-26.11.20261030.1c89083`.
Its manifest/template bytes match the active generation exactly. The next
explicit operator action is:

```sh
sudo ~/.local/state/narsil-inference-trial/system-strata-2g/sw/bin/narsil-inference calibrate
```

This loads real models using the existing active supervisor and new margin/
diagnostics, without activating another generation or changing its fence. It
publishes config only after all model/rejection tests pass and does **not**
start the API. The operator subsequently ran this exact command successfully;
see **Successful real calibration** below.

### Successful real calibration — API commissioning next

The operator ran the `system-strata-2g` calibration command successfully. It
completed tuned Strata short/long inference, Gemma4 12B at 8192, native full-
history/default/raw oversized-input rejection, both-backend release and atomic
measured-config publication. Root-owned 0644 config is present at
`/var/lib/inference-coordinator/config.json`; the **active generation's** API
loader accepted it against its own template/device/profile. No new activation,
repinning or inference replay was needed.

Saved observations (GiB; peak VRAM is total device use, not model-only):

| Backend | Peak total VRAM | Minimum MemAvailable | Cold free-VRAM required | Cold available-RAM required |
| --- | ---: | ---: | ---: | ---: |
| Strata desktop | 14.920 | 5.130 | 13.613 | 22.917 |
| Ollama Gemma4 12B / 8192 | 10.503 | 24.615 | 9.301 | 7.645 |

This confirms the earlier 6 GiB RAM margin would reject the observed Strata
minimum, whereas the approved 2 GiB floor admits it. The soft 12 GiB inference
target is exceeded. Measurements cover synthetic short/long text with bounded
output, not full 131K context or arbitrary desktop workloads. Keep observing
pressure and swap; the lower margin is not an OOM guarantee.

Post-calibration read-only checks: supervisor active, Strata healthy/unloaded
with busy=false and queued=0, Ollama empty, API still inactive, no failed units
or running systemd jobs. The original dependency-fixed closure remains active.
Next operator commands are `sudo systemctl start inference-coordinator.service`
and `sudo narsil-inference status`; review maintenance/fault/reconciliation
state before a separate reconcile and resume. Do not rerun prepare or activate
another generation. Real coordinated handoff, streaming/cancellation, strict
queued priority and protected-control tests are still commissioning gates.

### API startup failure — read-only staged probe prepared

After successful calibration, the operator ran `systemctl start
inference-coordinator.service`; the process exited status 1 after roughly one
second. `narsil-inference status` consequently failed to connect. Journal only
reports the generic `Inference API failed closed` message, not the failing
stage. Do not assume credential failure or discard/repeat calibration.

Prepared `scripts/check-api-startup.py` and `scripts/run-api-startup-check` as
immutable store artifacts, rooted at
`~/.local/state/narsil-inference-trial/startup-check{,-probe}`. The runner starts
one disposable bounded `inference-startup-check.service` as the actual service
UID/GID, with private independent systemd snapshots of the existing credentials
and the same security/network sandbox settings. It reads/validates measured
config, reports predefined credential metadata (never values), securely loads
snapshots from its own unit directory, constructs real adapters/runner without
setup/binding/cleanup, and reads telemetry/socket permissions. **No backend
calls, inference/lifecycle operations, listener, admissions or state writes.**
Creating the disposable service/snapshots is the only systemd mutation.
Failures report stage and exception class, never arbitrary exception text.

Four new fixture tests exercise success/no runner setup or cleanup, credential
failure redaction, config-file failure and wrong-UID rejection; **364 tests
pass**. Store runner:
`/nix/store/ld98r79lqvdha8gdrzw9mxx3svs27bjq-run-api-startup-check`;
probe: `/nix/store/clfp653klfkas7gw1g0k1rj8lr0qblrk-check-api-startup.py`.
The first privileged probe ran and passed service identity/config/template
validation, then failed secure credential load. Both client/admin snapshots were
uid=0, mode=0440, nlink=1, regular files. This pinpoints the policy mismatch;
no credentials were printed and no backend/API operation occurred.

Implemented a **separate** `load_systemd_credentials` policy: require an explicit
canonical unit credential directory, all config scope paths directly beneath
the pinned source directory, root-owned single-link regular **0440** files with
GID equal to the non-root service's effective GID, bounded secure no-follow
reads and cross-scope separation. The ordinary owner-private 0400/0600 loader
is unchanged; neither policy falls back to the other. Production now selects
the systemd loader. An explicit trusted `--credential-unit` can remap only scope
basenames for a separately reviewed transient commissioning service, without
changing measured config. This avoids needing daemon reload/reprovisioning just
to validate a code fix; no repaired API service has yet been started.

Eight new tests cover root/group/mode/link/type/size restrictions, unchanged
ordinary policy, canonical/source path checks, non-root identity, scoped
transient remapping and duplicate-secret refusal. **372 tests pass**.
Credential-fix closure built, not activated:
`~/.local/state/narsil-inference-trial/system-credentials` ->
`/nix/store/arq0pz69phwlpjc522f5fg7xadfclz4p-nixos-system-narsil-26.11.20261030.1c89083`.
Its template bytes match the active measured template. Probe now includes GID
and service GID metadata and uses the repaired immutable library.
Updated store runner:
`/nix/store/wl168f89rg03zrfcjif00ik99h7qd3v9-run-api-startup-check`;
probe `/nix/store/p9vj52gdg1ffmd813knhgdhqaxxd8m0i-check-api-startup.py`.
Both user-state GC roots now point to the updated artifacts. The fixed probe ran: config validation passed, both snapshots were uid=0,
gid=0, mode=0440, single-link regular files, while service_gid=981. Therefore
the proposed service-GID policy still rejects the actual snapshots; its group
assumption was incorrect. Do not weaken validation to generic root-readable
files or claim the repair is commissioned. Systemd may use named-user access
ACLs; inspect those directly before selecting a new policy.

Updated metadata-only probe now reads bounded `system.posix_acl_access` xattrs
and reports ACL version/entries plus kernel `os.access(R_OK, effective_ids=True)`
for the predefined client/admin files, without reading their contents at that
stage. One new fixture test refuses malformed ACL metadata before credential
load; **373 tests pass**. No acceptance policy was changed for this diagnostic.
Updated root points to runner
`/nix/store/gc2mpfpn5dv4xx2xxhqirc80kw5gymb7-run-api-startup-check`, probe
`/nix/store/3kg7cpygbpfk2hiwnz5pr14vdb1lmqjz-check-api-startup.py`.
The ACL probe ran successfully through metadata inspection and found the exact
Linux POSIX access ACL (version 2) on **both** root:root 0440 snapshots:
`[(1,4,4294967295),(2,4,987),(4,0,4294967295),(16,4,4294967295),(32,0,4294967295)]`.
Kernel read access for the service UID was true. This grants read to root and
one named service UID, no owning-group/other access; mode group bits represent
the ACL mask, not owning-group permission. The group-based loader still failed
as expected and is now superseded.

Implemented exact ACL validation: root:root single-link regular 0440 snapshot
under pinned scope/unit paths, then `fgetxattr` through the opened no-follow
**descriptor** must exactly match the observed five-entry version-2 ACL for the
actual effective service UID. Recheck ACL after secret reading, followed by
fresh fstat/identity comparison. Reject absent/malformed/changed ACLs, extra
named users/groups, different UID, group/other access, write/execute permissions
or any generic-readable fallback. Ordinary private-file policy stays unchanged.
Six new tests cover exact descriptor ACL access, malformed/extra/changed ACLs,
invalid UID/absence, before/after-read enforcement, descriptor cleanup and no ACL
selection for ordinary files. **379 tests pass**.

Built (not activated) `system-credentials-acl` ->
`/nix/store/h0sksmcwdny9h3m5mfh4ikd7mh03aim1-nixos-system-narsil-26.11.20261030.1c89083`.
Its measured-template bytes match the active generation. Updated root runner:
`/nix/store/x3jfw9052qfwlyszr3bnvy9qx1g8rm7r-run-api-startup-check`, probe
`/nix/store/8lqrjrgrz5vllr7jm01zkns8dwvzchks-check-api-startup.py` using the new
immutable library. The ACL-corrected probe subsequently passed every stage:
secure snapshots, real runtime construction without I/O, memory telemetry and
supervisor socket permissions. No backend/API calls, listener, admissions or
state mutation occurred. This validates the credential fix under the actual
service sandbox. Completed probe command:

```sh
sudo ~/.local/state/narsil-inference-trial/startup-check
```

Inspect its stage output before retrying API startup. No activation/reload,
recalibration, credential printing/rotation, journal reset or reprovisioning is
needed for this probe. Root execution remains operator-only.

### Temporary repaired API service — running in maintenance

To avoid invalidating the active supervisor's manager fence with daemon reload
or full activation, prepared immutable `scripts/start-api-repair`, rooted at
`~/.local/state/narsil-inference-trial/start-api-repair` ->
`/nix/store/26njwdwa6ggas51kfgpnacmxsrwbax1v-start-api-repair`.
It refuses a running/transitional original API, original main/control PID or
job, and an inactive supervisor. It starts one transient
**`inference-coordinator-repair.service`** with the validated ACL-corrected
executable and existing measured config, explicit credential-unit remapping,
Type=notify/watchdog, unprivileged identity, original credential scopes and
same sandbox/whole-cgroup/shutdown/memory/task limits. Requires only the
supervisor; Wants/After on backends. No automatic reconcile/resume, unit
replacement, retry, activation/reload, secret output or reprovisioning.

Five fixture tests exercise command/dependency/sandbox rendering, original
active/process/job refusal, inactive supervisor and nonroot guard; **384 tests
pass**. The operator subsequently ran the launcher and status successfully.
Completed commands:

```sh
sudo ~/.local/state/narsil-inference-trial/start-api-repair
sudo narsil-inference status
```

Status: idle; owner/lease null; maintenance=true; reconciled=false; fault=null;
both queues empty; no active request. Agent read-only checks verify repaired API
and supervisor active/running, correct Wants/Requires dependencies and loopback
`127.0.0.1:18080` listener. The operator completed reconcile/status: maintenance=true, reconciled=true,
fault=null, idle, no owner/lease/work. The operator then ran resume/status successfully: maintenance=false,
reconciled=true, fault=null, idle, no owner/lease/work. Admissions are enabled;
this did not prewarm a model. Real coordinated handoff testing is next.
Do not retry an uncertain
control response blindly. `narsil-inference` controls still use the same protected localhost API
and root-only scoped tokens. The old installed coordinator unit remains failed
and must not be started; actual service control/logs refer to
`inference-coordinator-repair.service`. This is temporary commissioning, not
persistent deployment or reboot readiness. After draining, stop the repaired
unit explicitly if needed. Do not activate another generation behind it.

### Admissions enabled — real coordinated handoff smoke test next

Operator resume/status reports maintenance=false, reconciled=true, fault=null,
idle with no owner/lease/active request and empty queues. Repaired API/supervisor
are active; non-loading reads still show Strata unloaded and Ollama empty.

Prepared immutable `scripts/smoke-handoff.py`, rooted at
`~/.local/state/narsil-inference-trial/smoke-handoff` ->
`/nix/store/lkdw8ndip7wjyhz9j0p611v5728d9nd2-smoke-handoff.py`.
It reads only the root-private **client** credential in memory, then makes
sequential short Strata -> Ollama -> Strata generations through coordinator
port 18080. Non-loading backend reads independently check exclusive expected
residency, idle Strata work, preserved 131072 profile and Ollama context 8192.
Requires positive generated-token counters, reports durations and numeric memory
telemetry, never logs credentials/prompts/full responses, uses no admin controls
and never retries/replays a request. It refuses unexpected initial residency,
maintenance/fault/queues/owner, and leaves final Strata loaded on success.

Five fake-client tests cover three coordinated requests/no raw mutations,
no replay on failure, maintenance refusal, overlapping residency rejection and
credential-error redaction; **389 tests pass**. The operator subsequently ran the real script successfully. Completed command:

```sh
sudo ~/.local/state/narsil-inference-trial/smoke-handoff
```

Actual results, with independent expected exclusive residency after each:

| Step | Backend | Output tokens | Duration | Total VRAM GiB | MemAvailable GiB |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | Strata | 16 | 29.4 s | 14.88 | 5.95 |
| 2 | Ollama | 2 | 7.2 s | 10.49 | 25.49 |
| 3 | Strata | 16 | 31.2 s | 14.84 | 5.81 |

Final Strata remains loaded. Agent non-loading reads confirm loaded Strata,
empty Ollama and active repaired API/supervisor. No admin controls, retries,
activation, reprovisioning or credential copying were used. This validates real
coordinated handoff, not streaming/disconnect/queued priority.

Prepared immutable `scripts/smoke-streams.py`, rooted at
`~/.local/state/narsil-inference-trial/smoke-streams` ->
`/nix/store/9k52wdxlm9a1gxx6gglxvrqkvfpbizx8-smoke-streams.py`. It requires initial
idle Strata ownership and performs: Strata SSE completion through terminal/EOF;
Ollama NDJSON completion; explicit Ollama disconnect after a nonempty token
while coordinator status confirms the same active request ID; waits for no
active work/owner/lease/fault and empty backends; then Strata SSE recovery and
exclusive final residency. No admin calls, retries, raw generations, secret or
response logging. Bounded lines/total bytes/timeouts. Final Strata stays loaded.
Five fixture tests cover framing/terminal/EOF, active cancellation correlation,
no claim after completion, errors/post-terminal data, and single submission;
**394 tests passed** at preparation. The operator subsequently ran the real
streaming harness successfully. Completed command:

```sh
sudo ~/.local/state/narsil-inference-trial/smoke-streams
```

Observed results: Strata SSE completed with **15 JSON events / 1.7s**;
Ollama NDJSON completed with **65 JSON events / 7.6s**; disconnect occurred only
after nonempty Ollama output with matching active coordinator request ID;
subsequent status had no active work/owner/lease/fault and both backends empty;
post-cancellation Strata SSE recovered successfully, final Strata loaded.
Agent non-loading reads confirm loaded Strata, empty Ollama and active repaired
API/supervisor. No admin calls, retry/replay or reset was needed.

Prepared immutable `scripts/smoke-priority.py`, rooted at
`~/.local/state/narsil-inference-trial/smoke-priority` ->
`/nix/store/4d6p368g9s9j4pccwk5ww7mnx118ag1a-smoke-priority.py`.
It starts an Ollama stream, then queues O-1, O-2 **before** S-1, S-2, observing
actual queue counts with the same active Ollama request ID and unfinished queued
callers. Active Ollama must finish naturally; required completion order is
`O-active -> S-1 -> S-2 -> O-1 -> O-2`, proving nonpreemption, strict next-boundary
Strata priority and per-backend FIFO in this real scenario. Then restore Strata
and verify exclusive final residency. No admin controls, retries, secret/body
logging or raw generation. Failed runs disconnect only their own callers and
require status inspection, not replay/reset. Six fixture tests cover order,
active-ID/queue correlation, early completion/fault rejection, submission order,
no inference after invalid initial state and credential-error redaction;
**400 tests pass**. The operator subsequently ran the real priority harness
successfully. Completed command:

```sh
sudo ~/.local/state/narsil-inference-trial/smoke-priority
```

Actual observed queue boundary: the same active Ollama request with **2 Strata
and 2 Ollama requests queued**, after Ollama requests were enqueued first.
Active Ollama finished naturally, without preemption. Observed completions:
`O-active -> S-1 (16 tokens) -> S-2 (16) -> O-1 (2) -> O-2 (2)`.
Post-test Strata recovery generated 16 tokens and verified exclusive final
Strata residency. Agent confirms repaired API and supervisor remain active.
No admin operations, retries, activation or reset were used.

This validates this real nonpreemptive strict-priority/FIFO scenario, not
fairness (Ollama starvation remains intentional), all transition-arrival stress
or arbitrary-workload memory safety. Live protected drain from the loaded state
is the next checkpoint before deliberate persistent deployment planning:

```sh
sudo narsil-inference drain
sudo narsil-inference status
```

Expected: maintenance=true, no owner/lease/active or queued work, fault=null.
The operator ran both commands successfully. Both returned idle,
maintenance=true, reconciled=true, fault=null, no owner/lease/active request,
empty queues/zero bytes. Agent non-loading reads independently confirm Strata
unloaded and Ollama empty; repaired API/supervisor remain active. The trial is
now safely parked in maintenance. No additional reconcile is needed merely
because a successful drain was performed; resume would be a separate deliberate
admissions action.

Live handoff, streaming completion, active Ollama disconnect/release/recovery,
nonpreemptive strict queued priority/FIFO and loaded-state protected drain have
all passed their scoped scenarios. This is not reboot/unattended production
qualification. Persistent corrected units remain unactivated.

Before any deployment: stop API and supervisor under the current valid fence;
review/preserve the **current healthy** journal/config and verified cold boundary
with a new guarded procedure (never reuse the first-stop abandonment tool);
review the target closure's dry activation; arrange condition-guarded startup;
explicitly provision fresh pins after the activation's manager-fence change;
validate/reuse measured config only if exact binding checks permit it, otherwise
recalibrate; start corrected original API in maintenance and recommission.
`prepare` currently refuses both existing supervisor state and measured config,
so neither rerunning it nor activating over live pins is a migration procedure.
The user has now explicitly requested deployment rather than preservation of
the current trial configuration. Proceed with fresh provisioning of the built
corrected desktop closure `system-credentials-acl` (h0sksmcwdny9h3m5mfh4ikd7mh03aim1).
Retiring old healthy state by moving it aside is sufficient; no separate recovery
exercise or migration of measured config is required. The original unresolved
archive remains untouched. Next gate is root-run `switch-to-configuration
dry-activate` for this exact closure (unprivileged execution refuses before any
activation). The operator's root dry activation completed: would stop/start
accounts-daemon, inference-supervisor and polkit, and reload dbus-broker. No
display-manager/session stop or mode switch is listed. Review accepted for
ordered shutdown before fresh provisioning; manager/bus identity must be observed
only after activation. Next stop repaired API **before** supervisor, and supervisor before
backends; do not enqueue all stops together because API cleanup still needs its
supervisor. Verify cold/journal boundary, move current state/config aside, activate
the corrected closure, and explicitly prepare fresh pins/config. No journal
editing, blind retry, automatic repinning, mode switch or logout. Deployment
authorization does not establish unattended/reboot-safe pin provisioning.

### Corrected-unit deployment — stopped boundary and next operator command

The user ran ordered API -> supervisor -> backend stops. Status confirms repaired
API not-found/inactive/dead (transient unit collected), supervisor/Strata/Ollama
inactive/dead, all MainPID/ControlPID=0, no unit jobs and no global jobs.

Prepared one-shot `scripts/retire-commissioned-state.py`, immutable/rooted at
`~/.local/state/narsil-inference-trial/retire-commissioned-state` ->
`/nix/store/nx1rlcbqc2r4dc98wgbvwzdwc43xzd7g-retire-commissioned-state.py`.
It requires the reviewed active `system-fixed` generation, root, exact existing
pins/boot/manager/mount fence, exclusive replay-validated journal with **no pending
intent**, stopped inference units/empty cgroups/no listeners/no jobs in two cold
passes. It then moves the whole healthy supervisor directory and measured config
to root-private `/var/lib/inference-commissioned-before-h0sksmcwdny9h3m5mfh4ikd7mh03aim1`,
creates an empty private supervisor directory, and leaves pins/config absent for
condition-guarded activation. No credential reads, journal edits, service actions,
automatic retries or repinning. Existing archive or uncertainty refuses; any
partial failure is inspection-only, never replay. Original abandoned-stop archive
is untouched. Six fixture tests include lock/pending refusal, PID/job checks,
read-only cold commands, and actual temp-filesystem whole-directory/config moves
and duplicate-destination refusal. **406 tests pass**.

Next root commands, chained so retirement failure prevents activation:

```sh
sudo ~/.local/state/narsil-inference-trial/retire-commissioned-state &&
  sudo ~/.local/state/narsil-inference-trial/system-credentials-acl/bin/switch-to-configuration test
```

Review actual output before fresh `prepare`. `test` installs corrected units for
this boot while preserving the previous boot default; this is not a claim of
unattended/reboot-ready provisioning. Neither command has run yet.

### Earlier development milestones (historical)

The implementation lives in `modules/apps/inference-coordinator/`; statements of missing wiring in the milestones below describe their original development boundary and are superseded by the scoped trial increment above:

- Strict versioned data-only JSON configuration parser with immutable results, bounded UTF-8 input, sanitized errors, duplicate/unknown-field rejection, explicit limits/backend registration, approved priority/resource policy, preserved desktop/headless Strata contexts, Ollama model/catalog/resident identities, separate cold/resident memory headroom budgets and external credential references. It performs no I/O; the development assembler consumes parsed configuration and separately loaded credentials explicitly. Schema validation cannot prove calibration, real tokenizer compatibility or quiescence. See `CONFIGURATION.md`; fixture budgets are synthetic, not deployment recommendations.
- Explicit secure Linux credential snapshot loader, separate from parsing; its snapshot is explicitly accepted by the development runtime assembler. It pins path components with no-follow directory-relative opens, checks trusted directory ownership/permissions, accepts only owner-private single-link regular files, bounds reads to 4096 bytes, detects metadata/identity changes, validates ASCII bearer contents and rejects equal secrets across client/admin/backend scopes. Results have redacted reprs and immutable backend maps; failures are sanitized with no anonymous/stale fallback. Tests use temporary synthetic files only and cover symlinks, hardlinks, special files, replacement races, duplicate tokens and descriptor cleanup. No deployed credential files were read. Production provisioning/rotation/startup wiring remain unfinished; minimum length does not establish entropy or protection against the trusted owning UID/root.
- Explicit development runtime assembler (`coordinator/runtime.py`) connects parsed config and credential snapshots to the scheduler, real lifecycle adapters, approved protocol adapters and HTTP app without construction-time I/O. Requires exact Ollama-ID counter/quiescence registries and an injected memory-admission implementation; no default safety callbacks. Revalidates credentials, maps limits/identities/backend authentication, and keeps startup in maintenance. Strata memory admission observes loaded/idle profile; Ollama memory admission runs after necessary eviction and receives exact requested context and residency, avoiding redundant cold-load headroom. App setup only opens control sessions; cleanup drains before closing them, even on failure. Fake loopback tests cover the complete assembly, handoffs, smaller-context changes, failure blocking, admin controls, partial setup and cleanup ordering. Production dependencies, entrypoint/provisioning and a hard total shutdown/recovery boundary remain unfinished.
- Documented proposed production process-supervision boundary in `SUPERVISION.md`: verified managed stop and whole-cgroup emptiness before lazy API restart, exact readiness/version/empty-residency checks, no implicit restart after uncertain stop, narrow helper privileges, remaining local-process trust assumptions and required fake-supervisor tests. The transaction implementation is described below; a read-only inspector now exists, but no mutating helper/systemd job-completion transport or real service transition exists yet. Read-only inspection confirmed the current active Ollama unit uses `KillMode=control-group`; this alone is not sufficient proof.
- Development managed-quiescence transaction (`coordinator/supervision.py`) over an explicitly injected helper: pinned unit/cgroup/deployment contract, correlated completed stop/start jobs, inactive-and-empty-cgroup proof before lazy restart, fresh invocation ID plus exact-version/empty-residency readiness, final invocation verification, phase/total deadlines and fail-closed cancellation/pending-job handling. Bounded no-symlink cgroup event reader uses recursive kernel population and distinguishes missing group from invalid telemetry root/events. Fake-helper/temporary-filesystem tests cover false acknowledgements, wrong contracts, populated descendants despite MainPID zero, group disappearance, pending/late jobs, cancellation, timeout, overlap, readiness failures, invocation changes and descriptor cleanup. No mutating helper/privileges/systemd job-completion transport, durable-intent/actual-job recovery integration, trusted mount-pin provisioning/namespace isolation or runtime wiring exists. This is not real release proof or hard whole-process shutdown.
- Separate read-only mount-pinned cgroup reader (`coordinator/cgroup_mount.py`) with an explicit operator-provisioned mount ID/device/root inode, bounded proc mountinfo/fdinfo checks, exact full cgroup2 mount matching and per-open descendant/events mount verification. Rechecks mount identity before returning population or disappearance; rejects wrong/stacked/nested mounts, malformed evidence and identity changes with no automatic repinning. Synthetic proc-evidence/temporary-filesystem tests cover failure paths and descriptor cleanup; no real mount changes. Construction does no I/O. Assumes trusted kernel procfs and a stable operator-controlled namespace; does not defend against privileged mount replacement/ID reuse or establish local-process isolation. Production pin provisioning and namespace enforcement remain unfinished.
- Standalone durable write-ahead job journal (`coordinator/job_journal.py`), explicitly bound to a unit/deployment/boot/bus-GUID/manager-name-owner identity (version-2 header; version-1 data refused without automatic migration). No-I/O construction; explicit exclusive initialization vs existing-file open; lifetime writer lock; bounded strict append-only replay; fsynced begin/submitted/completed/acknowledged records and one pending intent across restart. Even completed intents remain pending until explicit acknowledgement; nonce reuse, unknown submission, torn/corrupt logs, unsafe metadata, inode replacement and write/fsync failure fail closed. No automatic retries, repair, rotation, job control or uncertainty clearing. Secure no-follow directory/file opens and descriptor cleanup; fixture tests include abrupt child-process exit, partial writes, interruption, lock contention and failed fsync. This is synchronous storage for a future serialized helper, not actual systemd correlation/recovery or process supervision; trusted boot provisioning, unknown-job recovery and manager-restart/job-ID reuse handling remain unfinished.
- Bounded read-only systemd inspector (`coordinator/systemd_inspect.py`) over an operator-pinned absolute busctl executable and one configured unit. Requires an explicit immutable BusIdentity (bus GUID plus systemd unique name owner), checks pins before/after reads, addresses all systemd queries to the pinned unique owner with no well-known-name fallback, and permanently faults on an observed identity mismatch rather than repinning. Uses GetUnit and selected typed Unit/Service property reads, with before/after Unit comparison; no GetAll/environment reads, mutations, shell, inherited bus-address/loader environment, autostart, interactive authorization or command retries. Immutable evidence explicitly does not assert a valid deployment contract, atomic state, historical-job reconciliation or process release. Concurrent stdout/stderr limits, whole-inspection deadline, process-group kill/drain/reaping, tracked late spawn/cleanup and fail-closed cleanup uncertainty have fake-process coverage, including floods, inherited-pipe descendants, repeated cancellation and descriptor checks. Connection identity checks do not prove a manager process epoch or prevent job-ID reuse on a connection preserved across reexecution. Outer hard process supervision, trusted identity-pin provisioning, manager-reexecution/completion-correlation policy, fingerprint/hooks/lazy-start validation and runtime wiring remain unfinished. Identity fixtures test bus restarts reusing owner/job IDs, owner replacement during/between inspection, malformed pins and refusal of stale/unpinned journals; a pinned read-only installed-Ollama smoke check also succeeded. Read-only smoke check against installed systemd/busctl 262 and Ollama succeeded: active/running, current job ID 0, control-group kill mode, 90-second stop timeout, Restart=no, no delegation. No lifecycle/inference/residency queries were made; this is not approval of that unit for managed restart.
- Pure preliminary managed-unit safety gate (`coordinator/unit_policy.py`) with immutable unit/cgroup/bus/stop-timeout/service-type pins. Rejects unsafe kill/restart/delegation/trigger policy, visible jobs/control processes, mismatched identities, unsettled active/inactive state and malformed dataclass types. Eight synthetic tests cover rejection paths; no service calls or runtime wiring. Returns no authority object or `UnitState`: passing does not validate executable/deployment fingerprints, hooks, lazy startup, exclusive control, evidence freshness, manager epoch or journal history. Full deployment approval and job/release proof remain blockers; inactive state or `Job=0` never clears uncertainty.
- Dependency-free Python asyncio scheduler with explicit backend registration, FIFO queues, configured strict priority, one exclusive resource lease, count/byte admission caps, deadlines and cancellation tracking.
- Generic lifecycle and memory-admission contracts; fail-closed transitions, startup reconciliation and maintenance/drain without request replay.
- Fake-backend tests, including a third backend, starvation, concurrent worker serialization, arrivals during load/release, active/queued cancellation, uncertain release, failure/recovery, deadlines and drain.
- Initial aiohttp front door with explicit Strata/Ollama route policies, provider-prefix stripping, mandatory bearer authentication, private loopback upstreams, request/connection limits, queue expiry during active streams, and streaming response relay with flow control/idle deadlines. Unknown routes, backend controls, redirects, encoded requests and unsupported transports are refused.
- Loopback fake HTTP tests cover SSE/NDJSON, unchanged Strata tool/schema bodies, opaque multipart uploads, blocked downstream writes, queued/active disconnects, partial-stream timeouts, route/model/resource restrictions and no automatic inference replay.
- Ollama admission enforces model allowlisting and bounded context/output options, owns native keep-alive, and disables embedding truncation. Approved-only `/api/tags` and `/v1/models` discovery filtering is implemented with explicit alias mapping, bounded JSON, no unfiltered fallback, no loading/lease and no stale upstream validators. Refreshing discovery while Strata is active does not evict it.
- Ollama inference now requires a non-loading input-budget accountant before queueing. The gate checks model/effective-context agreement, per-input batch counts and reserved generation output; missing accounting fails closed with `503`, unsupported inputs/oversize requests return `422` without truncation. Full normalized envelopes reach the accountant, including tools/schema/system/template/context metadata. There is no heuristic fallback. **Production model tokenizer/template counters are not implemented yet**; tests inject synthetic counts. OpenAI effective context still needs verified backend/model configuration, and Strata relies on its existing full-prompt rejection.
- Authenticated, bodyless `GET /coordinator/status` reports sanitized scheduler ownership, maintenance/fault/reconciliation state, queue counts/bytes/oldest wait and active request ID without backend calls. Admitted inference uses coordinator-generated UUIDs in upstream/downstream `X-Request-ID`. Status does not claim independent readiness/residency, mode/profile, live memory or complete metrics. Optional separately authorized maintenance endpoints are implemented below; disabled by default.
- Optional bodyless `POST /coordinator/admin/{drain,reconcile,resume}` controls require a strong, distinct admin bearer token; inference/status and admin credentials do not cross scopes. Disabled by default. Operations serialize, reject browser Origin/Cookie requests, use a total deadline, survive caller disconnect and return sanitized no-store responses. Drain rejects queued work, finishes active inference and verifies all-backend release; reconcile remains in maintenance until explicit resume. Timeout/failure invalidates prior reconciliation even when waiting for the worker lock, preventing unsafe resume. Fake HTTP tests cover authorization/request shapes, all-backend drain, timeout during active streaming, queued rejection, overlap, disconnect continuation and failure/recovery. These are development controls, not production process supervision or admin network/credential wiring.
- Bounded loopback-only JSON control client and Strata/Ollama lifecycle adapters. Strata checks explicit acknowledgements, exact profile, busy/queued work and unloaded state. Ollama checks configured version, exact resident model/context, empty generation/embedding warmups, eviction of all models, bounded release settling, and same-backend model/context changes. Native admission carries requested context into lifecycle preparation.
- Ollama release requires an injected quiescence proof: its unload response schedules eviction, and `/api/ps` does not establish absence of pending loads. No production quiescence callback exists yet; a no-op is invalid. Actual process supervision/restart and API-readiness integration must be designed/tested before real transitions.
- Read-only explicit-AMD-device sysfs VRAM and Linux `MemAvailable` telemetry, plus bounded memory admission with fail-closed stale/missing/invalid telemetry handling. No model thresholds are guessed, calibrated or enabled. Memory checks supplement lifecycle proof and cannot prevent later desktop allocations.
- Lifecycle tests use local fake HTTP servers, including failed unload blocking the next backend, cancelled warmup requiring recovery, all-model eviction, version/profile/schema mismatch and false acknowledgement rejection. Memory tests use synthetic sysfs/procfs fixtures. Current coordinator suite: **333 passing tests**. Client API keys are stripped; optional inference-backend bearer credentials are configured separately from client/coordinator authentication.
- Commitment boundary: finish a started load, then recheck priority before inference admission. A Strata arrival during Ollama loading causes verified Ollama release and Strata preparation before the Ollama request executes. No overlapping loads and no active-inference preemption.

The local trial is **not yet real-backend commissioned or actual-use ready**. New supervision, process/credential/entrypoint and NixOS wiring need privileged validation; actual measured budgets and native full-input rejection are deliberately prerequisites to publishing a usable configuration. Unknown-intent recovery, unattended reload/reboot behavior, full mode integration, production independent tokenizers/OpenAI/embedding scope, LAN/tailnet migration, complete observability and UI remain unfinished. Adapter tests still use fake GPU release, not real proof of stopped GPU work; more socket/slow-consumer stress remains useful. HTTP uses aiohttp and persistent bus transport uses dbus-next 0.2.3, both from the existing locked nixpkgs without lockfile changes.

No models were downloaded. After desktop test activation and explicit first-failure recovery, real supervised Ollama stop/restart and Strata load/short-and-long-inference/unload occurred during the second prepare. No mode switch/logout was requested or reported. A disposable user `sleep` service was also started/stopped and removed for transport validation. Existing mutable Strata tuning is untouched; new service wiring is isolated in the opt-in trial, with small conditional/guard changes that preserve ordinary mode behavior.

## Historical next-session starting point — superseded

**Do not follow this old recovery/deployment procedure.** The personal-use
service described at the top and in `modules/apps/inference-coordinator/README.md`
replaces it. Use the `system-personal` closure: automatic reset/admission, no
pins/journal/prepare/retirement. The old services were stopped and no state was
retired successfully; the old failure does not block the new service.


Historical instruction (superseded): read the local-trial increment. Current service operations are in `modules/apps/inference-coordinator/README.md`. The user approved local API commissioning, targeted service/model tests and Narsil rebuild/switch, but requires asking before mode changes or logout. They separately approved explicit native-only backend rejection for this trial; do not reintroduce the tokenizer blocker for this scoped path or wire fake counters. Full counted/OpenAI/embedding/multimodal deployment still needs real accounting.

**Immediate gate:** read **Successful real calibration** above. Active closure is still `system-fixed` (`5d8y0qma5g73zd3dxiz1b3v5yi4swlz5`). Operator-run calibration from `system-strata-2g` (`5r699yl3n0zgv0nqjnan92cf9l75z7z5`) passed both models and all three native oversize rejection cases using existing supervisor state; measured config is published and accepted by the active API loader. Both backends are released, supervisor active, API inactive, no failed units/jobs. The operator attempted API start; it exited status 1 before bind, logging only a generic sanitized error. The first startup probe confirmed root-owned 0440 systemd snapshots rejected by the ordinary private-file policy. A separate strict root:service-GID 0440 loader is implemented/built at `system-credentials`, not activated; ordinary private-file policy unchanged. That repeat probe disproved the proposed group rule: snapshots are root:root 0440, service GID=981. Do not treat `system-credentials` as a validated fix. The ACL probe confirmed an exact root + named service-UID read-only access ACL, with owning-group/other access denied. Replaced the wrong group rule with exact descriptor-based ACL checks before/after reading and identity revalidation; ordinary private-file rules unchanged. New build is `system-credentials-acl`, not activated, template unchanged. The ACL-corrected sandbox probe passed all stages. The operator successfully started the guarded transient `inference-coordinator-repair.service`; status is idle/no owner/lease/fault/work, maintenance=true, reconciled=false. Agent verified running repaired API/supervisor and loopback-only listener. No activation/reload/reprovisioning occurred. Operator reconcile/status succeeded: idle, no owner/lease/fault/work, maintenance=true, reconciled=true. Operator resume/status also succeeded: maintenance=false, reconciled=true, fault=null, idle/no owner/lease/work. Immutable `smoke-handoff` is prepared and rooted; the operator ran it successfully: Strata 16 tokens/29.4s -> Ollama 2 tokens/7.2s -> Strata 16 tokens/31.2s, exclusive residency verified each step. Final Strata is loaded (~14.84 GiB total VRAM, 5.81 GiB MemAvailable). The real streaming harness also passed: Strata SSE 15 events/1.7s, Ollama NDJSON 65 events/7.6s, active-ID-confirmed Ollama disconnect with verified empty/no-owner/lease/work/fault state, then Strata SSE recovery. Final Strata loaded. The real priority harness also passed: the same active Ollama request with 2 Strata + 2 Ollama queued, then natural O-active completion followed by S-1→S-2→O-1→O-2, then S-final recovery (16 tokens). Final Strata loaded. 400 tests pass. No retries/admin controls/credential copying. Protected loaded-state drain/status also passed: idle, maintenance=true, reconciled=true, no owner/lease/work/fault. Agent confirms both backends unloaded/empty and services active. Current state is safely parked in maintenance. Next is deliberate persistent-deployment planning, not resume/activation/reprepare by default; current healthy journal/config must be preserved with a separately reviewed cold-boundary rollover before manager-fence changes. Do not start or retry the old installed API executable. No activation, prepare, archival reset or daemon reload is needed. User accepts desktop Strata 2 GiB MemAvailable floor and exceeding approximate 12 GiB target; Ollama/headless retain 6 GiB, VRAM margin and Strata engine tuning unchanged. Real handoff/streaming/cancellation/priority/FIFO and loaded-state protected drain passed; deliberate persistent deployment remains. Original stop 60919 is unresolved in its preserved private archive; never modify it or reuse the one-off recovery tool. Local SearXNG removal was explicitly accepted despite unvalidated Blade search. Agent cannot authenticate sudo. Ask before any mode switch/logout.

406 coordinator tests pass with `/nix/store/3hr90mddrgkz0src1vykj19yddnjimzl-python3-3.14.8-env/bin/python` (aiohttp + dbus-next), including built desktop unit checks; 21 mode-lifecycle tests previously passed. Parent/headless trial builds were successful. Real Strata load/inference/unload, supervised Ollama stop/restart, both-model calibration and native full-input rejection checks passed after the desktop Strata RAM-floor adjustment. Repaired API startup/reconcile/resume and real coordinated handoff passed; real streaming/cancel/recovery passed; real nonpreemptive strict queued priority and both-backend FIFO passed. Loaded-state protected drain passed and both backends are empty, maintenance=true/reconciled=true/no fault; persistent deployment remains unactivated. No mode changes occurred. Preserve Strata tuning and the explicit mode-switch refusal during this local trial. Installed Strata source was inspected at clean commit `296b59d2f73c8f04a805df29c2fa97655adace78`; Ollama is 0.40.11 and relevant exact-tag native truncation/runner-shift paths were researched. New durable transport/manifest/provisioning/RPC/operator/entrypoint/calibrator code still needs privileged commissioning, and unknown-intent recovery/unattended reload/reboot remain unresolved. Stronger raw-local isolation, full mode/remote/UI deployment are later scope.

Preserve unrelated user changes: `modules/apps/agents/{default.nix,settings.json,extensions/README.md}`, `modules/apps/dashboard/default.nix`, `modules/hosts/blade/default.nix`, untracked `docs/searxng.md` and `modules/apps/searxng/`. They are not ours to overwrite. A `path:` system build includes them, so review activation effects too.

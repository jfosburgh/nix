# Configuration schema v1 (data-only, development)

`coordinator.config.parse_config(body: bytes)` parses a bounded UTF-8 JSON
configuration into frozen dataclasses and read-only model mappings. It does not
read a file, open credentials, contact backends, import plugins, start a listener,
or reconcile/resume the scheduler. A separate explicit development assembler now
exists (below). An opt-in local-trial entrypoint/supervisor/calibrator now also
exists, but has not been activated or real-backend commissioned; see `TRIAL.md`.
A successful parse is structural validation, not production safety approval.

All fields below are required unless marked optional. Unknown fields, duplicate
JSON keys at any depth, non-finite numbers, invalid types (including booleans used
as integers), and inputs larger than 256 KiB are rejected with sanitized
`ConfigError`s. Errors do not echo supplied values. There are no implicit model,
memory, priority or timeout defaults.

## Root

| Field | Value |
| --- | --- |
| `version` | Integer `1` |
| `profile` | `desktop` or `headless` |
| `token_file` | Canonical absolute path to an externally supplied client credential |
| `admin_token_file` | Optional separate credential path; absent means admin disabled |
| `limits` | Object described below |
| `backends` | Array of exactly one Strata and one Ollama registration |

Credential references must be distinct across client, admin and optional backend
credentials. They are references, never inline tokens. The parser does **not**
verify file existence, ownership, symlink targets or credential entropy. Explicit
secure loading is implemented separately as described below. No example real
credential files or guessed memory thresholds are committed.

### Explicit credential loading (Linux, not automatically invoked)

`coordinator.credentials.load_credentials(config, expected_uid=...)` reads a
startup snapshot of every configured credential or raises sanitized
`CredentialError`. The default expected file owner is the process effective UID.
It does not create a service, open a listener, or change scheduler state.

- Every path component is pinned using directory-relative opens with
  `O_NOFOLLOW`/`O_CLOEXEC`; no symlink components or noncanonical paths are accepted.
- Ancestor directories must be owned by root or the expected UID, without
  group/other write permission. Root-owned sticky ancestors such as `/tmp` are
  permitted; descendants still have to satisfy the trust checks.
- Files must be single-link regular files, owned by the expected UID, with owner
  read permission and no bits outside `0600` (thus `0400` and `0600` are supported).
  Special files are rejected before open; final opens also use `O_NONBLOCK`.
- Each file is limited to 4096 bytes. Metadata/identity is checked before open,
  after open and after a bounded read; changes or size mismatches fail closed.
- Contents must contain at least 24 printable ASCII non-whitespace characters,
  optionally followed by exactly one LF. CRLF, extra newlines, whitespace,
  control bytes, invalid encoding and oversized files are refused. Minimum
  length is not a proof of randomness: provision actual high-entropy secrets.
- Equal secret values across client/admin/backend scopes are rejected even when
  stored at different paths or with differing trailing LF. Missing credentials
  have no environment, stale-value or anonymous fallback.
- The result is immutable with a redacted repr and read-only backend-token map.
  Errors never echo paths, token values or underlying OS exception text.

The intended files are local systemd-style credential files owned by the service
UID, not arbitrary network filesystems. Bounded bytes do not impose a hard I/O
deadline on an unresponsive filesystem. The expected UID/root remain trusted;
this is not protection against a malicious credential owner, mount administrator
or concurrent privileged writer. Python retains plaintext strings in memory and
cannot promise reliable zeroization. Do not serialize or log the credentials
object (including dataclass conversion). Credential provisioning, production
startup and reload/rotation policy are still unwired; loading failures must keep
admissions blocked, and changed files do not silently hot-reload a running app.

## Limits

Positive integers, at most signed 64-bit: `max_queue`, `max_queue_bytes`,
`max_body`, `max_connections`, `max_discovery_bytes`. `max_body` cannot exceed
`max_queue_bytes`.

Positive finite seconds, at most 86400: `lifecycle_timeout`, `inference_timeout`,
`body_timeout`, `stream_idle`, `queue_timeout`, `discovery_timeout`,
`admin_timeout`, `count_timeout`.

`max_queue`, `max_queue_bytes`, `lifecycle_timeout`, `inference_timeout` correspond
to scheduler constructor settings. Other settings correspond to HTTP transport
and Ollama input accounting. The development assembler maps them explicitly rather
than passing the entire object to a constructor. Durations are bounded schema
inputs, **not** calibrated application timeout recommendations.

## Backend registration

Common fields:

| Field | Value |
| --- | --- |
| `id` | Unique lowercase route/scheduler ID matching `[a-z][a-z0-9-]{0,31}`, not `coordinator` |
| `adapter` | `strata` or `ollama`; no dynamic module/command loading |
| `upstream` | Explicit HTTP origin using `127.0.0.1` or `::1`, with a port and no credentials/path/query |
| `priority` | Nonnegative integer, lower wins |
| `resources` | Exactly `["narsil-gpu"]` |
| `credential_file` | Optional dedicated backend bearer credential path |

IDs need not equal adapter names; the scheduler remains backend-generic. Schema
v1 deliberately supports only the approved initial pair and single-resource
policy. Adding another production adapter requires explicit schema, lifecycle,
protocol and policy tests, not silently inheriting a priority. Strata priority must
be strictly higher than Ollama's. Backend ports must differ, including across IPv4
and IPv6 loopback spelling, to avoid a dual-stack socket collision.

### Strata-specific fields

- `model`: exact expected profile identity, nonempty string.
- `context`: integer `131072` for desktop, `262144` for headless, preserving the
  approved profile limits.
- `cold`, `resident`: separately measured memory-headroom objects (below).

Other tuned Strata settings are preserved by the eventual Nix-generated service
configuration, not redefined by this parser. Exact model/configuration verification
is still a deployment responsibility.

### Ollama-specific fields

- `expected_version`: exact server version to validate at runtime.
- `models`: nonempty object keyed by exact admitted model IDs. Each value requires:
  - `catalog_name`: exact upstream discovery identity.
  - `resident_name`: exact `/api/ps` identity.
  - `context`: positive integer effective context limit.
  - `output`: positive integer reservation smaller than context.
  - `cold`, `resident`: separately measured memory-headroom objects.

Catalog names and resident names must each be unambiguous across the allowlist.
There is no guessed `:latest` mapping. These limits must later be checked against
real model templates/tokenizers and OpenAI effective backend context. Structural
validation does not prove those facts. The initial protocol route set is fixed in
code; per-model capabilities/restricted routes still need a coherent extension
before embedding-only or generation-only deployment profiles are supported.

### Explicit native-only trial policy

Ollama registrations optionally accept `input_policy`: `counted` (default) or
`native-reject-trial`. Strata registrations cannot set it. The trial value requires
exact `expected_version: "0.40.11"` and is a separately user-approved scope change,
not a selector for a fake counter. It enables only text-native `/api/chat` and
`/api/generate`, forces `truncate=false` / `shift=false` in inference AND warmup,
requires the fixed configured context and disables OpenAI, embeddings, multimodal
and unhandled request features. Discovery is limited to native tags/version.

This alternate policy relies on verified full-input rejection inside the owned
backend request, not pre-queue tokenizer/template accounting. It does not prove
reserved generation output fits; output may end at the context boundary. Real
oversized history/default/raw generation rejection must pass the explicit
commissioning command before a measured config is published. See `TRIAL.md`.

### Memory-headroom object

Both `cold` and `resident` require positive integer byte fields `vram_free` and
`ram_available`. They express **minimum free headroom**, not a model-size estimate
or hard GPU allocation cap. Cold and already-resident inference have separate
measurements. Parsing cannot establish that thresholds are conservative or that
there is enough actual memory. Same-backend Ollama model/context changes and
smaller requested contexts need a carefully tested budget-selection strategy;
never accidentally demand another cold allocation for an already loaded model.

## Explicit development runtime assembly

`coordinator.runtime.assemble(config, credentials, memory=..., counters=...,
quiescence=...)` constructs the scheduler, configured Strata/Ollama lifecycle
adapters, approved protocol adapters, endpoints and aiohttp application. It takes
already parsed configuration and already loaded credentials; it does not read
files, open network sessions, bind a listener, contact backends or resume work.
The returned `Runtime` has `scheduler`, `app` and a read-only `endpoints` registry,
with a secret-free repr. Backend IDs determine routes; adapter names do not.

Required injected dependencies have no defaults:

- `counters`: exact registry keyed by **counted-policy** Ollama backend IDs, each
  implementing the non-loading `InputCounter.count` contract. A native-rejection
  trial registration must have no counter entry, not a permissive synthetic one.
- `quiescence`: exact registry keyed by Ollama backend ID, each a cancellation-
  cooperative async callback establishing the production proof in `SUPERVISION.md`.
  `ManagedQuiescence` now implements that transaction over an injected helper;
  the production helper/transport and mount/job-state validation remain missing.
- `memory`: object with cancellation-cooperative async
  `check(backend_config, model=..., context=..., resident=...)`. It must use fresh
  telemetry and measured budgets or reject. Passing a callback is not evidence
  of valid calibration, quiescence or token counting. Synthetic providers exist
  only in tests and must not be wired to deployed services.

The assembler revalidates credential contents and cross-scope separation even for
directly constructed credential objects. Optional backend credentials go to both
control and inference transports, never replacing client/admin authentication.
Unknown/missing dependency registry entries and credential-scope mismatches fail
before app setup.

For Strata, memory admission inspects the exact idle profile and passes whether it
is already loaded. For Ollama, memory admission runs inside lifecycle preparation,
**after same-backend eviction** where needed, and verifies exact model/context
residency before passing the resident flag. The scheduler's generic Ollama gate
does not demand a redundant cold allocation. The injected memory implementation
receives the complete immutable backend registration, including configured
cold/resident budgets, plus the actual requested context. It must explicitly
validate smaller-context budgets; the assembler never guesses a scaling formula.

Use `create_runner(runtime.app)` to obtain safe aiohttp transport settings; the
assembler does not create a runner/listener. AppRunner setup opens control-client
sessions but does not reconcile, contact models or admit inference. Startup is
maintenance. An embedding application/operator must explicitly reconcile then
resume; those actions are potentially model-affecting, not readiness probes.
Protected discovery/status still work during maintenance.

App cleanup invokes the HTTP layer's maintenance/drain while lifecycle control
sessions remain open, then closes all clients, including on drain failure.
Partial session setup also closes previously opened clients. **Cleanup can unload
models even if inference never started.** No installed backends are suitable test
targets: all runtime tests use ephemeral loopback fakes. The existing HTTP cleanup
still lacks a hard whole-process shutdown deadline/recovery supervisor; per-step
cooperative lifecycle deadlines do not replace this remaining deployment blocker.
Runtime objects are intended for one app lifecycle/event loop, not concurrent
reuse across runners. The assembler itself has no implicit credential loading,
auto-reconcile, auto-resume, service activation, process helper or CLI. The separate
opt-in `production.py` / `helper_service.py` / `operator.py` entrypoints explicitly
supply those side-effect boundaries as documented in `TRIAL.md`; startup still
never reconciles/resumes and uncommissioned or mismatched configuration is refused.

## Deliberately not wired

No listener address/public ingress, systemd unit names, shell hooks, tokenizer
module names or synthetic-counter selector is accepted. The initial runtime
deployment must separately establish:

- Verified non-loading input counters and effective contexts, failing closed if
  missing; tests' synthetic counters must never be deployment dependencies.
- Explicit stable AMD PCI telemetry device, fresh samples and calibrated
  per-profile/model/residency headroom selection.
- Production helper/systemd transport, durable pending-job tracking and verified
  cgroup-v2 mount/isolation for the transaction in [SUPERVISION.md](SUPERVISION.md);
  no no-op quiescence callback or fake helper.
- Wiring the explicit credential loader into startup with secure provisioning,
  separate administration routing, private upstream bindings, and consistent
  LAN/tailnet ACLs.
- Startup reconciliation, bounded shutdown and no implicit admissions/resume.

These are remaining integration requirements, not TODOs that a permissive schema
string or default callback can satisfy. Test fixture budgets/model names are
synthetic and are not installable configuration examples.

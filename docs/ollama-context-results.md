# Live Ollama context and speed tests — Narsil, 2026-11-05

## Selection

- Serve **Gemma4 12B (`gemma4:12b`) at 65,536 context / 8,192 maximum output**.
- Do not serve/register Ollama Qwen 27B. The user requires at least 20 output
  tokens/s on Ollama and prefers Strata when stronger capability is needed.
- Strata configuration is unchanged. No models were downloaded or deleted.
- These are direct backend measurements, not proof of gateway activation.

## Method

Coordinator was explicitly stopped by the user before testing. Strata was
verified unloaded; models were tested sequentially through private Ollama port
12434. Ollama 0.40.11 used flash attention, q8_0 KV, and one parallel request.
Requests forced `truncate=false`, `shift=false`, `think=false`, temperature 0.
RAM availability, swap use and total amdgpu VRAM usage were sampled every 200 ms.
VRAM includes desktop and other allocations, rather than just model accounting.
Ollama `/api/ps` Gemma `size_vram` under-reported actual use, so admission
conclusions use sysfs telemetry. An empty `/api/ps` can precede allocation
release; later tests added a three-second settling delay between models.

Raw synthetic requests' results, including actual token counts and timing:
[`benchmarks/ollama-context-2026-11-05.jsonl`](benchmarks/ollama-context-2026-11-05.jsonl).
No credentials or private prompts are included.

## Long-prompt results

| Profile | Actual prompt tokens | Output tokens | Output tokens/s | Prompt evaluation | Minimum available RAM | Minimum free VRAM |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemma, 64K, sustained generation | 56,049 | 256 | **53.2** | 65.7 s | 24.1 GiB | 5.29 GiB |
| Gemma, 64K, retrieve initial code | 56,043 | 8 | 28.7 | 65.9 s | 24.5 GiB | 5.09 GiB |
| Qwen, 64K, 48 GPU layers, retrieve initial code | 56,042 | 8 | **3.3** | 98.4 s | 22.8 GiB | 2.56 GiB |

Both retrieval tests returned the exact initial code, `MAPLE-7391`. Filler was
repeated `alpha beta gamma delta`; the sustained-generation request asked for
Linux troubleshooting tips and reached its 256-token output cap. Output speed
is `eval_count / (eval_duration / 1e9)`, excluding loading/prefill. Full response
latency is materially higher: Gemma's sustained request took 74.25 seconds,
including a 3.59-second model load and 65.68-second prompt evaluation.

These text-only, thinking-disabled synthetic tests establish useful measured
profiles, not general coding/tool quality, worst-case memory, guaranteed speed
for all prompts, or a benchmark of 8,192 generated tokens. No threshold-enforcing
runtime speed monitor was added.

## Context sweep

Qwen automatic placement responded at 64K, 32K, 16K and 8K, but left respectively
about **14 MiB, 31 MiB, 199 MiB and 502 MiB** VRAM free after short generation.
All were below the existing **512 MiB** resident floor. Explicit 48-layer GPU
offload made 64K memory-safe but too slow for the user's requirement. The
experimental configuration/code for pinning GPU layers was removed afterward.

Gemma answered short prompts at **8K, 32K, 64K, 128K and 256K**. At 256K it
still had about 2.9 GiB VRAM free. However, short prompts only establish context
allocation/load, not useful full-window performance. A near-full 252K-token
prompt was started, then cancelled when the user supplied the speed requirement.
No completed long-256K result or maximum safe/fast context is claimed.
**64K is the selected long-prompt-and-speed-tested profile.**

## Source changes and operational state

- `modules/apps/inference-coordinator/default.nix`: Gemma 64K/8192, Qwen removed
  from allowlist; Gemma cold budgets conservatively 12 GiB RAM / 14 GiB VRAM.
- `modules/apps/agents/models.json`: matching Gemma limits, Qwen registration
  removed. Cloud defaults and Strata providers unchanged.
- Resident margins remain 6 GiB RAM and 512 MiB VRAM.
- Tests updated to match the served profile and exercise overflow at 8193 output
  tokens rather than the previous 513.
- No mode switch, graphical logout, reboot, or service activation occurred.
- All test models unloaded after completion. Coordinator remains stopped pending
  user restart or normal Narsil activation; restarting the old closure restores
  its old model limits, not these source changes.

Validation: **434 inference tests and 21 mode tests pass**, including installed
Pi CLI chat/tool round trips against fake backends, and checks against a newly
built Narsil closure plus the existing Blade closure. Narsil build output:
`~/.local/state/narsil-inference/system-context-tested` ->
`/nix/store/2338f8sjwy4c5q5426cvsk20m0s5fnbs-nixos-system-narsil-26.11.20261030.1c89083`.
Built does not mean activated.

Normal activation of this checkout on Narsil and an updated checkout/model
registry on Blade is still needed. The live tests themselves did not require a
rebuild, activation, or access to the private coordinator credential.

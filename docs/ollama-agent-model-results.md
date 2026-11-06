# Additional local agent models — live tests, 2026-11-05

## User requirements and selected profiles

The user approved trials of Ornith 1.5 9B, Nemotron 3.5 Bolt E4B and LFM3 1.7B.
Ollama must sustain at least 20 output tokens/s; coding models should support at
least 128K context, preferably 256K. Strata remains the stronger-capability path.

| Model | Outcome | Source configuration |
| --- | --- | --- |
| `ornith-1.5:9b` | Installed, speed/memory eligible at 128K and 256K; coding quality remains experimental | 262144 context / 8192 output; Pi name explicitly says experimental coding |
| `nemotron-3.5-bolt:e4b` | Installed; 64K helper, not a >=128K coding model | 65536 context / 8192 output |
| `lfm3:latest` | Pull refused: package requires Ollama >=0.40.13; installed runtime is 0.40.11 | Not served or registered. User explicitly chose to leave pending, not update/bypass the version check |

Gemma4 12B stays at its previously measured 64K profile. Qwen 27B remains excluded
for speed/memory reasons. No old weights were deleted and no default cloud model
or Strata tuning changed.

## Downloads and runtime

Downloaded through the existing local Ollama API, not a separate daemon:

- Ornith: Q4_K_M, 9.0B, digest
  `e5df7dcdd8a263994df62d610317e07be0d6af23f96fcbd8543273058fce575e`.
  Metadata confirms Qwen35 architecture and 262144 maximum context.
- Bolt: Q4_K_M, 7.5B main text weights plus packaged vision/draft components,
  digest `69f2be39b309ade35ef04ee02507915f4cd839f6631e14425146cb6c9df3bd39`.
  Metadata confirms Gemma4 architecture, 65536 maximum text context and configured
  speculative decoding (`draft_num_predict=7`). Effective E4B naming is not the
  total parameter count or complete memory footprint.
- LFM3: registry returned `model requires ollama version v0.40.13 or newer
  (current version is v0.40.11)`. No unsupported-context or version workaround.

All inference was serial with the production coordinator explicitly stopped by
the user and Strata verified unloaded. Downloads completed before timed inference.
Ollama 0.40.11 uses flash attention, q8_0 KV and one concurrent inference request.
RAM, swap and amdgpu total VRAM were sampled every 200 ms. Free VRAM includes
other desktop allocations; Ollama's Gemma-family size accounting is not trusted
as the sole memory measurement. Resident floors remain 6 GiB RAM / 512 MiB VRAM.

## Direct long-context results

Requests forced `truncate=false`, `shift=false`, `think=false`, temperature 0.
Input was an initial deployment code, repeated `alpha beta gamma delta`, and a
request to retrieve that code then produce enough prose to reach 256 output tokens.

| Model/window | Actual input tokens | Output tokens | Output tokens/s | Prompt evaluation | Minimum RAM available | Minimum VRAM free |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ornith, 128K | 122946 | 256 | **39.0** | 70.3 s | 25.08 GiB | 5.70 GiB |
| Ornith, 256K | 254018 | 256 | **24.7** | 214.1 s | 24.86 GiB | 2.44 GiB |
| Bolt, 64K | 57407 | 256 | **66.5** | 33.5 s | 24.71 GiB | 7.40 GiB |

All three retrieved the exact initial `MAPLE-7391` code. Short-prompt sustained
256-token generation was about 71.2 tokens/s for Ornith at either window and
86.4–94.6 tokens/s for Bolt at 16K–64K.

Decode rate is actual backend `eval_count / eval_duration`, excluding load and
prefill. These measurements do not guarantee >=20 tokens/s for every workload,
reasoning mode, quantization, or 8192-token completion. In particular, 24.7 at
256K has less margin than the 128K result. Initial-code retrieval in repetitive
filler is not validation of large-codebase understanding or coding quality.

## Tool recovery and real Pi coding

Both models completed a native three-turn tool probe: request `src/settings.py`,
receive a missing-file error, retry `settings.py`, then report the actual returned
`TIMEOUT_SECONDS = 37` and correct source path. Ornith passed at both 128K/256K;
Bolt at 64K. This is bounded tool/error handling, not broad autonomous-agent proof.

A real installed Pi process was also connected through the actual coordinator
chat bridge and scheduler to real Ornith at a 256K configured window. It had only
read/edit/write tools and a disposable CSV-parser repository. No shell tool or
production files were exposed by the test prompt; generated code was checked
externally with six fixed tests, which were verified unchanged.

Results:

- Thinking off, first trial: **5/6** tests; wrong exception type for multiple CSV
  records, despite claiming the cases passed by construction.
- Thinking off, second trial: **2/6**; after real failure feedback, **5/6**. It
  still incorrectly rejected a quoted newline.
- Thinking low: **5/6** initially; after real failure feedback, **6/6**. It
  corrected the exception-type handling. Initial agent pass took 28.34 seconds;
  feedback/correction took another 21.36 seconds.

This is why Ornith is labelled **experimental**, not promoted to the default or
recommended for unattended coding. Thinking-on feedback recovery worked on this
small task; a single smoke test is not a benchmark. The code task had a small
actual prompt in a 256K allocation; it did NOT contain 254K tokens of repository
code. The long-context throughput test above is a separate result.

## Gateway changes needed for useful 256K

Source changes, not merely advertised model metadata:

- Added the exact installed Ornith/Bolt IDs to the coordinator allowlist and Pi
  registry with matching windows/output caps; no LFM3 placeholder.
- Conservatively estimated cold budgets: Ornith 16 GiB RAM / 14 GiB VRAM free;
  Bolt 12 GiB RAM / 10 GiB VRAM free. These are admission estimates, not measured
  worst-case guarantees. Resident floors unchanged; headless remains unmeasured.
- Raised coordinator and Blade request-body caps from **1 MiB to 4 MiB**.
  Aggregate coordinator queue-byte cap raised from 4 MiB to **16 MiB**, still bounded.
- Raised coordinator upstream read-idle wait from **180 to 600 seconds**: measured
  256K cold prefill alone exceeded the former limit. Total inference limit stays
  900 seconds; Blade already permits a 3600-second upstream wait.
- Access controls, no-retry policy, private credentials and model lifecycle policy
  are unchanged. Runtime/version guard remains pinned to 0.40.11.

A real **256K SSE request through the actual chat bridge/scheduler/lifecycle**
also passed using a temporary loopback listener and a synthetic client token:
**1,460,667-byte request**, HTTP 200, backend usage **254,018 input + 256 output
tokens**, correct initial-code retrieval. First event arrived at **218.10 seconds**;
completion took **228.53 seconds**, with minimum **2.30 GiB VRAM free** and
**24.52 GiB RAM available**. This directly exercises a body above the former
1 MiB cap and a wait above the former 180s limit. It does not activate or test
the installed Blade HTTPS route, peer ACLs or systemd restart callback; benchmark
release used serial native unload while the real coordinator was stopped.

Full synthetic results, including failed coding attempts rather than just the
successful retry:
[`benchmarks/ollama-agent-models-2026-11-05.jsonl`](benchmarks/ollama-agent-models-2026-11-05.jsonl).

## Validation and deployment state

Both normal host builds succeeded, without activation:

- Narsil: `~/.local/state/narsil-inference/system-agent-models` ->
  `/nix/store/2s66r5fk9m58hgz666p8dscjzw28bliv-nixos-system-narsil-26.11.20261030.1c89083`.
- Blade: `~/.local/state/narsil-inference/blade-agent-models` ->
  `/nix/store/svmjqy6mdaz8ix16pfdfzf9fsfx396qi-nixos-system-blade-26.11.20261030.1c89083`.

**434 inference tests and 21 mode tests pass**, including checks against both new closures and
installed-Pi fake-backend chat/tool tests. Built checks assert the 256K profile,
4 MiB body caps and >=600-second read wait. Direct real-model tests above are
separate from those fake-backend regressions. No mode switch, logout, reboot,
private-credential read or production service activation occurred.

Final inspection confirms both backends are unloaded and the production
coordinator remains stopped, as requested for testing. All benchmark processes
have completed and their temporary listeners are closed.

Normal Narsil and Blade activation is still required. Opening `/model` reloads
the updated repo-backed registry after each host's checkout has been updated.
Starting the old installed coordinator restores its old configuration, not these
new source profiles.

## Sources

- [Ornith model card](https://huggingface.co/ornith-ai/Ornith-1.5-9B)
- [Ornith Ollama package](https://ollama.com/library/ornith-1.5:9b)
- [Bolt Ollama package](https://ollama.com/library/nemotron-3.5-bolt:e4b)
- [LFM3 model card](https://huggingface.co/LiquidAI/LFM3-1.7B)

The local installed metadata and real responses, not these cards' advertised
benchmarks, determine the selected profiles.

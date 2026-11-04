# Upstream

Vendored from https://github.com/Astro-Han/karpathy-llm-wiki

Commit: `eafcc77001e496cc43499e4923b663aec722c813`

License: MIT (see LICENSE).

Includes the upstream skill, references, evidence checker, and its tests.
Local changes: the global-root and explicit-write policy at the beginning of
SKILL.md pins all operations to `~/.wiki/`, prohibits session ingestion, and
requires explicit permission for commits and pushes. Preserve that override
when updating the vendored files.

Home Manager exposes this directory as `~/.pi/agent/skills/karpathy-llm-wiki`.
Wiki content is separate, writable, and Git-managed under `~/.wiki/`; it is not
stored in the Nix configuration or Nix store.

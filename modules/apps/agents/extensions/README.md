# Nix-managed Pi extension bundle

`packages.pi-development-extensions` builds the runtime dependencies declared in
`package.json`, with exact transitive versions and integrity hashes recorded in
`package-lock.json`. Home Manager exposes the result at
`~/.pi/agent/nix-packages`.

The bundle directory is deliberately outside Pi's auto-discovery paths. Home
Manager enables the main role with a small re-export at
`~/.pi/agent/extensions/development.ts`, links the coder definition at
`~/.pi/agent/agents/coder.md`, and exposes Lens skills through
`~/.pi/agent/skills/pi-lens`.

Building the package alone does not activate these links. Applying Home Manager
enables the main entry point without replacing `~/.pi/agent/settings.json`,
installing npm packages into the user profile, or managing authentication.
Locally managed packages such as the personal wiki remain independent and are
not added to the shared Nix configuration.

## Contents

- `node_modules/@juicesharp/rpiv-ask-user-question/index.ts`
- `node_modules/@juicesharp/rpiv-todo/index.ts`
- `node_modules/@narumitw/pi-usage/dist/index.ts` and its `@narumitw/pi-tui-kit` runtime dependency
- `node_modules/pi-lens/dist/index.js`
- `node_modules/pi-split-view/split-view.ts`
- `node_modules/pi-lens/skills/` and its other published runtime assets
- `subagent/index.ts` and `subagent/agents.ts`, from the same flake input as Pi

The bundled subagent implementation is from the pinned upstream source with the
worker-isolation patch described below. Its sample agent definitions and automatic
workflow prompts are not included. Custom roles and the coder definition are
staged separately:

| Path | Contract |
| --- | --- |
| `roles/main.ts` | Main-agent factory: questions, todo, diagnostic Lens, delegation, provider usage, split-view UI, supervisor policy |
| `roles/worker.ts` | Worker factory: diagnostic Lens only; caller must disable discovered extensions |
| `roles/lens.ts` | Shared diagnostic Lens initializer with managed downloads and automatic mutations disabled |
| `roles/supervisor.md` | Main-agent research, approval, delegation, and review policy |
| `agents/coder.md` | One-step coding assignment using `strata-server/strata-coder` |

The main factory composes the question, todo, diagnostic Lens, delegation, provider
usage and split-view extensions. Its `before_agent_start` hook sets a stable `development_supervisor`
system-prompt section from `roles/supervisor.md`, preserving other sections,
custom system prompts and guidelines. Missing or empty policy rejects
initialization. The policy is registered only in the main role, not in shared
`AGENTS.md` files or the worker.

The usage and split-view extensions are main-agent UI only. `/usage` queries the
active provider, `/fast` toggles supported Codex Fast mode, and `/split`,
`/split-thinking`, `/split-tools`, `/files`, `/split-diff`, `/split-tools-view`,
`/split-height`, `/split-tools-width`, `/split-divider`, `/split-trim-response`
compose pi's fullscreen layout; `/split-save` persists the current layout as the
startup defaults for new windows. The split panels need pi's fullscreen TUI mode,
which stays a locally managed setting this bundle does not change. Both packages
keep their published defaults, including usage's experimental features being off,
and neither changes local model or TUI settings.

The worker definition deliberately leaves tool selection to Pi and its role entry
point so Lens tools are not accidentally excluded by a built-in-tool-only
allowlist. The approval/delegation policy is instruction-based, not a capability
sandbox: the main agent retains its inspection, validation and editing tools.

Pi supplies its host modules and typebox. The build uses `--legacy-peer-deps` to
avoid installing duplicate host peers. Dependency lifecycle scripts are disabled;
the one explicitly invoked, reviewed ast-grep postinstall script only copies the
already-fetched platform binaries. Nix patches those ELF binaries and native
modules to use the appropriate loader and runtime libraries.

## Activation and model selection

Review the configuration diff before applying it. From the repository root,
replace `<your-home-profile>` with the appropriate existing profile, such as
`james@laptop`:

```sh
home-manager switch --flake 'path:.#<your-home-profile>'
```

`path:.` includes new, untracked files during review. Once files are tracked,
normal `.#<your-home-profile>` flake references also work. Home Manager's normal
file-collision checks remain enabled; existing unmanaged files at the new paths
are not forcibly overwritten. Start a new Pi process or use `/reload` to load the
managed entry point after activation.

The extension preserves the selected model and locally managed default. To ensure
Sol is the main model when starting on a machine with another default:

```sh
pi --model openai/gpt-6.1-sol
```

Your existing Sol default need not change. The coder definition explicitly selects
`strata-server/strata-coder`, independently of the main model.

Do not also `pi install` the bundled packages into the same loadout: that can
register duplicate tools. If copies were previously installed locally, inspect
`pi list` and resolve those duplicate declarations before enabling the Nix-managed
main role; do not remove unrelated local packages such as the wiki.

## Worker launch isolation

`subagent-worker-isolation.patch` retains upstream spawning, JSON output handling,
agent discovery, model selection, and prompt cleanup. It adds these resource
controls to every child of this bundled dispatcher:

```text
--no-extensions --no-skills --no-prompt-templates
--extension <bundle>/roles/worker.ts
--skill <bundle>/node_modules/pi-lens/skills
```

Paths resolve relative to the installed dispatcher's module URL, not the project
working directory. The child still runs in the selected working directory, uses
JSON/one-shot mode with no persisted session, and receives the agent's prompt and
provider-qualified model. An explicitly selected agent model does not inherit the
supervisor's thinking setting.

The worker entry point initializes only diagnostic Lens. Project/user `AGENTS.md`
context remains enabled; this is resource isolation, not an OS sandbox. The flags
disable discovered resource loading, not all reading or resolution of existing
Pi configuration/package declarations. This dispatcher is dedicated to the coding
workflow: other agent definitions dispatched through it get the same worker
resource loadout, not separate planner/reviewer extensions.

## Diagnostic Lens policy

`lens-diagnostics-only.patch` patches both configuration-resolver copies in the
published Lens 4.4.8 distribution. It forces `no-autoformat` and `no-autofix` on,
and `lens-actionable-warning-autofix` off, before normal CLI/global/project/nested
configuration resolution. Unrelated flags retain their upstream behavior. The
build checks the package version and resolver-copy count and applies the patch
without fuzz; an upgrade requires an explicit compatibility review.

The shared initializer disables managed tool/LSP installation before importing
Lens. It probes the patched entry-point resolver with conflicting flag values
before registering Lens hooks, rejecting a missing or incorrect policy. Factory
errors propagate without a fallback to upstream Lens. The patched resolver is
exported as `resolveNixLensFlag` for these probes and compatibility tests; this is
an integration-specific export, not an upstream API.

This is not a read-only sandbox: explicit agent-requested edits, such as AST
replacements or LSP renames, remain governed by the approved task. Caches and
other Lens runtime state are not prohibited. Automatic source formatting, lint
fixes and warning quickfixes cannot be enabled through project settings; changing
this policy requires reviewing the Nix-managed patch.

## Validation

From the repository root:

```sh
nix build --no-link 'path:.#pi-development-extensions'
alejandra --check modules/apps/agents/default.nix modules/apps/agents/extensions.nix
```

`path:.` includes new, untracked files during review. The package's install checks:

- Run the patched ast-grep CLI and native JavaScript parser.
- Reject bundled Pi host peers and typebox.
- Use the pinned Pi loader to initialize all six extension factories.
- Initialize the actual worker entry point and verify it does not register the
  question, todo, or subagent tools, the usage and split-view commands, or the
  split-view flag.
- Verify that the main role composes every package's tools, commands, flags and
  shortcuts without collisions, including the usage and split-view commands and
  flag; its policy section preserves existing/custom
  prompts and remains stable across repeated user/custom runs.
- Reject a missing or empty supervisor policy without partial registration.
- Parse the coder definition with Pi's frontmatter parser and check its model.
- Exercise both patched resolvers with conflicting CLI values and global,
  project, and on-disk nested-project settings; check unrelated flag behavior.
- Initialize diagnostic Lens and verify download-disable overrides and tool scope.
- Inject missing/incorrect policy, import-failure and factory-failure fixtures;
  verify rejection without fallback and download disabling before module import.

- Exercise the real subagent tool's subprocess launch with a fixture child that
  uses Pi's actual argument parser and resource loader. A trusted baseline loads
  the managed main re-export, coder/skill symlinks and local-package fixtures;
  locally selected model settings and package declarations remain unchanged.
- Verify the worker's model, resource isolation (including exclusion of the real
  main entry point and its usage and split-view commands and the split-view flag),
  retained instructions, prompt fidelity/cleanup,
  working-directory override, and failure reporting; an unknown agent must not
  spawn a child or fall back to another model.

The checks use an isolated home with managed tool installation disabled. The
subprocess check replaces only the current entry script with a Node fixture;
upstream argument construction, spawning and JSON handling remain real. It does
not run Pi's full CLI entry point, start a session, make a model request, test
interactive dialogs, or exercise live LSP diagnostics. It uses the pinned host's
internal loader/parser intentionally, so Pi upgrades must pass these compatibility
checks.

## Updating dependencies

1. Edit the exact direct versions in `package.json`.
2. In this directory, use the repository's Node/npm version to regenerate the lock:

   ```sh
   npm install --package-lock-only --ignore-scripts --legacy-peer-deps --no-audit --no-fund
   ```

3. Review the manifest and lock changes, including native/optional dependencies.
4. Recompute `npmDepsHash` with nixpkgs' `prefetch-npm-deps` against the lockfile and
   update `../extensions.nix`.
5. Build and inspect the install-check results on each supported architecture.

Updating the Pi flake input also updates the bundled subagent implementation and
reruns its compatibility checks.

## Runtime safety requirements

The shared initializer forces `PI_LENS_DISABLE_LSP_INSTALL=1` and
`PI_LENS_DISABLE_TOOL_INSTALL=1`, even if the shell tried to permit downloads.
The patched resolver, rather than global mutation defaults, enforces the automatic
source-mutation policy. This affects the Nix-built Lens copy only, not separately
installed local packages.

The bundled dispatcher disables discovered extensions and explicitly loads the
worker entry point and Lens skills. Tool allowlists alone do not disable extension
hooks, and direct extension loading does not load package-manifest skills.

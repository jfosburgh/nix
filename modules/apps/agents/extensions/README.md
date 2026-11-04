# Nix-managed Pi extensions

`packages.pi-development-extensions` installs these three plugins:

| Plugin | Pinned version | Purpose |
| --- | --- | --- |
| `@juicesharp/rpiv-ask-user-question` | 2.15.0 | Structured questions |
| `pi-web-access` | 0.36.0 | Existing web search and content retrieval |
| `pi-btw` | 0.8.1 | `/btw` and `/side` parallel side conversations |

Web access retains the previously installed version rather than upgrading it.
Exact transitive dependency versions and integrity hashes are recorded in
`package-lock.json`.

Home Manager exposes the bundle at `~/.pi/agent/nix-packages`, outside Pi's
auto-discovery paths. Three small re-export files under `~/.pi/agent/extensions/`
load only the plugins above. The existing `development.ts` path now loads just
the questions plugin; `web-access.ts` and `btw.ts` load the other two. The bundled
BTW skill is linked at `~/.pi/agent/skills/btw`.

The previous todo, Lens, subagent dispatcher, usage, split-view, supervisor
policy, coder definition, and Lens skills are no longer included. Home Manager
removes the former managed coder and Lens skill links when activated.

Pi supplies its own host modules and typebox; `--legacy-peer-deps` prevents
bundling duplicate host peers. Dependency lifecycle scripts are disabled.

## Personal data and settings

This cleanup does not reset model configuration, provider credentials, sessions,
themes, or personal settings. `~/.pi/agent/settings.json` remains a writable,
repo-backed symlink to `modules/apps/agents/settings.json`; Pi's writes there
appear as working-tree changes. Model configuration remains managed separately.
The existing SearXNG service and `SEARXNG_BASE_URL` setting are preserved.

The module does not delete unmanaged plugins or project-level `.pi` resources.
Do not also declare these same plugins through `pi install`, which could register
duplicate tools. Old cached npm directories alone do not load plugins; inspect
`pi list` for any independent declarations before activation.

BTW creates real side sessions with coding tools. `/btw:ask` is its read-only
mode. BTW does not inherit the main session's extension tools by default, so web
access in a BTW thread requires separate opt-in configuration; this module does
not enable that or change BTW's defaults.

## Validation and activation

From the repository root:

```sh
nix build --no-link 'path:.#pi-development-extensions'
alejandra --check modules/apps/agents/default.nix modules/apps/agents/extensions.nix
git diff --check
```

The build checks the installed dependency set against the lockfile, rejects
obsolete bundled resources and duplicate host peers, and loads all three
plugins using the pinned Pi host. It checks question/search tools, BTW commands,
registration collisions, and the absence of the removed tools and UI commands.
The check uses an isolated home. It does not start sessions, make model or web
requests, or exercise interactive dialogs and BTW side conversations. Build
checks must be re-reviewed when updating Pi or the plugins.

Building does not activate the configuration. After reviewing the diff, apply
your existing Home Manager profile, for example:

```sh
home-manager switch --flake 'path:.#<your-home-profile>'
```

Normal Home Manager file-collision checks remain enabled. Start a new Pi process
after activation so the old plugin code and supervisor instructions are no
longer loaded. Existing session history is preserved.

## Updating dependencies

1. Update exact versions in `package.json`.
2. Regenerate the lockfile in this directory:

   ```sh
   npm install --package-lock-only --ignore-scripts --legacy-peer-deps --no-audit --no-fund
   ```

3. Review the dependency graph and update the version assertions in
   `check-load.mjs`.
4. Recompute `npmDepsHash` in `../extensions.nix` using nixpkgs'
   `prefetch-npm-deps`, or use Nix's fixed-output hash mismatch workflow.
5. Run the validation commands above on each supported architecture.

# Shared SearXNG on Blade

## Configuration

SearXNG is now configured only by `modules/apps/searxng/default.nix`, imported by
Blade. The shared `agents` host module no longer enables a search server.
Home Manager's agents module sets:

```sh
SEARXNG_BASE_URL=https://search.threegoldenhairs.me
```

The hostname provides both browser search and GET `/search?format=json` for
agent tools. A Search link is included on the dashboard.

Blade runs SearXNG via uWSGI HTTP on **127.0.0.1:8888**, with nginx providing
HTTPS. The backend port is not opened in the firewall. Query access logging is
disabled in uWSGI and this nginx application location; this does not guarantee
that upstream search engines or application error logs never retain queries.

A root-owned oneshot provisions `/var/lib/searxng/environment` once, before
`searx-init`. This persistent secret is generated on the host, not committed,
placed in the Nix store, printed, or copied from a client home. Do not delete it
on routine rebuilds. Existing client secret files are not automatically removed.

## Network trust boundary

The entire application location (HTML, assets and JSON API) permits loopback,
LAN `192.168.1.0/24`, tailnet IPv4 `100.64.0.0/10`, and tailnet IPv6
`fd7a:115c:a1e0::/48`; everything else is denied. As with the dashboard, the
OPNsense source `192.168.1.1` is explicitly denied **before** allowing the LAN
because WAN forwarding currently SNATs traffic to that address. LAN clients must
connect directly using private DNS, not public-IP hairpin routing. Revisit this
policy if the network/NAT topology changes. Forwarded headers are not used to
grant access. Every allowed client can use the search API without an API key.

The separate ACME challenge location remains public for certificate renewal;
the application does not. Headscale adds an A record resolving the hostname to
Blade's tailnet IP `100.64.0.1`.

Manual prerequisites:

- Ensure public DNS/forwarding supports the existing Blade HTTP-01 ACME setup
  for `search.threegoldenhairs.me`; do not assume wildcard coverage.
- Add an OPNsense/Unbound LAN host override resolving that hostname to **Blade's
  LAN IP**, as with the dashboard.
- Tailnet clients must accept Headscale DNS. Verify TLS trust and resolution.

## Migration order — deploy server before clients

No running services were changed while preparing this migration. SSH to Blade
failed authentication in this session, so live service/DNS/TLS/search tests
remain outstanding. Do not switch clients first: their new endpoint must work
before their local search services are removed.

From the repository root (the `path:` form includes new untracked modules):

```sh
# Build/review before activation.
nix build 'path:.#nixosConfigurations.blade.config.system.build.toplevel'

# Deploy Blade using your working SSH key/agent and privilege escalation.
nixos-rebuild switch --flake 'path:.#blade' \
  --target-host james@100.64.0.1 --build-host localhost --elevate=sudo
```

On Blade, inspect service health:

```sh
systemctl status searxng-secret searx-init uwsgi nginx
journalctl -u searx-init -u uwsgi -u nginx -b
curl --fail --get http://127.0.0.1:8888/search \
  --data-urlencode 'q=NixOS documentation' --data-urlencode 'format=json'
```

From both trusted LAN and tailnet clients:

```sh
curl --fail --get https://search.threegoldenhairs.me/search \
  --data-urlencode 'q=NixOS documentation' --data-urlencode 'format=json'
```

Check actual returned results, not merely HTTP 200. Check the browser UI and
assets too. Verify application routes return 403 from public and router-SNAT
sources, and that the raw backend port cannot be reached remotely. ACME
challenges are intentionally exempt from application access restrictions.

Only after those checks, activate the updated NixOS configurations on agent
hosts (currently Narsil and Sting) and the applicable Home Manager profiles.
This removes their local search services and installs the shared endpoint.
Narsil's current desktop/headless mode should be preserved during deployment;
do not use a plain desktop rebuild switch while intentionally headless.

Start a fresh login/session or reload the managed environment and restart Pi
so it receives the new variable. Existing processes retain their old environment.
Independent Home Manager profiles also need activation, including clients that
never imported the agents NixOS module. Review any unmanaged per-client search
URL overrides without exposing or overwriting credentials.

For a temporary client smoke test before switching its local service off:

```sh
SEARXNG_BASE_URL=https://search.threegoldenhairs.me pi
```

Rollback is the previous NixOS/Home Manager generation, which restores the
local service and localhost endpoint on clients. Keep the old client secret
file until the migration has been verified. No secrets were deleted.

## Validation performed during preparation

- Evaluated Blade's complete system derivation successfully (existing Nextcloud
  upgrade warning remains unrelated).
- Built the generated Blade nginx configuration successfully.
- Evaluated Blade SearXNG enabled, uWSGI loopback binding, JSON/GET settings,
  external environment-file path and dependency chain for secret provisioning.
- Evaluated Narsil and Sting with `services.searx.enable = false`.
- Formatting and diff checks run on the changed configuration.

These are configuration/build checks, not a complete Blade system build or a
live deployment. Real search quality, certificates, DNS, ACL behavior and
client application behavior still require the migration checks above.

# Narsil's optional Strata server boot mode

Normal Narsil boot remains a desktop. The `strata-server` NixOS specialisation adds a separate boot-menu entry that:

- boots to `multi-user.target`, with no greeter, Hyprland or GNOME;
- disables both VT greeters, the session-switch watcher, Ollama and PipeWire;
- keeps the AMD compute driver, Wi-Fi/NetworkManager, SSH and Tailscale;
- enables Bluetooth and its adapter power-on policy in the configuration (see the live-switch caveat below);
- disables automatic sleep;
- starts Strata Coder with **262,144-token context**, INT8 KV streamed through a **32,768-token VRAM window**, WMMA prompt attention, MTP, and a **1,024 MiB cache reserve**;
- exposes it to trusted LAN/Tailscale clients through Blade's nginx, without client API keys.

The 256K profile was tested headlessly on Narsil with a roughly 260K-token synthetic code prompt and three-depth marker retrieval. The initial run reached 1,382 prompt tok/s and 25.7 generation tok/s, with at least 5.2 GiB available RAM and no request-time swap-out. A second cold-start ~260K prompt also passed, at 1,364 prompt tok/s and 14.8 generation tok/s, but caused about 713 MiB of swap-out. Warm cache/adaptive state matters; 25.7 tok/s is not a guaranteed full-context rate. These are capacity/performance checks, not broad quality or production stability guarantees. WMMA changes floating-point rounding. Keep the 6 GiB resident-RAM headroom and monitor real long conversations for paging.

Desktop mode's separate manual Strata launcher/config was tuned to 128K, a 3 GiB VRAM reserve, KV streaming and WMMA. This Nix module does not manage that mutable desktop JSON, start a desktop Strata service, or change your default pi model. Benchmark reports and raw measurements are in `/home/james/dev/Strata-data/benchmarks/desktop-tuning/` and `/home/james/dev/Strata-data/benchmarks/headless-context/`.

## Existing installation

The service uses the installation already prepared on Narsil:

- engine/server/venv: `/home/james/dev/Strata`;
- models, tokenizer, packs and MTP: `/home/james/dev/Strata-data`.

It does not download, compile or run inference during a Nix build. Missing files cause the service to fail; install/repair them as `james` before booting server mode. Keep the local venv and engine in place. The Nix generation roots Python and ROCm runtime dependencies; it does not make the mutable installation reproducible. A future Strata upgrade may require updating the pinned tuning-table name and runtime assumptions in `default.nix`.

The service runs as `james` with GPU groups, read-only access to home, managed writable runtime/cache/log directories, and a persistent HIP temporary directory. Configuration is generated as `/etc/strata/server.json`, independent of the desktop JSON. Do not start the manual desktop launcher at the same time.

## Network trust boundary

```text
LAN / Tailscale client
  -> https://strata.threegoldenhairs.me (Blade, 100.64.0.1)
     nginx allows LAN/Tailscale source addresses; denies WAN/router-SNAT
  -> http://100.64.0.3:8081 over encrypted Tailscale
     Narsil nginx allows ONLY Blade's 100.64.0.1 source address
  -> http://127.0.0.1:8080
     Strata itself is loopback-only, with explicit allowed_hosts
```

All routes (UI, API and model controls) have the source-address restrictions, not just the homepage. The ACME HTTP challenge location on Blade remains public for certificate renewal. API bodies/responses are unbuffered and long inference timeouts are supported.

**Trust:** every permitted LAN/tailnet client can use the model and its UI controls without a secret. This is not an internet-facing public endpoint. Do not remove the nginx allow/deny rules or trust arbitrary client-supplied forwarding headers. Blade is trusted to forward requests, and other Narsil local processes can access the loopback API.

The rules follow the existing dashboard's topology: `192.168.1.0/24` LAN, `100.64.0.0/10`/`fd7a:115c:a1e0::/48` Tailscale, and OPNsense at `192.168.1.1`. WAN forwarding is currently SNATed to the router, so that address is denied before the LAN allow. Revisit these rules if the router/proxy topology changes. Narsil's upstream port is allowed on `tailscale0` only; nginx's own Blade-only ACL also protects it when Tailscale's default trusted-interface firewall bypass applies.

### DNS prerequisites

1. Make `strata.threegoldenhairs.me` resolve publicly to Blade's existing public HTTPS/ACME entry point (or ensure your wildcard DNS already covers it). Certificate issuance requires the existing HTTP challenge forwarding to Blade.
2. For LAN clients, add an OPNsense/Unbound host override mapping this hostname directly to **Blade's LAN address**, as for the dashboard. Going through the public IP/hairpin NAT is deliberately denied.
3. Tailnet DNS gets an extra A record to `100.64.0.1` from Headscale after Blade is deployed. Clients must accept tailnet DNS.

The proxy returns 502/connection errors when Narsil is in ordinary desktop mode, because its headless upstream proxy is intentionally absent then. The dashboard link remains visible.

## Build and deploy (no automatic reboot)

From `/home/james/nix`, first build/check:

```sh
nix build .#nixosConfigurations.narsil.config.system.build.toplevel
```

Install Narsil's new boot generation **without switching the running desktop**:

```sh
sudo nixos-rebuild boot --flake /home/james/nix#narsil
```

Deploy Blade's nginx, Headscale DNS record and dashboard link:

```sh
nixos-rebuild switch --flake /home/james/nix#blade \
  --target-host james@100.64.0.1 --build-host localhost --elevate=sudo
```

These changes have not been activated simply by editing/building this repository. DNS/router overrides are a separate manual step. No passwords or API secrets need to be copied into Nix.

For boot-menu selection, reboot Narsil and choose the entry containing **strata-server** from systemd-boot (hold Space during boot if the menu is hidden). To return to the desktop on a later boot, select the normal NixOS entry. You can also switch live using the commands below.

Narsil's current Wi-Fi profile is system-wide and autoconnects, so it should connect without a desktop login. Verify remote access on the first boot before leaving it unattended.

## Live switching without rebooting

To install the new commands into the **running desktop** for the first time:

```sh
sudo nixos-rebuild switch --flake /home/james/nix#narsil
```

This activates the normal desktop configuration with the switching tools; it does not enter headless mode. `nixos-rebuild boot` alone only installs the next boot generation and does not add commands to the current shell's system path.

When already headless, activate a newly built headless profile without accidentally restoring the base desktop with:

```sh
sudo nixos-rebuild switch --flake /home/james/nix#narsil --specialisation strata-server
```

This installs the matching parent generation as well, so `narsil-desktop` can resolve the return path. A plain rebuild without `--specialisation` activates the base desktop.

Then use:

```sh
narsil-headless          # confirm, log out graphical sessions, start 256K Strata
narsil-desktop           # stop Strata, release VRAM, start the normal desktop
narsil-mode status      # current mode, generation and relevant service states
```

The commands ask for sudo when necessary. **Save your work first:** entering headless mode logs out **all** graphical users, including `james` and `work`. Their applications and graphical terminals close. This is not suspend/resume; returning starts a fresh desktop using the normal greeter/autologin configuration.

Run the return command over SSH or from a text console (for example Ctrl+Alt+F3). Bluetooth is enabled in the configuration, with the normal adapter power-on policy and retry service. However, the first live switch showed that isolating `multi-user.target` can stop `bluetooth.service`, because it is only pulled in through `bluetooth.target`. This runtime issue has not been fixed; do not rely on Bluetooth input for recovery. Use SSH or a wired/USB-receiver keyboard. PipeWire is off, so Bluetooth audio is not provided in headless mode.

Before the first switch, verify you can log in on Ctrl+Alt+F3 using the Bluetooth keyboard (use your normal account password, not just a graphical unlock method), then return to your graphical VT. Prefer also verifying an SSH login from another device. Mouse input is not normally used by a text console, even though Bluetooth remains available. Keep a wired/USB-receiver keyboard or working SSH connection as recovery if Bluetooth fails to reconnect.

The switch deliberately leaves SSH/text sessions alone; it does not terminate the whole user manager. The switching worker is a root system service, independent of the graphical terminal it closes. Progress remains available through:

```sh
journalctl -u 'narsil-mode-switch@*' -b -f
systemctl status narsil-mode-switch@headless.service
systemctl status narsil-mode-switch@desktop.service
```

For intentional non-interactive automation, use `narsil-headless --yes` or `narsil-desktop --yes`. Concurrent switches are refused. The worker checks installation files before ending sessions, stops old manually launched Strata processes, and waits for the 256K server's health check before declaring success. Returning stops Strata before restoring the compositor. If entering headless mode fails after logout, it attempts to restore the desktop; inspect the journal if recovery itself fails.

Both directions activate the corresponding existing NixOS generation with `switch-to-configuration test`, then select its systemd target. They do **not** rebuild the system, reboot, or change the bootloader selection. The matching desktop generation is resolved from the running generation and installed profiles, not blindly from the newest profile. Entering headless mode through these commands creates a root-owned GC root preserving the desktop generation for the return trip; it is removed after a successful return. A direct boot into a specialisation instead relies on its matching installed system profile until the first live switch.

An already-headless/desktop request is a no-op. To restart only Strata when already headless, use `sudo systemctl restart strata` instead. Do not run a rebuild or another manual model launcher concurrently with a switch.

## Verify after the first server-mode boot or live switch

On Narsil over SSH:

```sh
systemctl get-default                 # multi-user.target
systemctl status strata nginx
journalctl -u strata -b -f
curl http://127.0.0.1:8080/health     # loaded=true, max_context=131072
```

Engine log: `/var/log/strata/engine.log`. Generated config: `/etc/strata/server.json`.

Allow a few minutes for initial load. Monitor available RAM, zram swap, actual VRAM use and engine errors; the reserve flag sizes the expert cache rather than enforcing a hard GPU-memory cap.

From Blade, the upstream should work:

```sh
curl -H 'Host: strata.threegoldenhairs.me' http://100.64.0.3:8081/health
```

From a permitted LAN/Tailscale client:

```sh
curl https://strata.threegoldenhairs.me/health
curl https://strata.threegoldenhairs.me/v1/models
```

Also check from an untrusted/public connection that the HTTPS endpoint returns 403 rather than exposing the model. Non-Blade tailnet clients must not be able to use Narsil's upstream port directly (nginx returns 403).

## Pi

The shared pi model configuration adds a separate provider so the existing desktop provider remains unchanged:

```sh
pi --provider strata-server --model strata-coder --thinking low
```

Or select **Strata Coder (Narsil server, 128K)** with `/model`. Its `strata-private-network` key is only a dummy string to make pi list a keyless compatible endpoint; the server does not validate it and clients need no real key. The hostname must resolve privately as described above.

To stop inference while remaining in server mode:

```sh
sudo systemctl stop strata
```

To start it again:

```sh
sudo systemctl start strata
```

## Validation before deployment

- Built Narsil's complete system closure, including the `strata-server` specialisation.
- Evaluated both configurations: desktop remains graphical with Ollama; server is multi-user with the desktop and Ollama disabled, SSH/Tailscale retained, and no failed NixOS assertions.
- Built both generated nginx configurations and verified the Strata systemd unit with `systemd-analyze verify`.
- Exercised the generated ACLs in isolated loopback nginx instances: all 12 LAN, Tailscale, public, router-SNAT and Blade-only cases passed. These tests simulated peer addresses; they do not replace checking the actual network after deployment.
- Validated pi's local 64K and remote 128K model configuration with pi's schema.
- Built and ShellChecked the live-switch command/worker packages in both configurations, and checked that the worker service is identical in parent and child and survives target isolation.
- Ran the mocked lifecycle/helper tests in `modules/hosts/narsil/tests/test_live_modes.py`: session selection, SSH preservation, GPU-release ordering, confirmation, concurrency, generation matching and failure recovery. Run with `python -m unittest discover -s modules/hosts/narsil/tests -v`.

No actual live mode switch was performed during validation, so the current graphical session was not interrupted. No generation has been activated, no boot entry installed, and neither host has been rebooted as part of these checks. The first actual headless model load, end-to-end TLS/DNS access, and real external-denial check still need to be done after deployment.

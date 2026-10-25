# Local live dictation

Import `self.nixosModules.voxtype` in a host's module list (currently only
`modules/hosts/sting/default.nix`). This installs Voxtype and a Hyprland graphical-
session user service. It doesn't change shared Home Manager profiles or grant raw
input access. The service does not load the model in work's GNOME session.

## Use

Tap **Ctrl + Alt + Space**, release the keys, then speak. Text appears in the
focused text field incrementally. Tap the same shortcut again to stop.

**Ctrl + Alt + Shift + Space** instead streams into the persistent Pi agent's
input, even when its panel is hidden. It starts Pi if necessary, but never
changes application focus. Stopping the recording **automatically submits** the
Pi prompt once streaming finalization completes, even with the panel hidden.
Cursor dictation never submits. Cancel, empty output, the safety timeout, and
routing/backend failures do not submit. This requires the Hyprland Home Manager launcher
(`launch-pi-panel`); see `../hyprland/PI-PANEL.md` for setup and persistence.
Either shortcut stops an active recording without changing its destination.

Don't
change the focused application or move the cursor while dictating: streaming
output may revise the recent partial text using Backspace.

**Ctrl + Alt + Escape** cancels recording. In streaming mode Voxtype attempts to
rewind that recording's inserted text with Backspace, so don't move the cursor
while recording. Reloading Hyprland also cancels dictation.

Live typing requires toggle activation on Hyprland: synthetic output can disrupt
the release tracking for a held push-to-talk shortcut. The previous Right Ctrl +
Right Alt hold/release chord is therefore no longer bound.

## Model and limits

Uses Voxtype's ONNX-enabled package and the **Parakeet Unified English 0.6B**
cache-aware streaming model, running on the local CPU. All model files (~2.5 GB
total) are revision- and hash-pinned, downloaded in full into the Nix store during
the build. No hosted inference, Hugging Face API calls, accounts, or tokens are
needed at runtime; microphone audio stays on this machine.

The model stays loaded for responsiveness. This costs more RAM than the previous
Whisper `base.en` setup. Streaming is experimental; assess accuracy, partial-text
corrections, and CPU load on sting before settling on it.

Uses the default microphone and has a **five-minute safety timeout** (up from the
previous 60 seconds). Streaming doesn't remove that recording limit; tap to start
again after it stops. Streaming uses 0.56-second chunks, 5.6 seconds of left
context, and 0.56 seconds of right context (parakeet-rs defaults). These are set
explicitly because Voxtype 1.0.1's own defaults fail the model's frame-alignment
validation. Expect roughly a second or more of latency, not instant characters.

Cursor text is inserted using `wtype`, without pressing Enter. Clipboard fallback is
available if typing fails, but the live-insertion experience should be tested in
each target application.

## Recording indicator

A small **live waveform OSD** appears near the top center while dictating into
either destination. It uses Voxtype's Quickshell frontend, a minimal 260×48 panel,
and the daemon's existing audio-level stream—not a second microphone capture.
It does not take keyboard focus or intercept clicks. It hides at idle/cancel and
is supervised by the daemon, so restarting/stopping Voxtype also stops the OSD.
Streaming can remain active briefly while the backend drains after capture ends.

The QML and Quickshell dependencies are packaged declaratively in Nix; no
`voxtype setup quickshell` or per-user installation is needed. Adjust `osd` in
`default.nix` for position/style. The old persistent notification service is removed.

Voxtype's start, stop/transcribing, and transcript notifications are disabled.
Noctalia also suppresses other Voxtype status/clipboard notices, without disabling
clipboard fallback. There are no recording notifications or notification-history
entries. Desktop Pi completion notifications are separate; see `../hyprland/PI-PANEL.md`.

`modules/apps/hyprland/noctalia-settings.toml` disables the duplicate transient
privacy OSD. Noctalia exposes this switch for all capture kinds together, so this
also disables its brief camera/screen-share capture pop-ups; it does not disable
capture itself or the privacy bar widget.

The keyboard-layout OSD is also disabled: each `wtype` virtual keyboard sends
layout events as it is created/removed (English (US) / none), which otherwise
flash a keyboard pop-up during streaming. Volume, brightness, and lock-key OSDs
are unaffected.

## Activate on sting

```sh
sudo nixos-rebuild switch --flake /home/james/nix#sting
hyprctl reload
systemctl --user restart voxtype.service
noctalia msg config-reload
```

A fresh Hyprland login also starts the service automatically. The waveform itself
needs no Home Manager switch, `voxtype setup`, or manual model download. For the
updated Pi launcher/completion notifications, also follow `../hyprland/PI-PANEL.md`.

```sh
systemctl --user status voxtype.service
journalctl --user -u voxtype.service -f
voxtype record cancel
```

The service's generated config is at `/etc/voxtype/config.toml`.
Change settings in `default.nix`, not in that generated file. To return to
hold/release dictation, restore the Whisper engine/package/model and the previous
Hyprland bindings together; do not use hold/release with streaming enabled.

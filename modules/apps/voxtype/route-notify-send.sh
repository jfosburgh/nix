# Voxtype 1.0.1 uses the same post-output hook for success and backend errors.
# It awaits this error notification before invoking that hook. Veto submission
# here even if the user pressed stop just as the streaming backend failed.
# This wrapper exists ONLY on Voxtype's PATH; other applications are untouched.
if [[ -n "${XDG_RUNTIME_DIR:-}" && -f "$XDG_RUNTIME_DIR/voxtype-pi-target" ]]; then
  for arg in "$@"; do
    if [[ "$arg" == 'Streaming Error' ]]; then
      : >"$XDG_RUNTIME_DIR/voxtype-pi-failed"
      rm -f "$XDG_RUNTIME_DIR/voxtype-pi-submit"
      break
    fi
  done
fi
exec "$VOXTYPE_REAL_NOTIFY_SEND" "$@"

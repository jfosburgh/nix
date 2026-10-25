target="${1:-cursor}"
case "$target" in cursor|pi) ;; *) echo 'Expected cursor or pi' >&2; exit 2 ;; esac

exec 9>"$XDG_RUNTIME_DIR/voxtype-dictation.lock"
flock -n 9 || exit 0
state=$(voxtype status --format json | jq -er '.class')
case "$state" in
  recording|streaming)
    # Keep the destination through streaming teardown. The post-output hook
    # submits Pi after backend finalization, not directly on the shortcut.
    if [[ -f "$XDG_RUNTIME_DIR/voxtype-pi-target" ]]; then
      : >"$XDG_RUNTIME_DIR/voxtype-pi-submit"
    fi
    if ! voxtype record stop; then
      rm -f "$XDG_RUNTIME_DIR/voxtype-pi-submit"
      exit 1
    fi
    ;;
  idle)
    rm -f "$XDG_RUNTIME_DIR/voxtype-pi-submit" \
      "$XDG_RUNTIME_DIR/voxtype-pi-chars" "$XDG_RUNTIME_DIR/voxtype-pi-failed"
    if [[ "$target" == pi ]]; then
      # Start the dedicated agent if needed, without showing/focusing its window.
      launch-pi-panel --ensure
      : >"$XDG_RUNTIME_DIR/voxtype-pi-target"
    else
      rm -f "$XDG_RUNTIME_DIR/voxtype-pi-target"
    fi
    voxtype record start
    # Keep the lock until the asynchronous start has been observed, so a quick
    # second shortcut cannot change the destination before the daemon starts.
    for ((i = 0; i < 40; i++)); do
      state=$(voxtype status --format json | jq -er '.class')
      [[ "$state" != idle ]] && exit 0
      sleep 0.05
    done
    voxtype record cancel
    echo 'Dictation did not start; cancelled the pending recording' >&2
    exit 1
    ;;
  stopped)
    echo 'Voxtype is not running' >&2
    exit 1
    ;;
  *)
    # The previous recording is still being finalized; do not reroute it.
    echo "Voxtype is busy ($state); try again when idle" >&2
    ;;
esac

if [[ ! -e "$XDG_RUNTIME_DIR/voxtype-pi-target" ]]; then
  exec "$VOXTYPE_REAL_WTYPE" "$@"
fi

# Once routed to Pi, NEVER fall through to a real virtual keyboard, even if the
# tmux pane disappears. In particular, a failed backspace must not cause
# Voxtype's streaming layer to try another cursor-directed keyboard backend.
report_failure() {
  : >"$XDG_RUNTIME_DIR/voxtype-pi-failed" || true
  rm -f "$XDG_RUNTIME_DIR/voxtype-pi-submit" || true
  logger -t voxtype-pi 'Pi input routing failed; discarded output rather than typing into the active application' || true
  exit 0
}

[[ "$(tmux -L pi-panel display-message -p -t agent:0.0 '#{pane_current_command}' 2>/dev/null)" == pi ]] || report_failure

# Track this recording's remaining input, not a draft that was already there.
# Empty/retracted output must not accidentally submit an older prompt.
count_file="$XDG_RUNTIME_DIR/voxtype-pi-chars"
count=0
if [[ -f "$count_file" ]]; then
  count=$(<"$count_file")
  [[ "$count" =~ ^[0-9]+$ ]] || report_failure
fi

paste_text() {
  [[ -n "$1" ]] || return 0
  printf '%s' "$1" | tmux -L pi-panel load-buffer -b pi-dictation - || report_failure
  # Bracketed paste protects newlines and escape-like text from being treated
  # as submit keys. The separate completion hook sends Enter after finalization.
  tmux -L pi-panel paste-buffer -d -p -b pi-dictation -t agent:0.0 || report_failure
  count=$((count + ${#1}))
  printf '%s\n' "$count" >"$count_file" || report_failure
}

while (( $# )); do
  case "$1" in
    -s|-d)
      # wtype's initialization/inter-key delays aren't needed for tmux input.
      (( $# >= 2 )) || report_failure
      shift 2
      ;;
    -k)
      (( $# >= 2 )) || report_failure
      case "$2" in
        BackSpace)
          tmux -L pi-panel send-keys -t agent:0.0 BSpace || report_failure
          count=$((count > 0 ? count - 1 : 0))
          printf '%s\n' "$count" >"$count_file" || report_failure
          ;;
        Return) paste_text $'\n' ;;
        Tab) paste_text $'\t' ;;
        *) report_failure ;;
      esac
      shift 2
      ;;
    -P|-p|-M|-m)
      # Optional Shift prefix / Shift+Enter output; Return above is a draft
      # newline, regardless of modifier state. Never synthesize desktop keys.
      (( $# >= 2 )) || report_failure
      case "$2" in Shift_L|Shift_R|shift) ;; *) report_failure ;; esac
      shift 2
      ;;
    --)
      shift
      for text in "$@"; do paste_text "$text"; done
      break
      ;;
    *) report_failure ;;
  esac
done

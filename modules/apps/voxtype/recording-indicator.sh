# The daemon is the source of truth, not the shortcut's last pressed state.
# A separate notification id lets us explicitly close the never-expiring toast.
id_file="$XDG_RUNTIME_DIR/voxtype-indicator/notification-id"
notification_id=""

close_notification() {
  if [[ -f "$id_file" ]]; then
    notification_id=$(<"$id_file")
  fi
  if [[ "$notification_id" =~ ^[0-9]+$ && "$notification_id" != 0 ]]; then
    dbus-send --session --type=method_call --print-reply \
      --dest=org.freedesktop.Notifications /org/freedesktop/Notifications \
      org.freedesktop.Notifications.CloseNotification \
      "uint32:$notification_id" >/dev/null 2>&1 || true
  fi
  rm -f "$id_file"
  notification_id=""
}

# Also used as ExecStopPost, including after a crash or forced termination.
if [[ "${1:-}" == --close ]]; then
  close_notification
  exit 0
fi

trap close_notification EXIT
trap 'exit 0' TERM INT
close_notification

while IFS= read -r status; do
  state=$(jq -r '.class // "stopped"' <<<"$status")
  case "$state" in
    recording|streaming)
      if [[ -z "$notification_id" ]]; then
        notification_id=$(notify-send --print-id --app-name=Dictation \
          --icon=audio-input-microphone --expire-time=0 \
          --hint=boolean:transient:true \
          'Microphone recording' 'Ctrl + Alt + Space to stop')
        [[ "$notification_id" =~ ^[0-9]+$ && "$notification_id" != 0 ]]
        printf '%s\n' "$notification_id" >"$id_file"
      fi
      ;;
    *) close_notification ;;
  esac
done < <(voxtype status --follow --format json)

# An unexpectedly exited status follower should be restarted, not leave a
# stale recording indicator (or silently stop reporting future recordings).
exit 1

state_dir=/run/narsil-mode
mode=${1:-}
case "$mode" in headless|desktop) ;; *) echo 'Invalid switch mode' >&2; exit 2 ;; esac
install -d -m 0700 "$state_dir"
exec 9>"$state_dir/switch.lock"
if ! flock -n 9; then
  echo 'Another mode switch is running.' >&2
  exit 1
fi
desktop=$(find_desktop)
target=$desktop
if [[ "$mode" == headless ]]; then
  check_installation
  target="$desktop/specialisation/strata-server"
fi
# Protect the matching parent even if profiles are garbage-collected while
# its child is active. A boot directly into the child is resolved from profiles.
ln -sfn "$desktop" "$gc_root"
desktop_stopped=no

stop_strata() {
  if systemctl cat strata.service >/dev/null 2>&1; then
    systemctl stop strata.service || return
  fi
  stop-manual-strata
}

recover() {
  local result=$?
  trap - ERR
  echo "Mode switch failed (exit $result). See journalctl -u narsil-mode-switch@$mode.service." >&2
  if [[ "$mode" == headless && "$desktop_stopped" == yes ]]; then
    echo 'Attempting to restore the desktop configuration.' >&2
    # Do not restart a compositor until model processes have released the GPU.
    if stop_strata; then
      systemctl stop nginx.service || true
      if "$desktop/bin/switch-to-configuration" test; then
        if systemctl isolate graphical.target; then
          rm -f "$gc_root"
        fi
      fi
    fi
  fi
  exit "$result"
}
set -E
trap recover ERR

printf 'Switching to %s using %s\n' "$mode" "$target"
# Stop both the managed service and any old manually started localhost server
# before either a new model or a compositor can contend for RAM/VRAM/port 8080.
stop_strata
if [[ "$mode" == headless ]]; then
  declare -a graphical_sessions=()
  declare -A graphical_users=()
  session_list=$(loginctl list-sessions --no-legend --no-pager)
  mapfile -t sessions < <(awk '{print $1}' <<< "$session_list")
  for session in "${sessions[@]}"; do
    type=$(loginctl show-session "$session" --property=Type --value 2>/dev/null) || continue
    case "$type" in wayland|x11) ;; *) continue ;; esac
    graphical_sessions+=("$session")
    uid=$(loginctl show-session "$session" --property=User --value)
    user=$(loginctl show-session "$session" --property=Name --value)
    graphical_users["$uid"]=$user
  done
  # Stop the watcher first so logout cannot reactivate the other user's VT.
  desktop_stopped=yes
  systemctl stop vt-switch-on-logout.service greetd-vt2.service greetd.service
  for uid in "${!graphical_users[@]}"; do
    if [[ -S /run/user/$uid/bus ]]; then
      # UWSM/desktop apps can live in the user manager outside the login scope.
      # Stop only its graphical target, NOT the whole user (which would kill SSH).
      runuser -u "${graphical_users[$uid]}" -- env \
        XDG_RUNTIME_DIR="/run/user/$uid" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
        systemctl --user stop graphical-session.target
    fi
  done
  for session in "${graphical_sessions[@]}"; do
    if loginctl show-session "$session" >/dev/null 2>&1; then
      loginctl terminate-session "$session"
    fi
  done
fi
"$target/bin/switch-to-configuration" test
if [[ "$mode" == headless ]]; then
  systemctl isolate multi-user.target
  systemctl start strata.service nginx.service
  echo 'Headless mode active; waiting for the 256K model to load...'
  ready=no
  for (( attempt=0; attempt<150; attempt++ )); do
    if response=$(curl --fail --silent --max-time 2 http://127.0.0.1:8080/health) && \
      jq -e '.loaded == true and .max_context == 262144' <<< "$response" >/dev/null; then
      ready=yes
      break
    fi
    sleep 2
  done
  if [[ "$ready" != yes ]]; then
    echo 'Strata did not become ready within five minutes.' >&2
    false
  fi
  echo 'Strata ready: 256K context. LAN/Tailscale access is through Blade.'
else
  systemctl isolate graphical.target
  # The restored parent is now rooted by /run/current-system.
  rm -f "$gc_root"
  echo 'Desktop restored; its normal greeter/autologin is starting.'
fi

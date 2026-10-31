mode=${1:-status}
case "$mode" in
  status)
    printf 'Narsil mode: %s\n' "$(current_mode)"
    printf 'Running generation: %s\n' "$(readlink -f "$current_system")"
    systemctl --no-pager --plain list-units --all \
      'narsil-mode-switch@*.service' strata.service greetd.service greetd-vt2.service
    exit 0
    ;;
  headless|desktop) ;;
  *) echo 'Usage: narsil-mode {status|headless|desktop} [--yes]' >&2; exit 2 ;;
esac
if (( $# > 2 )) || [[ ${2:-} != '' && ${2:-} != --yes ]]; then
  echo 'Only --yes is accepted after the mode.' >&2
  exit 2
fi
if (( EUID != 0 )); then
  exec /run/wrappers/bin/sudo -- "$0" "$@"
fi
for other in headless desktop; do
  state=$(systemctl show --property=ActiveState --value "narsil-mode-switch@$other.service")
  case "$state" in
    active|activating|deactivating)
      echo 'A mode switch is already running. Check: journalctl -u "narsil-mode-switch@*" -f' >&2
      exit 1
      ;;
  esac
done
if [[ "$(current_mode)" == "$mode" ]]; then
  printf 'Already in %s mode. No change made.\n' "$mode"
  exit 0
fi
# Fail before logging anyone out if the matching generation/files are absent.
find_desktop >/dev/null
if [[ "$mode" == headless ]]; then
  check_installation
  echo 'WARNING: all graphical sessions will be logged out, including james and work.'
  echo 'Save your work. Strata will then start in 256K headless server mode.'
else
  echo 'Strata will stop and release the GPU. The desktop/greeter will start a fresh session.'
fi
echo 'SSH sessions are not deliberately terminated. This does not change the next-boot selection.'
if [[ ${2:-} != --yes ]]; then
  if [[ ! -t 0 ]]; then
    echo 'Interactive confirmation required; use --yes only for intentional automation.' >&2
    exit 1
  fi
  read -r -p 'Continue? [y/N] ' answer
  case "$answer" in y|Y|yes|YES) ;; *) echo 'Cancelled.'; exit 0 ;; esac
fi
printf 'Queuing %s mode. Follow progress with:\n  journalctl -u narsil-mode-switch@%s.service -f\n' "$mode" "$mode"
# The system manager owns this job, not the terminal/user session it will end.
systemctl reset-failed "narsil-mode-switch@$mode.service" 2>/dev/null || true
systemctl start --no-block "narsil-mode-switch@$mode.service"

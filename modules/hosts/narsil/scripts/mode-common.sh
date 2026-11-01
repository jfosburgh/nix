# Shared by the command and its system-service worker.
gc_root=/nix/var/nix/gcroots/narsil-mode-desktop
profiles_dir=/nix/var/nix/profiles
current_system=/run/current-system
mode_file=/etc/narsil-mode

current_mode() {
  if [[ -r "$mode_file" ]]; then
    tr -d '\n' < "$mode_file"
  else
    printf 'desktop'
  fi
}

find_desktop() {
  local current candidate desktop child
  current=$(readlink -f "$current_system")
  # A child cannot reference its parent in the Nix DAG. Match the running
  # child to the parent's specialisation link instead of blindly choosing
  # the latest profile (which might be a different generation).
  for candidate in "$current" "$gc_root" "$profiles_dir/system" "$profiles_dir"/system-*-link; do
    desktop=$(readlink -f "$candidate") || continue
    [[ -x "$desktop/specialisation/strata-server/bin/switch-to-configuration" ]] || continue
    child=$(readlink -f "$desktop/specialisation/strata-server")
    if [[ "$desktop" == "$current" || "$child" == "$current" ]]; then
      printf '%s\n' "$desktop"
      return 0
    fi
  done
  echo 'Cannot find the matching desktop generation. Activate the updated normal narsil configuration first.' >&2
  return 1
}

check_installation() {
  local file
  for file in \
    /home/james/dev/Strata/.venv/bin/python \
    /home/james/dev/Strata/engine/strata \
    /home/james/dev/Strata-data/packs/coder-iq1_m/tokenizer/vocab.json \
    /home/james/dev/Strata-data/packs/coder-iq1_m/native_experts.txt \
    /home/james/dev/Strata-data/models/coder-IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf \
    /home/james/dev/Strata-data/models/coder-IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00002-of-00002.gguf \
    /home/james/dev/Strata-data/mtp/rt/experts.bin; do
    if [[ ! -r "$file" ]]; then
      printf 'Missing Strata installation file: %s\n' "$file" >&2
      return 1
    fi
  done
}

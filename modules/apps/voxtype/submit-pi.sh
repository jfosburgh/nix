# Called by Voxtype after the streaming backend and output finish teardown.
# Merely pressing stop is too early to send the Pi prompt.
submit="$XDG_RUNTIME_DIR/voxtype-pi-submit"
count_file="$XDG_RUNTIME_DIR/voxtype-pi-chars"
failed="$XDG_RUNTIME_DIR/voxtype-pi-failed"
trap 'rm -f "$submit" "$count_file" "$failed"' EXIT

[[ -f "$XDG_RUNTIME_DIR/voxtype-pi-target" && -f "$submit" ]] || exit 0
[[ ! -f "$failed" && -f "$count_file" ]] || exit 0
count=$(<"$count_file")
[[ "$count" =~ ^[0-9]+$ && "$count" -gt 0 ]] || exit 0

# In pinned Voxtype 1.0.1 normal completion invokes post_output_command while
# state is still streaming; cancellation changes state to idle BEFORE the hook.
# Never submit cancellation's rewound text, even if stop was pressed just before.
state=$(voxtype status --format json | jq -er '.class')
[[ "$state" == streaming ]] || exit 0
[[ "$(tmux -L pi-panel display-message -p -t agent:0.0 '#{pane_current_command}' 2>/dev/null)" == pi ]] || exit 0

# Consume the request before sending, so repeated hook calls cannot send twice.
rm -f "$submit"
tmux -L pi-panel send-keys -t agent:0.0 Enter

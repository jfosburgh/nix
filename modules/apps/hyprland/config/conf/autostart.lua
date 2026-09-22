local terminal = "ghostty"
local browser = "zen"

hl.on("hyprland.start", function()
	hl.exec_cmd("uwsm app -- " .. terminal, { workspace = "1 silent" })
	hl.exec_cmd("uwsm app -- " .. browser, { workspace = "2 silent" })
	hl.exec_cmd("uwsm app -- hyprpolkitagent")
	hl.exec_cmd([[uwsm app -- sh -c '[ "$(hostname)" = glamdring ] && exec steam -tenfoot']])

	-- auto_sync only fires on a live theme change, not on startup; retry
	-- since noctalia's IPC handler isn't up instantly.
	hl.exec_cmd([[uwsm app -- sh -c 'for i in $(seq 1 15); do noctalia msg greeter-sync >/dev/null 2>&1 && break; sleep 1; done']])
end)

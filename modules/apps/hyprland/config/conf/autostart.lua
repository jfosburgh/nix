local terminal = "ghostty"
local browser = "zen"

hl.on("hyprland.start", function()
	-- Launched right as hyprland.start fires, the display pipeline can
	-- still be settling (DRM page-flip/CRTC errors observed in the
	-- compositor log at this point right after boot); ghostty has been
	-- seen to exit immediately if its window fails to map that early.
	-- Retry like the greeter-sync loop below.
	hl.exec_cmd(
		[[uwsm app -- sh -c 'for i in $(seq 1 5); do ]] .. terminal .. [[ && break; sleep 1; done']],
		{workspace = "1 silent"}
	)
	hl.exec_cmd("uwsm app -- " .. browser, { workspace = "2 silent" })
	hl.exec_cmd("uwsm app -- hyprpolkitagent")
	hl.exec_cmd([[uwsm app -- sh -c '[ "$(hostname)" = glamdring ] && exec steam -tenfoot']])

	-- auto_sync only fires on a live theme change, not on startup; retry
	-- since noctalia's IPC handler isn't up instantly.
	hl.exec_cmd([[uwsm app -- sh -c 'for i in $(seq 1 15); do noctalia msg greeter-sync >/dev/null 2>&1 && break; sleep 1; done']])
end)

local terminal = "ghostty"
local browser = "zen"

hl.on("hyprland.start", function()
	hl.exec_cmd("uwsm app -- " .. terminal, { workspace = "1 silent" })
	hl.exec_cmd("uwsm app -- " .. browser, { workspace = "2 silent" })
	hl.exec_cmd("uwsm app -- waybar")
	hl.exec_cmd("uwsm app -- hyprpaper")
	-- Runs its own day/night schedule from hyprsunset.conf's `profile`
	-- blocks. ../quickshell/nightlight/shell.qml's toggle also lazy-starts
	-- this if it's somehow not running, but starting it here means the
	-- schedule is actually in effect from login rather than only once
	-- someone opens that panel.
	hl.exec_cmd("uwsm app -- hyprsunset")
	hl.exec_cmd("uwsm app -- hyprpolkitagent")
	hl.exec_cmd("uwsm app -- mako")
	hl.exec_cmd("uwsm app -- swayosd-server")
	hl.exec_cmd("uwsm app -- wl-paste --watch cliphist store")
	hl.exec_cmd([[uwsm app -- sh -c '[ "$(hostname)" = glamdring ] && exec steam -tenfoot']])
end)

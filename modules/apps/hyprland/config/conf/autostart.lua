local terminal = "ghostty"
local browser = "zen"

hl.on("hyprland.start", function()
	hl.exec_cmd("uwsm app -- " .. terminal, { workspace = "1 silent" })
	hl.exec_cmd("uwsm app -- " .. browser, { workspace = "2 silent" })
	hl.exec_cmd("uwsm app -- hyprpolkitagent")
	hl.exec_cmd([[uwsm app -- sh -c '[ "$(hostname)" = glamdring ] && exec steam -tenfoot']])
end)

local mainMod = "SUPER"
local terminal = "ghostty"
local browser = "zen-browser"
local fileManager = "nautilus"
-- Plain `pkill quickshell` (not `-f`) matches by process name, not full
-- command line -- `-f` would match the pattern text against this very
-- shell's own argv (which contains the pattern as a literal string) and kill
-- itself before ever launching anything.
local menu = "pkill quickshell || qs -c app-launcher"
local webApp = "helium-browser"
local floatTerm = "launch-floating-terminal"

local function key(mods)
	return mainMod .. " + " .. mods
end

hl.bind(key("RETURN"), hl.dsp.exec_cmd(terminal))
hl.bind(key("SPACE"), hl.dsp.exec_cmd(menu))
hl.bind(key("C"), hl.dsp.window.close())
hl.bind(key("M"), hl.dsp.exec_cmd("uwsm stop"))
hl.bind(key("E"), hl.dsp.exec_cmd(fileManager))
hl.bind(key("V"), hl.dsp.window.float({ action = "toggle" }))
hl.bind(key("F"), hl.dsp.window.fullscreen())
hl.bind(key("B"), hl.dsp.exec_cmd("pkill waybar || waybar"))
hl.bind(key("S"), hl.dsp.exec_cmd("hyprshot -m region"))
-- hl.bind(key("SHIFT + S"), hl.dsp.exec_cmd("hyprshot -m window"))
hl.bind(key("SHIFT + L"), hl.dsp.exec_cmd("pidof hyprlock || hyprlock"))
hl.bind(key("P"), hl.dsp.exec_cmd(floatTerm .. " pacman-install"))
hl.bind(key("SHIFT + P"), hl.dsp.exec_cmd(floatTerm .. " aur-install"))
hl.bind(key("R"), hl.dsp.exec_cmd(floatTerm .. " pacman-remove"))
hl.bind(key("SHIFT + S"), hl.dsp.exec_cmd("slack"))
hl.bind(key("SHIFT + B"), hl.dsp.exec_cmd("pkill kanata || kanata"))
hl.bind(key("I"), hl.dsp.exec_cmd("pkill hypridle || hypridle"))
hl.bind(key("T"), hl.dsp.exec_cmd("launch-floating-terminal-keepalive"))
hl.bind(key("X"), hl.dsp.workspace.move({ monitor = "+1" }))
hl.bind(key("SHIFT + V"), hl.dsp.exec_cmd("qs -c clipboard-picker"))

-- Web-app shortcuts
local webApps = {
	{ "C", "https://chatgpt.com" },
	{ "G", "https://gemini.google.com/app" },
	{ "M", "https://messages.google.com/web/conversations" },
	{ "D", "https://discord.com/channels/@me" },
	{ "R", "https://www.reddit.com/" },
}
for _, app in ipairs(webApps) do
	hl.bind(key("SHIFT + " .. app[1]), hl.dsp.exec_cmd(webApp .. " --app=" .. app[2]))
end

-- Move focus with mainMod + hjkl
local directions = { h = "left", l = "right", k = "up", j = "down" }
for k, direction in pairs(directions) do
	hl.bind(key(k), hl.dsp.focus({ direction = direction }))
end

-- Switch workspaces with mainMod + [0-9]; move active window with mainMod + SHIFT + [0-9]
-- (key "0" maps to workspace 10)
for i = 1, 10 do
	local keyLabel = tostring(i % 10)
	hl.bind(key(keyLabel), hl.dsp.focus({ workspace = tostring(i) }))
	hl.bind(key("SHIFT + " .. keyLabel), hl.dsp.window.move({ workspace = tostring(i) }))
end

-- Moving and resizing windows with the mouse
hl.bind(key("mouse:272"), hl.dsp.window.drag(), { mouse = true })
hl.bind(key("SHIFT + mouse:272"), hl.dsp.window.resize(), { mouse = true })

-- Laptop multimedia keys for volume and LCD brightness
local mediaKeys = {
	{ "XF86AudioRaiseVolume", "swayosd-client --output-volume=raise" },
	{ "XF86AudioLowerVolume", "swayosd-client --output-volume=lower" },
	{ "XF86AudioMute", "swayosd-client --output-volume=mute-toggle" },
	{ "XF86AudioMicMute", "swayosd-client --input-volume=mute-toggle" },
	{ "XF86MonBrightnessUp", "swayosd-client --brightness=raise" },
	{ "XF86MonBrightnessDown", "swayosd-client --brightness=lower" },
}
for _, mk in ipairs(mediaKeys) do
	hl.bind(mk[1], hl.dsp.exec_cmd(mk[2]), { locked = true, repeating = true })
end

-- Requires playerctl
local playerctlKeys = {
	{ "XF86AudioNext", "next" },
	{ "XF86AudioPause", "play-pause" },
	{ "XF86AudioPlay", "play-pause" },
	{ "XF86AudioPrev", "previous" },
}
for _, pk in ipairs(playerctlKeys) do
	hl.bind(pk[1], hl.dsp.exec_cmd("playerctl " .. pk[2]), { locked = true })
end

-- hl.bind("switch:Lid Switch", hl.dsp.exec_cmd("systemctl suspend-then-hibernate"), { locked = true })

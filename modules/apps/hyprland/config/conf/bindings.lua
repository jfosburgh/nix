local mainMod = "SUPER"
local terminal = "ghostty"
local browser = "zen-browser"
local fileManager = "nautilus"
local noctaliaIpc = "noctalia msg "
local menu = noctaliaIpc .. "panel-toggle launcher"
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
hl.bind(key("B"), hl.dsp.exec_cmd(noctaliaIpc .. "panel-toggle control-center"))
hl.bind(key("S"), hl.dsp.exec_cmd(noctaliaIpc .. "screenshot-region"))
hl.bind(key("SHIFT + L"), hl.dsp.exec_cmd(noctaliaIpc .. "session lock"))
-- Fuzzy-search nixpkgs and drop into a nix shell with the selected package.
hl.bind(key("P"), hl.dsp.exec_cmd(floatTerm .. " nix-search-shell"))
hl.bind(key("SHIFT + S"), hl.dsp.exec_cmd("slack"))
hl.bind(key("SHIFT + B"), hl.dsp.exec_cmd("pkill kanata || kanata"))
hl.bind(key("I"), hl.dsp.exec_cmd(noctaliaIpc .. "caffeine-toggle"))
hl.bind(key("T"), hl.dsp.exec_cmd("launch-floating-terminal-keepalive"))
hl.bind(key("X"), hl.dsp.workspace.move({ monitor = "+1" }))
hl.bind(key("SHIFT + V"), hl.dsp.exec_cmd(noctaliaIpc .. "panel-toggle clipboard"))
hl.bind(key("SHIFT + U"), hl.dsp.exec_cmd("/run/current-system/sw/bin/switch-session"))

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

local mediaKeys = {
	{ "XF86AudioRaiseVolume", "volume-up" },
	{ "XF86AudioLowerVolume", "volume-down" },
	{ "XF86AudioMute", "volume-mute" },
	{ "XF86AudioMicMute", "mic-mute" },
	{ "XF86MonBrightnessUp", "brightness-up" },
	{ "XF86MonBrightnessDown", "brightness-down" },
}
for _, mk in ipairs(mediaKeys) do
	hl.bind(mk[1], hl.dsp.exec_cmd(noctaliaIpc .. mk[2]), { locked = true, repeating = true })
end

local mediaPlayerKeys = {
	{ "XF86AudioNext", "next" },
	{ "XF86AudioPause", "toggle" },
	{ "XF86AudioPlay", "toggle" },
	{ "XF86AudioPrev", "previous" },
}
for _, pk in ipairs(mediaPlayerKeys) do
	hl.bind(pk[1], hl.dsp.exec_cmd(noctaliaIpc .. "media " .. pk[2]), { locked = true })
end

-- hl.bind("switch:Lid Switch", hl.dsp.exec_cmd("systemctl suspend-then-hibernate"), { locked = true })

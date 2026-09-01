local mainMod = "SUPER"
local terminal = "ghostty"
local browser = "zen-browser"
local fileManager = "nautilus"
local menu = "~/.config/rofi/launchers/type-1/launcher.sh &"
local webApp = "helium-browser"
local floatTerm = "launch-floating-terminal"

hl.bind(mainMod .. " + RETURN", hl.dsp.exec_cmd(terminal))
hl.bind(mainMod .. " + SPACE", hl.dsp.exec_cmd(menu))
hl.bind(mainMod .. " + C", hl.dsp.window.close())
hl.bind(mainMod .. " + M", hl.dsp.exec_cmd("uwsm stop"))
hl.bind(mainMod .. " + E", hl.dsp.exec_cmd(fileManager))
hl.bind(mainMod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mainMod .. " + F", hl.dsp.window.fullscreen())
hl.bind(mainMod .. " + B", hl.dsp.exec_cmd("pkill waybar || waybar"))
hl.bind(mainMod .. " + S", hl.dsp.exec_cmd("hyprshot -m region"))
-- hl.bind(mainMod .. " + SHIFT + S", hl.dsp.exec_cmd("hyprshot -m window"))
hl.bind(mainMod .. " + SHIFT + L", hl.dsp.exec_cmd("pidof hyprlock || hyprlock"))
hl.bind(mainMod .. " + P", hl.dsp.exec_cmd(floatTerm .. " pacman-install"))
hl.bind(mainMod .. " + SHIFT + P", hl.dsp.exec_cmd(floatTerm .. " aur-install"))
hl.bind(mainMod .. " + R", hl.dsp.exec_cmd(floatTerm .. " pacman-remove"))
hl.bind(mainMod .. " + SHIFT + C", hl.dsp.exec_cmd(webApp .. " --app=https://chatgpt.com"))
hl.bind(mainMod .. " + SHIFT + G", hl.dsp.exec_cmd(webApp .. " --app=https://gemini.google.com/app"))
hl.bind(mainMod .. " + SHIFT + M", hl.dsp.exec_cmd(webApp .. " --app=https://messages.google.com/web/conversations"))
hl.bind(mainMod .. " + SHIFT + D", hl.dsp.exec_cmd(webApp .. " --app=https://discord.com/channels/@me"))
hl.bind(mainMod .. " + SHIFT + R", hl.dsp.exec_cmd(webApp .. " --app=https://www.reddit.com/"))
hl.bind(mainMod .. " + SHIFT + S", hl.dsp.exec_cmd("slack"))
hl.bind(mainMod .. " + SHIFT + B", hl.dsp.exec_cmd("pkill kanata || kanata"))
hl.bind(mainMod .. " + I", hl.dsp.exec_cmd("pkill hypridle || hypridle"))
hl.bind(mainMod .. " + T", hl.dsp.exec_cmd("launch-floating-terminal-keepalive"))

-- Move focus with mainMod + arrow keys
hl.bind(mainMod .. " + h", hl.dsp.focus({ direction = "left" }))
hl.bind(mainMod .. " + l", hl.dsp.focus({ direction = "right" }))
hl.bind(mainMod .. " + k", hl.dsp.focus({ direction = "up" }))
hl.bind(mainMod .. " + j", hl.dsp.focus({ direction = "down" }))

-- Switch workspaces with mainMod + [0-9]
hl.bind(mainMod .. " + 1", hl.dsp.focus({ workspace = "1" }))
hl.bind(mainMod .. " + 2", hl.dsp.focus({ workspace = "2" }))
hl.bind(mainMod .. " + 3", hl.dsp.focus({ workspace = "3" }))
hl.bind(mainMod .. " + 4", hl.dsp.focus({ workspace = "4" }))
hl.bind(mainMod .. " + 5", hl.dsp.focus({ workspace = "5" }))
hl.bind(mainMod .. " + 6", hl.dsp.focus({ workspace = "6" }))
hl.bind(mainMod .. " + 7", hl.dsp.focus({ workspace = "7" }))
hl.bind(mainMod .. " + 8", hl.dsp.focus({ workspace = "8" }))
hl.bind(mainMod .. " + 9", hl.dsp.focus({ workspace = "9" }))
hl.bind(mainMod .. " + 0", hl.dsp.focus({ workspace = "10" }))

-- Move active window to a workspace with mainMod + SHIFT + [0-9]
hl.bind(mainMod .. " + SHIFT + 1", hl.dsp.window.move({ workspace = "1" }))
hl.bind(mainMod .. " + SHIFT + 2", hl.dsp.window.move({ workspace = "2" }))
hl.bind(mainMod .. " + SHIFT + 3", hl.dsp.window.move({ workspace = "3" }))
hl.bind(mainMod .. " + SHIFT + 4", hl.dsp.window.move({ workspace = "4" }))
hl.bind(mainMod .. " + SHIFT + 5", hl.dsp.window.move({ workspace = "5" }))
hl.bind(mainMod .. " + SHIFT + 6", hl.dsp.window.move({ workspace = "6" }))
hl.bind(mainMod .. " + SHIFT + 7", hl.dsp.window.move({ workspace = "7" }))
hl.bind(mainMod .. " + SHIFT + 8", hl.dsp.window.move({ workspace = "8" }))
hl.bind(mainMod .. " + SHIFT + 9", hl.dsp.window.move({ workspace = "9" }))
hl.bind(mainMod .. " + SHIFT + 0", hl.dsp.window.move({ workspace = "10" }))

hl.bind(mainMod .. " + X", hl.dsp.workspace.move({ monitor = "+1" }))

hl.bind(mainMod .. " + SHIFT + V", hl.dsp.exec_cmd("cliphist list | rofi -dmenu | cliphist decode | wl-copy"))

-- Moving and resizing windows with the mouse
hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind(mainMod .. " + SHIFT + mouse:272", hl.dsp.window.resize(), { mouse = true })

-- Laptop multimedia keys for volume and LCD brightness
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("swayosd-client --output-volume=raise"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("swayosd-client --output-volume=lower"), { locked = true, repeating = true })
hl.bind("XF86AudioMute", hl.dsp.exec_cmd("swayosd-client --output-volume=mute-toggle"), { locked = true, repeating = true })
hl.bind("XF86AudioMicMute", hl.dsp.exec_cmd("swayosd-client --input-volume=mute-toggle"), { locked = true, repeating = true })
hl.bind("XF86MonBrightnessUp", hl.dsp.exec_cmd("swayosd-client --brightness=raise"), { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("swayosd-client --brightness=lower"), { locked = true, repeating = true })

-- Requires playerctl
hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"), { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"), { locked = true })

-- hl.bind("switch:Lid Switch", hl.dsp.exec_cmd("systemctl suspend-then-hibernate"), { locked = true })

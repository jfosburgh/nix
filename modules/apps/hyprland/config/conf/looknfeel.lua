-- Catppuccin Macchiato, generated from modules/apps/hyprland/default.nix.
local palette = dofile(os.getenv("HOME") .. "/.config/theme/macchiato.lua")

-- https://wiki.hyprland.org/Configuring/Variables/#general
hl.config({
	general = {
		gaps_in = 2,
		gaps_out = 4,

		border_size = 2,

		col = {
			active_border = { colors = { palette.mauve, palette.flamingo }, angle = 90 },
			inactive_border = palette.subtext0,
		},

		allow_tearing = false,
	},
})

hl.config({
	misc = {
		disable_splash_rendering = true,
	},
})

-- https://wiki.hyprland.org/Configuring/Variables/#decoration
hl.config({
	decoration = {
		rounding = 6,

		active_opacity = 1.0,
		inactive_opacity = 1.0,

		dim_inactive = true,
		dim_strength = 0.25,

		shadow = {
			enabled = false,
			range = 4,
			render_power = 3,
			color = "rgba(1a1a1aee)",
		},

		-- https://wiki.hyprland.org/Configuring/Variables/#blur
		blur = {
			enabled = true,
			size = 9,
			passes = 2,

			vibrancy = 0.1696,
		},
	},
})

-- https://wiki.hyprland.org/Configuring/Variables/#animations
hl.config({
	animations = {
		enabled = true,
	},
})

-- Default animations, see https://wiki.hyprland.org/Configuring/Animations/ for more

hl.curve("myBezier", { type = "bezier", points = { { 0.05, 0.9 }, { 0.1, 1.05 } } })

local animations = {
	{ leaf = "windows", enabled = true, speed = 3, bezier = "myBezier" },
	{ leaf = "windowsOut", enabled = false, speed = 3, bezier = "default", style = "popin 80%" },
	{ leaf = "border", enabled = false, speed = 3, bezier = "default" },
	{ leaf = "borderangle", enabled = false, speed = 3, bezier = "default" },
	{ leaf = "fade", enabled = true, speed = 3, bezier = "default" },
	{ leaf = "workspaces", enabled = false, speed = 1, bezier = "default" },
}
for _, anim in ipairs(animations) do
	hl.animation(anim)
end

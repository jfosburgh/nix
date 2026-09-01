hl.env("GDK_SCALE", "1")

local monitors = {
	{ output = "eDP-1", mode = "preferred", position = "-705x0", scale = 1.6 },
	{ output = "HDMI-A-1", mode = "3840x2160@60", position = "0x0", scale = 1.5, vrr = 1 },
	{ output = "", mode = "3840x2160@144", position = "-1200x-1350", scale = 1.3333 },
}
for _, m in ipairs(monitors) do
	hl.monitor(m)
end

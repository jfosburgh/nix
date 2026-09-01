-- Extra env variables
local envVars = {
	{ "XCURSOR_SIZE", "24" },
	{ "HYPRCURSOR_SIZE", "24" },
	{ "PATH", (os.getenv("PATH") or "") .. ":/home/james/.local/bin" },
	{ "QT_QPA_PLATFORMTHEME", "qt6ct" },
	{ "NIXOS_OZONE_WL", "1" },
	{ "MOZ_ENABLE_WAYLAND", "1" },
	{ "TERMINAL", "ghostty" },
	-- NVIDIA
	{ "ELECTRON_OZONE_PLATFORM_HINT", "wayland" },
}
for _, v in ipairs(envVars) do
	hl.env(v[1], v[2])
end

-- glamdring's 1080ti (Pascal) predates GSP firmware (Turing+), so it needs the
-- "egl" backend, not "direct" -- that mismatch is likely why these were
-- previously commented out. Config is shared across hosts, so gate on
-- hostname rather than setting these unconditionally and breaking OpenGL on
-- the AMD-only machines.
local function hostname()
	local file = io.open("/proc/sys/kernel/hostname", "r")
	if not file then
		return ""
	end
	local name = file:read("*l") or ""
	file:close()
	return name
end

if hostname() == "glamdring" then
	hl.env("NVD_BACKEND", "egl")
	hl.env("__GLX_VENDOR_LIBRARY_NAME", "nvidia")
end

hl.config({
	cursor = {
		no_hardware_cursors = true,
	},
})

hl.config({
	misc = {
		vrr = 0,
	},
})

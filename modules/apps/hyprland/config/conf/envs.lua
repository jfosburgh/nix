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

-- env = LIBVA_DRIVER_NAME,nvidia
-- env = __GLX_VENDOR_LIBRARY_NAME,nvidia
-- env = NVD_BACKEND,direct
-- env = __GL_VRR_ALLOWED,0

-- -- One of the following caused black screen
-- env = WLR_DRM_NO_ATOMIC,1
-- env = __GL_GSYNC_ALLOWED,0
-- env = AQ_NO_MODIFIERS,1

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

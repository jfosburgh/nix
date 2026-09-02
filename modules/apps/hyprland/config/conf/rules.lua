local floatClasses = {
	"com.boondax.dial",
	"com.jfosburgh.odincraft",
	"org.netrs.ui",
}
for _, class in ipairs(floatClasses) do
	hl.window_rule({ name = "float-" .. class, match = { class = class }, float = true })
end

hl.window_rule({ name = "float-floatterm", match = { title = "FloatTerm" }, float = true })
hl.window_rule({ name = "steam-big-picture-fullscreen", match = { class = "steam", title = ".*Big Picture.*" }, fullscreen = true })

hl.window_rule({ name = "float-portal-gtk", match = { class = "xdg-desktop-portal-gtk" }, float = true })

hl.window_rule({ name = "float-quickshell", match = { class = "org.quickshell" }, float = true })
hl.window_rule({ name = "center-quickshell", match = { class = "org.quickshell" }, center = true })

hl.window_rule({ name = "float-satty", match = { class = "com.gabm.satty" }, float = true })
hl.window_rule({ name = "center-satty", match = { class = "com.gabm.satty" }, center = true })

hl.window_rule({ name = "opacity-ghostty", match = { class = "com.mitchellh.ghostty" }, opacity = "0.92 0.85" })

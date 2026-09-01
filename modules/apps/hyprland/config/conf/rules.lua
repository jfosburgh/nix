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

-- The portal only ever shows dialogs (file pickers, screen-share prompts,
-- permission prompts), so every one of its windows should float.
hl.window_rule({ name = "float-portal-gtk", match = { class = "xdg-desktop-portal-gtk" }, float = true })

-- Quickshell app launcher (SUPER+SHIFT+SPACE). class/title are just
-- "org.quickshell"/"quickshell" -- fine while it's the only quickshell config
-- in use, but would need distinguishing (e.g. by title) if a second one
-- (persistent bar, etc.) is added later. No size rule: shell.qml computes its
-- own implicitHeight from the actual row/header sizes, and a fixed size rule
-- here would just override that.
hl.window_rule({ name = "float-quickshell", match = { class = "org.quickshell" }, float = true })
hl.window_rule({ name = "center-quickshell", match = { class = "org.quickshell" }, center = true })

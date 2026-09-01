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

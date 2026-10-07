require("./conf/autostart.lua")
require("./conf/bindings.lua")
require("./conf/envs.lua")
require("./conf/input.lua")
require("./conf/looknfeel.lua")
require("./conf/monitors.lua")
require("./conf/rules.lua")

-- Noctalia renders the ignored noctalia.lua, not this tracked config.
-- On a fresh install the theme may not have been generated yet.
local has_theme, theme = pcall(require, "noctalia")
if has_theme then
    theme.apply_theme()
end

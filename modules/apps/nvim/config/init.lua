require("options")
require("plugins")
require("config")
require("keymaps")
require("autocmds")

local ok, matugen = pcall(require, 'matugen')
if ok then matugen.setup() end

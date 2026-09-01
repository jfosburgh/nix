require("nvim-treesitter").install({"lua", "odin", "glsl", "slang", "markdown", "markdown_inline", "rust", "python", "json", "bash", "yaml", })

require("mini.icons").setup()
require("mini.pick").setup()
require("mini.extra").setup()
require("mini.completion").setup({
	lsp_completion = {
		source = "omnifunc",
		auto_setup = true,
	},
})

require("fzf-lua").setup({})

require("oil").setup({
	default_file_explorer = true,
	columns = {
		"icon",
	},
	view_options = {
		show_hidden = true,
	},
	use_default_keymaps = true,
})

require("gitsigns").setup({
	signs = {
		add = { text = "+" },
		change = { text = "~" },
		delete = { text = "_" },
		topdelete = { text = "‾" },
		changedelete = { text = "~" },
	},
})

vim.filetype.add({
	extension = {
		shaderslang = "slang",
	},
})

vim.cmd.colorscheme("catppuccin-macchiato")
vim.cmd.hi("statusline guibg=NONE")

vim.lsp.enable({
	"lua_ls",
	"ols",
	"glslang",
	"slangd",
	"rust_analyzer",
	"pyright",
	"ruff",
})

vim.diagnostic.config({
	severity_sort = true,
	float = { border = "rounded", source = "if_many" },
	underline = { severity = vim.diagnostic.severity.ERROR },
	signs = {
		text = {
			[vim.diagnostic.severity.ERROR] = "󰅚 ",
			[vim.diagnostic.severity.WARN] = "󰀪 ",
			[vim.diagnostic.severity.INFO] = "󰋽 ",
			[vim.diagnostic.severity.HINT] = "󰌶 ",
		},
	},
})
--
-- require("codecompanion").setup({
-- 	ignore_warnings = true,
-- 	strategies = {
-- 		chat = {
-- 			name = "copilot",
-- 			model = "gpt-5",
-- 			slash_commands = {
-- 				provider = "fzf_lua",
-- 			},
-- 			keymaps = {
-- 				completion = {
-- 					modes = { i = "<C-Space>" },
-- 					index = 1,
-- 					callback = "keymaps.completion",
-- 					description = "Completion menu",
-- 				},
-- 			},
-- 		},
-- 	},
-- 	display = {
-- 		action_palette = {
-- 			provider = "fzf_lua",
-- 		},
-- 	},
-- })

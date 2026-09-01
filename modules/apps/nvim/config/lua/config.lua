require("nvim-treesitter").install({"lua", "odin", "glsl", "slang", "markdown", "markdown_inline", "rust", "python", "json", "bash", "yaml", "nix", "hyprlang", })

require("mini.icons").setup()
require("mini.pick").setup()
require("mini.extra").setup()

require("blink.cmp").setup({
	keymap = { preset = "default" },
	completion = { documentation = { auto_show = true } },
	-- Pure-Lua fuzzy matcher: avoids fetching/building a prebuilt rust binary
	-- outside of nix, at the cost of some matching performance.
	fuzzy = { implementation = "lua" },
	signature = { enabled = true },
})

require("conform").setup({
	formatters_by_ft = {
		lua = { "stylua" },
		nix = { "alejandra" },
		json = { "prettier" },
		jsonc = { "prettier" },
		yaml = { "prettier" },
		markdown = { "prettier" },
		sh = { "shfmt" },
		bash = { "shfmt" },
	},
	default_format_opts = {
		-- Filetypes with no formatter above (or provided by a repo's
		-- .nvim.lua) fall back to whatever LSP is attached.
		lsp_format = "fallback",
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
	-- nvim already maps hyprland.conf/hypridle.conf/hyprlock.conf/hyprpaper.conf
	-- and anything under a /hypr/ dir to "hyprlang"; these two only match that
	-- when accessed through the deployed ~/.config/hypr symlink, not when
	-- editing the dotfiles repo directly.
	filename = {
		["hyprsunset.conf"] = "hyprlang",
		["macchiato.conf"] = "hyprlang",
	},
})

vim.cmd.colorscheme("catppuccin-macchiato")
vim.cmd.hi("statusline guibg=NONE")

-- Applies to every LSP config, including ones a repo's .nvim.lua enables later.
vim.lsp.config("*", {
	capabilities = require("blink.cmp").get_lsp_capabilities(),
})

-- Only servers for filetypes edited outside of any devenv repo. Project-specific
-- servers (rust_analyzer, pyright, ols, ...) are enabled per-repo via a
-- .nvim.lua that calls vim.lsp.enable({...}) once devenv has them on PATH.
vim.lsp.enable({
	"lua_ls",
	"nil_ls",
	"jsonls",
	"yamlls",
	"marksman",
	"bashls",
	"hyprls",
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

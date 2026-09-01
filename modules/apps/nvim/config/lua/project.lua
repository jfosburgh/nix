-- Helper for per-repo .nvim.lua files (requires 'exrc', see options.lua).
-- A repo whose devenv provides rust-analyzer + rustfmt would add:
--
--   require("project").setup({
--     lsp = { "rust_analyzer" },
--     formatters = { rust = { "rustfmt" } },
--   })
--
-- Servers/formatters only start if their binary is actually on PATH, so this
-- is safe to enable even if devenv hasn't been activated yet.

local M = {}

function M.setup(opts)
	opts = opts or {}

	if opts.lsp then
		vim.lsp.enable(opts.lsp)
	end

	if opts.formatters then
		local formatters_by_ft = require("conform").formatters_by_ft
		for ft, formatters in pairs(opts.formatters) do
			formatters_by_ft[ft] = formatters
		end
	end
end

return M

vim.api.nvim_create_autocmd('FileType', {
	pattern = { '<filetype>' },
	callback = function()
		vim.treesitter.start()
		vim.bo.indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
	end,
})

vim.api.nvim_create_autocmd("TextYankPost", {
	desc = "Highlight when yanking (copying) text",
	group = vim.api.nvim_create_augroup("highlight-yank", { clear = true }),
	callback = function()
		vim.highlight.on_yank()
	end,
})

-- Completion is handled by blink.cmp's own "lsp" source, so no LspAttach
-- hook is needed to enable native vim.lsp.completion here.

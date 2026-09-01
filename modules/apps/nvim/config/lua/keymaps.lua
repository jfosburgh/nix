vim.keymap.set("n", "<leader>so", ":update<CR> :so<CR>", { remap = true })
vim.keymap.set("n", "<c-c>", ":bd<CR>")
vim.keymap.set("n", "<c-s>", ":update<CR>")

vim.keymap.set("n", "-", "<CMD>Oil<CR>", { desc = "Open parent directory" })

vim.keymap.set("n", "<leader>fd", "<CMD>FzfLua diagnostics_document<CR>")
vim.keymap.set("n", "<leader>,", "<CMD>FzfLua buffers<CR>")
vim.keymap.set("n", "<leader>fg", "<CMD>FzfLua live_grep<CR>")

vim.keymap.set("n", "<leader>ld", vim.diagnostic.open_float, { remap = true })
vim.keymap.set("n", "<leader>lf", vim.lsp.buf.format, { remap = true })
vim.keymap.set("n", "gd", vim.lsp.buf.definition, { remap = true })

vim.keymap.set("i", "<c-space>", function()
	vim.lsp.completion.get()
end)

vim.keymap.set("n", "<C-h>", "<C-w><C-h>", { desc = "Move focus to the left window" })
vim.keymap.set("n", "<C-l>", "<C-w><C-l>", { desc = "Move focus to the right window" })
vim.keymap.set("n", "<C-j>", "<C-w><C-j>", { desc = "Move focus to the lower window" })
vim.keymap.set("n", "<C-k>", "<C-w><C-k>", { desc = "Move focus to the upper window" })

vim.keymap.set("n", "<C-n>", "<CMD>bn<CR>", { remap = true })
vim.keymap.set("n", "<C-p>", "<CMD>bp<CR>", { remap = true })

vim.keymap.set("n", "<leader>lg", "<CMD>LazyGit<CR>")

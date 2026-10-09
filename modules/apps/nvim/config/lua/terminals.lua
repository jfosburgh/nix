local M = {}
local sessions = {}

local function project_dir()
	local name = vim.api.nvim_buf_get_name(0)
	local start = vim.bo.buftype == "" and name ~= "" and name or vim.fn.getcwd()
	return vim.fs.root(start, {
		".git",
		".nvim.lua",
		"devenv.nix",
		"flake.nix",
		"package.json",
		"Cargo.toml",
		"pyproject.toml",
		"go.mod",
	}) or vim.fn.getcwd()
end

local function open(kind, dir)
	dir = dir or project_dir()
	sessions[dir] = sessions[dir] or {}
	local term = sessions[dir][kind]
	if not term then
		if kind == "ai" and vim.fn.executable("pi") ~= 1 then
			vim.notify("pi is not on PATH", vim.log.levels.ERROR)
			return
		end
		term = require("toggleterm.terminal").Terminal:new({
			cmd = kind == "ai" and "pi" or nil,
			dir = dir,
			direction = kind == "ai" and "vertical" or "float",
			hidden = true,
			close_on_exit = true,
			on_open = function(t)
				local opts = { buffer = t.bufnr, silent = true }
				-- Close only the window: the terminal buffer and job stay alive.
				vim.keymap.set({ "n", "t" }, "<C-w>", function()
					t:close()
				end, vim.tbl_extend("force", opts, { desc = "Hide terminal (keep running)" }))
				vim.keymap.set({ "n", "t" }, "<C-t>", function()
					open("shell", dir)
				end, vim.tbl_extend("force", opts, { desc = "Open project floating terminal" }))
				vim.keymap.set("n", "<leader>ai", function()
					open("ai", dir)
				end, vim.tbl_extend("force", opts, { desc = "Open project pi terminal" }))
				-- Execute Ex commands in Neovim, never send their text to the PTY.
				for key, direction in pairs({ h = "Left", j = "Down", k = "Up", l = "Right" }) do
					vim.keymap.set("t", "<C-" .. key .. ">", function()
						vim.cmd("stopinsert")
						vim.cmd("TmuxNavigate" .. direction)
					end, vim.tbl_extend("force", opts, { desc = "Navigate " .. direction:lower() }))
				end
				if kind == "ai" then
					vim.cmd("wincmd L")
					t:resize(math.max(1, math.floor(vim.o.columns / 3)))
				end
				vim.cmd("startinsert")
			end,
			on_exit = function()
				-- An explicitly exited shell/pi should be recreated next time.
				sessions[dir][kind] = nil
			end,
		})
		sessions[dir][kind] = term
	end
	if term:is_open() then
		term:focus()
		vim.cmd("startinsert")
	else
		term:open(kind == "ai" and math.max(1, math.floor(vim.o.columns / 3)) or nil)
	end
	return term
end

function M.setup()
	require("toggleterm").setup({
		start_in_insert = true,
		persist_mode = false,
		persist_size = false,
		autochdir = false,
		float_opts = {
			border = "rounded",
			width = function()
				return math.floor(vim.o.columns * 0.85)
			end,
			height = function()
				return math.floor(vim.o.lines * 0.8)
			end,
		},
	})
end

function M.shell()
	open("shell")
end

function M.ai()
	open("ai")
end

function M.send_selection()
	-- Include complete selected lines so the referenced range matches the code.
	local first, last = vim.fn.line("v"), vim.fn.line(".")
	if first > last then
		first, last = last, first
	end
	local dir = project_dir()
	local path = vim.api.nvim_buf_get_name(0)
	if path == "" then
		path = "[unnamed buffer]"
	elseif path:sub(1, #dir + 1) == dir .. "/" then
		path = path:sub(#dir + 2)
	end
	local lines = vim.api.nvim_buf_get_lines(0, first - 1, last, false)
	local code = table.concat(lines, "\n")
	-- Use a fence longer than any backtick run in the selected source.
	local fence = "```"
	for ticks in code:gmatch("`+") do
		if #ticks >= #fence then
			fence = string.rep("`", #ticks + 1)
		end
	end
	local text = string.format("%s:%d-%d\n%s%s\n%s\n%s\n", path, first, last, fence, vim.bo.filetype, code, fence)
	vim.cmd.normal({ args = { "\27" }, bang = true })
	local term = open("ai", dir)
	if term then
		-- Bracketed paste inserts multiline text into pi's editor, not a submit.
		vim.fn.chansend(term.job_id, "\27[200~" .. text .. "\27[201~")
	end
end

return M

 local M = {}

function M.setup()
  require('base16-colorscheme').setup({
    base00 = '#1f1f28',
    base01 = '#2a2a37',
    base02 = '#333343',
    base03 = '#68697a',
    base04 = '#717c7c',
    base05 = '#c8c093',
    base06 = '#c8c093',
    base07 = '#c8c093',
    base08 = '#c34043',
    base09 = '#7e9cd8',
    base0A = '#c0a36e',
    base0B = '#76946a',
    base0C = '#96b1e9',
    base0D = '#ade996',
    base0E = '#e9cb96',
    base0F = '#f4e1be',
  })

  local hi = function(group, opts)
    vim.api.nvim_set_hl(0, group, opts)
  end

  hi('TelescopeNormal',         { fg = '#c8c093',          bg = '#1f1f28' })
  hi('TelescopeBorder',         { fg = '#68697a',             bg = '#1f1f28' })
  hi('TelescopePromptNormal',   { fg = '#c8c093',          bg = '#1f1f28' })
  hi('TelescopePromptBorder',   { fg = '#68697a',             bg = '#1f1f28' })
  hi('TelescopePromptPrefix',   { fg = '#76946a',             bg = '#1f1f28' })
  hi('TelescopePromptCounter',  { fg = '#717c7c',  bg = '#1f1f28' })
  hi('TelescopePromptTitle',    { fg = '#1f1f28',             bg = '#76946a' })
  hi('TelescopePreviewTitle',   { fg = '#1f1f28',             bg = '#c0a36e' })
  hi('TelescopeResultsTitle',   { fg = '#1f1f28',             bg = '#7e9cd8' })
  hi('TelescopeSelection',      { fg = '#c8c093',          bg = '#333343' })
  hi('TelescopeSelectionCaret', { fg = '#76946a',             bg = '#333343' })
  hi('TelescopeMatching',       { fg = '#76946a',             bold = true })
end

-- Register a signal handler for SIGUSR1 (matugen updates).
-- The handler re-requires this module, which re-runs the code below, so the
-- previous handle is stopped first; otherwise handlers double on every signal.
if _G.__matugen_signal then
  _G.__matugen_signal:stop()
  _G.__matugen_signal:close()
end

local signal = vim.uv.new_signal()
_G.__matugen_signal = signal
signal:start(
  'sigusr1',
  vim.schedule_wrap(function()
    package.loaded['matugen'] = nil
    require('matugen').setup()
  end)
)

return M

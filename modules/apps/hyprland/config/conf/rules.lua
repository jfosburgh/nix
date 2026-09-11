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

hl.window_rule({ name = "float-portal-gtk", match = { class = "xdg-desktop-portal-gtk" }, float = true })

hl.window_rule({ name = "float-quickshell", match = { class = "org.quickshell" }, float = true })

-- app-launcher/clipboard-picker are modal search/select flows, so they stay
-- centered like a spotlight -- Hyprland's own `center` window-rule flag
-- already handles that correctly on any monitor, no math needed.
hl.window_rule({ name = "center-app-launcher", match = { class = "org.quickshell", title = "quickshell-app-launcher" }, center = true })
hl.window_rule({ name = "center-clipboard-picker", match = { class = "org.quickshell", title = "quickshell-clipboard-picker" }, center = true })

-- Quickshell popups that behave like a dropdown/quick-settings panel rather
-- than a modal: pinned to a screen corner *before they're ever shown* (no
-- center-then-jump-to-corner flash), cursor warped into them the moment they
-- open, and closed the instant focus moves elsewhere. Each such popup sets a
-- distinct `title: "quickshell-<name>"` in its shell.qml so it can be
-- addressed here; add new ones to popupPanels below.
--
-- Positioning genuinely needs to happen before the window is shown, which
-- rules out the dynamic approach tried first here: win.monitor is already
-- resolved at the window.open_early event (which fires before the window's
-- first visible frame), so dispatching a window.move there looked like the
-- way to reposition with zero flash -- but doing so crashed Hyprland
-- outright, since the window's surface isn't actually ready for it that
-- early. A *static* window_rule `move`, by contrast, is applied before the
-- window is ever shown with zero jump and zero crash risk -- the same
-- well-tested path center=true already uses above for app-launcher/
-- clipboard-picker. Its downside is it can't do self-size-relative
-- arithmetic (a formula like "100%-w-12" parses as invalid and Hyprland
-- silently falls back to default placement instead of erroring), so the
-- offset is computed here by hand instead, from the monitor active when
-- this config loads (both current hosts are single-monitor, so "the
-- monitor" is unambiguous at load time; revisit if that ever changes) and
-- each popup's known width (window.open would know the real width, but a
-- static rule -- applied before any window exists -- can't, so this has to
-- be kept in sync by hand with each shell.qml's implicitWidth).
--
-- Close-on-defocus relies on this system's default input:follow_mouse=1
-- (focus-follows-mouse, verified live via `hyprctl getoption`): moving the
-- pointer off the panel already changes the focused window, so watching
-- window.active for focus leaving a popupPanels title behaves like "closes
-- when the pointer leaves" with no polling involved.
local popupPanels = {
	["quickshell-audio"] = "top-right",
	["quickshell-wifi"] = "top-right",
	["quickshell-bluetooth"] = "top-right",
	["quickshell-power"] = "top-right",
	["quickshell-session"] = "top-right",
}

local popupPanelWidth = {
	["quickshell-audio"] = 420,
	["quickshell-wifi"] = 420,
	["quickshell-bluetooth"] = 420,
	["quickshell-power"] = 420,
	["quickshell-session"] = 420,
}

-- general.gaps_out (and any CSS-gap-shaped config value) reads back as a
-- {top, right, bottom, left} table even when set as a single uniform number
-- in conf/looknfeel.lua -- Hyprland normalizes it internally. Reading it as
-- a bare number (`hl.get_config(...) or 4`) doesn't error since the table is
-- truthy and the fallback never fires -- it just silently produces a table
-- where a number was expected, and arithmetic on it errors when actually used.
local function gapSide(gap, side)
	if type(gap) == "table" then
		return gap[side] or 0
	end
	return gap or 0
end

-- Registers the static window_rule that places `title` before it's ever
-- shown. corner: "top-left" | "top-center" | "top-right". Rule `move`
-- values are monitor-relative offsets (confirmed empirically: move="50 50"
-- landed at monitor.x+50, monitor.y+50), so this computes an offset, not an
-- absolute position.
local function registerStaticPopupPosition(title, corner, attempt)
	attempt = attempt or 1
	local mon = hl.get_active_monitor()
	local width = popupPanelWidth[title]
	local reservedTop = mon and type(mon.reserved) == "table" and mon.reserved.top or 0

	-- Two separate races can leave this under-informed on the first pass:
	-- hl.get_active_monitor() can still read nil here even though
	-- monitors.lua (loaded right before this file) just declared the
	-- monitor -- confirmed live on sting via `hyprctl eval`: the exact same
	-- math run interactively after load resolves correctly, but this
	-- function reliably sees a nil monitor both on Hyprland's own startup
	-- load and on an explicit `hyprctl reload`, i.e. a monitor declared
	-- earlier in the same config pass isn't necessarily live yet by the
	-- time this later line of the same pass runs. And even once mon is
	-- real, waybar reserves its layer-shell space asynchronously
	-- (autostart.lua execs it in this same config pass, well after this
	-- file runs), so reservedTop can still read 0 long after mon itself is
	-- populated -- confirmed live on sting: the popup landed at y=6
	-- (gaps_out+border only) instead of below the bar, because this ran
	-- before waybar's surface had reserved anything. Retry on both
	-- conditions together (rather than giving up for the rest of the
	-- session, which left the popup either permanently centered or
	-- permanently glued to the top of the screen) rides out both races; a
	-- monitor with no bar at all would spin the full budget below and then
	-- fall through using reservedTop=0, which is the correct answer for
	-- that case anyway.
	local needsRetry = not (mon and width) or reservedTop == 0
	if needsRetry and attempt <= 50 then
		hl.timer(function()
			registerStaticPopupPosition(title, corner, attempt + 1)
		end, { timeout = 100, type = "oneshot" })
	end
	if not (mon and width) then
		return
	end

	local logicalWidth = mon.width / mon.scale
	local gapsOut = hl.get_config("general.gaps_out")
	local borderSize = hl.get_config("general.border_size") or 2
	local topOffset = math.floor(reservedTop + gapSide(gapsOut, "top") + borderSize)

	local xOffset
	if corner == "top-left" then
		xOffset = math.floor(gapSide(gapsOut, "left") + borderSize)
	elseif corner == "top-center" then
		xOffset = math.floor((logicalWidth - width) / 2)
	elseif corner == "top-right" then
		xOffset = math.floor(logicalWidth - width - gapSide(gapsOut, "right") - borderSize)
	else
		error("registerStaticPopupPosition: unknown corner " .. tostring(corner))
	end

	hl.window_rule({
		name = "position-" .. title,
		match = { class = "org.quickshell", title = title },
		move = xOffset .. " " .. topOffset,
	})
end

for title, corner in pairs(popupPanels) do
	registerStaticPopupPosition(title, corner)
end

-- The window is already correctly placed by the static rule above by the
-- time window.open fires, so this only needs to warp the cursor to its real
-- (now-known) center and arm the close-on-defocus grace period -- no move
-- dispatch here means no risk of the earlier center-then-jump focus-mismatch
-- bug recurring.
local armedAt = {}

hl.on("window.open", function(win)
	if not (win and win.title and popupPanels[win.title]) then
		return
	end

	local at, size = win.at, win.size
	if at and size then
		hl.dispatch(hl.dsp.cursor.move({ x = math.floor(at.x + size.x / 2), y = math.floor(at.y + size.y / 2) }))
	end

	armedAt[win.title] = false
	hl.timer(function()
		armedAt[win.title] = true
	end, { timeout = 250, type = "oneshot" })
end)

local lastActiveTitle = nil
hl.on("window.active", function(win)
	local newTitle = win and win.title or nil

	if lastActiveTitle and lastActiveTitle ~= newTitle and popupPanels[lastActiveTitle] and armedAt[lastActiveTitle] then
		hl.dispatch(hl.dsp.window.close({ window = "title:" .. lastActiveTitle }))
		armedAt[lastActiveTitle] = nil
	end

	lastActiveTitle = newTitle
end)

hl.window_rule({ name = "float-satty", match = { class = "com.gabm.satty" }, float = true })
hl.window_rule({ name = "center-satty", match = { class = "com.gabm.satty" }, center = true })

hl.window_rule({ name = "opacity-ghostty", match = { class = "com.mitchellh.ghostty" }, opacity = "0.92 0.85" })

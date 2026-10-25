-- A scratchpad overlays the current desktop without retiling it. Hiding the
-- workspace keeps the window and Pi alive; tmux also survives a closed window.
-- Clicking the desktop beside this floating-only scratchpad remains possible.
hl.config({ input = { special_fallthrough = true } })
hl.window_rule({
    name = "pi-agent-panel",
    match = { class = "^dev\\.pi\\.DesktopAgent$" },
    workspace = "special:pi-agent silent",
    float = true,
    size = { "monitor_w / 3", "monitor_h - 24" },
    move = { "monitor_w * 2 / 3 - 12", 12 },
    animation = "slide right",
    no_dim = true,
    opacity = "1.0 override",
})

-- Normal workspace animations remain disabled. These leaves affect special
-- workspaces only; opposite directions make both show and hide use the right.
hl.animation({ leaf = "specialWorkspaceIn", enabled = true, speed = 2.5, bezier = "myBezier", style = "slide right 35%" })
hl.animation({ leaf = "specialWorkspaceOut", enabled = true, speed = 2.5, bezier = "myBezier", style = "slide left 35%" })

hl.bind("SUPER + A", hl.dsp.exec_cmd("launch-pi-panel"), {
    description = "Toggle persistent Pi agent panel",
})

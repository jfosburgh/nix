-- Streaming output must not share a held push-to-talk shortcut: synthetic
-- typing can disrupt Hyprland's release tracking. Tap, release, then speak.
hl.bind("CTRL + ALT + SPACE", hl.dsp.exec_cmd("voxtype-dictate cursor"), {
    description = "Toggle local live dictation into the active cursor",
})
hl.bind("CTRL + ALT + SHIFT + SPACE", hl.dsp.exec_cmd("voxtype-dictate pi"), {
    description = "Toggle local live dictation into the persistent Pi agent",
})
hl.bind("CTRL + ALT + Escape", hl.dsp.exec_cmd("voxtype record cancel"), {
    description = "Cancel local dictation (rewind this recording's streamed text)",
})

-- 0.56.2 has no config.unload event. Cancel on reload/shutdown so an old
-- streaming session cannot continue typing after its bindings are replaced.
local function reset()
    hl.exec_cmd("voxtype record cancel")
    -- Remove a marker left by the previous hold-to-talk implementation.
    os.remove(os.getenv("XDG_RUNTIME_DIR") .. "/voxtype-modifiers-held")
end
hl.on("config.reloaded", reset)
hl.on("hyprland.shutdown", reset)

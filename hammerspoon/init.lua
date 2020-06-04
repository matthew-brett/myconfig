-- Init file for Hammerspoon: https://www.hammerspoon.org

function fill_screen(framer)
    -- Make window with current focus fill frame from `framer`.
    local win = hs.window.focusedWindow()
    local f = win:frame()
    local max = framer:frame()

    f.x = max.x
    f.y = max.y
    f.w = max.w
    f.h = max.h
    win:setFrame(f)
end

hs.hotkey.bind({"shift", "cmd", "alt", "ctrl"}, "Up", function()
    -- Expand current window to fill current desktop.
    fill_screen(hs.window.desktop())
end)

hs.hotkey.bind({"shift", "cmd", "alt", "ctrl"}, "P", function()
    -- Push current window to Primary display, expand to fill display.
    fill_screen(hs.screen.primaryScreen())
end)

hs.hotkey.bind({"shift", "cmd", "alt", "ctrl"}, "O", function()
    -- Push current window to second (Other) display, expand to fill display.
    fill_screen(hs.screen.allScreens()[2])
end)

-- Init file for Hammerspoon: https://www.hammerspoon.org

function fill_screen(framer)
    -- Make window with current focus fill frame from `framer`.
    local max = framer:frame()
    fill_from_dims(max.x, max.y, max.w, max.h)
end

function fill_from_dims(x, y, w, h)
    -- Make window with current focus have size x, y, w, h
    local win = hs.window.focusedWindow()
    local f = win:frame()
    f.x = x
    f.y = y
    f.w = w
    f.h = h
    win:setFrame(f)
end

hs.hotkey.bind({"shift", "cmd", "alt", "ctrl"}, "N", function()
    -- Expand current Primary screen, and screen to the East, if present.
    -- (screen elsewhere might be the Cintiq).
    local p_sc = hs.screen.primaryScreen()
    local east_sc = p_sc:toEast()
    if east_sc == nil then
        fill_screen(p_sc)
        return
    end
    local f1 = p_sc:frame()
    local f2 = east_sc:frame()
    fill_from_dims(f1.x, f1.y, f1.w + f2.w, f1.h + f2.h)
end)

hs.hotkey.bind({"shift", "cmd", "alt", "ctrl"}, "P", function()
    -- Push current window to Primary display, expand to fill display.
    fill_screen(hs.screen.primaryScreen())
end)

hs.hotkey.bind({"shift", "cmd", "alt", "ctrl"}, "O", function()
    -- Push current window to second (Other) display, expand to fill display.
    -- Use screen to East of primary display.
    local east_sc = hs.screen.primaryScreen():toEast()
    if east_sc == nil then
        return
    end
    fill_screen(east_sc)
end)

hs.hotkey.bind({"shift", "cmd", "alt", "ctrl"}, "C", function()
    -- Push current window to Cintiq display, if present
    local screens = hs.screen.allScreens()
    local index, screen
    for index, screen in pairs(screens) do
        if screen:name():find('Cintiq', 1, true) then
            fill_screen(screen)
            return
        end
    end
end)

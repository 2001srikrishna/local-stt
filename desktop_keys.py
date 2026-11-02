"""Paste-key selection, separate from desktop APIs for offline regression tests."""
import time

# Linux input-event ABI key codes. No Enter, pointer, or text-typing capability.
EV_KEY=1
CTRL=29
SHIFT=42
V=47
TERMINALS=('kitty','konsole','alacritty','wezterm','foot','gnome-terminal','gnome.terminal','terminator','xterm','urxvt','tilix','ghostty')


def is_terminal(app):
    return any(name in app.lower() for name in TERMINALS)


def paste_keys(ui,terminal):
    modifiers=[CTRL,SHIFT] if terminal else [CTRL]
    try:
        for key in modifiers:ui.write(EV_KEY,key,1)
        ui.write(EV_KEY,V,1);ui.syn();time.sleep(.02)
    finally:
        ui.write(EV_KEY,V,0)
        for key in reversed(modifiers):ui.write(EV_KEY,key,0)
        ui.syn()

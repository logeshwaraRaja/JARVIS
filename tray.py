"""System-tray icon (pystray). Left-click toggles dictation; menu has pause + quit."""
import pystray
from micicon import draw_mic

COLORS = {"loading": "#E0A100", "listening": "#0B6E99", "dictating": "#D32F2F", "paused": "#6B7B86"}


def make_icon(color):
    return draw_mic(64, color, button=False)


class Tray:
    def __init__(self, cmds, ui_q):
        self.cmds, self.ui_q = cmds, ui_q
        self.mode = "loading"
        menu = pystray.Menu(
            pystray.MenuItem("Start / stop dictation", lambda i, it: cmds.put("toggle"), default=True),
            pystray.MenuItem("Pause \"Hey Jarvis\" listening", lambda i, it: cmds.put("pause"),
                             checked=lambda it: self.mode == "paused"),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda i, it: ui_q.put(("quit",))),
        )
        self.icon = pystray.Icon("local_dictation", make_icon(COLORS["loading"]), "JARVIS", menu)

    def run(self):
        self.icon.run_detached()

    def set_mode(self, mode):
        self.mode = mode
        try:
            self.icon.icon = make_icon(COLORS.get(mode, COLORS["listening"]))
            self.icon.title = {"listening": "JARVIS - say \"Hey Jarvis\"", "dictating": "Dictating...",
                               "paused": "JARVIS - paused", "loading": "Loading..."}.get(mode, "JARVIS")
        except Exception:
            pass

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass

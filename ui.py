"""Memo-style dictation card (live waveform + live text) and the floating mic button."""
import colorsys
import ctypes
import os
import queue
import time
import tkinter as tk
from collections import deque

from PIL import ImageTk

import config
from layered import LayeredWindow
from micicon import draw_mic

BG = "#071C2B"
PANEL = "#0C2A3F"
DOT = "#3E6177"
TXT = "#EAF4FA"
DIM = "#6F8FA3"
MODE_COLORS = {"loading": "#E0A100", "listening": "#0B6E99", "dictating": "#D32F2F", "paused": "#6B7B86"}


def _hwnd(win):
    u = ctypes.windll.user32
    return u.GetAncestor(win.winfo_id(), 2) or win.winfo_id()


def no_activate(win):
    """Never steal focus from the app you're dictating into."""
    try:
        win.update_idletasks()
        u = ctypes.windll.user32
        h = _hwnd(win)
        u.SetWindowLongW(h, -20, u.GetWindowLongW(h, -20) | 0x08000000 | 0x00000080)
    except Exception:
        pass


def round_corners(win):
    try:
        v = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(_hwnd(win), 33, ctypes.byref(v), 4)
    except Exception:
        pass


class UI:
    def __init__(self, cmds, ui_q, tray=None):
        self.cmds, self.ui_q, self.tray = cmds, ui_q, tray
        self.root = tk.Tk()
        self.root.withdraw()
        self.SC = max(1.0, self.root.winfo_fpixels("1i") / 96.0)   # display scale (DPI aware)
        self.CW, self.CH = int(580 * self.SC), int(250 * self.SC)
        self.mode = "loading"
        self.hist = deque(maxlen=300)
        self.hide_at = 0
        self.shown_text = None
        self._build_card()
        self._build_button()
        self.root.after(30, self.poll)

    # ---------------------------------------------------------------- card ---
    def _build_card(self):
        c = self.card = tk.Toplevel(self.root)
        c.overrideredirect(True)
        c.attributes("-topmost", True)
        c.attributes("-alpha", 0.97)
        c.configure(bg=BG)
        sw, sh = c.winfo_screenwidth(), c.winfo_screenheight()
        c.geometry(f"{self.CW}x{self.CH}+{(sw - self.CW) // 2}+{sh - self.CH - 80}")

        head = tk.Frame(c, bg=BG)
        head.pack(fill="x", padx=14, pady=(12, 0))
        self.wave = tk.Canvas(head, height=int(64 * self.SC), bg=BG, highlightthickness=0)
        self.wave.pack(side="left", fill="x", expand=True)
        close = tk.Label(head, text="✕", fg=DIM, bg=BG, font=("Segoe UI", 13), cursor="hand2")
        close.pack(side="right", padx=(8, 0))
        close.bind("<Button-1>", lambda e: self.cmds.put("stop"))
        close.bind("<Enter>", lambda e: close.config(fg="white"))
        close.bind("<Leave>", lambda e: close.config(fg=DIM))

        self.status = tk.Label(c, text="", fg=DIM, bg=BG, font=("Segoe UI", 9), anchor="w")
        self.status.pack(fill="x", padx=16, pady=(6, 0))

        self.text = tk.Text(c, height=5, wrap="word", bg=PANEL, fg=TXT, bd=0, highlightthickness=0,
                            font=("Segoe UI", 13), padx=14, pady=10, cursor="arrow", spacing3=3)
        self.text.pack(fill="both", expand=True, padx=14, pady=(6, 14))
        self.text.tag_configure("dim", foreground=DIM)
        self.text.config(state="disabled")
        no_activate(c)
        round_corners(c)
        c.withdraw()

    def _draw_wave(self):
        cv = self.wave
        cv.delete("all")
        w = cv.winfo_width() or 480
        h = int(cv["height"])
        sc = self.SC
        mid, step = h // 2, int(6 * sc)
        n = max(10, w // step)
        items = list(self.hist)[-n:]
        pad = n - len(items)
        for i in range(n):
            x = i * step + int(3 * sc)
            j = i - pad
            amp, hue = (0.0, 0.5) if j < 0 else items[j]
            if amp < 0.04:
                cv.create_line(x, mid, x + max(1, int(sc)), mid, fill=DOT, width=max(2, int(2 * sc)))
            else:
                half = max(3 * sc, amp * (h - 6 * sc) / 2)
                r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 1.0)
                col = "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
                cv.create_line(x, mid - half, x, mid + half, fill=col, width=max(3, int(3 * sc)), capstyle="round")

    def _set_text(self, s, dim=False):
        key = (s, dim)
        if key == self.shown_text:
            return
        self.shown_text = key
        t = self.text
        t.config(state="normal")
        t.delete("1.0", "end")
        t.insert("end", s, ("dim",) if dim else ())
        t.see("end")
        t.config(state="disabled")

    def _show_card(self):
        if config.SHOW_CARD:
            self.card.deiconify()
            self.card.attributes("-topmost", True)

    # -------------------------------------------------------------- button ---
    def _build_button(self):
        self.S = int(64 * self.SC)      # physical pixels, so the icon is rendered 1:1 (no resampling blur)
        self._imgs = {}
        b = self.btn = tk.Toplevel(self.root)
        b.overrideredirect(True)
        b.attributes("-topmost", True)
        keycol = "#010203"
        b.configure(bg=keycol)
        sw, sh = b.winfo_screenwidth(), b.winfo_screenheight()
        b.geometry(f"{self.S}x{self.S}+{sw - self.S - 24}+{sh - self.S - 110}")
        self.bc = tk.Canvas(b, width=self.S, height=self.S, bg=keycol, highlightthickness=0, cursor="hand2")
        self.bc.pack()
        self._img_item = self.bc.create_image(0, 0, anchor="nw")
        self._drag = None
        self.bc.bind("<ButtonPress-1>", self._press)
        self.bc.bind("<B1-Motion>", self._motion)
        self.bc.bind("<ButtonRelease-1>", self._release)
        self.bc.bind("<Button-3>", self._menu)
        self.lw = None
        try:                          # preferred: real per-pixel alpha (smooth edges, no ring)
            self.lw = LayeredWindow(b)
        except Exception as e:
            print("[ui] per-pixel alpha unavailable, using colour-key fallback:", e)
            b.attributes("-transparentcolor", keycol)
        no_activate(b)
        self._draw_button()
        if not config.SHOW_FLOATING_MIC:
            b.withdraw()

    def _draw_button(self, pulse=0.0):
        col = MODE_COLORS.get(self.mode, MODE_COLORS["listening"])
        idx = int(pulse * 10) if self.mode == "dictating" else None
        pv = None if idx is None else idx / 10.0
        key = (self.mode, idx)
        if self.lw:
            try:
                self.lw.show(key, lambda: draw_mic(self.S, col, pv, button=True))
                return
            except Exception as e:
                print("[ui] layered window failed, falling back:", e)
                self.lw = None
                self.btn.attributes("-transparentcolor", "#010203")
        if key not in self._imgs:
            self._imgs[key] = ImageTk.PhotoImage(draw_mic(self.S, col, pv, button=True, key=True))
        self.bc.itemconfig(self._img_item, image=self._imgs[key])

    def _press(self, e):
        self._drag = (e.x_root, e.y_root, self.btn.winfo_x(), self.btn.winfo_y(), False)

    def _motion(self, e):
        if not self._drag:
            return
        x0, y0, wx, wy, moved = self._drag
        dx, dy = e.x_root - x0, e.y_root - y0
        if moved or abs(dx) + abs(dy) > 5:
            self._drag = (x0, y0, wx, wy, True)
            self.btn.geometry(f"+{wx + dx}+{wy + dy}")

    def _release(self, e):
        if self._drag and not self._drag[4]:
            self.cmds.put("toggle")
        self._drag = None

    def _menu(self, e):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Start / stop dictation", command=lambda: self.cmds.put("toggle"))
        m.add_command(label="Pause / resume \"Hey Jarvis\"", command=lambda: self.cmds.put("pause"))
        m.add_separator()
        m.add_command(label="Quit", command=self.quit)
        m.tk_popup(e.x_root, e.y_root)

    # ---------------------------------------------------------------- loop ---
    def quit(self):
        if self.tray:
            self.tray.stop()
        self.root.destroy()
        os._exit(0)

    def poll(self):
        redraw = False
        try:
            while True:
                m = self.ui_q.get_nowait()
                k = m[0]
                if k == "wave":
                    self.hist.append((m[1], m[2]))
                    redraw = True
                elif k == "text":
                    self._set_text(m[1]) if m[1] else self._set_text("Listening... start speaking", dim=True)
                elif k == "mode":
                    self.mode = m[1]
                    self._draw_button()
                    if self.tray:
                        self.tray.set_mode(m[1])
                elif k == "state":
                    self._state(m[1], m[2])
                elif k == "quit":
                    self.quit()
        except queue.Empty:
            pass
        if redraw:
            self._draw_wave()
        if self.mode == "dictating":
            self._draw_button((time.time() % 1.2) / 1.2)
        if self.hide_at and time.time() > self.hide_at:
            self.card.withdraw()
            self.hide_at = 0
        self.root.after(30, self.poll)

    def _state(self, name, text):
        if name == "dictating":
            self.hist.clear()
            self.hide_at = 0
            self.shown_text = None
            self.status.config(text="● Dictating   ·   say “Halt dictation” (or “Halt” + pause) when you're done",
                               fg="#FF8A80")
            self._set_text("Listening... start speaking", dim=True)
            self._draw_wave()
            self._show_card()
        else:
            msgs = {"done": ("✓ Copied to clipboard", "#80E0A0"),
                    "pasted": ("✓ Pasted into the app", "#80E0A0"),
                    "empty": ("Nothing heard", DIM),
                    "error": ("Something went wrong", "#FF8A80")}
            msg, col = msgs.get(name, (name, DIM))
            self.status.config(text=msg, fg=col)
            if text:
                self._set_text(text)
            self.hist.clear()
            self._draw_wave()
            self._show_card()
            self.hide_at = time.time() + (6 if name == "error" else 2.8)

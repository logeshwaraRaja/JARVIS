"""Local voice dictation (Windows).

Say "Hey Jarvis" -> dictation starts; say "Halt dictation" -> text is copied to the clipboard.
Or click the floating mic / tray icon, or press Ctrl+Alt+Space.

Run:  python app.py        (pythonw app.py = no console window; log goes to dictation.log)
"""
import ctypes
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import config

try:  # crisp rendering on scaled (125%/150%) displays: stop Windows bitmap-stretching our windows
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def single_instance(keep=True):
    h = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\LocalVoiceDictation_v2")
    if ctypes.windll.kernel32.GetLastError() == 183:
        return None
    if not keep:
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    return h


# Started from a console (python app.py)? Re-launch detached with pythonw so closing the console
# doesn't kill it. Use `python app.py --foreground` to keep it attached for debugging.
if (sys.platform == "win32" and os.path.basename(sys.executable).lower() == "python.exe"
        and "--foreground" not in sys.argv and "--child" not in sys.argv):
    pyw = sys.executable[:-len("python.exe")] + "pythonw.exe"
    if not single_instance(keep=False):
        print("Already running in the background - look for the mic in the tray / on screen.")
    elif os.path.exists(pyw):
        subprocess.Popen([pyw, os.path.abspath(__file__), "--child"], cwd=str(config.BASE), close_fds=True,
                         creationflags=0x00000008 | 0x00000200 | 0x08000000)  # DETACHED | NEW_GROUP | NO_WINDOW
        print("Dictation started in the background. You can close this window. "
              "Quit from the tray icon or the mic's right-click menu. Log: dictation.log")
        sys.exit(0)

if sys.stdout is None or sys.stderr is None:   # pythonw: no console, log to a file
    _log = open(config.BASE / "dictation.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _log

import numpy as np
import pyperclip
import sounddevice as sd
from pynput import keyboard

import tts
from engines import load_engine
from textutil import SOFT, WAKE, analyse, clean, extract, near_miss
from tray import Tray
from ui import UI


def trace(msg):
    if config.WAKE_TRACE:
        try:
            with open(config.BASE / "wake_trace.log", "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
        except Exception:
            pass


cmds = queue.Queue()     # "toggle" / "start" / "stop" / "pause"
ui_q = queue.Queue()     # messages to the UI thread
tts_cmds = queue.Queue() # "toggle_read" (from the text-to-speech hotkey)


# ------------------------------------------------------------------ hotkey ---
VK = {"ctrl": {0x11, 0xA2, 0xA3}, "alt": {0x12, 0xA4, 0xA5}, "shift": {0x10, 0xA0, 0xA1}}
DOWN, UP = {0x100, 0x104}, {0x101, 0x105}


class Hotkey:
    """Optional keyboard shortcut(s). Swallows each trigger key so it isn't typed into your app.

    `bindings` is a list of (modifiers_tuple, key_str, queue, command_str) -- one low-level
    keyboard hook serves all of them (e.g. the dictation toggle and the text-to-speech toggle)."""

    def __init__(self, bindings):
        self.gk = ctypes.windll.user32.GetAsyncKeyState
        self.bindings = [
            {"mods": mods, "vk": 0x20 if key == "space" else ord(key.upper()),
             "queue": q, "cmd": cmd, "pressed": False}
            for mods, key, q, cmd in bindings
        ]

    def _mods_down(self, mods):
        # Ask Windows for the real key state right now (never goes stale like our own bookkeeping).
        generic = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10}
        return all(self.gk(generic[m]) & 0x8000 for m in mods)

    def filter(self, msg, data):
        for b in self.bindings:
            if data.vkCode != b["vk"]:
                continue
            if msg in DOWN:
                if self._mods_down(b["mods"]):
                    if not b["pressed"]:
                        b["pressed"] = True
                        b["queue"].put(b["cmd"])
                    self.listener.suppress_event()
                else:
                    b["pressed"] = False      # plain key press: let it through untouched
            elif msg in UP and b["pressed"]:
                b["pressed"] = False
                self.listener.suppress_event()
        return True

    def run(self):
        self.listener = keyboard.Listener(win32_event_filter=self.filter)
        self.listener.daemon = True
        self.listener.start()


# ------------------------------------------------------------------ output ---
def modifiers_released(timeout=1.0):
    gk = ctypes.windll.user32.GetAsyncKeyState
    end = time.time() + timeout
    while time.time() < end:
        if not any(gk(v) & 0x8000 for v in (0x11, 0x12, 0x10, 0x20)):
            return
        time.sleep(0.02)


def deliver(text):
    old = None
    if config.AUTO_PASTE and config.RESTORE_CLIPBOARD:
        try:
            old = pyperclip.paste()
        except Exception:
            pass
    pyperclip.copy(text)
    if not config.AUTO_PASTE:
        return "done"
    modifiers_released()
    time.sleep(0.05)
    kb = keyboard.Controller()
    with kb.pressed(keyboard.Key.ctrl):
        kb.press("v"); kb.release("v")
    if old is not None:
        time.sleep(0.25)
        pyperclip.copy(old)
    return "pasted"


# -------------------------------------------------------------- read-aloud ---
def tts_worker():
    """Independent of the dictation state machine: select text anywhere, press the TTS hotkey
    to hear it (never saved), or the save hotkey to hear it AND save it to a file (nothing is
    ever saved unless this second hotkey is used). Press either one again while something's
    running to stop early -- only one read/save runs at a time."""
    proc = None
    while True:
        try:
            cmd = tts_cmds.get(timeout=0.2)
        except queue.Empty:
            cmd = None
        if proc is not None and proc.poll() is not None:
            result = getattr(proc, "result", None)       # _StoppableSpeech ("piper") only
            if isinstance(result, Path):
                ui_q.put(("state", f"Saved: {result.name}", ""))
            proc = None                                   # finished on its own
        if cmd not in ("toggle_read", "toggle_save"):
            continue
        if proc is not None:
            proc.terminate()
            proc = None
            ui_q.put(("state", "Stopped reading", ""))
            continue
        try:
            text = tts.grab_selection()
        except Exception as e:
            print("[tts-error] grab:", e)
            ui_q.put(("state", "error", f"TTS: {e}"[:80]))
            continue
        if not text.strip():
            ui_q.put(("state", "Nothing selected", ""))
            continue
        try:
            if cmd == "toggle_save":
                proc = tts.speak_and_save_async(text, engine=config.TTS_ENGINE)
                print(f"[tts] reading + saving {len(text)} chars")
                ui_q.put(("state", "Reading + saving...", ""))
            else:
                proc = tts.speak_async(text, rate=config.TTS_RATE, voice=config.TTS_VOICE, engine=config.TTS_ENGINE)
                print(f"[tts] reading {len(text)} chars")
                ui_q.put(("state", "Reading selection...", ""))
        except Exception as e:
            print("[tts-error] speak:", e)
            ui_q.put(("state", "error", f"TTS: {e}"[:80]))


# ------------------------------------------------------------------ worker ---
class Dictation:
    def __init__(self, engine):
        self.e = engine
        self.state = "idle"           # idle (waiting for wake word) | dictating
        self.manual = False           # started by click/hotkey (no wake phrase in the text)
        self.paused = False           # wake word listening paused
        self.last_text, self.last_change = "", time.time()
        self.last_sent = None
        self.soft_text, self.soft_since = None, 0.0
        self.onset, self.last_loud = time.time(), 0.0

    def mode(self):
        return "dictating" if self.state == "dictating" else ("paused" if self.paused else "listening")

    def push_mode(self):
        ui_q.put(("mode", self.mode()))

    def begin(self, manual, reset=True):
        if reset:
            self.e.reset()
        self.state, self.manual = "dictating", manual
        self.last_sent = None
        ui_q.put(("state", "dictating", ""))
        self.push_mode()

    def end(self, strip_soft=False):
        final = self.e.finish()
        body, _ = extract(final, self.manual)
        if strip_soft:                              # ended by a bare "Halt": drop it from the text
            body = clean(SOFT.sub("", body))
        self.soft_text = None
        self.e.reset()
        self.state, self.last_text, self.last_change = "idle", "", time.time()
        self.push_mode()
        if not body:
            ui_q.put(("state", "empty", ""))
            return
        try:
            res = deliver(body)
            print(f"[dictation] {body}")
            ui_q.put(("state", res, body))
        except Exception as ex:
            print("[error]", ex)
            ui_q.put(("state", "error", str(ex)[:80]))

    def command(self, cmd):
        if cmd == "toggle":
            self.end() if self.state == "dictating" else self.begin(True)
        elif cmd == "start" and self.state == "idle":
            self.begin(True)
        elif cmd == "stop" and self.state == "dictating":
            self.end()
        elif cmd == "pause":
            self.paused = not self.paused
            self.last_text = ""
            if self.state == "idle":
                self.e.reset()
            self.push_mode()

    def on_chunk(self, chunk):
        e = self.e
        if self.state == "dictating":
            e.feed(chunk)
            amp, hue = analyse(chunk, config.SAMPLE_RATE)
            ui_q.put(("wave", amp, hue))
            if not e.streaming:
                return
            raw = e.partial()
            body, stopped = extract(raw, self.manual)
            if body != self.last_sent:
                self.last_sent = body
                ui_q.put(("text", body))
            if stopped:
                self.end()
                return
            if config.SOFT_STOP_ENABLED:     # bare "Halt" as the last word, followed by a pause
                if SOFT.search(body):
                    now = time.time()
                    if raw != self.soft_text:
                        self.soft_text, self.soft_since = raw, now
                    elif now - self.soft_since >= config.SOFT_STOP_PAUSE:
                        self.end(strip_soft=True)
                else:
                    self.soft_text = None
            return
        # idle: only listen for the wake phrase
        if not (config.WAKE_ENABLED and e.streaming) or self.paused:
            return
        now = time.time()
        if float(np.abs(chunk).max()) > 0.01:          # remember when this burst of speech began
            if now - self.last_loud > 0.8:
                self.onset = now
            self.last_loud = now
        e.feed(chunk)
        text = e.partial()
        if WAKE.search(text):
            trace(f"ACTIVATED {now - self.onset:.2f}s after speech began (heard: "
                  f"'{WAKE.search(text).group(0)}')")
            self.begin(False, reset=False)
            body, _ = extract(text, False)
            self.last_sent = body
            ui_q.put(("text", body))
            return
        now = time.time()
        if text != self.last_text:
            self.last_text, self.last_change = text, now
        if text and (now - self.last_change > 1.5 or len(text) > 300):
            if config.WAKE_DEBUG:          # lets you see what the model heard instead of the wake phrase
                print(f"[heard-idle] {text}")
            nm = near_miss(text)
            if nm:
                trace(f"NEAR MISS - model heard {nm} instead of 'jarvis'")
            e.reset()                      # utterance finished without the wake phrase: forget it
            self.last_text = ""


def pick_device():
    if config.INPUT_DEVICE is None:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and str(config.INPUT_DEVICE).lower() in d["name"].lower():
            return i
    print(f"[audio] device '{config.INPUT_DEVICE}' not found, using default")
    return None


def worker(engine):
    d = Dictation(engine)
    audio_q = queue.Queue()

    def cb(indata, frames, t, status):
        audio_q.put(indata[:, 0].copy())

    def open_stream(device):
        s = sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1, dtype="float32",
                           blocksize=int(config.SAMPLE_RATE * 0.05), device=device, callback=cb)
        s.start()
        return s

    while True:
        wanted = pick_device()
        try:
            try:
                stream = open_stream(wanted)
            except Exception as e:
                if wanted is None:
                    raise
                print(f"[audio] could not open '{config.INPUT_DEVICE}' ({e}); using the system default mic")
                stream = open_stream(None)     # fall back to the Windows default input
            break
        except Exception as e:   # mic may not be ready right after login
            print("[audio] waiting for microphone:", e)
            time.sleep(3)
    d.push_mode()
    try:
        print("Microphone in use:", sd.query_devices(stream.device)["name"])
    except Exception:
        pass
    print("Listening. Say \"Hey Jarvis\" to start, \"Halt dictation\" to finish.")
    quiet_since, warned_silent = None, False
    max_backlog, last_report = 0, time.time()
    while True:
        try:
            while True:
                d.command(cmds.get_nowait())
        except queue.Empty:
            pass
        try:
            chunk = audio_q.get(timeout=0.05)
        except queue.Empty:
            continue
        backlog = audio_q.qsize()                      # chunks waiting = how far behind real time we are
        max_backlog = max(max_backlog, backlog)
        if time.time() - last_report > 60:
            if max_backlog >= 10:                      # 10 chunks = 0.5 s of audio piled up
                trace(f"BACKLOG up to {max_backlog * 0.05:.2f}s of audio waiting (CPU too busy? "
                      f"try NUM_THREADS = 4)")
            max_backlog, last_report = 0, time.time()
        peak = float(np.abs(chunk).max())
        if peak > 0.002:
            quiet_since = None
        elif quiet_since is None:
            quiet_since = time.time()
        if quiet_since and time.time() - quiet_since > 30 and not warned_silent:
            warned_silent = True    # once per silent stretch; a muted/blocked mic sends flat silence
            print("[audio] WARNING: no sound from the microphone for 30 s - muted, or wrong mic? "
                  "Run python mic_test.py")
        if quiet_since is None:
            warned_silent = False
        try:
            d.on_chunk(chunk)
        except Exception as e:
            print("[error]", e)
            ui_q.put(("state", "error", str(e)[:80]))
            d.state = "idle"
            d.push_mode()


def main():
    if sys.platform != "win32":
        sys.exit("This tool targets Windows.")
    _mutex = single_instance()
    if _mutex is None:
        sys.exit("Already running.")
    tray = Tray(cmds, ui_q)
    ui = UI(cmds, ui_q, tray)
    tray.run()

    def boot():
        print("Loading speech model...")
        try:
            engine = load_engine()
        except Exception as e:
            print("[fatal]", e)
            ui_q.put(("state", "error", str(e)[:80]))
            return
        bindings = []
        if config.HOTKEY_ENABLED:
            bindings.append((config.HOTKEY_MODIFIERS, config.HOTKEY_KEY, cmds, "toggle"))
        tts_worker_needed = config.TTS_HOTKEY_ENABLED or config.TTS_SAVE_HOTKEY_ENABLED
        if config.TTS_HOTKEY_ENABLED:
            bindings.append((config.TTS_HOTKEY_MODIFIERS, config.TTS_HOTKEY_KEY, tts_cmds, "toggle_read"))
            mods = "+".join(m.capitalize() for m in config.TTS_HOTKEY_MODIFIERS)
            print(f"Text-to-speech: select text anywhere, press {mods}+{config.TTS_HOTKEY_KEY.upper()} "
                  "to hear it (press again to stop; never saved to disk).")
        if config.TTS_SAVE_HOTKEY_ENABLED:
            bindings.append((config.TTS_SAVE_HOTKEY_MODIFIERS, config.TTS_SAVE_HOTKEY_KEY, tts_cmds, "toggle_save"))
            smods = "+".join(m.capitalize() for m in config.TTS_SAVE_HOTKEY_MODIFIERS)
            print(f"Text-to-speech (save): press {smods}+{config.TTS_SAVE_HOTKEY_KEY.upper()} to also "
                  f"save the audio to {config.TTS_SAVE_DIR} (needs TTS_ENGINE = \"piper\").")
        if tts_worker_needed:
            threading.Thread(target=tts_worker, daemon=True).start()
        if bindings:
            Hotkey(bindings).run()
        worker(engine)

    threading.Thread(target=boot, daemon=True).start()
    try:
        ui.root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

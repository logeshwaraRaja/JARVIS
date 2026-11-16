"""Text-to-speech: read the current selection aloud.

Grabs whatever is selected in the focused app with a simulated Ctrl+C (the AUTO_PASTE
clipboard trick, in reverse), then speaks it with the engine set as TTS_ENGINE in config.py:
"sapi" (speak.ps1), "onecore" (speak_onecore.ps1) or "piper" (played here through sounddevice).
No network call with any of them -- same on-device privacy posture as dictation itself.
"""
import ctypes
import subprocess
import threading
import time
import wave

import pyperclip
from pynput import keyboard

import config

CREATE_NO_WINDOW = 0x08000000
_SENTINEL = "\x00__jarvis_tts_sentinel__\x00"
_piper_voice = None   # (model_path, PiperVoice) -- loading the model is the slow part, cache it


def _modifiers_released(timeout=1.0):
    """Wait for the hotkey's own modifiers to physically come up before we simulate more
    keystrokes -- otherwise a still-held Ctrl/Alt from the shortcut can collide with the
    synthetic Ctrl+C we're about to send (same race AUTO_PASTE avoids before Ctrl+V)."""
    gk = ctypes.windll.user32.GetAsyncKeyState
    end = time.time() + timeout
    while time.time() < end:
        if not any(gk(v) & 0x8000 for v in (0x11, 0x12, 0x10, 0x20)):
            return
        time.sleep(0.02)


def grab_selection(timeout=0.5):
    """Copy the current selection and return it, restoring the clipboard afterward.
    Returns "" if nothing was selected (or the focused app ignored Ctrl+C, e.g. elevated apps)."""
    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    try:
        pyperclip.copy(_SENTINEL)
    except Exception:
        pass
    _modifiers_released()
    time.sleep(0.05)
    kb = keyboard.Controller()
    with kb.pressed(keyboard.Key.ctrl):
        kb.press("c")
        kb.release("c")
    end = time.time() + timeout
    text = _SENTINEL
    while time.time() < end:
        time.sleep(0.03)
        try:
            cur = pyperclip.paste()
        except Exception:
            continue
        if cur != _SENTINEL:
            text = cur
            break
    if old is not None:
        try:
            pyperclip.copy(old)
        except Exception:
            pass
    return "" if text == _SENTINEL else text


class _StoppableSpeech:
    """subprocess.Popen-alike (just .terminate() / .poll()) so tts_worker() in app.py can treat
    every TTS engine the same way, whether it's an actual OS process (sapi/onecore) or, as here,
    a Python thread streaming audio through sounddevice. `.result` is whatever `target` returned
    (e.g. the saved file's Path), readable once .poll() stops being None."""

    def __init__(self, target):
        self._stop = threading.Event()
        self._done = threading.Event()
        self.result = None
        self._thread = threading.Thread(target=self._run, args=(target,), daemon=True)
        self._thread.start()

    def _run(self, target):
        try:
            self.result = target(self._stop)
        except Exception as e:
            print("[tts-error] piper:", e)
        finally:
            self._done.set()

    def terminate(self):
        self._stop.set()

    def poll(self):
        return 0 if self._done.is_set() else None


def _load_piper_voice(model_path):
    global _piper_voice
    if _piper_voice is None or _piper_voice[0] != model_path:
        from piper import PiperVoice          # pip install piper-tts -- see README/backlog.md
        _piper_voice = (model_path, PiperVoice.load(str(model_path)))
    return _piper_voice[1]


def _speak_piper(text, model_path, stop_event):
    import numpy as np
    import sounddevice as sd
    voice = _load_piper_voice(model_path)
    stream = sd.OutputStream(samplerate=voice.config.sample_rate, channels=1, dtype="int16")
    stream.start()
    try:
        for chunk in voice.synthesize(text):
            if stop_event.is_set():
                break
            stream.write(np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16))
    finally:
        stream.stop()
        stream.close()


def _speak_and_save_piper(text, model_path, out_dir, stop_event):
    """Like _speak_piper, but also writes the audio to a timestamped WAV in out_dir. Returns
    the saved Path (or None if nothing was written, e.g. stopped before any audio arrived)."""
    import numpy as np
    import sounddevice as sd
    voice = _load_piper_voice(model_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"reading_{time.strftime('%Y%m%d_%H%M%S')}.wav"
    sr = voice.config.sample_rate
    stream = sd.OutputStream(samplerate=sr, channels=1, dtype="int16")
    stream.start()
    wrote_any = False
    try:
        with wave.open(str(out_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sr)
            for chunk in voice.synthesize(text):
                if stop_event.is_set():
                    break
                stream.write(np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16))
                wav_file.writeframes(chunk.audio_int16_bytes)
                wrote_any = True
    finally:
        stream.stop()
        stream.close()
    if not wrote_any:
        out_path.unlink(missing_ok=True)
        return None
    return out_path


def speak_and_save_async(text, engine="piper"):
    """Like speak_async(), but also saves the audio to config.TTS_SAVE_DIR -- nothing is ever
    saved unless this is called explicitly (the plain read-aloud path never writes to disk).
    Piper-only for now: "sapi"/"onecore" hand playback off to Windows itself, so this process
    never sees the raw audio to save it. Returns a _StoppableSpeech whose .result is the saved
    Path once .poll() stops being None (or None if stopped before any audio was generated)."""
    if engine != "piper":
        raise ValueError(f'Saving needs TTS_ENGINE = "piper", not {engine!r}')
    return _StoppableSpeech(
        lambda stop_event: _speak_and_save_piper(text, config.PIPER_MODEL_PATH, config.TTS_SAVE_DIR, stop_event))


def speak_async(text, rate=0, voice="", engine="sapi"):
    """Start speaking `text` in the background. Returns something with .terminate() (stop
    speaking early) and .poll() (None while still speaking) -- a real Popen for "sapi"/"onecore",
    a _StoppableSpeech wrapper for "piper".

    engine="sapi" (default): classic SAPI5 Desktop voices (David/Zira/Mark) via speak.ps1.
    engine="onecore": the newer Natural voices (Aria/Guy/Jenny/...) via speak_onecore.ps1.
    engine="piper": open-source neural voices (OHF-Voice/piper1-gpl), played directly through
    sounddevice -- no PowerShell involved. Needs `pip install piper-tts` and a downloaded voice
    model at config.PIPER_MODEL_PATH (see README).
    Rate control (`rate`) only applies to "sapi" for now -- see backlog.md."""
    if engine == "piper":
        return _StoppableSpeech(lambda stop_event: _speak_piper(text, config.PIPER_MODEL_PATH, stop_event))
    if engine == "onecore":
        args = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(config.BASE / "speak_onecore.ps1"), "-VoiceSub", voice or ""]
    else:
        args = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(config.BASE / "speak.ps1"),
                "-Rate", str(int(rate)), "-VoiceSub", voice or ""]
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
    proc.stdin.write(text.encode("utf-8", errors="replace"))
    proc.stdin.close()
    return proc

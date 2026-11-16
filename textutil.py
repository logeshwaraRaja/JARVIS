"""Pure helpers (no GUI/audio imports) so they can be unit-tested."""
import re
import numpy as np
import config

WAKE = re.compile(config.WAKE_REGEX, re.I)
STOP = re.compile(config.STOP_REGEX, re.I)
SOFT = re.compile(config.SOFT_STOP_REGEX, re.I)


def near_miss(text: str):
    """Words that look like 'jarvis' but did not match the wake regex (what the model heard instead)."""
    import difflib
    if WAKE.search(text):
        return []
    return [w for w in re.findall(r"[a-z']+", text.lower())
            if len(w) >= 3 and difflib.SequenceMatcher(None, w, "jarvis").ratio() >= 0.55]


def clean(s: str) -> str:
    s = re.sub(r"^[\s,.:;!?-]+", "", s)
    s = re.sub(r"[\s,;:-]+$", "", s)
    return (s[:1].upper() + s[1:]) if s else s


def extract(text: str, manual: bool):
    """Return (body, stopped). body = words after the wake phrase and before the stop phrase."""
    start = 0
    if not manual:
        m = WAKE.search(text)
        if m:
            start = m.end()
    body = text[start:]
    h = STOP.search(body)
    if h:
        body = body[:h.start()]
    return clean(body), bool(h)


_hue = 0.5


def analyse(chunk: np.ndarray, sr: int):
    """Return (amplitude 0..1, hue 0..1). Hue follows the voice pitch (low = cyan, high = magenta)."""
    global _hue
    rms = float(np.sqrt(np.mean(chunk ** 2)))
    if rms < 0.008:
        return 0.0, _hue
    amp = min(1.0, (rms * 10) ** 0.6)
    win = chunk * np.hanning(len(chunk))
    spec = np.abs(np.fft.rfft(win))
    freqs = np.fft.rfftfreq(len(chunk), 1.0 / sr)
    band = (freqs > 70) & (freqs < 450)
    if band.any():
        f = float(freqs[band][np.argmax(spec[band])])
        target = 0.5 + 0.38 * min(1.0, max(0.0, (f - 80) / 320))
        _hue = 0.8 * _hue + 0.2 * target
    return amp, _hue

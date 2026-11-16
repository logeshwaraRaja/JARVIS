"""Download a Piper text-to-speech voice (the .onnx model + its .onnx.json config) into models/piper.

    python download_voice.py                      the voice set as PIPER_MODEL_PATH in config.py
    python download_voice.py en_US-amy-medium     any other voice, by name
    python download_voice.py en_US-amy-medium en_GB-cori-medium ...

Voices come from https://huggingface.co/rhasspy/piper-voices (override the base URL with the
env var PIPER_VOICES_URL). Only the standard library is used, so this works before
`pip install piper-tts`. Each voice has its own license -- see its MODEL_CARD on Hugging Face.
"""
import os
import sys
import urllib.request

import config

BASE_URL = os.environ.get("PIPER_VOICES_URL", "https://huggingface.co/rhasspy/piper-voices/resolve/main")
dest = config.PIPER_MODEL_PATH.parent


def voice_url(name):
    """'en_GB-alba-medium' -> <base>/en/en_GB/alba/medium/en_GB-alba-medium"""
    try:
        lang, speaker, quality = name.split("-")
    except ValueError:
        sys.exit(f"'{name}' is not a voice name like en_GB-alba-medium (<lang>-<name>-<quality>).")
    return f"{BASE_URL}/{lang.split('_')[0]}/{lang}/{speaker}/{quality}/{name}"


def fetch(url, path):
    tmp = path.with_name(path.name + ".part")
    try:
        with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
            total, done = int(r.headers.get("Content-Length") or 0), 0
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                done += len(b)
                if total:
                    print(f"\r  {path.name}: {done * 100 // total}%", end="", flush=True)
        print()
        tmp.replace(path)
        return True
    except Exception as e:
        print(f"\n  {path.name}: download failed: {e}")
        tmp.unlink(missing_ok=True)
        return False


def download(name):
    onnx, cfg = dest / f"{name}.onnx", dest / f"{name}.onnx.json"
    if onnx.exists() and cfg.exists():
        print(f"{name}: already present.")
        return True
    print(f"{name}: downloading from {voice_url(name)}.onnx")
    ok = fetch(voice_url(name) + ".onnx.json", cfg) and fetch(voice_url(name) + ".onnx", onnx)
    if not ok:
        print(f"  If this source is blocked, download {name}.onnx and {name}.onnx.json another way "
              f"and put both into: {dest}")
    return ok


if __name__ == "__main__":
    names = sys.argv[1:] or [config.PIPER_MODEL_PATH.name[:-len(".onnx")]]
    dest.mkdir(parents=True, exist_ok=True)
    results = [download(n) for n in names]
    print("Done ->", dest)
    sys.exit(0 if all(results) else 1)

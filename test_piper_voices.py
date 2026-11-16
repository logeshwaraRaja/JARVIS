"""Synthesize the same sample text through every downloaded Piper voice, so you can compare
them by ear. Each voice announces itself first (e.g. "This is Amy, US English, medium
quality.") before reading the sample text, so you can tell them apart by listening alone.
Saves one WAV per voice into models/piper/samples/ and plays them back to back.

Run after downloading one or more voices (see README's "Read text aloud" section for the
download commands):

    python test_piper_voices.py            synthesize + save + play every voice in models/piper/
    python test_piper_voices.py --no-play   just synthesize and save the WAVs, don't play them
"""
import sys
import time
import wave

import numpy as np
import sounddevice as sd

import config

SAMPLE_TEXT = (
    "Good morning. Today we are rolling out the new authentication service to production. "
    "The deployment pipeline runs automated tests, builds a container image, and pushes it "
    "to the internal registry before anything reaches a live server. "
    "If the health check fails twice in a row, the rollout pauses and pages the on call engineer."
)

_LANG_NAMES = {"en_US": "US English", "en_GB": "British English"}


def _describe_voice(stem):
    """'en_US-amy-medium' -> 'Amy, US English, medium quality' (best-effort, falls back
    gracefully for names that don't follow the usual <lang>-<name>-<quality> pattern)."""
    parts = stem.split("-")
    lang = parts[0] if parts else stem
    name = parts[1].replace("_", " ").title() if len(parts) > 1 else stem
    quality = parts[2] if len(parts) > 2 else ""
    bits = [name, _LANG_NAMES.get(lang, lang)]
    if quality:
        bits.append(f"{quality} quality")
    return ", ".join(bits)


def _synthesize_into(voice, text, wav_file):
    """Stream Piper's own per-sentence chunks straight into an already-open wave.Wave_write.
    (Deliberately not using the synthesize_wav() convenience method twice on one file --
    Python's wave module locks nchannels/sampwidth/framerate after the first write, so a
    second such call raises wave.Error. Writing raw frames ourselves sidesteps that.)"""
    for chunk in voice.synthesize(text):
        wav_file.writeframes(chunk.audio_int16_bytes)


def main():
    from piper import PiperVoice   # pip install piper-tts

    voice_dir = config.PIPER_MODEL_PATH.parent
    onnx_files = sorted(voice_dir.glob("*.onnx"))
    if not onnx_files:
        print(f"No voice models found in {voice_dir}. See README's \"Read text aloud\" section "
              "for the download commands.")
        return

    out_dir = voice_dir / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    do_play = "--no-play" not in sys.argv

    print(f"Found {len(onnx_files)} voice(s). Sample text:\n  {SAMPLE_TEXT}\n")

    for onnx_path in onnx_files:
        name = onnx_path.stem
        intro = f"This is {_describe_voice(name)}."
        print(f"-- {name} --  (\"{intro}\")")
        try:
            voice = PiperVoice.load(str(onnx_path))
        except Exception as e:
            print(f"   could not load: {e}")
            continue

        sr = voice.config.sample_rate
        wav_path = out_dir / f"{name}.wav"
        with wave.open(str(wav_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sr)
            _synthesize_into(voice, intro, wav_file)
            wav_file.writeframes(np.zeros(int(0.5 * sr), dtype=np.int16).tobytes())  # short pause
            _synthesize_into(voice, SAMPLE_TEXT, wav_file)
        print(f"   saved {wav_path}")

        if do_play:
            with wave.open(str(wav_path), "rb") as wav_file:
                frames = wav_file.readframes(wav_file.getnframes())
            data = np.frombuffer(frames, dtype=np.int16)
            sd.play(data, sr)
            sd.wait()
            time.sleep(0.4)

    print(f"\nAll samples saved under {out_dir} -- replay any of them any time, or re-run with "
          "--no-play to just regenerate the files without listening again.")


if __name__ == "__main__":
    main()

"""Print the voices available on this machine, so you can set TTS_VOICE (or PIPER_MODEL_PATH)
in config.py.

    python list_voices.py              classic SAPI5 "Desktop" voices (used when TTS_ENGINE = "sapi")
    python list_voices.py --onecore    newer "Natural" voices (used when TTS_ENGINE = "onecore")
    python list_voices.py --piper      Piper voice models already downloaded into .\\models\\piper

Desktop voices are typically "Microsoft David Desktop" / "Microsoft Zira Desktop" (sometimes
"Mark") on a stock English Windows install. Natural voices (Aria, Guy, Jenny, ...) live under
Settings -> Time & Language -> Speech -> "Manage voices" -> Add voices -- if --onecore prints
nothing, none are installed yet (add one there first; can be unavailable on managed PCs).
Piper voices aren't "installed" system-wide -- download one with, e.g.:
    python -m piper.download_voices en_US-amy-medium --data-dir models/piper
(the files come from huggingface.co/rhasspy/piper-voices; browse
https://github.com/OHF-Voice/piper1-gpl for the full voice catalog and licenses)
"""
import json
import subprocess
import sys
from pathlib import Path

import config

_SAPI_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.GetInstalledVoices() | ForEach-Object {
    $i = $_.VoiceInfo
    "{0} | {1} | {2} | age {3}" -f $i.Name, $i.Culture, $i.Gender, $i.Age
}
"""

_ONECORE_SCRIPT = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime]
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$synth.AllVoices | ForEach-Object {
    "{0} | {1} | {2}" -f $_.DisplayName, $_.Language, $_.Gender
}
"""


def _list_piper():
    d = config.PIPER_MODEL_PATH.parent
    print(f"Piper voice models in {d}:\n")
    found = False
    if d.exists():
        for onnx in sorted(d.glob("*.onnx")):
            found = True
            cfg_path = onnx.with_suffix(".onnx.json")
            extra = ""
            if cfg_path.exists():
                try:
                    cfg = json.loads(cfg_path.read_text())
                    extra = f" | {cfg.get('audio', {}).get('sample_rate', '?')} Hz | {cfg.get('language', {}).get('code', '?')}"
                except Exception:
                    pass
            mark = "*" if onnx == config.PIPER_MODEL_PATH else " "
            print(f"  {mark} {onnx.name}{extra}")
    if not found:
        print("  (none found -- see the module docstring for the download command)")
    print("\n* = current PIPER_MODEL_PATH in config.py")


if __name__ == "__main__":
    if "--piper" in sys.argv:
        _list_piper()
        sys.exit(0)

    onecore = "--onecore" in sys.argv
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", _ONECORE_SCRIPT if onecore else _SAPI_SCRIPT],
        capture_output=True, text=True,
    )
    kind = "OneCore 'Natural' voices (DisplayName | Language | Gender)" if onecore else \
           "Classic SAPI5 'Desktop' voices (Name | Culture | Gender | Age)"
    print(f"Installed {kind}:\n")
    print(out.stdout.strip() or "(none found)")
    if out.stderr.strip():
        print("\n[stderr]", out.stderr.strip())
    if not onecore:
        print("\nRun `python list_voices.py --onecore` for the newer Natural voices, or "
              "`python list_voices.py --piper` for downloaded Piper models.")

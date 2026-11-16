"""Which microphone actually hears you?  Run:  python mic_test.py   then keep talking for ~2 s per device.

Stop the dictation app first (tray -> Quit) so it isn't holding the mic.
"""
import numpy as np
import sounddevice as sd

SR = 16000
default_in = sd.default.device[0]
apis = {i: a["name"] for i, a in enumerate(sd.query_hostapis())}
print("Speak continuously, e.g. count 1 to 10, while each device is tested.\n")
rows, seen = [], set()
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] < 1 or d["name"] in seen:
        continue
    seen.add(d["name"])
    try:
        a = sd.rec(int(SR * 2), samplerate=SR, channels=1, dtype="float32", device=i)
        sd.wait()
        peak = float(np.abs(a).max())
    except Exception as e:
        rows.append((i, d["name"], None, str(e)[:40])); continue
    rows.append((i, d["name"], peak, ""))
    bar = "#" * int(min(1.0, peak * 4) * 30)
    state = "SILENT (muted or no signal)" if peak < 0.001 else ("weak" if peak < 0.02 else "OK")
    print(f"{'*' if i == default_in else ' '} [{i}] {d['name'][:44]:44} peak={peak:.3f} {bar} {state}")
for i, n, p, err in rows:
    if p is None:
        print(f"  [{i}] {n[:44]} - could not open: {err}")
print("\n* = Windows default. Put a name that shows OK into INPUT_DEVICE in config.py.")

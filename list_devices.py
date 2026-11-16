"""Print the microphones Windows exposes, so you can set INPUT_DEVICE in config.py."""
import sounddevice as sd

default_in = sd.default.device[0]
print("Input devices (use any distinctive part of the name as INPUT_DEVICE):\n")
seen = set()
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0 and d["name"] not in seen:
        seen.add(d["name"])
        print(f"  {'*' if i == default_in else ' '} [{i}] {d['name']}")
print("\n* = current Windows default")

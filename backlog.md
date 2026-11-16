# Backlog

Enhancement ideas for this dictation / read-aloud tool, not yet scheduled or committed to.
Add to this list as new ideas come up; move an item into README's capabilities once it's built.

## Speech-to-text

- **Filler-word / grammar cleanup before paste.** Run dictated text through an LLM before it's
  copied/pasted, to drop filler words ("um", "uh") and fix grammar while keeping meaning and tone.
  Needs a callable model endpoint (a local model or a hosted API) and a pluggable backend (`SANITIZE_API_URL` / `SANITIZE_API_STYLE`), a
  short timeout with fallback to the raw transcript on error/timeout, and a README privacy update
  once enabled (dictated text would leave the device for this step).
- **Spoken formatting commands.** "new line", "comma", "period", etc. currently get typed literally
  instead of becoming real formatting. Doable as a text post-processing step before paste/copy, no
  model change needed.
- **Custom vocabulary / name boosting.** Bias recognition toward domain-specific terms, product
  names, or people's names that the model currently mishears.
- **Text replacement shortcuts.** A small dictionary so commonly mis-transcribed or frequently-typed
  terms (acronyms, names, standard phrases) get auto-corrected before paste.
- **Configurable onset / mic-gain threshold.** The "has speech started" volume threshold is
  currently hardcoded in `app.py`. Exposing it (and optionally a software gain multiplier) in
  `config.py` would help on quieter mics without relying solely on Windows' own mic boost setting.
- **Audio cue on start/stop.** A short beep instead of (or alongside) the visual card, useful when
  not looking at the screen (e.g. wearing a headset).

## Text-to-speech

- **Natural (OneCore) voices.** Shipped behind `TTS_ENGINE = "onecore"`, but only lightly tested:
  it needs a Natural voice added under Settings -> Speech, which is not possible on every PC
  (managed machines often block the Store download). Left in the code/config for machines that
  can use it.
- **Open-source (Piper) voices.** Done -- `TTS_ENGINE = "piper"` in `config.py`, played directly
  through `sounddevice` (no PowerShell involved for this one). Needs `pip install piper-tts` and a
  downloaded voice model (`PIPER_MODEL_PATH`, fetched by `download_voice.py`). GPL-3.0 engine
  license (espeak-ng phonemizer is GPL too); it is installed with pip, not bundled here. Voice
  models are licensed separately per voice (check each one's `MODEL_CARD`). Open follow-ups:
  `TTS_RATE` doesn't apply yet (Piper's own rate knob is `length_scale` in `SynthesisConfig`, a
  different scale again from both SAPI and OneCore).
- **"Read clipboard" as a second mode.** Separate from "read the current selection" -- a shortcut
  that reads back whatever's already on the clipboard, for cases where something was copied
  without using this app's hotkey.
- **Save-on-demand (Ctrl+Alt+Shift+S).** Done -- separate from the plain read-aloud hotkey (which
  never writes to disk), this one also saves a timestamped WAV to `TTS_SAVE_DIR`. Piper-only for
  now (`sapi`/`onecore` hand playback to Windows itself, so this process never has the raw audio
  to save). Deliberately a different letter from `TTS_HOTKEY_KEY`, not the same key plus Shift --
  the `Hotkey` matcher in `app.py` checks "are these modifiers held", not "are *only* these
  modifiers held", so two bindings sharing a key with one's modifiers a subset of the other's
  would both fire on the stricter combo. Worth fixing properly (exact-modifier matching) if a
  third overlapping shortcut is ever wanted; for now, "pick a different letter" is the workaround.
  Open follow-up: no option yet to save silently without also playing.

## Status

- [x] Auto-paste after dictation (`AUTO_PASTE`) -- shipped, on by default.
- [x] Read selection aloud (`TTS_HOTKEY`, Ctrl+Alt+R) -- shipped, never saves to disk.
- [x] Save-on-demand read-aloud (`TTS_SAVE_HOTKEY`, Ctrl+Alt+Shift+S) -- shipped, Piper-only.
- [x] Open-source (Piper) voices -- shipped behind `TTS_ENGINE = "piper"`, the current default;
  `download_voice.py` fetches voices, `test_piper_voices.py` compares them by ear.
- [x] Natural (OneCore) voices -- shipped behind `TTS_ENGINE = "onecore"`, lightly tested.
- [x] Commented-out `PIPER_MODEL_PATH` alternatives in `config.py` for six female voices --
  uncomment one instead of retyping the path.
- [ ] Everything else above -- not started.

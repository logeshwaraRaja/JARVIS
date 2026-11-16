"""Settings for the local dictation tool. Edit and restart app.py."""
from pathlib import Path

BASE = Path(__file__).resolve().parent

# --- Voice triggers (regex, case-insensitive; punctuation between words is ignored) ---
WAKE_ENABLED = True
# "Hey" is optional (the name alone also works) and common mishearings of Jarvis are accepted.
WAKE_REGEX = (r"\b(?:(?:hey|hay|hi|hello|okay|ok|a)\W*)?"
              r"(?:jarvis|jarvas|jarvus|jervis|jarvice|jarviss|jarvish|java's|jar\s+vis|jar\s+viss|charvis|garvis)\b")
# Troubleshooting only: write what the model heard (when it wasn't the wake phrase) to dictation.log.
# It stores your spoken words in plain text, so leave it off unless you are debugging the wake word.
WAKE_DEBUG = False
# Wake-word health trace -> wake_trace.log. Records only: activation latency, near-miss WORDS (e.g. "jarvas",
# "service") and audio-backlog warnings. It does not store your sentences.
WAKE_TRACE = True
STOP_REGEX = r"\bhalt\W*dictations?\b"
# Short stop: a bare "Halt" only counts when it is the LAST word and you then stay quiet for a moment,
# so sentences like "we need to halt the deployment" keep going.
SOFT_STOP_ENABLED = True
SOFT_STOP_REGEX = r"\bhalt\W*$"
SOFT_STOP_PAUSE = 0.8                       # seconds of silence after "Halt"

# --- Optional keyboard shortcut (press once to start, again to stop) ---
HOTKEY_ENABLED = True
HOTKEY_MODIFIERS = ("ctrl", "alt")      # any of: ctrl, alt, shift
HOTKEY_KEY = "space"

# --- Output ---
AUTO_PASTE = True                           # True = also press Ctrl+V in the focused app
RESTORE_CLIPBOARD = True                    # with AUTO_PASTE: put your old clipboard back afterwards

# --- Text-to-speech: select text in any app, press the shortcut, it's read aloud; press again to stop.
# No network call with any engine below -- "piper" is the only one needing a pip install + a
# one-time local model download (see README); "sapi" and "onecore" are built into Windows. ---
TTS_HOTKEY_ENABLED = True
TTS_HOTKEY_MODIFIERS = ("ctrl", "alt")  # any of: ctrl, alt, shift
TTS_HOTKEY_KEY = "r"
# "sapi" = classic Desktop voices (David/Zira/Mark, via speak.ps1, System.Speech). "onecore" = the
# newer "Natural" voices (Aria, Guy, Jenny, ... under Settings -> Time & Language -> Speech, via
# speak_onecore.ps1, Windows.Media.SpeechSynthesis) -- needs one installed first; can be unavailable on
# managed PCs since it's fetched through the Microsoft Store. "piper" = open-source
# neural voices (github.com/OHF-Voice/piper1-gpl, GPL-3.0 engine + GPL espeak-ng phonemizer -- it is
# installed separately with pip and not bundled here; keep that licence in mind if you ever
# redistribute it with this tool); needs `pip install piper-tts` and PIPER_MODEL_PATH below to
# point at a downloaded voice (voice licenses vary -- check each one's MODEL_CARD). Flip back to
# "sapi" any time -- this is just a config switch, nothing to uninstall.
# TTS_ENGINE = "sapi"
TTS_ENGINE = "piper"
TTS_RATE = 0                                # SAPI rate only: -10 (slowest) .. 10 (fastest), 0 = normal.
                                            # Not used by "onecore"/"piper" yet -- see backlog.md.
TTS_VOICE = "Zira"                          # substring of a voice name: SAPI "Name" (list_voices.py) or
                                            # OneCore "DisplayName" (list_voices.py --onecore). Not used
                                            # by "piper" -- that's picked via PIPER_MODEL_PATH instead.
# Only used by "piper" -- uncomment exactly one of these (whichever you've downloaded with
# download_voice.py, see the README); `list_voices.py --piper`
# lists what's actually in models/piper right now.
# PIPER_MODEL_PATH = BASE / "models" / "piper" / "en_US-amy-medium.onnx"          # soft/warm, conversational (US)
# PIPER_MODEL_PATH = BASE / "models" / "piper" / "en_US-lessac-high.onnx"         # highest quality, narrator style (US)
# PIPER_MODEL_PATH = BASE / "models" / "piper" / "en_GB-cori-medium.onnx"         # top-ranked naturalness (British)
# PIPER_MODEL_PATH = BASE / "models" / "piper" / "en_US-hfc_female-medium.onnx"   # US, non-commercial/research license
# PIPER_MODEL_PATH = BASE / "models" / "piper" / "en_US-kristin-medium.onnx"      # US, less common, worth a listen
PIPER_MODEL_PATH = BASE / "models" / "piper" / "en_GB-alba-medium.onnx"         # British, CC BY 4.0

# Separate shortcut that ALSO saves the audio to a file -- the plain TTS_HOTKEY above never
# writes anything to disk, only plays it; nothing is ever saved unless you press this one.
# Piper-only: "sapi"/"onecore" hand playback off to Windows itself, so this process never sees
# the raw audio to save it (pressing this with another engine selected just shows an error).
# Deliberately a different letter from TTS_HOTKEY_KEY, not just an extra modifier on the same
# key -- the hotkey matcher checks "are these modifiers held", not "are *only* these modifiers
# held", so reusing "r" with Shift added would fire *both* shortcuts at once.
TTS_SAVE_HOTKEY_ENABLED = True
TTS_SAVE_HOTKEY_MODIFIERS = ("ctrl", "alt", "shift")
TTS_SAVE_HOTKEY_KEY = "s"                   # Ctrl+Alt+Shift+S -- select text, press this, it reads
                                            # AND saves; press again while it's running to stop early.
TTS_SAVE_DIR = BASE / "tts_output"          # created on first save; files are named reading_<timestamp>.wav

# --- Engine: "nemotron" (sherpa-onnx, streaming, needed for voice triggers), "nemotron_local" (same
# model, but the Microsoft-exported ONNX graphs -- see NemotronLocalEngine in engines.py -- used when
# you already have a copy in that layout and don't want to download the sherpa-onnx release below) or "whisper" (manual start only) ---
# ENGINE = "nemotron_local"
ENGINE = "nemotron"
MODEL_DIR = BASE / "models" / "sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25"
# Where download_model.py gets the model. Point MODEL_URL (or the env var DICTATION_MODEL_URL) at a
# mirror of your own if you keep one. MODEL_SHA256: paste the hash it printed to lock the file.
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
             "sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25.tar.bz2")
MODEL_SHA256 = ""
# Model folder for ENGINE = "nemotron_local" (you supply it; see README "Speech engines").
NEMOTRON_LOCAL_MODEL_DIR = BASE / "models" / "nemotron-speech-streaming-en-0.6b-generic-cpu-3"
NUM_THREADS = 4                             # CPU threads for the speech model. Raise it if wake_trace.log
                                            # shows BACKLOG warnings (CPU falling behind real time, which
                                            # delays the wake word); drop to 2 if you have few cores to spare.
WHISPER_MODEL = "small.en"

# --- Audio ---
SAMPLE_RATE = 16000
INPUT_DEVICE = None                         # None = Windows default mic. Or part of a name, e.g. "Microphone Array".
                                            # If the named mic is missing or fails to open, the default is used.
MIN_SECONDS = 0.3

# --- UI ---
SHOW_CARD = True                            # the memo-style dictation card
SHOW_FLOATING_MIC = True                    # the small clickable mic button

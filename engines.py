"""Speech engines. API: start()/reset() -> feed(float32) -> partial() -> finish()."""
import json
import numpy as np
import config


# ---- shared log-mel feature extraction (NeMo-style) for NemotronLocalEngine ----

def _hz_to_mel(f):
    return 2595.0 * np.log10(1.0 + f / 700.0)


def _mel_to_hz(m):
    return 700.0 * (10.0 ** (m / 2595.0) - 1.0)


def _slaney_mel_filterbank(sr, n_fft, n_mels, fmin, fmax):
    """Matches librosa.filters.mel(..., htk=False) defaults, which is what
    NeMo's FilterbankFeatures uses to build its mel matrix."""
    n_freqs = n_fft // 2 + 1
    fft_freqs = np.linspace(0, sr / 2, n_freqs)
    mel_pts = np.linspace(_hz_to_mel(fmin), _hz_to_mel(fmax), n_mels + 2)
    hz_pts = _mel_to_hz(mel_pts)
    weights = np.zeros((n_mels, n_freqs), dtype=np.float64)
    fdiff = np.diff(hz_pts)
    ramps = hz_pts.reshape(-1, 1) - fft_freqs.reshape(1, -1)
    for i in range(n_mels):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        weights[i] = np.maximum(0, np.minimum(lower, upper))
    enorm = 2.0 / (hz_pts[2:n_mels + 2] - hz_pts[:n_mels])  # slaney area normalization
    weights *= enorm[:, np.newaxis]
    return weights.astype(np.float32)


class NemotronEngine:
    """Nemotron streaming ASR via sherpa-onnx (CPU, int8, no PyTorch)."""
    streaming = True

    def __init__(self):
        import sherpa_onnx
        d = config.MODEL_DIR
        if not (d / "tokens.txt").exists():
            raise FileNotFoundError(f"Model not found in {d}. Run: python download_model.py")
        self.rec = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(d / "tokens.txt"),
            encoder=str(d / "encoder.int8.onnx"),
            decoder=str(d / "decoder.int8.onnx"),
            joiner=str(d / "joiner.int8.onnx"),
            model_type="nemotron",
            feature_dim=128,
            sample_rate=config.SAMPLE_RATE,
            num_threads=config.NUM_THREADS,
            decoding_method="greedy_search",
            enable_endpoint_detection=False,
            provider="cpu",
        )
        self.stream = self.rec.create_stream()

    def start(self):
        self.stream = self.rec.create_stream()

    reset = start

    def _text(self):
        r = self.rec.get_result(self.stream)
        return (r if isinstance(r, str) else r.text).strip()

    def feed(self, samples: np.ndarray):
        self.stream.accept_waveform(config.SAMPLE_RATE, samples)
        while self.rec.is_ready(self.stream):
            self.rec.decode_stream(self.stream)

    def partial(self):
        return self._text()

    def finish(self):
        tail = np.zeros(int(0.66 * config.SAMPLE_RATE), dtype=np.float32)
        self.stream.accept_waveform(config.SAMPLE_RATE, tail)
        self.stream.input_finished()
        while self.rec.is_ready(self.stream):
            self.rec.decode_stream(self.stream)
        return self._text()


class NemotronLocalEngine:
    """Same Nemotron streaming ASR model as NemotronEngine, but reads the
    Microsoft/Olive-exported ONNX graphs (genai_config.json + encoder.onnx /
    decoder.onnx / joint.onnx) -- the ONNX Runtime GenAI layout -- instead of
    sherpa-onnx's own export. That export uses different tensor names/layouts than sherpa-onnx
    expects, so this engine talks to onnxruntime directly: it implements the
    cache-aware streaming encoder loop and a greedy RNNT decode loop itself,
    using only the parameters published in the model's own genai_config.json /
    audio_processor_config.json (no hardcoded shapes), so it also works with
    other same-format Nemotron exports dropped into the same folder layout.

    Use this when you already have a Microsoft-exported copy of the model
    locally and don't want to download the
    sherpa-onnx release that NemotronEngine/download_model.py normally fetch.
    Tradeoff: these graphs are typically fp32 (not int8), so this is heavier
    on CPU than NemotronEngine -- see README for a measured ballpark.
    """
    streaming = True

    def __init__(self):
        import onnxruntime as ort
        d = config.NEMOTRON_LOCAL_MODEL_DIR
        cfg_path = d / "genai_config.json"
        if not cfg_path.exists():
            raise FileNotFoundError(
                f"Model not found in {d}. Copy the Microsoft-exported model folder "
                f"(encoder.onnx(.data), decoder.onnx(.data), joint.onnx(.data), "
                f"vocab.txt, genai_config.json, audio_processor_config.json) there.")
        cfg = json.loads(cfg_path.read_text())["model"]
        self.vocab = [line.rstrip("\n") for line in (d / "vocab.txt").open(encoding="utf-8")]
        self.blank_id = cfg["blank_id"]
        self.max_symbols = cfg.get("max_symbols_per_step", 10)
        self.chunk_samples = cfg["chunk_samples"]
        self.sample_rate = cfg["sample_rate"]
        self.n_mels = cfg["num_mels"]
        self.n_fft = cfg["fft_size"]
        self.hop = cfg["hop_length"]
        self.win = cfg["win_length"]
        self.preemph = cfg["preemph"]
        self.log_eps = cfg["log_eps"]
        self.left_context = cfg["left_context"]
        self.conv_context = cfg["conv_context"]
        self.pre_encode_cache = cfg["pre_encode_cache_size"]
        self.window_size = self.chunk_samples // self.hop + self.pre_encode_cache
        self.enc_hid = cfg["encoder"]["hidden_size"]
        self.enc_layers = cfg["encoder"]["num_hidden_layers"]
        self.dec_hid = cfg["decoder"]["hidden_size"]
        self._enc_io, self._dec_io, self._joi_io = cfg["encoder"], cfg["decoder"], cfg["joiner"]
        self._mel_fb = _slaney_mel_filterbank(self.sample_rate, self.n_fft, self.n_mels, 0.0, self.sample_rate / 2)
        self._hann = np.hanning(self.win + 1)[:-1].astype(np.float32)

        so = ort.SessionOptions()
        so.intra_op_num_threads = config.NUM_THREADS
        # The model's own config recommends this for every sub-graph; disabling
        # the busy-spin wait avoided ~2.5x slower decoding under CPU contention
        # in testing -- keep it even though it looks like a no-op knob.
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self._enc_sess = ort.InferenceSession(str(d / self._enc_io["filename"]), so, providers=["CPUExecutionProvider"])
        self._dec_sess = ort.InferenceSession(str(d / self._dec_io["filename"]), so, providers=["CPUExecutionProvider"])
        self._joi_sess = ort.InferenceSession(str(d / self._joi_io["filename"]), so, providers=["CPUExecutionProvider"])
        self.start()

    def _mel_frames(self, samples: np.ndarray):
        if len(samples) == 0:
            return np.zeros((0, self.n_mels), dtype=np.float32)
        extended = np.concatenate([[self._prev_sample], samples]).astype(np.float64)
        pre = extended[1:] - self.preemph * extended[:-1]
        self._prev_sample = float(samples[-1])
        pad = self.n_fft // 2
        padded = np.pad(pre, (pad, pad), mode="reflect")
        n_frames = 1 + (len(padded) - self.n_fft) // self.hop
        frames = np.zeros((n_frames, self.n_mels), dtype=np.float32)
        for i in range(n_frames):
            start = i * self.hop
            seg = padded[start:start + self.win]
            buf = np.zeros(self.n_fft, dtype=np.float64)
            buf[:self.win] = seg * self._hann
            power = (np.abs(np.fft.rfft(buf)) ** 2.0).astype(np.float32)
            frames[i] = np.log(self._mel_fb @ power + self.log_eps)
        return frames

    def _encoder_step(self, raw_chunk: np.ndarray):
        new_frames = self._mel_frames(raw_chunk)
        frames = np.concatenate([self._mel_cache, new_frames], axis=0)
        if frames.shape[0] < self.window_size:
            valid_len = frames.shape[0]
            frames_in = np.concatenate(
                [frames, np.zeros((self.window_size - valid_len, self.n_mels), dtype=np.float32)], axis=0)
        else:
            frames_in = frames[-self.window_size:]
            valid_len = self.window_size
        self._mel_cache = frames[-self.pre_encode_cache:] if frames.shape[0] >= self.pre_encode_cache else frames

        i, o = self._enc_io["inputs"], self._enc_io["outputs"]
        feed = {
            i["audio_features"]: frames_in[np.newaxis, :, :].astype(np.float32),
            i["input_lengths"]: np.array([valid_len], dtype=np.int64),
            i["cache_last_channel"]: self._cache_last_channel,
            i["cache_last_time"]: self._cache_last_time,
            i["cache_last_channel_len"]: self._cache_last_channel_len,
        }
        names = [o["encoder_outputs"], o["output_lengths"], o["cache_last_channel_next"],
                 o["cache_last_time_next"], o["cache_last_channel_len_next"]]
        outputs, enc_len, self._cache_last_channel, self._cache_last_time, self._cache_last_channel_len = \
            self._enc_sess.run(names, feed)
        return outputs[0, :int(enc_len[0]), :]  # [time, enc_hid]

    def _decoder_step(self, token_id, h, c):
        i, o = self._dec_io["inputs"], self._dec_io["outputs"]
        feed = {i["targets"]: np.array([[token_id]], dtype=np.int64),
                i["lstm_hidden_state"]: h, i["lstm_cell_state"]: c}
        names = [o["outputs"], o["lstm_hidden_state"], o["lstm_cell_state"]]
        dec_out, h_out, c_out = self._dec_sess.run(names, feed)
        return dec_out[:, :, 0], h_out, c_out  # [1, dec_hid]

    def _joiner_step(self, enc_frame, dec_out):
        i, o = self._joi_io["inputs"], self._joi_io["outputs"]
        feed = {i["encoder_outputs"]: enc_frame[np.newaxis, np.newaxis, :],
                i["decoder_outputs"]: dec_out[np.newaxis, :, :]}
        logits = self._joi_sess.run([o["logits"]], feed)[0]
        return int(np.argmax(logits[0, 0, 0]))

    def _decode_chunk(self, raw_chunk: np.ndarray):
        for e_t in self._encoder_step(raw_chunk):
            n_sym = 0
            while n_sym < self.max_symbols:
                dec_out, h_try, c_try = self._decoder_step(self._last_token, self._h, self._c)
                best = self._joiner_step(e_t, dec_out)
                if best == self.blank_id:
                    break
                self._tokens.append(best)
                self._last_token = best
                self._h, self._c = h_try, c_try
                n_sym += 1

    def start(self):
        self._cache_last_channel = np.zeros((1, self.enc_layers, self.left_context, self.enc_hid), dtype=np.float32)
        self._cache_last_time = np.zeros((1, self.enc_layers, self.enc_hid, self.conv_context), dtype=np.float32)
        self._cache_last_channel_len = np.zeros((1,), dtype=np.int64)
        self._mel_cache = np.zeros((0, self.n_mels), dtype=np.float32)
        self._prev_sample = 0.0
        self._h = np.zeros((2, 1, self.dec_hid), dtype=np.float32)
        self._c = np.zeros((2, 1, self.dec_hid), dtype=np.float32)
        self._last_token = self.blank_id
        self._tokens = []
        self._buf = np.zeros(0, dtype=np.float32)

    reset = start

    def _text(self):
        pieces = [self.vocab[i] for i in self._tokens]
        return "".join(pieces).replace("▁", " ").strip()

    def feed(self, samples: np.ndarray):
        self._buf = np.concatenate([self._buf, samples.astype(np.float32)])
        while len(self._buf) >= self.chunk_samples:
            self._decode_chunk(self._buf[:self.chunk_samples])
            self._buf = self._buf[self.chunk_samples:]

    def partial(self):
        return self._text()

    def finish(self):
        tail = np.zeros(self.chunk_samples - len(self._buf), dtype=np.float32)
        self._decode_chunk(np.concatenate([self._buf, tail]))
        self._buf = np.zeros(0, dtype=np.float32)
        self._decode_chunk(np.zeros(self.chunk_samples, dtype=np.float32))  # flush trailing word, like NemotronEngine
        return self._text()


class WhisperEngine:
    """Fallback: transcribes when dictation stops. No live text, so no voice triggers."""
    streaming = False

    def __init__(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
        self.buf = []

    def start(self):
        self.buf = []

    reset = start

    def feed(self, samples):
        self.buf.append(samples)

    def partial(self):
        return ""

    def finish(self):
        if not self.buf:
            return ""
        audio = np.concatenate(self.buf)
        segs, _ = self.model.transcribe(audio, language="en", beam_size=5, vad_filter=True)
        return " ".join(s.text.strip() for s in segs).strip()


def load_engine():
    if config.ENGINE == "whisper":
        return WhisperEngine()
    if config.ENGINE == "nemotron_local":
        try:
            return NemotronLocalEngine()
        except Exception as e:
            print(f"[engine] NemotronLocal unavailable ({e}). Falling back to faster-whisper (no voice triggers).")
            return WhisperEngine()
    try:
        return NemotronEngine()
    except Exception as e:
        print(f"[engine] Nemotron unavailable ({e}). Falling back to faster-whisper (no voice triggers).")
        return WhisperEngine()

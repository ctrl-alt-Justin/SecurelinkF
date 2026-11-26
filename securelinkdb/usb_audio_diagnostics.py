"""Opt-in local capture of completed USB utterances and offline signal metrics."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from uuid import uuid4
import wave

import numpy as np


logger = logging.getLogger("securelink.usb_audio_diagnostics")
SAMPLE_RATE = 16000
CAPTURE_LIMIT = 5
MAX_PCM_BYTES = 16 * SAMPLE_RATE * 2
MIN_WINDOW_SAMPLES = SAMPLE_RATE // 4
LIMIT_LEVEL = 0.99


@dataclass
class AudioCapture:
    capture_id: str
    pin_pcm: bytes
    stages: dict[str, np.ndarray] = field(default_factory=dict)
    gain: float = 1.0
    unavailable_reason: str = "stage was not reached"

    def snapshot(self, stage: str, audio: np.ndarray) -> None:
        try:
            if audio.nbytes > MAX_PCM_BYTES * 2:
                self.unavailable_reason = "stage exceeded the diagnostic size limit"
                return
            self.stages[stage] = audio.copy()
        except Exception:
            self.unavailable_reason = "stage snapshot failed"
            logger.warning("USB audio diagnostic snapshot failed", exc_info=True)


class USBAudioDiagnostics:
    def __init__(self, root: Path, enabled: bool = False):
        self.enabled = enabled
        self._session = root / uuid4().hex if enabled else root
        self._lock = Lock()
        self._remaining = CAPTURE_LIMIT
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="usb-audio-diagnostic") if enabled else None

    def begin(self, pcm: bytes) -> AudioCapture | None:
        if self._worker is None or not pcm or len(pcm) % 2 or len(pcm) > MAX_PCM_BYTES:
            return None
        try:
            with self._lock:
                if not self._remaining:
                    return None
                capture = AudioCapture(f"{CAPTURE_LIMIT - self._remaining + 1:02d}", pcm)
                self._remaining -= 1
                return capture
        except Exception:
            logger.warning("USB audio diagnostic could not start", exc_info=True)
            return None

    def submit(self, capture: AudioCapture | None) -> None:
        if capture is None or self._worker is None:
            return
        try:
            self._worker.submit(self._write_capture, capture)
        except Exception:
            logger.warning("USB audio diagnostic could not be queued", exc_info=True)

    def close(self, *, wait: bool = True) -> None:
        if self._worker is not None:
            self._worker.shutdown(wait=wait)

    def _write_capture(self, capture: AudioCapture) -> None:
        try:
            self._session.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix=".pending-", dir=self._session) as pending:
                bundle = Path(pending) / capture.capture_id
                bundle.mkdir()
                with wave.open(str(bundle / "pin_pcm16.wav"), "wb") as raw:
                    raw.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
                    raw.writeframes(capture.pin_pcm)
                for name, audio in capture.stages.items():
                    np.save(bundle / f"{name}.npy", audio, allow_pickle=False)
                (bundle / "metrics.json").write_text(
                    json.dumps(_measure_capture(capture), indent=2, allow_nan=False) + "\n",
                    encoding="utf-8",
                )
                bundle.rename(self._session / capture.capture_id)
        except Exception:
            logger.warning("USB audio diagnostic could not be saved", exc_info=True)


def _speech_windows(audio: np.ndarray) -> list[dict]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    if not np.all(np.isfinite(audio)) or not np.any(audio):
        return []
    options = VadOptions(threshold=0.40, min_speech_duration_ms=250, speech_pad_ms=0)
    return get_speech_timestamps(audio, options, sampling_rate=SAMPLE_RATE)


def _measure_capture(capture: AudioCapture) -> dict:
    pin_samples = np.frombuffer(capture.pin_pcm, dtype="<i2")
    pin_audio = pin_samples.astype(np.float32) / 32768.0
    mask = np.zeros(pin_audio.size, dtype=bool)
    vad_error = None
    windows = []
    try:
        windows = _speech_windows(pin_audio)
        for window in windows:
            mask[window["start"]:window["end"]] = True
    except Exception:
        vad_error = "diagnostic VAD failed"
        mask.fill(False)
        windows = []

    pin_rail_count = int(np.count_nonzero((pin_samples == -32768) | (pin_samples == 32767)))
    stages = {
        "pin_pcm16": _stage_metrics(
            pin_audio, mask, vad_error, "pin_pcm16.wav",
            {"kind": "PCM16 rails", "threshold_pcm16": [-32768, 32767], "count": pin_rail_count},
        )
    }
    pre_gain = capture.stages.get("post_denoise_pre_gain")
    for name in ("post_denoise_pre_gain", "whisper_input"):
        audio = capture.stages.get(name)
        if audio is None:
            stages[name] = {"unavailable": capture.unavailable_reason}
            continue
        if name == "whisper_input":
            # Reconstruct the actual pre-limit values with the unchanged float32 gain.
            limited = (
                int(np.count_nonzero(np.abs(pre_gain * capture.gain) > LIMIT_LEVEL))
                if pre_gain is not None and pre_gain.shape == audio.shape else None
            )
            limits = {"kind": "desktop limiter", "threshold_full_scale": LIMIT_LEVEL, "count": limited}
        else:
            limits = {
                "kind": "at or beyond nominal full scale",
                "threshold_full_scale": 1.0,
                "count": int(np.count_nonzero(np.abs(audio) >= 1.0)),
            }
        stages[name] = _stage_metrics(audio, mask, vad_error, f"{name}.npy", limits)

    return {
        "capture_id": capture.capture_id,
        "sample_rate_hz": SAMPLE_RATE,
        "desktop_gain": capture.gain,
        "speech_windows_source": "pin_pcm16",
        "speech_windows_samples": windows,
        "speech_window_error": vad_error,
        "stages": stages,
    }


def _stage_metrics(audio, mask, vad_error, filename, limits):
    finite = bool(np.all(np.isfinite(audio)))
    result = {
        "file": filename,
        "dtype": "int16-le" if filename.endswith(".wav") else str(audio.dtype),
        "duration_s": audio.size / SAMPLE_RATE,
        "peak_full_scale": float(np.max(np.abs(audio))) if audio.size and finite else None,
        "clipping_or_limiting": limits,
        "speech_active_rms_full_scale": None,
        "background_rms_full_scale": None,
        "speech_to_background_db": None,
        "estimate_unavailable_reason": None,
    }
    if not finite:
        reason = "signal contains non-finite samples"
    elif audio.shape != mask.shape:
        reason = "stage sample count differs from PIN timeline"
    elif vad_error:
        reason = vad_error
    else:
        speech_count = int(np.count_nonzero(mask))
        if speech_count >= MIN_WINDOW_SAMPLES:
            result["speech_active_rms_full_scale"] = float(np.sqrt(np.mean(np.square(audio[mask], dtype=np.float64))))
        if audio.size - speech_count >= MIN_WINDOW_SAMPLES:
            result["background_rms_full_scale"] = float(np.sqrt(np.mean(np.square(audio[~mask], dtype=np.float64))))
        speech = result["speech_active_rms_full_scale"]
        background = result["background_rms_full_scale"]
        if not speech:
            reason = "less than 250 ms of measurable speech"
        elif background is None:
            reason = "less than 250 ms of background"
        elif background <= 1 / 32768:
            reason = "background at or below one PCM16 step"
        elif speech < 10 ** (3 / 20) * background:
            reason = "speech and background less than 3 dB apart or background louder"
        else:
            result["speech_to_background_db"] = float(20 * np.log10(speech / background))
            reason = None
    result["estimate_unavailable_reason"] = reason
    return result

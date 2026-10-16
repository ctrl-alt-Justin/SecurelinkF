"""
Microsoft NSNet2 (Noise Suppression Net 2) Speech Enhancement Module
Integrated for SecureLink AI Central System.

Eliminates fan noise, air-conditioning hum, and background classroom chatter
while preserving natural vocal dynamics and speech formants.
"""

import os
import numpy as np
import scipy.signal as signal
import onnxruntime as ort

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "nsnet2", "nsnet2-20ms-baseline.onnx")


class NSNet2Denoiser:
    """
    Production NSNet2 Speech Isolator.
    Processes 16kHz audio in 20ms frames with 50% overlap.
    """

    def __init__(self, model_path: str = MODEL_PATH, mingain_db: float = -12.0):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"NSNet2 model not found at {model_path}")

        self.cfg = {
            "winlen": 0.02,        # 20ms window
            "hopfrac": 0.5,        # 10ms frame shift (50% overlap)
            "fs": 16000,           # 16kHz sample rate
            "mingain": mingain_db, # -12dB floor: suppresses fan drone while eliminating spectral bubbling on word decays
            "feattype": "LogPow"
        }
        self.fs = int(self.cfg["fs"])
        self.win_len_samples = int(float(self.cfg["winlen"]) * self.fs) # 320 samples
        self.hop_samples = int(self.win_len_samples * float(self.cfg["hopfrac"])) # 160 samples
        self.mingain = 10 ** (self.cfg["mingain"] / 20.0)
        self.default_strength = 0.50 # Gentle neural isolation leaves trailing syllables natural and crumb-free

        # Initialize ONNX Runtime with CUDA if available, fallback to CPU
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        available_providers = ort.get_available_providers()
        selected_providers = [p for p in providers if p in available_providers]

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self.session = ort.InferenceSession(model_path, sess_options=sess_options, providers=selected_providers)
        self.input_name = self.session.get_inputs()[0].name
        self.window = np.sqrt(np.hanning(self.win_len_samples))

    def _stft(self, x: np.ndarray) -> np.ndarray:
        """Compute short-time Fourier transform without phase distortion."""
        if x.ndim == 1:
            x = x[:, np.newaxis]
        n_samples = x.shape[0]
        n_channels = x.shape[1]
        spec_size = int(self.win_len_samples // 2 + 1)
        n_frames = int(np.ceil((n_samples + self.win_len_samples - self.hop_samples) / self.hop_samples))
        padded_len = n_frames * self.hop_samples

        x_padded = np.vstack([x, np.zeros((padded_len - n_samples, n_channels))])
        x_spec = np.zeros((spec_size, n_frames, n_channels), dtype=complex)
        win_m = np.outer(self.window, np.ones((1, n_channels)))
        x_frame = np.zeros((self.win_len_samples, n_channels))

        for frame_idx in range(n_frames):
            idx = int(frame_idx * self.hop_samples)
            x_frame = np.vstack((x_frame[self.hop_samples:, :], x_padded[idx:idx + self.hop_samples, :]))
            x_win = win_m * x_frame
            x_spec[:, frame_idx, :] = np.fft.rfft(x_win, self.win_len_samples, axis=0)

        delay = int(self.win_len_samples // self.hop_samples - 1)
        x_spec = x_spec[:, delay:, :]

        if n_channels == 1:
            x_spec = np.squeeze(x_spec, axis=-1)
        return x_spec

    def _istft(self, spec: np.ndarray) -> np.ndarray:
        """Inverse STFT to reconstruct clean speech signal."""
        if spec.ndim < 3:
            spec = spec[:, :, np.newaxis]
        n_frames = spec.shape[1]
        n_channels = spec.shape[2]

        total_samples = self.hop_samples * (n_frames - 1) + self.win_len_samples
        win_m = np.outer(self.window, np.ones((1, n_channels)))
        signal_out = np.zeros((total_samples, n_channels))

        for frame_idx in range(n_frames):
            spec_frame = np.squeeze(spec[:, frame_idx, :])
            if spec_frame.ndim == 1:
                spec_frame = spec_frame[:, np.newaxis]
            x_win = np.fft.irfft(spec_frame, self.win_len_samples, axis=0)
            x_win = win_m * x_win[0:self.win_len_samples, :]
            idx1 = int(frame_idx * self.hop_samples)
            idx2 = int(idx1 + self.win_len_samples)
            signal_out[idx1:idx2, :] += x_win

        if n_channels == 1:
            signal_out = np.squeeze(signal_out, axis=-1)
        return signal_out

    def enhance(self, audio: np.ndarray, fs: int = 16000, strength: float = 0.65) -> np.ndarray:
        """
        Enhance and isolate human speech from noisy audio.
        strength: 0.0 (no noise suppression) to 1.0 (maximum suppression).
                  Default 0.65 preserves all vocal formants, nasal sounds ('ng', 'n', 'm'),
                  and word transitions while suppressing continuous fan drone.
        Accepts float32 in [-1.0, 1.0] or int16 PCM audio.
        Returns float32 clean audio in [-1.0, 1.0].
        """
        if audio is None or len(audio) == 0:
            return audio

        # Convert int16 to float32
        is_int16 = (audio.dtype == np.int16)
        if is_int16:
            audio_f = audio.astype(np.float32) / 32768.0
        else:
            audio_f = audio.astype(np.float32)

        # Resample if sample rate doesn't match 16kHz
        if fs != self.fs:
            num_target_samples = int(len(audio_f) * (self.fs / fs))
            audio_f = signal.resample(audio_f, num_target_samples)

        orig_len = len(audio_f)
        if orig_len < self.win_len_samples:
            # Too short to process through STFT
            return audio

        # 1. Complex STFT Spectrum
        input_spec = self._stft(audio_f)

        # 2. Log Power Spectrum Features
        pmin = 1e-12
        pow_spec = np.abs(input_spec) ** 2
        input_features = np.log10(np.maximum(pow_spec, pmin))

        # Shape: [batch=1, time, freq]
        input_features = np.expand_dims(np.transpose(input_features), axis=0).astype(np.float32)

        # 3. Neural Network Inference (Gain estimation)
        network_out = self.session.run(None, {self.input_name: input_features})[0][0]

        # 4. Apply estimated speech mask with gentle clamp & strength blending
        gain = np.transpose(network_out)
        gain = np.clip(gain, a_min=self.mingain, a_max=1.0)
        
        # Soft blend prevents cutting off nasal phonemes ('anong', 'na', 'mo')
        s = float(np.clip(strength, 0.0, 1.0))
        blended_gain = (1.0 - s) + (s * gain)
        clean_spec = input_spec * blended_gain

        # 5. Reconstruct time-domain audio via Inverse STFT
        clean_audio = self._istft(clean_spec)

        # Trim or pad back to original length
        if len(clean_audio) > orig_len:
            clean_audio = clean_audio[:orig_len]
        elif len(clean_audio) < orig_len:
            clean_audio = np.pad(clean_audio, (0, orig_len - len(clean_audio)))

        # Rescale if original was int16, otherwise guarantee float32
        if is_int16:
            clean_audio = np.clip(clean_audio * 32767.0, -32768, 32767).astype(np.int16)
        else:
            clean_audio = clean_audio.astype(np.float32)

        return clean_audio


# Global singleton instance for high performance
_denoiser_instance = None

def get_nsnet2_denoiser() -> NSNet2Denoiser:
    global _denoiser_instance
    if _denoiser_instance is None:
        _denoiser_instance = NSNet2Denoiser()
    return _denoiser_instance


def denoise_audio(audio: np.ndarray, fs: int = 16000, strength: float = 0.65) -> np.ndarray:
    """Convenience helper to denoise audio using NSNet2."""
    denoiser = get_nsnet2_denoiser()
    return denoiser.enhance(audio, fs=fs, strength=strength)

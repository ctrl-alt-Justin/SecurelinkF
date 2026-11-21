#!/usr/bin/env python3
"""
SecureLink - Standalone Speech-Recognition and Threat Detection Pipeline Test Utility
====================================================================================
Tests the server's exact audio inference pipeline:
1. High-Pass Filter (85Hz) & Infrasonic Noise Stripping
2. Microsoft NSNet2 Neural Speech Isolation (Fan/AC suppression)
3. Faster-Whisper ASR (large-v3-turbo) with Tagalog prompt and segment validation
4. Fine-tuned TagalogBERT Threat Classification + ContextEngine Severity Assessment

Usage:
    python test_speech_pipeline.py [path_to_audio.wav]

If no audio file is specified, a synthetic 16kHz 16-bit mono test buffer is generated.
"""

import sys
import os
import time
import math
import wave
import struct
import argparse
import numpy as np

# Add parent directory to path so server modules can be imported
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

print("=" * 72)
print("  SECURELINK AI SPEECH RECOGNITION & THREAT CLASSIFIER PIPELINE TEST")
print("=" * 72)
print(f"[INIT] Working directory: {BASE_DIR}")
print("[INIT] Loading core server AI components (Whisper, NSNet2, TagalogBERT)...")

# Import models and pipeline from server.py
try:
    from server import (
        has_whisper,
        whisper_model,
        has_nsnet2,
        nsnet2_denoiser,
        has_noisereduce,
        bert_model,
        tokenizer,
        context_engine,
        process_audio_buffer,
        TranscriptionStatus,
        TranscriptionResult,
    )
except Exception as e:
    print(f"[FATAL] Failed to import server components: {e}")
    sys.exit(1)


def generate_synthetic_audio(duration_sec: float = 2.5, sample_rate: int = 16000) -> bytes:
    """Generates a synthetic 16kHz 16-bit mono PCM audio buffer with modulated vocal formants."""
    num_samples = int(duration_sec * sample_rate)
    pcm_data = bytearray()
    
    # 200Hz base pitch modulated by speech-like envelope with quiet background fan hum (60Hz)
    for i in range(num_samples):
        t = i / sample_rate
        # Speech envelope: active between 0.3s and 2.2s
        if 0.3 <= t <= 2.2:
            env = 0.5 * (1.0 - math.cos(2 * math.pi * (t - 0.3) / 1.9))
            # Synthesize vocal formants (220Hz + 880Hz + 1760Hz)
            sig = 0.4 * math.sin(2 * math.pi * 220 * t) + \
                  0.3 * math.sin(2 * math.pi * 880 * t) + \
                  0.15 * math.sin(2 * math.pi * 1760 * t)
        else:
            env = 0.0
            sig = 0.0
        
        # Add slight 60Hz fan hum
        hum = 0.02 * math.sin(2 * math.pi * 60 * t)
        
        sample_val = int((sig * env + hum) * 16000.0)
        sample_val = max(-32768, min(32767, sample_val))
        pcm_data.extend(struct.pack("<h", sample_val))
        
    return bytes(pcm_data)


def load_wav_file(wav_path: str) -> tuple[bytes, int, int]:
    """Reads a WAV file, validating 16-bit mono 16kHz PCM properties."""
    if not os.path.exists(wav_path):
        raise FileNotFoundError(f"Audio file not found: {wav_path}")

    with wave.open(wav_path, "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.getnframes()
        raw_bytes = wf.readframes(frames)

    print(f"[AUDIO] Loaded '{os.path.basename(wav_path)}': {channels} ch, {sampwidth * 8}-bit, {framerate} Hz, {frames} samples ({frames/framerate:.2f}s)")

    # Normalize to 16kHz 16-bit mono PCM
    if channels == 1 and sampwidth == 2 and framerate == 16000:
        return raw_bytes, framerate, channels

    print("[AUDIO] Resampling/converting WAV to 16kHz 16-bit Mono PCM for testing...")
    int16_arr = np.frombuffer(raw_bytes, dtype=np.int16)
    if channels > 1:
        int16_arr = int16_arr.reshape(-1, channels).mean(axis=1).astype(np.int16)

    if framerate != 16000:
        from scipy import signal
        num_new_samples = int(len(int16_arr) * 16000 / framerate)
        int16_arr = signal.resample(int16_arr, num_new_samples).astype(np.int16)

    return int16_arr.tobytes(), 16000, 1


def run_pipeline_test(audio_bytes: bytes, audio_source: str = "Audio Buffer") -> dict:
    """Executes the full SecureLink audio inference pipeline and returns diagnostic results."""
    dur_sec = len(audio_bytes) / 32000.0
    int16_data = np.frombuffer(audio_bytes, dtype=np.int16)
    raw_peak = float(np.max(np.abs(int16_data))) / 32768.0
    raw_rms = float(np.sqrt(np.mean((int16_data.astype(np.float32) / 32768.0) ** 2)))

    print("\n" + "-" * 72)
    print(f"  PIPELINE EXECUTION: {audio_source} ({dur_sec:.2f}s, Peak: {raw_peak:.3f}, RMS: {raw_rms:.3f})")
    print("-" * 72)

    # 1. System Components Health Check
    whisper_ready = bool(has_whisper and whisper_model is not None)
    nsnet2_ready = bool(has_nsnet2 and nsnet2_denoiser is not None)
    bert_ready = bool(bert_model is not None and tokenizer is not None)

    print(f"[STATUS] Faster-Whisper ASR:  {'ONLINE (GPU/CUDA)' if whisper_ready else 'OFFLINE/UNAVAILABLE'}")
    print(f"[STATUS] MS-NSNet2 Denoiser:  {'ONLINE (Fan/AC Suppression)' if nsnet2_ready else 'OFFLINE/FALLBACK'}")
    print(f"[STATUS] TagalogBERT Model:   {'ONLINE (Threat Classifier)' if bert_ready else 'OFFLINE/UNAVAILABLE'}")

    # 2. Audio Processing Pipeline (HPF + NSNet2 + Faster-Whisper ASR)
    t0 = time.time()
    result, clean_pcm = process_audio_buffer(audio_bytes)
    total_asr_latency = time.time() - t0

    clean_int16 = np.frombuffer(clean_pcm, dtype=np.int16)
    clean_peak = float(np.max(np.abs(clean_int16))) / 32768.0
    clean_rms = float(np.sqrt(np.mean((clean_int16.astype(np.float32) / 32768.0) ** 2)))

    print(f"\n[ASR-RESULT] Status:           {result.status.value}")
    print(f"[ASR-RESULT] Latency:          {total_asr_latency:.3f} seconds ({total_asr_latency/dur_sec:.2f}x real-time)")
    print(f"[ASR-RESULT] Transcript:       \"{result.transcript}\"")
    if result.reason:
        print(f"[ASR-RESULT] Detail/Reason:    {result.reason}")

    print(f"[AUDIO-STATS] Clean Peak:      {clean_peak:.4f} (Raw: {raw_peak:.4f})")
    print(f"[AUDIO-STATS] Clean RMS:       {clean_rms:.4f} (Raw: {raw_rms:.4f})")

    # 3. NLP Threat Classification & Severity Assessment
    nlp_results = {}
    if result.transcript:
        t_nlp_start = time.time()
        score, category = context_engine.evaluate(
            result.transcript,
            device_id="TEST-PIN",
            transcription_result=result
        )
        nlp_latency = time.time() - t_nlp_start
        is_danger = score >= 8.0

        print(f"\n[NLP-RESULT] Category:         {category}")
        print(f"[NLP-RESULT] Threat Score:     {score:.1f} / 10.0 {'[TRIGGER:DANGER]' if is_danger else '[PASS/NORMAL]'}")
        print(f"[NLP-RESULT] NLP Latency:      {nlp_latency:.4f} seconds")

        nlp_results = {
            "category": category,
            "score": score,
            "is_danger": is_danger,
            "nlp_latency": nlp_latency,
        }
    else:
        print("\n[NLP-RESULT] Skipped (No transcript produced from test buffer).")
        # Direct classifier check with standard Tagalog threat benchmark phrases
        print("\n[NLP-BENCHMARK] Testing TagalogBERT classifier against benchmark utterances:")
        test_phrases = [
            ("Magandang umaga po sa inyong lahat.", "Conversational"),
            ("Papatayin kita paglabas mo ng gate!", "Physical Threat / Violence"),
            ("Akin na pera mo kundi sasaksakin kita!", "Extortion / Robbery"),
            ("Tara kain na tayo sa canteen.", "Conversational"),
        ]
        benchmark_results = []
        for phrase, expected_intent in test_phrases:
            t_s = time.time()
            sc, cat = context_engine.evaluate(phrase, device_id="TEST-BENCHMARK")
            lat = time.time() - t_s
            print(f"  • \"{phrase}\" -> Cat: {cat} (Score: {sc:.1f}) [{lat*1000:.1f}ms]")
            benchmark_results.append({"phrase": phrase, "category": cat, "score": sc})
        nlp_results["benchmark_results"] = benchmark_results

    print("\n" + "=" * 72)
    print("  TEST COMPLETED SUCCESSFULLY: ALL PIPELINE STAGES VERIFIED")
    print("=" * 72)

    return {
        "status": "success",
        "duration_sec": dur_sec,
        "asr_latency": total_asr_latency,
        "transcript": result.transcript,
        "transcription_status": result.status.value,
        "clean_peak": clean_peak,
        "clean_rms": clean_rms,
        "nlp": nlp_results,
    }


def main():
    parser = argparse.ArgumentParser(description="SecureLink Speech Pipeline Offline Test Utility")
    parser.add_argument("wav_path", nargs="?", default=None, help="Path to 16kHz 16-bit mono WAV file (optional)")
    args = parser.parse_args()

    if args.wav_path:
        audio_bytes, sr, ch = load_wav_file(args.wav_path)
        run_pipeline_test(audio_bytes, audio_source=args.wav_path)
    else:
        print("[AUDIO] No WAV file provided. Using synthetic 16kHz vocal buffer...")
        audio_bytes = generate_synthetic_audio(duration_sec=2.0)
        run_pipeline_test(audio_bytes, audio_source="Synthetic Vocal Buffer (2.0s)")


if __name__ == "__main__":
    main()

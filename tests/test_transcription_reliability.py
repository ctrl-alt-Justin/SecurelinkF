import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import wave
import numpy as np

# Ensure torch/lib is in DLL directory for Windows CUDA before importing server
import torch
if torch.cuda.is_available():
    torch_lib_dir = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.exists(torch_lib_dir):
        try:
            os.add_dll_directory(torch_lib_dir)
        except Exception:
            pass

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SECURELINK_DIR = os.path.join(WORKSPACE_ROOT, "securelinkdb")
if SECURELINK_DIR not in sys.path:
    sys.path.insert(0, SECURELINK_DIR)

from server import (
    TranscriptionStatus,
    TranscriptionResult,
    process_audio_buffer,
    handle_completed_audio,
    context_engine,
    registered_devices,
    active_pins,
)

RECORDINGS_DIR = os.path.join(SECURELINK_DIR, "recordings", "audio")


def load_wav_bytes(filename: str) -> bytes:
    path = os.path.join(RECORDINGS_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Fixture not found: {path}")
    with wave.open(path, "rb") as wf:
        return wf.readframes(wf.getnframes())


class TestTranscriptionReliability(unittest.TestCase):
    """Phase 1 Transcription Reliability & Silence Hallucination Tests."""

    def test_pure_digital_silence(self):
        """Pure zero PCM should return NO_SPEECH immediately."""
        zero_pcm = np.zeros(16000, dtype=np.int16).tobytes() # 1 second of silence
        result, clean_pcm = process_audio_buffer(zero_pcm)
        self.assertIsInstance(result, TranscriptionResult)
        self.assertEqual(result.status, TranscriptionStatus.NO_SPEECH)
        self.assertEqual(result.transcript, "")
        self.assertIn("silence", result.reason.lower())

    def test_buffer_too_short(self):
        """Buffers under 100ms should be dropped as NO_SPEECH."""
        short_pcm = np.zeros(1000, dtype=np.int16).tobytes()
        result, clean_pcm = process_audio_buffer(short_pcm)
        self.assertEqual(result.status, TranscriptionStatus.NO_SPEECH)
        self.assertIn("100ms", result.reason)

    def test_synthetic_fan_hum_and_hiss(self):
        """Low-level stationary fan hum/hiss should not generate transcripts."""
        t = np.linspace(0, 2.0, 32000, endpoint=False)
        # 60Hz hum + 120Hz harmonic + mild noise, scaled to peak ~0.008
        hum = 0.005 * np.sin(2 * np.pi * 60 * t) + 0.002 * np.sin(2 * np.pi * 120 * t)
        noise = np.random.normal(0, 0.001, 32000)
        synth_signal = (hum + noise).astype(np.float32)
        synth_pcm = (synth_signal * 32767.0).astype(np.int16).tobytes()

        result, _ = process_audio_buffer(synth_pcm)
        self.assertIn(
            result.status,
            (TranscriptionStatus.NO_SPEECH, TranscriptionStatus.TRANSCRIPTION_REJECTED),
        )
        self.assertEqual(result.transcript, "")

    def test_near_silence_real_fixture_evt135503(self):
        """EVT-135503.wav contains background room ambience (near-silence). Must not hallucinate."""
        pcm = load_wav_bytes("EVT-135503.wav")
        result, _ = process_audio_buffer(pcm)
        self.assertIn(
            result.status,
            (TranscriptionStatus.NO_SPEECH, TranscriptionStatus.TRANSCRIPTION_REJECTED),
        )
        self.assertEqual(result.transcript, "")

    def test_loud_acoustic_burst_not_hallucinated_as_danger_evt236767(self):
        """
        EVT-236767.wav previously hallucinated a 19-word threat hotword string.
        Under the updated pipeline, hotwords are disabled and segment checks reject non-speech.
        Must be TRANSCRIPTION_REJECTED and must never produce threat words.
        """
        pcm = load_wav_bytes("EVT-236767.wav")
        result, _ = process_audio_buffer(pcm)
        self.assertEqual(result.status, TranscriptionStatus.TRANSCRIPTION_REJECTED)
        # Verify fabricated threat string is completely absent
        threat_leak = any(
            w in result.transcript.lower()
            for w in ["patayin", "holdap", "bugbog", "sapakan", "nakaw", "suntan"]
        )
        self.assertFalse(threat_leak, f"Threat words leaked into rejected audio: '{result.transcript}'")

    def test_repetition_loop_rejected_evt1664(self):
        """EVT-1664.wav previously had runaway hallucination loops (cr=7.435). Must be blocked."""
        pcm = load_wav_bytes("EVT-1664.wav")
        result, _ = process_audio_buffer(pcm)
        self.assertIn(
            result.status,
            (TranscriptionStatus.NO_SPEECH, TranscriptionStatus.TRANSCRIPTION_REJECTED),
        )
        self.assertEqual(result.transcript, "")

    def test_quiet_genuine_speech_preserved_evt146419(self):
        """EVT-146419.wav is quiet genuine speech (peak=0.0359). Must NOT be dropped."""
        pcm = load_wav_bytes("EVT-146419.wav")
        result, _ = process_audio_buffer(pcm)
        self.assertEqual(result.status, TranscriptionStatus.TRANSCRIBED)
        self.assertTrue(len(result.transcript) > 0)
        self.assertGreater(result.metrics.get("avg_logprob", -2.0), -1.10)

    def test_tagalog_speech_preserved_evt187083(self):
        """EVT-187083.wav is genuine Tagalog speech ('Walang pasok')."""
        pcm = load_wav_bytes("EVT-187083.wav")
        result, _ = process_audio_buffer(pcm)
        self.assertEqual(result.status, TranscriptionStatus.TRANSCRIBED)
        self.assertIn("walang", result.transcript.lower())

    def test_english_speech_preserved_evt192827(self):
        """EVT-192827.wav is genuine English speech ('Mic test')."""
        pcm = load_wav_bytes("EVT-192827.wav")
        result, _ = process_audio_buffer(pcm)
        self.assertEqual(result.status, TranscriptionStatus.TRANSCRIBED)
        self.assertIn("test", result.transcript.lower())

    def test_taglish_speech_preserved_evt117465(self):
        """EVT-117465.wav is genuine Taglish speech ('hello mic check so ito...')."""
        pcm = load_wav_bytes("EVT-117465.wav")
        result, _ = process_audio_buffer(pcm)
        self.assertEqual(result.status, TranscriptionStatus.TRANSCRIBED)
        self.assertTrue(len(result.transcript) > 0)


class TestDangerGatingAndMockDeviceCommands(unittest.IsolatedAsyncioTestCase):
    """Verifies that non-transcribed statuses never trigger danger or dispatch hardware commands."""

    async def test_rejected_transcription_never_calls_evaluate_or_triggers_danger(self):
        """
        When process_audio_buffer returns TRANSCRIPTION_REJECTED (e.g. EVT-236767),
        context_engine.evaluate() must NOT be called, and TRIGGER:DANGER must NEVER be sent.
        """
        mock_ws = AsyncMock()
        device_id = "TEST-PIN-001"
        pcm = load_wav_bytes("EVT-236767.wav")

        with patch.object(context_engine, "evaluate", wraps=context_engine.evaluate) as mock_eval:
            await handle_completed_audio(device_id, pcm, mock_ws)
            mock_eval.assert_not_called()

        # Ensure no TRIGGER:DANGER was dispatched
        for call in mock_ws.send_text.call_args_list:
            self.assertNotEqual(call[0][0], "TRIGGER:DANGER")

    async def test_uncertain_transcription_never_calls_evaluate_or_triggers_danger(self):
        """
        When a result is UNCERTAIN_TRANSCRIPTION, it must never enter context_engine.evaluate()
        or trigger hardware danger.
        """
        mock_ws = AsyncMock()
        device_id = "TEST-PIN-002"
        pcm = np.zeros(16000, dtype=np.int16).tobytes()

        # Simulate process_audio_buffer returning UNCERTAIN_TRANSCRIPTION
        uncertain_res = TranscriptionResult(
            status=TranscriptionStatus.UNCERTAIN_TRANSCRIPTION,
            transcript="borderline acoustic noise",
            reason="Borderline acoustic confidence",
            metrics={"avg_logprob": -1.25}
        )

        with patch("server.process_audio_buffer", return_value=(uncertain_res, pcm)):
            with patch.object(context_engine, "evaluate") as mock_eval:
                await handle_completed_audio(device_id, pcm, mock_ws)
                mock_eval.assert_not_called()

        for call in mock_ws.send_text.call_args_list:
            self.assertNotEqual(call[0][0], "TRIGGER:DANGER")

    async def test_genuine_threat_transcribed_triggers_danger_safely_mocked(self):
        """
        When genuine threat speech IS TRANSCRIBED with high score, TRIGGER:DANGER is sent
        to the mocked websocket without contacting physical hardware.
        """
        mock_ws = AsyncMock()
        device_id = "TEST-PIN-003"
        pcm = np.zeros(16000, dtype=np.int16).tobytes()

        threat_res = TranscriptionResult(
            status=TranscriptionStatus.TRANSCRIBED,
            transcript="Sasapakin kita at papatayin kita gago ka",
            reason="Speech transcribed with high confidence",
            metrics={"avg_logprob": -0.35}
        )

        with patch("server.process_audio_buffer", return_value=(threat_res, pcm)):
            with patch("server.broadcast_to_ui", new_callable=AsyncMock):
                with patch("server.save_wav"):
                    await handle_completed_audio(device_id, pcm, mock_ws)

        # Mock websocket should have received TRIGGER:DANGER
        dispatched_messages = [c[0][0] for c in mock_ws.send_text.call_args_list]
        self.assertIn("TRIGGER:DANGER", dispatched_messages)


if __name__ == "__main__":
    unittest.main()


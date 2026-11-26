import asyncio
from collections import deque
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import wave
import httpx
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

from incident_store import IncidentStore
import server
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


def fixture_exists(filename: str) -> bool:
    return os.path.exists(os.path.join(RECORDINGS_DIR, filename))


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

    @unittest.skipIf(not fixture_exists("EVT-135503.wav"), "Fixture EVT-135503.wav not on disk")
    def test_near_silence_real_fixture_evt135503(self):
        """EVT-135503.wav contains background room ambience (near-silence). Must not hallucinate."""
        pcm = load_wav_bytes("EVT-135503.wav")
        result, _ = process_audio_buffer(pcm)
        self.assertIn(
            result.status,
            (TranscriptionStatus.NO_SPEECH, TranscriptionStatus.TRANSCRIPTION_REJECTED),
        )
        self.assertEqual(result.transcript, "")

    @unittest.skipIf(not fixture_exists("EVT-236767.wav"), "Fixture EVT-236767.wav not on disk")
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

    @unittest.skipIf(not fixture_exists("EVT-1664.wav"), "Fixture EVT-1664.wav not on disk")
    def test_repetition_loop_rejected_evt1664(self):
        """EVT-1664.wav previously had runaway hallucination loops (cr=7.435). Must be blocked."""
        pcm = load_wav_bytes("EVT-1664.wav")
        result, _ = process_audio_buffer(pcm)
        self.assertIn(
            result.status,
            (TranscriptionStatus.NO_SPEECH, TranscriptionStatus.TRANSCRIPTION_REJECTED),
        )
        self.assertEqual(result.transcript, "")

    @unittest.skipIf(not fixture_exists("EVT-146419.wav"), "Fixture EVT-146419.wav not on disk")
    def test_quiet_genuine_speech_preserved_evt146419(self):
        """EVT-146419.wav is quiet genuine speech (peak=0.0359). Must NOT be dropped."""
        pcm = load_wav_bytes("EVT-146419.wav")
        result, _ = process_audio_buffer(pcm)
        self.assertEqual(result.status, TranscriptionStatus.TRANSCRIBED)
        self.assertTrue(len(result.transcript) > 0)
        self.assertGreater(result.metrics.get("avg_logprob", -2.0), -1.10)

    @unittest.skipIf(not fixture_exists("EVT-187083.wav"), "Fixture EVT-187083.wav not on disk")
    def test_tagalog_speech_preserved_evt187083(self):
        """EVT-187083.wav is genuine Tagalog speech ('Walang pasok')."""
        pcm = load_wav_bytes("EVT-187083.wav")
        result, _ = process_audio_buffer(pcm)
        self.assertEqual(result.status, TranscriptionStatus.TRANSCRIBED)
        self.assertIn("walang", result.transcript.lower())

    @unittest.skipIf(not fixture_exists("EVT-192827.wav"), "Fixture EVT-192827.wav not on disk")
    def test_english_speech_preserved_evt192827(self):
        """EVT-192827.wav is genuine English speech ('Mic test')."""
        pcm = load_wav_bytes("EVT-192827.wav")
        result, _ = process_audio_buffer(pcm)
        self.assertEqual(result.status, TranscriptionStatus.TRANSCRIBED)
        self.assertIn("test", result.transcript.lower())

    @unittest.skipIf(not fixture_exists("EVT-117465.wav"), "Fixture EVT-117465.wav not on disk")
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
        pcm = np.zeros(16000, dtype=np.int16).tobytes()
        rejected_res = TranscriptionResult(
            status=TranscriptionStatus.TRANSCRIPTION_REJECTED,
            transcript="",
            reason="Repetition loop rejected",
            metrics={"avg_logprob": -1.5}
        )

        with patch("server.process_audio_buffer", return_value=(rejected_res, pcm)):
            with patch.object(context_engine, "evaluate", wraps=context_engine.evaluate) as mock_eval:
                await handle_completed_audio(device_id, pcm, mock_ws)
                mock_eval.assert_not_called()

        # Ensure no TRIGGER:DANGER was dispatched
        for call in mock_ws.send_text.call_args_list:
            self.assertNotEqual(call[0][0], "TRIGGER:DANGER")

    async def test_uncertain_transcription_routes_for_human_review_without_danger(self):
        """
        When a result is UNCERTAIN_TRANSCRIPTION, it must route for human review with original + normalized text,
        confidence metrics, and authorized audio linkage, while NEVER triggering DANGER or emergency hardware.
        """
        mock_ws = AsyncMock()
        device_id = "TEST-PIN-002"
        pcm = np.zeros(16000, dtype=np.int16).tobytes()

        uncertain_res = TranscriptionResult(
            status=TranscriptionStatus.UNCERTAIN_TRANSCRIPTION,
            transcript="Papatayin kita mamaya!",
            reason="Borderline acoustic confidence (avg_logprob=-1.250 < -1.10)",
            metrics={"avg_logprob": -1.25, "no_speech_prob": 0.12, "compression_ratio": 1.15},
        )

        # Direct WebSocket source verification
        direct_incidents = deque()
        direct_reviews = deque()
        direct_auth_audio = {}
        direct_broadcast = AsyncMock()
        direct_preview = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            iso_store = IncidentStore(os.path.join(tmpdir, "incidents.db"))
            try:
                with (
                    patch("server.process_audio_buffer", return_value=(uncertain_res, pcm)),
                    patch("server.broadcast_to_ui", direct_broadcast),
                    patch("server.save_wav") as mock_save,
                    patch("server.incident_store", iso_store),
                    patch("server.recent_incidents", direct_incidents),
                    patch("server.recent_uncertain_reviews", direct_reviews),
                    patch("server.authorized_review_audio", direct_auth_audio),
                    patch("server.ordinary_speech_preview", direct_preview),
                    patch("server.UNCERTAIN_REVIEW_AUDIO_DIR", tmpdir),
                ):
                    await handle_completed_audio(device_id, pcm, mock_ws, source="ESP32_DIRECT")
            finally:
                iso_store.close()

        for call in mock_ws.send_text.call_args_list:
            self.assertNotEqual(call[0][0], "TRIGGER:DANGER")
        mock_save.assert_called_once()
        saved_path = mock_save.call_args[0][1]
        self.assertTrue(os.path.dirname(saved_path).endswith(os.path.basename(tmpdir)))
        direct_preview.publish.assert_not_called()

        self.assertEqual(len(direct_incidents), 1)
        self.assertEqual(len(direct_reviews), 1)
        payload = direct_incidents[0]
        self.assertLess(payload["score"], 8.0)
        self.assertFalse(payload["video"])
        self.assertTrue(payload["human_review_required"])
        self.assertEqual(payload["review_status"], "PENDING_REVIEW")
        self.assertEqual(payload["transcription_status"], "UNCERTAIN_TRANSCRIPTION")
        self.assertEqual(payload["original_transcript"], "Papatayin kita mamaya!")
        self.assertEqual(payload["normalized_transcript"], "papatayin kita mamaya")
        self.assertEqual(payload["confidence"]["avg_logprob"], -1.25)
        self.assertTrue(payload["audio_authorized"])
        self.assertTrue(payload["audio_review_url"].startswith("/api/review/audio/"))

        # USB source verification: must NEVER invoke USB danger hardware methods
        usb_mock = MagicMock()
        usb_mock.is_authenticated = True
        usb_mock.device_id = device_id
        with tempfile.TemporaryDirectory() as tmpdir:
            iso_store_usb = IncidentStore(os.path.join(tmpdir, "incidents_usb.db"))
            try:
                with (
                    patch("server.process_audio_buffer", return_value=(uncertain_res, pcm)),
                    patch("server.broadcast_to_ui", new_callable=AsyncMock),
                    patch("server.save_wav"),
                    patch("server.usb_mgr", usb_mock),
                    patch("server.incident_store", iso_store_usb),
                    patch("server.recent_incidents", deque()),
                    patch("server.recent_uncertain_reviews", deque()),
                    patch("server.authorized_review_audio", {}),
                    patch("server.UNCERTAIN_REVIEW_AUDIO_DIR", tmpdir),
                ):
                    await handle_completed_audio(device_id, pcm, websocket=None, source="USB")
            finally:
                iso_store_usb.close()
        usb_mock.send_line.assert_not_called()
        usb_mock.send_danger_trigger.assert_not_called()
        usb_mock._send_text.assert_not_called()

    async def test_review_audio_endpoint_requires_valid_token(self):
        """Uncertain review audio endpoint must reject missing/bad tokens and serve WAV only to valid tokens."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_name = "EVT-TESTREV.wav"
            wav_path = os.path.join(tmpdir, wav_name)
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(np.zeros(1600, dtype=np.int16).tobytes())

            auth_store = {}
            iso_store = IncidentStore(os.path.join(tmpdir, "incidents.db"))
            try:
                with (
                    patch.object(server, "UNCERTAIN_REVIEW_AUDIO_DIR", tmpdir),
                    patch.object(server, "authorized_review_audio", auth_store),
                    patch.object(server, "incident_store", iso_store),
                    patch.object(server, "recent_uncertain_reviews", deque()),
                ):
                    token = server._register_authorized_review_audio("EVT-TESTREV", wav_name, "PIN-001")
                    transport = httpx.ASGITransport(app=server.app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
                        r_no_tok = await client.get("/api/review/audio/EVT-TESTREV")
                        r_bad_tok = await client.get("/api/review/audio/EVT-TESTREV?token=wrongtoken")
                        r_query_ok = await client.get(f"/api/review/audio/EVT-TESTREV?token={token}")
                        r_bearer_ok = await client.get(
                            "/api/review/audio/EVT-TESTREV",
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        r_list = await client.get("/api/review/uncertain")

                    self.assertEqual(r_no_tok.status_code, 401)
                    self.assertEqual(r_bad_tok.status_code, 401)
                    self.assertEqual(r_query_ok.status_code, 200)
                    self.assertEqual(r_query_ok.headers.get("content-type"), "audio/wav")
                    self.assertEqual(r_bearer_ok.status_code, 200)
                    self.assertEqual(r_list.status_code, 200)
                    self.assertEqual(r_list.json()["status"], "success")
            finally:
                iso_store.close()

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

        with tempfile.TemporaryDirectory() as tmpdir:
            iso_store = IncidentStore(os.path.join(tmpdir, "incidents.db"))
            try:
                with (
                    patch("server.process_audio_buffer", return_value=(threat_res, pcm)),
                    patch("server.broadcast_to_ui", new_callable=AsyncMock),
                    patch("server.save_wav"),
                    patch("server.incident_store", iso_store),
                    patch("server.recent_incidents", deque(maxlen=50)),
                ):
                    await handle_completed_audio(device_id, pcm, mock_ws)
            finally:
                iso_store.close()

        # Mock websocket should have received TRIGGER:DANGER
        dispatched_messages = [c[0][0] for c in mock_ws.send_text.call_args_list]
        self.assertIn("TRIGGER:DANGER", dispatched_messages)


if __name__ == "__main__":
    unittest.main()

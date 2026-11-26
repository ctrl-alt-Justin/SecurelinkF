"""
Regression & integration tests for SecureLink V4:
- Task 1: USB danger command delivery through owning USBDeviceManager method,
  delivery-failure resilience (WAV + UI broadcast still occur), and inference-state
  reset on completion, error, and reconnect.
- Task 2: Local SQLite IncidentStore persistence across backend restarts, legacy + V4
  field preservation, POST /api/incidents/{id}/review & GET /api/incidents*,
  restart-resilient review audio tokens, and ordinary-speech exclusion from SQLite.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import wave
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import numpy as np
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

import server  # noqa: E402
from incident_store import IncidentStore  # noqa: E402
from server import (  # noqa: E402
    TranscriptionResult,
    TranscriptionStatus,
    handle_completed_audio,
)
from usb_manager import USBDeviceManager  # noqa: E402


class _FakeSerialPort:
    def __init__(self, fail_write: bool = False):
        self.is_open = True
        self.fail_write = fail_write
        self.write_buffer = bytearray()

    def write(self, data: bytes) -> int:
        if self.fail_write:
            raise OSError("Simulated USB write error")
        self.write_buffer.extend(data)
        return len(data)

    def flush(self) -> None:
        pass


class TestUsbDangerDeliveryAndIncidentStore(unittest.IsolatedAsyncioTestCase):
    async def test_usb_danger_delivery_and_failure_resilience(self):
        """
        1) Valid USB DANGER threat calls send_danger_trigger and writes SL:TRIGGER:DANGER.
        2) Serial write failure never aborts WAV saving, UI broadcast, SQLite save, or state reset.
        """
        pcm = (np.ones(16000, dtype=np.int16) * 400).tobytes()
        threat_res = TranscriptionResult(
            status=TranscriptionStatus.TRANSCRIBED,
            transcript="Papatayin kita mamaya sa gate!",
            reason="High confidence speech",
            metrics={"avg_logprob": -0.25},
        )

        # Case A: Healthy USB serial write
        mgr_ok = USBDeviceManager()
        port_ok = _FakeSerialPort(fail_write=False)
        mgr_ok.serial_port = port_ok
        mgr_ok.is_authenticated = True
        mgr_ok.device_id = "PIN-USB-1"
        mgr_ok.last_heartbeat_ts = time.time()
        mgr_ok.vad_state = "VAD ARMED"

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "incidents.db")
            store = IncidentStore(db_path)
            bcast = AsyncMock()
            mock_reg = {"PIN-USB-1": {"id": "PIN-USB-1", "state": "VAD ARMED", "online": False}}
            try:
                with (
                    patch.object(server, "usb_mgr", mgr_ok),
                    patch.object(server, "incident_store", store),
                    patch.object(server, "process_audio_buffer", return_value=(threat_res, pcm)),
                    patch.object(server, "broadcast_to_ui", bcast),
                    patch.object(server, "AUDIO_RECORDINGS_DIR", tmpdir),
                    patch.object(server, "registered_devices", mock_reg),
                    patch.object(server, "recent_incidents", deque(maxlen=50)),
                    patch.object(server, "usb_audio_diagnostics", MagicMock(enabled=False)),
                ):
                    await handle_completed_audio("PIN-USB-1", pcm, source="USB")
            finally:
                store.close()

            self.assertIn(b"SL:TRIGGER:DANGER\n", bytes(port_ok.write_buffer))
            self.assertFalse(mgr_ok.audio_analyzing)
            self.assertEqual(mgr_ok.vad_state, "VAD ARMED")
            self.assertEqual(mock_reg["PIN-USB-1"]["state"], "VAD ARMED")
            wav_files = [f for f in os.listdir(tmpdir) if f.endswith(".wav")]
            self.assertEqual(len(wav_files), 1)
            incident_events = [c.args[0] for c in bcast.call_args_list if c.args and c.args[0].get("event_type") == "incident"]
            self.assertEqual(len(incident_events), 1)
            self.assertEqual(incident_events[0]["level"], "DANGER")

        # Case B: USB write raises OSError -> WAV, UI broadcast, SQLite, and reset MUST still succeed
        mgr_fail = USBDeviceManager()
        port_fail = _FakeSerialPort(fail_write=True)
        mgr_fail.serial_port = port_fail
        mgr_fail.is_authenticated = True
        mgr_fail.device_id = "PIN-USB-2"
        mgr_fail.last_heartbeat_ts = time.time()
        mgr_fail.vad_state = "VAD ARMED"

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "incidents.db")
            store = IncidentStore(db_path)
            bcast = AsyncMock()
            mock_reg = {"PIN-USB-2": {"id": "PIN-USB-2", "state": "VAD ARMED", "online": False}}
            try:
                with (
                    patch.object(server, "usb_mgr", mgr_fail),
                    patch.object(server, "incident_store", store),
                    patch.object(server, "process_audio_buffer", return_value=(threat_res, pcm)),
                    patch.object(server, "broadcast_to_ui", bcast),
                    patch.object(server, "AUDIO_RECORDINGS_DIR", tmpdir),
                    patch.object(server, "registered_devices", mock_reg),
                    patch.object(server, "recent_incidents", deque(maxlen=50)),
                    patch.object(server, "usb_audio_diagnostics", MagicMock(enabled=False)),
                ):
                    await handle_completed_audio("PIN-USB-2", pcm, source="USB")
                self.assertEqual(store.count_incidents(), 1)
            finally:
                store.close()

            self.assertFalse(mgr_fail.audio_analyzing)
            self.assertEqual(mgr_fail.vad_state, "VAD ARMED")
            self.assertEqual(mock_reg["PIN-USB-2"]["state"], "VAD ARMED")
            wav_files = [f for f in os.listdir(tmpdir) if f.endswith(".wav")]
            self.assertEqual(len(wav_files), 1, "WAV evidence MUST still be saved on USB write failure")
            incident_events = [c.args[0] for c in bcast.call_args_list if c.args and c.args[0].get("event_type") == "incident"]
            self.assertEqual(len(incident_events), 1, "UI broadcast MUST still fire on USB write failure")

    async def test_inference_error_and_reconnect_cleanly_reset_analyzing_state(self):
        """Exceptions during inference never leave usb_mgr.audio_analyzing or device state stuck."""
        pcm = (np.ones(16000, dtype=np.int16) * 200).tobytes()
        mgr = USBDeviceManager()
        mgr.serial_port = _FakeSerialPort()
        mgr.is_authenticated = True
        mgr.device_id = "PIN-USB-ERR"
        mgr.last_heartbeat_ts = time.time()
        mgr.vad_state = "VAD ARMED"

        mock_reg = {"PIN-USB-ERR": {"id": "PIN-USB-ERR", "state": "VAD ARMED", "online": True}}
        with (
            patch.object(server, "usb_mgr", mgr),
            patch.object(server, "process_audio_buffer", side_effect=RuntimeError("ASR boom")),
            patch.object(server, "broadcast_to_ui", AsyncMock()),
            patch.object(server, "registered_devices", mock_reg),
            patch.object(server, "usb_audio_diagnostics", MagicMock(enabled=False)),
        ):
            with self.assertRaises(RuntimeError):
                await handle_completed_audio("PIN-USB-ERR", pcm, source="USB")

        self.assertFalse(mgr.audio_analyzing)
        self.assertEqual(mgr.vad_state, "VAD ARMED")
        self.assertEqual(mock_reg["PIN-USB-ERR"]["state"], "VAD ARMED")

        # Disconnect while analyzing also resets audio_analyzing
        mgr.audio_analyzing = True
        mgr._mark_disconnected(reason="Unplugged mid-analysis")
        self.assertFalse(mgr.audio_analyzing)
        self.assertEqual(mgr.vad_state, "OFFLINE")

    async def test_sqlite_incident_persistence_review_endpoints_and_ordinary_exclusion(self):
        """
        Verify SQLite persistence across restart, review endpoints (PENDING/CONFIRMED/DISMISSED),
        authorized review audio restart fallback, and ordinary speech NEVER written to SQLite.
        """
        pcm = (np.ones(16000, dtype=np.int16) * 300).tobytes()
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "incidents.db")
            review_dir = os.path.join(tmpdir, "review_audio")
            audio_dir = os.path.join(tmpdir, "audio")
            os.makedirs(review_dir, exist_ok=True)
            os.makedirs(audio_dir, exist_ok=True)

            store1 = IncidentStore(db_path)
            uncertain_res = TranscriptionResult(
                status=TranscriptionStatus.UNCERTAIN_TRANSCRIPTION,
                transcript="Sasapakin kita mamaya!",
                reason="Borderline confidence",
                metrics={"avg_logprob": -1.2},
            )
            benign_res = TranscriptionResult(
                status=TranscriptionStatus.TRANSCRIBED,
                transcript="Tara kain tayo sa canteen mamaya.",
                reason="High confidence",
                metrics={"avg_logprob": -0.2},
            )

            def _write_wav(pcm_data, path):
                with wave.open(path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(pcm_data)

            preview_mock = MagicMock()
            with (
                patch.object(server, "incident_store", store1),
                patch.object(server, "UNCERTAIN_REVIEW_AUDIO_DIR", review_dir),
                patch.object(server, "AUDIO_RECORDINGS_DIR", audio_dir),
                patch.object(server, "save_wav", side_effect=_write_wav),
                patch.object(server, "broadcast_to_ui", AsyncMock()),
                patch.object(server, "ordinary_speech_preview", preview_mock),
                patch.object(server, "registered_devices", {"PIN-DB": {"id": "PIN-DB", "state": "VAD ARMED"}}),
                patch.object(server, "active_pins", {}),
                patch.object(server, "recent_incidents", deque(maxlen=50)),
                patch.object(server, "recent_uncertain_reviews", deque(maxlen=50)),
                patch.object(server, "authorized_review_audio", {}),
                patch.object(server, "usb_audio_diagnostics", MagicMock(enabled=False)),
            ):
                # 1. Ordinary speech -> preview only, NEVER written to SQLite
                with patch.object(server, "process_audio_buffer", return_value=(benign_res, pcm)):
                    await handle_completed_audio("PIN-DB", pcm, source="ESP32_DIRECT")
                preview_mock.publish.assert_called_once()
                self.assertEqual(store1.count_incidents(), 0)

                # 2. Uncertain flagged utterance -> written to SQLite + review token hashed
                with patch.object(server, "process_audio_buffer", return_value=(uncertain_res, pcm)):
                    await handle_completed_audio("PIN-DB", pcm, source="ESP32_DIRECT")
                self.assertEqual(store1.count_incidents(), 1)
                saved = store1.list_incidents(limit=10)[0]
                incident_id = saved["id"]
                review_url = saved["audio_review_url"]
                self.assertEqual(saved["original_transcript"], "Sasapakin kita mamaya!")
                self.assertEqual(saved["normalized_transcript"], "sasapakin kita mamaya")
                self.assertEqual(saved["transcription_status"], "UNCERTAIN_TRANSCRIPTION")
                self.assertEqual(saved["review_status"], "PENDING_REVIEW")
                self.assertTrue(saved["human_review_required"])
                self.assertTrue(saved["audio_authorized"])
                self.assertIn("created_at", saved)
            store1.close()

            # Simulate backend restart: fresh IncidentStore on same DB + empty in-memory caches
            store2 = IncidentStore(db_path)
            try:
                reloaded = store2.get_incident(incident_id)
                self.assertIsNotNone(reloaded)
                self.assertEqual(reloaded["transcript"], "Sasapakin kita mamaya!")
                self.assertEqual(reloaded["confidence"]["avg_logprob"], -1.2)

                with (
                    patch.object(server, "incident_store", store2),
                    patch.object(server, "UNCERTAIN_REVIEW_AUDIO_DIR", review_dir),
                    patch.object(server, "recent_incidents", deque(maxlen=50)),
                    patch.object(server, "recent_uncertain_reviews", deque(maxlen=50)),
                    patch.object(server, "authorized_review_audio", {}),
                    patch.object(server, "broadcast_to_ui", AsyncMock()) as rev_bcast,
                ):
                    transport = httpx.ASGITransport(app=server.app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
                        # Authorized review audio works even after in-memory cache cleared
                        r_aud = await client.get(review_url)
                        self.assertEqual(r_aud.status_code, 200)
                        r_aud_bad = await client.get(f"/api/review/audio/{incident_id}?token=bad")
                        self.assertEqual(r_aud_bad.status_code, 401)

                        r_list = await client.get("/api/incidents")
                        self.assertEqual(r_list.status_code, 200)
                        self.assertEqual(r_list.json()["count"], 1)

                        r_one = await client.get(f"/api/incidents/{incident_id}")
                        self.assertEqual(r_one.status_code, 200)

                        # Invalid review status -> 400
                        r_bad = await client.post(
                            f"/api/incidents/{incident_id}/review",
                            json={"review_status": "BOGUS"},
                        )
                        self.assertEqual(r_bad.status_code, 400)

                        # Unknown incident -> 404
                        r_miss = await client.post(
                            "/api/incidents/EVT-NOPE/review",
                            json={"review_status": "CONFIRMED"},
                        )
                        self.assertEqual(r_miss.status_code, 404)

                        # Confirm then dismiss
                        r_conf = await client.post(
                            f"/api/incidents/{incident_id}/review",
                            json={
                                "review_status": "CONFIRMED",
                                "reviewer_notes": "Verified hallway threat",
                                "reviewed_by": "Counselor Ana",
                            },
                        )
                        self.assertEqual(r_conf.status_code, 200)
                        conf_inc = r_conf.json()["incident"]
                        self.assertEqual(conf_inc["review_status"], "CONFIRMED")
                        self.assertEqual(conf_inc["reviewer_notes"], "Verified hallway threat")
                        self.assertEqual(conf_inc["reviewed_by"], "Counselor Ana")
                        self.assertIsNotNone(conf_inc["reviewed_at"])
                        self.assertFalse(conf_inc["human_review_required"])
                        rev_bcast.assert_awaited()

                        r_dis = await client.post(
                            f"/api/incidents/{incident_id}/review",
                            json={"review_status": "DISMISSED", "reviewer_notes": "False alarm"},
                        )
                        self.assertEqual(r_dis.status_code, 200)
                        self.assertEqual(r_dis.json()["incident"]["review_status"], "DISMISSED")
            finally:
                store2.close()


if __name__ == "__main__":
    unittest.main()

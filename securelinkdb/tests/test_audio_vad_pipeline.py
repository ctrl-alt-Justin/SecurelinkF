import unittest
from unittest.mock import MagicMock
import numpy as np
import time

from securelinkdb.usb_manager import USBDeviceManager

class TestAudioVADPipeline(unittest.TestCase):
    def setUp(self):
        self.mgr = USBDeviceManager()
        self.mgr.current_port_name = "COM4"

    def test_authoritative_vad_arming(self):
        # 1. Initially offline: VAD must NOT be armed
        self.assertFalse(self.mgr.is_vad_armed)
        self.assertIn("closed", self.mgr.vad_status_reason.lower())

        # 2. Mock serial open & authenticated, before first SL:PING
        mock_serial = MagicMock()
        mock_serial.is_open = True
        self.mgr.serial_port = mock_serial
        self.mgr.is_authenticated = True
        self.mgr.last_heartbeat_ts = time.time()
        self.mgr.vad_state = "VAD ARMED"
        self.mgr.mic_initialized = False

        self.assertFalse(self.mgr.is_vad_armed)
        self.assertIn("awaiting initial hardware telemetry", self.mgr.vad_status_reason.lower())

        # 2b. Heartbeat received, but mic failed initialization
        self.mgr.heartbeat_received_count = 1
        self.assertFalse(self.mgr.is_vad_armed)
        self.assertIn("microphone", self.mgr.vad_status_reason.lower())

        # 3. Mic initialized, but VAD init failed
        self.mgr.mic_initialized = True
        self.mgr.vad_initialized = False
        self.assertFalse(self.mgr.is_vad_armed)
        self.assertIn("vad", self.mgr.vad_status_reason.lower())

        # 4. Fully initialized and armed
        self.mgr.vad_initialized = True
        self.assertTrue(self.mgr.is_vad_armed)
        self.assertIn("vad armed", self.mgr.vad_status_reason.lower())

    def test_unexpected_disarm_during_heartbeat_prevented(self):
        # Ensure benign heartbeat does NOT disarm a healthy VAD
        mock_serial = MagicMock()
        mock_serial.is_open = True
        self.mgr.serial_port = mock_serial
        self.mgr.is_authenticated = True
        self.mgr.last_heartbeat_ts = time.time()
        self.mgr.mic_initialized = True
        self.mgr.vad_initialized = True
        self.mgr.vad_state = "VAD ARMED"

        self.assertTrue(self.mgr.is_vad_armed)

        # Receive standard heartbeat ping
        ping_line = "SL:PING:95:4100:VAD ARMED:1:1:1200:150:OPERATIONAL"
        self.mgr._handle_command(ping_line)

        self.assertTrue(self.mgr.is_vad_armed)
        self.assertFalse(self.mgr.vad_explicitly_disarmed)
        self.assertEqual(self.mgr.vad_state, "VAD ARMED")

    def test_explicit_disarm_and_rearm_lifecycle(self):
        mock_serial = MagicMock()
        mock_serial.is_open = True
        self.mgr.serial_port = mock_serial
        self.mgr.is_authenticated = True
        self.mgr.last_heartbeat_ts = time.time()
        self.mgr.mic_initialized = True
        self.mgr.vad_initialized = True
        self.mgr.vad_state = "VAD ARMED"

        self.assertTrue(self.mgr.is_vad_armed)

        # 1. Trigger explicit disarm
        self.mgr.disarm_vad(reason="High ambient noise zone")
        self.assertFalse(self.mgr.is_vad_armed)
        self.assertTrue(self.mgr.vad_explicitly_disarmed)
        self.assertEqual(self.mgr.vad_state, "VAD DISARMED")
        self.assertIn("high ambient noise zone", self.mgr.vad_status_reason.lower())

        # 2. Firmware sends back SL:VAD:DISARMED
        self.mgr._handle_command("SL:VAD:DISARMED:High ambient noise zone")
        self.assertFalse(self.mgr.is_vad_armed)

        # 3. Explicit re-arm
        arm_ok = self.mgr.arm_vad()
        self.assertTrue(arm_ok)
        self.assertTrue(self.mgr.is_vad_armed)
        self.assertFalse(self.mgr.vad_explicitly_disarmed)
        self.assertEqual(self.mgr.vad_state, "VAD ARMED")

    def test_recovery_from_uninitialized_mic_or_vad(self):
        mock_serial = MagicMock()
        mock_serial.is_open = True
        self.mgr.serial_port = mock_serial
        self.mgr.is_authenticated = True
        self.mgr.last_heartbeat_ts = time.time()
        self.mgr.mic_initialized = False
        self.mgr.vad_initialized = False

        self.assertFalse(self.mgr.is_vad_armed)
        # Cannot arm when uninitialized
        self.assertFalse(self.mgr.arm_vad())

        # Recover audio VAD command issued
        rec_ok = self.mgr.recover_audio_vad()
        self.assertTrue(rec_ok)

        # Device reports successful recovery in next heartbeat ping
        self.mgr._handle_command("SL:PING:90:4020:VAD ARMED:1:1:50:110:OPERATIONAL")
        self.assertTrue(self.mgr.mic_initialized)
        self.assertTrue(self.mgr.vad_initialized)
        self.assertTrue(self.mgr.is_vad_armed)

    def test_disconnect_and_reconnect_preserves_safety(self):
        mock_serial = MagicMock()
        mock_serial.is_open = True
        self.mgr.serial_port = mock_serial
        self.mgr.is_authenticated = True
        self.mgr.device_id = "PIN-F360"
        self.mgr.last_heartbeat_ts = time.time()
        self.mgr.mic_initialized = True
        self.mgr.vad_initialized = True
        self.mgr.vad_state = "VAD ARMED"

        self.assertTrue(self.mgr.is_vad_armed)

        # Disconnect serial
        self.mgr._close_serial(reason="USB cable unplugged")
        self.assertFalse(self.mgr.is_vad_armed)
        self.assertEqual(self.mgr.vad_state, "OFFLINE")
        self.assertIn("unplugged", self.mgr.vad_disarm_reason.lower())

        # Reconnect
        mock_serial2 = MagicMock()
        mock_serial2.is_open = True
        self.mgr.serial_port = mock_serial2
        self.mgr.is_authenticated = True
        self.mgr.last_heartbeat_ts = time.time()
        self.mgr._handle_command("SL:PING:92:4050:VAD ARMED:1:1:200:140:OPERATIONAL")

        self.assertTrue(self.mgr.is_vad_armed)
        self.assertEqual(self.mgr.vad_state, "VAD ARMED")

    def test_dashboard_refresh_idempotent(self):
        # Multiple get_status calls do not alter or reset VAD state
        mock_serial = MagicMock()
        mock_serial.is_open = True
        self.mgr.serial_port = mock_serial
        self.mgr.is_authenticated = True
        self.mgr.last_heartbeat_ts = time.time()
        self.mgr.mic_initialized = True
        self.mgr.vad_initialized = True
        self.mgr.vad_state = "VAD ARMED"

        s1 = self.mgr.get_status()
        s2 = self.mgr.get_status()
        self.assertEqual(s1["vad_armed"], s2["vad_armed"])
        self.assertEqual(s1["stages"]["7_vad_armed"], s2["stages"]["7_vad_armed"])
        self.assertTrue(s1["stages"]["7_vad_armed"])

    def test_part9_idle_vs_step7_armed_distinction(self):
        # Step 7 must be True when armed, and Part 9 must be False when idle (not analyzing)
        mock_serial = MagicMock()
        mock_serial.is_open = True
        self.mgr.serial_port = mock_serial
        self.mgr.is_authenticated = True
        self.mgr.last_heartbeat_ts = time.time()
        self.mgr.mic_initialized = True
        self.mgr.vad_initialized = True
        self.mgr.vad_state = "VAD ARMED"
        self.mgr.audio_analyzing = False

        status = self.mgr.get_status()
        self.assertTrue(status["stages"]["7_vad_armed"])
        self.assertFalse(status["stages"]["9_audio_processing"])

        # When backend AI is analyzing audio
        self.mgr.audio_analyzing = True
        status2 = self.mgr.get_status()
        self.assertTrue(status2["stages"]["9_audio_processing"])

    def test_binary_audio_chunk_metrics_and_rms(self):
        mock_serial = MagicMock()
        mock_serial.is_open = True
        self.mgr.serial_port = mock_serial
        self.mgr.is_authenticated = True
        self.mgr.audio_streaming = True

        # Generate 16-bit PCM test tone (512 samples = 1024 bytes)
        t = np.linspace(0, 1, 512, endpoint=False)
        tone = (np.sin(2 * np.pi * 440 * t) * 5000).astype(np.int16)
        raw_bytes = tone.tobytes()

        self.mgr._handle_audio_chunk(1, raw_bytes)
        self.assertEqual(self.mgr.audio_chunks_received, 1)
        self.assertEqual(self.mgr.current_chunk_seq, 1)
        self.assertEqual(self.mgr.missing_chunks, 0)
        self.assertGreater(self.mgr.last_audio_peak, 0.1)
        self.assertGreater(self.mgr.last_audio_rms, 0.05)

        # Gap detection
        self.mgr._handle_audio_chunk(4, raw_bytes)
        self.assertEqual(self.mgr.audio_chunks_received, 2)
        self.assertEqual(self.mgr.current_chunk_seq, 4)
        self.assertEqual(self.mgr.missing_chunks, 2)

if __name__ == "__main__":
    unittest.main()

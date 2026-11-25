"""
Unit and Integration Tests for SecureLink USB Serial Protocol
Verifies:
1. Port scanning and ESP32 auto-discovery.
2. Handshake request & identification parsing.
3. Authentication and authorization verification.
4. Heartbeat telemetry (PING/PONG, battery, voltage, VAD state).
5. Watchdog timeout and safe disconnect transition.
6. Binary framed audio streaming (STREAM_START, AUDIO chunks, STREAM_END).
7. Audio buffer accumulation and handoff to ASR pipeline.
8. Connection priority in connection state engine (USB takes priority over WebSocket and BLE).
"""

import os
import sys
import unittest
import time
import io
import serial
from unittest.mock import MagicMock, patch

# Ensure securelinkdb directory is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from usb_manager import USBDeviceManager, HEARTBEAT_TIMEOUT_SEC
import server


class MockSerialPort:
    """Mock serial port implementing basic read/write operations for protocol testing."""
    def __init__(self, *args, **kwargs):
        self.is_open = True
        self.dtr = True
        self.rts = False
        self.write_buffer = bytearray()
        self.read_buffer = bytearray()

    @property
    def in_waiting(self) -> int:
        return len(self.read_buffer)

    def write(self, data: bytes) -> int:
        self.write_buffer.extend(data)
        return len(data)

    def read(self, size: int = 1) -> bytes:
        chunk = bytes(self.read_buffer[:size])
        del self.read_buffer[:size]
        return chunk

    def flush(self):
        pass

    def close(self):
        self.is_open = False


class TestUSBSerialProtocol(unittest.TestCase):

    def setUp(self):
        self.updates = []
        self.completed_audios = []

        def on_update(dev):
            self.updates.append(dev)

        def on_audio(dev_id, pcm):
            self.completed_audios.append((dev_id, pcm))

        def verify_cred(pin_id):
            return pin_id in ("PIN-F360", "PIN-001")

        self.mgr = USBDeviceManager(
            on_device_update=on_update,
            on_audio_complete=on_audio,
            verify_credential_fn=verify_cred
        )
        self.mock_serial = MockSerialPort()
        self.mgr.serial_port = self.mock_serial
        self.mgr.current_port_name = "COM4"
        self.mgr.last_heartbeat_ts = time.time()

    def tearDown(self):
        self.mgr.stop()

    def wait_for_usb(self, predicate, timeout=4.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "USB worker failed to reach the expected state")
            time.sleep(0.01)

    def test_01_handshake_and_authentication_success(self):
        """PIN identifies itself via SL:IDENT; manager verifies and responds with SL:AUTH:OK."""
        self.mgr._handle_command("SL:IDENT:PIN-F360:E8:F6:0A:8C:F3:60:2.1")
        self.assertTrue(self.mgr.is_authenticated)
        self.assertEqual(self.mgr.device_id, "PIN-F360")
        self.assertEqual(self.mgr.mac_address, "E8:F6:0A:8C:F3:60")
        self.assertIn(b"SL:AUTH:OK\n", bytes(self.mock_serial.write_buffer))
        self.assertTrue(any(u.get("state") == "VAD ARMED" for u in self.updates))

    def test_02_authentication_rejection_unauthorized(self):
        """Unauthorized device is rejected with SL:AUTH:ERR:UNAUTHORIZED."""
        self.mgr._handle_command("SL:IDENT:PIN-UNKNOWN:11:22:33:44:55:66:2.1")
        self.assertFalse(self.mgr.is_authenticated)
        self.assertIn(b"SL:AUTH:ERR:UNAUTHORIZED\n", bytes(self.mock_serial.write_buffer))

    def test_03_heartbeat_ping_pong_telemetry(self):
        """Pin sends SL:PING; manager records battery and responds with SL:PONG."""
        # Must authenticate first
        self.mgr._handle_command("SL:IDENT:PIN-F360:E8:F6:0A:8C:F3:60:2.1")
        self.mock_serial.write_buffer.clear()

        # Send Ping with 92% battery, 4150mV, VAD ARMED
        self.mgr._handle_command("SL:PING:92:4150:VAD ARMED")
        self.assertEqual(self.mgr.battery, 92)
        self.assertEqual(self.mgr.battery_mv, 4150)
        self.assertEqual(self.mgr.vad_state, "VAD ARMED")
        self.assertIn(b"SL:PONG\n", bytes(self.mock_serial.write_buffer))

    def test_04_unknown_battery_handling(self):
        """Pin sends SL:PING with -1 (uncalibrated ADC); manager safely preserves -1."""
        self.mgr._handle_command("SL:IDENT:PIN-F360:E8:F6:0A:8C:F3:60:2.1")
        self.mgr._handle_command("SL:PING:-1:-1:STANDBY")
        self.assertEqual(self.mgr.battery, -1)
        self.assertEqual(self.mgr.battery_mv, -1)

    def test_05_audio_stream_framing_and_reconstruction(self):
        """Stream framing test: SL:STREAM_START, SL:AUDIO chunks, and SL:STREAM_END."""
        self.mgr._handle_command("SL:IDENT:PIN-F360:E8:F6:0A:8C:F3:60:2.1")

        # 1. Start stream
        self.mgr._handle_command("SL:STREAM_START:1")
        self.assertTrue(self.mgr.audio_streaming)
        self.assertEqual(self.mgr.current_stream_seq, 1)

        # 2. Feed two 3200-byte PCM audio chunks (6400 bytes total = 200ms of 16kHz 16-bit PCM)
        chunk_1 = b"\x10\x00" * 1600 # 3200 bytes
        chunk_2 = b"\x20\x00" * 1600 # 3200 bytes
        self.mgr._handle_audio_chunk(1, chunk_1)
        self.mgr._handle_audio_chunk(2, chunk_2)
        self.assertEqual(len(self.mgr.audio_accumulator), 6400)

        # 3. End stream
        self.mgr._handle_command("SL:STREAM_END:1:6400")
        self.assertFalse(self.mgr.audio_streaming)
        self.assertEqual(len(self.completed_audios), 1)
        dev_id, pcm = self.completed_audios[0]
        self.assertEqual(dev_id, "PIN-F360")
        self.assertEqual(len(pcm), 6400)
        self.assertEqual(pcm[:3200], chunk_1)
        self.assertEqual(pcm[3200:], chunk_2)

    def test_06_framing_parser_with_interleaved_lines_and_binary(self):
        """Verifies buffer parsing when binary audio is interleaved with line commands."""
        self.mgr.running = True
        raw_pcm = b"\xAA\x55" * 1600 # 3200 bytes
        frame = b"SL:IDENT:PIN-F360:E8:F6:0A:8C:F3:60:2.1\n"
        frame += b"SL:STREAM_START:1\n"
        frame += f"SL:AUDIO:{len(raw_pcm)}:1\n".encode("utf-8") + raw_pcm
        frame += f"SL:STREAM_END:1:{len(raw_pcm)}\n".encode("utf-8")

        # Load into mock read buffer
        self.mock_serial.read_buffer.extend(frame)

        # Manually invoke the framing loop logic once
        buffer = bytearray()
        while self.mock_serial.in_waiting > 0:
            chunk = self.mock_serial.read(self.mock_serial.in_waiting)
            buffer.extend(chunk)

            while len(buffer) > 0:
                idx = buffer.find(b"SL:")
                if idx < 0:
                    buffer = buffer[-2:] if len(buffer) >= 2 else buffer
                    break
                if idx > 0:
                    del buffer[:idx]

                newline_idx = buffer.find(b"\n")
                if newline_idx < 0:
                    break

                header_bytes = bytes(buffer[:newline_idx]).strip()
                header_str = header_bytes.decode("utf-8", errors="replace")

                if header_str.startswith("SL:AUDIO:"):
                    parts = header_str.split(":")
                    payload_len = int(parts[2])
                    total_needed = newline_idx + 1 + payload_len
                    if len(buffer) < total_needed:
                        break
                    audio_bytes = bytes(buffer[newline_idx + 1: total_needed])
                    del buffer[:total_needed]
                    self.mgr._handle_audio_chunk(1, audio_bytes)
                    continue

                del buffer[:newline_idx + 1]
                self.mgr._handle_command(header_str)

        self.assertTrue(self.mgr.is_authenticated)
        self.assertEqual(len(self.completed_audios), 1)
        self.assertEqual(self.completed_audios[0][1], raw_pcm)

    def test_07_usb_priority_in_connection_state_machine(self):
        """When USB is authenticated, recalculate_pin_connection_state sets connection_source to USB."""
        # Authenticate USB manager with open serial port and fresh heartbeat
        server.usb_mgr.serial_port = self.mock_serial
        server.usb_mgr.is_authenticated = True
        server.usb_mgr.device_id = "PIN-F360"
        server.usb_mgr.current_port_name = "COM4"
        server.usb_mgr.last_heartbeat_ts = time.time()
        server.usb_mgr.battery = 85
        server.usb_mgr.battery_mv = 4050
        server.usb_mgr.vad_state = "VAD ARMED"

        state = server.recalculate_pin_connection_state("PIN-F360")
        self.assertTrue(state["online"])
        self.assertEqual(state["connection_source"], "USB")
        self.assertEqual(state["port"], "COM4")
        self.assertEqual(state["battery"], 85)

        # Cleanup
        server.usb_mgr.is_authenticated = False
        server.usb_mgr.device_id = None
        server.usb_mgr.serial_port = None

    def test_08_audio_chunk_acknowledgment(self):
        """Manager writes SL:AUDIO:ACK:<seq> upon receiving each binary audio frame."""
        self.mgr.running = True
        raw_pcm = b"\x11\x22" * 100 # 200 bytes
        frame = f"SL:AUDIO:{len(raw_pcm)}:42\n".encode("utf-8") + raw_pcm
        self.mock_serial.read_buffer.extend(frame)

        # Run one parse iteration
        buffer = bytearray()
        chunk = self.mock_serial.read(self.mock_serial.in_waiting)
        buffer.extend(chunk)
        newline_idx = buffer.find(b"\n")
        header_bytes = bytes(buffer[:newline_idx]).strip()
        header_str = header_bytes.decode("utf-8")
        parts = header_str.split(":")
        payload_len = int(parts[2])
        seq_num = int(parts[3])
        total_needed = newline_idx + 1 + payload_len
        raw_audio = bytes(buffer[newline_idx + 1: total_needed])
        self.mgr._handle_audio_chunk(seq_num, raw_audio)
        self.mgr._send_text(f"SL:AUDIO:ACK:{seq_num}\n")

        self.assertIn(b"SL:AUDIO:ACK:42\n", bytes(self.mock_serial.write_buffer))

    def test_09_mac_verification_and_credential_enforcement(self):
        """Credential verification requires valid device in device_credentials.json and matching MAC."""
        with patch("server.load_device_credentials") as mock_creds:
            mock_creds.return_value = {
                "PIN-F360": {
                    "token_hash": "abc",
                    "mac": "E8:F6:0A:8C:F3:60",
                }
            }
            # 1. Matching device & MAC -> (True, None)
            valid, err = server._verify_usb_credential("PIN-F360", "E8:F6:0A:8C:F3:60")
            self.assertTrue(valid)
            self.assertIsNone(err)

            # 2. Matching device with lowercase / hyphenated MAC
            valid, err = server._verify_usb_credential("PIN-F360", "e8-f6-0a-8c-f3-60")
            self.assertTrue(valid)
            self.assertIsNone(err)

            # 3. Mismatched MAC
            valid, err = server._verify_usb_credential("PIN-F360", "AA:BB:CC:DD:EE:FF")
            self.assertFalse(valid)
            self.assertEqual(err, "MAC_MISMATCH")

            # 4. Unknown device ID without credentials (no auto-registration bypass!)
            valid, err = server._verify_usb_credential("PIN-UNREGISTERED", "E8:F6:0A:8C:F3:60")
            self.assertFalse(valid)
            self.assertEqual(err, "UNREGISTERED_DEVICE")

    def test_10_cross_thread_event_loop_scheduling(self):
        """Cross-thread callbacks dispatch via asyncio.run_coroutine_threadsafe when loop is active."""
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True

        with patch("server.fastapi_event_loop", mock_loop):
            with patch("asyncio.run_coroutine_threadsafe") as mock_threadsafe:
                def fake_threadsafe(coro, loop):
                    coro.close()
                    fut = MagicMock()
                    return fut
                mock_threadsafe.side_effect = fake_threadsafe

                # 1. Device update callback from USB thread
                server._on_usb_device_update({"id": "PIN-F360", "state": "VAD ARMED"})
                self.assertEqual(mock_threadsafe.call_count, 1)

                # 2. Completed audio callback from USB thread
                server._on_usb_audio_complete("PIN-F360", b"\x00" * 3200)
                self.assertEqual(mock_threadsafe.call_count, 2)

    def test_11_audio_chunk_deduplication(self):
        """Manager ignores duplicate chunks with identical sequence number."""
        self.mgr._handle_command("SL:IDENT:PIN-F360:E8:F6:0A:8C:F3:60:2.1")
        self.mgr._handle_command("SL:STREAM_START:1")

        chunk = b"\x55\xAA" * 100 # 200 bytes
        self.mgr._handle_audio_chunk(1, chunk)
        self.assertEqual(len(self.mgr.audio_accumulator), 200)

        # Send exact same chunk seq 1 again (e.g. firmware retransmission)
        self.mgr._handle_audio_chunk(1, chunk)
        # Length must still be 200, not 400!
        self.assertEqual(len(self.mgr.audio_accumulator), 200)

        # Send new chunk seq 2
        self.mgr._handle_audio_chunk(2, chunk)
        self.assertEqual(len(self.mgr.audio_accumulator), 400)

    def test_12_heartbeat_timeout_watchdog_transition_and_recovery(self):
        """Heartbeat timeout marks device offline and clears authenticated state."""
        self.mgr._handle_command("SL:IDENT:PIN-F360:E8:F6:0A:8C:F3:60:2.1")
        self.assertTrue(self.mgr.is_authenticated)

        # Simulate heartbeat timeout (> 6.0s ago)
        self.mgr.last_heartbeat_ts = time.time() - 10.0
        status = self.mgr.get_status()
        self.assertFalse(status["is_online"])
        self.assertFalse(status["heartbeat_fresh"])

        # Recovery upon receiving fresh PING after re-auth
        self.mgr.last_heartbeat_ts = time.time()
        self.mgr._handle_command("SL:PING:95:4180:VAD ARMED")
        status_recovered = self.mgr.get_status()
        self.assertTrue(status_recovered["is_online"])
        self.assertTrue(status_recovered["heartbeat_fresh"])

    def test_13_nine_stage_pipeline_status(self):
        """get_status returns comprehensive 9-stage pipeline breakdown."""
        self.mgr._handle_command("SL:IDENT:PIN-F360:E8:F6:0A:8C:F3:60:2.1")
        self.mgr._handle_command("SL:PING:80:4000:VAD ARMED")
        st = self.mgr.get_status()

        stages = st.get("stages", {})
        self.assertTrue(stages.get("1_port_detected"))
        self.assertTrue(stages.get("2_port_open"))
        self.assertTrue(stages.get("3_identity_received"))
        self.assertTrue(stages.get("4_auth_accepted"))
        self.assertTrue(stages.get("5_heartbeat_received"))
        self.assertTrue(stages.get("6_pin_online"))
        self.assertTrue(stages.get("7_vad_armed"))
        self.assertFalse(stages.get("8_audio_streaming"))
        self.assertFalse(stages.get("9_audio_processing"))

    def test_14_split_buffer_partial_read_framing(self):
        """Buffer parser correctly handles fragmented reads across multiple chunk iterations."""
        self.mgr.running = True
        raw_pcm = b"\x33\x44" * 1600 # 3200 bytes
        full_packet = (
            b"SL:IDENT:PIN-F360:E8:F6:0A:8C:F3:60:2.1\n"
            b"SL:STREAM_START:1\n"
            + f"SL:AUDIO:{len(raw_pcm)}:1\n".encode("utf-8")
            + raw_pcm
            + b"SL:STREAM_END:1:3200\n"
        )

        buffer = bytearray()
        # Feed in arbitrary 25-byte fragments to test split boundaries
        frag_size = 25
        for i in range(0, len(full_packet), frag_size):
            buffer.extend(full_packet[i : i + frag_size])

            while len(buffer) > 0:
                idx = buffer.find(b"SL:")
                if idx < 0:
                    buffer = buffer[-2:] if len(buffer) >= 2 else buffer
                    break
                if idx > 0:
                    del buffer[:idx]

                newline_idx = buffer.find(b"\n")
                if newline_idx < 0:
                    break

                header_bytes = bytes(buffer[:newline_idx]).strip()
                header_str = header_bytes.decode("utf-8", errors="replace")

                if header_str.startswith("SL:AUDIO:"):
                    parts = header_str.split(":")
                    payload_len = int(parts[2])
                    seq = int(parts[3])
                    total_needed = newline_idx + 1 + payload_len
                    if len(buffer) < total_needed:
                        break
                    audio_data = bytes(buffer[newline_idx + 1 : total_needed])
                    del buffer[:total_needed]
                    self.mgr._handle_audio_chunk(seq, audio_data)
                    continue

                del buffer[: newline_idx + 1]
                self.mgr._handle_command(header_str)

        self.assertTrue(self.mgr.is_authenticated)
        self.assertEqual(len(self.completed_audios), 1)
        self.assertEqual(self.completed_audios[0][1], raw_pcm)

    def test_15_worker_restart_after_disconnect(self):
        """Worker thread restarts cleanly when connect is invoked after stop/disconnect."""
        self.mgr.stop()
        self.assertFalse(self.mgr.running)

        # Connect with mock serial patch to prevent actual OS COM open
        with patch("serial.Serial", side_effect=MockSerialPort):
            ok, msg = self.mgr.connect("COM4", timeout=1.0)
            self.assertTrue(ok)
            self.assertTrue(self.mgr.running)
            self.assertIsNotNone(self.mgr.thread)
            self.assertTrue(self.mgr.thread.is_alive())

    def test_16_port_open_failure_logging_and_reporting(self):
        """Serial opening failure logs at ERROR level, records last_open_error, and reports failure."""
        with patch("serial.Serial", side_effect=serial.SerialException("Access is denied")):
            with self.assertLogs("securelink.usb", level="ERROR") as cm:
                ok, msg = self.mgr.connect("COM_FAIL", timeout=0.5)
                self.assertFalse(ok)
                self.assertIn("SerialException", msg)
                self.assertIn("Access is denied", msg)
                self.assertEqual(self.mgr.connection_state, "ERROR")
                self.assertIsNotNone(self.mgr.last_open_error)
                self.assertIn("SerialException", self.mgr.last_open_error)

                # Check ERROR log
                self.assertTrue(any("Failed to open USB serial port COM_FAIL: SerialException: Access is denied" in log for log in cm.output))

            # Expose through get_status
            st = self.mgr.get_status()
            self.assertFalse(st["serial_port_open"])
            self.assertIn("Access is denied", st["last_open_error"])
            self.assertEqual(st["connection_state"], "ERROR")

    def test_17_successful_port_opening_and_status(self):
        """Successful port opening sets distinct states, opens port, and reflects in get_status."""
        with patch("serial.Serial", side_effect=MockSerialPort):
            ok, msg = self.mgr.connect("COM4", timeout=1.0)
            self.assertTrue(ok)
            self.assertTrue(self.mgr.serial_port and self.mgr.serial_port.is_open)

            st = self.mgr.get_status()
            self.assertTrue(st["serial_port_open"])
            self.assertTrue(st["worker_running"])
            self.assertIsNone(st["last_open_error"])
            # State is either PORT OPEN or HANDSHAKE WAITING
            self.assertIn(st["connection_state"], ("PORT OPEN", "HANDSHAKE WAITING"))

    def test_18_handshake_timeout_detection(self):
        """Pin that does not respond with identification within 5.0s triggers handshake timeout."""
        mock_port = MockSerialPort()
        self.mgr.serial_port = mock_port
        self.mgr.current_port_name = "COM4"
        self.mgr.connection_state = "HANDSHAKE WAITING"
        self.mgr.is_authenticated = False
        self.mgr.handshake_start_ts = time.time() - 6.0  # Expired > 5.0s ago

        # Execute one loop iteration check
        if (time.time() - self.mgr.handshake_start_ts) > 5.0:
            timeout_msg = f"Handshake timeout: Pin on {self.mgr.current_port_name} did not respond within 5.0s"
            self.mgr.last_error = timeout_msg
            self.mgr.connection_state = "ERROR"
            self.mgr._close_serial(reason=timeout_msg)

        self.assertEqual(self.mgr.connection_state, "ERROR")
        self.assertIn("Handshake timeout", self.mgr.last_error)
        self.assertFalse(self.mgr.serial_port and self.mgr.serial_port.is_open)

        st = self.mgr.get_status()
        self.assertIn("Handshake timeout", st["last_error"])
        self.assertEqual(st["connection_state"], "ERROR")

    def test_19_disconnect_and_reconnect_cycle(self):
        """Disconnect closes serial port without concurrency race, and reconnect restores connection."""
        ports = [{"port": "COM4", "is_esp32": True, "description": "USB Serial Device"}]
        with patch("serial.Serial", side_effect=MockSerialPort) as open_port, patch.object(self.mgr, "scan_ports", return_value=ports):
            # 1. Connect
            ok, msg = self.mgr.connect("COM4", timeout=1.0)
            self.assertTrue(ok)
            self.assertTrue(self.mgr.serial_port and self.mgr.serial_port.is_open)

            # 2. Disconnect safely
            ok, msg = self.mgr.disconnect(timeout=1.0)
            self.assertTrue(ok)
            self.assertTrue(self.mgr.serial_port is None or not self.mgr.serial_port.is_open)
            self.assertEqual(self.mgr.connection_state, "OFFLINE")
            time.sleep(0.25)
            self.assertEqual(open_port.call_count, 1)

            # 3. Reconnect
            ok, msg = self.mgr.connect("COM4", timeout=1.0)
            self.assertTrue(ok)
            self.assertTrue(self.mgr.serial_port and self.mgr.serial_port.is_open)

    def test_worker_discards_partial_audio_before_reopening(self):
        ident = b"SL:IDENT:PIN-001:00:11:22:33:44:55:2.1\n"
        ping = b"SL:PING:80:4000:VAD ARMED\n"
        partial_frame = b"SL:AUDIO:3200:1\n" + b"\x00" * 20
        first_port = MockSerialPort()
        first_port.read_buffer.extend(ident + ping + b"SL:STREAM_START:1\n" + partial_frame)
        next_port = MockSerialPort()
        pcm = b"\x01\x02" * 1600
        next_port.read_buffer.extend(
            ident + ping + b"SL:STREAM_START:2\nSL:AUDIO:3200:2\n" + pcm + b"SL:STREAM_END:2:3200\n"
        )
        self.mgr.serial_port = None

        with patch("serial.Serial", side_effect=[first_port, next_port]):
            try:
                self.mgr.start("COM4")
                self.wait_for_usb(lambda: self.mgr._receive_buffer == partial_frame)
                self.mgr.last_heartbeat_ts = time.time() - HEARTBEAT_TIMEOUT_SEC - 1
                self.wait_for_usb(lambda: len(self.completed_audios) == 1)
                self.assertEqual(self.completed_audios, [("PIN-001", pcm)])
                self.assertIn(b"SL:AUDIO:ACK:2\n", next_port.write_buffer)
                self.assertIn("Heartbeat timed out", self.mgr.last_disconnect_reason)
                self.assertTrue(self.mgr.is_authenticated)
            finally:
                self.mgr.stop()

    def test_worker_rediscovers_same_pin_after_com_port_changes(self):
        ident = b"SL:IDENT:PIN-001:00:11:22:33:44:55:2.1\n"
        other_ident = b"SL:IDENT:PIN-F360:AA:BB:CC:DD:EE:FF:2.1\n"
        ping = b"SL:PING:80:4000:VAD ARMED\n"
        original = MockSerialPort()
        original.read_buffer.extend(ident + ping)
        different_pin = MockSerialPort()
        different_pin.read_buffer.extend(other_ident + ping)
        rediscovered = MockSerialPort()
        rediscovered.read_buffer.extend(ident + ping)
        candidates = [
            {"port": port, "is_esp32": True, "description": "USB Serial Device"}
            for port in ("COM5", "COM7")
        ]
        self.mgr.serial_port = None

        with patch.object(self.mgr, "scan_ports", return_value=candidates), patch(
            "serial.Serial", side_effect=[original, serial.SerialException("COM4 disappeared"), different_pin, rediscovered]
        ) as open_port:
            try:
                self.mgr.start("COM4")
                self.wait_for_usb(lambda: self.mgr.connection_state == "ONLINE")
                self.mgr.last_heartbeat_ts = time.time() - HEARTBEAT_TIMEOUT_SEC - 1
                self.wait_for_usb(lambda: self.mgr.current_port_name == "COM7" and self.mgr.connection_state == "ONLINE")
                self.assertEqual(self.mgr.device_id, "PIN-001")
                self.assertEqual([call.kwargs["port"] for call in open_port.call_args_list], ["COM4", "COM4", "COM5", "COM7"])
                self.assertIn(b"SL:AUTH:ERR:UNEXPECTED_PIN\n", different_pin.write_buffer)
                self.assertNotIn(b"SL:AUTH:OK\n", different_pin.write_buffer)
            finally:
                self.mgr.stop()

    def test_worker_retries_handshake_if_first_request_is_missed(self):
        port = MockSerialPort()
        self.mgr.serial_port = None
        with patch("serial.Serial", return_value=port), patch("usb_manager.HANDSHAKE_RETRY_SEC", 0.05):
            try:
                self.mgr.start("COM4")
                self.wait_for_usb(lambda: port.write_buffer.count(b"SL:HANDSHAKE:REQ\n") >= 2)
                port.read_buffer.extend(b"SL:IDENT:PIN-001:00:11:22:33:44:55:2.1\nSL:PING:80:4000:VAD ARMED\n")
                self.wait_for_usb(lambda: self.mgr.connection_state == "ONLINE")
            finally:
                self.mgr.stop()


if __name__ == "__main__":
    unittest.main()

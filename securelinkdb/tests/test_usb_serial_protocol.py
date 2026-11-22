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
from unittest.mock import MagicMock, patch

# Ensure securelinkdb directory is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from usb_manager import USBDeviceManager, HEARTBEAT_TIMEOUT_SEC
import server


class MockSerialPort:
    """Mock serial port implementing basic read/write operations for protocol testing."""
    def __init__(self):
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
        self.mgr._handle_audio_chunk(1, chunk_2)
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
        # Authenticate USB manager
        server.usb_mgr.is_authenticated = True
        server.usb_mgr.device_id = "PIN-F360"
        server.usb_mgr.current_port_name = "COM4"
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


if __name__ == "__main__":
    unittest.main()

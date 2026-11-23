"""
SecureLink USB Serial Device Manager
Direct USB connection between XIAO ESP32-S3 Sense and SecureLink Central System.
Handles port discovery, handshake, authentication, heartbeats, and binary-framed audio streaming.
"""

import os
import sys
import time
import json
import logging
import threading
import queue
from typing import Optional, Callable, Dict, Any, List
import serial
import serial.tools.list_ports

logger = logging.getLogger("securelink.usb")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[USB-SERIAL] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Protocol Constants
SL_PREFIX = b"SL:"
SL_MAGIC = "SL:"
HEARTBEAT_TIMEOUT_SEC = 6.0
DEFAULT_BAUD = 115200

# ESP32-S3 USB CDC identifiers
ESP32S3_VID_PID = ("303A", "1001")

# Calibrated non-linear discharge curve for standard 3.7V LiPo cell
# Matches ESP32 firmware LIPO_CALIBRATION_CURVE
LIPO_DISCHARGE_TABLE = [
    (4200, 100),
    (4150, 95),
    (4110, 90),
    (4080, 85),
    (4020, 80),
    (3980, 75),
    (3950, 70),
    (3910, 65),
    (3870, 60),
    (3850, 55),
    (3840, 50),
    (3820, 45),
    (3800, 40),
    (3790, 35),
    (3770, 30),
    (3750, 25),
    (3730, 20),
    (3710, 15),
    (3690, 10),
    (3610, 5),
    (3400, 1),
    (3270, 0),
]


def calculate_lipo_percentage(voltage_mv: int) -> int:
    """Calculates non-linear 1S LiPo percentage from millivolts (3270mV = 0%, 4200mV = 100%).
    Returns -1 if voltage is outside the valid LiPo operating window (2800mV - 4400mV).
    """
    if voltage_mv < 2800 or voltage_mv > 4400:
        return -1
    if voltage_mv >= 4200:
        return 100
    if voltage_mv <= 3270:
        return 0
    for i in range(len(LIPO_DISCHARGE_TABLE) - 1):
        v_high, p_high = LIPO_DISCHARGE_TABLE[i]
        v_low, p_low = LIPO_DISCHARGE_TABLE[i + 1]
        if v_low <= voltage_mv <= v_high:
            pct = p_low + int(((voltage_mv - v_low) * (p_high - p_low)) / (v_high - v_low))
            return max(0, min(100, pct))
    return 0


class USBDeviceManager:
    def __init__(
        self,
        on_device_update: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_audio_complete: Optional[Callable[[str, bytes], None]] = None,
        verify_credential_fn: Optional[Callable[[str], bool]] = None,
    ):
        self.on_device_update = on_device_update
        self.on_audio_complete = on_audio_complete
        self.verify_credential_fn = verify_credential_fn

        self.serial_port: Optional[serial.Serial] = None
        self.current_port_name: Optional[str] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

        # Connected Pin State
        self.device_id: Optional[str] = None
        self.mac_address: Optional[str] = None
        self.fw_version: Optional[str] = None
        self.is_authenticated = False
        self.auth_error_reason: Optional[str] = None
        self.last_heartbeat_ts: float = 0.0
        self.battery: int = -1
        self.battery_mv: int = -1
        self.vad_state: str = "OFFLINE"
        self.audio_streaming: bool = False
        self.audio_accumulator = bytearray()
        self.seen_chunk_seqs: set = set()
        self.current_stream_seq: int = 0

        # Connection Lifecycle & Error States
        # States: "OFFLINE", "REQUESTED", "OPENING PORT", "PORT OPEN", "HANDSHAKE WAITING", "AUTHENTICATED", "ONLINE", "ERROR"
        self.connection_state: str = "OFFLINE"
        self.last_open_error: Optional[str] = None
        self.last_error: Optional[str] = None
        self.handshake_start_ts: float = 0.0
        self.pending_port_request: Optional[str] = None
        self.pending_disconnect_request: bool = False
        self.port_event = threading.Event()
        self.disconnect_event = threading.Event()

        # Auto-reconnect configuration
        self.auto_reconnect = True
        self.auto_discovery = True

    @property
    def battery_valid(self) -> bool:
        """Returns True if a valid physical battery sensor reading is present (2800-4400mV)."""
        return self.battery >= 0 and (2800 <= self.battery_mv <= 4400)

    @property
    def battery_status(self) -> str:
        """Returns human-readable battery telemetry status code."""
        if self.battery_valid:
            return "VALID"
        return "UNAVAILABLE"

    def scan_ports(self) -> List[Dict[str, str]]:
        """Scans all available COM ports and flags likely XIAO ESP32-S3 Sense devices."""
        results = []
        for p in serial.tools.list_ports.comports():
            is_esp32 = False
            hwid_upper = (p.hwid or "").upper()
            if "303A:1001" in hwid_upper:
                is_esp32 = True
            elif "ESP32" in (p.description or "").upper():
                is_esp32 = True
            elif "USB SERIAL" in (p.description or "").upper() and p.vid == 0x303A:
                is_esp32 = True

            results.append({
                "port": p.device,
                "description": p.description or "Serial Port",
                "hwid": p.hwid or "",
                "is_esp32": is_esp32,
            })
        return results

    def find_pin_port(self) -> Optional[str]:
        """Automatically discovers the port of a connected XIAO ESP32-S3."""
        ports = self.scan_ports()
        # 1. Prefer matching VID:PID 303A:1001
        for p in ports:
            if p["is_esp32"]:
                return p["port"]
        # 2. If exactly one USB Serial port exists, candidate it
        usb_serial_ports = [p["port"] for p in ports if "USB SERIAL" in p["description"].upper()]
        if len(usb_serial_ports) == 1:
            return usb_serial_ports[0]
        return None

    def start(self, port: Optional[str] = None):
        """Starts the USB reader thread."""
        with self.lock:
            if self.running:
                return
            self.running = True
            self.current_port_name = port
            self.thread = threading.Thread(target=self._run_loop, daemon=True, name="USBSerialReader")
            self.thread.start()
            logger.info("USB Device Manager worker thread started.")

    def stop(self):
        """Stops the USB reader thread and closes any open port."""
        self.running = False
        self.port_event.set()
        self.disconnect_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        with self.lock:
            self._close_serial(reason="Stopped")
            self.connection_state = "OFFLINE"
        logger.info("USB Device Manager stopped.")

    def _close_serial(self, reason: str = "Disconnected"):
        if self.serial_port:
            try:
                self.serial_port.close()
            except Exception:
                pass
            self.serial_port = None
        if self.is_authenticated or self.device_id:
            self._mark_disconnected(reason=reason)
        elif self.connection_state != "ERROR":
            self.connection_state = "OFFLINE"

    def _mark_disconnected(self, reason: str = "Disconnected"):
        old_id = self.device_id
        self.is_authenticated = False
        self.vad_state = "OFFLINE"
        self.audio_streaming = False
        self.audio_accumulator.clear()
        self.seen_chunk_seqs.clear()
        if self.connection_state != "ERROR":
            self.connection_state = "OFFLINE"
        dev_info = {
            "id": old_id or "PIN-USB",
            "online": False,
            "direct_online": False,
            "relay_online": False,
            "connection_source": "USB",
            "state": "OFFLINE",
            "lastSeen": f"{reason} at {time.strftime('%H:%M:%S')}",
            "battery": -1,
            "batteryMv": -1,
            "paired": True,
            "port": self.current_port_name or "None",
        }
        if self.on_device_update:
            try:
                self.on_device_update(dev_info)
            except Exception as e:
                logger.error(f"Error invoking on_device_update: {e}")
        logger.info(f"USB Device '{old_id}' marked OFFLINE ({reason}).")

    def connect(self, port: str, timeout: float = 3.0) -> tuple:
        """
        Manually requests connection to a specific port.
        Safely restarts the worker thread if stopped, delegates port opening
        to the worker thread, and waits up to timeout for the port to actually open.
        Returns (success: bool, message: str).
        """
        port = port.strip()
        with self.lock:
            self.last_open_error = None
            self.last_error = None
            self.connection_state = "REQUESTED"
            self.port_event.clear()
            self.pending_disconnect_request = False
            self.pending_port_request = port

            # 1. If worker thread is not running or thread dead, start/restart it
            if not self.running or self.thread is None or not self.thread.is_alive():
                self.running = True
                self.current_port_name = port
                self.thread = threading.Thread(target=self._run_loop, daemon=True, name="USBSerialReader")
                self.thread.start()
                logger.info(f"Started USB worker thread for port {port}")

        # 2. Wait for worker thread to attempt opening the port
        self.port_event.wait(timeout=timeout)

        with self.lock:
            if self.serial_port and self.serial_port.is_open:
                return True, f"Port {self.current_port_name} opened successfully"
            else:
                err = self.last_open_error or self.last_error or f"Failed to open port {port} within {timeout}s"
                return False, err

    def disconnect(self, timeout: float = 2.0) -> tuple:
        """
        Requests disconnection from the current serial port safely without
        modifying the handle concurrently from the calling thread.
        Returns (success: bool, message: str).
        """
        with self.lock:
            if not self.running or self.thread is None or not self.thread.is_alive():
                self._close_serial(reason="User disconnected")
                self.connection_state = "OFFLINE"
                return True, "Disconnected (worker was stopped)"

            self.disconnect_event.clear()
            self.pending_disconnect_request = True

        self.disconnect_event.wait(timeout=timeout)
        return True, "Disconnected"

    def _open_port(self, port_name: str) -> bool:
        try:
            self.connection_state = "OPENING PORT"
            ser = serial.Serial(
                port=port_name,
                baudrate=DEFAULT_BAUD,
                timeout=0.05,
                write_timeout=0.5,
            )
            # Toggle DTR/RTS properly for ESP32 CDC
            ser.dtr = True
            ser.rts = False
            self.serial_port = ser
            self.current_port_name = port_name
            self.last_open_error = None
            self.last_error = None
            self.last_heartbeat_ts = time.time()
            self.handshake_start_ts = time.time()
            self.connection_state = "PORT OPEN"
            logger.info(f"Opened USB serial port {port_name} at {DEFAULT_BAUD} baud.")
            # Transition to HANDSHAKE WAITING and send request
            self.connection_state = "HANDSHAKE WAITING"
            self._send_text("SL:HANDSHAKE:REQ\n")
            return True
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}"
            logger.error(f"Failed to open USB serial port {port_name}: {err_msg}")
            self.last_open_error = err_msg
            self.last_error = err_msg
            self.connection_state = "ERROR"
            self.serial_port = None
            return False

    def _send_text(self, text: str):
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(text.encode("utf-8"))
                self.serial_port.flush()
            except Exception as e:
                logger.error(f"Error sending text over USB: {e}")

    def _run_loop(self):
        """Background thread loop handling serial reads, framing, and watchdog."""
        buffer = bytearray()

        while self.running:
            # 1. Handle pending disconnect request from caller safely in worker thread
            if self.pending_disconnect_request:
                self._close_serial(reason="User requested disconnect")
                self.connection_state = "OFFLINE"
                self.current_port_name = None
                self.pending_disconnect_request = False
                self.disconnect_event.set()
                self.port_event.set()
                time.sleep(0.1)
                continue

            # 2. Handle pending port switch / connect request
            if self.pending_port_request is not None:
                target = self.pending_port_request
                self.pending_port_request = None
                if self.serial_port and self.serial_port.is_open:
                    self._close_serial(reason="Switching port")
                self.current_port_name = target
                self._open_port(target)
                self.port_event.set()
                if not self.serial_port:
                    time.sleep(0.5)
                    continue

            # 3. If port is not open, attempt auto-discovery or target port
            if not self.serial_port or not self.serial_port.is_open:
                target_port = self.current_port_name or (self.find_pin_port() if self.auto_discovery else None)
                if target_port:
                    self._open_port(target_port)
                    self.port_event.set()
                    if not self.serial_port:
                        time.sleep(1.0)
                        continue
                else:
                    self.port_event.set()
                    time.sleep(0.5)
                    continue

            # 4. Check handshake timeout (5.0s limit waiting for identification)
            if self.connection_state == "HANDSHAKE WAITING" and not self.is_authenticated:
                if (time.time() - self.handshake_start_ts) > 5.0:
                    timeout_msg = f"Handshake timeout: Pin on {self.current_port_name} did not respond within 5.0s"
                    logger.error(timeout_msg)
                    self.last_error = timeout_msg
                    self.connection_state = "ERROR"
                    self._close_serial(reason=timeout_msg)
                    continue

            # 5. Check heartbeat watchdog if authenticated
            if self.is_authenticated:
                if (time.time() - self.last_heartbeat_ts) > HEARTBEAT_TIMEOUT_SEC:
                    hb_msg = f"Heartbeat timed out for {self.device_id} (> {HEARTBEAT_TIMEOUT_SEC}s)"
                    logger.warning(f"{hb_msg}. Marking OFFLINE.")
                    self.last_error = hb_msg
                    self.connection_state = "ERROR"
                    self._close_serial(reason=hb_msg)
                    continue

            # 6. Read incoming bytes
            try:
                waiting = self.serial_port.in_waiting
                chunk = self.serial_port.read(waiting if waiting > 0 else 64)
                if chunk:
                    buffer.extend(chunk)
            except (serial.SerialException, OSError) as e:
                err_str = f"Serial port {self.current_port_name} error: {type(e).__name__}: {e}"
                logger.error(err_str)
                self.last_error = err_str
                self.connection_state = "ERROR"
                self._close_serial(reason=err_str)
                time.sleep(1.0)
                continue

            # 7. Parse framed protocol messages from buffer
            while len(buffer) > 0:
                # Find start prefix "SL:"
                idx = buffer.find(SL_PREFIX)
                if idx < 0:
                    # Keep at most last 2 bytes in case "SL:" was partially read
                    buffer = buffer[-2:] if len(buffer) >= 2 else buffer
                    break
                if idx > 0:
                    # Discard garbage before "SL:"
                    del buffer[:idx]

                # Look for line ending marking end of command header
                newline_idx = buffer.find(b"\n")
                if newline_idx < 0:
                    # Incomplete header, wait for more data (unless buffer exceeds 2KB)
                    if len(buffer) > 2048:
                        buffer.clear()
                    break

                header_bytes = bytes(buffer[:newline_idx]).strip()
                header_str = header_bytes.decode("utf-8", errors="replace")

                # Check if this is a binary audio frame header: SL:AUDIO:<len>:<seq>
                if header_str.startswith("SL:AUDIO:"):
                    parts = header_str.split(":")
                    if len(parts) >= 3:
                        try:
                            payload_len = int(parts[2])
                            seq_num = int(parts[3]) if len(parts) >= 4 else 0
                        except ValueError:
                            payload_len = -1

                        if payload_len > 0:
                            total_needed = newline_idx + 1 + payload_len
                            if len(buffer) < total_needed:
                                # Incomplete binary chunk; wait for remaining bytes
                                break

                            # Extract binary PCM data
                            raw_audio = bytes(buffer[newline_idx + 1 : total_needed])
                            del buffer[:total_needed]
                            self._handle_audio_chunk(seq_num, raw_audio)
                            self._send_text(f"SL:AUDIO:ACK:{seq_num}\n")
                            continue

                # Normal line-delimited message: consume header line
                del buffer[: newline_idx + 1]
                self._handle_command(header_str)

            time.sleep(0.005)

        # Worker thread exiting: safely close serial port
        self._close_serial(reason="Worker thread stopped")
        self.connection_state = "OFFLINE"

    def _handle_command(self, cmd_str: str):
        """Processes line-delimited command messages from ESP32."""
        parts = cmd_str.split(":")
        if len(parts) < 2 or parts[0] != "SL":
            return

        cmd = parts[1].strip()

        # 1. Identification / Handshake: SL:IDENT:<dev_id>:<mac>:<fw_ver>
        if cmd == "IDENT":
            dev_id = parts[2].strip().upper() if len(parts) >= 3 else "PIN-001"
            if len(parts) > 4:
                # MAC address contains colons (e.g. E8:F6:0A:8C:F3:60)
                fw = parts[-1].strip()
                mac = ":".join(parts[3:-1]).strip()
            elif len(parts) == 4:
                mac = parts[3].strip()
                fw = "2.1"
            else:
                mac = ""
                fw = "2.1"

            logger.info(f"Received identification from pin '{dev_id}' (MAC: {mac}, FW: {fw}).")
            self.device_id = dev_id
            self.mac_address = mac
            self.fw_version = fw

            # Verify authorization against credentials
            is_valid = True
            err_reason = None
            if self.verify_credential_fn:
                try:
                    import inspect
                    sig = inspect.signature(self.verify_credential_fn)
                    if len(sig.parameters) >= 2:
                        res = self.verify_credential_fn(dev_id, mac)
                    else:
                        res = self.verify_credential_fn(dev_id)
                    if isinstance(res, tuple):
                        is_valid, err_reason = res
                    else:
                        is_valid = bool(res)
                        err_reason = None if is_valid else "UNAUTHORIZED"
                except Exception as e:
                    logger.error(f"Credential check failed: {e}")
                    is_valid = False
                    err_reason = "AUTH_EXCEPTION"

            if is_valid:
                self.is_authenticated = True
                self.connection_state = "AUTHENTICATED"
                self.last_error = None
                self.auth_error_reason = None
                self.last_heartbeat_ts = time.time()
                self._send_text("SL:AUTH:OK\n")
                logger.info(f"Pin '{dev_id}' successfully authenticated over USB.")
                self._emit_device_update(state="VAD ARMED")
            else:
                self.is_authenticated = False
                self.connection_state = "ERROR"
                self.auth_error_reason = err_reason or "UNAUTHORIZED"
                self.last_error = f"Authentication rejected: {self.auth_error_reason}"
                self._send_text(f"SL:AUTH:ERR:{self.auth_error_reason}\n")
                logger.warning(f"Pin '{dev_id}' unauthorized ({self.auth_error_reason}). Authentication rejected.")

        # 2. Heartbeat Ping: SL:PING:<batt_pct>:<batt_mv>:<vad_state>
        elif cmd == "PING":
            if not self.is_authenticated:
                # Prompt pin to re-authenticate
                self._send_text("SL:HANDSHAKE:REQ\n")
                return

            self.last_heartbeat_ts = time.time()
            self.connection_state = "ONLINE"
            raw_b = -1
            raw_mv = -1
            if len(parts) >= 3:
                try:
                    raw_b = int(parts[2])
                except ValueError:
                    raw_b = -1
            if len(parts) >= 4:
                try:
                    raw_mv = int(parts[3])
                except ValueError:
                    raw_mv = -1

            # Validate physical battery voltage:
            # Standard 1S LiPo operating/charging range is 2800mV to 4400mV.
            # Voltage below 2800mV indicates floating ADC / missing voltage divider.
            if 2800 <= raw_mv <= 4400:
                self.battery_mv = raw_mv
                if 0 <= raw_b <= 100:
                    self.battery = raw_b
                else:
                    self.battery = calculate_lipo_percentage(raw_mv)
            else:
                self.battery_mv = -1
                self.battery = -1

            if len(parts) >= 5:
                self.vad_state = parts[4].strip()

            self._send_text("SL:PONG\n")
            if not self.audio_streaming:
                self._emit_device_update(state=self.vad_state or "VAD ARMED")

        # 3. Audio Stream Start: SL:STREAM_START:<seq>
        elif cmd in ("STREAM_START", "AUDIO_START"):
            seq = int(parts[2]) if len(parts) >= 3 else 0
            self.current_stream_seq = seq
            self.audio_streaming = True
            self.audio_accumulator.clear()
            self.seen_chunk_seqs.clear()
            logger.info(f"Audio stream #{seq} started over USB from '{self.device_id}'.")
            self._emit_device_update(state="STREAMING AUDIO (USB)")

        # 4. Audio Stream End: SL:STREAM_END:<seq>:<total_bytes>
        elif cmd in ("STREAM_END", "AUDIO_END"):
            seq = int(parts[2]) if len(parts) >= 3 else 0
            logger.info(f"Audio stream #{seq} finished over USB. Accumulated {len(self.audio_accumulator)} bytes.")
            self.audio_streaming = False
            self.seen_chunk_seqs.clear()
            pcm_data = bytes(self.audio_accumulator)
            self.audio_accumulator.clear()

            self._emit_device_update(state="ANALYZING SPEECH")

            if self.on_audio_complete and self.device_id and len(pcm_data) >= 3200:
                try:
                    self.on_audio_complete(self.device_id, pcm_data)
                except Exception as e:
                    logger.error(f"Error invoking on_audio_complete: {e}")

            # Return state to VAD ARMED
            self._emit_device_update(state="VAD ARMED")

        # 5. Diagnostic Log: SL:LOG:<message>
        elif cmd == "LOG":
            msg = ":".join(parts[2:])
            logger.debug(f"[PIN-FW] {msg}")

    def _handle_audio_chunk(self, seq: int, raw_bytes: bytes):
        """Appends verified binary PCM chunk to stream accumulator with deduplication."""
        self.last_heartbeat_ts = time.time()
        if seq in self.seen_chunk_seqs:
            logger.info(f"Duplicate audio chunk #{seq} ignored; re-acknowledging.")
            return
        self.seen_chunk_seqs.add(seq)
        self.audio_accumulator.extend(raw_bytes)
        if not self.audio_streaming:
            self.audio_streaming = True
            self._emit_device_update(state="STREAMING AUDIO (USB)")

    def _emit_device_update(self, state: str = "VAD ARMED"):
        """Emits unified device status dict to callback for dashboard and backend."""
        now_str = time.strftime("%H:%M:%S")
        runtime_str = "--"
        if self.battery >= 0:
            rem_mins = int((self.battery / 100.0) * 315)
            runtime_str = f"{rem_mins // 60}h {rem_mins % 60:02d}m"

        dev_dict = {
            "id": self.device_id or "PIN-001",
            "online": self.is_authenticated,
            "direct_online": self.is_authenticated,
            "relay_online": False,
            "connection_source": "USB",
            "state": state,
            "network": f"USB CDC ({self.current_port_name or 'COM'})",
            "lastSeen": f"Active via USB at {now_str}",
            "cpuMhz": 160,
            "rssi": -30,  # Direct USB cable is perfect link quality
            "estRuntime": runtime_str,
            "battery": self.battery,
            "batteryMv": self.battery_mv,
            "battery_valid": self.battery_valid,
            "battery_status": self.battery_status,
            "paired": True,
            "port": self.current_port_name,
            "fwVersion": self.fw_version or "2.1",
            "mac": self.mac_address or "",
        }

        if self.on_device_update:
            try:
                self.on_device_update(dev_dict)
            except Exception as e:
                logger.error(f"Error in on_device_update callback: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Returns live diagnostic summary of USB subsystem including 9-stage pipeline state."""
        now = time.time()
        port_open = bool(self.serial_port and self.serial_port.is_open)
        worker_running = bool(self.running and self.thread and self.thread.is_alive())
        heartbeat_fresh = (now - self.last_heartbeat_ts <= HEARTBEAT_TIMEOUT_SEC) if self.last_heartbeat_ts > 0 else False
        is_online = port_open and self.is_authenticated and heartbeat_fresh
        sec_since_heartbeat = round(now - self.last_heartbeat_ts, 1) if self.last_heartbeat_ts > 0 else -1.0

        available_ports = self.scan_ports()
        pin_candidate = any(p["is_esp32"] for p in available_ports) or (self.current_port_name is not None)

        effective_error = self.last_open_error or self.last_error or self.auth_error_reason

        return {
            "status": "connected" if is_online else ("connecting" if (self.connection_state in ("REQUESTED", "OPENING PORT", "PORT OPEN", "HANDSHAKE WAITING")) else "disconnected"),
            "connection_state": self.connection_state,
            "serial_port_open": port_open,
            "last_open_error": self.last_open_error,
            "last_error": effective_error,
            "worker_running": worker_running,
            "port": self.current_port_name,
            "device_id": self.device_id,
            "mac": self.mac_address,
            "fw_version": self.fw_version,
            "is_authenticated": self.is_authenticated,
            "auth_error": self.auth_error_reason,
            "is_online": is_online,
            "vad_state": self.vad_state,
            "audio_streaming": self.audio_streaming,
            "accumulated_bytes": len(self.audio_accumulator),
            "battery": self.battery,
            "battery_mv": self.battery_mv,
            "battery_valid": self.battery_valid,
            "battery_status": self.battery_status,
            "heartbeat_fresh": heartbeat_fresh,
            "last_heartbeat_sec_ago": sec_since_heartbeat,
            # 9-stage pipeline diagnostics
            "stages": {
                "1_port_detected": pin_candidate,
                "2_port_open": port_open,
                "3_identity_received": bool(self.device_id),
                "4_auth_accepted": self.is_authenticated,
                "5_heartbeat_received": self.last_heartbeat_ts > 0,
                "6_pin_online": is_online,
                "7_vad_armed": self.vad_state == "VAD ARMED" and is_online,
                "8_audio_streaming": self.audio_streaming,
                "9_audio_processing": self.vad_state == "ANALYZING SPEECH",
            },
            "available_ports": available_ports,
        }

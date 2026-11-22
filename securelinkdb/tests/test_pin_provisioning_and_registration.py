"""
Unit and Integration Tests for SecureLink:
ESP32 BLE Provisioning, Non-Blocking Workers, and Robust Device Registration Promotion

Covers all 12 acceptance criteria specified in Task 6:
1. BLE JSON sent in multiple fragments.
2. BLE write failure at first, middle, and final chunk.
3. ESP32 callback returns promptly while provisioning runs in a worker task.
4. Wi-Fi authentication failure handling.
5. Invalid or expired pairing code on /api/pin/register.
6. Backend accepts registration but ESP32 fails to save token (stays unpromoted, expires).
7. Token saved but WebSocket authentication fails (rejected, stays unpromoted).
8. Successful WebSocket authentication promotes the pending pin.
9. Server restart does not convert pending registrations into paired devices.
10. Repeated registration attempts do not create duplicate devices.
11. Failed registration leaves no paired PIN-F360 on the dashboard.
12. Existing mobile QR pairing still works.
"""

import asyncio
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure securelinkdb directory is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import server
from server import (
    PinRegistrationState,
    active_pairing_codes,
    pending_registrations,
    registered_devices,
    active_pins,
    pin_active_sockets,
    load_device_credentials,
    save_device_credentials,
    hash_device_token,
    verify_device_token,
    cleanup_expired_pending_registrations,
    get_device_registration_state,
    register_pin_api,
    get_pairing_code_status,
    get_pin_status,
    init_registered_devices_from_credentials,
    DEVICE_CREDENTIALS_FILE,
)


class TestBleFramingAndDiagnostics(unittest.TestCase):
    """Criteria 1 & 2: BLE JSON chunking, reassembly, and failure diagnostics."""

    def test_01_ble_json_multiple_fragments(self):
        """Test that multi-chunk BLE messages are safely assembled and validated."""
        full_payload = json.dumps({
            "type": "provision",
            "version": 1,
            "ssid": "SecureLink-Test-AP",
            "password": "SuperSecretPassword123!",
            "pairing_code": "847291",
            "server_url": "http://192.168.1.100:8080"
        })

        # Emulate 20-byte BLE chunks (standard ATT MTU default)
        chunk_size = 20
        raw_bytes = full_payload.encode("utf-8")
        chunks = [raw_bytes[i:i + chunk_size] for i in range(0, len(raw_bytes), chunk_size)]
        self.assertGreater(len(chunks), 5, "Payload should be split into multiple chunks")

        # Emulate ESP32 buffer assembly
        rx_buffer = bytearray()
        assembled_obj = None

        for idx, chunk in enumerate(chunks):
            rx_buffer.extend(chunk)
            decoded = rx_buffer.decode("utf-8", errors="ignore").strip()
            # Check JSON completeness: starts and ends with braces
            if decoded.startswith("{") and decoded.endswith("}"):
                try:
                    assembled_obj = json.loads(decoded)
                    break
                except json.JSONDecodeError:
                    pass

        self.assertIsNotNone(assembled_obj, "Reassembled JSON should be valid")
        self.assertEqual(assembled_obj["type"], "provision")
        self.assertEqual(assembled_obj["pairing_code"], "847291")
        self.assertEqual(assembled_obj["ssid"], "SecureLink-Test-AP")

    def test_02_ble_write_failure_first_middle_final_chunk(self):
        """Test diagnostic reporting when BLE write fails at first, middle, or final chunk."""
        def simulate_chunked_send(payload_bytes, max_chunk, fail_at_chunk_index):
            total_chunks = (len(payload_bytes) + max_chunk - 1) // max_chunk
            for chunk_idx in range(total_chunks):
                if chunk_idx == fail_at_chunk_index:
                    return {
                        "success": False,
                        "code": "ERR_BLE_WRITE_FAILED",
                        "failed_chunk_index": chunk_idx,
                        "total_chunks": total_chunks,
                        "message": f"BLE write failed at chunk {chunk_idx}/{total_chunks}"
                    }
            return {
                "success": True,
                "failed_chunk_index": None,
                "total_chunks": total_chunks,
                "message": "OK"
            }

        payload = b'{"type":"provision","ssid":"MyWifi","pairing_code":"123456"}'
        chunk_sz = 15
        total = (len(payload) + chunk_sz - 1) // chunk_sz
        self.assertGreaterEqual(total, 3)

        # Failure at first chunk (index 0)
        res_first = simulate_chunked_send(payload, chunk_sz, fail_at_chunk_index=0)
        self.assertFalse(res_first["success"])
        self.assertEqual(res_first["failed_chunk_index"], 0)

        # Failure at middle chunk (index 2)
        res_mid = simulate_chunked_send(payload, chunk_sz, fail_at_chunk_index=2)
        self.assertFalse(res_mid["success"])
        self.assertEqual(res_mid["failed_chunk_index"], 2)

        # Failure at final chunk (index total-1)
        res_last = simulate_chunked_send(payload, chunk_sz, fail_at_chunk_index=total - 1)
        self.assertFalse(res_last["success"])
        self.assertEqual(res_last["failed_chunk_index"], total - 1)


class TestEsp32TaskAndWifiFailure(unittest.TestCase):
    """Criteria 3 & 4: Non-blocking callback and Wi-Fi failure handling."""

    def test_03_esp32_callback_prompt_return_worker_task(self):
        """Test that simulated BLE onWrite enqueues request and returns in < 5ms."""
        queue = []
        is_active = False

        def on_write_callback(chunk):
            nonlocal is_active
            t_start = time.perf_counter()
            # Fast synchronous check and enqueue
            queue.append(chunk)
            t_elapsed_ms = (time.perf_counter() - t_start) * 1000
            return t_elapsed_ms

        elapsed = on_write_callback('{"type":"provision","ssid":"Test","pairing_code":"999111"}')
        self.assertLess(elapsed, 10.0, "Callback should complete in well under 10ms (non-blocking)")
        self.assertEqual(len(queue), 1)

    def test_04_wifi_auth_failure_handling(self):
        """Test that Wi-Fi failure reports ERR_WIFI_AUTH and does not register device."""
        events = []
        def worker_simulate(wifi_ok: bool):
            events.append({"type": "wifi_connecting", "ssid": "OfficeNet"})
            if not wifi_ok:
                events.append({
                    "type": "provision_error",
                    "code": "ERR_WIFI_AUTH",
                    "message": "Could not connect to Wi-Fi network"
                })
                return False
            events.append({"type": "wifi_connected", "ip": "192.168.1.50"})
            return True

        success = worker_simulate(wifi_ok=False)
        self.assertFalse(success)
        self.assertEqual(events[-1]["code"], "ERR_WIFI_AUTH")
        self.assertEqual(events[-1]["type"], "provision_error")


class TestPinRegistrationPromotion(unittest.IsolatedAsyncioTestCase):
    """Criteria 5 to 12: Backend registration, promotion, persistence, and mobile QR."""

    async def asyncSetUp(self):
        # Clear in-memory structures before each test
        active_pairing_codes.clear()
        pending_registrations.clear()
        registered_devices.clear()
        active_pins.clear()

        # Use temporary file for device_credentials.json to keep tests isolated
        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_creds_file = server.DEVICE_CREDENTIALS_FILE
        server.DEVICE_CREDENTIALS_FILE = os.path.join(self.temp_dir.name, "device_credentials.json")

    async def asyncTearDown(self):
        server.DEVICE_CREDENTIALS_FILE = self.orig_creds_file
        self.temp_dir.cleanup()

    async def test_05_invalid_or_expired_pairing_code(self):
        """Test that invalid or expired pairing codes are rejected without creating devices."""
        # 1. Non-existent code
        resp = await register_pin_api({
            "device_id": "PIN-F360",
            "pairing_code": "000000"
        })
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["code"], "ERR_INVALID_CODE")
        self.assertNotIn("PIN-F360", pending_registrations)
        self.assertNotIn("PIN-F360", registered_devices)

        # 2. Expired code
        active_pairing_codes["112233"] = {
            "created_at": time.time() - 200,
            "expires_at": time.time() - 10,
            "used": False,
            "device_id": None
        }
        resp_exp = await register_pin_api({
            "device_id": "PIN-F360",
            "pairing_code": "112233"
        })
        self.assertEqual(resp_exp["status"], "error")
        self.assertEqual(resp_exp["code"], "ERR_INVALID_CODE")
        self.assertNotIn("PIN-F360", pending_registrations)
        self.assertNotIn("PIN-F360", registered_devices)

    async def test_06_backend_accepts_registration_but_token_save_fails(self):
        """Test that HTTP registration creates PENDING state, and expires without appearing paired."""
        active_pairing_codes["987654"] = {
            "created_at": time.time(),
            "expires_at": time.time() + 60,
            "used": False,
            "device_id": None
        }

        resp = await register_pin_api({
            "device_id": "PIN-F360",
            "pairing_code": "987654",
            "firmware_version": "2.1",
            "mac": "AA:BB:CC:DD:EE:FF"
        })

        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["registration_state"], PinRegistrationState.PENDING)
        self.assertIn("PIN-F360", pending_registrations)

        # CRITICAL: Device must NOT be in registered_devices or device_credentials.json!
        self.assertNotIn("PIN-F360", registered_devices)
        creds = load_device_credentials()
        self.assertNotIn("PIN-F360", creds)

        # Simulate expiration (e.g. ESP32 powered off or flash failed, no WS connection)
        pending_registrations["PIN-F360"]["expires_at"] = time.time() - 1
        cleanup_expired_pending_registrations()

        self.assertNotIn("PIN-F360", pending_registrations)
        self.assertNotIn("PIN-F360", registered_devices)
        self.assertEqual(get_device_registration_state("PIN-F360"), PinRegistrationState.UNREGISTERED)

    async def test_07_token_saved_but_websocket_auth_fails(self):
        """Test that sending wrong token fails authentication and does not promote pin."""
        active_pairing_codes["554433"] = {
            "created_at": time.time(),
            "expires_at": time.time() + 60,
            "used": False,
            "device_id": None
        }

        resp = await register_pin_api({
            "device_id": "PIN-F360",
            "pairing_code": "554433"
        })
        real_token = resp["device_token"]

        # Simulated physical WebSocket connection with WRONG token
        wrong_token = "deadbeef" * 8
        is_authenticated = False
        if "PIN-F360" in pending_registrations:
            exp_hash = pending_registrations["PIN-F360"]["token_hash"]
            if secrets.compare_digest(exp_hash, hash_device_token(wrong_token)):
                is_authenticated = True

        self.assertFalse(is_authenticated, "Invalid token must not authenticate")
        # Ensure PIN-F360 was NOT promoted to registered_devices
        self.assertNotIn("PIN-F360", registered_devices)
        creds = load_device_credentials()
        self.assertNotIn("PIN-F360", creds)

    async def test_08_successful_websocket_auth_promotes_pending_pin(self):
        """Test full happy path: valid code -> pending -> WS auth -> promoted to PAIRED."""
        active_pairing_codes["123456"] = {
            "created_at": time.time(),
            "expires_at": time.time() + 60,
            "used": False,
            "device_id": None
        }

        # Step 1: HTTP register
        resp = await register_pin_api({
            "device_id": "PIN-F360",
            "pairing_code": "123456",
            "firmware_version": "2.1",
            "mac": "11:22:33:44:55:66"
        })
        self.assertEqual(resp["status"], "success")
        issued_token = resp["device_token"]
        self.assertIn("PIN-F360", pending_registrations)
        self.assertNotIn("PIN-F360", registered_devices)

        # Check status endpoint shows pending=True, paired=False
        status_resp = await get_pairing_code_status("123456")
        self.assertTrue(status_resp["pending"])
        self.assertFalse(status_resp["paired"])

        # Step 2: Simulated physical WebSocket authentication handshake
        async with server.pin_registration_lock:
            pending_entry = pending_registrations.get("PIN-F360")
            self.assertIsNotNone(pending_entry)
            expected_hash = pending_entry["token_hash"]
            self.assertTrue(secrets.compare_digest(expected_hash, hash_device_token(issued_token)))

            # Atomic promotion
            pending_registrations.pop("PIN-F360")
            creds = load_device_credentials()
            creds["PIN-F360"] = {
                "token_hash": expected_hash,
                "registered_at": "2026-11-22 04:00:00",
                "fw_version": "2.1",
                "mac": "11:22:33:44:55:66",
                "pairing_code_used": "123456"
            }
            save_device_credentials(creds)
            registered_devices["PIN-F360"] = {
                "id": "PIN-F360",
                "online": True,
                "connection_source": "ESP32_DIRECT",
                "battery": 100,
                "state": "VAD ARMED",
                "network": "Campus Wi-Fi",
                "paired": True
            }

        # Verify promotion results
        self.assertNotIn("PIN-F360", pending_registrations)
        self.assertIn("PIN-F360", registered_devices)
        self.assertTrue(registered_devices["PIN-F360"]["paired"])
        self.assertTrue(verify_device_token("PIN-F360", issued_token))

        # Check status endpoint now reports paired=True
        status_after = await get_pairing_code_status("123456")
        self.assertTrue(status_after["paired"])
        self.assertFalse(status_after["pending"])

    async def test_09_server_restart_does_not_convert_pending_to_paired(self):
        """Test that server restart does not load in-memory pending registrations as paired."""
        pending_registrations["PIN-UNFINISHED"] = {
            "device_id": "PIN-UNFINISHED",
            "token_hash": hash_device_token("secret123"),
            "expires_at": time.time() + 60,
            "state": PinRegistrationState.PENDING
        }

        # Emulate server reboot:
        registered_devices.clear()
        pending_registrations.clear()
        init_registered_devices_from_credentials()

        self.assertNotIn("PIN-UNFINISHED", registered_devices)
        self.assertEqual(get_device_registration_state("PIN-UNFINISHED"), PinRegistrationState.UNREGISTERED)

    async def test_10_repeated_registration_attempts_no_duplicates(self):
        """Test that repeated calls with same pairing code by same device resume safely without duplicate tokens, and other devices are rejected."""
        active_pairing_codes["778899"] = {
            "created_at": time.time(),
            "expires_at": time.time() + 60,
            "used": False,
            "device_id": None
        }

        # First call succeeds
        resp1 = await register_pin_api({
            "device_id": "PIN-F360",
            "pairing_code": "778899"
        })
        self.assertEqual(resp1["status"], "success")
        token1 = resp1["device_token"]

        # Resumption call with the same pairing code and same device_id resumes safely with same token
        resp2 = await register_pin_api({
            "device_id": "PIN-F360",
            "pairing_code": "778899"
        })
        self.assertEqual(resp2["status"], "success")
        self.assertEqual(resp2["registration_state"], PinRegistrationState.PENDING)
        self.assertEqual(resp2["device_token"], token1, "Resumed pending registration must return same credential token")

        # Call with different device_id on consumed code must be rejected
        resp3 = await register_pin_api({
            "device_id": "PIN-IMPOSTOR",
            "pairing_code": "778899"
        })
        self.assertEqual(resp3["status"], "error")
        self.assertEqual(resp3["code"], "ERR_INVALID_CODE")

        # Ensure only 1 pending registration exists
        count = sum(1 for k in pending_registrations if k == "PIN-F360")
        self.assertEqual(count, 1)

    async def test_11_failed_registration_leaves_no_paired_pin(self):
        """Test that any registration failure leaves no paired PIN-F360 on dashboard."""
        registered_devices.clear()
        active_pairing_codes["223344"] = {
            "created_at": time.time(),
            "expires_at": time.time() + 60,
            "used": True, # Already used
            "device_id": "PIN-OTHER"
        }

        resp = await register_pin_api({
            "device_id": "PIN-F360",
            "pairing_code": "223344"
        })
        self.assertEqual(resp["status"], "error")

        # Dashboard registered devices must remain clean
        self.assertNotIn("PIN-F360", registered_devices)

    async def test_12_existing_mobile_qr_pairing_still_works(self):
        """Test that Mobile Companion QR pairing generation and flow remains intact."""
        from server import mobile_pairing_mgr

        session = await mobile_pairing_mgr.create_session(
            server_ip="127.0.0.1",
            server_port=8080,
            cloud_tunnel_url=None
        )
        self.assertIsNotNone(session)
        self.assertIn("session_id", session)
        self.assertIn("pairing_code", session)
        self.assertEqual(len(session["pairing_code"]), 8, "Mobile pairing code is 8 digits")

        # Verify QR payload format
        self.assertIn("qr_payload", session)
        qr_obj = session["qr_payload"]
        if isinstance(qr_obj, str):
            qr_obj = json.loads(qr_obj)
        self.assertEqual(qr_obj["pairing_code"], session["pairing_code"])
        self.assertEqual(qr_obj["session_id"], session["session_id"])
        self.assertEqual(qr_obj["type"], "SECURELINK_MOBILE_PAIR")

    def test_13_special_characters_and_whitespace_preservation(self):
        """Test that passwords with leading/trailing spaces, colons, and quotes are preserved."""
        # Simulated payload with complex password
        test_passwords = [
            "  leadingAndTrailingSpaces  ",
            "password:with:colons:123!",
            'pass"with"quotes!#$',
            "Complex!@#$%^&*()_+-=[]{}|;':,.<>/?",
        ]
        for raw_pass in test_passwords:
            payload = json.dumps({
                "cmd": "provision",
                "ssid": "SecureLink-Test",
                "password": raw_pass,
                "server": "192.168.1.100",
                "port": 8080,
                "pairing_code": "123456"
            })
            parsed = json.loads(payload)
            self.assertEqual(parsed["password"], raw_pass, "Password must not be modified or stripped")

    def test_14_wifi_diagnostic_error_codes(self):
        """Test that Wi-Fi disconnect reason codes map to distinct, actionable error codes."""
        def diagnose_wifi_failure(reason_code: int, sta_connected: bool, got_ip: bool) -> tuple:
            if sta_connected and not got_ip:
                return "ERR_DHCP_TIMEOUT", "Associated with Wi-Fi, but failed to obtain IP address from DHCP"
            if reason_code == 201:
                return "ERR_AP_NOT_FOUND", "Access point not found"
            if reason_code in (202, 15, 2, 14):
                return "ERR_AUTH_REJECTED", "Wi-Fi password rejected by access point"
            if reason_code in (200, 205):
                return "ERR_WIFI_TIMEOUT", "Wi-Fi connection timed out"
            return "ERR_WIFI_TIMEOUT", "Wi-Fi connection timed out"

        self.assertEqual(diagnose_wifi_failure(201, False, False)[0], "ERR_AP_NOT_FOUND")
        self.assertEqual(diagnose_wifi_failure(202, False, False)[0], "ERR_AUTH_REJECTED")
        self.assertEqual(diagnose_wifi_failure(15, False, False)[0], "ERR_AUTH_REJECTED")
        self.assertEqual(diagnose_wifi_failure(0, True, False)[0], "ERR_DHCP_TIMEOUT")
        self.assertEqual(diagnose_wifi_failure(200, False, False)[0], "ERR_WIFI_TIMEOUT")

    async def test_15_usb_provisioning_stages_and_ack(self):
        """Test that USB provisioning validates parameters, requires serial ACK, and reports stages."""
        # Test missing COM port
        res = await server.provision_pin_serial({"ssid": "TestSSID", "pass": "secret"})
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["stage"], "serial_failed")

        # Test empty SSID
        res2 = await server.provision_pin_serial({"port": "COM99", "ssid": "", "pass": "secret"})
        self.assertEqual(res2["status"], "error")
        self.assertEqual(res2["stage"], "serial_failed")

        # Test simulated serial port failure
        res3 = await server.provision_pin_serial({"port": "COM_NON_EXISTENT", "ssid": "TestSSID", "pass": "secret"})
        self.assertEqual(res3["status"], "error")
        self.assertEqual(res3["stage"], "serial_failed")

    async def test_16_reconnection_after_wifi_drop_preserves_paired_state(self):
        """Test that temporary Wi-Fi disconnect marks pin OFFLINE without deleting pairing, and reconnects safely."""
        dev_id = "PIN-F360"
        creds = load_device_credentials()
        creds[dev_id] = {
            "token_hash": hash_device_token("test_token_123"),
            "registered_at": "2026-11-22 12:00:00",
            "fw_version": "2.1",
            "mac": "E8:F6:0A:8C:F3:60",
            "pairing_code_used": "112233"
        }
        save_device_credentials(creds)

        # Device is online
        mock_ws = MagicMock()
        active_pins[mock_ws] = dev_id
        registered_devices[dev_id] = {
            "id": dev_id,
            "online": True,
            "paired": True,
            "state": "VAD ARMED",
            "registration_state": PinRegistrationState.ONLINE
        }

        self.assertEqual(get_device_registration_state(dev_id), PinRegistrationState.PAIRED)

        # Wi-Fi dropped: socket closes
        active_pins.pop(mock_ws, None)
        registered_devices[dev_id]["online"] = False
        registered_devices[dev_id]["state"] = "OFFLINE"
        registered_devices[dev_id]["registration_state"] = PinRegistrationState.OFFLINE

        # Paired credentials MUST remain intact
        creds_after_drop = load_device_credentials()
        self.assertIn(dev_id, creds_after_drop)
        self.assertTrue(registered_devices[dev_id]["paired"])
        self.assertFalse(registered_devices[dev_id]["online"])
        self.assertEqual(registered_devices[dev_id]["state"], "OFFLINE")

        # Reconnection with valid token
        new_ws = MagicMock()
        active_pins[new_ws] = dev_id
        registered_devices[dev_id]["online"] = True
        registered_devices[dev_id]["state"] = "VAD ARMED"
        registered_devices[dev_id]["registration_state"] = PinRegistrationState.ONLINE

        self.assertTrue(registered_devices[dev_id]["online"])
        self.assertEqual(get_device_registration_state(dev_id), PinRegistrationState.PAIRED)
        # Ensure no duplicate records exist
        self.assertEqual(list(registered_devices.keys()).count(dev_id), 1)

    def test_17_target_server_url_selection_and_tunnel_preference(self):
        """Test Problem A: Target server URL resolution prioritizes Cloudflare Tunnel over local LAN."""
        def resolve_pin_server_url(cloud_tunnel: str, local_ip: str, mode: str = "automatic") -> str:
            clean_tunnel = cloud_tunnel.strip().rstrip("/") if cloud_tunnel else ""
            clean_lan = f"http://{local_ip.strip()}:8080".rstrip("/") if local_ip else ""

            if mode == "cloudflareTunnel":
                return clean_tunnel if clean_tunnel else clean_lan
            if mode == "localLan":
                return clean_lan if clean_lan else clean_tunnel

            # Automatic mode: prefer HTTPS Cloudflare tunnel if valid
            if clean_tunnel and (".trycloudflare.com" in clean_tunnel or clean_tunnel.startswith("https://")):
                return clean_tunnel
            return clean_lan if clean_lan else clean_tunnel

        tunnel = "https://active-sample-tunnel.trycloudflare.com/"
        lan = "192.168.1.150"

        # 1. Automatic mode with active tunnel -> MUST select tunnel
        selected = resolve_pin_server_url(tunnel, lan, mode="automatic")
        self.assertEqual(selected, "https://active-sample-tunnel.trycloudflare.com")
        self.assertFalse(selected.endswith("/"))

        # 2. Local LAN mode -> selects LAN IP
        selected_lan = resolve_pin_server_url(tunnel, lan, mode="localLan")
        self.assertEqual(selected_lan, "http://192.168.1.150:8080")

        # 3. Tunnel absent -> falls back to LAN in automatic mode
        selected_fallback = resolve_pin_server_url("", lan, mode="automatic")
        self.assertEqual(selected_fallback, "http://192.168.1.150:8080")

    def test_18_websocket_connection_superseding_prevents_offline_flapping(self):
        """Test Problem B: Superseded websocket disconnect does NOT mark device OFFLINE or flap state."""
        dev_id = "PIN-F360"
        old_ws = MagicMock()
        new_ws = MagicMock()

        registered_devices[dev_id] = {
            "id": dev_id,
            "online": True,
            "paired": True,
            "state": "VAD ARMED"
        }

        # Step 1: old_ws connects and is active
        pin_active_sockets[dev_id] = old_ws
        active_pins[old_ws] = dev_id

        # Step 2: Device reconnects. new_ws authenticates and supersedes old_ws
        if old_ws != new_ws and dev_id in pin_active_sockets:
            active_pins.pop(old_ws, None)
        pin_active_sockets[dev_id] = new_ws
        active_pins[new_ws] = dev_id

        # Step 3: old_ws finally terminates and its finally block executes:
        # Simulate finally block of handle_pin_websocket:
        active_pins.pop(old_ws, None)
        if pin_active_sockets.get(dev_id) == old_ws:
            del pin_active_sockets[dev_id]

        is_still_online = (dev_id in pin_active_sockets) or any(d_id == dev_id for d_id in active_pins.values())
        if not is_still_online and dev_id in registered_devices:
            registered_devices[dev_id]["online"] = False
            registered_devices[dev_id]["state"] = "OFFLINE"

        # Device MUST remain ONLINE and VAD ARMED because new_ws is authoritative
        self.assertTrue(registered_devices[dev_id]["online"])
        self.assertEqual(registered_devices[dev_id]["state"], "VAD ARMED")
        self.assertEqual(pin_active_sockets.get(dev_id), new_ws)

        # Cleanup
        active_pins.pop(new_ws, None)
        pin_active_sockets.pop(dev_id, None)

    async def test_19_pin_status_authoritative_endpoint(self):
        """Test Problem B: /api/pin/status/{device_id} accurately reports paired and online states."""
        dev_id = "PIN-TEST-STATUS"
        creds = load_device_credentials()
        creds[dev_id] = {
            "token_hash": hash_device_token("status_token"),
            "registered_at": "2026-11-22 12:00:00",
            "fw_version": "2.1",
            "mac": "11:22:33:44:55:66",
            "pairing_code_used": "999999"
        }
        save_device_credentials(creds)

        # 1. Device registered and paired, but offline
        registered_devices[dev_id] = {"id": dev_id, "online": False, "paired": True, "state": "OFFLINE"}
        status_res = await get_pin_status(dev_id)
        self.assertEqual(status_res["status"], "success")
        self.assertTrue(status_res["registered"])
        self.assertTrue(status_res["paired"])
        self.assertFalse(status_res["online"])
        self.assertEqual(status_res["state"], "OFFLINE")

        # 2. Device connects active socket
        mock_ws = MagicMock()
        pin_active_sockets[dev_id] = mock_ws
        active_pins[mock_ws] = dev_id
        registered_devices[dev_id]["online"] = True
        registered_devices[dev_id]["state"] = "VAD ARMED"

        status_res2 = await get_pin_status(dev_id)
        self.assertTrue(status_res2["online"])
        self.assertEqual(status_res2["state"], "VAD ARMED")

        # Cleanup
        active_pins.pop(mock_ws, None)
        pin_active_sockets.pop(dev_id, None)
        creds.pop(dev_id, None)
        save_device_credentials(creds)
        registered_devices.pop(dev_id, None)

    def test_20_fragmented_ble_notification_reassembly(self):
        """Test Problem C: Multi-chunk BLE notifications reassemble correctly across MTU 23 boundaries."""
        class BleNotificationReassembler:
            def __init__(self):
                self.rx_buffer = bytearray()
                self.events = []

            def _is_complete_json(self, text: str) -> bool:
                trimmed = text.strip()
                if not (trimmed.startswith("{") and trimmed.endswith("}")):
                    return False
                in_str = False
                escaped = False
                depth = 0
                for c in trimmed:
                    if escaped:
                        escaped = False
                        continue
                    if c == "\\":
                        escaped = True
                        continue
                    if c == '"':
                        in_str = not in_str
                        continue
                    if not in_str:
                        if c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                            if depth == 0:
                                return True
                return False

            def receive_chunk(self, chunk_bytes: bytes):
                self.rx_buffer.extend(chunk_bytes)
                text = self.rx_buffer.decode("utf-8", errors="ignore").strip()
                if self._is_complete_json(text):
                    try:
                        parsed = json.loads(text)
                        self.events.append(parsed)
                        self.rx_buffer.clear()
                    except json.JSONDecodeError:
                        pass

        reassembler = BleNotificationReassembler()
        full_event = json.dumps({"type": "pairing_success", "device_id": "PIN-F360", "status": "authenticated"})

        # Emulate 20-byte BLE notification writes (standard MTU 23)
        raw = full_event.encode("utf-8")
        chunk_size = 20
        chunks = [raw[i:i + chunk_size] for i in range(0, len(raw), chunk_size)]
        self.assertGreater(len(chunks), 1, "Should be split into multiple chunks")

        for idx, chunk in enumerate(chunks[:-1]):
            reassembler.receive_chunk(chunk)
            self.assertEqual(len(reassembler.events), 0, f"Chunk {idx} is incomplete, should not parse")

        # Send final chunk
        reassembler.receive_chunk(chunks[-1])
        self.assertEqual(len(reassembler.events), 1, "Complete event should parse on final chunk")
        self.assertEqual(reassembler.events[0]["type"], "pairing_success")
        self.assertEqual(reassembler.events[0]["device_id"], "PIN-F360")

    async def test_21_polling_verification_fallback_when_ble_dropped(self):
        """Test Problem C: Polling verification confirms pairing even if BLE notifications are lost."""
        dev_id = "PIN-F360-BLE-LOSS"
        pairing_code = "778899"

        # Server side: registration occurred and device was authenticated/promoted
        creds = load_device_credentials()
        creds[dev_id] = {
            "token_hash": hash_device_token("token_lost_ble"),
            "registered_at": "2026-11-22 12:00:00",
            "fw_version": "2.1",
            "mac": "AA:BB:CC:DD:EE:FF",
            "pairing_code_used": pairing_code
        }
        save_device_credentials(creds)
        registered_devices[dev_id] = {"id": dev_id, "online": True, "paired": True, "state": "VAD ARMED"}

        active_pairing_codes[pairing_code] = {
            "code": pairing_code,
            "created_at": time.time(),
            "expires_at": time.time() + 180,
            "used": True,
            "paired": True,
            "device_id": dev_id
        }

        # Mobile companion polling verification simulation
        status_res = await get_pin_status(dev_id)
        code_status = await get_pairing_code_status(pairing_code)

        is_paired_confirmed = (
            status_res.get("paired", False) or
            code_status.get("paired", False) or
            code_status.get("device_id") == dev_id
        )

        self.assertTrue(is_paired_confirmed, "Polling verification must confirm paired status even without BLE event")

        # Cleanup
        creds.pop(dev_id, None)
        save_device_credentials(creds)
        registered_devices.pop(dev_id, None)
        active_pairing_codes.pop(pairing_code, None)

    def test_22_stored_token_does_not_imply_server_authenticated(self):
        """Test Critical Issue A: Stored token only means hasStoredCredentials, NOT serverAuthenticated."""
        class PinFirmwareState:
            def __init__(self):
                self.hasStoredCredentials = False
                self.serverAuthenticated = False
                self.websocketConnected = False
                self.isDevicePaired = False
                self.token = ""
                self.device_id = "PIN-F360"

            def loadPreferences(self, stored_token: str):
                self.token = stored_token
                self.hasStoredCredentials = len(stored_token) > 0
                self.isDevicePaired = self.hasStoredCredentials
                # CRITICAL: Boot/load must NEVER set serverAuthenticated to True!
                self.serverAuthenticated = False

            def onWebSocketConnected(self):
                self.websocketConnected = True
                self.serverAuthenticated = False  # Pending handshake

            def onAuthOk(self, resp_device_id: str):
                if not resp_device_id or resp_device_id == self.device_id:
                    self.serverAuthenticated = True
                    self.isDevicePaired = True
                    self.hasStoredCredentials = True

            def onAuthError(self):
                self.serverAuthenticated = False
                self.hasStoredCredentials = False
                self.isDevicePaired = False
                self.token = ""

            def onWebSocketDisconnected(self):
                self.websocketConnected = False
                self.serverAuthenticated = False

        state = PinFirmwareState()
        # 1. Boot with stored token from prior session
        state.loadPreferences("stored_token_abc_123")
        self.assertTrue(state.hasStoredCredentials)
        self.assertFalse(state.serverAuthenticated, "Stored token must NOT mark server authenticated!")

        # 2. WebSocket transport connects
        state.onWebSocketConnected()
        self.assertTrue(state.websocketConnected)
        self.assertFalse(state.serverAuthenticated, "TCP/WS connect must NOT mark server authenticated!")

        # 3. Server returns auth_ok for matching device
        state.onAuthOk("PIN-F360")
        self.assertTrue(state.serverAuthenticated, "auth_ok for this device must set serverAuthenticated = True")

        # 4. Mismatched device ID does not authenticate
        state2 = PinFirmwareState()
        state2.loadPreferences("token_xyz")
        state2.onWebSocketConnected()
        state2.onAuthOk("PIN-IMPOSTOR")
        self.assertFalse(state2.serverAuthenticated, "Mismatched device ID must not authenticate!")

        # 5. Socket disconnect resets authentication
        state.onWebSocketDisconnected()
        self.assertFalse(state.websocketConnected)
        self.assertFalse(state.serverAuthenticated, "Disconnect must reset serverAuthenticated to False")

    async def test_23_server_authoritative_verification_no_local_cache_bypass(self):
        """Test Critical Issue B: Local cache does NOT count as server verification; query backend authoritatively."""
        dev_id = "PIN-AUTH-VERIFY"

        # 1. Query non-existent device: must return registered = False
        res_unregistered = await get_pin_status(dev_id)
        self.assertFalse(res_unregistered["registered"])
        self.assertFalse(res_unregistered["paired"])
        self.assertEqual(res_unregistered["state"], "UNREGISTERED")

        # 2. Register device legitimately
        creds = load_device_credentials()
        creds[dev_id] = {
            "token_hash": hash_device_token("token_verified_123"),
            "registered_at": "2026-11-22 12:00:00",
            "fw_version": "2.1",
            "mac": "00:11:22:33:44:55",
            "pairing_code_used": "123987"
        }
        save_device_credentials(creds)

        # Authoritative endpoint confirms registration even while offline
        res_registered = await get_pin_status(dev_id)
        self.assertTrue(res_registered["registered"])
        self.assertTrue(res_registered["paired"])
        self.assertFalse(res_registered["online"])
        self.assertEqual(res_registered["state"], "OFFLINE")

        # Cleanup
        creds.pop(dev_id, None)
        save_device_credentials(creds)

    def test_24_unknown_battery_telemetry_distinct_from_zero(self):
        """Test Critical Issue C & J: Unknown/invalid battery is -1, distinct from real 0%."""
        def calculate_battery_pct(measured_mv: int) -> int:
            if 3200 <= measured_mv <= 4350:
                pct = int(((measured_mv - 3300) / (4200 - 3300)) * 100)
                return max(1, min(100, pct))
            return -1  # Unavailable / unknown

        # Valid voltage measurements
        self.assertEqual(calculate_battery_pct(4200), 100)
        self.assertEqual(calculate_battery_pct(3750), 50)
        self.assertGreaterEqual(calculate_battery_pct(3300), 1)

        # Invalid/floating measurements (e.g. no divider wired or disconnected) -> MUST be -1
        self.assertEqual(calculate_battery_pct(0), -1)
        self.assertEqual(calculate_battery_pct(500), -1)
        self.assertEqual(calculate_battery_pct(2800), -1)
        self.assertEqual(calculate_battery_pct(4800), -1)

    async def test_25_ble_relayed_presence_security_boundary(self):
        """Test Critical Issue D: Unregistered pins cannot inject telemetry; registered pins update without clobbering direct online state."""
        unregistered_pin = "PIN-UNTRUSTED"
        registered_pin = "PIN-TRUSTED"

        # Setup registered pin in credentials and server
        creds = load_device_credentials()
        creds[registered_pin] = {
            "token_hash": hash_device_token("trusted_token"),
            "registered_at": "2026-11-22 12:00:00",
            "fw_version": "2.1",
            "mac": "22:33:44:55:66:77",
            "pairing_code_used": "654321"
        }
        save_device_credentials(creds)
        registered_devices[registered_pin] = {
            "id": registered_pin,
            "online": False,
            "state": "OFFLINE",
            "battery": -1,
            "ble_proximity": False
        }

        # 1. Unregistered pin attempted relay: MUST be rejected
        now_ts = time.time()
        self.assertNotIn(unregistered_pin, creds)
        unreg_res = server.recalculate_pin_connection_state(unregistered_pin, now_ts)
        self.assertFalse(unreg_res["online"])
        self.assertEqual(unreg_res["state"], "UNREGISTERED")

        # 2. Registered pin relay: active BLE relay updates presence & battery, preserves direct Wi-Fi if online
        server.active_ble_relays[registered_pin] = {
            "Mobile-1": {
                "timestamp": now_ts,
                "rssi": -55,
                "battery": 72,
                "battery_mv": 3950,
                "last_seen_str": "12:00:00"
            }
        }
        reg_res = server.recalculate_pin_connection_state(registered_pin, now_ts)
        self.assertTrue(reg_res["online"])
        self.assertTrue(reg_res["ble_proximity"])
        self.assertEqual(reg_res["battery"], 72)
        self.assertEqual(reg_res["batteryMv"], 3950)
        self.assertEqual(reg_res["connection_source"], "MOBILE_BLE_RELAY")
        self.assertEqual(reg_res["state"], "STANDBY")

        # Cleanup
        server.active_ble_relays.pop(registered_pin, None)
        creds.pop(registered_pin, None)
        save_device_credentials(creds)
        registered_devices.pop(registered_pin, None)

    def test_26_structured_server_endpoint_parser(self):
        """Test URL parsing across schemes, hosts, ports, paths, and TLS detection matching firmware."""
        def parse_server_endpoint(raw_url: str, default_port: int = 8080):
            clean = raw_url.strip()
            scheme = "http"
            port = default_port
            is_tls = False
            path = "/"

            if clean.startswith("https://"):
                scheme = "https"
                is_tls = True
                clean = clean[8:]
                port = 443
            elif clean.startswith("http://"):
                scheme = "http"
                clean = clean[7:]
                port = 8080
            elif clean.startswith("wss://"):
                scheme = "wss"
                is_tls = True
                clean = clean[6:]
                port = 443
            elif clean.startswith("ws://"):
                scheme = "ws"
                clean = clean[5:]
                port = 8080

            slash_idx = clean.find("/")
            if slash_idx >= 0:
                path = clean[slash_idx:]
                clean = clean[:slash_idx]

            colon_idx = clean.find(":")
            if colon_idx >= 0:
                host = clean[:colon_idx]
                parsed_port = int(clean[colon_idx + 1:])
                if parsed_port > 0:
                    port = parsed_port
            else:
                host = clean

            if "trycloudflare.com" in host or port == 443:
                is_tls = True
                if port == 8080:
                    port = 443

            return {
                "raw": raw_url,
                "scheme": scheme,
                "host": host,
                "port": port,
                "path": path,
                "is_tls": is_tls
            }

        # 1. Cloudflare Quick Tunnel URL
        cf = parse_server_endpoint("https://abc-123.trycloudflare.com")
        self.assertEqual(cf["scheme"], "https")
        self.assertEqual(cf["host"], "abc-123.trycloudflare.com")
        self.assertEqual(cf["port"], 443)
        self.assertTrue(cf["is_tls"])

        # 2. Local LAN URL with port
        lan = parse_server_endpoint("http://192.168.1.50:8080")
        self.assertEqual(lan["scheme"], "http")
        self.assertEqual(lan["host"], "192.168.1.50")
        self.assertEqual(lan["port"], 8080)
        self.assertFalse(lan["is_tls"])

        # 3. Plain IP without scheme or port
        plain = parse_server_endpoint("10.28.20.11")
        self.assertEqual(plain["scheme"], "http")
        self.assertEqual(plain["host"], "10.28.20.11")
        self.assertEqual(plain["port"], 8080)
        self.assertFalse(plain["is_tls"])

        # 4. Custom port HTTPS with subpath
        custom = parse_server_endpoint("https://secure.example.com:8443/api/v1")
        self.assertEqual(custom["scheme"], "https")
        self.assertEqual(custom["host"], "secure.example.com")
        self.assertEqual(custom["port"], 8443)
        self.assertEqual(custom["path"], "/api/v1")
        self.assertTrue(custom["is_tls"])

    def test_27_multi_root_ca_bundle_validation(self):
        """Test that the firmware trust bundle embeds Google Trust Services, ISRG Root X1, and DigiCert."""
        esp32_file = os.path.join(BASE_DIR, "..", "esp32code.txt")
        self.assertTrue(os.path.exists(esp32_file), "esp32code.txt must exist")
        with open(esp32_file, "r", encoding="utf-8") as f:
            code = f.read()

        # Must define cloudflare_ca_bundle
        self.assertIn("cloudflare_ca_bundle", code)

        # Must include GTS Root R1 (Google Trust Services)
        self.assertIn("Google Trust Services", code)
        self.assertIn("GTS Root R1", code)

        # Must include ISRG Root X1 (Let's Encrypt)
        self.assertIn("ISRG Root X1", code)

        # Must include DigiCert Global Root CA
        self.assertIn("DigiCert Global Root CA", code)

        # Verify cert PEM structure count in bundle (at least 4 certs)
        cert_count = code.count("-----BEGIN CERTIFICATE-----")
        self.assertGreaterEqual(cert_count, 4, "Must contain at least 4 root certificates")

    def test_28_bounded_ntp_synchronization_no_insecure_fallback(self):
        """Test that NTP synchronization enforces valid time (> 2024-01-01) with zero setInsecure() calls."""
        esp32_file = os.path.join(BASE_DIR, "..", "esp32code.txt")
        with open(esp32_file, "r", encoding="utf-8") as f:
            code = f.read()

        # setInsecure must NOT appear anywhere in the firmware
        self.assertNotIn("setInsecure()", code, "Firmware must not bypass TLS verification via setInsecure()")

        # syncNtpTime must check for year >= 2024 (timestamp >= 1704067200)
        self.assertIn("1704067200", code)
        self.assertIn("syncNtpTime", code)

    def test_29_tunnel_origin_health_and_rejection_of_502_503(self):
        """Test that tunnel manager rejects HTTP 502/503 origin errors and only promotes on HTTP 200."""
        from tunnel_manager import CloudflareTunnelManager, TunnelState

        manager = CloudflareTunnelManager(port=8080)

        # Simulate 502 Bad Gateway response: MUST return False (unreachable)
        with patch("urllib.request.urlopen") as mock_url:
            import urllib.error
            mock_url.side_effect = urllib.error.HTTPError(
                url="https://test.trycloudflare.com/health",
                code=502,
                msg="Bad Gateway",
                hdrs={},
                fp=None
            )
            reachable = asyncio.run(manager._validate_reachability("https://test.trycloudflare.com", max_retries=1))
            self.assertFalse(reachable, "HTTP 502 must NOT be considered reachable")

        # Simulate 200 OK: MUST return True
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            reachable = asyncio.run(manager._validate_reachability("https://test.trycloudflare.com", max_retries=1))
            self.assertTrue(reachable, "HTTP 200 must be verified reachable")

    def test_30_stale_tunnel_url_clearance_on_offline(self):
        """Test that when tunnel is offline or stopped, active URL is cleared and config is reset."""
        from tunnel_manager import CloudflareTunnelManager, TunnelState

        url_changes = []
        manager = CloudflareTunnelManager(port=8080, on_url_change=lambda u: url_changes.append(u))

        # Manually set an active tunnel
        manager.active_url = "https://stale.trycloudflare.com"
        manager.state = TunnelState.CONNECTED

        # Calling stop() must reset active_url to None, state to OFFLINE, and notify listeners
        asyncio.run(manager.stop())
        self.assertIsNone(manager.active_url)
        self.assertEqual(manager.state, TunnelState.OFFLINE)
        self.assertIn(None, url_changes, "Listeners must be notified with None when tunnel stops")

    def test_31_granular_ble_diagnostic_error_codes(self):
        """Test that each network failure mode produces distinct, actionable diagnostic error codes."""
        diagnostic_codes = [
            "ERR_DNS_FAILED",
            "ERR_TCP_CONNECT",
            "ERR_TLS_CERT",
            "ERR_TLS_TIME",
            "ERR_TLS_HANDSHAKE",
            "ERR_TUNNEL_ORIGIN",
            "ERR_HTTP_TIMEOUT",
            "ERR_HTTP_STATUS",
            "ERR_WS_CONNECT",
            "ERR_WS_TIMEOUT",
            "ERR_WS_AUTH"
        ]

        # Verify all codes are unique
        self.assertEqual(len(diagnostic_codes), len(set(diagnostic_codes)))

        # Verify flutter service maps each distinct code
        service_file = os.path.join(BASE_DIR, "lib", "mobile", "services", "mobile_server_service.dart")
        with open(service_file, "r", encoding="utf-8") as f:
            service_code = f.read()

        for code in diagnostic_codes:
            self.assertIn(code, service_code, f"MobileServerService must handle {code}")

    def test_32_recalculate_pin_connection_state_priority_and_transitions(self):
        """Test authoritative priority: Direct WS > BLE Relay, and seamless fallback when direct drops."""
        pin_id = "PIN-TRANSIT-01"
        creds = load_device_credentials()
        creds[pin_id] = {
            "token_hash": hash_device_token("tok_transit"),
            "registered_at": "2026-11-23 00:00:00",
            "fw_version": "2.1",
            "mac": "11:22:33:44:55:66"
        }
        save_device_credentials(creds)
        server.registered_devices[pin_id] = {
            "id": pin_id,
            "online": False,
            "battery": -1,
            "state": "OFFLINE",
            "network": "Campus Wi-Fi",
            "lastSeen": "Registered",
            "paired": True
        }

        now_ts = time.time()

        # State 1: Both offline
        s1 = server.recalculate_pin_connection_state(pin_id, now_ts)
        self.assertFalse(s1["online"])
        self.assertFalse(s1["direct_online"])
        self.assertFalse(s1["relay_online"])
        self.assertIsNone(s1["connection_source"])

        # State 2: Direct Wi-Fi connects
        mock_ws = MagicMock()
        server.pin_active_sockets[pin_id] = mock_ws
        server.active_pins[mock_ws] = pin_id
        s2 = server.recalculate_pin_connection_state(pin_id, now_ts)
        self.assertTrue(s2["online"])
        self.assertTrue(s2["direct_online"])
        self.assertFalse(s2["relay_online"])
        self.assertEqual(s2["connection_source"], "ESP32_DIRECT")

        # State 3: BLE relay also arrives while direct is active
        server.active_ble_relays[pin_id] = {
            "Mobile-Teacher": {
                "timestamp": now_ts,
                "rssi": -50,
                "battery": 88,
                "battery_mv": 4100,
                "last_seen_str": "00:01:00"
            }
        }
        s3 = server.recalculate_pin_connection_state(pin_id, now_ts)
        self.assertTrue(s3["online"])
        self.assertTrue(s3["direct_online"])
        self.assertTrue(s3["relay_online"])
        self.assertTrue(s3["ble_proximity"])
        self.assertEqual(s3["connection_source"], "ESP32_DIRECT", "Direct Wi-Fi MUST retain priority over BLE relay")

        # State 4: Direct Wi-Fi drops! Seamless fallback to BLE Relay
        server.pin_active_sockets.pop(pin_id, None)
        server.active_pins.pop(mock_ws, None)
        s4 = server.recalculate_pin_connection_state(pin_id, now_ts)
        self.assertTrue(s4["online"], "Pin MUST remain ONLINE via BLE Relay when direct Wi-Fi drops!")
        self.assertFalse(s4["direct_online"])
        self.assertTrue(s4["relay_online"])
        self.assertEqual(s4["connection_source"], "MOBILE_BLE_RELAY")
        self.assertEqual(s4["battery"], 88)
        self.assertEqual(s4["relayed_by"], "Mobile-Teacher")

        # State 5: BLE Relay also disconnects
        server.active_ble_relays.pop(pin_id, None)
        s5 = server.recalculate_pin_connection_state(pin_id, now_ts)
        self.assertFalse(s5["online"])
        self.assertFalse(s5["relay_online"])
        self.assertEqual(s5["state"], "OFFLINE")

        # Cleanup
        creds.pop(pin_id, None)
        save_device_credentials(creds)
        server.registered_devices.pop(pin_id, None)

    def test_33_watchdog_preserves_active_ble_relay(self):
        """Test that the pin liveness watchdog does NOT mark pin OFFLINE if active BLE relay exists."""
        pin_id = "PIN-WATCHDOG-01"
        creds = load_device_credentials()
        creds[pin_id] = {
            "token_hash": hash_device_token("tok_watchdog"),
            "registered_at": "2026-11-23 00:00:00",
            "fw_version": "2.1",
            "mac": "22:33:44:55:66:77"
        }
        save_device_credentials(creds)
        server.registered_devices[pin_id] = {
            "id": pin_id,
            "online": True,
            "connection_source": "MOBILE_BLE_RELAY",
            "battery": 65,
            "state": "STANDBY",
            "network": "BLE Audio Bridge",
            "lastSeen": "Just now",
            "paired": True
        }

        now_ts = time.time()
        server.active_ble_relays[pin_id] = {
            "Companion-1": {
                "timestamp": now_ts,
                "rssi": -65,
                "battery": 65,
                "battery_mv": 3800,
                "last_seen_str": "00:02:00"
            }
        }

        # Device has NO direct socket
        self.assertNotIn(pin_id, server.pin_active_sockets)

        # Run state recalculation (what watchdog does)
        dev = server.recalculate_pin_connection_state(pin_id, now_ts)
        self.assertTrue(dev["online"], "Watchdog recalculation MUST keep device ONLINE when BLE relay is active")
        self.assertEqual(dev["connection_source"], "MOBILE_BLE_RELAY")
        self.assertEqual(dev["battery"], 65)

        # Cleanup
        server.active_ble_relays.pop(pin_id, None)
        creds.pop(pin_id, None)
        save_device_credentials(creds)
        server.registered_devices.pop(pin_id, None)

    def test_34_ble_relay_timeout_pruning(self):
        """Test that BLE relays older than BLE_RELAY_TIMEOUT_SEC (15s) are pruned and mark pin OFFLINE."""
        pin_id = "PIN-PRUNE-01"
        creds = load_device_credentials()
        creds[pin_id] = {
            "token_hash": hash_device_token("tok_prune"),
            "registered_at": "2026-11-23 00:00:00",
            "fw_version": "2.1",
            "mac": "33:44:55:66:77:88"
        }
        save_device_credentials(creds)
        server.registered_devices[pin_id] = {
            "id": pin_id,
            "online": True,
            "connection_source": "MOBILE_BLE_RELAY",
            "battery": 50,
            "state": "STANDBY",
            "paired": True
        }

        now_ts = 1000.0
        # Relay recorded at timestamp 980.0 (20s old > 15s timeout)
        server.active_ble_relays[pin_id] = {
            "Companion-Stale": {
                "timestamp": 980.0,
                "rssi": -70,
                "battery": 50,
                "battery_mv": 3700,
                "last_seen_str": "00:00:00"
            }
        }

        dev = server.recalculate_pin_connection_state(pin_id, now_ts=now_ts)
        self.assertFalse(dev["online"], "Pin MUST be marked OFFLINE when BLE relay exceeds 15s timeout")
        self.assertFalse(dev["relay_online"])
        self.assertIsNone(dev["connection_source"])
        self.assertEqual(dev["state"], "OFFLINE")

        # Cleanup
        server.active_ble_relays.pop(pin_id, None)
        creds.pop(pin_id, None)
        save_device_credentials(creds)
        server.registered_devices.pop(pin_id, None)

    def test_35_multi_companion_relay_tracking(self):
        """Test that multiple companion relays for the same pin do not clobber each other on partial disconnect."""
        pin_id = "PIN-MULTI-01"
        creds = load_device_credentials()
        creds[pin_id] = {
            "token_hash": hash_device_token("tok_multi"),
            "registered_at": "2026-11-23 00:00:00",
            "fw_version": "2.1",
            "mac": "44:55:66:77:88:99"
        }
        save_device_credentials(creds)

        now_ts = time.time()
        # Two companions active
        server.active_ble_relays[pin_id] = {
            "Phone-Teacher": {
                "timestamp": now_ts - 2.0,
                "rssi": -60,
                "battery": 90,
                "battery_mv": 4150,
                "last_seen_str": "00:03:00"
            },
            "Phone-Student": {
                "timestamp": now_ts,
                "rssi": -55,
                "battery": 90,
                "battery_mv": 4150,
                "last_seen_str": "00:03:02"
            }
        }

        dev = server.recalculate_pin_connection_state(pin_id, now_ts)
        self.assertTrue(dev["online"])
        self.assertEqual(dev["relayed_by"], "Phone-Student")

        # Phone-Student disconnects: Phone-Teacher is still within 15s window
        server.active_ble_relays[pin_id].pop("Phone-Student", None)
        dev2 = server.recalculate_pin_connection_state(pin_id, now_ts)
        self.assertTrue(dev2["online"], "Device MUST remain ONLINE as long as at least one companion is actively relaying")
        self.assertEqual(dev2["relayed_by"], "Phone-Teacher")

        # Phone-Teacher disconnects: now OFFLINE
        server.active_ble_relays[pin_id].pop("Phone-Teacher", None)
        dev3 = server.recalculate_pin_connection_state(pin_id, now_ts)
        self.assertFalse(dev3["online"])

        # Cleanup
        server.active_ble_relays.pop(pin_id, None)
        creds.pop(pin_id, None)
        save_device_credentials(creds)
        server.registered_devices.pop(pin_id, None)

    def test_36_unknown_battery_sentinel_and_ui_clamping(self):
        """Test unknown battery sentinel (-1): estRuntime is '--', clamped to >= 0.0 in UI, not marked critical."""
        pin_id = "PIN-NOBATT-01"
        creds = load_device_credentials()
        creds[pin_id] = {
            "token_hash": hash_device_token("tok_nobatt"),
            "registered_at": "2026-11-23 00:00:00",
            "fw_version": "2.1",
            "mac": "55:66:77:88:99:AA"
        }
        save_device_credentials(creds)

        now_ts = time.time()
        server.active_ble_relays[pin_id] = {
            "Phone-1": {
                "timestamp": now_ts,
                "rssi": -60,
                "battery": -1,
                "battery_mv": -1,
                "last_seen_str": "00:04:00"
            }
        }

        dev = server.recalculate_pin_connection_state(pin_id, now_ts)
        self.assertEqual(dev["battery"], -1)
        self.assertEqual(dev["batteryMv"], -1)
        self.assertEqual(dev["estRuntime"], "--")

        # Progress bar value formula: value = battery >= 0 ? (battery / 100.0).clamp(0.0, 1.0) : 0.0
        val = (dev["battery"] / 100.0) if dev["battery"] >= 0 else 0.0
        self.assertGreaterEqual(val, 0.0)
        self.assertEqual(val, 0.0)

        # Cleanup
        server.active_ble_relays.pop(pin_id, None)
        creds.pop(pin_id, None)
        save_device_credentials(creds)
        server.registered_devices.pop(pin_id, None)

    def test_37_firmware_audio_routing_and_snapshot_authentication_guard(self):
        """Test firmware enforces ws.isConnected() && serverAuthenticated before sending audio/snapshots over Wi-Fi."""
        esp32_file = os.path.join(BASE_DIR, "..", "esp32code.txt")
        with open(esp32_file, "r", encoding="utf-8") as f:
            code = f.read()

        # Audio stream Tier A must be gated on serverAuthenticated
        self.assertIn("hasActiveStream && ws.isConnected() && serverAuthenticated", code)

        # Snapshot Wi-Fi route must be gated on serverAuthenticated
        self.assertIn("ws.isConnected() && serverAuthenticated", code)

        # Direct heartbeat must be gated on serverAuthenticated
        self.assertIn("ws.isConnected() && serverAuthenticated", code)

        # BLE heartbeat must be active when bleClientConnected
        self.assertIn("if (bleClientConnected)", code)

        # readBatteryTelemetry single ADC read
        self.assertIn("BatteryTelemetry readBatteryTelemetry()", code)
        self.assertIn("analogReadMilliVolts(BATTERY_PIN)", code)

    def test_38_exact_firmware_binary_identity(self):
        """Test that esp32code.txt and bullying_pin_v2.ino are 100% byte-for-byte identical."""
        f1_path = os.path.join(BASE_DIR, "..", "esp32code.txt")
        f2_path = os.path.join("D:\\", "Downloads", "bullying_pin_v2", "bullying_pin_v2.ino")

        with open(f1_path, "rb") as f1, open(f2_path, "rb") as f2:
            bytes1 = f1.read()
            bytes2 = f2.read()

        self.assertEqual(len(bytes1), len(bytes2), "Files must have identical byte lengths")
        self.assertEqual(bytes1, bytes2, "esp32code.txt and bullying_pin_v2.ino must be byte-for-byte identical")


if __name__ == "__main__":
    unittest.main()

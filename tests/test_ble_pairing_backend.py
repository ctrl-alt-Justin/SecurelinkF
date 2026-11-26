import asyncio
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

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

import httpx
import server
from server import (
    app,
    active_pairing_codes,
    pending_registrations,
    load_device_credentials,
    save_device_credentials,
    hash_device_token,
    verify_device_token,
    registered_devices,
    active_pins,
)


class TestBlePairingBackend(unittest.IsolatedAsyncioTestCase):
    """Automated test suite for SecureLink BLE Onboarding, Pairing Codes, and Device Authentication."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_creds_file = os.path.join(self.temp_dir.name, "test_credentials.json")
        self.temp_codes_file = os.path.join(self.temp_dir.name, "test_pairing_codes.json")

        self.creds_patch = patch("server.DEVICE_CREDENTIALS_FILE", self.temp_creds_file)
        self.codes_patch = patch("server.ACTIVE_PAIRING_CODES_FILE", self.temp_codes_file)
        self.creds_patch.start()
        self.codes_patch.start()

        active_pairing_codes.clear()
        pending_registrations.clear()
        registered_devices.clear()
        transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.codes_patch.stop()
        self.creds_patch.stop()
        self.temp_dir.cleanup()
        active_pairing_codes.clear()
        pending_registrations.clear()
        registered_devices.clear()

    async def test_01_generate_pairing_code(self):
        """Generates 6-digit cryptographic pairing code with 10-minute TTL."""
        resp = await self.client.post("/api/pairing-code/generate")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["status"], "success")
        code = data["pairing_code"]
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        self.assertEqual(data["expires_in"], 600)
        self.assertIn(code, active_pairing_codes)
        self.assertFalse(active_pairing_codes[code]["used"])

    async def test_02_pairing_code_status(self):
        """Checks status of valid, expired, and non-existent pairing codes."""
        # Non-existent code
        resp = await self.client.get("/api/pairing-code/status/999999")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["valid"])

        # Newly generated valid code
        gen_resp = (await self.client.post("/api/pairing-code/generate")).json()
        code = gen_resp["pairing_code"]

        status_resp = await self.client.get(f"/api/pairing-code/status/{code}")
        self.assertEqual(status_resp.status_code, 200)
        data = status_resp.json()
        self.assertTrue(data["valid"])
        self.assertFalse(data["used"])
        self.assertFalse(data["expired"])
        self.assertGreater(data["remaining_seconds"], 590)

    async def test_03_pin_registration_success(self):
        """Registers a Smart Pin into PENDING state using a valid code and receives a 32-byte secret."""
        gen_resp = (await self.client.post("/api/pairing-code/generate")).json()
        code = gen_resp["pairing_code"]

        reg_payload = {
            "device_id": "PIN-4A8C",
            "pairing_code": code,
            "firmware_version": "2.1",
            "mac": "84:FC:E6:21:4A:8C"
        }
        reg_resp = await self.client.post("/api/pin/register", json=reg_payload)
        self.assertEqual(reg_resp.status_code, 200)
        reg_data = reg_resp.json()

        self.assertEqual(reg_data["status"], "success")
        self.assertEqual(reg_data["registration_state"], server.PinRegistrationState.PENDING)
        self.assertEqual(reg_data["device_id"], "PIN-4A8C")
        token = reg_data["device_token"]
        self.assertEqual(len(token), 64)  # 32 bytes in hex = 64 characters

        # Check code is marked used and pending registration holds the hashed token
        self.assertTrue(active_pairing_codes[code]["used"])
        self.assertEqual(active_pairing_codes[code]["device_id"], "PIN-4A8C")
        self.assertIn("PIN-4A8C", pending_registrations)
        self.assertEqual(
            pending_registrations["PIN-4A8C"]["token_hash"],
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )
        # Paired credentials are NOT persisted until WebSocket auth promotion
        self.assertFalse(os.path.exists(self.temp_creds_file))

    async def test_04_single_use_pairing_code_consumption(self):
        """Pairing codes are strictly single-use; subsequent registration attempts are rejected."""
        gen_resp = (await self.client.post("/api/pairing-code/generate")).json()
        code = gen_resp["pairing_code"]

        # First registration succeeds
        resp1 = await self.client.post("/api/pin/register", json={"device_id": "PIN-4A8C", "pairing_code": code})
        self.assertEqual(resp1.json()["status"], "success")

        # Second registration with identical code must fail
        resp2 = await self.client.post("/api/pin/register", json={"device_id": "PIN-9999", "pairing_code": code})
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["status"], "error")
        self.assertEqual(resp2.json()["code"], "ERR_INVALID_CODE")

    async def test_05_expired_pairing_code_rejection(self):
        """Expired pairing codes cannot be used to register devices."""
        gen_resp = (await self.client.post("/api/pairing-code/generate")).json()
        code = gen_resp["pairing_code"]

        # Force expire the code
        active_pairing_codes[code]["expires_at"] = time.time() - 10.0

        resp = await self.client.post("/api/pin/register", json={"device_id": "PIN-4A8C", "pairing_code": code})
        self.assertEqual(resp.json()["status"], "error")
        self.assertEqual(resp.json()["code"], "ERR_INVALID_CODE")

    async def test_06_token_hash_verification_utility(self):
        """Validates token hashing and constant-time digest comparison."""
        token = secrets.token_hex(32)
        save_device_credentials({
            "PIN-1234": {
                "token_hash": hash_device_token(token),
                "registered_at": "2026-11-21 20:00:00"
            }
        })

        # Correct token succeeds
        self.assertTrue(verify_device_token("PIN-1234", token))
        # Wrong token fails
        self.assertFalse(verify_device_token("PIN-1234", "wrong_token_hex"))
        # Unknown device fails
        self.assertFalse(verify_device_token("PIN-UNKNOWN", token))

    async def test_07_paired_devices_listing(self):
        """Endpoint GET /api/devices/paired returns registered devices and metadata."""
        token = secrets.token_hex(32)
        save_device_credentials({
            "PIN-4A8C": {
                "token_hash": hash_device_token(token),
                "registered_at": "2026-11-21 20:00:00",
                "fw_version": "2.1",
                "mac": "84:FC:E6:21:4A:8C"
            }
        })

        resp = await self.client.get("/api/devices/paired")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["devices"][0]["device_id"], "PIN-4A8C")
        self.assertEqual(data["devices"][0]["mac"], "84:FC:E6:21:4A:8C")

    async def test_08_ble_json_protocol_packet_simulation(self):
        """Simulates full Nordic UART JSON payload exchange between Mobile Companion and Smart Pin."""
        # 1. Device Info Request
        req_info = json.dumps({"type": "get_device_info"})
        parsed_req = json.loads(req_info)
        self.assertEqual(parsed_req["type"], "get_device_info")

        # 2. Pin Response
        pin_resp = json.dumps({
            "type": "device_info",
            "device_id": "PIN-4A8C",
            "mac": "84:FC:E6:21:4A:8C",
            "fw_version": "2.1",
            "paired": False
        })
        parsed_resp = json.loads(pin_resp)
        self.assertEqual(parsed_resp["device_id"], "PIN-4A8C")
        self.assertFalse(parsed_resp["paired"])

        # 3. Provisioning Command
        prov_cmd = json.dumps({
            "type": "provision",
            "version": 1,
            "ssid": "Campus_Staff_5G",
            "password": "Password123!",
            "pairing_code": "849201",
            "server_url": "http://10.28.20.28:8080"
        })
        parsed_prov = json.loads(prov_cmd)
        self.assertEqual(parsed_prov["pairing_code"], "849201")
        self.assertEqual(parsed_prov["ssid"], "Campus_Staff_5G")

        # 4. Progress Events
        progress_events = [
            {"type": "provision_received"},
            {"type": "wifi_connecting", "ssid": "Campus_Staff_5G"},
            {"type": "wifi_connected", "ip": "10.28.20.145"},
            {"type": "pairing_pending"},
            {"type": "pairing_success", "device_id": "PIN-4A8C"}
        ]
        for ev in progress_events:
            ev_str = json.dumps(ev)
            self.assertTrue(json.loads(ev_str)["type"].startswith(("provision", "wifi", "pairing")))


if __name__ == "__main__":
    unittest.main()

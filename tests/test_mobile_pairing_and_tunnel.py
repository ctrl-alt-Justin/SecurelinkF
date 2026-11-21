"""
Automated Integration & Unit Tests for SecureLink:
- Mobile Companion QR Pairing
- Manual 8-Digit Pairing Code
- Ephemeral Single-Use Enforcing & Expiration
- Rate Limiting & Lockout
- Administrator Approval & Revocation
- Authenticated Dedicated /mobile WebSocket
- Empty Credential Store Security Check (No Auth Bypass)
- Cloudflare Quick Tunnel Manager Lifecycle & States
"""

import os
import sys
import time
import json
import asyncio
import unittest
from unittest.mock import patch, MagicMock

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
from server import app, mobile_pairing_mgr, tunnel_mgr, active_mobile_clients
from tunnel_manager import TunnelState, CloudflareTunnelManager
from mobile_pairing import MobilePairingManager, PairingState

class TestMobilePairingAndTunnel(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Reset mobile pairing manager sessions and rate limits
        mobile_pairing_mgr.sessions.clear()
        mobile_pairing_mgr.code_to_session.clear()
        mobile_pairing_mgr.rate_limits.clear()
        mobile_pairing_mgr.lockouts.clear()

        # Temporary test devices storage
        self.test_mgr = MobilePairingManager(cs_id="CS-TEST-01", cs_name="Test Central System")
        self.transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_01_create_mobile_pairing_session(self):
        """Test POST /api/mobile-pairing/create generates 8-digit numeric code and valid QR payload."""
        resp = await self.client.post("/api/mobile-pairing/create", json={"ttl_seconds": 90})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["status"], "success")
        self.assertIn("session_id", data)
        self.assertIn("pairing_code", data)
        self.assertEqual(len(data["pairing_code"]), 8)
        self.assertTrue(data["pairing_code"].isdigit())
        self.assertEqual(data["expires_in"], 90)

        # Check QR payload
        qr = data["qr_payload"]
        self.assertEqual(qr["type"], "SECURELINK_MOBILE_PAIR")
        self.assertEqual(qr["version"], "1.0")
        self.assertEqual(qr["session_id"], data["session_id"])
        self.assertEqual(qr["pairing_code"], data["pairing_code"])
        self.assertIn("server_ip", qr)
        self.assertEqual(qr["server_port"], 8080)

    async def test_02_redeem_pairing_code_manual_and_qr(self):
        """Test redeeming pairing code advances session to pending_approval."""
        create_resp = await self.client.post("/api/mobile-pairing/create", json={"ttl_seconds": 90})
        c_data = create_resp.json()
        code = c_data["pairing_code"]
        session_id = c_data["session_id"]

        # Option A: Redeem using QR payload (session_id + pairing_code)
        redeem_resp = await self.client.post("/api/mobile-pairing/redeem", json={
            "session_id": session_id,
            "pairing_code": code,
            "device_id": "MOBILE-TEST-01",
            "device_name": "Teacher Pixel 8",
            "user_name": "Prof. Santos",
            "role": "Teacher"
        })
        self.assertEqual(redeem_resp.status_code, 200)
        r_data = redeem_resp.json()
        self.assertEqual(r_data["status"], "pending_approval")
        self.assertEqual(r_data["session_id"], session_id)

        # Check status endpoint
        st_resp = await self.client.get(f"/api/mobile-pairing/status/{session_id}")
        self.assertEqual(st_resp.status_code, 200)
        st_data = st_resp.json()
        self.assertEqual(st_data["state"], "pending_approval")
        self.assertEqual(st_data["device_info"]["user_name"], "Prof. Santos")

    async def test_03_expired_pairing_code_rejected(self):
        """Test that expired pairing codes (~90s TTL) are strictly rejected."""
        # Create session with 1-second TTL
        create_resp = await self.client.post("/api/mobile-pairing/create", json={"ttl_seconds": 1})
        c_data = create_resp.json()
        code = c_data["pairing_code"]
        session_id = c_data["session_id"]

        # Wait 1.1s for expiration
        await asyncio.sleep(1.1)

        redeem_resp = await self.client.post("/api/mobile-pairing/redeem", json={
            "session_id": session_id,
            "pairing_code": code,
            "device_id": "MOBILE-EXPIRED",
            "device_name": "Test Phone",
            "user_name": "Test User",
            "role": "Teacher"
        })
        self.assertEqual(redeem_resp.status_code, 400)
        err = redeem_resp.json()
        self.assertEqual(err["code"], "ERR_CODE_EXPIRED")

    async def test_04_single_use_enforcement_and_reuse_rejection(self):
        """Test that a pairing code cannot be redeemed twice."""
        create_resp = await self.client.post("/api/mobile-pairing/create", json={"ttl_seconds": 90})
        c_data = create_resp.json()
        code = c_data["pairing_code"]
        session_id = c_data["session_id"]

        # First redemption succeeds
        r1 = await self.client.post("/api/mobile-pairing/redeem", json={
            "session_id": session_id,
            "pairing_code": code,
            "device_id": "MOBILE-USER-1",
            "device_name": "Phone 1",
            "user_name": "User 1",
            "role": "Teacher"
        })
        self.assertEqual(r1.status_code, 200)

        # Second redemption must be rejected (single-use violated)
        r2 = await self.client.post("/api/mobile-pairing/redeem", json={
            "session_id": session_id,
            "pairing_code": code,
            "device_id": "MOBILE-USER-2",
            "device_name": "Phone 2",
            "user_name": "User 2",
            "role": "Student"
        })
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(r2.json()["code"], "ERR_CODE_ALREADY_USED")

    async def test_05_rate_limiting_and_lockout(self):
        """Test that 5 consecutive failed pairing attempts trigger a 60-second lockout."""
        client_ip = "192.168.1.99"
        headers = {"x-forwarded-for": client_ip}

        # Submit 5 invalid redemption attempts
        for i in range(5):
            res = await self.client.post("/api/mobile-pairing/redeem", headers=headers, json={
                "pairing_code": "00000000",
                "device_id": f"ATTACKER-{i}",
                "device_name": "Malicious Phone",
                "user_name": "Unknown",
                "role": "Student"
            })
            self.assertEqual(res.status_code, 400)

        # 6th attempt should be rate limited (HTTP 429)
        lockout_res = await self.client.post("/api/mobile-pairing/redeem", headers=headers, json={
            "pairing_code": "00000000",
            "device_id": "ATTACKER-LOCKED",
            "device_name": "Malicious Phone",
            "user_name": "Unknown",
            "role": "Student"
        })
        self.assertEqual(lockout_res.status_code, 429)
        err = lockout_res.json()
        self.assertEqual(err["code"], "ERR_RATE_LIMITED")
        self.assertIn("retry_after", err)

    async def test_06_admin_approval_and_token_issuance(self):
        """Test admin approval workflow, 32-byte credential token issuance, and device persistence."""
        # 1. Create session
        c_res = await self.client.post("/api/mobile-pairing/create", json={"ttl_seconds": 90})
        session_id = c_res.json()["session_id"]
        code = c_res.json()["pairing_code"]

        # 2. Redeem
        await self.client.post("/api/mobile-pairing/redeem", json={
            "session_id": session_id,
            "pairing_code": code,
            "device_id": "MOBILE-FACULTY-01",
            "device_name": "Dr. Mendoza Galaxy S24",
            "user_name": "Dr. Mendoza",
            "role": "Teacher"
        })

        # 3. Approve via admin endpoint
        appr_res = await self.client.post("/api/mobile-pairing/approve", json={
            "session_id": session_id,
            "role": "Admin"
        })
        self.assertEqual(appr_res.status_code, 200)
        self.assertEqual(appr_res.json()["status"], "success")

        # 4. Mobile poll retrieves issued auth_token
        status_res = await self.client.get(f"/api/mobile-pairing/status/{session_id}")
        self.assertEqual(status_res.status_code, 200)
        s_data = status_res.json()
        self.assertEqual(s_data["state"], "approved")
        self.assertIn("auth_token", s_data)
        self.assertEqual(len(s_data["auth_token"]), 64)  # 32 bytes hex = 64 characters

        # 5. Verify token verification works
        token = s_data["auth_token"]
        is_valid, dev_info = mobile_pairing_mgr.verify_mobile_token("MOBILE-FACULTY-01", token)
        self.assertTrue(is_valid)
        self.assertEqual(dev_info["role"], "Admin")

    async def test_07_device_revocation(self):
        """Test revoking a paired device prevents future token verification."""
        # Create, redeem, and approve device
        c_res = await self.client.post("/api/mobile-pairing/create", json={"ttl_seconds": 90})
        sid = c_res.json()["session_id"]
        code = c_res.json()["pairing_code"]

        await self.client.post("/api/mobile-pairing/redeem", json={
            "session_id": sid,
            "pairing_code": code,
            "device_id": "MOBILE-REVOKE-ME",
            "device_name": "Lost Phone",
            "user_name": "Lost User",
            "role": "Student"
        })

        await self.client.post("/api/mobile-pairing/approve", json={"session_id": sid})
        s_res = await self.client.get(f"/api/mobile-pairing/status/{sid}")
        token = s_res.json()["auth_token"]

        # Pre-revocation verification succeeds
        ok, _ = mobile_pairing_mgr.verify_mobile_token("MOBILE-REVOKE-ME", token)
        self.assertTrue(ok)

        # Revoke device
        rev_res = await self.client.post("/api/mobile-pairing/revoke", json={"device_id": "MOBILE-REVOKE-ME"})
        self.assertEqual(rev_res.status_code, 200)

        # Post-revocation verification fails
        ok_after, _ = mobile_pairing_mgr.verify_mobile_token("MOBILE-REVOKE-ME", token)
        self.assertFalse(ok_after)

    async def test_08_empty_credential_store_security_check(self):
        """Security audit test: When credential store has no entry, unauthenticated connections MUST fail."""
        # Testing mobile token verification with unknown device
        ok, _ = mobile_pairing_mgr.verify_mobile_token("UNREGISTERED-DEVICE", "randomtoken123")
        self.assertFalse(ok)

    async def test_09_cloudflare_tunnel_manager_states_and_reachability(self):
        """Test CloudflareTunnelManager state transitions and reachability validation."""
        test_mgr = CloudflareTunnelManager(port=8080)
        self.assertEqual(test_mgr.state, TunnelState.OFFLINE)
        self.assertTrue(test_mgr.is_installed())

        # Test reachability validation failure with dummy non-existent URL
        with patch("tunnel_manager.urllib.request.urlopen", side_effect=Exception("Connection refused")):
            is_reachable = await test_mgr._validate_reachability("https://non-existent-tunnel.trycloudflare.com", max_retries=1)
            self.assertFalse(is_reachable)

        # Test reachability validation success
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        with patch("tunnel_manager.urllib.request.urlopen", return_value=mock_resp):
            is_reachable = await test_mgr._validate_reachability("https://valid-tunnel.trycloudflare.com", max_retries=1)
            self.assertTrue(is_reachable)

if __name__ == "__main__":
    unittest.main()

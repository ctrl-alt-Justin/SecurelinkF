"""
SECURELINK MOBILE PAIRING & AUTHENTICATION MANAGER
Provides QR and 8-digit manual pairing for Mobile Companions,
administrator approval workflows, single-use cryptographically hashed codes,
rate limiting, lockout protection, and persistent credential management in mobile_devices.json.
"""

import os
import time
import json
import hmac
import hashlib
import secrets
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger("securelink.mobile_pairing")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MOBILE_DEVICES_FILE = os.path.join(BASE_DIR, "mobile_devices.json")

class PairingState:
    PENDING_REDEMPTION = "pending_redemption"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"

class MobilePairingManager:
    def __init__(self, cs_id: str = "CS-CAMPUS-01", cs_name: str = "SecureLink Campus Central System"):
        self.cs_id = cs_id
        self.cs_name = cs_name
        self.sessions: Dict[str, Dict[str, Any]] = {}  # session_id -> session_data
        self.code_to_session: Dict[str, str] = {}      # code_hash -> session_id
        self.rate_limits: Dict[str, List[float]] = {}  # ip_address -> timestamps of failed attempts
        self.lockouts: Dict[str, float] = {}           # ip_address -> lockout_until_timestamp
        self._lock = asyncio.Lock()

    def _hash_code(self, code: str) -> str:
        return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()

    def load_paired_devices(self) -> Dict[str, Any]:
        """Loads persistent paired mobile devices from mobile_devices.json."""
        if os.path.exists(MOBILE_DEVICES_FILE):
            try:
                with open(MOBILE_DEVICES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[MOBILE-AUTH] Error loading {MOBILE_DEVICES_FILE}: {e}")
        return {}

    def save_paired_devices(self, data: Dict[str, Any]):
        """Persists paired mobile devices to mobile_devices.json."""
        try:
            with open(MOBILE_DEVICES_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"[MOBILE-AUTH] Error saving {MOBILE_DEVICES_FILE}: {e}")

    def purge_expired_sessions(self):
        """Removes expired or completed pairing sessions after retention grace period."""
        now = time.time()
        expired_ids = []
        for sid, sdata in list(self.sessions.items()):
            if sdata["state"] == PairingState.PENDING_REDEMPTION and now > sdata["expires_at"]:
                sdata["state"] = PairingState.EXPIRED

            # Retain expired, approved, or rejected sessions for 120s so clients get unambiguous state
            if now > sdata["expires_at"] + 120:
                expired_ids.append(sid)

        for sid in expired_ids:
            sdata = self.sessions.pop(sid, None)
            if sdata and "code_hash" in sdata:
                self.code_to_session.pop(sdata["code_hash"], None)

    def is_rate_limited(self, ip: str) -> Tuple[bool, int]:
        """Checks if client IP is currently locked out due to excessive failed pairing attempts."""
        now = time.time()
        lockout_until = self.lockouts.get(ip, 0)
        if now < lockout_until:
            return True, int(lockout_until - now)

        # Clean old attempts (> 60s)
        attempts = [t for t in self.rate_limits.get(ip, []) if now - t < 60]
        self.rate_limits[ip] = attempts
        if len(attempts) >= 5:
            # Lock out for 60 seconds
            self.lockouts[ip] = now + 60
            logger.warning(f"[MOBILE-PAIRING] IP {ip} locked out for 60s due to 5 consecutive failed redemption attempts.")
            return True, 60
        return False, 0

    def record_failed_attempt(self, ip: str):
        now = time.time()
        attempts = self.rate_limits.setdefault(ip, [])
        attempts.append(now)

    def clear_rate_limit(self, ip: str):
        self.rate_limits.pop(ip, None)
        self.lockouts.pop(ip, None)

    async def create_session(
        self,
        server_ip: str,
        server_port: int,
        cloud_tunnel_url: Optional[str] = None,
        ttl_seconds: int = 90
    ) -> Dict[str, Any]:
        """
        Creates an 8-digit numeric pairing code with a ~90-second expiration.
        Stores only the SHA-256 hash of the code in memory.
        """
        async with self._lock:
            self.purge_expired_sessions()

            # Generate unique session ID
            session_id = secrets.token_hex(16)

            # Generate cryptographically secure random 8-digit numeric string
            while True:
                code = "".join(secrets.choice("0123456789") for _ in range(8))
                code_hash = self._hash_code(code)
                if code_hash not in self.code_to_session:
                    break

            now = time.time()
            expires_at = now + ttl_seconds

            self.sessions[session_id] = {
                "session_id": session_id,
                "code_hash": code_hash,
                "created_at": now,
                "expires_at": expires_at,
                "ttl_seconds": ttl_seconds,
                "state": PairingState.PENDING_REDEMPTION,
                "device_info": None,
                "auth_token": None,
            }
            self.code_to_session[code_hash] = session_id

            # QR Code Payload without permanent secrets
            qr_payload = {
                "type": "SECURELINK_MOBILE_PAIR",
                "version": "1.0",
                "session_id": session_id,
                "pairing_code": code,
                "cs_id": self.cs_id,
                "server_ip": server_ip,
                "server_port": server_port,
                "cloud_tunnel_url": cloud_tunnel_url,
                "timestamp": datetime.now().isoformat()
            }

            return {
                "status": "success",
                "session_id": session_id,
                "pairing_code": code,
                "expires_in": ttl_seconds,
                "expires_at": int(expires_at),
                "qr_payload": qr_payload,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

    async def redeem_code(
        self,
        pairing_code: str,
        device_id: str,
        device_name: str,
        user_name: str,
        role: str,
        client_ip: str,
        session_id: Optional[str] = None,
        connection_type: str = "local"
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Validates pairing credentials, single-use enforcement, and registers a pending mobile pairing request.
        """
        async with self._lock:
            self.purge_expired_sessions()

            limited, remaining = self.is_rate_limited(client_ip)
            if limited:
                return False, {
                    "status": "error",
                    "code": "ERR_RATE_LIMITED",
                    "message": f"Too many failed pairing attempts. Locked out for {remaining} seconds.",
                    "retry_after": remaining
                }

            code_clean = pairing_code.replace(" ", "").replace("-", "").strip()
            if len(code_clean) != 8 or not code_clean.isdigit():
                self.record_failed_attempt(client_ip)
                return False, {
                    "status": "error",
                    "code": "ERR_INVALID_CODE_FORMAT",
                    "message": "Pairing code must be an 8-digit numeric string."
                }

            target_session_id = session_id
            code_hash = self._hash_code(code_clean)

            # Match session
            if not target_session_id:
                target_session_id = self.code_to_session.get(code_hash)

            if not target_session_id or target_session_id not in self.sessions:
                self.record_failed_attempt(client_ip)
                return False, {
                    "status": "error",
                    "code": "ERR_SESSION_NOT_FOUND",
                    "message": "Pairing session not found or expired."
                }

            session = self.sessions[target_session_id]
            now = time.time()

            # Check expiration
            if now > session["expires_at"] or session["state"] == PairingState.EXPIRED:
                session["state"] = PairingState.EXPIRED
                self.record_failed_attempt(client_ip)
                return False, {
                    "status": "error",
                    "code": "ERR_CODE_EXPIRED",
                    "message": "Pairing code has expired. Please generate a new code on the dashboard."
                }

            # Check single-use
            if session["state"] != PairingState.PENDING_REDEMPTION:
                self.record_failed_attempt(client_ip)
                return False, {
                    "status": "error",
                    "code": "ERR_CODE_ALREADY_USED",
                    "message": "Pairing code has already been redeemed or used."
                }

            # Constant-time comparison of code hash
            if not hmac.compare_digest(session["code_hash"], code_hash):
                self.record_failed_attempt(client_ip)
                return False, {
                    "status": "error",
                    "code": "ERR_INVALID_CODE",
                    "message": "Invalid pairing code."
                }

            # Successfully validated single-use code: advance to PENDING_APPROVAL
            self.clear_rate_limit(client_ip)
            session["state"] = PairingState.PENDING_APPROVAL
            session["device_info"] = {
                "device_id": device_id.strip(),
                "device_name": device_name.strip() or f"Mobile Device ({device_id})",
                "user_name": user_name.strip() or "Teacher / Staff",
                "role": role.strip() or "Teacher",
                "client_ip": client_ip,
                "connection_type": connection_type,
                "redeemed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            return True, {
                "status": "pending_approval",
                "session_id": target_session_id,
                "message": "Pairing request received. Waiting for Central System administrator approval."
            }

    async def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """Pollable endpoint for mobile and dashboard to check status of a pairing session."""
        self.purge_expired_sessions()
        session = self.sessions.get(session_id)
        if not session:
            return {
                "status": "error",
                "code": "ERR_NOT_FOUND",
                "message": "Pairing session not found or expired.",
                "state": PairingState.EXPIRED
            }

        now = time.time()
        remaining = max(0, int(session["expires_at"] - now))
        is_expired = (now > session["expires_at"]) and (session["state"] == PairingState.PENDING_REDEMPTION)
        if is_expired:
            session["state"] = PairingState.EXPIRED

        resp = {
            "status": "success",
            "session_id": session_id,
            "state": session["state"],
            "remaining_seconds": remaining,
            "device_info": session.get("device_info"),
        }

        if session["state"] == PairingState.APPROVED and session.get("auth_token"):
            resp["auth_token"] = session["auth_token"]
            resp["device_id"] = session["device_info"]["device_id"]
            resp["cs_id"] = self.cs_id

        return resp

    async def approve_session(
        self,
        session_id: str,
        role_override: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Dashboard administrator approves the pending mobile device, issues a 32-byte secure token,
        and persists credentials in mobile_devices.json.
        """
        async with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return False, {"status": "error", "message": "Session not found or expired."}

            if session["state"] != PairingState.PENDING_APPROVAL:
                return False, {"status": "error", "message": f"Session cannot be approved in state '{session['state']}'."}

            dev_info = session["device_info"]
            device_id = dev_info["device_id"]
            role = role_override.strip() if role_override else dev_info["role"]

            # Generate 32-byte cryptographic mobile access token
            mobile_token = secrets.token_hex(32)
            token_hash = self._hash_token(mobile_token)

            # Persist in mobile_devices.json
            devices = self.load_paired_devices()
            devices[device_id] = {
                "device_id": device_id,
                "device_name": dev_info["device_name"],
                "user_name": dev_info["user_name"],
                "role": role,
                "token_hash": token_hash,
                "paired_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "revoked": False,
                "last_seen": "Just paired",
                "connection_type": dev_info.get("connection_type", "local"),
                "paired_ip": dev_info.get("client_ip", "unknown")
            }
            self.save_paired_devices(devices)

            session["state"] = PairingState.APPROVED
            session["auth_token"] = mobile_token
            # Extend expiration so mobile has time to retrieve token via polling
            session["expires_at"] = time.time() + 120

            logger.info(f"[MOBILE-PAIRING] Administrator approved mobile device '{device_id}' ({dev_info['user_name']}). Token issued.")

            return True, {
                "status": "success",
                "session_id": session_id,
                "device_id": device_id,
                "role": role,
                "message": f"Mobile device '{device_id}' approved successfully."
            }

    async def revoke_device(self, device_id: str) -> Tuple[bool, Dict[str, Any]]:
        """Revokes a previously paired mobile device."""
        async with self._lock:
            devices = self.load_paired_devices()
            if device_id not in devices:
                return False, {"status": "error", "message": f"Device '{device_id}' not found."}

            devices[device_id]["revoked"] = True
            devices[device_id]["revoked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.save_paired_devices(devices)

            logger.info(f"[MOBILE-PAIRING] Device '{device_id}' revoked by administrator.")
            return True, {"status": "success", "device_id": device_id, "message": "Device revoked."}

    def verify_mobile_token(self, device_id: str, token: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Validates mobile bearer token using constant-time comparison against persisted token_hash.
        Rejects revoked devices.
        """
        if not device_id or not token:
            return False, None

        devices = self.load_paired_devices()
        dev_entry = devices.get(device_id)
        if not dev_entry:
            return False, None

        if dev_entry.get("revoked", False):
            return False, None

        expected_hash = dev_entry.get("token_hash", "")
        actual_hash = self._hash_token(token)

        if hmac.compare_digest(expected_hash, actual_hash):
            return True, dev_entry
        return False, None

    def update_device_presence(self, device_id: str, connection_type: str):
        """Updates last_seen and connection_type for active device."""
        devices = self.load_paired_devices()
        if device_id in devices:
            devices[device_id]["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            devices[device_id]["connection_type"] = connection_type
            self.save_paired_devices(devices)

    def list_all_devices(self, active_mobile_devices: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Returns list of all paired devices and pending approval requests."""
        devices = self.load_paired_devices()
        result = []
        active_ids = active_mobile_devices or {}

        for dev_id, info in devices.items():
            is_online = dev_id in active_ids
            result.append({
                "device_id": dev_id,
                "device_name": info.get("device_name", dev_id),
                "user_name": info.get("user_name", "Teacher / Student"),
                "role": info.get("role", "Teacher"),
                "paired_at": info.get("paired_at", ""),
                "revoked": info.get("revoked", False),
                "online": is_online,
                "last_seen": info.get("last_seen", ""),
                "connection_type": active_ids[dev_id].get("connection_type", info.get("connection_type", "local")) if is_online else info.get("connection_type", "local")
            })
        return result

    def list_pending_requests(self) -> List[Dict[str, Any]]:
        """Lists sessions currently waiting for administrator approval."""
        self.purge_expired_sessions()
        pending = []
        for sid, sdata in self.sessions.items():
            if sdata["state"] == PairingState.PENDING_APPROVAL and sdata.get("device_info"):
                info = sdata["device_info"].copy()
                info["session_id"] = sid
                pending.append(info)
        return pending

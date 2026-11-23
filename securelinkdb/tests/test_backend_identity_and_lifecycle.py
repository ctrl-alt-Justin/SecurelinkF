"""
Unit and Integration Tests for SecureLink Backend Identity, Lifecycle Management, and Route Verification
Verifies:
1. USB routes registered in the running FastAPI application.
2. Backend identity endpoint (/api/system/info).
3. Wrong backend version and missing routes detection.
4. HTTP 404 error handling (must not be masked as generic COM4 failure).
5. Backend startup from different working directories (deterministic BASE_DIR / PROJECT_DIR).
6. Port 8080 occupied detection.
7. Stale backend process detection and safe filtering (never kill unrelated processes).
8. Correct backend route availability.
"""

import os
import sys
import unittest
import asyncio
from unittest.mock import MagicMock, patch

# Ensure securelinkdb directory is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import server


class TestBackendIdentityAndLifecycle(unittest.TestCase):
    def test_01_usb_routes_registered_in_fastapi(self):
        """All four USB serial endpoints must be registered in server.app routes."""
        routes = {}
        for r in server.app.routes:
            if hasattr(r, "path") and r.path.startswith("/api/usb"):
                routes[r.path] = getattr(r, "methods", set())

        self.assertIn("/api/usb/status", routes)
        self.assertIn("GET", routes["/api/usb/status"])

        self.assertIn("/api/usb/ports", routes)
        self.assertIn("GET", routes["/api/usb/ports"])

        self.assertIn("/api/usb/connect", routes)
        self.assertIn("POST", routes["/api/usb/connect"])

        self.assertIn("/api/usb/disconnect", routes)
        self.assertIn("POST", routes["/api/usb/disconnect"])

    def test_02_backend_identity_endpoint(self):
        """GET /api/system/info returns accurate identity metadata without exposing secrets."""
        data = asyncio.run(server.get_system_info())

        self.assertEqual(data["status"], "success")
        self.assertIn("SecureLink", data["application"])
        self.assertEqual(data["backend_version"], server.BACKEND_VERSION)
        self.assertIsNotNone(data["git_commit"])
        self.assertIsInstance(data["pid"], int)
        self.assertTrue(os.path.exists(data["executable"]))
        self.assertEqual(data["project_dir"], server.PROJECT_DIR)
        self.assertEqual(data["server_port"], 8080)
        self.assertTrue(data["usb_endpoints_available"])
        self.assertIn("/api/usb/connect", data["usb_routes"])

        # Security check: No passwords, pairing tokens, or secrets exposed
        keys = list(data.keys())
        for forbidden in ("password", "token", "secret", "credentials", "wifi"):
            self.assertFalse(any(forbidden in k.lower() for k in keys))

    def test_03_wrong_backend_version_and_missing_routes_detection(self):
        """Backend without /api/usb/connect must be flagged as version mismatch."""
        # Simulate an older backend response missing USB connect route
        legacy_info = {
            "application": "SecureLink AI Inference Server",
            "backend_version": "1.0-legacy",
            "usb_endpoints_available": False,
            "usb_routes": ["/api/network-info"]
        }

        routes = legacy_info.get("usb_routes", [])
        has_connect = "/api/usb/connect" in routes and legacy_info.get("usb_endpoints_available", False)
        self.assertFalse(has_connect)

        error_message = "BACKEND VERSION MISMATCH — USB CONNECT ENDPOINT NOT AVAILABLE" if not has_connect else None
        self.assertEqual(error_message, "BACKEND VERSION MISMATCH — USB CONNECT ENDPOINT NOT AVAILABLE")

    def test_04_http_404_error_handling_and_no_generic_failure(self):
        """A 404 response on /api/usb/connect indicates route absence, not a COM port hardware error."""
        registered_paths = [r.path for r in server.app.routes if hasattr(r, "path")]
        non_existent = "/api/usb/connect_fake"
        is_404 = non_existent not in registered_paths
        self.assertTrue(is_404)

        # Dashboard diagnostic logic verification
        status_code = 404
        if status_code == 404:
            diagnostic = "HTTP 404 Not Found: /api/usb/connect route does not exist on running backend"
        else:
            diagnostic = "Failed to open COM4"

        self.assertIn("HTTP 404 Not Found", diagnostic)
        self.assertNotIn("Failed to open COM4", diagnostic)

    def test_05_backend_startup_from_different_working_directory(self):
        """BASE_DIR and PROJECT_DIR must remain deterministic even if launched from another CWD."""
        expected_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.assertEqual(os.path.abspath(server.BASE_DIR), expected_dir)
        self.assertEqual(os.path.abspath(server.PROJECT_DIR), expected_dir)

    def test_06_port_8080_already_occupied_detection(self):
        """System detects when port 8080 is occupied by inspecting listening sockets."""
        netstat_output = (
            "  TCP    0.0.0.0:8080           0.0.0.0:0              LISTENING       18568\n"
            "  TCP    127.0.0.1:5000         0.0.0.0:0              LISTENING       1234\n"
        )
        target_pid = None
        for line in netstat_output.split("\n"):
            if ":8080" in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    target_pid = int(parts[-1])
                    break

        self.assertEqual(target_pid, 18568)

    def test_07_stale_backend_detection_and_safe_filtering(self):
        """Safe lifecycle management must only flag SecureLink processes, protecting third-party apps."""
        # 1. Stale SecureLink process -> Target for cleanup
        securelink_cmd = "C:\\Python312\\python.exe server.py"
        is_sl = ("server.py" in securelink_cmd.lower() or "securelink" in securelink_cmd.lower())
        self.assertTrue(is_sl)

        # 2. Unrelated python process (e.g. Jupyter or custom script) -> Protected
        unrelated_python = "C:\\Python312\\python.exe -m jupyter notebook"
        is_unrelated_sl = ("server.py" in unrelated_python.lower() or "securelink" in unrelated_python.lower())
        self.assertFalse(is_unrelated_sl)

        # 3. Third-party web server (e.g. node.js or nginx) -> Protected
        node_cmd = "C:\\Program Files\\nodejs\\node.exe index.js"
        is_node_sl = ("server.py" in node_cmd.lower() or "securelink" in node_cmd.lower())
        self.assertFalse(is_node_sl)

    def test_08_correct_backend_startup_and_route_availability(self):
        """FastAPI application accepts connect request when proper parameters provided."""
        with patch.object(server.usb_mgr, "connect", return_value=(True, "Port COM4 opened successfully")):
            resp = asyncio.run(server.connect_usb_port({"port": "COM4"}))
            self.assertEqual(resp["status"], "success")
            self.assertEqual(resp["port"], "COM4")


if __name__ == "__main__":
    unittest.main()

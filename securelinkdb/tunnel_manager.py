"""
SECURELINK CLOUDFLARE QUICK TUNNEL MANAGER
Manages the free, zero-configuration Cloudflare Quick Tunnel (trycloudflare.com).
Enables secure remote HTTPS/WSS access without requiring a custom domain or Cloudflare account.
"""

import os
import sys
import re
import time
import json
import shutil
import asyncio
import logging
import platform
import subprocess
import urllib.request
from typing import Optional, Dict, Any, Callable

logger = logging.getLogger("securelink.tunnel")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED_LOCAL_WIN = os.path.join(BASE_DIR, "cloudflared.exe")
TUNNEL_CONFIG_FILE = os.path.join(BASE_DIR, "tunnel_config.json")
URL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

class TunnelState:
    OFFLINE = "Offline"
    STARTING = "Starting"
    CONNECTED = "Connected"
    RECONNECTING = "Reconnecting"
    ERROR = "Error"

class CloudflareTunnelManager:
    def __init__(self, port: int = 8080, on_url_change: Optional[Callable[[Optional[str]], Any]] = None):
        self.port = port
        self.on_url_change = on_url_change
        self.state = TunnelState.OFFLINE
        self.active_url: Optional[str] = None
        self.process: Optional[subprocess.Popen] = None
        self.error_message: Optional[str] = None
        self.started_at: Optional[float] = None
        self.consecutive_crashes = 0
        self._monitor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._stop_requested = False

    def find_cloudflared_binary(self) -> Optional[str]:
        """Locates cloudflared executable in local directory or system PATH."""
        if sys.platform == "win32" and os.path.exists(CLOUDFLARED_LOCAL_WIN):
            return CLOUDFLARED_LOCAL_WIN
        
        bin_in_path = shutil.which("cloudflared")
        if bin_in_path:
            return bin_in_path
            
        local_bin = os.path.join(BASE_DIR, "cloudflared")
        if os.path.exists(local_bin):
            return local_bin
            
        return None

    def get_install_instructions(self) -> Dict[str, Any]:
        """Returns OS-specific installation instructions for cloudflared."""
        os_name = platform.system().lower()
        if os_name == "windows":
            return {
                "os": "Windows",
                "recommended_command": "winget install --id Cloudflare.cloudflared",
                "manual_url": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
                "instructions": (
                    "1. Run in PowerShell: winget install --id Cloudflare.cloudflared\n"
                    "   OR download cloudflared-windows-amd64.exe from GitHub,\n"
                    "   rename it to 'cloudflared.exe', and place it in the securelinkdb folder."
                )
            }
        elif os_name == "darwin":
            return {
                "os": "macOS",
                "recommended_command": "brew install cloudflare/cloudflare/cloudflared",
                "manual_url": "https://github.com/cloudflare/cloudflared/releases",
                "instructions": "Run in Terminal: brew install cloudflare/cloudflare/cloudflared"
            }
        else:
            return {
                "os": "Linux",
                "recommended_command": "sudo apt-get install cloudflared",
                "manual_url": "https://github.com/cloudflare/cloudflared/releases",
                "instructions": (
                    "Debian/Ubuntu: sudo mkdir -p --mode=0755 /etc/apt/keyrings && "
                    "curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /etc/apt/keyrings/cloudflare-main.gpg >/dev/null && "
                    "echo 'deb [signed-by=/etc/apt/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list && "
                    "sudo apt-get update && sudo apt-get install cloudflared"
                )
            }

    def is_installed(self) -> bool:
        return self.find_cloudflared_binary() is not None

    def get_status(self) -> Dict[str, Any]:
        uptime = int(time.time() - self.started_at) if (self.started_at and self.state == TunnelState.CONNECTED) else 0
        return {
            "status": "success",
            "state": self.state,
            "cloud_tunnel_url": self.active_url,
            "port": self.port,
            "is_installed": self.is_installed(),
            "uptime_seconds": uptime,
            "error_message": self.error_message,
            "install_instructions": self.get_install_instructions() if not self.is_installed() else None,
        }

    async def start(self) -> Dict[str, Any]:
        """Starts the Quick Tunnel with single-instance enforcement and background monitoring."""
        async with self._lock:
            self._stop_requested = False
            bin_path = self.find_cloudflared_binary()
            if not bin_path:
                self.state = TunnelState.ERROR
                self.error_message = "cloudflared executable not found on host."
                return self.get_status()

            if self.process is not None and self.process.poll() is None:
                if self.state == TunnelState.CONNECTED and self.active_url:
                    return self.get_status()
                # Stop stale instance
                self._kill_process()

            self._cleanup_orphaned_processes()

            self.state = TunnelState.STARTING
            self.error_message = None
            self.active_url = None
            self._save_config(None)

            cmd = [bin_path, "tunnel", "--url", f"http://127.0.0.1:{self.port}", "--protocol", "http2", "--no-autoupdate"]
            try:
                # Start process with suppressed stdin
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
                )
            except Exception as e:
                self.state = TunnelState.ERROR
                self.error_message = f"Failed to spawn cloudflared: {e}"
                return self.get_status()

            # Launch asynchronous output parser & monitor
            if self._monitor_task and not self._monitor_task.done():
                self._monitor_task.cancel()
            self._monitor_task = asyncio.create_task(self._monitor_loop())

            return self.get_status()

    async def _monitor_loop(self):
        """Asynchronously parses cloudflared output for tunnel URL, validates reachability, and monitors liveness."""
        loop = asyncio.get_running_loop()
        tunnel_url = None

        def read_line():
            if self.process and self.process.stdout:
                return self.process.stdout.readline()
            return ""

        while self.process and self.process.poll() is None:
            line = await loop.run_in_executor(None, read_line)
            if not line:
                await asyncio.sleep(0.1)
                continue

            clean_line = line.strip()
            
            # Surface explicit cloudflared warnings and errors for visibility
            if any(term in clean_line.lower() for term in ["err", "error", "failed to create", "fatal"]):
                logger.warning(f"[CLOUDFLARED] {clean_line}")

            # Look for trycloudflare.com URL
            if not tunnel_url:
                match = URL_PATTERN.search(clean_line)
                if match:
                    candidate_url = match.group(0).strip()
                    logger.info(f"[TUNNEL] Captured candidate tunnel URL: {candidate_url}. Verifying origin health...")
                    tunnel_url = candidate_url
                    # Verify origin reachability asynchronously before promoting to CONNECTED
                    asyncio.create_task(self._verify_and_activate_tunnel(candidate_url))

        exit_code = self.process.poll() if self.process else -1
        logger.warning(f"[TUNNEL] cloudflared process ended with exit code {exit_code}")

        if not self._stop_requested:
            # Unexpected termination: transition to Reconnecting and backoff restart
            self.state = TunnelState.RECONNECTING
            self.active_url = None
            self._save_config(None)
            if self.on_url_change:
                try:
                    res = self.on_url_change(None)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass

            self.consecutive_crashes += 1
            # Exponential backoff capped at 30 seconds
            backoff_secs = min(30, 2 ** min(self.consecutive_crashes, 5))
            logger.info(f"[TUNNEL] Reconnecting in {backoff_secs}s (crash #{self.consecutive_crashes})...")
            await asyncio.sleep(backoff_secs)

            if not self._stop_requested:
                await self.start()
        else:
            self.state = TunnelState.OFFLINE
            self.active_url = None
            self._save_config(None)

    async def _verify_and_activate_tunnel(self, candidate_url: str):
        """Asynchronously validates that the origin server responds HTTP 200 before advertising CONNECTED state."""
        is_reachable = await self._validate_reachability(candidate_url, max_retries=15)
        if is_reachable and not self._stop_requested:
            self.active_url = candidate_url
            self.state = TunnelState.CONNECTED
            self.started_at = time.time()
            self.consecutive_crashes = 0
            self.error_message = None
            self._save_config(candidate_url)
            logger.info(f"[TUNNEL] Quick Tunnel verified healthy and reachable! Active URL: {candidate_url}")
            if self.on_url_change:
                try:
                    res = self.on_url_change(candidate_url)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as ex:
                    logger.error(f"[TUNNEL] Callback error: {ex}")
        elif not self._stop_requested:
            self.state = TunnelState.ERROR
            self.active_url = None
            self.error_message = (
                f"Cloudflare Edge active at {candidate_url}, but local origin port {self.port} "
                "is unreachable (HTTP 502/503). Ensure server.py is running!"
            )
            self._save_config(None)
            logger.error(f"[TUNNEL] {self.error_message}")
            if self.on_url_change:
                try:
                    res = self.on_url_change(None)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass

    async def _validate_reachability(self, candidate_url: str, max_retries: int = 15) -> bool:
        """Validates that candidate tunnel URL is genuinely online and local origin returns HTTP 200."""
        check_endpoint = f"{candidate_url}/health"

        for attempt in range(max_retries):
            if self._stop_requested:
                return False
            try:
                loop = asyncio.get_running_loop()
                def probe():
                    req = urllib.request.Request(
                        check_endpoint,
                        headers={"User-Agent": "SecureLink-Tunnel-Validator/1.0"}
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=3.0) as resp:
                            status = getattr(resp, "status", None) or (resp.getcode() if hasattr(resp, "getcode") else None)
                            # Only HTTP 200 (or acceptable redirect 307) confirms origin is genuinely responsive
                            return status in [200, 307]
                    except urllib.error.HTTPError as he:
                        # 502/503 indicates Cloudflare Edge is up but origin is not answering yet
                        logger.debug(f"[TUNNEL-PROBE] Origin not ready yet (HTTP {he.code})")
                        return False
                ok = await loop.run_in_executor(None, probe)
                if ok:
                    return True
            except Exception as e:
                logger.debug(f"[TUNNEL-PROBE] Attempt {attempt+1}/{max_retries} failed: {e}")
            await asyncio.sleep(1.0)
        return False

    async def stop(self) -> Dict[str, Any]:
        """Cleanly stops the tunnel process and removes config."""
        async with self._lock:
            self._stop_requested = True
            if self._monitor_task and not self._monitor_task.done():
                self._monitor_task.cancel()
            self._kill_process()
            self.state = TunnelState.OFFLINE
            self.active_url = None
            self.started_at = None
            self.error_message = None
            self._save_config(None)
            
            if self.on_url_change:
                try:
                    res = self.on_url_change(None)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass

            return self.get_status()

    def _kill_process(self):
        if self.process:
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            except Exception:
                pass
            self.process = None

    def _cleanup_orphaned_processes(self):
        """Kills previous cloudflared process managed by this instance."""
        if self.process:
            self._kill_process()

    def _save_config(self, url: Optional[str]):
        try:
            if url:
                with open(TUNNEL_CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump({
                        "cloud_tunnel_url": url,
                        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "state": self.state
                    }, f, indent=2)
            else:
                if os.path.exists(TUNNEL_CONFIG_FILE):
                    os.remove(TUNNEL_CONFIG_FILE)
        except Exception as e:
            logger.error(f"[TUNNEL] Config file error: {e}")

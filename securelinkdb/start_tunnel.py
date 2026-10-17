"""
SECURELINK MOBILE DATA CLOUD TUNNEL GATEWAY
Allows smartphones outside the campus Wi-Fi network (on cellular 4G/5G mobile data)
to seamlessly synchronize incidents, telemetry, and smart pin states with the Central System.

Powered by Cloudflare Quick Tunnels (Zero configuration, no account required, 100% free & HTTPS/WSS encrypted).
"""

import os
import sys
import re
import time
import json
import shutil
import urllib.request
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED_EXE = os.path.join(BASE_DIR, "cloudflared.exe")
TUNNEL_CONFIG = os.path.join(BASE_DIR, "tunnel_config.json")
CLOUDFLARED_DOWNLOAD_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

def ensure_cloudflared():
    # 1. Check if cloudflared is already in PATH or local directory
    if os.path.exists(CLOUDFLARED_EXE):
        return CLOUDFLARED_EXE
    
    in_path = shutil.which("cloudflared")
    if in_path:
        return in_path

    # 2. Automatically download portable cloudflared single-binary executable
    print("\n[SETUP] Portable cloudflared binary not found.")
    print(f"[SETUP] Downloading standalone cloudflared for Windows from Cloudflare GitHub releases...")
    print(f"        URL: {CLOUDFLARED_DOWNLOAD_URL}")
    
    def reporthook(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            percent = min(100.0, (downloaded / total_size) * 100)
            mb_down = downloaded / (1024 * 1024)
            mb_total = total_size / (1024 * 1024)
            sys.stdout.write(f"\r[DOWNLOADING] {mb_down:.1f}MB / {mb_total:.1f}MB ({percent:.1f}%)")
            sys.stdout.flush()

    try:
        temp_download = CLOUDFLARED_EXE + ".tmp"
        urllib.request.urlretrieve(CLOUDFLARED_DOWNLOAD_URL, temp_download, reporthook=reporthook)
        print("\n[SETUP] Download complete! Finalizing executable...")
        if os.path.exists(CLOUDFLARED_EXE):
            os.remove(CLOUDFLARED_EXE)
        os.rename(temp_download, CLOUDFLARED_EXE)
        print(f"[SETUP] Successfully installed portable cloudflared to: {CLOUDFLARED_EXE}\n")
        return CLOUDFLARED_EXE
    except Exception as e:
        print(f"\n[ERR] Could not auto-download cloudflared: {e}")
        print("[TIP] You can manually download cloudflared-windows-amd64.exe and place it as 'cloudflared.exe' in this directory.")
        return None

def notify_server(tunnel_url: str):
    # Save to tunnel_config.json
    try:
        with open(TUNNEL_CONFIG, "w", encoding="utf-8") as f:
            json.dump({"cloud_tunnel_url": tunnel_url, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}, f, indent=2)
    except Exception:
        pass

    # Notify running server.py on port 8080 if running
    try:
        payload = json.dumps({"cloud_tunnel_url": tunnel_url}).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:8080/api/cloud-tunnel", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            pass
    except Exception:
        # Server might not be running yet, that's fine as tunnel_config.json is saved
        pass

def main():
    print("=======================================================================")
    print("  SECURELINK CLOUD TUNNEL GATEWAY (MOBILE DATA / CELLULAR 4G/5G SYNC)  ")
    print("=======================================================================")
    print("  Enables teachers and staff on Cellular/Mobile Data to stay synced")
    print("  with Central System AI, Smart Pins, and real-time danger alerts.")
    print("=======================================================================\n")

    bin_path = ensure_cloudflared()
    if not bin_path:
        input("\nPress Enter to exit...")
        return

    port = 8080
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])

    cmd = [bin_path, "tunnel", "--url", f"http://127.0.0.1:{port}"]
    print(f"[TUNNEL] Starting Cloudflare Quick Tunnel forwarding to http://127.0.0.1:{port}...")

    # Start subprocess
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    tunnel_url = None
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()

            if not tunnel_url:
                match = url_pattern.search(line)
                if match:
                    tunnel_url = match.group(0).strip()
                    notify_server(tunnel_url)
                    print("\n" + "=" * 71)
                    print("  >>> SECURELINK MOBILE DATA CLOUD TUNNEL ACTIVE! <<<")
                    print("=" * 71)
                    print(f"  Public Tunnel URL:  {tunnel_url}")
                    print("=" * 71)
                    print("  INSTRUCTIONS FOR MOBILE PHONE (ON MOBILE DATA):")
                    print("  1. In the SecureLink Mobile Companion app on your phone:")
                    print("     Tap the header connection button ('SYNC CS').")
                    print("  2. In the 'Cloud Tunnel URL' field, paste this exact URL:")
                    print(f"     {tunnel_url}")
                    print("  3. Tap 'Apply & Sync Central System'.")
                    print("  4. The phone will show 'CS CLOUD' and receive all safety alerts,")
                    print("     telemetry, and voice streams over Cellular Data!")
                    print("=" * 71 + "\n")
    except KeyboardInterrupt:
        print("\n[TUNNEL] Stopping Cloud Tunnel...")
    finally:
        proc.terminate()
        try:
            if os.path.exists(TUNNEL_CONFIG):
                os.remove(TUNNEL_CONFIG)
        except Exception:
            pass
        print("[TUNNEL] Cloud Tunnel stopped.")

if __name__ == "__main__":
    main()

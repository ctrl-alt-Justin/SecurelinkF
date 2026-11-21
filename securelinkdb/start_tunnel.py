"""
SECURELINK MOBILE DATA CLOUD TUNNEL GATEWAY
Allows smartphones outside the campus Wi-Fi network (on cellular 4G/5G mobile data)
to seamlessly synchronize incidents, telemetry, and smart pin states with the Central System.

Powered by Cloudflare Quick Tunnels (Zero configuration, no account required, 100% free & HTTPS/WSS encrypted).
"""

import sys
import time
import asyncio
from tunnel_manager import CloudflareTunnelManager, TunnelState

async def async_main():
    print("=======================================================================")
    print("  SECURELINK CLOUD TUNNEL GATEWAY (MOBILE DATA / CELLULAR 4G/5G SYNC)  ")
    print("=======================================================================")
    print("  Enables teachers and staff on Cellular/Mobile Data to stay synced")
    print("  with Central System AI, Smart Pins, and real-time danger alerts.")
    print("=======================================================================\n")

    port = 8080
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])

    # Check if Central System server.py is already running on port 8080
    import urllib.request
    import json
    server_running = False
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/cloud-tunnel")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode())
            server_running = True
            if data.get("state") == "Connected" and data.get("cloud_tunnel_url"):
                print("=======================================================================")
                print("  >>> CENTRAL SYSTEM ACTIVE CLOUDFLARE TUNNEL DETECTED! <<<")
                print("=======================================================================")
                print(f"  Public Tunnel URL:  {data['cloud_tunnel_url']}")
                print("=======================================================================")
                print("  Central System AI is already running and tunneling to this URL.")
                print("  Press Ctrl+C to exit.\n")
                try:
                    while True:
                        await asyncio.sleep(2.0)
                except (KeyboardInterrupt, asyncio.CancelledError):
                    return
    except Exception:
        pass

    if not server_running:
        print(f"[NOTE] Central System AI Backend (server.py) is not yet detected on port {port}.")
        print("       The Cloudflare Tunnel will route incoming traffic to http://127.0.0.1:8080.")
        print("       Start 'python server.py' or open the Desktop Dashboard so requests can be processed.\n")

    mgr = CloudflareTunnelManager(port=port)
    if not mgr.is_installed():
        print("[SETUP] cloudflared binary not found!")
        inst = mgr.get_install_instructions()
        print(inst.get("instructions", "Please install cloudflared."))
        input("\nPress Enter to exit...")
        return

    print(f"[TUNNEL] Starting Cloudflare Quick Tunnel forwarding to http://127.0.0.1:{port}...")
    await mgr.start()

    print("[TUNNEL] Initializing tunnel and validating reachability...")
    for _ in range(30):
        if mgr.state == TunnelState.CONNECTED and mgr.active_url:
            break
        await asyncio.sleep(1.0)

    if mgr.state == TunnelState.CONNECTED and mgr.active_url:
        print("\n" + "=" * 71)
        print("  >>> SECURELINK MOBILE DATA CLOUD TUNNEL ACTIVE! <<<")
        print("=" * 71)
        print(f"  Public Tunnel URL:  {mgr.active_url}")
        print("=" * 71)
        print("  INSTRUCTIONS FOR MOBILE PHONE (ON MOBILE DATA):")
        print("  1. In the SecureLink Mobile Companion app on your phone:")
        print("     Tap the header connection button ('SYNC CS').")
        print("  2. In the 'Cloud Tunnel URL' field, paste this exact URL:")
        print(f"     {mgr.active_url}")
        print("  3. Tap 'Apply & Sync Central System'.")
        print("  4. The phone will show 'CS CLOUD' and receive all safety alerts,")
        print("     telemetry, and voice streams over Cellular Data!")
        print("=" * 71 + "\n")
        print("[TUNNEL] Press Ctrl+C to stop tunnel.")
    else:
        print(f"\n[WARN] Tunnel state: {mgr.state}. Error: {mgr.error_message}")

    try:
        while True:
            await asyncio.sleep(2.0)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[TUNNEL] Stopping Cloud Tunnel...")
    finally:
        await mgr.stop()
        print("[TUNNEL] Cloud Tunnel stopped.")

def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()

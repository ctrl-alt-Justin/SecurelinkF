import asyncio
import os
import sys
import time
import json

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "securelinkdb"))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import server
from fastapi.testclient import TestClient

def main():
    print("Testing live FastAPI + USB subsystem integration...")
    
    # 1. Run startup event to capture event loop and init devices
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Run startup
    loop.run_until_complete(server.startup_event())
    
    # Wait for USB manager to discover COM4, handshake and authenticate
    print("Waiting 4 seconds for USB handshake on physical COM4...")
    time.sleep(4.0)
    
    status = server.usb_mgr.get_status()
    print("USB Manager Status:", json.dumps(status, indent=2))
    
    # Check registered_devices
    pin_state = server.registered_devices.get("PIN-F360")
    print("Registered PIN-F360 state:", json.dumps(pin_state, indent=2))
    
    # Check assertions
    assert server.usb_mgr.is_authenticated, "USB Manager should be authenticated!"
    assert server.usb_mgr.device_id == "PIN-F360", "Device ID should be PIN-F360!"
    assert pin_state is not None, "PIN-F360 must be in registered_devices!"
    assert pin_state.get("online") is True, "PIN-F360 must be online!"
    assert pin_state.get("connection_source") == "USB", "Connection source must be USB!"
    assert pin_state.get("state") == "VAD ARMED", "State must be VAD ARMED!"
    
    print("\n>>> LIVE PHYSICAL HARDWARE USB VERIFICATION SUCCESSFUL! <<<")
    
    # Cleanup
    loop.run_until_complete(server.shutdown_event())
    loop.close()

if __name__ == "__main__":
    main()

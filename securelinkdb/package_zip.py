import zipfile
import os

release_dir = r"build\windows\x64\runner\Release"
output_zip = r"..\SecureLink_Desktop_Windows_x64.zip"

if os.path.exists(output_zip):
    try:
        os.remove(output_zip)
    except Exception:
        pass

print("Creating portable ZIP package...")
with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(release_dir):
        for f in files:
            full_p = os.path.join(root, f)
            rel_p = os.path.relpath(full_p, release_dir)
            arcname = os.path.join("SecureLink_Desktop", rel_p)
            zf.write(full_p, arcname)

    icon_p = r"windows\runner\resources\app_icon.ico"
    if os.path.exists(icon_p):
        zf.write(icon_p, os.path.join("SecureLink_Desktop", "app_icon.ico"))

    launcher_content = "@echo off\r\ntitle SecureLink AI Sentinel Dashboard\r\ncd /d \"%~dp0\"\r\nstart securelinkdb.exe\r\n"
    zf.writestr("SecureLink_Desktop/Launch_SecureLink.bat", launcher_content)

    readme_content = (
        "=======================================================\r\n"
        "SECURELINK AI CAMPUS SENTINEL - WINDOWS DESKTOP V2.0\r\n"
        "=======================================================\r\n\r\n"
        "INSTRUCTIONS:\r\n"
        "1. Run 'Launch_SecureLink.bat' or double-click 'securelinkdb.exe'\r\n"
        "2. The dashboard will automatically connect to the local AI inference engine on port 8080.\r\n"
        "3. Telemetry, VAD waveform audio, threat classifications, and OV3660 camera snapshots\r\n"
        "   will stream in real-time from active ESP32 smart pins.\r\n\r\n"
        "REQUIREMENTS:\r\n"
        "- Windows 10/11 64-bit\r\n"
        "- Network connection on the same subnet as the ESP32 pins (or via Cloudflare Quick Tunnel)\r\n"
    )
    zf.writestr("SecureLink_Desktop/README.txt", readme_content)

size_mb = os.path.getsize(output_zip) / (1024 * 1024)
print(f"Successfully created {os.path.abspath(output_zip)} ({size_mb:.1f} MB)")

import sys
import os

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
esp32_path = os.path.join(repo_root, "esp32code.txt")
ino_path = r"D:\Downloads\bullying_pin_v2\bullying_pin_v2.ino"

with open(esp32_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """                        if (sendOk) {
                            totalStreamBytes += BATCH_SIZE;
                        }
                    } else if (isOfflineRecording && offlineIncidentFile) {"""

replacement = """                        if (sendOk) {
                            totalStreamBytes += BATCH_SIZE;
                        }
                    } else if (hasActiveStream && ws.isConnected() && serverAuthenticated && !isUploadingArchive) {
                        sendOk = ws.sendBIN(txBuf, BATCH_SIZE);
                    } else if (isOfflineRecording && offlineIncidentFile) {"""

if target in content:
    content = content.replace(target, replacement)
    print("Added fallback Wi-Fi guard to steady chunk.")

with open(esp32_path, "w", encoding="utf-8") as f:
    f.write(content)

with open(ino_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Updated esp32code.txt and bullying_pin_v2.ino successfully.")

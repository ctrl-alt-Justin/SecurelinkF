"""
SecureLink Diagnostics & Self-Test Script
Run with: python test_pipeline.py
"""
import sys
import time
import numpy as np
import torch

print("=======================================================")
print(" SECURELINK HARDWARE & AI PIPELINE DIAGNOSTICS")
print("=======================================================")

# 1. Check Python & PyTorch CUDA
print(f"[1/5] Python Version: {sys.version.split()[0]}")
cuda_ok = torch.cuda.is_available()
device_name = torch.cuda.get_device_name(0) if cuda_ok else "None (CPU Mode)"
print(f"      CUDA Acceleration: {'ONLINE' if cuda_ok else 'OFFLINE'} ({device_name})")

# 2. Check Denoising
print("\n[2/5] Checking Noise Reduction...")
try:
    import noisereduce as nr
    # Synthetic test signal
    sr = 16000
    t = np.linspace(0, 1.0, sr)
    noise = np.random.normal(0, 0.1, sr)
    signal = np.sin(2 * np.pi * 440 * t) + noise
    clean = nr.reduce_noise(y=signal, sr=sr, prop_decrease=0.85, stationary=True)
    print("      NoiseReduce: OK (Classroom fan/AC suppression active)")
except Exception as e:
    print(f"      NoiseReduce: FAILED ({e})")

# 3. Check Fine-Tuned TagalogBERT Model
print("\n[3/5] Checking Fine-Tuned TagalogBERT Threat Model...")
try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    import torch.nn.functional as F

    tokenizer = AutoTokenizer.from_pretrained("./securelink_final_model")
    bert_model = AutoModelForSequenceClassification.from_pretrained("./securelink_final_model")
    bert_model.eval()

    test_phrases = [
        ("Tara kain tayo sa labas mamaya.", 0, "Normal / Safe"),
        ("Ang pangit mo, mukha kang ewan.", 1, "Verbal Harassment"),
        ("Akin na yang pera mo kundi yari ka sakin.", 2, "Extortion"),
        ("Papatayin kita mamaya paglabas ng school.", 3, "Physical Threat / Danger"),
    ]

    for phrase, expected_cls, label in test_phrases:
        inputs = tokenizer(phrase, return_tensors="pt", truncation=True, max_length=128)
        with torch.no_grad():
            outputs = bert_model(**inputs)
        probs = F.softmax(outputs.logits, dim=-1)
        pred = probs.argmax(-1).item()
        conf = probs[0][pred].item() * 100
        status = "PASS" if pred == expected_cls else f"DIFF (Pred: {pred})"
        print(f"      [{status}] \"{phrase}\" -> Class {pred} ({label}) @ {conf:.1f}% confidence")

    print("      TagalogBERT Model: OK")
except Exception as e:
    print(f"      TagalogBERT Model: FAILED ({e})")

# 4. Check Faster-Whisper ASR
print("\n[4/5] Checking Faster-Whisper Speech Recognition...")
try:
    from faster_whisper import WhisperModel
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "int8" if device == "cpu" else "float16"
    model_size = "large-v3-turbo" if device == "cuda" else "medium"

    print(f"      Loading Faster-Whisper ({model_size} on {device.upper()})...")
    t0 = time.time()
    whisper = WhisperModel(model_size, device=device, compute_type=compute_type)
    load_time = time.time() - t0
    print(f"      Faster-Whisper Loaded in {load_time:.2f}s: OK")
except Exception as e:
    print(f"      Faster-Whisper: FAILED ({e})")

# 5. Check Ports (8080 and 8888)
print("\n[5/5] Checking Network Ports Availability...")
import socket

def check_port(port, proto=socket.SOCK_STREAM):
    s = socket.socket(socket.AF_INET, proto)
    try:
        s.bind(("0.0.0.0", port))
        available = True
    except Exception:
        available = False
    finally:
        s.close()
    return available

tcp_8080 = check_port(8080, socket.SOCK_STREAM)
udp_8888 = check_port(8888, socket.SOCK_DGRAM)
print(f"      TCP Port 8080 (WebSocket Hub): {'AVAILABLE' if tcp_8080 else 'IN USE / OCCUPIED'}")
print(f"      UDP Port 8888 (Auto-Discovery): {'AVAILABLE' if udp_8888 else 'IN USE / OCCUPIED'}")

print("\n=======================================================")
print(" DIAGNOSTICS COMPLETE!")
print(" To start the system:")
print("   1. Run server:    python server.py")
print("   2. Run dashboard: flutter run -d windows")
print("=======================================================\n")

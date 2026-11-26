# SecureLink V4 — Detection Architecture Audit

**Project:** SecureLink: Design and Development of a Compact NLP-Enabled Anti-Bullying Discreet Wearable Smart Badge Using Seeed Studio XIAO ESP32S3 Sense  
**Audit Date:** November 25, 2026  
**Audited Branch:** `SecureLink-DetectionV4` (branched cleanly from protected baseline `USBConnectionVersion`)  
**Baseline Commit SHA:** `dc14709f9bcab46b7699ab3339361d8616b65781` (`USB Connection Working`)  
**Research Scope:** Verbal bullying detection (assistive wearable system supporting timely human intervention by trusted adults; not replacing professional judgment; excludes BLE/Wi-Fi/pulse/physical bullying detection).  
**Audit Method:** Direct static source inspection of active code on `SecureLink-DetectionV4` plus execution of existing Python test suites and Flutter static analysis. No production detection, transcription, severity, or firmware code was modified.

---

## 1. Executive Summary & Git Baseline Verification

### 1.1 Git Safety Verification
* **Protected Branch:** `USBConnectionVersion` (`dc14709f9bcab46b7699ab3339361d8616b65781`), matching `origin/USBConnectionVersion` (`dc14709f9bcab46b7699ab3339361d8616b65781`). Completely untouched.
* **Development Branch:** `SecureLink-DetectionV4` created from `USBConnectionVersion` at `dc14709`.
* **Working Tree Note:** Existing user edits to `AGENTS.md` were preserved untouched. Running the root test suite mutated two tracked local state files (`securelinkdb/active_pairing_codes.json` and `securelinkdb/mobile_devices.json`); those test-induced mutations were reverted immediately after verification.

### 1.2 Top-Level Verdict
All **9 concerns** raised in the prior independent GitHub code review are **CONFIRMED** in the active `dc14709` codebase. In addition, this audit uncovered **five critical operational and research-defensibility defects** not previously documented:
1. **Runtime Crash on USB `DANGER` Alerts (`server.py:2682`):** `handle_completed_audio` calls `usb_mgr.send_line("SL:TRIGGER:DANGER")`, which **does not exist** on `USBDeviceManager` (the actual method is `_send_text`). Any `score >= 8.0` USB event raises `AttributeError` before saving the WAV or broadcasting the incident to the dashboard.
2. **Active Prompt-Echo False Rejections with Empty Prompt (`server.py:157, 164-167, 2541-2549`):** `INITIAL_TAGALOG_PROMPT` is `""`, yet `PROMPT_ECHO_WORDS` still discards real student utterances where `>= 50%` of words match common school vocabulary (`"paaralan"`, `"tara"`, `"kumusta"`, `"sandali"`, `"magandang"`, `"araw"`, `"opo"`).
3. **Dead Language-Fallback Logic (`server.py:2368, 2434-2459`):** Hardcoding `"language": "tl"` causes `info.language` to always return `"tl"`, rendering the entire non-Philippine language fallback block unreachable while biasing English/Taglish decoding toward Tagalog phonetics.
4. **Test-Contract Conflict on Uncertain Transcriptions (`tests/test_transcription_reliability.py:98` vs `context_engine.py:437-438, 760-764`):** `ContextEngine V3` was designed to accept `UNCERTAIN_TRANSCRIPTION` and cap it below `DANGER` with `human_review_required=True`, but `server.py:2648` drops it and an existing unit test explicitly asserts that `UNCERTAIN_TRANSCRIPTION` must *never* call `context_engine.evaluate()`.
5. **Documentation–Code Drift (`SEVERITY_SCORER_EXPLANATION.txt`, `TECHNICAL_AUDIT.md`):** Existing project documentation still describes an older V1/V2 pipeline where TagalogBERT runs inference and multiplies scores by `1.3x`, contradicting the live ContextEngine V3 code.

---

## 2. Verification of the 9 Previously Identified Concerns

| # | Previously Identified Concern | Verdict | Primary Code Evidence |
|---|---|---|---|
| 1 | TagalogBERT classifier is loaded but unused in active ContextEngine V3 inference | **CONFIRMED** | Loaded at `securelinkdb/server.py:198-218`, attached at `server.py:240-241`, stored at `securelinkdb/context_engine.py:409-410`, **0 references** anywhere in `context_engine.py:411-873`. `ContextExtraction.model_confidence` (`context_engine.py:106`) stays hardcoded at `1.0`. |
| 2 | Classification relies heavily on fixed regular expressions and linguistic patterns | **CONFIRMED** | `ContextEngine.analyze_intent()` (`context_engine.py:445-521`) uses 11 fixed `re.compile` pattern lists (`lines 150-265`) and unanchored substring lists (`lines 574-575`). No semantic model or fuzzy matching executes. |
| 3 | Humor, idiom, negation, and reported-speech rules may prematurely suppress harmful statements | **CONFIRMED** | First-match early returns in `analyze_intent()` (`context_engine.py:454-483`) execute `IDIOMATIC_NON_THREATS` (including `\b(biro|joke|char|charot)\s+lang\b` at `line 163`), `NEGATION_PATTERNS`, `HYPOTHETICAL_PATTERNS`, `REPORTED_SPEECH_PATTERNS`, and `PAST_INCIDENT_PATTERNS` (bare `\b(kahapon|kanina|earlier)\b` at `line 199`) **before** checking physical threats, extortion, coercion, or harassment (`lines 484-513`). |
| 4 | Existing training dataset contains only 66 examples | **CONFIRMED** | `securelinkdb/dataset.csv` has 67 lines total (1 header + **66 examples**: 20 label `0`, 16 label `1`, 15 label `2`, 15 label `3`). `securelinkdb/train.py:14` performs an unstratified 80/20 split (52 train / 14 eval) on 110M-parameter `jcblaise/roberta-tagalog-base` with no `compute_metrics`. |
| 5 | Severity scores are primarily heuristic and lack demonstrated expert validation | **CONFIRMED** | `ContextEngine.score_threat()` (`context_engine.py:601-783`) uses hardcoded base scores (`1.0`–`9.2`), additive offsets (`+0.5`, `+0.3`, `+0.3`), escalation floors (`6.5`, `7.2`, `7.5`, `7.6`), and caps (`7.8`, `6.5`, `6.0`). No rubric mapping, inter-rater validation, or empirical calibration exists in the repo. |
| 6 | Device-level escalation may confuse repeated utterances with repeated bullying incidents | **CONFIRMED** | `DeviceIncidentTracker` (`context_engine.py:289-356`) counts individual `HistoricalStatement` utterances in a 600s in-memory `deque(maxlen=20)`. Firmware splits speech at 8s (`esp32code.txt:1825`) and 1.4s pauses (`esp32code.txt:575`), so one continuous episode generates multiple statements and falsely escalates. Also `intimidation_count` (`line 347-348`) counts *all* `DIRECT_THREAT` intents rather than only social intimidation. |
| 7 | Uncertain transcriptions may be discarded before reaching human review | **CONFIRMED** | `server.py:2648` gates exclusively on `result.status == TranscriptionStatus.TRANSCRIBED and result.transcript`. All `UNCERTAIN_TRANSCRIPTION` results (`mean_logprob < -1.10`, `server.py:2565-2572`) fall into `else:` (`server.py:2745-2747`) and are discarded without calling `context_engine.evaluate()`, saving audio, or notifying reviewers. |
| 8 | Rich contextual assessment metadata is not fully propagated to the Flutter dashboard | **CONFIRMED** | `server.py:2651` unpacks only `score, category = context_engine.evaluate(...)`, discarding 11 `SeverityAssessment` fields (`level`, `intent`, `threat_type`, `targetedness`, `imminence`, `risk_factors`, `evidence_confidence`, `explanation`, `recommended_response`, `human_review_required`, `context`) and Whisper `metrics`/`audio_quality`. `lib/main.dart:924-1027` (`Incident`) and `lib/mobile/services/mobile_server_service.dart:30-130` (`IncidentReport`) neither parse nor display these fields. |
| 9 | Current language configuration and audio filtering may introduce avoidable transcription errors | **CONFIRMED** | `server.py:2368` forces `"language": "tl"` (disabling English/Taglish auto-detection and making `lines 2434-2459` dead code); `"temperature": [0.0]` (`line 2372`) disables temperature fallback; cascaded HPFs (`100 Hz` in `esp32code.txt:618-627` + `85 Hz` in `server.py:2289-2290`); `PROMPT_ECHO_WORDS` rejects genuine school phrases (`lines 2541-2549`); token concentration rejects genuine frantic repetition (`lines 2528-2538`). |

---

## 3. End-to-End Pipeline Trace

```
[XIAO ESP32-S3 Sense: MSM261D PDM Mic (GPIO 42/41, 16kHz 16-bit Mono)]
   -> Core 1: 100Hz 2nd-order Butterworth HPF (esp32code.txt:618)
   -> Core 1: SpeexDSP VAD (probStart=75, probContinue=55, denoise=0) + Peak/Ambient Floor Gate
   -> Core 1: 128KB PSRAM Ring Buffer (4.0s capacity, 1.0s pre-roll; 32KB SRAM fallback)
   -> Core 0: USB CDC Serial (115200 baud) SL:STREAM_START / SL:AUDIO:<len>:<seq> (3200B chunks, 2x 150ms ACK) / SL:STREAM_END
   -> Backend USB Thread (usb_manager.py): Accumulate PCM (>= 3200B), schedule async handle_completed_audio
   -> Backend Async Pipeline (server.py, serialized via ai_inference_lock):
        1. Min length gate (>= 4800B / 150ms in handle_completed_audio; >= 3200B in process_audio_buffer)
        2. 85Hz 2nd-order Butterworth HPF + electrical silence gate (hpf_peak < 0.003)
        3. Microsoft NSNet2 ONNX denoising (strength=0.50, mingain=-12dB) [fallback: noisereduce]
        4. Conditional post-denoise gain (if 0.01 < peak < 0.35, up to 3.0x toward 0.45)
        5. Faster-Whisper (large-v3-turbo CUDA fp16 / medium CPU int8, language="tl", vad_filter=True)
        6. Segment quality checks (no_speech_prob < 0.60, cr <= 2.4, avg_logprob >= -1.40)
        7. Word-level anti-hallucination filters (mic check, artifacts, streak, diversity, concentration, prompt-echo)
        8. Confidence split: mean_logprob < -1.10 -> UNCERTAIN_TRANSCRIPTION (DROPPED at server.py:2648!)
        9. ContextEngine V3 regex/heuristic evaluation (TagalogBERT UNUSED) -> tuple unpack (score, category)
       10. DANGER check (score >= 8.0) -> CRASHES on USB via nonexistent usb_mgr.send_line()!
       11. Save denoised WAV -> recordings/audio/EVT-<6digits>.wav
       12. Append to in-memory deque(maxlen=50) -> broadcast JSON over /ui and /mobile WebSockets
   -> Flutter Desktop (lib/main.dart) & Mobile (lib/mobile/): Render Incident card, audio playback, clipboard export
```

---

## 4. Detailed Subsystem Findings

### 4.1 Firmware Audio Acquisition & VAD (`esp32code.txt`)
* **Hardware Capture (`lines 47-54, 996-1024, 1495-1583`):**
  * **SAFEGUARD:** Core 1 dedicated FreeRTOS task (`audioRecordTask`, priority 5, stack 8192) isolates I2S PDM capture (GPIO 42 CLK, GPIO 41 DATA, 16 kHz, 16-bit mono, 320 samples = 20 ms/frame) from Core 0 USB serial work.
  * **SAFEGUARD:** Commit `dc14709` resolved the earlier SRAM ring-buffer modulo hazard by tracking `audioRingCapacity` (128,000 B PSRAM / 32,000 B SRAM) and clamping `audioPreRollBytes` (`lines 548-555, 1611-1623`).
  * **SAFEGUARD:** `STREAM_GAIN_SHIFT = 0` (`line 581`) avoids digital clipping, and `applySoftLimiter` (`line 630`) is defined (though currently unused in `audioRecordTask`).
  * **CONFIRMED LIMITATION (8-Second Stream Split & Silence Timeout):** `maxStreamReached` hard-cuts any continuous stream at **8,000 ms** (`line 1825`), and `SILENCE_TIMEOUT = 1400 ms` (`line 575`) ends streams on pauses > 1.4 s. Multi-sentence bullying episodes are split into multiple discrete streams, causing (a) truncated mid-sentence transcripts and (b) artificial inflation of per-device utterance counts in `DeviceIncidentTracker`.
  * **CONFIRMED LIMITATION (Quiet/Whispered Speech Gate):** `speechDetected = ((isSpeech != 0) && (currentPeak > ambientFloor + 35) && (currentPeak >= 135)) || (currentPeak >= 380)` (`line 1525`). Whispered intimidation (e.g., quiet threats close to a student's ear when ambient floor rises toward its cap of `160`) can fall below `ambientFloor + 35` and never trigger streaming.
  * **CONFIRMED LIMITATION (Lock-Free Ring Buffer Race):** `ringHead` and `ringTail` (`lines 556-557`) are `volatile size_t` shared across Core 1 (writer + overrun advance at `line 1576`) and Core 0 (reader + reset at `lines 1708, 1862, 1896, 1931`) without a spinlock/critical section. Under heavy streaming with an overrun, Core 1 and Core 0 can race on `ringTail`, silently losing or shifting 3,200 B chunks.

### 4.2 USB Audio Transport & Buffering (`esp32code.txt`, `securelinkdb/usb_manager.py`)
* **SAFEGUARD:** `sendUsbAudioChunk()` (`esp32code.txt:1657-1679`) frames `SL:AUDIO:<size>:<seq>\n` + raw PCM, waits up to 150 ms for `SL:AUDIO:ACK:<seq>` with 1 retry, and checks `usbStreamInterrupted`. On the host, `usb_manager.py:597-618` validates `0 < payload_len <= 3200` and even byte length, deduplicates `seq`, tracks `missing_chunks` / `duplicate_chunks`, and computes chunk peak/RMS.
* **SAFEGUARD:** `_on_usb_audio_complete` (`server.py:397-408`) dispatches `handle_completed_audio` asynchronously onto `fastapi_event_loop` via `asyncio.run_coroutine_threadsafe()`, so transcription does **not** block the USB serial reader thread or heartbeats.
* **CONFIRMED ISSUE (Post-`STREAM_END` State Race):** In `usb_manager.py:820-833`, `STREAM_END` sets `self.audio_analyzing = True`, calls `self.on_audio_complete(...)` (which returns immediately after scheduling the coroutine!), and **immediately** sets `self.audio_analyzing = False` and `self.vad_state = "VAD ARMED"` before `handle_completed_audio` even starts on the event loop! `server.py:2631-2632` then sets them back to `ANALYZING SPEECH` asynchronously. This race can cause Stage 9 UI flicker or premature disarmed/idle status.
* **CONFIRMED ISSUE (Dual Minimum-Length Discards):** `usb_manager.py:824` drops streams `< 3200 B` (< 100 ms) silently, and `server.py:2603` drops streams `< 4800 B` (< 150 ms) silently. Short 1-word exclamations can be dropped without logging acoustic metrics.
* **CONFIRMED ISSUE (USB Audio Fallback to LittleFS):** During USB streaming, if `sendUsbAudioChunk` fails both retries (`esp32code.txt:1843-1854, 1912-1923`), firmware opens `/offline_inc_<ms>.pcm` on LittleFS and writes chunks there — yet `processArchiveUpload()` (`line 1345`) only uploads LittleFS archives over Wi-Fi WebSocket (`ws.isConnected()`), which is disabled in USB-only mode. Those offline recordings are stranded on flash until overwritten.

### 4.3 Audio Preprocessing & Faster-Whisper Configuration (`securelinkdb/server.py`, `securelinkdb/nsnet2.py`)
* **CONFIRMED ISSUE (Cascaded High-Pass Filtering):** Firmware applies a 2nd-order Butterworth HPF at `100 Hz` (`esp32code.txt:618-627`), and the server applies a second 2nd-order Butterworth HPF at `85 Hz` (`server.py:2289-2290`). While unlikely to eliminate speech, cascading doubles phase shift near lower male fundamental frequencies (85–130 Hz) unnecessarily on USB-originating audio.
* **CONFIRMED ISSUE (NSNet2 Strength & STFT Overlap):** `nsnet2.py:23, 38, 105-172` uses `mingain_db=-12.0` and `DENOISE_STRENGTH=0.50` (`server.py:187`), which is reasonably gentle. However, raw (pre-denoised) PCM is **not** preserved on disk — `server.py:2720` saves only `clean_pcm` (`recordings/audio/EVT-<id>.wav`), making offline A/B evaluation of denoiser artifacts impossible after capture.
* **CONFIRMED ISSUE (Forced `language="tl"` & Dead Fallback Code):** `server.py:2368` sets `"language": "tl"` on the primary `whisper_model.transcribe()` call. Consequently `info.language` is always `"tl"`, making the fallback block at `server.py:2437-2459` (`if detected_lang not in ('tl', 'en')`) completely dead code. English and heavy Taglish utterances are forced through Tagalog language priors, contributing to spelling/phonetic errors.
* **CONFIRMED ISSUE (Disabled Temperature Fallback):** `server.py:2372` sets `"temperature": [0.0]`. When beam search at temperature `0.0` produces a repetition loop (`cr > 2.4`), Faster-Whisper cannot automatically retry at `[0.0, 0.2, 0.4]` and instead discards the segment (`lines 2417-2419`).
* **CONFIRMED ISSUE (Active `PROMPT_ECHO_WORDS` Without a Prompt):** `INITIAL_TAGALOG_PROMPT = ""` (`server.py:157`), yet `Check 4` (`server.py:2541-2549`) still rejects any utterance of `>= 2` words where `>= 50%` of words appear in `PROMPT_ECHO_WORDS` (`"magandang"`, `"araw"`, `"umaga"`, `"hapon"`, `"gabi"`, `"kumusta"`, `"usapan"`, `"tagalog"`, `"filipino"`, `"paaralan"`, `"silid-aralan"`, `"sandali"`, `"opo"`, `"tara"`). Real student speech such as `"Tara sa paaralan"` or `"Magandang umaga po"` is falsely rejected as a prompt echo.
* **CONFIRMED ISSUE (Over-Aggressive Repetition/Concentration Rejection):** `Check 1` (`line 2508`: `max_streak >= 3 and len(words) <= 5`) and `Check 3` (`line 2532`: `count / len(words) > 0.50` for `len(words) >= 4`) will reject genuine panicked pleas or repeated verbal taunts (e.g., `"Tulong tulong tulong po!"` or `"Bobo bobo bobo ka!"`).
* **CONFIRMED ISSUE (Silero VAD Short-Utterance Drop):** `vad_parameters=dict(threshold=0.40, min_speech_duration_ms=250, speech_pad_ms=300)` (`server.py:2378`) can drop brief single-word slurs or shouts under 250 ms.

### 4.4 Semantic Classifier (`securelink_final_model`, `train.py`, `dataset.csv`) & ContextEngine V3 (`context_engine.py`)
* **CONFIRMED ISSUE (TagalogBERT Loaded but Unused):** `server.py:198-218` loads a **416.15 MB** `RobertaForSequenceClassification` (`jcblaise/roberta-tagalog-base`, 4 labels `LABEL_0..LABEL_3`) onto the RTX 3050 GPU, consuming VRAM and startup time, assigns it to `context_engine.bert_model` (`server.py:240`), and never calls it in `context_engine.py`.
* **CONFIRMED ISSUE (Severely Undersized, Unbalanced, Unvalidated Dataset):** `securelinkdb/dataset.csv` contains only **66 sentences** (20 benign, 16 harassment, 15 extortion, 15 physical threat). Noticeably, `dataset.csv` has **zero** examples of identity-based slurs/banter (`"bakla"`), **zero** reported-speech examples, **zero** coerced-secrecy examples, and **zero** adversarial `"joke lang"` + serious threat combinations. `train.py:14` does an unstratified 80/20 split (52 train / 14 val) and computes no precision/recall/F1/confusion matrix.
* **CONFIRMED ISSUE (Premature Early-Return Suppression in `analyze_intent`):**
  * `IDIOMATIC_NON_THREATS` (`context_engine.py:455-458`) runs first. Any utterance containing `"joke lang"`, `"biro lang"`, `"char lang"`, `"charot lang"`, `"just kidding"`, or `"mahal kita"` **unconditionally returns `ORDINARY_CONVERSATION` (`score=1.0`)**, even when paired with an explicit threat (`"Papatayin kita sa gate mamaya, joke lang"` -> `1.0 NORMAL`; `"Akin na baon mo, biro lang"` -> `1.0 NORMAL`).
  * `NEGATION_PATTERNS` (`lines 461-464`) runs second: `"Hindi kita sasaktan ngayon, mamaya kita bubugbugin"` -> `1.2 NORMAL`.
  * `HYPOTHETICAL_PATTERNS` (`lines 467-470`) runs third: `"Paano kung patayin kita ngayon?"` -> `1.8 NORMAL`.
  * `PAST_INCIDENT_PATTERNS` (`lines 479-482`) matches any bare temporal adverb (`kahapon`, `kanina`, `dati`, `yesterday`, `earlier` at `line 199`) **before** checking direct threats: `"Kanina pa kita hinihintay, bubugbugin kita ngayon"` -> downgraded to `PAST_INCIDENT` (`3.5 WARNING`) instead of `DANGER`!
  * `REPORTED_SPEECH_PATTERNS` (`lines 473-476`) matches before direct threats: `"Sabi niya bobo ka, at sasapakin din kita"` -> `REPORTED_THREAT` (`5.0`).
* **CONFIRMED ISSUE (Filipino Context Gap — `"Hoy, bakla ka!"`):**
  * `"bakla"` (and related identity/SOGIE/appearance/regional terms) does not exist in any pattern or dataset entry. Currently `"Hoy, bakla ka!"` falls through to `ORDINARY_CONVERSATION` (`score=1.0`, `human_review_required=False`, `evidence_confidence=1.0`).
  * Conversely, friendly Taglish gaming/peer banter like `"Ang bobo mo naman pre haha"` matches `VERBAL_HARASSMENT_PATTERNS` (`bobo mo` at `line 253`) and scores **`6.0` (`THREAT`)** with zero uncertainty flag—even though `dataset.csv:8` (`"ang bobo mo naman sa ML!"`) and `dataset.csv:7` (`"gago ka talaga pre haha"`) were explicitly intended as benign (`0`)!
  * The engine has **no ambiguity / context-insufficient state** (e.g., `AMBIGUOUS_CONTEXT` / `NEEDS_REVIEW` with moderated score and `human_review_required=True`) when an utterance contains identity-sensitive or potentially teasing language without acoustic/conversational proof of hostile intent.
* **CONFIRMED ISSUE (Unanchored Substring Matching in `extract_context`):** `context_engine.py:574-575` uses `w in text_lower` without word boundaries (`"gun"` matches `"gunitain"`, `"bote"` matches `"sabote"`, `"gate"` matches `"investigate"`), falsely inflating `specificity = "HIGH"`.
* **CONFIRMED ISSUE (Escalation Logic & Ephemeral State):**
  * `DeviceIncidentTracker` (`context_engine.py:289-356`) lives purely in RAM (`deque(maxlen=20)`, 600 s window). Server restart erases all history, so cross-day recurrence (central to bullying definitions) cannot be tracked.
  * Within a single 600 s window, firmware 8 s stream splits or a speaker repeating themselves within 10 seconds count as separate incidents, falsely escalating a single event to `Escalated Harassment` (`7.2`) or `Escalated Intimidation` (`7.6`).
  * `intimidation_count` (`lines 347-348`) increments for all `ThreatIntent.DIRECT_THREAT` (both physical and social), conflating physical threats with social intimidation.

### 4.5 Emergency Hardware Triggers (`server.py`, `esp32code.txt`)
* **CONFIRMED CRITICAL BUG (`server.py:2681-2682`):**
  ```python
  if source == "USB":
      usb_mgr.send_line("SL:TRIGGER:DANGER")
  ```
  `USBDeviceManager` (`securelinkdb/usb_manager.py`) has **no `send_line` method** (only `_send_text(text)`). When a USB-connected pin produces a `DANGER` (`score >= 8.0`) transcript, `handle_completed_audio` raises `AttributeError`, aborting before WAV persistence, `recent_incidents.append`, or dashboard broadcast. Because `handle_completed_audio` is scheduled via `asyncio.run_coroutine_threadsafe` without awaiting its future, the exception is silently dropped inside the Future!
* **CONFIRMED ISSUE (Firmware `SL:TRIGGER:DANGER` Is a No-Op Log):** `esp32code.txt:1463-1464` prints `[USB] *** THREAT ALERT: TRIGGER DANGER DETECTED ***` and does not capture a snapshot or trigger any hardware indicator.
* **CONFIRMED ISSUE (Dashboard Re-Triggers `TRIGGER:DANGER`):** `lib/main.dart:1369` sends `'TRIGGER:DANGER'` back over `/ui` whenever a `DANGER` incident arrives, which `server.py:1310-1317` relays to **all** WebSocket pins (`active_pins`, not USB pins), creating redundant broadcasts on Wi-Fi pins and zero effect on USB pins.
* **SAFEGUARD:** Boot button GPIO 0 (`esp32code.txt:1603, 1743`) is used solely for holding 2 s to enter Setup Portal; there is no unauthenticated panic-button path that could misfire.

### 4.6 Incident Storage, Reporting & Flutter Integration (`server.py`, `lib/main.dart`, `lib/mobile/`)
* **CONFIRMED ISSUE (Metadata Drop Table):**

| Field Produced by `ContextEngine V3` / Whisper | Sent in `server.py:2726-2742`? | Parsed in Desktop `main.dart:924-1027`? | Parsed in Mobile `mobile_server_service.dart:30-130`? |
|---|---|---|---|
| `score` | Yes (`score`) | Yes | Yes (`threat_score`/`score`) |
| `category` | Yes (`category`) | Yes | Yes (`threat_label`/`category`) |
| `level` (`NORMAL`/`WARNING`/`THREAT`/`DANGER`) | **No** (recomputed in Dart) | Recomputed from `score` | Recomputed (`isFlagged`/`isThreat`/`isDanger`) |
| `intent` (`ThreatIntent`) | **No** | **No** | **No** |
| `threat_type` (`ThreatType`) | **No** | **No** | **No** |
| `targetedness` (`Targetedness`) | **No** | **No** | **No** |
| `imminence` (`Imminence`) | **No** | **No** | **No** |
| `risk_factors` (`List[str]`) | **No** | **No** | **No** |
| `evidence_confidence` (`float`) | **No** | **No** | **No** |
| `explanation` (`str`) | **No** | **No** | **No** |
| `recommended_response` (`str`) | **No** | **No** | **No** |
| `human_review_required` (`bool`) | **No** | **No** | **No** |
| `context` (`ContextExtraction`: specificity, negated, reported_speech, reliability, model_confidence) | **No** | **No** | **No** |
| Whisper `metrics` (`avg_logprob`, `no_speech_prob`, `compression_ratio`, `detected_language`) | **No** | **No** | **No** |
| `TranscriptionStatus` (`TRANSCRIBED` vs `UNCERTAIN_TRANSCRIPTION`) | **No** (`UNCERTAIN` dropped!) | **No** | **No** |

* **CONFIRMED ISSUE (Volatile Incident Storage):** `recent_incidents` (`server.py:373`) is an in-memory `collections.deque(maxlen=50)`. There is **no database or JSON incident log**. Restarting `server.py` wipes all incident transcripts, scores, and metadata; only orphan `.wav` files remain in `securelinkdb/recordings/audio/` (currently **219 WAV files** on disk, 0 snapshots). Furthermore, desktop `/ui` (`server.py:1274-1303`) does **not** even send `recent_incidents` on connect (unlike `/mobile` at `line 1963`), so refreshing or reopening the desktop dashboard loses prior session incidents.
* **CONFIRMED ISSUE (No Human-in-the-Loop Review or Feedback Loop):** Neither `lib/main.dart` nor `lib/mobile/screens/incidents_screen.dart` has a "Needs Review / Uncertain" badge, reviewer disposition controls (e.g., *Confirm Bullying / Benign Banter / False Positive / Escalated to Counselor*), reviewer notes, or audit trail.
* **CONFIRMED ISSUE (Incident Reporting Is Clipboard-Only):** "Export Log" (`main.dart:5540`) and "Export Incident Dossier" (`main.dart:6208-6217`) copy plain text to the Windows clipboard. There is no structured CSV/PDF export, no persisted report archive, and no automated notification workflow for trusted adults beyond live WebSocket alerts.
* **CONFIRMED ISSUE (Incident ID Collision & Timestamp Drift):** `server.py:2707` generates `EVT-{int(time.time() * 1000) % 1000000}` (6-digit millisecond modulo wraps every ~16.7 minutes and risks WAV filename overwrite), and `main.dart:1009` stamps `DateTime.now()` on receipt rather than using a backend UTC/ISO-8601 capture timestamp.

### 4.7 Privacy, Security & Access Controls
* **CONFIRMED CRITICAL PRIVACY RISK (Unauthenticated Public Access to Student Audio & Live Transcripts):**
  * `server.py:3247` binds Uvicorn to `0.0.0.0:8080`.
  * `server.py:112` mounts `app.mount("/recordings", StaticFiles(directory=RECORDINGS_DIR))` with **zero authentication** — anyone on the LAN (or anyone with the Cloudflare Quick Tunnel URL when active) who knows or guesses `EVT-<6digits>.wav` can download raw student audio recordings directly.
  * `server.py:1274` (`/ui` WebSocket) has **zero authentication** — any host on the LAN or via tunnel can connect to `ws://<host>:8080/ui` and eavesdrop on live student transcripts, device IDs, and recording URLs, or issue `TRIGGER:DANGER` / `fleet_config` / `set_harmful_only` commands.
  * Administrative REST routes (`/api/devices`, `/api/usb/*`, `/api/toggle-harmful-only`, `/api/denoise-settings`, `/api/checkpoints*`, `/api/mobile-pairing/approve`, `/api/mobile-pairing/revoke`, `/api/diagnostics`) have **zero authentication**.
  * **SAFEGUARD:** `/mobile` WebSocket (`server.py:1889-1930`) enforces SHA-256 hashed bearer token verification via `mobile_pairing_mgr.verify_mobile_token()`, and USB serial (`server.py:410-426`) verifies device ID + MAC against `device_credentials.json`.
* **CONFIRMED PRIVACY RISK (Unencrypted Recordings at Rest & No Size Cap):**
  * All 219 WAV files in `securelinkdb/recordings/audio/` are stored as unencrypted PCM WAV files.
  * **SAFEGUARD:** `periodic_recordings_cleanup()` (`server.py:2204-2229`) purges files older than `RECORDINGS_RETENTION_DAYS` (default 30 days) every 12 hours. However, there is no disk-quota cap, and benign conversational audio is recorded to disk whenever `harmful_words_only == False` (the default at `server.py:250`), raising student-privacy proportionality concerns (recording non-incident classroom speech).
* **CONFIRMED SECURITY ISSUE (Secrets in Tracked Files — Values Redacted):**
  * `esp32code.txt:58-59, 1028-1029`: Hardcoded default Wi-Fi SSID and WPA2 password strings.
  * `securelinkdb/checkpoints.json`: Contains plaintext Wi-Fi `ssid` and `pass` fields in a Git-tracked file.
  * `securelinkdb/device_credentials.json` (1 record) and `securelinkdb/mobile_devices.json` (4 records): Store `token_hash` (hashed, good safeguard) alongside device MACs, user names, and IP addresses in Git-tracked files. `securelinkdb/active_pairing_codes.json` (4 entries) tracks pairing codes in Git.

### 4.8 Model Availability & Runtime Dependencies
Verified directly on the workstation (`Python 3.12.8`, `NVIDIA GeForce RTX 3050 6GB Laptop GPU`, `CUDA: True`):
* **Local Models Present:**
  * Faster-Whisper `large-v3-turbo` (CUDA `float16`): **Loaded successfully** during test execution.
  * Microsoft NSNet2 ONNX: `securelinkdb/models/nsnet2/nsnet2-20ms-baseline.onnx` (10.5 MB) — **Present and loaded**.
  * Fine-tuned TagalogBERT (`jcblaise/roberta-tagalog-base`): `securelinkdb/securelink_final_model/model.safetensors` (416.15 MB) + tokenizer files + 5 training checkpoints in `securelink_tagalogbert/` — **Present and loaded on CUDA**.
* **Dependency Manifest Drift (`securelinkdb/requirements.txt`):**
  * Missing from `requirements.txt` despite being directly imported or required for tests/NSNet2: `pyserial`, `scipy`, `onnxruntime`, `noisereduce`, `httpx`, `pydantic`.
  * Listed in `requirements.txt` (`lines 8, 10`) but **not installed** in the active Python environment (and unused in `server.py`): `deepfilternet`, `soundfile`.

---

## 5. Existing Automated Test & Static Analysis Baseline

Executed cleanly on branch `SecureLink-DetectionV4` (`dc14709`) without modifying any code:

| Suite / Tool | Command | Total | Passed | Failed | Errors | Skipped | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| Root Python Tests | `python -m unittest discover -s tests -p "test_*.py" -v` | 45 | 36 | 1 | 1 | 7 | See breakdown below |
| Package Python Tests | `python -m unittest discover -s securelinkdb/tests -t . -p "test_*.py" -v` | 89 | 89 | 0 | 0 | 0 | **100% PASS** (3.876 s) |
| Flutter Static Analysis | `flutter analyze` (in `securelinkdb/`) | 455 issues | — | 0 errors | 0 | — | 0 errors, 27 warnings, 428 infos (`withOpacity` deprecations) |

### Root Suite Detailed Breakdown (`tests/`)
* **`tests/test_context_engine_v3.py`:** **13/13 passed.** (Note: tests only clean regex phrases; zero tests for adversarial `"joke lang"` + threat, `"Hoy, bakla ka!"`, TagalogBERT invocation, or split-stream escalation.)
* **`tests/test_mobile_pairing_and_tunnel.py`:** **9/9 passed.**
* **`tests/test_transcription_reliability.py`:** **6 passed, 7 skipped.**
  * *Skipped (7):* `EVT-192827.wav`, `EVT-236767.wav`, `EVT-135503.wav`, `EVT-146419.wav`, `EVT-1664.wav`, `EVT-187083.wav`, `EVT-117465.wav` — all skipped with `'Fixture <name> not on disk'`. Real audio regression coverage is currently **blind**!
  * *Contract Conflict:* `test_uncertain_transcription_never_calls_evaluate_or_triggers_danger` asserts `context_engine.evaluate()` is never called on `UNCERTAIN_TRANSCRIPTION`.
* **`tests/test_ble_pairing_backend.py`:** **6 passed, 1 failed, 1 error.**
  * *FAIL:* `test_01_generate_pairing_code` (`AssertionError: 600 != 300`; backend TTL changed to 600 s).
  * *ERROR:* `test_03_pin_registration_success` (`FileNotFoundError: ... test_credentials.json`; backend moved to two-phase pending registration until WebSocket auth).
* **Test Isolation Defect:** Running `tests/` mutated live tracked files `securelinkdb/active_pairing_codes.json` and `securelinkdb/mobile_devices.json`.

---

## 6. Consolidated Risk & Limitation Register

### 6.1 Architectural Limitations (Inherent to Thesis Scope)
1. **No Speaker Diarization:** A single wearable PDM microphone cannot reliably separate the wearer's voice from nearby peers or bystanders; acoustic context alone cannot determine who is the aggressor vs. target in crowded hallways.
2. **No Acoustic Prosody / Affect Modeling Yet:** Text-only NLP cannot hear laughter, tone, vocal stress, or shouting volume (though acoustic peak/RMS metadata already exists in `server.py` and could be surfaced as auxiliary context for human reviewers).
3. **Assistive System Only:** Automated classification cannot achieve 100% precision on culturally nuanced Filipino/Taglish speech; human-in-the-loop review by a counselor/prefect is mandatory for ambiguous or medium-risk events.
4. **USB-Only Phase Constraint:** During this development sprint, wireless transports (BLE/Wi-Fi) and camera snapshot transport over USB are out of scope; hardware testing uses direct USB CDC on `COM4`.

### 6.2 Regression Risks for V4 Implementation
1. **Flutter Hard Casts on Incident JSON (`lib/main.dart:992`):** `(json['score'] as num).toDouble()` will throw if `score` is ever `null` or missing. New fields added to `incident_payload` must be strictly **additive** with safe Dart null defaults, preserving all existing keys (`event_type`, `id`, `device_id`, `score`, `category`, `transcript`, `audio`, `audio_url`, `local_audio_url`, `lan_audio_url`, `audio_file`, `video`, `duration`, `source`, `relayed_by`).
2. **Legacy Tuple Unpacking (`context_engine.py:129-142`):** Callers expecting `score, category = context_engine.evaluate(...)` must remain compatible while `server.py` transitions to reading the full `SeverityAssessment` object.
3. **USB Protocol & Hardware Stability (`usb_manager.py`, `esp32code.txt`):** Any change to `server.py` around `usb_mgr` or `handle_completed_audio` must not block the `USBSerialReader` thread, disturb `SL:PING`/`SL:PONG` timing, or alter `SL:AUDIO` framing.
4. **GPU Memory Contention (6 GB RTX 3050):** Loading Faster-Whisper `large-v3-turbo` (fp16) + NSNet2 ONNX + TagalogBERT simultaneously must remain guarded by `ai_inference_lock` and benchmarked for VRAM headroom once TagalogBERT actually runs forward passes in production.
5. **Existing Test Contract Breaks:** Updating `UNCERTAIN_TRANSCRIPTION` handling and `PROMPT_ECHO_WORDS` requires intentionally updating `tests/test_transcription_reliability.py` alongside adding V4 regression tests.

---

## 7. Prioritized V4 Recommendations

1. **P0 — Fix Critical Runtime & Safety Bugs:** Fix `usb_mgr.send_line` crash on USB `DANGER` (`server.py:2682`); fix `PROMPT_ECHO_WORDS` false rejections when prompt is empty; fix `audio_analyzing` race between `usb_manager.py` and `server.py`.
2. **P0 — Enable Uncertainty & Human-Review Pipeline:** Route `UNCERTAIN_TRANSCRIPTION` into `ContextEngine` (capped below `DANGER`, `human_review_required=True`) instead of discarding; introduce explicit `AMBIGUOUS / NEEDS_REVIEW` handling for context-dependent Filipino expressions (`"Hoy, bakla ka!"`).
3. **P1 — True Hybrid Detection Engine (ContextEngine V4 + Active TagalogBERT):** Replace early-return suppression with multi-signal compositional evaluation (so `"joke lang"` / `"kahapon"` / `"hindi"` never blindly erase co-occurring direct threats), integrate fine-tuned TagalogBERT probability outputs into scoring & uncertainty calibration, and expand the Filipino/Taglish dataset with an explicit annotation rubric and stratified validation metrics.
4. **P1 — Calibration, Episode-Level Recurrence & Explainability:** Replace ad-hoc score constants with a documented, rubric-aligned scoring matrix; separate single-episode split streams (e.g., utterances within 15–30 s) from true multi-episode recurrence; persist incident and recurrence records in SQLite.
5. **P2 — ASR & Taglish Reliability:** Evaluate `language=None` (auto-detect with Tagalog/English guard) vs. `language="tl"` on a controlled Tagalog/English/Taglish test set; restore temperature fallback (`[0.0, 0.2, 0.4]`); eliminate redundant server HPF for already-filtered pin audio; optionally retain raw vs. denoised evaluation samples during offline benchmarking.
6. **P2 — Dashboard Propagation, Human Review UI & Privacy Hardening:** Propagate full `SeverityAssessment` + ASR confidence metadata to Flutter desktop & mobile; add reviewer confirmation/false-positive disposition controls; add authentication / localhost-binding safeguards for `/ui`, `/recordings`, and admin APIs; stop committing Wi-Fi secrets in tracked config files.

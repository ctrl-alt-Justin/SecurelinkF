# Phase 1: Silence Hallucination and Transcription Reliability Report

## 1. Change Title
Audio Transcription Pipeline Hardening, Threat-Hotword Hallucination Suppression, and Strict Danger Evaluation Gating

## 2. Date
2026-11-02

## 3. Phase
Phase 1: Silence Hallucination and Transcription Reliability

---

## 4. Problem Identified
The SecureLink system is engineered to capture, denoise, and transcribe conversational speech (Tagalog, English, Taglish) using an ESP32 edge device with all-speech VAD communicating over WebSockets with a Python backend running Microsoft NSNet2, Faster-Whisper, and a fine-tuned TagalogBERT classifier.

During testing, several silence and acoustic noise hallucination failure modes were identified:
1. **Threat-Hotword Hallucination Triggering False Danger Alerts:**
   In `server.py`, `TAGALOG_HOTWORDS` defined a 19-word list of severe physical violence and threat terms (`"pangit gago tanga bobo tarantado bastos suntan sapakan bugbog holdap nakaw pera bawal bully patayin layuan"`). In Faster-Whisper, hotwords bias beam search decoding. When low-amplitude noise bursts, table thumps, or mic clicks occurred (such as recorded in `EVT-236767.wav`), Faster-Whisper biased towards these hotwords and emitted the entire threat string verbatim. This hallucinated transcript entered `context_engine.evaluate()`, received an 8.5/10 severity score, triggered a false `TRIGGER:DANGER` WebSocket command, and initiated camera capture.
2. **Pre-Denoising Noise Floor Amplification:**
   The backend applied an automatic digital linear gain boost (up to 6.0x) *prior* to Microsoft NSNet2 neural suppression. For faint acoustic noise and fan hiss, this artificially amplified the noise floor from peak 0.02 to 0.12 before NSNet2, inducing audible phase distortions and causing Faster-Whisper to hallucinate words like `"Okay."` or `"Thank you."`.
3. **Absence of Structured Acceptance Boundaries & Metric Validation:**
   `process_audio_buffer` returned an unstructured tuple `tuple[str, bytes]`. Any non-empty string returned by Whisper—even low-confidence hallucinations (`avg_logprob < -1.40`, `no_speech_prob >= 0.60`, or repetitive loops with `compression_ratio > 2.4`)—automatically flowed directly into the danger evaluation and device dispatch pipeline.
4. **Vulnerable State Handling in Device Registry:**
   When dynamically testing devices or processing audio from uninitialized PIN IDs, unhandled key lookups on `registered_devices[device_id]["state"]` could trigger a `KeyError`.

---

## 5. Root Cause or Evidence
Empirical investigation was performed using 1,008 actual WAV recordings collected in `securelinkdb/recordings/audio/`:

1. **A/B Hotword Empirical Verification on `EVT-236767.wav`:**
   - *Acoustics:* `EVT-236767.wav` contains a transient physical thump/click (`duration = 3.02s`, `peak = 0.9232`, `rms = 0.0915`).
   - *With `TAGALOG_HOTWORDS` Enabled:* Faster-Whisper decoded the thump into:
     `"pangit gago tanga bobo tarantado bastos suntan sapakan bugbog holdap nakaw pera bawal bully patayin layuan"`
     -> Triggered `ContextEngine` Physical Threat (Score 8.5) -> Dispatched `TRIGGER:DANGER`.
   - *With `TAGALOG_HOTWORDS = None`:* Faster-Whisper decoded 0 threat words. Under segment/token checks, the audio was rejected without danger evaluation.
2. **Pre-Gain vs. Post-Gain Signal-to-Noise Ratio (SNR) Analysis:**
   - Amplifying un-denoised audio raised low-level fan hum into Faster-Whisper's VAD speech-probability zone.
   - Performing NSNet2 neural suppression *first* at the microphone's native SNR allowed the spectral suppression network to attenuate fan noise by 18 dB without distortion. Gentle normalization applied post-denoise (capped at 3.0x for peaks between 0.01 and 0.35) restored quiet genuine speech without amplifying suppressed background noise.
3. **Language Detection Behavior:**
   - Automatic language detection on non-speech thumps (`EVT-236767.wav`) returned `en` with 0 speech segments. Forcing `language="tl"` on the same non-speech thump forced Whisper to guess Tagalog phonemes, producing `"Outro"` or `"Pag-pag-pag-gay"`.
   - On genuine Tagalog (`EVT-187083.wav`, `EVT-146419.wav`) and Taglish (`EVT-117465.wav`), Whisper detected Tagalog with >0.73 probability, confirming that natural speech is recognized accurately.

---

## 6. Files Modified
- [`securelinkdb/server.py`](file:///d:/Flutter%20Securelink%20Dashboard/securelinkdb/server.py) — Core audio processing pipeline, transcription acceptance gating, and danger dispatch safety.
- [`tests/test_transcription_reliability.py`](file:///d:/Flutter%20Securelink%20Dashboard/tests/test_transcription_reliability.py) — Automated regression test suite covering silence, acoustic bursts, real speech fixtures, and mocked hardware safety.
- Note: Firmware (`esp32code.txt`), TagalogBERT model weights, ContextEngine scoring formulas, Flutter desktop UI, and mobile apps were **NOT** modified.

---

## 7. Specific Functions or Sections Modified in `securelinkdb/server.py`
1. **Lines 54–73: Data Contracts Definition**
   - Introduced `TranscriptionStatus(str, Enum)` with statuses: `NO_SPEECH`, `SPEECH_DETECTED`, `TRANSCRIBED`, `UNCERTAIN_TRANSCRIPTION`, `TRANSCRIPTION_REJECTED`.
   - Introduced `TranscriptionResult` dataclass with fields: `status`, `transcript`, `reason`, `metrics`, `audio_quality`, `processing_info`, implementing `__str__` and `__bool__` for backward compatibility.
2. **Line 117: Threat Hotword Deactivation**
   - Changed `TAGALOG_HOTWORDS = ...` to `TAGALOG_HOTWORDS = None` to starve beam search of threat-word bias.
3. **Lines 1044–1365: `process_audio_buffer(pcm_bytes: bytes) -> tuple[TranscriptionResult, bytes]`**
   - Restructured pipeline order: 85 Hz Butterworth HPF -> Pure electrical silence check (`peak < 0.003`) -> Microsoft NSNet2 neural suppression *before* digital gain -> Gentle post-denoise normalization (capped at 3.0x for peaks between 0.01 and 0.35) -> Faster-Whisper ASR with `hotwords=None` and `temperature=[0.0]`.
   - Added segment-level metric validation: drops segments with `no_speech_prob >= 0.60`, `compression_ratio > 2.4`, or `avg_logprob < -1.40`.
   - Added word-level loop and token concentration filters with hyphen normalization (`re.split(r'[\s\-]+', transcript)`).
   - Added isolated hallucination artifact filter (`"thank you"`, `"outro"`, `"okay"`, `"subtitles"`, etc.).
   - Added borderline acoustic confidence classification (`avg_logprob < -1.10` classified as `UNCERTAIN_TRANSCRIPTION`).
4. **Lines 1380–1475: `handle_completed_audio(...)`**
   - Replaced raw string check with strict gate:
     `if result.status == TranscriptionStatus.TRANSCRIBED and result.transcript:`
   - Disallowed `NO_SPEECH`, `SPEECH_DETECTED`, `UNCERTAIN_TRANSCRIPTION`, and `TRANSCRIPTION_REJECTED` from ever calling `context_engine.evaluate()`, logging incident WAVs, or triggering `TRIGGER:DANGER`.
   - Fixed dictionary `.get("state")` access on `registered_devices` to prevent runtime `KeyError`.

---

## 8. Description of the Original Behavior
- `process_audio_buffer` amplified audio by up to 6.0x *before* denoising.
- Faster-Whisper decoded with active `TAGALOG_HOTWORDS` containing 19 severe threats.
- Any non-empty string returned by Whisper was passed directly into `context_engine.evaluate(transcript)`.
- If an acoustic thump was decoded as threat hotwords, the system evaluated it as `Physical Threat (Score 8.5)`, dispatched `TRIGGER:DANGER` to physical devices, and triggered camera capture.
- Non-transcribed or rejected audio had no explicit status or diagnostic metadata.

---

## 9. Description of the New Behavior
- Processing order applies neural denoising at native input SNR, followed by gentle, noise-aware post-gain.
- Threat hotwords are disabled in general decoding (`TAGALOG_HOTWORDS = None`).
- Every audio buffer returns a structured `TranscriptionResult` with full acoustic and decoding diagnostics.
- Strict gating: Only `TranscriptionStatus.TRANSCRIBED` can enter `context_engine.evaluate()`.
- Repetition loops, runaway hallucination strings, isolated hallucination artifacts, and non-speech acoustic bursts are marked `TRANSCRIPTION_REJECTED` or `NO_SPEECH` and blocked from danger evaluation.
- Quiet genuine speech (e.g. `EVT-146419.wav`, peak=0.0359) is boosted and accepted as `TRANSCRIBED`.
- Tagalog, English, and Taglish genuine speech are transcribed accurately.

---

## 10. Reason for Each Modification
| Modification | Technical Reason |
| :--- | :--- |
| `TAGALOG_HOTWORDS = None` | Eliminates ASR beam search prior probability bias towards threat vocabulary during indistinct acoustic events. Genuine threats are still recognized via Tagalog acoustic models and TagalogBERT. |
| NSNet2 Before Gain | Prevents amplifying low-level fan noise and ambient room hiss into the neural suppressor. Preserves true signal-to-noise ratio. |
| Gentle Post-Gain Normalization | Restores quiet genuine speech (0.01 < peak < 0.35) into Whisper's optimal operating range (~0.45 peak) while leaving ambient noise unamplified. |
| Segment-level Metric Checks | Filters hallucinated segments where Whisper's internal confidence is low (`no_speech_prob >= 0.60`, `avg_logprob < -1.40`, or `compression_ratio > 2.4`). |
| Hyphen-aware Repetition Filter | Catches repetitive syllable and word loops (e.g. "pag-pag-pag", "magandang-magandang") that bypass whitespace-only tokenizers. |
| Strict Status Gate | Guarantees by design that silence, uncertain speech, and rejected artifacts cannot trigger danger alerts or hardware actions. |
| Safe `.get("state")` Dict Access | Prevents unhandled `KeyError` crashes when handling connections from dynamic device IDs or test harnesses. |

---

## 11. Firmware/Backend Compatibility Changes
- **ESP32 Firmware Compatibility:** 100% compatible. No changes were made to `esp32code.txt`. All-speech VAD, 16 kHz 16-bit PCM streaming, WebSocket headers, and `TRIGGER:DANGER` protocol remain unchanged.
- **Flutter UI & Dashboard Compatibility:** 100% compatible. The WebSocket payload format (`event_type: "incident"`, `event_type: "device_update"`) and recording URL schemes remain unchanged.
- **ContextEngine & BERT Compatibility:** 100% compatible. The inputs, scoring weights, pronoun multipliers, and severity thresholds of `ContextEngine` were preserved intact.

---

## 12. Potential Side Effects & Mitigation
- *Side Effect:* Genuine speech containing stuttered words might be checked against the repetition loop filter.
  *Mitigation:* The streak filter only triggers if a word of length $\ge 3$ repeats $\ge 4$ times, or $\ge 3$ times in an extremely short utterance ($\le 5$ words). Common conversational phrases like "sige, sige" or "hello, mic check" are unaffected.
- *Side Effect:* Courtesy phrases like "thank you" or "salamat" spoken in isolation are rejected.
  *Mitigation:* In an institutional safety context, isolated courtesy phrases carry no danger risk. When spoken as part of longer sentences, they are preserved.

---

## 13. Tests Performed
An automated regression test suite was implemented in [`tests/test_transcription_reliability.py`](file:///d:/Flutter%20Securelink%20Dashboard/tests/test_transcription_reliability.py) using `unittest` and `unittest.mock`:
1. `test_pure_digital_silence`: 1.0s of zero PCM.
2. `test_buffer_too_short`: Audio buffer < 100ms.
3. `test_synthetic_fan_hum_and_hiss`: 60Hz + 120Hz harmonics + stationary Gaussian hiss.
4. `test_near_silence_real_fixture_evt135503`: Real recording of ambient room silence (`EVT-135503.wav`).
5. `test_loud_acoustic_burst_not_hallucinated_as_danger_evt236767`: Real recording of loud click/thump (`EVT-236767.wav`) that previously triggered false danger.
6. `test_repetition_loop_rejected_evt1664`: Real recording with runaway hallucination (`EVT-1664.wav`).
7. `test_quiet_genuine_speech_preserved_evt146419`: Quiet real speech (`EVT-146419.wav`, peak=0.0359).
8. `test_tagalog_speech_preserved_evt187083`: Real Tagalog speech ("Walang pasok").
9. `test_english_speech_preserved_evt192827`: Real English speech ("Mic test").
10. `test_taglish_speech_preserved_evt117465`: Real Taglish speech ("hello mic check so ito...").
11. `test_rejected_transcription_never_calls_evaluate_or_triggers_danger`: Mocked hardware WebSocket test verifying that rejected audio never invokes `context_engine.evaluate()` or sends `TRIGGER:DANGER`.
12. `test_uncertain_transcription_never_calls_evaluate_or_triggers_danger`: Mocked test verifying that `UNCERTAIN_TRANSCRIPTION` never invokes `context_engine.evaluate()`.
13. `test_genuine_threat_transcribed_triggers_danger_safely_mocked`: Mocked test verifying that genuine high-severity threat speech is recognized and dispatches `TRIGGER:DANGER` safely.

---

## 14. Test Results
All 13 automated regression tests passed successfully:
```text
Ran 13 tests in 5.006s
OK
```
Key verifications:
- `EVT-236767.wav`: Classified as `TRANSCRIPTION_REJECTED`. 0 threat words decoded. 0 danger evaluations triggered. False alarm eliminated.
- `EVT-146419.wav` (Quiet genuine speech): Classified as `TRANSCRIBED` (`"Mawala ka lang sa..."`, avg_logprob=-0.49). Speech preserved without quality gate drop.
- `EVT-187083.wav` (Tagalog): Classified as `TRANSCRIBED` (`"Walang pasok."`).
- `EVT-192827.wav` (English): Classified as `TRANSCRIBED` (`"My test, 1, 2, 3, my test."`).
- `EVT-117465.wav` (Taglish): Classified as `TRANSCRIBED` (`"Hello, mic check. So, ito..."`).
- `EVT-135503.wav` & Pure Silence: Classified as `NO_SPEECH`.
- Device safety: 0 live hardware commands were sent to physical pins during testing.

---

## 15. Known Limitations
1. **Acoustic Similarity of Non-Speech Rhythms:**
   While threat hotword hallucinations are eliminated, heavy rhythmic acoustic impacts (e.g. rapid hand drumming on the microphone casing) may occasionally generate non-threat repetitive syllables ("pag-pag-pag") before being caught by the repetition filter.
2. **Single-Word Soft Speech Overlapping Ambient Noise:**
   If a single one-syllable word is spoken at an extremely low volume (peak < 0.01, below 25 dB SNR) in high ambient noise, the neural denoiser may attenuate it as noise. Multi-word phrases and sentences are reliably preserved.
3. **Whisper Hallucination Invariance:**
   No ASR model using sequence-to-sequence autoregressive decoding is 100% immune to all hallucinations under extreme out-of-distribution acoustic inputs. The defense-in-depth architecture implemented here ensures that even if an acoustic hallucination occurs, the strict `TranscriptionStatus.TRANSCRIBED` gate and confidence thresholds prevent it from activating false physical danger alarms.

---

## 16. Rollback Instructions
To revert the changes made in Phase 1:
1. Discard modifications to `server.py`:
   ```bash
   git checkout securelinkdb/server.py
   ```
2. Remove the automated test suite if needed:
   ```bash
   rm -rf tests/
   ```
3. Restart the backend service:
   ```bash
   python securelinkdb/server.py
   ```


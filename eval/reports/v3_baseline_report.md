# SecureLink V3 Baseline Evaluation Report

**Generated (UTC):** 2026-11-25T01:29:01.848669+00:00  
**Datasets:** securelink_v4_dev_sample (dev, n=13), securelink_v4_held_out_sample (held_out, n=6)  
**Reproduction Command:** `python -m eval.runner --dataset eval/datasets/dev_sample.json --dataset eval/datasets/held_out_sample.json --output-md eval/reports/v3_baseline_report.md --output-json eval/reports/v3_baseline_report.json`  

## 1. Execution Summary
- Total scenarios: **19** | Evaluated: **18** | Missing fixtures: **1** | Unsupported: **0** | Skipped: **0**

## 2. Intent & Severity Classification Metrics
- **Intent Accuracy:** `0.6875` | **Macro Precision:** `0.7375` | **Macro Recall:** `0.7417` | **Macro F1:** `0.7146` (n=16)
- **Level Accuracy:** `0.7059` | **Level Macro F1:** `0.5667` (n=17)

## 3. Safety, Severity Agreement & Review Priority
- **Friendly-Teasing False Positives:** `1/2` (rate=0.5, IDs=['DEV-TXT-003'])
- **Serious-Threat False Negatives:** `3/9` (rate=0.3333, IDs=['DEV-TXT-004', 'DEV-TXT-009', 'HO-TXT-005'])
- **False DANGER Classifications:** `0/14` (rate=0.0, IDs=[])
- **Severity Level Exact Agreement:** `0.7059` (n=17)
- **Provisional Severity Range Agreement:** `0.7059` (n=17) | **Severity MAE:** `1.4059`
- **Review-Priority Accuracy:** `0.7647` | Precision: `0.8333` | Recall: `0.625` (n=17)

## 4. ASR & Audio Metrics
- **Evaluated Audio Clips:** `2`
- **Mean WER:** `0.0` | **Mean CER:** `0.0`
- **Critical-Word Recognition Error Rate:** `None` (0/0 missed)
- **Negation Recognition Error Rate:** `None` (0/0 missed)

## 5. Processing Latency
- **Text / Multi-Turn (ms):** mean=`0.137`, p50=`0.074`, p95=`0.695`, max=`0.695` (n=16)
- **Audio / End-to-End (ms):** mean=`22.638`, p50=`1.809`, p95=`43.467`, max=`43.467` (n=2)

## 6. Missing Fixtures & Unsupported Capabilities
- **MISSING FIXTURE** `DEV-AUD-MISSING-001`: `eval/fixtures/audio/nonexistent_sample.wav`
- *Capability Note:* ContextEngine V3 does not invoke TagalogBERT during evaluate() (audit finding #1).
- *Capability Note:* USBDeviceManager lacks send_line(); end-to-end harness runs under mocked ESP32_DIRECT websocket to avoid triggering hardware or hitting server.py:2682 AttributeError.
- *Capability Note:* UNCERTAIN_TRANSCRIPTION is currently dropped by server.py:2648 before reaching human review.

## 7. Scenario Results
| ID | Split | Mode | Status | Expected Intent / Level | Predicted Intent / Level | Score | Review (Exp/Pred) | Latency (ms) |
|---|---|---|---|---|---|---:|---|---:|
| `DEV-TXT-001` | dev | text | EVALUATED | ORDINARY_CONVERSATION / NORMAL | ORDINARY_CONVERSATION / NORMAL | 1.0 | False/False | 0.306 |
| `DEV-TXT-002` | dev | text | EVALUATED | AMBIGUOUS_CONTEXT / WARNING | ORDINARY_CONVERSATION / NORMAL | 1.0 | True/False | 0.258 |
| `DEV-TXT-003` | dev | text | EVALUATED | ORDINARY_CONVERSATION / NORMAL | VERBAL_HARASSMENT / THREAT | 6.0 | False/False | 0.074 |
| `DEV-TXT-004` | dev | text | EVALUATED | DIRECT_THREAT / THREAT | ORDINARY_CONVERSATION / NORMAL | 1.0 | True/False | 0.033 |
| `DEV-TXT-005` | dev | text | EVALUATED | DIRECT_THREAT / DANGER | DIRECT_THREAT / DANGER | 9.1 | False/False | 0.046 |
| `DEV-TXT-006` | dev | text | EVALUATED | EXTORTION / THREAT | EXTORTION / THREAT | 7.1 | True/True | 0.062 |
| `DEV-TXT-007` | dev | text | EVALUATED | COERCION / THREAT | COERCION / THREAT | 5.5 | True/True | 0.054 |
| `DEV-TXT-008` | dev | text | EVALUATED | REPORTED_THREAT / THREAT | REPORTED_THREAT / THREAT | 5.0 | True/True | 0.044 |
| `DEV-TXT-009` | dev | text | EVALUATED | DIRECT_THREAT / DANGER | PAST_INCIDENT / WARNING | 3.5 | False/True | 0.052 |
| `DEV-MT-001` | dev | multi_turn | EVALUATED | VERBAL_HARASSMENT / THREAT | VERBAL_HARASSMENT / THREAT | 7.2 | False/False | 0.128 |
| `DEV-AUD-001` | dev | audio | EVALUATED | - / - | NO_SPEECH / - | - | None/None | 1.809 |
| `DEV-E2E-001` | dev | end_to_end | EVALUATED | - / NORMAL | NO_INCIDENT / NORMAL | 0.0 | False/False | 43.467 |
| `DEV-AUD-MISSING-001` | dev | audio | MISSING_FIXTURE | - / - | - / - | - | - | - |
| `HO-TXT-001` | held_out | text | EVALUATED | ORDINARY_CONVERSATION / NORMAL | ORDINARY_CONVERSATION / NORMAL | 1.0 | False/False | 0.695 |
| `HO-TXT-002` | held_out | text | EVALUATED | NEGATED_THREAT / NORMAL | NEGATED_THREAT / NORMAL | 1.2 | False/False | 0.079 |
| `HO-TXT-003` | held_out | text | EVALUATED | DIRECT_THREAT / THREAT | DIRECT_THREAT / THREAT | 6.5 | True/True | 0.099 |
| `HO-TXT-004` | held_out | text | EVALUATED | DIRECT_THREAT / DANGER | DIRECT_THREAT / DANGER | 9.0 | False/False | 0.079 |
| `HO-TXT-005` | held_out | text | EVALUATED | EXTORTION / THREAT | ORDINARY_CONVERSATION / NORMAL | 1.0 | True/False | 0.055 |
| `HO-MT-001` | held_out | multi_turn | EVALUATED | EXTORTION / THREAT | EXTORTION / THREAT | 7.5 | True/True | 0.134 |

# SecureLink V3 vs. V4 Held-Out Benchmark Comparison (`v4_school_held_out_review_final.json`, n=60)

**Generated (UTC):** 2026-11-26T15:36:37.625589+00:00  
**Dataset:** `eval/datasets/v4_school_held_out_review_final.json` (`held_out`, n=60; languages: `{'en': 20, 'taglish': 20, 'tl': 20}`; `provisional_tagged=60`)  
**Validation & Leakage Audit:** Exact duplicates = `0`, Near-duplicates (>=0.85) = `0`, Overlap vs `v4_dev_300.json` = `0 IDs / 0 texts`, Blind overlap vs `dataset_v4_train.csv` = `0 exact / 0 near`  
**Evaluated Engines:** V3 Baseline (`USBConnectionVersion:securelinkdb/context_engine.py`), V4 Rules (`securelinkdb/context_engine.py`), and V4 + Fine-Tuned TagalogBERT (`securelinkdb/securelink_final_model`, CUDA=True).

## 1. Headline Metrics & Safety Slices

| Metric | V3 Baseline | V4 (Rules) | V4 (+ Fine-Tuned TagalogBERT) | Delta (V4+BERT vs V3) | Delta (V4+BERT vs V4 Rules) |
|---|---:|---:|---:|---:|---:|
| Intent Accuracy | 0.5000 | 0.4833 | 0.5833 | +0.0833 | +0.1000 |
| Intent Macro Precision | 0.6906 | 0.6906 | 0.5550 | -0.1356 | -0.1356 |
| Intent Macro Recall | 0.3233 | 0.3067 | 0.5417 | +0.2184 | +0.2350 |
| Intent Macro F1 | 0.3221 | 0.3021 | 0.4389 | +0.1168 | +0.1368 |
| Severity Level Accuracy | 0.6000 | 0.6167 | 0.7000 | +0.1000 | +0.0833 |
| Severity Level Macro F1 | 0.2926 | 0.3199 | 0.4896 | +0.1970 | +0.1697 |
| Serious-Threat False Negatives | 19/24 (0.7917) | 19/24 (0.7917) | 1/24 (0.0417) | -18 | -18 |
| Friendly-Teasing False Positives | 0/12 (0.0000) | 0/12 (0.0000) | 3/12 (0.2500) | +3 | +3 |
| False DANGER Classifications | 4/55 (0.0727) | 3/55 (0.0545) | 3/55 (0.0545) | -1 | +0 |
| Review-Priority Accuracy | 0.6000 | 0.6167 | 0.7833 | +0.1833 | +0.1666 |
| Review-Priority Precision | 0.5000 | 0.6667 | 0.6897 | +0.1897 | +0.0230 |
| Review-Priority Recall | 0.0417 | 0.0833 | 0.8333 | +0.7916 | +0.7500 |
| Mean Latency (ms) | 0.443 | 0.942 | 41.021 | +40.578 | +40.079 |

## 2. Per-Class Intent Classification

| Intent Class | Support | V3 P / R / F1 | V4 Rules P / R / F1 | V4 + Fine-Tuned BERT P / R / F1 |
|---|---:|---|---|---|
| `COERCION` | 7 | 0.0000 / 0.0000 / 0.0000 | 0.0000 / 0.0000 / 0.0000 | 0.0000 / 0.0000 / 0.0000 |
| `DIRECT_THREAT` | 12 | 1.0000 / 0.3333 / 0.5000 | 1.0000 / 0.2500 / 0.4000 | 0.7143 / 0.8333 / 0.7692 |
| `EXTORTION` | 5 | 1.0000 / 0.2000 / 0.3333 | 1.0000 / 0.2000 / 0.3333 | 0.3571 / 1.0000 / 0.5263 |
| `NEGATED_THREAT` | 12 | 1.0000 / 0.0833 / 0.1538 | 1.0000 / 0.0833 / 0.1538 | 1.0000 / 0.0833 / 0.1538 |
| `ORDINARY_CONVERSATION` | 24 | 0.4528 / 1.0000 / 0.6234 | 0.4528 / 1.0000 / 0.6234 | 0.7037 / 0.7917 / 0.7451 |
| `PAST_INCIDENT` | 0 | 0.0000 / 0.0000 / 0.0000 | 0.0000 / 0.0000 / 0.0000 | 0.0000 / 0.0000 / 0.0000 |
| `REPORTED_THREAT` | 0 | 0.0000 / 0.0000 / 0.0000 | 0.0000 / 0.0000 / 0.0000 | 0.0000 / 0.0000 / 0.0000 |
| `VERBAL_HARASSMENT` | 0 | 0.0000 / 0.0000 / 0.0000 | 0.0000 / 0.0000 / 0.0000 | 0.0000 / 0.0000 / 0.0000 |

## 3. Safety Error Details (Misses, False Positives & False DANGER)

- **V3 Serious-Threat Misses (19):** `['V4-SCHOOL-HO-002', 'V4-SCHOOL-HO-003', 'V4-SCHOOL-HO-004', 'V4-SCHOOL-HO-005', 'V4-SCHOOL-HO-006', 'V4-SCHOOL-HO-008', 'V4-SCHOOL-HO-010', 'V4-SCHOOL-HO-011', 'V4-SCHOOL-HO-013', 'V4-SCHOOL-HO-014', 'V4-SCHOOL-HO-015', 'V4-SCHOOL-HO-017', 'V4-SCHOOL-HO-018', 'V4-SCHOOL-HO-019', 'V4-SCHOOL-HO-020', 'V4-SCHOOL-HO-021', 'V4-SCHOOL-HO-022', 'V4-SCHOOL-HO-023', 'V4-SCHOOL-HO-024']`
- **V4 (Rules) Serious-Threat Misses (19):** `['V4-SCHOOL-HO-002', 'V4-SCHOOL-HO-003', 'V4-SCHOOL-HO-004', 'V4-SCHOOL-HO-005', 'V4-SCHOOL-HO-006', 'V4-SCHOOL-HO-008', 'V4-SCHOOL-HO-010', 'V4-SCHOOL-HO-011', 'V4-SCHOOL-HO-013', 'V4-SCHOOL-HO-014', 'V4-SCHOOL-HO-015', 'V4-SCHOOL-HO-017', 'V4-SCHOOL-HO-018', 'V4-SCHOOL-HO-019', 'V4-SCHOOL-HO-020', 'V4-SCHOOL-HO-021', 'V4-SCHOOL-HO-022', 'V4-SCHOOL-HO-023', 'V4-SCHOOL-HO-024']`
- **V4 (+ Fine-Tuned TagalogBERT) Serious-Threat Misses (1):** `['V4-SCHOOL-HO-013']`
- **V3 Friendly-Teasing False Positives (0):** `[]`
- **V4 (Rules) Friendly-Teasing False Positives (0):** `[]`
- **V4 (+ Fine-Tuned TagalogBERT) Friendly-Teasing False Positives (3):** `['V4-SCHOOL-HO-027', 'V4-SCHOOL-HO-029', 'V4-SCHOOL-HO-030']`
- **V3 False DANGER IDs (4):** `['V4-SCHOOL-HO-001', 'V4-SCHOOL-HO-007', 'V4-SCHOOL-HO-009', 'V4-SCHOOL-HO-012']`
- **V4 (Rules) False DANGER IDs (3):** `['V4-SCHOOL-HO-001', 'V4-SCHOOL-HO-009', 'V4-SCHOOL-HO-012']`
- **V4 (+ Fine-Tuned TagalogBERT) False DANGER IDs (3):** `['V4-SCHOOL-HO-001', 'V4-SCHOOL-HO-009', 'V4-SCHOOL-HO-012']`

## 4. Intent Confusion Matrices (Rows = Expected, Cols = Predicted)

### V3 Baseline Confusion Matrix

| Expected \ Pred | `COERCION` | `DIRECT_THR` | `EXTORTION` | `NEGATED_TH` | `ORDINARY_C` | `PAST_INCID` |
|---|---:|---:|---:|---:|---:|---:|
| `COERCION` | 0 | 0 | 0 | 0 | 7 | 0 |
| `DIRECT_THREAT` | 0 | 4 | 0 | 0 | 8 | 0 |
| `EXTORTION` | 0 | 0 | 1 | 0 | 4 | 0 |
| `NEGATED_THREAT` | 0 | 0 | 0 | 1 | 10 | 1 |
| `ORDINARY_CONVERSATION` | 0 | 0 | 0 | 0 | 24 | 0 |
| `PAST_INCIDENT` | 0 | 0 | 0 | 0 | 0 | 0 |

### V4 (Rules) Confusion Matrix

| Expected \ Pred | `COERCION` | `DIRECT_THR` | `EXTORTION` | `NEGATED_TH` | `ORDINARY_C` | `REPORTED_T` |
|---|---:|---:|---:|---:|---:|---:|
| `COERCION` | 0 | 0 | 0 | 0 | 7 | 0 |
| `DIRECT_THREAT` | 0 | 3 | 0 | 0 | 8 | 1 |
| `EXTORTION` | 0 | 0 | 1 | 0 | 4 | 0 |
| `NEGATED_THREAT` | 0 | 0 | 0 | 1 | 10 | 1 |
| `ORDINARY_CONVERSATION` | 0 | 0 | 0 | 0 | 24 | 0 |
| `REPORTED_THREAT` | 0 | 0 | 0 | 0 | 0 | 0 |

### V4 (+ Fine-Tuned TagalogBERT) Confusion Matrix

| Expected \ Pred | `COERCION` | `DIRECT_THR` | `EXTORTION` | `NEGATED_TH` | `ORDINARY_C` | `REPORTED_T` | `VERBAL_HAR` |
|---|---:|---:|---:|---:|---:|---:|---:|
| `COERCION` | 0 | 0 | 6 | 0 | 1 | 0 | 0 |
| `DIRECT_THREAT` | 0 | 10 | 1 | 0 | 0 | 1 | 0 |
| `EXTORTION` | 0 | 0 | 5 | 0 | 0 | 0 | 0 |
| `NEGATED_THREAT` | 0 | 2 | 0 | 1 | 7 | 1 | 1 |
| `ORDINARY_CONVERSATION` | 0 | 2 | 2 | 0 | 19 | 0 | 1 |
| `REPORTED_THREAT` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `VERBAL_HARASSMENT` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

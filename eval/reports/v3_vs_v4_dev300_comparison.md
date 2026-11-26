# SecureLink V3 vs. V4 Benchmark Comparison (`v4_dev_300.json`, n=300)

**Dataset:** `eval/datasets/v4_dev_300.json` (`dev`, n=300; synthetic provisional labels)  
**Reproduction Command (V4):** `python -m eval.runner --dataset eval/datasets/v4_dev_300.json --skip-audio --output-md eval/reports/v4_dev300_report.md --output-json eval/reports/v4_dev300_report.json`  

## 1. Headline Metrics & Safety Slices

| Metric | V3 Baseline | V4 Engine | Delta |
|---|---:|---:|---:|
| Intent Accuracy | 0.6400 | 0.9433 | +0.3033 |
| Intent Macro Precision | 0.6858 | 0.9170 | +0.2312 |
| Intent Macro Recall | 0.7038 | 0.9437 | +0.2399 |
| Intent Macro F1 | 0.6413 | 0.9207 | +0.2794 |
| Severity Level Accuracy | 0.6433 | 0.9367 | +0.2934 |
| Severity Level Macro F1 | 0.5357 | 0.9315 | +0.3958 |
| Provisional Severity Range Agreement | 0.6567 | 0.9367 | +0.2800 |
| Severity MAE (lower is better) | 1.4770 | 0.3137 | -1.1633 |
| Serious-Threat False Negatives (lower is better) | 20/63 (0.3175) | 0/63 (0.0) | -20 |
| Friendly-Teasing False Positives (lower is better) | 8/44 (0.1818) | 0/44 (0.0) | -8 |
| False DANGER Classifications (lower is better) | 2/275 (0.0073) | 0/275 (0.0) | -2 |
| Review-Priority Accuracy | 0.7600 | 0.9267 | +0.1667 |
| Review-Priority Precision | 0.8393 | 0.9583 | +0.1190 |
| Review-Priority Recall | 0.4273 | 0.8364 | +0.4091 |
| Mean Latency (ms) | 0.084 | 0.193 | +0.109 |

## 2. Per-Class Intent Classification (V3 vs. V4)

| Intent Class | Support | V3 P / R / F1 | V4 P / R / F1 |
|---|---:|---|---|
| `AMBIGUOUS_CONTEXT` | 38 | 0.0000 / 0.0000 / 0.0000 | 0.9394 / 0.8158 / 0.8732 |
| `COERCION` | 8 | 1.0000 / 1.0000 / 1.0000 | 1.0000 / 1.0000 / 1.0000 |
| `DIRECT_THREAT` | 45 | 0.9000 / 0.6000 / 0.7200 | 1.0000 / 0.9778 / 0.9888 |
| `EXTORTION` | 10 | 1.0000 / 0.6000 / 0.7500 | 1.0000 / 1.0000 / 1.0000 |
| `HYPOTHETICAL_THREAT` | 9 | 0.8182 / 1.0000 / 0.9000 | 1.0000 / 1.0000 / 1.0000 |
| `NEGATED_THREAT` | 11 | 0.8750 / 0.6364 / 0.7368 | 1.0000 / 0.9091 / 0.9524 |
| `ORDINARY_CONVERSATION` | 106 | 0.5291 / 0.8585 / 0.6547 | 0.9455 / 0.9811 / 0.9630 |
| `PAST_INCIDENT` | 1 | 0.1000 / 1.0000 / 0.1818 | 0.5000 / 1.0000 / 0.6667 |
| `REPORTED_THREAT` | 22 | 0.9500 / 0.8636 / 0.9048 | 0.8947 / 0.7727 / 0.8293 |
| `VERBAL_HARASSMENT` | 50 | 0.6857 / 0.4800 / 0.5647 | 0.8909 / 0.9800 / 0.9333 |

## 3. V4 Intent Confusion Matrix (Rows = Expected, Cols = Predicted)

| Expected \ Pred | `AMBIGUOUS_` | `COERCION` | `DIRECT_THR` | `EXTORTION` | `HYPOTHETIC` | `NEGATED_TH` | `ORDINARY_C` | `PAST_INCID` | `REPORTED_T` | `VERBAL_HAR` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `AMBIGUOUS_CONTEXT` | 31 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 6 |
| `COERCION` | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `DIRECT_THREAT` | 0 | 0 | 44 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| `EXTORTION` | 0 | 0 | 0 | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| `HYPOTHETICAL_THREAT` | 0 | 0 | 0 | 0 | 9 | 0 | 0 | 0 | 0 | 0 |
| `NEGATED_THREAT` | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 1 | 0 |
| `ORDINARY_CONVERSATION` | 2 | 0 | 0 | 0 | 0 | 0 | 104 | 0 | 0 | 0 |
| `PAST_INCIDENT` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| `REPORTED_THREAT` | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0 | 17 | 0 |
| `VERBAL_HARASSMENT` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 49 |

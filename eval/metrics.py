"""
Evaluation metric calculations for SecureLink V4.

All metric functions are pure, deterministic, dependency-light (Python stdlib only),
and directly unit-tested in `tests/test_eval_framework.py`.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation (preserving Tagalog ñ and internal apostrophes), collapse whitespace."""
    if not text:
        return ""
    cleaned = text.lower().strip()
    cleaned = re.sub(r"[^a-z0-9ñ'\s-]", " ", cleaned)
    cleaned = cleaned.replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def tokenize_words(text: str) -> List[str]:
    norm = normalize_text(text)
    return norm.split() if norm else []


def _levenshtein(seq_a: Sequence[Any], seq_b: Sequence[Any]) -> int:
    """Standard dynamic-programming Levenshtein edit distance."""
    m, n = len(seq_a), len(seq_b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        curr[0] = i
        a_i = seq_a[i - 1]
        for j in range(1, n + 1):
            cost = 0 if a_i == seq_b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,      # deletion
                curr[j - 1] + 1,  # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev, curr = curr, prev
    return prev[n]


def compute_wer(reference: str, hypothesis: str) -> Optional[float]:
    """
    Compute Word Error Rate (WER = edit_distance(ref_words, hyp_words) / len(ref_words)).
    If reference is empty: returns 0.0 when hypothesis is also empty, else 1.0 (insertion error).
    """
    ref_words = tokenize_words(reference)
    hyp_words = tokenize_words(hypothesis)
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    dist = _levenshtein(ref_words, hyp_words)
    return round(dist / len(ref_words), 4)


def compute_cer(reference: str, hypothesis: str) -> Optional[float]:
    """
    Compute Character Error Rate on normalized text (excluding outer whitespace).
    If reference is empty: returns 0.0 when hypothesis is also empty, else 1.0.
    """
    ref_chars = list(normalize_text(reference))
    hyp_chars = list(normalize_text(hypothesis))
    if not ref_chars:
        return 0.0 if not hyp_chars else 1.0
    dist = _levenshtein(ref_chars, hyp_chars)
    return round(dist / len(ref_chars), 4)


def compute_keyword_recognition_errors(
    expected_keywords: Sequence[str],
    hypothesis: str,
) -> Dict[str, Any]:
    """
    Evaluate whether expected critical words or negation tokens appear in the ASR hypothesis.
    Matches whole normalized tokens or multi-word normalized phrases.
    """
    hyp_norm = f" {normalize_text(hypothesis)} "
    expected_clean = [normalize_text(w) for w in expected_keywords if normalize_text(w)]
    if not expected_clean:
        return {
            "total": 0,
            "missed_count": 0,
            "error_rate": None,
            "missed_words": [],
        }
    missed = [kw for kw in expected_clean if f" {kw} " not in hyp_norm]
    return {
        "total": len(expected_clean),
        "missed_count": len(missed),
        "error_rate": round(len(missed) / len(expected_clean), 4),
        "missed_words": missed,
    }


def compute_classification_metrics(
    y_true: Sequence[str],
    y_pred: Sequence[str],
) -> Dict[str, Any]:
    """
    Compute per-class Precision, Recall, F1, Support, Macro-F1, Micro-F1 (Accuracy),
    and Confusion Matrix (nested dict: true_label -> predicted_label -> count).
    """
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have equal length.")

    labels = sorted(set(y_true) | set(y_pred))
    confusion: Dict[str, Dict[str, int]] = {
        t: {p: 0 for p in labels} for t in labels
    }
    for t, p in zip(y_true, y_pred):
        confusion[t][p] += 1

    per_class: Dict[str, Dict[str, Any]] = {}
    macro_p_vals: List[float] = []
    macro_r_vals: List[float] = []
    macro_f1_vals: List[float] = []

    total_correct = 0
    total_samples = len(y_true)

    for lbl in labels:
        tp = confusion[lbl][lbl]
        fp = sum(confusion[other][lbl] for other in labels if other != lbl)
        fn = sum(confusion[lbl][other] for other in labels if other != lbl)
        support = tp + fn
        total_correct += tp

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        per_class[lbl] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }
        # Only include classes with ground-truth support in macro averages
        if support > 0:
            macro_p_vals.append(precision)
            macro_r_vals.append(recall)
            macro_f1_vals.append(f1)

    accuracy = (total_correct / total_samples) if total_samples > 0 else 0.0
    macro_precision = (sum(macro_p_vals) / len(macro_p_vals)) if macro_p_vals else 0.0
    macro_recall = (sum(macro_r_vals) / len(macro_r_vals)) if macro_r_vals else 0.0
    macro_f1 = (sum(macro_f1_vals) / len(macro_f1_vals)) if macro_f1_vals else 0.0

    return {
        "total": total_samples,
        "accuracy": round(accuracy, 4),
        "macro_precision": round(macro_precision, 4),
        "macro_recall": round(macro_recall, 4),
        "macro_f1": round(macro_f1, 4),
        "per_class": per_class,
        "confusion_matrix": confusion,
    }


def compute_safety_and_severity_metrics(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute domain-specific safety, severity agreement, and review-priority metrics
    over evaluated scenario records.

    Expected record keys (optional where N/A):
    - expected_level, predicted_level
    - provisional_severity, provisional_severity_range, predicted_score
    - expected_review_required, predicted_review_required
    - is_friendly_teasing, is_serious_threat
    """
    teasing_total = 0
    teasing_fp = 0
    teasing_fp_ids: List[str] = []

    threat_total = 0
    threat_fn = 0
    threat_fn_ids: List[str] = []

    level_total = 0
    level_exact = 0

    range_total = 0
    range_in_band = 0
    abs_errors: List[float] = []

    non_danger_total = 0
    false_danger_count = 0
    false_danger_ids: List[str] = []

    review_total = 0
    review_tp = 0
    review_fp = 0
    review_fn = 0
    review_tn = 0

    for rec in records:
        if rec.get("status") != "EVALUATED":
            continue

        sc_id = str(rec.get("id", ""))
        pred_level = rec.get("predicted_level")
        pred_score = rec.get("predicted_score")
        exp_level = rec.get("expected_level")

        # Friendly teasing false positives (predicted THREAT/DANGER or score >= 4.0)
        if rec.get("is_friendly_teasing"):
            teasing_total += 1
            if pred_level in ("THREAT", "DANGER") or (pred_score is not None and pred_score >= 4.0):
                teasing_fp += 1
                teasing_fp_ids.append(sc_id)

        # Serious threat false negatives (predicted NORMAL/WARNING or score < 4.0)
        if rec.get("is_serious_threat"):
            threat_total += 1
            if pred_level in ("NORMAL", "WARNING") or (pred_score is not None and pred_score < 4.0):
                threat_fn += 1
                threat_fn_ids.append(sc_id)

        # Level agreement & false DANGER
        if exp_level is not None and pred_level is not None:
            level_total += 1
            if pred_level == exp_level:
                level_exact += 1
            if exp_level != "DANGER":
                non_danger_total += 1
                if pred_level == "DANGER" or (pred_score is not None and pred_score >= 8.0):
                    false_danger_count += 1
                    false_danger_ids.append(sc_id)

        # Provisional severity range & MAE
        sev_range = rec.get("provisional_severity_range")
        if sev_range is not None and pred_score is not None:
            range_total += 1
            if sev_range[0] <= pred_score <= sev_range[1]:
                range_in_band += 1

        prov_sev = rec.get("provisional_severity")
        if prov_sev is not None and pred_score is not None:
            abs_errors.append(abs(float(pred_score) - float(prov_sev)))

        # Review priority agreement
        exp_rev = rec.get("expected_review_required")
        pred_rev = rec.get("predicted_review_required")
        if exp_rev is not None and pred_rev is not None:
            review_total += 1
            if exp_rev and pred_rev:
                review_tp += 1
            elif not exp_rev and pred_rev:
                review_fp += 1
            elif exp_rev and not pred_rev:
                review_fn += 1
            else:
                review_tn += 1

    review_accuracy = ((review_tp + review_tn) / review_total) if review_total > 0 else None
    review_precision = (review_tp / (review_tp + review_fp)) if (review_tp + review_fp) > 0 else None
    review_recall = (review_tp / (review_tp + review_fn)) if (review_tp + review_fn) > 0 else None

    return {
        "friendly_teasing_total": teasing_total,
        "friendly_teasing_false_positives": teasing_fp,
        "friendly_teasing_fp_rate": round(teasing_fp / teasing_total, 4) if teasing_total > 0 else None,
        "friendly_teasing_fp_ids": teasing_fp_ids,
        "serious_threat_total": threat_total,
        "serious_threat_false_negatives": threat_fn,
        "serious_threat_fn_rate": round(threat_fn / threat_total, 4) if threat_total > 0 else None,
        "serious_threat_fn_ids": threat_fn_ids,
        "severity_level_total": level_total,
        "severity_level_exact_agreement": round(level_exact / level_total, 4) if level_total > 0 else None,
        "severity_range_total": range_total,
        "severity_range_agreement": round(range_in_band / range_total, 4) if range_total > 0 else None,
        "severity_mae": round(sum(abs_errors) / len(abs_errors), 4) if abs_errors else None,
        "non_danger_total": non_danger_total,
        "false_danger_count": false_danger_count,
        "false_danger_rate": round(false_danger_count / non_danger_total, 4) if non_danger_total > 0 else None,
        "false_danger_ids": false_danger_ids,
        "review_priority_total": review_total,
        "review_priority_accuracy": round(review_accuracy, 4) if review_accuracy is not None else None,
        "review_priority_precision": round(review_precision, 4) if review_precision is not None else None,
        "review_priority_recall": round(review_recall, 4) if review_recall is not None else None,
    }


def compute_latency_stats(latencies_ms: Sequence[float]) -> Dict[str, Optional[float]]:
    """Compute count, mean, p50, p95, and max latency in milliseconds."""
    if not latencies_ms:
        return {"count": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}
    ordered = sorted(float(x) for x in latencies_ms)
    n = len(ordered)

    def _percentile(pct: float) -> float:
        idx = min(n - 1, max(0, int(math.ceil((pct / 100.0) * n)) - 1))
        return ordered[idx]

    return {
        "count": n,
        "mean_ms": round(sum(ordered) / n, 3),
        "p50_ms": round(_percentile(50), 3),
        "p95_ms": round(_percentile(95), 3),
        "max_ms": round(ordered[-1], 3),
    }

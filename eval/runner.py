"""
SecureLink V4 Lightweight Reproducible Evaluation Runner.

Evaluates the existing V3 detection and transcription pipeline in strict isolation:
- Fresh ContextEngine instance per scenario (zero cross-scenario history leakage).
- Zero hardware triggers, notifications, WAV disk writes, or camera activations.
- Accurately reports missing audio fixtures and unsupported capabilities.

Usage:
    python -m eval.runner --dataset eval/datasets/dev_sample.json
    python -m eval.runner --dataset eval/datasets/dev_sample.json --skip-audio
    python -m eval.runner --dataset eval/datasets/dev_sample.json --dataset eval/datasets/held_out_sample.json --output-md eval/reports/v3_baseline_report.md --output-json eval/reports/v3_baseline_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SECURELINKDB_DIR = REPO_ROOT / "securelinkdb"
if str(SECURELINKDB_DIR) not in sys.path:
    sys.path.insert(0, str(SECURELINKDB_DIR))

from context_engine import ContextEngine  # noqa: E402
from eval.metrics import (  # noqa: E402
    compute_cer,
    compute_classification_metrics,
    compute_keyword_recognition_errors,
    compute_latency_stats,
    compute_safety_and_severity_metrics,
    compute_wer,
)
from eval.schema import (  # noqa: E402
    EvalDataset,
    EvalScenario,
    EvaluationMode,
    load_dataset,
    verify_split_isolation,
)


def _resolve_audio_path(audio_path: str) -> Path:
    p = Path(audio_path)
    return p if p.is_absolute() else (REPO_ROOT / p)


def _read_wav_pcm16_mono_16k(path: Path) -> Tuple[Optional[bytes], Optional[str]]:
    """Read raw PCM bytes from a 16kHz 16-bit mono WAV file. Returns (pcm_bytes, error_reason)."""
    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            if channels != 1 or sampwidth != 2 or framerate != 16000:
                return None, (
                    f"Unsupported WAV format ({framerate}Hz, {sampwidth*8}-bit, {channels}ch; "
                    "expected 16000Hz 16-bit mono)"
                )
            return wf.readframes(wf.getnframes()), None
    except Exception as exc:
        return None, f"Failed to read WAV file: {type(exc).__name__}: {exc}"


def _lazy_import_server():
    """Import securelinkdb.server lazily only when audio or end-to-end modes are evaluated."""
    import torch

    if torch.cuda.is_available():
        torch_lib_dir = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.exists(torch_lib_dir):
            try:
                os.add_dll_directory(torch_lib_dir)
            except Exception:
                pass

    import server  # type: ignore

    return server


def evaluate_text_scenario(scenario: EvalScenario) -> Dict[str, Any]:
    """Evaluate a single-utterance text scenario on a fresh isolated ContextEngine."""
    engine = ContextEngine(escalation_window_seconds=600.0)
    dev_id = f"EVAL-{scenario.id}"
    t0 = time.perf_counter()
    assessment = engine.evaluate(scenario.utterance or "", device_id=dev_id, timestamp=1_700_000_000.0)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "id": scenario.id,
        "split": scenario.split.value,
        "mode": scenario.mode.value,
        "language": scenario.language.value,
        "status": "EVALUATED",
        "utterance": scenario.utterance,
        "expected_intent": scenario.expected_intent,
        "predicted_intent": assessment.intent.value,
        "expected_level": scenario.expected_level,
        "predicted_level": assessment.level,
        "provisional_severity": scenario.provisional_severity,
        "provisional_severity_range": list(scenario.provisional_severity_range)
        if scenario.provisional_severity_range
        else None,
        "predicted_score": float(assessment.score),
        "predicted_category": assessment.category,
        "expected_review_required": scenario.expected_review_required,
        "predicted_review_required": bool(assessment.human_review_required),
        "is_friendly_teasing": scenario.is_friendly_teasing,
        "is_serious_threat": scenario.is_serious_threat,
        "risk_factors": list(assessment.risk_factors),
        "explanation": assessment.explanation,
        "latency_ms": round(latency_ms, 3),
        "tags": list(scenario.tags),
    }


def evaluate_multi_turn_scenario(scenario: EvalScenario) -> Dict[str, Any]:
    """Evaluate a multi-turn conversational scenario on an isolated ContextEngine."""
    engine = ContextEngine(escalation_window_seconds=600.0)
    dev_id = f"EVAL-{scenario.id}"
    base_ts = 1_700_000_000.0
    turn_results: List[Dict[str, Any]] = []
    total_latency_ms = 0.0
    last_assessment = None

    for idx, turn in enumerate(scenario.turns):
        t0 = time.perf_counter()
        assessment = engine.evaluate(
            turn.utterance,
            device_id=dev_id,
            timestamp=base_ts + float(turn.timestamp_offset_sec),
        )
        turn_latency = (time.perf_counter() - t0) * 1000.0
        total_latency_ms += turn_latency
        last_assessment = assessment
        turn_results.append({
            "turn_index": idx,
            "timestamp_offset_sec": turn.timestamp_offset_sec,
            "speaker_role": turn.speaker_role,
            "utterance": turn.utterance,
            "expected_intent": turn.expected_intent,
            "predicted_intent": assessment.intent.value,
            "expected_level": turn.expected_level,
            "predicted_level": assessment.level,
            "predicted_score": float(assessment.score),
            "predicted_category": assessment.category,
            "predicted_review_required": bool(assessment.human_review_required),
            "risk_factors": list(assessment.risk_factors),
            "latency_ms": round(turn_latency, 3),
        })

    assert last_assessment is not None
    return {
        "id": scenario.id,
        "split": scenario.split.value,
        "mode": scenario.mode.value,
        "language": scenario.language.value,
        "status": "EVALUATED",
        "num_turns": len(scenario.turns),
        "turn_results": turn_results,
        "expected_intent": scenario.expected_intent,
        "predicted_intent": last_assessment.intent.value,
        "expected_level": scenario.expected_level,
        "predicted_level": last_assessment.level,
        "provisional_severity": scenario.provisional_severity,
        "provisional_severity_range": list(scenario.provisional_severity_range)
        if scenario.provisional_severity_range
        else None,
        "predicted_score": float(last_assessment.score),
        "predicted_category": last_assessment.category,
        "expected_review_required": scenario.expected_review_required,
        "predicted_review_required": bool(last_assessment.human_review_required),
        "is_friendly_teasing": scenario.is_friendly_teasing,
        "is_serious_threat": scenario.is_serious_threat,
        "risk_factors": list(last_assessment.risk_factors),
        "explanation": last_assessment.explanation,
        "latency_ms": round(total_latency_ms, 3),
        "tags": list(scenario.tags),
    }


def evaluate_audio_scenario(
    scenario: EvalScenario,
    server_mod: Any,
    end_to_end: bool = False,
) -> Dict[str, Any]:
    """
    Evaluate an audio transcription or end-to-end audio-to-incident scenario.
    All hardware triggers, UI broadcasts, and disk WAV writes are strictly mocked.
    """
    resolved = _resolve_audio_path(scenario.audio_path or "")
    if not resolved.exists():
        return {
            "id": scenario.id,
            "split": scenario.split.value,
            "mode": scenario.mode.value,
            "language": scenario.language.value,
            "status": "MISSING_FIXTURE",
            "reason": f"Audio fixture not found on disk: {scenario.audio_path}",
            "audio_path": scenario.audio_path,
            "tags": list(scenario.tags),
        }

    pcm_bytes, wav_err = _read_wav_pcm16_mono_16k(resolved)
    if wav_err or pcm_bytes is None:
        return {
            "id": scenario.id,
            "split": scenario.split.value,
            "mode": scenario.mode.value,
            "language": scenario.language.value,
            "status": "UNSUPPORTED_CAPABILITY",
            "reason": wav_err or "Invalid WAV data",
            "audio_path": scenario.audio_path,
            "tags": list(scenario.tags),
        }

    # 1. ASR pass via existing production process_audio_buffer
    t0 = time.perf_counter()
    asr_result, _clean_pcm = server_mod.process_audio_buffer(pcm_bytes)
    asr_latency_ms = (time.perf_counter() - t0) * 1000.0
    hyp = asr_result.transcript or ""

    wer = compute_wer(scenario.reference_transcript, hyp) if scenario.reference_transcript is not None else None
    cer = compute_cer(scenario.reference_transcript, hyp) if scenario.reference_transcript is not None else None
    crit_err = compute_keyword_recognition_errors(scenario.critical_words, hyp)
    neg_err = compute_keyword_recognition_errors(scenario.negation_words, hyp)

    rec: Dict[str, Any] = {
        "id": scenario.id,
        "split": scenario.split.value,
        "mode": scenario.mode.value,
        "language": scenario.language.value,
        "status": "EVALUATED",
        "audio_path": scenario.audio_path,
        "reference_transcript": scenario.reference_transcript,
        "hypothesis_transcript": hyp,
        "expected_transcription_status": scenario.expected_transcription_status,
        "transcription_status": asr_result.status.value,
        "transcription_reason": asr_result.reason,
        "asr_metrics": dict(asr_result.metrics or {}),
        "audio_quality": dict(asr_result.audio_quality or {}),
        "wer": wer,
        "cer": cer,
        "critical_word_errors": crit_err,
        "negation_word_errors": neg_err,
        "asr_latency_ms": round(asr_latency_ms, 3),
        "latency_ms": round(asr_latency_ms, 3),
        "tags": list(scenario.tags),
    }

    if not end_to_end:
        return rec

    # 2. End-to-end isolated audio-to-incident evaluation via handle_completed_audio
    # Strictly mock all side effects: zero WAV writes, zero UI broadcasts, zero hardware triggers.
    isolated_engine = ContextEngine(escalation_window_seconds=600.0)
    dev_id = f"EVAL-{scenario.id}"
    mock_ws = AsyncMock()
    captured_broadcasts: List[Dict[str, Any]] = []
    captured_incidents: collections.deque = collections.deque(maxlen=50)
    mock_registered: Dict[str, Any] = {dev_id: {"id": dev_id, "state": "VAD ARMED", "online": True}}

    async def _capture_broadcast(payload: dict):
        captured_broadcasts.append(payload)

    t_e2e_start = time.perf_counter()
    with (
        patch.object(server_mod, "process_audio_buffer", return_value=(asr_result, _clean_pcm)),
        patch.object(server_mod, "context_engine", isolated_engine),
        patch.object(server_mod, "broadcast_to_ui", side_effect=_capture_broadcast),
        patch.object(server_mod, "save_wav", MagicMock()),
        patch.object(server_mod, "recent_incidents", captured_incidents),
        patch.object(server_mod, "registered_devices", mock_registered),
        patch.object(server_mod, "active_pins", {mock_ws: dev_id}),
        patch.object(server_mod, "harmful_words_only", False),
    ):
        asyncio.run(
            server_mod.handle_completed_audio(
                dev_id, pcm_bytes, websocket=mock_ws, source="ESP32_DIRECT"
            )
        )
    e2e_latency_ms = asr_latency_ms + (time.perf_counter() - t_e2e_start) * 1000.0

    incident_events = [e for e in captured_broadcasts if e.get("event_type") == "incident"]
    danger_triggers_intercepted = [
        call.args[0] for call in mock_ws.send_text.call_args_list if call.args
    ]

    # Also evaluate isolated ContextEngine directly when transcript exists so intent/review metrics are visible
    assessment = None
    if hyp:
        assessment = isolated_engine.evaluate(hyp, device_id=f"{dev_id}-DIRECT", transcription_result=asr_result)

    rec.update({
        "e2e_incident_emitted": len(incident_events) > 0,
        "e2e_incident_payload_keys": sorted(incident_events[0].keys()) if incident_events else [],
        "e2e_danger_triggers_intercepted": danger_triggers_intercepted,
        "expected_intent": scenario.expected_intent,
        "predicted_intent": assessment.intent.value if assessment else "NO_INCIDENT",
        "expected_level": scenario.expected_level,
        "predicted_level": assessment.level if assessment else "NORMAL",
        "provisional_severity": scenario.provisional_severity,
        "provisional_severity_range": list(scenario.provisional_severity_range)
        if scenario.provisional_severity_range
        else None,
        "predicted_score": float(incident_events[0]["score"])
        if incident_events
        else (float(assessment.score) if assessment else 0.0),
        "predicted_category": incident_events[0]["category"]
        if incident_events
        else (assessment.category if assessment else "No Speech"),
        "expected_review_required": scenario.expected_review_required,
        "predicted_review_required": bool(assessment.human_review_required) if assessment else False,
        "is_friendly_teasing": scenario.is_friendly_teasing,
        "is_serious_threat": scenario.is_serious_threat,
        "latency_ms": round(e2e_latency_ms, 3),
    })
    return rec


def run_evaluation(
    datasets: Sequence[EvalDataset],
    modes: Optional[Sequence[str]] = None,
    skip_audio: bool = False,
    server_mod: Any = None,
) -> Dict[str, Any]:
    """
    Execute evaluation across one or more EvalDatasets and return a structured report dict.
    """
    allowed_modes = set(modes) if modes else {m.value for m in EvaluationMode}
    records: List[Dict[str, Any]] = []
    missing_fixtures: List[Dict[str, str]] = []
    unsupported_capabilities: List[Dict[str, str]] = []
    loaded_server = server_mod

    # Split-isolation verification when both dev and held_out are supplied
    split_checks: Dict[str, Any] = {}
    dev_sets = [d for d in datasets if d.split.value == "dev"]
    held_sets = [d for d in datasets if d.split.value == "held_out"]
    if dev_sets and held_sets:
        split_checks = verify_split_isolation(dev_sets[0], held_sets[0])

    for ds in datasets:
        for sc in ds.scenarios:
            if sc.mode.value not in allowed_modes:
                continue

            if sc.mode == EvaluationMode.TEXT:
                records.append(evaluate_text_scenario(sc))
            elif sc.mode == EvaluationMode.MULTI_TURN:
                records.append(evaluate_multi_turn_scenario(sc))
            elif sc.mode in (EvaluationMode.AUDIO, EvaluationMode.END_TO_END):
                if skip_audio:
                    rec = {
                        "id": sc.id,
                        "split": sc.split.value,
                        "mode": sc.mode.value,
                        "language": sc.language.value,
                        "status": "SKIPPED",
                        "reason": "Skipped by --skip-audio flag",
                        "audio_path": sc.audio_path,
                    }
                    records.append(rec)
                    continue

                resolved = _resolve_audio_path(sc.audio_path or "")
                if not resolved.exists():
                    rec = {
                        "id": sc.id,
                        "split": sc.split.value,
                        "mode": sc.mode.value,
                        "language": sc.language.value,
                        "status": "MISSING_FIXTURE",
                        "reason": f"Audio fixture not found on disk: {sc.audio_path}",
                        "audio_path": sc.audio_path,
                        "tags": list(sc.tags),
                    }
                    records.append(rec)
                    missing_fixtures.append({"id": sc.id, "audio_path": sc.audio_path or "", "reason": rec["reason"]})
                    continue

                if loaded_server is None:
                    loaded_server = _lazy_import_server()

                rec = evaluate_audio_scenario(
                    sc,
                    loaded_server,
                    end_to_end=(sc.mode == EvaluationMode.END_TO_END),
                )
                records.append(rec)
                if rec["status"] == "MISSING_FIXTURE":
                    missing_fixtures.append({"id": sc.id, "audio_path": sc.audio_path or "", "reason": rec["reason"]})
                elif rec["status"] == "UNSUPPORTED_CAPABILITY":
                    unsupported_capabilities.append({"id": sc.id, "reason": rec["reason"]})

    # Aggregate intent classification metrics
    intent_true: List[str] = []
    intent_pred: List[str] = []
    level_true: List[str] = []
    level_pred: List[str] = []
    text_latencies: List[float] = []
    audio_latencies: List[float] = []
    wers: List[float] = []
    cers: List[float] = []
    crit_total = 0
    crit_missed = 0
    neg_total = 0
    neg_missed = 0

    for rec in records:
        if rec.get("status") != "EVALUATED":
            continue
        if rec.get("expected_intent") and rec.get("predicted_intent"):
            intent_true.append(str(rec["expected_intent"]))
            intent_pred.append(str(rec["predicted_intent"]))
        if rec.get("expected_level") and rec.get("predicted_level"):
            level_true.append(str(rec["expected_level"]))
            level_pred.append(str(rec["predicted_level"]))
        if rec["mode"] in ("text", "multi_turn") and rec.get("latency_ms") is not None:
            text_latencies.append(float(rec["latency_ms"]))
        if rec["mode"] in ("audio", "end_to_end"):
            if rec.get("latency_ms") is not None:
                audio_latencies.append(float(rec["latency_ms"]))
            if rec.get("wer") is not None:
                wers.append(float(rec["wer"]))
            if rec.get("cer") is not None:
                cers.append(float(rec["cer"]))
            cw = rec.get("critical_word_errors") or {}
            nw = rec.get("negation_word_errors") or {}
            crit_total += int(cw.get("total", 0))
            crit_missed += int(cw.get("missed_count", 0))
            neg_total += int(nw.get("total", 0))
            neg_missed += int(nw.get("missed_count", 0))

    # Runtime capability audit (factual, never fabricated)
    capabilities: Dict[str, Any] = {
        "context_engine_bert_active": False,
        "usb_send_line_supported": False,
        "whisper_loaded": bool(getattr(loaded_server, "has_whisper", False)) if loaded_server else None,
        "nsnet2_loaded": bool(getattr(loaded_server, "has_nsnet2", False)) if loaded_server else None,
        "notes": [
            "ContextEngine V3 does not invoke TagalogBERT during evaluate() (audit finding #1).",
            "USBDeviceManager lacks send_line(); end-to-end harness runs under mocked ESP32_DIRECT websocket to avoid triggering hardware or hitting server.py:2682 AttributeError.",
            "UNCERTAIN_TRANSCRIPTION is currently dropped by server.py:2648 before reaching human review.",
        ],
    }

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "datasets": [
            {
                "name": d.dataset_name,
                "split": d.split.value,
                "schema_version": d.schema_version,
                "scenario_count": len(d.scenarios),
            }
            for d in datasets
        ],
        "split_isolation_check": split_checks,
        "counts": {
            "total_scenarios": len(records),
            "evaluated": sum(1 for r in records if r["status"] == "EVALUATED"),
            "missing_fixtures": len(missing_fixtures),
            "unsupported_capabilities": len(unsupported_capabilities),
            "skipped": sum(1 for r in records if r["status"] == "SKIPPED"),
        },
        "intent_classification": compute_classification_metrics(intent_true, intent_pred),
        "level_classification": compute_classification_metrics(level_true, level_pred),
        "safety_and_severity": compute_safety_and_severity_metrics(records),
        "asr_metrics": {
            "evaluated_audio_clips": len(audio_latencies),
            "mean_wer": round(sum(wers) / len(wers), 4) if wers else None,
            "mean_cer": round(sum(cers) / len(cers), 4) if cers else None,
            "critical_words_total": crit_total,
            "critical_words_missed": crit_missed,
            "critical_word_error_rate": round(crit_missed / crit_total, 4) if crit_total > 0 else None,
            "negation_words_total": neg_total,
            "negation_words_missed": neg_missed,
            "negation_word_error_rate": round(neg_missed / neg_total, 4) if neg_total > 0 else None,
        },
        "latency": {
            "text_and_multi_turn": compute_latency_stats(text_latencies),
            "audio_and_end_to_end": compute_latency_stats(audio_latencies),
        },
        "missing_fixtures": missing_fixtures,
        "unsupported_capabilities": unsupported_capabilities,
        "capabilities_audit": capabilities,
        "records": records,
    }
    return summary


def format_markdown_report(report: Dict[str, Any], command_used: str = "") -> str:
    """Format an evaluation report dict into a concise Markdown baseline report."""
    counts = report["counts"]
    intent_m = report["intent_classification"]
    level_m = report["level_classification"]
    safety = report["safety_and_severity"]
    asr = report["asr_metrics"]
    lat = report["latency"]

    ds_summary = ", ".join(
        f"{d['name']} ({d['split']}, n={d['scenario_count']})" for d in report["datasets"]
    )
    lines: List[str] = [
        "# SecureLink V3 Baseline Evaluation Report",
        "",
        f"**Generated (UTC):** {report['generated_at_utc']}  ",
        f"**Datasets:** {ds_summary}  ",
    ]
    if command_used:
        lines.append(f"**Reproduction Command:** `{command_used}`  ")
    lines.extend([
        "",
        "## 1. Execution Summary",
        f"- Total scenarios: **{counts['total_scenarios']}** | Evaluated: **{counts['evaluated']}** | Missing fixtures: **{counts['missing_fixtures']}** | Unsupported: **{counts['unsupported_capabilities']}** | Skipped: **{counts['skipped']}**",
        "",
        "## 2. Intent & Severity Classification Metrics",
        f"- **Intent Accuracy:** `{intent_m['accuracy']}` | **Macro Precision:** `{intent_m['macro_precision']}` | **Macro Recall:** `{intent_m['macro_recall']}` | **Macro F1:** `{intent_m['macro_f1']}` (n={intent_m['total']})",
        f"- **Level Accuracy:** `{level_m['accuracy']}` | **Level Macro F1:** `{level_m['macro_f1']}` (n={level_m['total']})",
        "",
        "## 3. Safety, Severity Agreement & Review Priority",
        f"- **Friendly-Teasing False Positives:** `{safety['friendly_teasing_false_positives']}/{safety['friendly_teasing_total']}` (rate={safety['friendly_teasing_fp_rate']}, IDs={safety['friendly_teasing_fp_ids']})",
        f"- **Serious-Threat False Negatives:** `{safety['serious_threat_false_negatives']}/{safety['serious_threat_total']}` (rate={safety['serious_threat_fn_rate']}, IDs={safety['serious_threat_fn_ids']})",
        f"- **False DANGER Classifications:** `{safety['false_danger_count']}/{safety['non_danger_total']}` (rate={safety['false_danger_rate']}, IDs={safety['false_danger_ids']})",
        f"- **Severity Level Exact Agreement:** `{safety['severity_level_exact_agreement']}` (n={safety['severity_level_total']})",
        f"- **Provisional Severity Range Agreement:** `{safety['severity_range_agreement']}` (n={safety['severity_range_total']}) | **Severity MAE:** `{safety['severity_mae']}`",
        f"- **Review-Priority Accuracy:** `{safety['review_priority_accuracy']}` | Precision: `{safety['review_priority_precision']}` | Recall: `{safety['review_priority_recall']}` (n={safety['review_priority_total']})",
        "",
        "## 4. ASR & Audio Metrics",
        f"- **Evaluated Audio Clips:** `{asr['evaluated_audio_clips']}`",
        f"- **Mean WER:** `{asr['mean_wer']}` | **Mean CER:** `{asr['mean_cer']}`",
        f"- **Critical-Word Recognition Error Rate:** `{asr['critical_word_error_rate']}` ({asr['critical_words_missed']}/{asr['critical_words_total']} missed)",
        f"- **Negation Recognition Error Rate:** `{asr['negation_word_error_rate']}` ({asr['negation_words_missed']}/{asr['negation_words_total']} missed)",
        "",
        "## 5. Processing Latency",
        f"- **Text / Multi-Turn (ms):** mean=`{lat['text_and_multi_turn']['mean_ms']}`, p50=`{lat['text_and_multi_turn']['p50_ms']}`, p95=`{lat['text_and_multi_turn']['p95_ms']}`, max=`{lat['text_and_multi_turn']['max_ms']}` (n={lat['text_and_multi_turn']['count']})",
        f"- **Audio / End-to-End (ms):** mean=`{lat['audio_and_end_to_end']['mean_ms']}`, p50=`{lat['audio_and_end_to_end']['p50_ms']}`, p95=`{lat['audio_and_end_to_end']['p95_ms']}`, max=`{lat['audio_and_end_to_end']['max_ms']}` (n={lat['audio_and_end_to_end']['count']})",
        "",
        "## 6. Missing Fixtures & Unsupported Capabilities",
    ])
    if report["missing_fixtures"]:
        for mf in report["missing_fixtures"]:
            lines.append(f"- **MISSING FIXTURE** `{mf['id']}`: `{mf['audio_path']}`")
    else:
        lines.append("- None")
    if report["unsupported_capabilities"]:
        for uc in report["unsupported_capabilities"]:
            lines.append(f"- **UNSUPPORTED** `{uc['id']}`: {uc['reason']}")
    for note in report["capabilities_audit"]["notes"]:
        lines.append(f"- *Capability Note:* {note}")

    lines.extend([
        "",
        "## 7. Scenario Results",
        "| ID | Split | Mode | Status | Expected Intent / Level | Predicted Intent / Level | Score | Review (Exp/Pred) | Latency (ms) |",
        "|---|---|---|---|---|---|---:|---|---:|",
    ])
    for r in report["records"]:
        exp_il = f"{r.get('expected_intent') or '-'} / {r.get('expected_level') or '-'}"
        pred_il = f"{r.get('predicted_intent') or r.get('transcription_status') or '-'} / {r.get('predicted_level') or '-'}"
        rev = f"{r.get('expected_review_required')}/{r.get('predicted_review_required')}" if r.get("status") == "EVALUATED" else "-"
        sc = r.get("predicted_score", "-")
        lat_ms = r.get("latency_ms", "-")
        lines.append(
            f"| `{r['id']}` | {r['split']} | {r['mode']} | {r['status']} | {exp_il} | {pred_il} | {sc} | {rev} | {lat_ms} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="SecureLink V4 Reproducible Evaluation Runner")
    parser.add_argument(
        "--dataset",
        action="append",
        required=True,
        help="Path to EvalDataset JSON file (may be specified multiple times).",
    )
    parser.add_argument(
        "--mode",
        choices=["all", "text", "multi_turn", "audio", "end_to_end"],
        default="all",
        help="Filter evaluation to a single mode (default: all).",
    )
    parser.add_argument(
        "--skip-audio",
        action="store_true",
        help="Skip audio and end_to_end scenarios (fast text-only run without loading Whisper).",
    )
    parser.add_argument("--output-json", default=None, help="Optional path to write full JSON report.")
    parser.add_argument("--output-md", default=None, help="Optional path to write Markdown report.")
    args = parser.parse_args(argv)

    datasets = [load_dataset(p) for p in args.dataset]
    modes = None if args.mode == "all" else [args.mode]
    report = run_evaluation(datasets, modes=modes, skip_audio=args.skip_audio)

    cmd_str = "python -m eval.runner " + " ".join(argv if argv is not None else sys.argv[1:])
    md = format_markdown_report(report, command_used=cmd_str)

    if args.output_json:
        out_j = Path(args.output_json)
        out_j.parent.mkdir(parents=True, exist_ok=True)
        out_j.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.output_md:
        out_m = Path(args.output_md)
        out_m.parent.mkdir(parents=True, exist_ok=True)
        out_m.write_text(md, encoding="utf-8")

    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

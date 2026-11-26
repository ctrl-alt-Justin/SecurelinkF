"""
Targeted automated tests for the SecureLink V4 Evaluation Framework (`eval/`).

Verifies:
- Dataset schema validation and dev/held-out split isolation
- WER, CER, critical-word, and negation recognition error metrics
- Precision, recall, F1, confusion matrix, safety slices, severity agreement, and latency stats
- Strict per-scenario ContextEngine history isolation
- Accurate reporting of missing audio fixtures and unsupported WAV formats
- Prevention of hardware triggers, real broadcasts, and disk WAV writes during end-to-end evaluation
"""

from __future__ import annotations

import os
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from eval.metrics import (
    compute_asr_metrics,
    compute_cer,
    compute_classification_metrics,
    compute_keyword_recognition_errors,
    compute_latency_stats,
    compute_negation_preservation,
    compute_safety_and_severity_metrics,
    compute_wer,
)
from eval.runner import (
    evaluate_audio_scenario,
    evaluate_multi_turn_scenario,
    evaluate_text_scenario,
    format_markdown_report,
    run_evaluation,
)
from eval.schema import (
    EvalDataset,
    EvalScenario,
    EvaluationMode,
    LanguageCode,
    SplitType,
    TurnItem,
    load_dataset,
    verify_split_isolation,
)


class TestEvalMetrics(unittest.TestCase):
    def test_wer_and_cer_exact_and_edits(self):
        self.assertEqual(compute_wer("Papatayin kita mamaya!", "papatayin kita mamaya"), 0.0)
        self.assertEqual(compute_cer("Papatayin kita", "papatayin kita"), 0.0)
        # 1 substitution out of 3 words -> 1/3
        self.assertAlmostEqual(compute_wer("hindi kita sasaktan", "hindi kita saktan"), 0.3333, places=4)
        # Empty reference handling
        self.assertEqual(compute_wer("", ""), 0.0)
        self.assertEqual(compute_wer("", "hallucinated"), 1.0)
        self.assertEqual(compute_cer("", ""), 0.0)
        self.assertEqual(compute_cer("", "abc"), 1.0)

    def test_critical_and_negation_word_recognition_errors(self):
        crit = compute_keyword_recognition_errors(["papatayin", "gate"], "papatayin kita sa labas")
        self.assertEqual(crit["total"], 2)
        self.assertEqual(crit["missed_count"], 1)
        self.assertEqual(crit["error_rate"], 0.5)
        self.assertEqual(crit["missed_words"], ["gate"])

        neg = compute_keyword_recognition_errors(["hindi"], "kita sasaktan")
        self.assertEqual(neg["total"], 1)
        self.assertEqual(neg["missed_count"], 1)
        self.assertEqual(neg["error_rate"], 1.0)

        empty = compute_keyword_recognition_errors([], "anything")
        self.assertIsNone(empty["error_rate"])

    def test_classification_metrics_and_confusion_matrix(self):
        y_true = ["NORMAL", "NORMAL", "THREAT", "DANGER"]
        y_pred = ["NORMAL", "THREAT", "THREAT", "DANGER"]
        m = compute_classification_metrics(y_true, y_pred)
        self.assertEqual(m["total"], 4)
        self.assertEqual(m["accuracy"], 0.75)
        self.assertEqual(m["per_class"]["NORMAL"]["precision"], 1.0)
        self.assertEqual(m["per_class"]["NORMAL"]["recall"], 0.5)
        self.assertEqual(m["per_class"]["THREAT"]["precision"], 0.5)
        self.assertEqual(m["per_class"]["THREAT"]["recall"], 1.0)
        self.assertEqual(m["per_class"]["DANGER"]["f1"], 1.0)
        self.assertEqual(m["confusion_matrix"]["NORMAL"]["THREAT"], 1)

    def test_safety_severity_and_review_metrics(self):
        records = [
            {
                "id": "S1",
                "status": "EVALUATED",
                "is_friendly_teasing": True,
                "is_serious_threat": False,
                "expected_level": "NORMAL",
                "predicted_level": "THREAT",
                "provisional_severity": 1.0,
                "provisional_severity_range": [0.0, 1.9],
                "predicted_score": 6.0,
                "expected_review_required": False,
                "predicted_review_required": False,
            },
            {
                "id": "S2",
                "status": "EVALUATED",
                "is_friendly_teasing": False,
                "is_serious_threat": True,
                "expected_level": "DANGER",
                "predicted_level": "NORMAL",
                "provisional_severity": 9.0,
                "provisional_severity_range": [8.0, 10.0],
                "predicted_score": 1.0,
                "expected_review_required": True,
                "predicted_review_required": False,
            },
            {
                "id": "S3",
                "status": "EVALUATED",
                "is_friendly_teasing": False,
                "is_serious_threat": False,
                "expected_level": "WARNING",
                "predicted_level": "DANGER",
                "provisional_severity": 3.0,
                "provisional_severity_range": [2.0, 3.9],
                "predicted_score": 8.5,
                "expected_review_required": True,
                "predicted_review_required": True,
            },
        ]
        s = compute_safety_and_severity_metrics(records)
        self.assertEqual(s["friendly_teasing_false_positives"], 1)
        self.assertEqual(s["friendly_teasing_fp_rate"], 1.0)
        self.assertEqual(s["serious_threat_false_negatives"], 1)
        self.assertEqual(s["serious_threat_fn_rate"], 1.0)
        self.assertEqual(s["false_danger_count"], 1)
        self.assertEqual(s["false_danger_ids"], ["S3"])
        self.assertEqual(s["severity_level_exact_agreement"], 0.0)
        self.assertEqual(s["severity_range_agreement"], 0.0)
        self.assertAlmostEqual(s["severity_mae"], (5.0 + 8.0 + 5.5) / 3.0, places=3)
        self.assertAlmostEqual(s["review_priority_accuracy"], 2 / 3, places=4)
        self.assertEqual(s["review_priority_precision"], 1.0)
        self.assertEqual(s["review_priority_recall"], 0.5)

    def test_latency_stats(self):
        stats = compute_latency_stats([10.0, 20.0, 30.0, 40.0, 100.0])
        self.assertEqual(stats["count"], 5)
        self.assertEqual(stats["mean_ms"], 40.0)
        self.assertEqual(stats["p50_ms"], 30.0)
        self.assertEqual(stats["max_ms"], 100.0)
        empty = compute_latency_stats([])
        self.assertEqual(empty["count"], 0)
        self.assertIsNone(empty["mean_ms"])


class TestEvalSchemaAndRunner(unittest.TestCase):
    def test_sample_datasets_load_and_are_disjoint(self):
        dev = load_dataset("eval/datasets/dev_sample.json")
        held = load_dataset("eval/datasets/held_out_sample.json")
        self.assertEqual(dev.split, SplitType.DEV)
        self.assertEqual(held.split, SplitType.HELD_OUT)
        iso = verify_split_isolation(dev, held)
        self.assertEqual(iso["overlapping_ids"], [])
        self.assertEqual(iso["overlapping_texts"], [])

    def test_scenario_history_isolation(self):
        """Multi-turn harassment in Scenario A must not leak into single-turn Scenario B."""
        sc_a = EvalScenario(
            id="ISO-A",
            split=SplitType.DEV,
            mode=EvaluationMode.MULTI_TURN,
            language=LanguageCode.TL,
            turns=[
                TurnItem(utterance="Bobo ka!", timestamp_offset_sec=0.0),
                TurnItem(utterance="Inutil ka!", timestamp_offset_sec=10.0),
                TurnItem(utterance="Tanga mo!", timestamp_offset_sec=20.0),
            ],
            expected_intent="VERBAL_HARASSMENT",
            expected_level="THREAT",
        )
        sc_b = EvalScenario(
            id="ISO-B",
            split=SplitType.DEV,
            mode=EvaluationMode.TEXT,
            language=LanguageCode.TL,
            utterance="Gago ka!",
            expected_intent="VERBAL_HARASSMENT",
            expected_level="THREAT",
        )
        res_a = evaluate_multi_turn_scenario(sc_a)
        res_b = evaluate_text_scenario(sc_b)
        self.assertGreaterEqual(res_a["predicted_score"], 7.0)
        self.assertLess(res_b["predicted_score"], 6.5)

    def test_missing_fixture_and_unsupported_wav_reported_accurately(self):
        missing_sc = EvalScenario(
            id="MISS-1",
            split=SplitType.DEV,
            mode=EvaluationMode.AUDIO,
            audio_path="eval/fixtures/audio/does_not_exist_xyz.wav",
            reference_transcript="Test",
        )
        ds = EvalDataset(dataset_name="test_missing", split=SplitType.DEV, scenarios=[missing_sc])
        report = run_evaluation([ds], skip_audio=False)
        self.assertEqual(report["counts"]["missing_fixtures"], 1)
        self.assertEqual(report["records"][0]["status"], "MISSING_FIXTURE")
        self.assertIsNone(report["asr_metrics"]["mean_wer"])

        # Unsupported WAV format (e.g., stereo 44.1kHz)
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_wav = Path(tmpdir) / "stereo_44k.wav"
            with wave.open(str(bad_wav), "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                wf.writeframes(np.zeros(2000, dtype=np.int16).tobytes())
            bad_sc = EvalScenario(
                id="BAD-WAV",
                split=SplitType.DEV,
                mode=EvaluationMode.AUDIO,
                audio_path=str(bad_wav),
                reference_transcript="",
            )
            fake_server = SimpleNamespace(process_audio_buffer=MagicMock())
            rec = evaluate_audio_scenario(bad_sc, fake_server, end_to_end=False)
            self.assertEqual(rec["status"], "UNSUPPORTED_CAPABILITY")
            self.assertIn("Unsupported WAV format", rec["reason"])
            fake_server.process_audio_buffer.assert_not_called()

    def test_end_to_end_prevents_hardware_triggers_and_disk_writes(self):
        """End-to-end audio evaluation must intercept triggers and never write WAVs or notify live UI."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "sample_1s.wav"
            pcm = np.zeros(16000, dtype=np.int16).tobytes()
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(pcm)

            sc = EvalScenario(
                id="E2E-SAFE-1",
                split=SplitType.DEV,
                mode=EvaluationMode.END_TO_END,
                language=LanguageCode.TL,
                audio_path=str(wav_path),
                reference_transcript="Papatayin kita!",
                expected_intent="DIRECT_THREAT",
                expected_level="DANGER",
                is_serious_threat=True,
                critical_words=["papatayin"],
            )

            # Build a lightweight mock server module mimicking server.py's handle_completed_audio contract
            real_save_wav = MagicMock()
            real_broadcast = AsyncMock()
            asr_status = SimpleNamespace(value="TRANSCRIBED")
            asr_result = SimpleNamespace(
                status=asr_status,
                transcript="Papatayin kita!",
                reason="Mock transcribed",
                metrics={"avg_logprob": -0.2},
                audio_quality={"raw_peak": 0.4},
            )

            async def _fake_handle_completed_audio(dev_id, pcm_bytes, websocket=None, source="ESP32_DIRECT"):
                res, clean = fake_server.process_audio_buffer(pcm_bytes)
                score, cat = fake_server.context_engine.evaluate(res.transcript, device_id=dev_id)
                if score >= 8.0 and websocket is not None:
                    await websocket.send_text("TRIGGER:DANGER")
                fake_server.save_wav(clean, "/should/never/write.wav")
                await fake_server.broadcast_to_ui({
                    "event_type": "incident",
                    "id": "EVT-MOCK",
                    "device_id": dev_id,
                    "score": float(score),
                    "category": cat,
                    "transcript": res.transcript,
                })

            fake_server = SimpleNamespace(
                process_audio_buffer=MagicMock(return_value=(asr_result, pcm)),
                handle_completed_audio=_fake_handle_completed_audio,
                context_engine=None,
                broadcast_to_ui=real_broadcast,
                save_wav=real_save_wav,
                recent_incidents=[],
                registered_devices={},
                active_pins={},
                harmful_words_only=False,
            )

            rec = evaluate_audio_scenario(sc, fake_server, end_to_end=True)
            self.assertEqual(rec["status"], "EVALUATED")
            self.assertTrue(rec["e2e_incident_emitted"])
            self.assertEqual(rec["e2e_danger_triggers_intercepted"], ["TRIGGER:DANGER"])
            self.assertEqual(rec["predicted_level"], "DANGER")
            # Real side-effect functions must NEVER be called
            real_save_wav.assert_not_called()
            real_broadcast.assert_not_called()

    def test_markdown_report_formatting_runs(self):
        dev = load_dataset("eval/datasets/dev_sample.json")
        report = run_evaluation([dev], skip_audio=True)
        md = format_markdown_report(report, command_used="python -m eval.runner --dataset eval/datasets/dev_sample.json --skip-audio")
        self.assertIn("# SecureLink V3 Baseline Evaluation Report", md)
        self.assertIn("ASR & Control Metrics", md)
        self.assertIn("Friendly-Teasing False Positives", md)
        self.assertIn("DEV-TXT-002", md)

    def test_e2e_dropped_utterance_does_not_fallback_to_classifier(self):
        """When handle_completed_audio emits NO incident, E2E must NOT substitute ContextEngine direct scoring."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "rejected_threat.wav"
            pcm = np.zeros(16000, dtype=np.int16).tobytes()
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(pcm)

            sc = EvalScenario(
                id="E2E-DROP-1",
                split=SplitType.DEV,
                mode=EvaluationMode.END_TO_END,
                language=LanguageCode.TL,
                audio_path=str(wav_path),
                reference_transcript="Papatayin kita!",
                expected_intent="DIRECT_THREAT",
                expected_level="DANGER",
                is_serious_threat=True,
                critical_words=["papatayin"],
            )

            asr_result = SimpleNamespace(
                status=SimpleNamespace(value="TRANSCRIPTION_REJECTED"),
                transcript="Papatayin kita!",
                reason="Mock lexical rejection",
                metrics={"avg_logprob": -1.5},
                audio_quality={"raw_peak": 0.4},
            )

            async def _drop_handle(dev_id, pcm_bytes, websocket=None, source="ESP32_DIRECT"):
                res, _clean = fake_server.process_audio_buffer(pcm_bytes)
                if res.status.value == "TRANSCRIBED" and res.transcript:
                    await fake_server.broadcast_to_ui({"event_type": "incident"})

            fake_server = SimpleNamespace(
                process_audio_buffer=MagicMock(return_value=(asr_result, pcm)),
                handle_completed_audio=_drop_handle,
                context_engine=None,
                broadcast_to_ui=AsyncMock(),
                save_wav=MagicMock(),
                recent_incidents=[],
                registered_devices={},
                active_pins={},
                harmful_words_only=False,
            )

            rec = evaluate_audio_scenario(sc, fake_server, end_to_end=True)
            self.assertEqual(rec["status"], "EVALUATED")
            self.assertFalse(rec["e2e_incident_emitted"])
            self.assertEqual(rec["predicted_intent"], "NO_INCIDENT")
            self.assertEqual(rec["predicted_level"], "NORMAL")
            self.assertEqual(rec["predicted_score"], 0.0)
            self.assertFalse(rec["predicted_review_required"])
            safety = compute_safety_and_severity_metrics([rec])
            self.assertEqual(safety["serious_threat_false_negatives"], 1)

    def test_asr_metrics_separates_controls_negations_and_outcomes(self):
        """Confirmed non-speech controls must stay out of speech WER and report false transcripts separately."""
        neg_ok = compute_negation_preservation("Hindi kita sasaktan", "hindi kita sasaktan", ["hindi"])
        self.assertEqual(neg_ok["expected_count"], 1)
        self.assertEqual(neg_ok["preserved_count"], 1)
        self.assertEqual(neg_ok["extra_inserted_count"], 0)

        neg_flip = compute_negation_preservation("Sasaktan kita", "hindi kita sasaktan")
        self.assertEqual(neg_flip["expected_count"], 0)
        self.assertEqual(neg_flip["extra_inserted_count"], 1)

        records = [
            {
                "id": "SP-1",
                "mode": "audio",
                "status": "EVALUATED",
                "is_non_speech_control": False,
                "transcription_status": "TRANSCRIBED",
                "hypothesis_transcript": "hindi kita sasaktan",
                "reference_transcript": "hindi kita sasaktan",
                "wer": 0.0,
                "cer": 0.0,
                "word_edit_counts": {"reference_words": 3, "hypothesis_words": 3, "edits": 0},
                "critical_word_errors": {"total": 1, "missed_count": 0},
                "negation_word_errors": {"total": 1, "missed_count": 0},
                "negation_preservation": neg_ok,
                "asr_latency_ms": 500.0,
            },
            {
                "id": "SP-2",
                "mode": "end_to_end",
                "status": "EVALUATED",
                "is_non_speech_control": False,
                "transcription_status": "UNCERTAIN_TRANSCRIPTION",
                "hypothesis_transcript": "wala",
                "reference_transcript": "hindi",
                "wer": 1.0,
                "cer": 0.8,
                "word_edit_counts": {"reference_words": 1, "hypothesis_words": 1, "edits": 1},
                "critical_word_errors": {"total": 0, "missed_count": 0},
                "negation_word_errors": {"total": 1, "missed_count": 1},
                "negation_preservation": compute_negation_preservation("hindi", "wala", ["hindi"]),
                "asr_latency_ms": 700.0,
            },
            {
                "id": "CTRL-1",
                "mode": "audio",
                "status": "EVALUATED",
                "is_non_speech_control": True,
                "transcription_status": "NO_SPEECH",
                "hypothesis_transcript": "",
                "reference_transcript": "",
                "asr_latency_ms": 5.0,
            },
            {
                "id": "CTRL-2",
                "mode": "audio",
                "status": "EVALUATED",
                "is_non_speech_control": True,
                "transcription_status": "TRANSCRIBED",
                "hypothesis_transcript": "thank you",
                "reference_transcript": "",
                "asr_latency_ms": 100.0,
            },
        ]
        asr = compute_asr_metrics(records)
        self.assertEqual(asr["evaluated_audio_clips"], 4)
        self.assertEqual(asr["speech_clips"], 2)
        self.assertEqual(asr["corpus_wer"], 0.25)  # 1 edit / 4 ref words; controls excluded
        self.assertEqual(asr["mean_wer"], 0.5)
        self.assertEqual(asr["non_speech_controls_total"], 2)
        self.assertEqual(asr["non_speech_false_transcripts"], 1)
        self.assertEqual(asr["non_speech_false_transcript_ids"], ["CTRL-2"])
        self.assertEqual(asr["speech_outcomes"], {"accepted": 1, "uncertain": 1, "rejected": 0, "no_speech": 0, "other": 0})
        self.assertEqual(asr["control_outcomes"], {"accepted": 1, "uncertain": 0, "rejected": 0, "no_speech": 1, "other": 0})
        self.assertEqual(asr["negation_tokens_preserved"], 1)
        self.assertEqual(asr["negation_tokens_expected"], 2)

    def test_e2e_uncertain_transcript_routed_without_danger_trigger(self):
        """Real server.handle_completed_audio routes UNCERTAIN_TRANSCRIPTION without firing DANGER."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "uncertain_threat.wav"
            pcm = np.zeros(16000, dtype=np.int16).tobytes()
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(pcm)

            import server as real_server  # imported via sys.path injected by eval.runner

            sc = EvalScenario(
                id="E2E-UNCERTAIN-1",
                split=SplitType.DEV,
                mode=EvaluationMode.END_TO_END,
                language=LanguageCode.TL,
                audio_path=str(wav_path),
                reference_transcript="Papatayin kita!",
                expected_intent="DIRECT_THREAT",
                expected_level="THREAT",
                expected_review_required=True,
                critical_words=["papatayin"],
            )
            uncertain_res = real_server.TranscriptionResult(
                status=real_server.TranscriptionStatus.UNCERTAIN_TRANSCRIPTION,
                transcript="Papatayin kita!",
                reason="Borderline acoustic confidence (avg_logprob=-1.250 < -1.10)",
                metrics={"avg_logprob": -1.25, "no_speech_prob": 0.1, "compression_ratio": 1.1},
                audio_quality={"raw_peak": 0.35},
            )
            with (
                patch.object(real_server, "process_audio_buffer", return_value=(uncertain_res, pcm)),
                patch.object(real_server, "UNCERTAIN_REVIEW_AUDIO_DIR", tmpdir),
            ):
                rec = evaluate_audio_scenario(sc, real_server, end_to_end=True)

            self.assertEqual(rec["status"], "EVALUATED")
            self.assertTrue(rec["e2e_incident_emitted"])
            self.assertTrue(rec["e2e_review_routed"])
            self.assertEqual(rec["e2e_danger_triggers_intercepted"], [])
            self.assertLess(rec["predicted_score"], 8.0)
            self.assertTrue(rec["predicted_review_required"])

    def test_v4_dev_300_dataset_integrity_and_isolation(self):
        from eval.validate_dataset import find_exact_and_near_duplicates, summarize_dataset

        dev_300 = load_dataset("eval/datasets/v4_dev_300.json")
        held_out = load_dataset("eval/datasets/held_out_sample.json")
        summary = summarize_dataset(dev_300)
        dups = find_exact_and_near_duplicates(dev_300, jaccard_threshold=0.85)
        iso = verify_split_isolation(dev_300, held_out)

        self.assertEqual(summary["total_scenarios"], 300)
        self.assertEqual(summary["provisional_tagged"], 300)
        self.assertEqual(
            summary["category_distribution"],
            {
                "ordinary_conversation": 45,
                "friendly_teasing": 40,
                "verbal_harassment": 40,
                "ambiguous_expression": 35,
                "direct_and_indirect_threats": 35,
                "multi_turn_conversation": 30,
                "reported_speech": 20,
                "negation_and_hypothetical": 20,
                "sarcasm_and_idioms": 20,
                "extortion_and_coercion": 15,
            },
        )
        self.assertEqual(dups["exact_duplicates"], [])
        self.assertEqual(dups["near_duplicates"], [])
        self.assertEqual(iso["overlapping_ids"], [])
        self.assertEqual(iso["overlapping_texts"], [])


if __name__ == "__main__":
    unittest.main()

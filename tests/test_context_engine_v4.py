"""
Comprehensive unit & integration tests for SecureLink V4:
- ContextEngine V4 compositional linguistic rules (Filipino, English, Taglish)
- Active TagalogBERT hybrid fusion + confidence-gated graceful rules fallback
- Local checkpoint compatibility (`securelink_final_model` -> ContextEngine)
- Episode-aware escalation separation (~8s USB split chunks vs distinct episodes)
- `securelinkdb/train.py` stratified split, balanced class weights, WeightedLossTrainer, and export
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer, RobertaConfig, RobertaForSequenceClassification

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SECURELINK_DIR = WORKSPACE_ROOT / "securelinkdb"
if str(SECURELINK_DIR) not in sys.path:
    sys.path.insert(0, str(SECURELINK_DIR))

from context_engine import (  # noqa: E402
    ContextEngine,
    IncidentLevel,
    ThreatIntent,
    ThreatType,
)
import train as train_mod  # noqa: E402


class _FakeTokenizer:
    def __call__(self, text, return_tensors="pt", truncation=True, max_length=128):
        return {
            "input_ids": torch.tensor([[0, 1, 2]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }


class _FixedLogitsBert:
    """Deterministic stub model outputting fixed logits on demand."""

    def __init__(self, logits_list):
        self._logits = torch.tensor([logits_list], dtype=torch.float32)

    def parameters(self):
        yield torch.zeros(1)

    def __call__(self, **kwargs):
        return SimpleNamespace(logits=self._logits)


class TestContextEngineV4HybridAndRules(unittest.TestCase):
    def test_v4_default_rules_without_bert_weights_gracefully_fallback(self):
        engine = ContextEngine(bert_model=None, tokenizer=None)
        res = engine.evaluate("Papatayin kita mamaya sa gate!", device_id="V4-NOBERT")
        self.assertEqual(res.intent, ThreatIntent.DIRECT_THREAT)
        self.assertEqual(res.level, IncidentLevel.DANGER.value)
        self.assertFalse(res.context.model_used)
        self.assertEqual(res.context.model_confidence, 1.0)

    def test_v4_active_bert_high_confidence_upgrades_unpatterned_extortion_and_caps_semantic_threat(self):
        # Class 2 (EXTORTION) with softmax ~0.95
        ext_engine = ContextEngine(
            bert_model=_FixedLogitsBert([0.0, 0.0, 5.0, 0.0]),
            tokenizer=_FakeTokenizer(),
            bert_confidence_threshold=0.65,
        )
        res_ext = ext_engine.evaluate("Dalhin mo bukas yung pambayad sa locker.", device_id="V4-BERT-2")
        self.assertTrue(res_ext.context.model_used)
        self.assertEqual(res_ext.context.model_label, 2)
        self.assertGreater(res_ext.context.model_confidence, 0.90)
        self.assertEqual(res_ext.intent, ThreatIntent.EXTORTION)
        self.assertEqual(res_ext.level, IncidentLevel.THREAT.value)
        self.assertTrue(res_ext.human_review_required)

        # Class 3 (semantic physical threat) without explicit rule match MUST cap < 8.0 and flag review
        thr_engine = ContextEngine(
            bert_model=_FixedLogitsBert([0.0, 0.0, 0.0, 5.0]),
            tokenizer=_FakeTokenizer(),
            bert_confidence_threshold=0.65,
        )
        res_thr = thr_engine.evaluate("Magkita tayo sa likod pag uwian.", device_id="V4-BERT-3")
        self.assertTrue(res_thr.context.model_used)
        self.assertEqual(res_thr.intent, ThreatIntent.DIRECT_THREAT)
        self.assertLess(res_thr.score, 8.0, "Semantic-only BERT threat must never trigger DANGER directly")
        self.assertEqual(res_thr.level, IncidentLevel.THREAT.value)
        self.assertTrue(res_thr.human_review_required)

    def test_v4_low_confidence_bert_falls_back_and_never_overrides_negation(self):
        # Low-confidence model ([0.4, 0.2, 0.2, 0.2] -> ~0.30) must fall back to rules
        low_conf_engine = ContextEngine(
            bert_model=_FixedLogitsBert([0.0, 0.0, 0.0, 0.2]),
            tokenizer=_FakeTokenizer(),
            bert_confidence_threshold=0.65,
        )
        res_low = low_conf_engine.evaluate("Tara kain tayo sa canteen mamaya.", device_id="V4-LOWCONF")
        self.assertTrue(res_low.context.model_used)
        self.assertLess(res_low.context.model_confidence, 0.65)
        self.assertEqual(res_low.intent, ThreatIntent.ORDINARY_CONVERSATION)
        self.assertTrue(any("rules fallback" in rf for rf in res_low.risk_factors))

        # High-confidence BERT predicting threat must NEVER override explicit negation
        neg_guard_engine = ContextEngine(
            bert_model=_FixedLogitsBert([0.0, 0.0, 0.0, 5.0]),
            tokenizer=_FakeTokenizer(),
            bert_confidence_threshold=0.65,
        )
        res_neg = neg_guard_engine.evaluate("Hindi kita sasaktan.", device_id="V4-NEGGUARD")
        self.assertEqual(res_neg.intent, ThreatIntent.NEGATED_THREAT)
        self.assertEqual(res_neg.level, IncidentLevel.NORMAL.value)

    def test_local_checkpoint_loads_and_evaluates_if_present(self):
        model_dir = SECURELINK_DIR / "securelink_final_model"
        if not model_dir.is_dir():
            self.skipTest("Local securelink_final_model weights not present")
        engine = ContextEngine(bert_confidence_threshold=0.65)
        self.assertTrue(engine.load_local_checkpoint(str(model_dir)))
        res = engine.evaluate("Tara kain tayo sa canteen mamaya.", device_id="V4-LOCAL-CKPT")
        self.assertTrue(res.context.model_used)
        self.assertIsNotNone(res.context.model_probabilities)
        self.assertEqual(set(res.context.model_probabilities.keys()), {"0", "1", "2", "3"})
        self.assertEqual(res.intent, ThreatIntent.ORDINARY_CONVERSATION)

    def test_humor_masked_threats_retained_and_friendly_banter_preserved(self):
        engine = ContextEngine()
        # Serious threats followed by joke disclaimers MUST NOT become NORMAL
        masked_cases = [
            ("Papatayin kita mamaya sa gate, joke lang.", ThreatIntent.DIRECT_THREAT),
            ("Bubugbugin kita paglabas mo ng school, biro lang!", ThreatIntent.DIRECT_THREAT),
            ("Sasapakin kita sa mukha ngayon, charot lang.", ThreatIntent.DIRECT_THREAT),
            ("I will stab you after school, just kidding.", ThreatIntent.DIRECT_THREAT),
            ("Ilabas mo na yung baon mo ngayon, joke lang!", ThreatIntent.EXTORTION),
        ]
        for text, expected_intent in masked_cases:
            res = engine.evaluate(text, device_id="V4-MASKED")
            self.assertEqual(res.intent, expected_intent, f"Failed for {text}")
            self.assertEqual(res.level, IncidentLevel.THREAT.value)
            self.assertLess(res.score, 8.0)
            self.assertTrue(res.human_review_required)

        # Mutual friendly banter must stay NORMAL
        banter_cases = [
            "Ang bobo mo naman mag-tank sa ML pre, haha bawi next game!",
            "Tanga mo pre sablay yung ulti mo haha, clutch ko na to!",
            "Gago ka pre, ang taas ng score mo sa physics, ikaw na lodi!",
            "Shut up, I'll beat you in the next quarter lol!",
        ]
        for text in banter_cases:
            res = engine.evaluate(text, device_id="V4-BANTER")
            self.assertEqual(res.intent, ThreatIntent.ORDINARY_CONVERSATION, f"False positive on {text}")
            self.assertEqual(res.level, IncidentLevel.NORMAL.value)

    def test_contrastive_clauses_negation_past_and_quoted_threats(self):
        engine = ContextEngine()

        # Contrastive clause: negation/idiom/past BEFORE active threat must NOT suppress threat
        r1 = engine.evaluate("Hindi kita sasaktan ngayon, pero papatayin kita bukas sa labas!", device_id="V4-CONT1")
        self.assertEqual(r1.intent, ThreatIntent.DIRECT_THREAT)
        self.assertEqual(r1.level, IncidentLevel.DANGER.value)

        r2 = engine.evaluate("Mahal kita pero sasapakin kita pag lumapit ka pa sa kanya!", device_id="V4-CONT2")
        self.assertEqual(r2.intent, ThreatIntent.DIRECT_THREAT)
        self.assertEqual(r2.level, IncidentLevel.DANGER.value)

        r3 = engine.evaluate("Kanina pa kita hinihintay, bubugbugin kita ngayon na!", device_id="V4-CONT3")
        self.assertEqual(r3.intent, ThreatIntent.DIRECT_THREAT)
        self.assertEqual(r3.level, IncidentLevel.DANGER.value)

        # Bare 'kanina'/'kahapon' without harm verb stays ORDINARY
        r_ord = engine.evaluate("Pahiram naman ng notes sa GenMath, di ko nakopya kanina.", device_id="V4-ORD")
        self.assertEqual(r_ord.intent, ThreatIntent.ORDINARY_CONVERSATION)
        self.assertEqual(r_ord.level, IncidentLevel.NORMAL.value)

        # Quoted digital threat never triggers DANGER
        r_rep = engine.evaluate("He literally texted 'I will punch your face' to my friend.", device_id="V4-REP")
        self.assertEqual(r_rep.intent, ThreatIntent.REPORTED_THREAT)
        self.assertLess(r_rep.score, 8.0)
        self.assertTrue(r_rep.human_review_required)

        # Word-boundary fix in extract_context ('investigate' / 'gunitain' must not match 'gate' / 'gun')
        r_wb = engine.evaluate("We will investigate and gunitain the history tomorrow.", device_id="V4-WB")
        self.assertEqual(r_wb.context.specificity, "LOW")

    def test_filipino_identity_term_hoy_bakla_ka_context_separation(self):
        engine = ContextEngine()

        # 1. Ambiguous standalone identity term -> AMBIGUOUS_CONTEXT + review (NOT auto-bullying)
        ambig = engine.evaluate("Hoy, bakla ka!", device_id="V4-BAKLA-AMB")
        self.assertEqual(ambig.intent, ThreatIntent.AMBIGUOUS_CONTEXT)
        self.assertEqual(ambig.level, IncidentLevel.WARNING.value)
        self.assertTrue(ambig.human_review_required)
        self.assertLess(ambig.score, 4.0)

        # 2. Benign friendly turn -> NORMAL
        benign = engine.evaluate("Hoy bakla, haha binilhan kita ng turon sa canteen bes!", device_id="V4-BAKLA-BEN")
        self.assertEqual(benign.intent, ThreatIntent.ORDINARY_CONVERSATION)
        self.assertEqual(benign.level, IncidentLevel.NORMAL.value)

        # 3. Hostile exclusion -> VERBAL_HARASSMENT (capped < DANGER)
        hostile = engine.evaluate("Hoy, bakla ka! Lumayo ka nga dito, nakakadiri ka!", device_id="V4-BAKLA-HAR")
        self.assertEqual(hostile.intent, ThreatIntent.VERBAL_HARASSMENT)
        self.assertEqual(hostile.level, IncidentLevel.THREAT.value)
        self.assertLess(hostile.score, 8.0)

    def test_split_stream_chunks_vs_repeated_episodes_and_social_intimidation_count(self):
        engine = ContextEngine(episode_gap_seconds=20.0, chunk_continuation_window_seconds=9.5)

        # Three consecutive ~8s USB split chunks of ONE utterance -> stay episode 1, NO escalation
        base_ts = 1_700_000_000.0
        c1 = engine.evaluate("Bobo ka talaga...", device_id="V4-SPLIT", timestamp=base_ts)
        c2 = engine.evaluate("...tanga mo sa klase...", device_id="V4-SPLIT", timestamp=base_ts + 8.0)
        c3 = engine.evaluate("...walang kwenta kausap.", device_id="V4-SPLIT", timestamp=base_ts + 16.0)
        self.assertEqual(c1.context.episode_id, 1)
        self.assertEqual(c2.context.episode_id, 1)
        self.assertTrue(c2.context.is_split_chunk)
        self.assertEqual(c3.context.episode_id, 1)
        self.assertEqual(c3.context.distinct_episodes, 1)
        self.assertLess(c3.score, 7.0, "8s split chunks must not falsely escalate as repeated episodes")

        # Three SEPARATE bullying episodes (>20s apart) -> distinct episodes = 3, escalates within THREAT (< 8.0)
        e1 = engine.evaluate("Bobo ka talaga!", device_id="V4-MULTI", timestamp=base_ts)
        e2 = engine.evaluate("Inutil ka!", device_id="V4-MULTI", timestamp=base_ts + 60.0)
        e3 = engine.evaluate("Wala kang kwenta!", device_id="V4-MULTI", timestamp=base_ts + 120.0)
        self.assertEqual(e1.context.episode_id, 1)
        self.assertEqual(e2.context.episode_id, 2)
        self.assertEqual(e3.context.episode_id, 3)
        self.assertEqual(e3.context.distinct_episodes, 3)
        self.assertGreaterEqual(e3.score, 7.0)
        self.assertLess(e3.score, 8.0)

        # Physical threats must NOT inflate social intimidation_count
        engine.evaluate("Papatayin kita!", device_id="V4-INTIM-SEP", timestamp=base_ts)
        tracker = engine.escalation_manager.get_tracker("V4-INTIM-SEP")
        metrics = tracker.get_escalation_metrics(current_time=base_ts + 60.0)
        self.assertEqual(metrics["intimidation_count"], 0)

    def test_v4_asr_slip_rescue_bounded_warning_and_non_regression(self):
        # Even with a high-confidence threat BERT stub, ASR-slip rescue must NEVER trigger DANGER
        engine = ContextEngine(
            bert_model=_FixedLogitsBert([0.0, 0.0, 0.0, 5.0]),
            tokenizer=_FakeTokenizer(),
            bert_confidence_threshold=0.65,
        )
        slip_cases = [
            "Subukan mong bubukbugin kita mamaya!",
            "Sasabakin kita sa gate paglabas!",
            "Sondokin kita mamaya eh.",
        ]
        for text in slip_cases:
            res = engine.evaluate(text, device_id="V4-ASR-SLIP")
            self.assertEqual(res.intent, ThreatIntent.AMBIGUOUS_CONTEXT, f"Expected AMBIGUOUS_CONTEXT for {text}")
            self.assertEqual(res.level, IncidentLevel.WARNING.value, f"Expected WARNING for {text}")
            self.assertEqual(res.category, "ASR-Slip Threat Review")
            self.assertLess(res.score, 4.0)
            self.assertGreaterEqual(res.score, 2.0)
            self.assertTrue(res.human_review_required)
            self.assertNotEqual(res.level, IncidentLevel.DANGER.value)

        # Benign lookalikes and negated phrases must remain CONVERSATIONAL / NORMAL
        safe_engine = ContextEngine()
        benign_cases = [
            "Sapat na yung baon ko mamaya sa gate pre.",
            "Hindi kita bubukbugin mamaya, joke lang pre.",
            "Batay sa sinabi mo kanina, tapos na tayo mamaya.",
        ]
        for text in benign_cases:
            res = safe_engine.evaluate(text, device_id="V4-ASR-SAFE")
            self.assertEqual(res.level, IncidentLevel.NORMAL.value, f"False positive on benign lookalike: {text}")


class TestTrainPipelineV4(unittest.TestCase):
    def test_stratified_split_class_weights_weighted_trainer_and_export_compat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Imbalanced synthetic CSV (16 class-0, 8 class-1, 6 class-2, 6 class-3 + 1 duplicate)
            rows = []
            for i in range(16):
                rows.append((f"Tara kain tayo sa canteen pre {i}", 0))
            rows.append(("Tara kain tayo sa canteen pre 0", 0))  # exact dup to be removed
            for i in range(8):
                rows.append((f"Ang bobo mo talaga classmate {i}", 1))
            for i in range(6):
                rows.append((f"Ibigay mo na baon mo ngayon {i}", 2))
            for i in range(6):
                rows.append((f"Sasapakin kita mamaya sa gate {i}", 3))

            csv_path = tmp / "expanded_synth.csv"
            pd.DataFrame(rows, columns=["text", "label"]).to_csv(csv_path, index=False)

            train_df, val_df = train_mod.load_and_prepare_dataset(csv_path, val_size=0.25, seed=42)
            self.assertEqual(len(train_df) + len(val_df), 36)  # 37 minus 1 duplicate
            self.assertEqual(set(val_df["label"].unique()), {0, 1, 2, 3})

            weights = train_mod.compute_balanced_class_weights(train_df["label"].tolist(), num_labels=4)
            self.assertEqual(weights.shape, (4,))
            self.assertGreater(float(weights[2]), float(weights[0]), "Minority class must receive higher weight")

            # Tiny offline RobertaConfig model verifying WeightedLossTrainer + save/load into ContextEngine
            local_tok_dir = SECURELINK_DIR / "securelink_final_model"
            tok = (
                AutoTokenizer.from_pretrained(str(local_tok_dir), local_files_only=True)
                if local_tok_dir.is_dir()
                else _FakeTokenizer()
            )
            tiny_vocab = getattr(tok, "vocab_size", 256)
            tiny_cfg = RobertaConfig(
                vocab_size=tiny_vocab,
                hidden_size=32,
                num_hidden_layers=1,
                num_attention_heads=2,
                intermediate_size=64,
                num_labels=4,
                id2label=train_mod.ID2LABEL,
                label2id=train_mod.LABEL2ID,
            )
            tiny_model = RobertaForSequenceClassification(tiny_cfg)
            loss_trainer = train_mod.WeightedLossTrainer(model=tiny_model, class_weights=weights)
            batch = {
                "input_ids": torch.tensor([[1, 2, 3, 4], [5, 6, 7, 8]]),
                "attention_mask": torch.tensor([[1, 1, 1, 1], [1, 1, 1, 0]]),
                "labels": torch.tensor([0, 3]),
            }
            loss = loss_trainer.compute_loss(tiny_model, batch)
            self.assertTrue(torch.is_tensor(loss))
            self.assertGreater(float(loss.item()), 0.0)

            metrics_fn = train_mod.build_compute_metrics(num_labels=4)
            eval_out = metrics_fn(([[4.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 4.0]], [0, 3]))
            self.assertEqual(eval_out["accuracy"], 1.0)
            self.assertEqual(eval_out["f1_class_0"], 1.0)
            self.assertEqual(eval_out["f1_class_3"], 1.0)

            # Verify saved checkpoint reloads with AutoModelForSequenceClassification(local_files_only=True)
            export_dir = tmp / "exported_model"
            tiny_model.save_pretrained(str(export_dir))
            reloaded = AutoModelForSequenceClassification.from_pretrained(str(export_dir), local_files_only=True)
            engine = ContextEngine(bert_model=reloaded, tokenizer=tok)
            res = engine.predict_transformer("Papatayin kita!")
            self.assertTrue(res["used"])
            self.assertEqual(set(res["probabilities"].keys()), {"0", "1", "2", "3"})


if __name__ == "__main__":
    unittest.main()

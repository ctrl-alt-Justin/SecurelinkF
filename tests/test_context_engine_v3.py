import sys
import os
import time
import threading
import unittest

sys.path.insert(0, os.path.abspath("securelinkdb"))
from context_engine import (
    ContextEngine,
    ThreatIntent,
    ThreatType,
    IncidentLevel,
    EvidenceReliability,
    SeverityAssessment,
)


class TestContextEngineV3(unittest.TestCase):

    def setUp(self):
        self.engine = ContextEngine(escalation_window_seconds=600.0)

    # -------------------------------------------------------------------------
    # 1. Idiomatic Non-Threats
    # -------------------------------------------------------------------------
    def test_idiomatic_non_threats(self):
        test_cases = [
            ("Patay na patay ako sa kanya.", ThreatIntent.ORDINARY_CONVERSATION, IncidentLevel.NORMAL),
            ("Grabe, nakakamatay yung exam.", ThreatIntent.ORDINARY_CONVERSATION, IncidentLevel.NORMAL),
            ("Babawi ako sa susunod.", ThreatIntent.ORDINARY_CONVERSATION, IncidentLevel.NORMAL),
            ("Wag ka mag-alala, biro lang.", ThreatIntent.ORDINARY_CONVERSATION, IncidentLevel.NORMAL),
            ("Mahal kita sobra.", ThreatIntent.ORDINARY_CONVERSATION, IncidentLevel.NORMAL),
            ("Tara kain tayo sa canteen mamaya.", ThreatIntent.ORDINARY_CONVERSATION, IncidentLevel.NORMAL),
        ]
        for text, expected_intent, expected_level in test_cases:
            res = self.engine.evaluate(text, device_id="TEST-IDIOM")
            self.assertEqual(res.intent, expected_intent, f"Failed intent for: {text}")
            self.assertEqual(res.level, expected_level.value, f"Failed level for: {text} (score={res.score})")
            self.assertLess(res.score, 2.0)

    # -------------------------------------------------------------------------
    # 2. Negated Threats
    # -------------------------------------------------------------------------
    def test_negated_threats(self):
        test_cases = [
            "Hindi kita sasaktan.",
            "Di kita papatayin.",
            "Wala akong gagawing masama sa'yo.",
            "I will not hurt you.",
        ]
        for text in test_cases:
            res = self.engine.evaluate(text, device_id="TEST-NEG")
            self.assertEqual(res.intent, ThreatIntent.NEGATED_THREAT, f"Failed for: {text}")
            self.assertEqual(res.level, IncidentLevel.NORMAL.value)
            self.assertLess(res.score, 2.0)

    # -------------------------------------------------------------------------
    # 3. Hypothetical & Dream Statements
    # -------------------------------------------------------------------------
    def test_hypothetical_statements(self):
        test_cases = [
            "Napanaginipan kong namatay siya.",
            "Paano kung may kutsilyo ako?",
            "What if mawala siya?",
        ]
        for text in test_cases:
            res = self.engine.evaluate(text, device_id="TEST-HYP")
            self.assertEqual(res.intent, ThreatIntent.HYPOTHETICAL_THREAT, f"Failed for: {text}")
            self.assertIn(res.level, (IncidentLevel.NORMAL.value, IncidentLevel.WARNING.value))
            self.assertLess(res.score, 4.0)

    # -------------------------------------------------------------------------
    # 4. Reported Speech
    # -------------------------------------------------------------------------
    def test_reported_speech(self):
        test_cases = [
            "Sinabi niya na papatayin niya ako.",
            "Sabi nila bubugbugin daw ako mamaya.",
            "He said that he would beat me up.",
        ]
        for text in test_cases:
            res = self.engine.evaluate(text, device_id="TEST-REP")
            self.assertEqual(res.intent, ThreatIntent.REPORTED_THREAT, f"Failed for: {text}")
            self.assertEqual(res.level, IncidentLevel.THREAT.value)
            self.assertLess(res.score, 8.0, "Reported threat must never trigger DANGER!")
            self.assertTrue(res.human_review_required)

    # -------------------------------------------------------------------------
    # 5. Past Incidents
    # -------------------------------------------------------------------------
    def test_past_incidents(self):
        test_cases = [
            "Sinapak ako kahapon sa labas.",
            "Binugbog siya nung isang linggo.",
        ]
        for text in test_cases:
            res = self.engine.evaluate(text, device_id="TEST-PAST")
            self.assertEqual(res.intent, ThreatIntent.PAST_INCIDENT, f"Failed for: {text}")
            self.assertIn(res.level, (IncidentLevel.WARNING.value, IncidentLevel.THREAT.value))
            self.assertLess(res.score, 8.0, "Past incident must never trigger DANGER!")

    # -------------------------------------------------------------------------
    # 6. Verbal Harassment Capped Below DANGER
    # -------------------------------------------------------------------------
    def test_verbal_harassment_capped_below_danger(self):
        # Single targeted insult
        res = self.engine.evaluate("Ang bobo mo talaga, umalis ka nga dito!", device_id="PIN-HARASS")
        self.assertEqual(res.intent, ThreatIntent.VERBAL_HARASSMENT)
        self.assertEqual(res.level, IncidentLevel.THREAT.value)
        self.assertLess(res.score, 8.0, "Single insult must NOT reach DANGER!")

        # Repeated insults on same device
        res2 = self.engine.evaluate("Pangit mo inutil ka!", device_id="PIN-HARASS")
        res3 = self.engine.evaluate("Wala kang kwenta gago ka!", device_id="PIN-HARASS")
        self.assertEqual(res3.level, IncidentLevel.THREAT.value)
        self.assertLess(res3.score, 8.0, "Repeated verbal harassment must NEVER reach DANGER (>=8.0)!")
        self.assertGreaterEqual(res3.score, 7.0, "Repeated harassment should escalate severity within THREAT band")

    # -------------------------------------------------------------------------
    # 7. Extortion & Coercion
    # -------------------------------------------------------------------------
    def test_extortion_and_coercion(self):
        res_ext = self.engine.evaluate("Akin na yang baon mo kundi aabangan kita sa gate.", device_id="PIN-EXT")
        self.assertEqual(res_ext.intent, ThreatIntent.EXTORTION)
        self.assertEqual(res_ext.level, IncidentLevel.THREAT.value)

        res_ext2 = self.engine.evaluate("Araw-araw mo akong babayaran.", device_id="PIN-EXT2")
        self.assertEqual(res_ext2.intent, ThreatIntent.EXTORTION)
        self.assertEqual(res_ext2.level, IncidentLevel.THREAT.value)

        res_coer = self.engine.evaluate("Huwag mong sabihin sa teacher.", device_id="PIN-COER")
        self.assertEqual(res_coer.intent, ThreatIntent.COERCION)
        self.assertEqual(res_coer.level, IncidentLevel.THREAT.value)

    # -------------------------------------------------------------------------
    # 8. Indirect / School Intimidation Patterns
    # -------------------------------------------------------------------------
    def test_indirect_school_intimidation(self):
        scenarios = [
            "Alam mo na mangyayari sa'yo mamaya.",
            "May kakausap sa'yo pagkatapos ng klase.",
            "Sa susunod na makita kita, ewan ko na lang.",
            "Hindi pa tayo tapos.",
            "Abangan kita sa gate mamaya.",
        ]
        for s in scenarios:
            res = self.engine.evaluate(s, device_id="PIN-IND")
            self.assertEqual(res.intent, ThreatIntent.DIRECT_THREAT, f"Failed for: {s}")
            self.assertEqual(res.level, IncidentLevel.THREAT.value, f"Failed level for: {s}")
            self.assertGreaterEqual(res.score, 5.5)

    # -------------------------------------------------------------------------
    # 9. Direct Physical Threats (DANGER >= 8.0)
    # -------------------------------------------------------------------------
    def test_direct_physical_threats(self):
        scenarios = [
            "Papatayin kita.",
            "Sasapakin kita paglabas mo ng school!",
            "Bubugbugin kita mamaya sa gate.",
            "I will kill you.",
        ]
        for s in scenarios:
            res = self.engine.evaluate(s, device_id="PIN-DANGER")
            self.assertEqual(res.intent, ThreatIntent.DIRECT_THREAT)
            self.assertEqual(res.threat_type, ThreatType.PHYSICAL_VIOLENCE)
            self.assertEqual(res.level, IncidentLevel.DANGER.value, f"Must be DANGER: {s}")
            self.assertGreaterEqual(res.score, 8.0)

    # -------------------------------------------------------------------------
    # 10. Device Isolation (No Cross-Contamination)
    # -------------------------------------------------------------------------
    def test_device_isolation(self):
        # Device A receives 3 insults
        self.engine.evaluate("Bobo ka!", device_id="DEV-A")
        self.engine.evaluate("Inutil ka!", device_id="DEV-A")
        res_a3 = self.engine.evaluate("Tanga mo!", device_id="DEV-A")
        self.assertGreaterEqual(res_a3.score, 7.0)

        # Device B receives 1 mild insult: must NOT inherit Device A's escalation!
        res_b1 = self.engine.evaluate("Gago ka!", device_id="DEV-B")
        self.assertLess(res_b1.score, 6.5, "Device B must not inherit Device A's escalation count!")

    # -------------------------------------------------------------------------
    # 11. Backward Compatibility (Tuple Unpacking & Slicing)
    # -------------------------------------------------------------------------
    def test_backward_compatibility(self):
        score, category = self.engine.evaluate("Papatayin kita.")
        self.assertIsInstance(score, float)
        self.assertIsInstance(category, str)
        self.assertGreaterEqual(score, 8.0)
        self.assertEqual(category, "Physical Threat")

        assessment = self.engine.evaluate("Papatayin kita.")
        self.assertEqual(assessment[0], score)
        self.assertEqual(assessment[1], category)
        self.assertEqual(len(assessment), 2)

    # -------------------------------------------------------------------------
    # 12. English & Taglish Code-Switching
    # -------------------------------------------------------------------------
    def test_english_and_taglish_code_switching(self):
        # English direct threat
        res_en = self.engine.evaluate("I will punch you right now!", device_id="DEV-EN")
        self.assertEqual(res_en.intent, ThreatIntent.DIRECT_THREAT)
        self.assertEqual(res_en.level, IncidentLevel.DANGER.value)

        # English extortion
        res_ext_en = self.engine.evaluate("Give me your lunch money or else!", device_id="DEV-EN2")
        self.assertEqual(res_ext_en.intent, ThreatIntent.EXTORTION)
        self.assertEqual(res_ext_en.level, IncidentLevel.THREAT.value)

        # English coercion
        res_coer_en = self.engine.evaluate("Don't tell anyone about this.", device_id="DEV-EN3")
        self.assertEqual(res_coer_en.intent, ThreatIntent.COERCION)
        self.assertEqual(res_coer_en.level, IncidentLevel.THREAT.value)

        # Taglish extortion
        res_taglish = self.engine.evaluate("Ibigay mo na yung baon mo kundi lagot ka.", device_id="DEV-TL")
        self.assertEqual(res_taglish.intent, ThreatIntent.EXTORTION)
        self.assertEqual(res_taglish.level, IncidentLevel.THREAT.value)

    # -------------------------------------------------------------------------
    # 13. Concurrency & Thread-Safety
    # -------------------------------------------------------------------------
    def test_concurrency_and_thread_safety(self):
        errors = []

        def worker(dev_id: str):
            try:
                for i in range(10):
                    res = self.engine.evaluate(f"Gago ka {i}!", device_id=dev_id)
                    self.assertIsInstance(res.score, float)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"PIN-{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")

    # -------------------------------------------------------------------------
    # 14. Sliding Window Expiration Pruning
    # -------------------------------------------------------------------------
    def test_sliding_window_pruning(self):
        engine_short = ContextEngine(escalation_window_seconds=1.0)
        t0 = time.time()
        engine_short.evaluate("Bobo ka!", device_id="DEV-PRUNE", timestamp=t0)
        engine_short.evaluate("Tanga mo!", device_id="DEV-PRUNE", timestamp=t0 + 0.1)

        # 2 statements within window -> harassment_count in history = 2
        tracker = engine_short.escalation_manager.get_tracker("DEV-PRUNE")
        self.assertEqual(len(tracker.history), 2)

        # Advance past window (t0 + 2.0s) -> expired statements pruned
        tracker.prune_expired(current_time=t0 + 2.0)
        self.assertEqual(len(tracker.history), 0)

    # -------------------------------------------------------------------------
    # 15. Uncertain Evidence Capping
    # -------------------------------------------------------------------------
    def test_uncertain_evidence_capping(self):
        # Even a lethal phrase is capped if evidence reliability is UNCERTAIN
        class MockUncertainResult:
            status = "UNCERTAIN_TRANSCRIPTION"

        res = self.engine.evaluate(
            "Papatayin kita.",
            device_id="DEV-UNC",
            transcription_result=MockUncertainResult()
        )
        self.assertLess(res.score, 8.0, "Uncertain evidence must NEVER reach DANGER (>=8.0) directly!")
        self.assertEqual(res.level, IncidentLevel.THREAT.value)
        self.assertTrue(res.human_review_required)


if __name__ == "__main__":
    unittest.main()

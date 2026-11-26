import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

import numpy as np


server_dir = str(Path(__file__).resolve().parents[1])
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

import server
from usb_audio_diagnostics import CAPTURE_LIMIT, USBAudioDiagnostics


class TestUSBAudioDiagnostics(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(TemporaryDirectory())
        self.root = Path(temporary) / "private-captures"
        self.pcm = np.repeat(np.array([6400, 640], dtype="<i2"), 6400).tobytes()
        self.decoder_inputs = []
        self.model = Mock(transcribe=self.decode)

    def decode(self, audio, **kwargs):
        self.decoder_inputs.append((audio.copy(), kwargs))
        segment = SimpleNamespace(
            text="short spoken reference", avg_logprob=-1.2,
            no_speech_prob=0.0, compression_ratio=1.0,
        )
        return iter([segment]), SimpleNamespace(language="tl")

    def pipeline(self, diagnostics):
        stack = ExitStack()
        stack.enter_context(patch.object(server, "usb_audio_diagnostics", diagnostics))
        stack.enter_context(patch.object(server.signal, "sosfilt", side_effect=lambda _, audio: audio))
        stack.enter_context(patch.object(server, "has_whisper", True))
        stack.enter_context(patch.object(server, "whisper_model", self.model))
        stack.enter_context(patch.object(server, "has_nsnet2", True))
        stack.enter_context(patch.object(
            server, "nsnet2_denoiser", Mock(enhance=lambda audio, **_: audio * np.float32(0.5))
        ))
        return stack

    def bundle_metadata(self):
        return [
            (path.parent, json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(self.root.glob("*/*/metrics.json"))
        ]

    def test_disabled_and_non_usb_processing_write_nothing(self):
        for enabled, source in ((False, "USB"), (True, "ESP32_DIRECT")):
            with self.subTest(enabled=enabled, source=source):
                diagnostics = USBAudioDiagnostics(self.root, enabled=enabled)
                with self.pipeline(diagnostics):
                    asyncio.run(server.handle_completed_audio("TEST", self.pcm, source=source))
                diagnostics.close()
                self.assertFalse(self.root.exists())
        self.assertEqual(len(self.decoder_inputs), 2)

    def test_usb_capture_pairs_exact_signals_and_preserves_result(self):
        diagnostics = USBAudioDiagnostics(self.root, enabled=True)
        self.addCleanup(diagnostics.close)
        second = np.repeat(np.array([8200, 820], dtype="<i2"), 6400).tobytes()
        with self.pipeline(diagnostics), patch(
            "usb_audio_diagnostics._speech_windows", return_value=[{"start": 0, "end": 6400}]
        ):
            for pcm in (self.pcm, second):
                baseline = server.process_audio_buffer(pcm)
                self.assertEqual(server._process_usb_audio_with_diagnostics(pcm), baseline)
            diagnostics.close()

        bundles = self.bundle_metadata()
        self.assertEqual([data["capture_id"] for _, data in bundles], ["01", "02"])
        for index, ((bundle, meta), pcm) in enumerate(zip(bundles, (self.pcm, second), strict=True)):
            with wave.open(str(bundle / "pin_pcm16.wav"), "rb") as pin:
                self.assertEqual((pin.getnchannels(), pin.getsampwidth(), pin.getframerate()), (1, 2, 16000))
                self.assertEqual(pin.readframes(pin.getnframes()), pcm)
            expected_pre_gain = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768 * np.float32(0.5)
            np.testing.assert_array_equal(np.load(bundle / "post_denoise_pre_gain.npy"), expected_pre_gain)
            baseline_input, baseline_options = self.decoder_inputs[index * 2]
            actual_input, actual_options = self.decoder_inputs[index * 2 + 1]
            np.testing.assert_array_equal(actual_input, baseline_input)
            self.assertEqual(actual_options, baseline_options)
            self.assertTrue(actual_options["vad_filter"])
            saved_input = np.load(bundle / "whisper_input.npy")
            self.assertEqual(saved_input.dtype, np.float32)
            np.testing.assert_array_equal(saved_input, actual_input)
            self.assertEqual(meta["speech_windows_samples"], [{"start": 0, "end": 6400}])
            for stage in meta["stages"].values():
                self.assertAlmostEqual(stage["duration_s"], 0.8)
                self.assertAlmostEqual(stage["speech_to_background_db"], 20)
                self.assertEqual(stage["clipping_or_limiting"]["count"], 0)

    def test_completed_usb_route_captures_short_utterances_and_enforces_limit(self):
        diagnostics = USBAudioDiagnostics(self.root, enabled=True)
        self.addCleanup(diagnostics.close)
        pcm = self.pcm[:3200]
        with self.pipeline(diagnostics), patch("usb_audio_diagnostics._speech_windows", return_value=[]):
            for _ in range(CAPTURE_LIMIT + 2):
                asyncio.run(server.handle_completed_audio("TEST", pcm, source="USB"))
            diagnostics.close()
        self.assertEqual(self.decoder_inputs, [])
        bundles = self.bundle_metadata()
        self.assertEqual(len(bundles), CAPTURE_LIMIT)
        for _, meta in bundles:
            self.assertIn("150 ms", meta["stages"]["whisper_input"]["unavailable"])
            self.assertIsNone(meta["stages"]["pin_pcm16"]["speech_to_background_db"])

    def test_worker_analysis_does_not_block_transcription(self):
        diagnostics = USBAudioDiagnostics(self.root, enabled=True)
        entered, release = Event(), Event()

        def paused_analysis(_):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test did not release diagnostic worker")
            return []

        try:
            with self.pipeline(diagnostics), patch("usb_audio_diagnostics._speech_windows", side_effect=paused_analysis):
                asyncio.run(server.handle_completed_audio("TEST", self.pcm, source="USB"))
                self.assertTrue(entered.wait(2))
                self.assertFalse(self.bundle_metadata())
                release.set()
                diagnostics.close()
        finally:
            release.set()
            diagnostics.close()
        self.assertEqual(len(self.bundle_metadata()), 1)

    def test_diagnostic_vad_failure_still_saves_signals(self):
        diagnostics = USBAudioDiagnostics(self.root, enabled=True)
        self.addCleanup(diagnostics.close)
        with self.pipeline(diagnostics), patch("usb_audio_diagnostics._speech_windows", side_effect=RuntimeError):
            self.assertEqual(server._process_usb_audio_with_diagnostics(self.pcm), server.process_audio_buffer(self.pcm))
            diagnostics.close()
        bundle, meta = self.bundle_metadata()[0]
        self.assertTrue((bundle / "whisper_input.npy").exists())
        self.assertEqual(meta["speech_window_error"], "diagnostic VAD failed")
        self.assertIsNone(meta["stages"]["whisper_input"]["speech_to_background_db"])

    def test_storage_failure_preserves_normal_processing(self):
        self.root.touch()
        diagnostics = USBAudioDiagnostics(self.root, enabled=True)
        self.addCleanup(diagnostics.close)
        with self.pipeline(diagnostics), self.assertLogs("securelink.usb_audio_diagnostics", level="WARNING"):
            baseline = server.process_audio_buffer(self.pcm)
            self.assertEqual(server._process_usb_audio_with_diagnostics(self.pcm), baseline)
            diagnostics.close()
        self.assertTrue(self.root.is_file())

    def test_limit_counts_and_unequal_stage_lengths(self):
        diagnostics = USBAudioDiagnostics(self.root, enabled=True)
        self.addCleanup(diagnostics.close)
        raw = np.resize(np.array([-32768, 32767, 0], dtype="<i2"), 16000).tobytes()
        capture = diagnostics.begin(raw)
        pre_gain = np.zeros(15999, dtype=np.float32)
        pre_gain[:4] = [-1.1, 1.2, 0.5, 0.99]
        capture.snapshot("post_denoise_pre_gain", pre_gain)
        capture.snapshot("whisper_input", np.clip(pre_gain, -0.99, 0.99))
        with patch("usb_audio_diagnostics._speech_windows", return_value=[{"start": 0, "end": 8000}]):
            diagnostics.submit(capture)
            diagnostics.close()
        _, meta = self.bundle_metadata()[0]
        stages = meta["stages"]
        self.assertEqual(stages["pin_pcm16"]["clipping_or_limiting"]["count"], 10667)
        self.assertEqual(stages["post_denoise_pre_gain"]["clipping_or_limiting"]["count"], 2)
        self.assertEqual(stages["whisper_input"]["clipping_or_limiting"]["count"], 2)
        self.assertIsNone(stages["whisper_input"]["speech_active_rms_full_scale"])
        self.assertIn("sample count differs", stages["whisper_input"]["estimate_unavailable_reason"])

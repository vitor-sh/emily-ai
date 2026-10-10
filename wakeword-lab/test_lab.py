import copy
import json
from pathlib import Path
import tempfile
import unittest

from lab import audit, read_config, training_config, sha256, summarize_scores
from run_upstream import ambient_guard
from colab_setup import run


class DataProtectionTests(unittest.TestCase):
    def test_calibration_covers_saturated_scores_above_point_95(self):
        scores = [dict(split=s, positive=p, score=.996 if p else .99)
                  for s in ('validation', 'testing') for p in (True, False)]
        report = summarize_scores(scores)
        self.assertEqual(report['validation']['recall'], 1.)
        self.assertEqual(report['validation']['false_positive_rate'], 0.)
        self.assertGreater(report['validation']['threshold'], .99)

    def test_resume_rejects_changed_settings_and_corrupted_audio(self):
        from diversity import read_progress
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            audio = work / 'sample.wav'
            audio.write_bytes(b'original')
            path = work / 'progress.json'
            path.write_text(json.dumps(dict(signature='expected', completed=['voice'],
                records=[dict(path='sample.wav', sha256=sha256(audio))])))
            self.assertEqual(read_progress(path, 'expected', work)['completed'], ['voice'])
            with self.assertRaisesRegex(ValueError, 'parâmetros'):
                read_progress(path, 'changed', work)
            audio.write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, 'alterado'):
                read_progress(path, 'expected', work)

    def test_cuda_failure_falls_back_to_cpu_without_claiming_gpu(self):
        from unittest.mock import Mock, patch
        from diversity import kokoro_session
        ort = Mock()
        ort.get_available_providers.return_value = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        cpu = Mock()
        ort.InferenceSession.side_effect = [RuntimeError('missing CUDA library'), cpu]
        assets = dict(release='https://example.invalid/', files={
            'kokoro-v1.0.fp16-gpu.onnx': 'gpu', 'kokoro-v1.0.int8.onnx': 'cpu'})
        with patch('diversity.checked_asset'):
            session, digest = kokoro_session(ort, assets, Path('/test'), None)
        self.assertIs(session, cpu)
        self.assertEqual(digest, 'cpu')
        self.assertEqual(ort.InferenceSession.call_args.kwargs['providers'], ['CPUExecutionProvider'])

    def test_allowed_false_positive_rate_does_not_force_rejection_of_all_calls(self):
        scores = []
        for split in ('validation', 'testing'):
            scores.extend(dict(split=split, positive=True, score=.8) for _ in range(10))
            scores.extend(dict(split=split, positive=False, score=.1) for _ in range(199))
            scores.append(dict(split=split, positive=False, score=.8))
        report = summarize_scores(scores)
        self.assertEqual(report['validation']['recall'], 1.)
        self.assertEqual(report['validation']['false_positive_rate'], .005)

    def test_augmentation_preserves_whole_call_and_balances_duration(self):
        try:
            import numpy as np
            from diversity import augment
        except ImportError:
            self.skipTest('Teste de áudio exige o ambiente de treinamento.')
        call = np.sin(np.arange(16000) * .1) * .3
        for seed in range(10):
            positive = augment(call, np.random.default_rng(seed), True)
            negative = augment(call, np.random.default_rng(seed), False)
            self.assertEqual(positive.dtype, np.int16)
            self.assertEqual(len(positive), 52800)
            np.testing.assert_array_equal(positive, negative)
            # Too-long calls fail rather than silently training on a cut-off name.
        with self.assertRaisesRegex(ValueError, 'longa'):
            augment(np.ones(48000), np.random.default_rng(1), True)

    def test_diverse_sources_include_native_and_female_heldout_profiles(self):
        config = read_config()
        self.assertGreaterEqual(len(config['voices']), 30)
        for split in ('training', 'validation', 'testing'):
            rows = [v for v in config['voices'] if v['split'] == split]
            self.assertTrue(any(v['native_pt'] for v in rows))
            self.assertTrue(any(v.get('style', '').startswith(('af_', 'bf_', 'pf_')) for v in rows))
        # Avoid known same-name language adaptations and the blended heart profile.
        self.assertFalse(any(v.get('style') in ('ef_dora', 'em_alex', 'em_santa', 'af_heart') for v in config['voices']))

    def test_source_hash_mismatch_is_rejected(self):
        from diversity import checked_asset
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'model.onnx'
            path.write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError, 'Hash'):
                checked_asset('https://example.invalid/not-used', path, '0' * 64)

    def test_diagnostics_export_only_known_model_files(self):
        from build_notebook import diagnostic_files
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            trained = work / 'trained'
            trained.mkdir()
            for name in ('best_weights.weights.h5', 'private.wav', 'secret.json'):
                (trained / name).write_bytes(b'test')
            self.assertEqual(diagnostic_files(work), [trained / 'best_weights.weights.h5'])

    def test_rejecting_every_call_is_a_failed_model(self):
        scores = [dict(split=s, positive=p, score=.54) for s in ("validation", "testing") for p in (True, False)]
        report = summarize_scores(scores)
        self.assertEqual(report["status"], "rejected_synthetic_evaluation")
        self.assertEqual(report["diagnostics"]["testing"]["rank_auc"], .5)

    def test_test_speaker_cannot_change_selected_threshold(self):
        scores = [dict(split=s, positive=p, score=.8 if p else .1)
                  for s in ("validation", "testing") for p in (True, False)]
        threshold = summarize_scores(scores)["validation"]["threshold"]
        scores[-2]["score"] = .3
        self.assertEqual(summarize_scores(scores)["validation"]["threshold"], threshold)
        self.assertEqual(summarize_scores(scores)["testing"]["recall"], 0)

    def test_invalid_scores_cannot_pass_evaluation(self):
        with self.assertRaises(ValueError):
            summarize_scores([dict(split="validation", positive=True, score=float("nan"))])
    def rows(self):
        return [dict(voice=split, split=split, seconds=2., positive=positive)
                for split in ("training", "validation", "testing") for positive in (True, False)]

    def test_distinct_speakers(self):
        audit(self.rows())
        rows = self.rows()
        rows[-1]["voice"] = "training"
        with self.assertRaisesRegex(ValueError, "Vazamento"):
            audit(rows)

    def test_missing_negatives_cannot_be_validated(self):
        with self.assertRaises(ValueError):
            audit([r for r in self.rows() if r["positive"]])

    def test_unreviewed_license_is_rejected(self):
        config = read_config()
        config["voices"][0]["dataset_license"] = "CC-BY-NC-4.0"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError): read_config(path)

    def test_duplicate_speaker_rejected(self):
        config = read_config()
        config["voices"].append(copy.deepcopy(config["voices"][0]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError): read_config(path)

    def test_training_does_not_depend_on_absent_ambient_metric(self):
        config = training_config(Path("/experiment"), 20)
        self.assertEqual(config["maximization_metric"], "recall")
        self.assertEqual(config["minimization_metric"], "loss")
        self.assertEqual(config["eval_step_interval"], 20)
        self.assertNotIn("private", json.dumps(config))

    def test_quantization_calibration_has_whole_streaming_chunks(self):
        config = training_config(Path("/experiment"), 20)
        output_frames = 1 + (config["clip_duration_ms"] - 30) // 30
        dropped = 4 + (4 + 10 + 14 + 22) * 3
        self.assertEqual((output_frames + dropped) % 3, 0)

    def test_no_ambient_data_is_not_reported_as_zero_false_accepts(self):
        from unittest.mock import Mock
        original = Mock(return_value="measured")
        processor = Mock()
        processor.get_mode_size.return_value = 0
        self.assertIsNone(ambient_guard(original)({}, "folder", processor))
        original.assert_not_called()
        processor.get_mode_size.return_value = 2
        self.assertEqual(ambient_guard(original)({}, "folder", processor), "measured")

    def test_audio_hash_changes_after_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.wav"
            path.write_bytes(b"before")
            before = sha256(path)
            path.write_bytes(b"after")
            self.assertNotEqual(before, sha256(path))

    def test_setup_error_preserves_real_stderr(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "TEST_INSTALL_ERROR"):
                run([sys.executable, "-c", "import sys; print('TEST_INSTALL_ERROR', file=sys.stderr); sys.exit(7)"],
                    Path(directory), "Testar diagnóstico")
            self.assertIn("TEST_INSTALL_ERROR", (Path(directory) / "setup.log").read_text())


if __name__ == "__main__": unittest.main()

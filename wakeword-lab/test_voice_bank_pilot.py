import os
import sys
from pathlib import Path
import tempfile
import unittest
import numpy as np
from scipy.io import wavfile
from setup_voice_bank import run, generator_environment
from voice_bank_pilot import profiles,transcript_flags,audio_checks,pcm16,read_progress,digest,write_json

class VoiceBankChecks(unittest.TestCase):
    def test_count_is_not_inflated_by_repeated_descriptions(self):
        rows=profiles(216)
        self.assertEqual(len({r['id'] for r in rows}),216)
        self.assertEqual(len({r['instruction'] for r in rows}),216)
        self.assertEqual(len({r['requested_region'] for r in profiles(12)}),6)
    def test_name_alone_and_missing_prefix_not_approved(self):
        for text in ['Emily','E Emily','Ei','Emily Ei','Ei Emily abre o YouTube']:
            self.assertTrue(transcript_flags(text,True))
        self.assertFalse(transcript_flags('Ei, Êmili!',True))
        self.assertTrue(transcript_flags('Eu falei ei Emily ontem',False))
    def test_invalid_generation_cannot_enter_bank(self):
        for audio in [np.zeros(16000),np.full(16000,np.nan),np.ones((2,16000))]:
            with self.assertRaises(ValueError):audio_checks(audio,16000)
        audio=np.sin(np.arange(3*16000)*.1)*.5
        self.assertIn('call_longer_than_v2_training_budget',audio_checks(audio,16000,True)['flags'])
    def test_preserve_low_volume_pcm_and_resample_duration(self):
        audio=np.sin(np.arange(24000)*.1)*.01
        pcm=pcm16(audio,24000)
        self.assertEqual(pcm.dtype,np.int16)
        self.assertEqual(len(pcm),16000)
        self.assertLess(int(np.abs(pcm).max()),500)
        self.assertGreater(int(np.abs(pcm).max()),200)
    def test_short_call_with_long_silent_tail_is_flagged_without_trimming(self):
        speech=np.sin(np.arange(16000)*.1)*.05
        audio=np.concatenate([np.zeros(3200),speech,np.zeros(13*16000)])
        original=audio.copy()
        checks=audio_checks(audio,16000,True)
        self.assertIn('short_call_unexpected_file_duration',checks['flags'])
        self.assertIn('excessive_trailing_silence',checks['flags'])
        self.assertAlmostEqual(checks['leading_seconds'],.2,places=2)
        self.assertAlmostEqual(checks['trailing_seconds'],13,places=2)
        np.testing.assert_array_equal(audio,original)
    def test_driver_paths_preserved_and_training_libs_removed(self):
        original = {'LD_LIBRARY_PATH':'/usr/lib64-nvidia:/content/emily-wakeword/.training-venv/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/cuda/lib64/stubs',
                    'CUDA_VISIBLE_DEVICES':'0'}
        env = generator_environment(original)
        self.assertIn('/usr/lib64-nvidia',env['LD_LIBRARY_PATH'].split(':'))
        self.assertNotIn('.training-venv/',env['LD_LIBRARY_PATH'])
        self.assertNotIn('/stubs',env['LD_LIBRARY_PATH'])
        self.assertEqual(env['CUDA_VISIBLE_DEVICES'],'0')
        self.assertIn('.training-venv/',original['LD_LIBRARY_PATH'])

    def test_setup_failure_reports_real_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with self.assertRaisesRegex(RuntimeError,'EXPECTED_SETUP_FAILURE'):
                run([sys.executable,'-c',"print('EXPECTED_SETUP_FAILURE'); raise SystemExit(7)"],root,os.environ.copy())
            self.assertIn('EXPECTED_SETUP_FAILURE',(root/'setup.log').read_text())

    def test_resume_rejects_modified_audio_and_changed_bank(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            state=read_progress(root,12)
            wavfile.write(root/'a.wav',16000,np.ones(16000,np.int16))
            state['records'].append(dict(path='a.wav',sha256=digest(root/'a.wav')))
            write_json(root/'progress.json',state)
            self.assertEqual(len(read_progress(root,12)['records']),1)
            with self.assertRaises(ValueError):read_progress(root,13)
            (root/'a.wav').write_bytes(b'changed')
            with self.assertRaises(ValueError):read_progress(root,12)

if __name__=='__main__':unittest.main()

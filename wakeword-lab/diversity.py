"""Licensed synthetic diversity; styles are not claimed to be real speakers."""
import json
import math
import hashlib
from pathlib import Path


def read_progress(path, signature, work):
    from lab import sha256
    progress = json.loads(path.read_text()) if path.exists() else dict(signature=signature, completed=[], records=[])
    if progress['signature'] != signature:
        raise ValueError('Geração interrompida com parâmetros diferentes; use uma pasta nova.')
    for row in progress['records']:
        relative = Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Caminho inválido no progresso de geração.')
        if sha256(work / relative) != row['sha256']:
            raise ValueError('Áudio do progresso foi alterado; use uma pasta nova.')
    return progress


def checked_asset(url, path, digest):
    from lab import fetch, sha256
    fetch(url, path)
    if sha256(path) != digest:
        raise ValueError(f'Hash de origem inesperado: {path.name}')


def kokoro_session(ort, assets, asset_dir, options):
    """Prefer CUDA float16; keep an explicitly tested int8 CPU fallback."""
    if 'CUDAExecutionProvider' in ort.get_available_providers():
        name = 'kokoro-v1.0.fp16-gpu.onnx'
        checked_asset(assets['release'] + name, asset_dir / name, assets['files'][name])
        try:
            session = ort.InferenceSession(str(asset_dir / name), sess_options=options,
                                           providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
            if 'CUDAExecutionProvider' in session.get_providers():
                print('Kokoro: CUDA float16 (GPU).', flush=True)
                return session, assets['files'][name]
        except Exception as error:
            print(f'Kokoro CUDA indisponível: {type(error).__name__}; usando CPU.', flush=True)
    name = 'kokoro-v1.0.int8.onnx'
    checked_asset(assets['release'] + name, asset_dir / name, assets['files'][name])
    print('Kokoro: int8 CPU; geração pode demorar mais.', flush=True)
    return ort.InferenceSession(str(asset_dir / name), sess_options=options,
                                providers=['CPUExecutionProvider']), assets['files'][name]


def augment(audio, rng, positive):
    """Keep the entire call inside the final training window, with real context."""
    import numpy as np
    from scipy.signal import resample_poly, lfilter
    # Time/rate perturbation creates variants, never new speaker identities.
    minimum_speed = max(90, math.ceil(len(audio) / (2.0 * 16000) * 100)) if positive else 90
    if minimum_speed > 110:
        raise ValueError('Chamada sintetizada longa demais para o campo receptivo; revisar pronúncia.')
    speed = int(rng.integers(minimum_speed, 111))
    audio = resample_poly(audio, 100, speed)
    if positive and len(audio) > int(2.0 * 16000):
        raise ValueError('Chamada sintetizada longa demais para o campo receptivo; revisar pronúncia.')
    # Random bandwidth and weak reverberation. No hard clipping of the call.
    if rng.random() < .35:
        audio = lfilter([.3], [1, -.7], audio)
    if rng.random() < .4:
        delay = int(rng.uniform(.02, .09) * 16000)
        echo = np.pad(audio, (delay, 0))[:len(audio)]
        audio = audio + float(rng.uniform(.05, .2)) * echo
    audio = audio * 10 ** (float(rng.uniform(-22, -2)) / 20)
    tail = int(rng.uniform(.06, .15) * 16000)
    # Equal minimum duration in both classes; do not let silence length label them.
    lead = max(int(.6 * 16000), int(3.3 * 16000) - len(audio) - tail)
    audio = np.pad(audio, (lead, tail))
    noise = rng.normal(0, float(rng.uniform(.00003, .003)), audio.shape)
    if rng.random() < .5:
        noise = lfilter([.15], [1, -.85], noise)
    return np.clip((audio + noise) * 32768, -32768, 32767).astype(np.int16)


def generate(work, repetitions, smoke=False):
    import numpy as np
    import onnxruntime as ort
    from scipy.io import wavfile
    from scipy.signal import resample_poly
    from lab import read_config, fetch, sha256, audit
    from piper import PiperVoice, SynthesisConfig
    from piper.config import PiperConfig
    from piper.phonemize_espeak import ESPEAK_DATA_DIR
    from kokoro_onnx import Kokoro

    config = read_config()
    if smoke:
        config['negative_phrases'] = ['Emily.', 'Ei, Emília.', 'Eu estava falando com a Emily.']
    work.mkdir(parents=True, exist_ok=True)
    manifest = work / 'samples.jsonl'
    if manifest.exists():
        raise ValueError('Use uma pasta nova para não misturar experimentos.')
    settings = dict(config=config, repetitions=repetitions, generator_sha256=sha256(Path(__file__)))
    signature = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    progress_path = work / 'generation-progress.json'
    progress = read_progress(progress_path, signature, work)
    assets = config['kokoro_assets']
    asset_dir = work / 'kokoro'
    name = 'voices-v1.0.bin'
    checked_asset(assets['release'] + name, asset_dir / name, assets['files'][name])
    card_base = 'https://huggingface.co/hexgrad/Kokoro-82M/resolve/' + assets['model_card_revision']
    for name in ('README.md', 'VOICES.md'):
        fetch(card_base + '/' + name, asset_dir / name)
    config['source_card_hashes'] = {name: sha256(asset_dir / name) for name in ('README.md', 'VOICES.md')}
    config['evaluation_note'] = 'Foreign Kokoro styles use pt-br phonemes; not native PT speakers. No voice blending.'
    (work / 'resolved_sources.json').write_text(json.dumps(config, indent=2, ensure_ascii=False))
    records = progress['records']
    kokoro = None
    def options():
        op = ort.SessionOptions()
        op.intra_op_num_threads = 1
        op.inter_op_num_threads = 1
        return op
    for spec in config['voices']:
        voice_id = spec['id']
        if voice_id in progress['completed']:
            print('Perfil já concluído:', voice_id, flush=True)
            continue
        # Voice-local seeds make resumed generation independent of skipped voices.
        seed = int.from_bytes(hashlib.sha256(('20261005:' + voice_id).encode()).digest()[:8], 'little')
        rng = np.random.default_rng(seed)
        backend = spec['backend']
        if backend == 'piper':
            voice_dir = work / 'voices' / voice_id
            base = f"https://huggingface.co/rhasspy/piper-voices/resolve/{config['voices_revision']}/{spec['path']}/"
            for name in (voice_id + '.onnx', voice_id + '.onnx.json', 'MODEL_CARD'):
                fetch(base + name, voice_dir / name)
            path = voice_dir / (voice_id + '.onnx')
            piper = PiperVoice(config=PiperConfig.from_dict(json.loads(Path(str(path) + '.json').read_text())),
                               session=ort.InferenceSession(str(path), sess_options=options(), providers=['CPUExecutionProvider']),
                               espeak_data_dir=ESPEAK_DATA_DIR, download_dir=voice_dir)
            model_hash = sha256(path)
            def synth(text, speed):
                chunks = list(piper.synthesize(text, SynthesisConfig(length_scale=1 / speed)))
                return np.concatenate([c.audio_float_array for c in chunks]), chunks[0].sample_rate
        else:
            if kokoro is None:
                session, kokoro_hash = kokoro_session(ort, assets, asset_dir, options())
                kokoro = Kokoro.from_session(session, str(asset_dir / 'voices-v1.0.bin'))
            model_hash = kokoro_hash
            def synth(text, speed):
                return kokoro.create(text, voice=spec['style'], speed=speed, lang='pt-br')
        print('Gerando perfil:', voice_id, spec['split'], flush=True)
        # Native training voices get more examples; held-out voices stay affordable.
        count = repetitions if spec['split'] == 'training' else min(repetitions, 24)
        if spec['split'] == 'training' and spec['native_pt']:
            count *= 2
        for positive, phrases in ((True, config['positive_phrases']), (False, config['negative_phrases'])):
            for index, phrase in enumerate(phrases):
                if index % 8 == 0:
                    print('  Chamadas' if positive else '  Negativos', index + 1, '/', len(phrases), flush=True)
                n = count if positive else max(1, count // 6)
                bases = []
                # Cache up to three different syntheses; waveform augmentation is cheap.
                for speed in (1., 1.12, .95)[:min(3, n)]:
                    raw, rate = synth(phrase, speed)
                    if not np.isfinite(raw).all() or len(raw) < rate * .1 or np.max(np.abs(raw)) < .001:
                        raise ValueError(f'Síntese vazia/inválida: {voice_id}, {phrase}')
                    divisor = math.gcd(rate, 16000)
                    bases.append(resample_poly(raw, 16000 // divisor, rate // divisor))
                for variant in range(n):
                    audio = augment(bases[variant % len(bases)], rng, positive)
                    relative = Path('audio') / spec['split'] / f'{voice_id}-{int(positive)}-{index}-{variant}.wav'
                    dest = work / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    wavfile.write(dest, 16000, audio)
                    records.append(dict(path=str(relative), voice=voice_id, split=spec['split'], positive=positive,
                                        text=phrase, native_pt=spec['native_pt'], backend=backend,
                                        seconds=len(audio) / 16000, sha256=sha256(dest),
                                        model_sha256=model_hash, license=spec['dataset_license']))
        # Dedicated silence/colored-noise negatives, also included in evaluation.
        for index in range(max(2, count // 2)):
            size = int((3.3 if index % 2 else 8.) * 16000)
            level = (0., .0001, .002, .01)[index % 4]
            audio = np.clip(rng.normal(0, level, size) * 32768, -32768, 32767).astype(np.int16)
            relative = Path('audio') / spec['split'] / f'{voice_id}-background-{index}.wav'
            dest = work / relative
            wavfile.write(dest, 16000, audio)
            records.append(dict(path=str(relative), voice=voice_id, split=spec['split'], positive=False,
                                text='[synthetic silence/noise]', seconds=size / 16000,
                                sha256=sha256(dest), model_sha256=model_hash, license=spec['dataset_license']))
        if backend == 'piper':
            del piper
        progress['completed'].append(voice_id)
        progress['records'] = records
        temporary = progress_path.with_suffix('.part')
        temporary.write_text(json.dumps(progress, ensure_ascii=False))
        temporary.replace(progress_path)
    audit(records)
    manifest.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records))
    print(f'{len(records)} amostras, {len(config["voices"])} perfis. Ainda é avaliação sintética.', flush=True)

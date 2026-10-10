"""Isolated PT-BR microWakeWord experiment. Never installs a model in Emily."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
SPLITS = ("training", "validation", "testing")


def read_config(path=ROOT / "voices.json"):
    config = json.loads(Path(path).read_text())
    ids = [v["id"] for v in config["voices"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Uma voz não pode aparecer em mais de uma divisão.")
    if set(v["split"] for v in config["voices"]) != set(SPLITS):
        raise ValueError("Precisamos de vozes separadas para treino, validação e teste.")
    for voice in config["voices"]:
        if voice["dataset_license"] not in ("CC0", "CC-BY-4.0", "Apache-2.0"):
            raise ValueError("Fonte ainda não revisada para redistribuição.")
        if voice.get("backend", "piper") not in ("piper", "kokoro"):
            raise ValueError("Sintetizador não revisado.")
        if voice.get("backend") == "kokoro" and voice["dataset_license"] != "Apache-2.0":
            raise ValueError("Licença Kokoro inesperada.")
    return config


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url, path):
    path = Path(path)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as file:
            while block := response.read(1024 * 1024):
                file.write(block)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def generate(work, repetitions, smoke=False):
    if read_config().get('schema_version') == 2:
        from diversity import generate as generate_diverse
        return generate_diverse(work, repetitions, smoke=smoke)
    # Load one ONNX voice at a time: do not retain four models in RAM.
    import numpy as np
    from piper import PiperVoice, SynthesisConfig
    from piper.config import PiperConfig
    from piper.phonemize_espeak import ESPEAK_DATA_DIR
    import onnxruntime
    from scipy.io import wavfile
    from scipy.signal import resample_poly

    config = read_config()
    work.mkdir(parents=True, exist_ok=True)
    manifest_path = work / "samples.jsonl"
    if manifest_path.exists():
        raise ValueError("Use uma pasta nova para não misturar experimentos.")
    rng = np.random.default_rng(20261004)
    revision = config["voices_revision"]
    if revision == "main":
        # Resolve mutable branch once, then download every model/card at this commit.
        with urllib.request.urlopen("https://huggingface.co/api/models/rhasspy/piper-voices", timeout=60) as response:
            revision = json.load(response)["sha"]
    config["voices_revision"] = revision
    (work / "resolved_sources.json").write_text(json.dumps(config, indent=2, ensure_ascii=False))
    records = []
    for voice_spec in config["voices"]:
        voice_dir = work / "voices" / voice_spec["id"]
        base = f"https://huggingface.co/rhasspy/piper-voices/resolve/{revision}/" + voice_spec["path"]
        for filename in (voice_spec["id"] + ".onnx", voice_spec["id"] + ".onnx.json", "MODEL_CARD"):
            fetch(base + "/" + urllib.parse.quote(filename), voice_dir / filename)
        model = voice_dir / (voice_spec["id"] + ".onnx")
        model_hash = sha256(model)
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        voice = PiperVoice(config=PiperConfig.from_dict(json.loads(Path(str(model) + ".json").read_text())),
                           session=onnxruntime.InferenceSession(str(model), sess_options=options,
                                                              providers=["CPUExecutionProvider"]),
                           espeak_data_dir=ESPEAK_DATA_DIR, download_dir=voice_dir)
        print("Gerando:", voice_spec["id"], voice_spec["split"], flush=True)
        groups = ((True, config["positive_phrases"]), (False, config["negative_phrases"]))
        for positive, phrases in groups:
            for phrase_index, phrase in enumerate(phrases):
                count = repetitions if positive else max(1, repetitions // 3)
                for variant in range(count):
                    syn = SynthesisConfig(length_scale=float(rng.uniform(.8, 1.25)),
                                          noise_scale=float(rng.uniform(.5, .8)),
                                          noise_w_scale=float(rng.uniform(.6, 1.0)))
                    chunks = list(voice.synthesize(phrase, syn))
                    audio = np.concatenate([c.audio_float_array for c in chunks])
                    rate = chunks[0].sample_rate
                    divisor = math.gcd(rate, 16000)
                    audio = resample_poly(audio, 16000 // divisor, rate // divisor)
                    # Preserve the complete call; add context for PCAN stabilization.
                    # No arbitrary tail truncation which could train on a command instead.
                    audio *= 10 ** (float(rng.uniform(-18, -1)) / 20)
                    audio = np.pad(audio, (int(rng.uniform(.5, 1.1) * 16000), 3200))
                    audio += rng.normal(0, float(rng.uniform(.0001, .002)), audio.shape)
                    relative = Path("audio") / voice_spec["split"] / (
                        f"{voice_spec['id']}-{int(positive)}-{phrase_index}-{variant}.wav")
                    destination = work / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    wavfile.write(destination, 16000, np.clip(audio * 32768, -32768, 32767).astype(np.int16))
                    records.append(dict(path=str(relative), voice=voice_spec["id"],
                                        split=voice_spec["split"], positive=positive, text=phrase,
                                        seconds=len(audio) / 16000, sha256=sha256(destination),
                                        model_sha256=model_hash,
                                        license=voice_spec["dataset_license"]))
        del voice
    manifest_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    audit(records)
    print(f"Gerados {len(records)} exemplos. Apenas dados sintéticos; não é validação real.")


def audit(records):
    if not records:
        raise ValueError("Manifesto vazio.")
    voices = {}
    for row in records:
        if row["split"] not in SPLITS or row["seconds"] <= 0:
            raise ValueError("Amostra inválida.")
        previous = voices.setdefault(row["voice"], row["split"])
        if previous != row["split"]:
            raise ValueError("Vazamento de voz entre treino e teste.")
    for split in SPLITS:
        if {r["positive"] for r in records if r["split"] == split} != {True, False}:
            raise ValueError(f"Faltam positivos ou negativos em {split}.")


def features(work):
    import numpy as np
    from scipy.io import wavfile
    from mmap_ninja.ragged import RaggedMmap
    from microwakeword.audio.audio_utils import generate_features_for_clip

    records = [json.loads(line) for line in (work / "samples.jsonl").read_text().splitlines()]
    audit(records)
    for positive in (True, False):
        for split in SPLITS:
            rows = [r for r in records if r["positive"] == positive and r["split"] == split]
            out = work / "features" / str(int(positive)) / split / "samples_mmap"
            if out.exists():
                raise ValueError("Características já existem; use outra pasta.")
            def iterator():
                for row in rows:
                    path = work / row["path"]
                    if sha256(path) != row["sha256"]:
                        raise ValueError("Áudio alterado depois da geração.")
                    rate, audio = wavfile.read(path)
                    if rate != 16000 or audio.ndim != 1 or audio.dtype != np.int16:
                        raise ValueError("Esperado WAV mono PCM16 de 16 kHz.")
                    # Reference TF microfrontend, uint16 retained: upstream scales by 0.0390625.
                    yield generate_features_for_clip(audio, step_ms=10, use_c=False)
            out.parent.mkdir(parents=True, exist_ok=True)
            RaggedMmap.from_generator(out_dir=str(out), sample_generator=iterator(), batch_size=8, verbose=False)
    print("Características do microfrontend prontas.")


def training_config(work, steps):
    return dict(window_step_ms=10, train_dir=str(work / "trained"),
                features=[dict(features_dir=str(work / "features" / str(int(positive))),
                               sampling_weight=1., penalty_weight=1., truth=positive,
                               truncation_strategy="truncate_start" if positive else "random", type="mmap")
                          for positive in (True, False)],
                training_steps=[steps], positive_class_weight=[1], negative_class_weight=[2],
                learning_rates=[.0003], batch_size=16, time_mask_max_size=[5], time_mask_count=[1],
                freq_mask_max_size=[3], freq_mask_count=[1], eval_step_interval=min(steps, 250),
                clip_duration_ms=2040, target_minimization=.15, minimization_metric="loss",
                # No ambient corpus yet: average_viable_recall would always be zero.
                # Pinned upstream does not actually return the documented false_positive_rate metric.
                maximization_metric="recall")


def train(work, steps):
    import yaml
    config = training_config(work, steps)
    signature = dict(clip_duration_ms=config["clip_duration_ms"], stride=3,
                     upstream_commit=read_config()["upstream_commit"],
                     training_settings=config,
                     samples_sha256=sha256(work / "samples.jsonl"))
    signature_path = work / "checkpoint-settings.json"
    if (work / "trained").exists():
        if not signature_path.exists() or json.loads(signature_path.read_text()) != signature:
            raise ValueError("Checkpoint incompatível com este experimento; use uma pasta nova.")
    signature_path.write_text(json.dumps(signature, indent=2))
    path = work / "training.yaml"
    path.write_text(yaml.safe_dump(config))
    command = [sys.executable, str(ROOT / "run_upstream.py"),
               "--training_config", str(path), "--train", "1", "--restore_checkpoint", "1",
               "--test_tf_nonstreaming", "0", "--test_tflite_nonstreaming", "0",
               "--test_tflite_nonstreaming_quantized", "0", "--test_tflite_streaming", "0",
               "--test_tflite_streaming_quantized", "1", "--use_weights", "best_weights",
               "mixednet", "--pointwise_filters", "32,32,32,32", "--repeat_in_block", "1,1,1,1",
               "--mixconv_kernel_sizes", "[5],[7,11],[9,15],[23]",
               "--residual_connection", "0,0,0,0", "--first_conv_filters", "16",
               "--first_conv_kernel_size", "5", "--stride", "3"]
    subprocess.run(command, check=True)


def quantize(values, details):
    import numpy as np
    scale, zero = details["quantization"]
    if not scale:
        raise ValueError("Tensor sem escala de quantização.")
    bounds = np.iinfo(details["dtype"])
    return np.clip(np.rint(values / scale + zero), bounds.min, bounds.max).astype(details["dtype"])


def score_clip(model_path, audio):
    import numpy as np
    from ai_edge_litert.interpreter import Interpreter
    from microwakeword.audio.audio_utils import generate_features_for_clip

    # Fresh interpreter per file: streaming state must never leak between speakers.
    model = Interpreter(model_path=str(model_path), num_threads=1)
    model.allocate_tensors()
    input_tensor = model.get_input_details()[0]
    output_tensor = model.get_output_details()[0]
    features = generate_features_for_clip(audio, step_ms=10, use_c=False).astype(np.float32) * .0390625
    stride = int(input_tensor["shape"][1])
    probabilities = []
    for start in range(0, len(features) - stride + 1, stride):
        chunk = features[start:start + stride].reshape(input_tensor["shape"])
        if np.issubdtype(input_tensor["dtype"], np.integer):
            chunk = quantize(chunk, input_tensor)
        model.set_tensor(input_tensor["index"], chunk)
        model.invoke()
        value = float(model.get_tensor(output_tensor["index"]).reshape(-1)[0])
        if np.issubdtype(output_tensor["dtype"], np.integer):
            scale, zero = output_tensor["quantization"]
            value = (value - zero) * scale
        probabilities.append(value)
    # Five streaming outputs = 150 ms with this model's 30 ms stride.
    if len(probabilities) < 5:
        return 0.
    return float(np.max(np.convolve(probabilities, np.ones(5) / 5, mode="valid")))


def summarize_scores(scores):
    """Choose by validation only; rejecting all calls is a failed candidate."""
    from bisect import bisect_left, bisect_right
    for row in scores:
        if not math.isfinite(row["score"]) or not 0 <= row["score"] <= 1:
            raise ValueError("Pontuação inválida na avaliação.")
    def metrics(split, threshold):
        positives = [r for r in scores if r["split"] == split and r["positive"]]
        negatives = [r for r in scores if r["split"] == split and not r["positive"]]
        if not positives or not negatives:
            raise ValueError(f"Faltam classes na avaliação: {split}")
        return dict(threshold=threshold, recall=sum(r["score"] >= threshold for r in positives) / len(positives),
                    false_positive_rate=sum(r["score"] >= threshold for r in negatives) / len(negatives),
                    positive_count=len(positives), negative_count=len(negatives))
    # Evaluate actual validation boundaries, including saturated scores above .95.
    # A coarse .05 grid can incorrectly reject a separable quantized model.
    values = {r['score'] for r in scores if r['split'] == 'validation'}
    thresholds = {0., 1.} | values | {math.nextafter(value, 1.) for value in values}
    candidates = [metrics('validation', threshold) for threshold in sorted(thresholds)]
    viable = [r for r in candidates if r["false_positive_rate"] <= .01]
    # Within the permitted FPR, maximize recall rather than preferring rejection of all calls.
    chosen = (min(viable, key=lambda r: (-r['recall'], r['false_positive_rate'], -r['threshold']))
              if viable else min(candidates, key=lambda r: (r['false_positive_rate'], -r['recall'], -r['threshold'])))
    testing = metrics("testing", chosen["threshold"])
    diagnostics = {}
    for split in ("validation", "testing"):
        positive = sorted(r["score"] for r in scores if r["split"] == split and r["positive"])
        negative = sorted(r["score"] for r in scores if r["split"] == split and not r["positive"])
        # Rank AUC, with ties counted as 0.5; independent of threshold selection.
        auc = sum(bisect_left(negative, p) + .5 * (bisect_right(negative, p) - bisect_left(negative, p))
                  for p in positive) / (len(positive) * len(negative))
        diagnostics[split] = dict(rank_auc=auc,
                                 positive_range=[positive[0], positive[-1]],
                                 negative_range=[negative[0], negative[-1]])
    rejected = chosen["recall"] == 0 or testing["recall"] == 0 or chosen["false_positive_rate"] > .01
    return dict(status="rejected_synthetic_evaluation" if rejected else "experimental_not_for_installation",
                evidence="synthetic_only", validation=chosen, testing=testing,
                diagnostics=diagnostics, scores=scores,
                reason="Não há reconhecimento útil dentro do limite de falsos positivos." if rejected
                       else "Resultados sintéticos não comprovam desempenho real.",
                missing=["held-out real positive speakers", "long real ambient recordings",
                         "Android frontend parity, battery and latency"])


def evaluate(work):
    from scipy.io import wavfile
    import numpy as np
    model = work / "trained/tflite_stream_state_internal_quant/stream_state_internal_quant.tflite"
    records = [json.loads(line) for line in (work / "samples.jsonl").read_text().splitlines()]
    audit(records)
    scores = []
    for row in records:
        if row["split"] == "training":
            continue
        rate, audio = wavfile.read(work / row["path"])
        if rate != 16000 or audio.dtype != np.int16 or audio.ndim != 1:
            raise ValueError("Formato de avaliação inválido.")
        scores.append(dict(split=row["split"], positive=row["positive"],
                           voice=row["voice"], native_pt=row.get('native_pt'),
                           background=row.get('text') == '[synthetic silence/noise]',
                           score=score_clip(model, audio)))
    report = summarize_scores(scores)
    threshold = report['validation']['threshold']
    report['per_profile'] = []
    for voice in sorted({row['voice'] for row in scores}):
        rows = [row for row in scores if row['voice'] == voice]
        positive = [row for row in rows if row['positive']]
        negative = [row for row in rows if not row['positive']]
        background = [row for row in negative if row['background']]
        report['per_profile'].append(dict(voice=voice, split=rows[0]['split'], native_pt=rows[0]['native_pt'],
                                         positive_count=len(positive), negative_count=len(negative),
                                         recall=sum(r['score'] >= threshold for r in positive) / len(positive),
                                         false_positive_rate=sum(r['score'] >= threshold for r in negative) / len(negative),
                                         background_false_accepts=sum(r['score'] >= threshold for r in background)))
    report.update(model_sha256=sha256(model), model_bytes=model.stat().st_size)
    (work / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "scores"}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("generate", "features", "train", "audit", "evaluate"))
    parser.add_argument("--work", type=Path, default=ROOT / "work")
    parser.add_argument("--repetitions", type=int, default=80)
    parser.add_argument("--steps", type=int, default=3000)
    parser.add_argument("--smoke", action="store_true", help="Lote reduzido de geração para testar o pipeline, sem valor de validação.")
    args = parser.parse_args()
    if args.repetitions < 1 or args.steps < 1:
        parser.error("repetições e passos precisam ser positivos")
    work = args.work.resolve()
    if args.stage == "generate": generate(work, args.repetitions, smoke=args.smoke)
    elif args.stage == "features": features(work)
    elif args.stage == "train": train(work, args.steps)
    elif args.stage == "evaluate": evaluate(work)
    else:
        audit([json.loads(line) for line in (work / "samples.jsonl").read_text().splitlines()])
        print("Divisões e classes verificadas.")


if __name__ == "__main__":
    # Set before importing TensorFlow/NumPy; default modest CPU usage, Colab may override.
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "TF_NUM_INTRAOP_THREADS", "TF_NUM_INTEROP_THREADS"):
        os.environ.setdefault(variable, "1")
    main()

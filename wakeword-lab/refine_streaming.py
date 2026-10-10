"""Controlled v2 refinement. Training data only; synthetic gates never approve Android."""
import os
os.environ.setdefault('TF_NUM_INTRAOP_THREADS', '2')
os.environ.setdefault('TF_NUM_INTEROP_THREADS', '1')
from pathlib import Path
import argparse
import json
import math
import shutil
import sys
import zipfile
import numpy as np
import tensorflow as tf
import yaml
from mmap_ninja.ragged import RaggedMmap
from microwakeword import mixednet
from lab import audit, evaluate, sha256, training_config

class ConfigLoader(yaml.SafeLoader):
    pass
ConfigLoader.add_constructor('tag:yaml.org,2002:python/tuple',
                             lambda loader, node: tuple(loader.construct_sequence(node)))

def aligned_windows(features, length):
    """Reference-matched steady-state phase, retaining the unused final input frame."""
    return np.asarray([np.concatenate([features[end-length+1:end], np.zeros((1,40), np.float32)])
                       for end in range(length, len(features)+1, 3)], np.float32)

def operating_point(rows):
    if any(not math.isfinite(r['score']) or not 0<=r['score']<=1 for r in rows):
        raise ValueError('Pontuação inválida.')
    positives = sorted(r['score'] for r in rows if r['positive'])
    negatives = sorted(r['score'] for r in rows if not r['positive'])
    if not positives or not negatives:
        raise ValueError('Validação precisa das duas classes.')
    from bisect import bisect_left
    thresholds = {0.,1.} | set(positives + negatives) | {math.nextafter(v,1.) for v in positives+negatives}
    choices, all_choices = [], []
    for threshold in thresholds:
        recall = (len(positives)-bisect_left(positives,threshold))/len(positives)
        fpr = (len(negatives)-bisect_left(negatives,threshold))/len(negatives)
        item = dict(threshold=float(threshold),recall=recall,false_positive_rate=fpr)
        all_choices.append(item)
        if fpr <= .01:
            choices.append(item)
    if not choices:
        return min(all_choices,key=lambda r:(r['false_positive_rate'],-r['recall'],-r['threshold']))
    return max(choices, key=lambda r:(r['recall'],-r['false_positive_rate'],r['threshold']))

def load_features(source, manifest, split):
    result = {}
    for positive in (True, False):
        rows = [r for r in manifest if r['split']==split and r['positive']==positive]
        mmap = RaggedMmap(source/f'features/{int(positive)}/{split}/samples_mmap')
        if len(rows)!=len(mmap):
            raise ValueError('Manifesto não corresponde às características.')
        # Keep training mmap-backed rather than copying the corpus into GPU/RAM.
        result[positive] = (rows, mmap)
    return result

def validate(infer, data, length):
    scores = []
    for positive, (rows,mmap) in data.items():
        for index, row in enumerate(rows):
            features = np.asarray(mmap[index],np.float32)*.0390625
            windows = aligned_windows(features,length)
            if len(windows)<5:
                raise ValueError('Exemplo curto demais para medir estabilidade.')
            probabilities = np.concatenate([infer(windows[i:i+128]).numpy().ravel()
                                            for i in range(0,len(windows),128)])
            score = float(np.convolve(probabilities,np.ones(5)/5,'valid').max())
            scores.append(dict(positive=positive,score=score,voice=row['voice']))
    return operating_point(scores)

def make_model(config, source_weights, pooled):
    flags = argparse.Namespace(**config['flags'])
    original = mixednet.model(flags,config['training_input_shape'],1)
    original.load_weights(source_weights)
    if not pooled:
        return original
    flags.pooled = 1
    flags.max_pool = 0
    model = mixednet.model(flags,config['training_input_shape'],1)
    weights = original.get_weights()
    kernel,bias = weights[-2:]
    channels = model.layers[-1].get_weights()[0].shape[0]
    if kernel.shape[0]%channels:
        raise ValueError('Arquitetura recebida incompatível.')
    # Initialize the averaged temporal head from the old head; retraining is mandatory.
    model.set_weights(weights[:-2]+[kernel.reshape(-1,channels,1).sum(axis=0),bias])
    return model

def train_variant(source, destination, config, training, validation, steps, interval, pooled):
    destination.mkdir(parents=True,exist_ok=False)
    trained = destination/'trained'
    trained.mkdir()
    model = make_model(config,source/'trained/best_weights.weights.h5',pooled)
    length = config['spectrogram_length']
    rng = np.random.default_rng(20261004)
    tf.keras.utils.set_random_seed(20261004)
    @tf.function(input_signature=[tf.TensorSpec([None,length,40],tf.float32)])
    def infer(x):
        return model(x,training=False)
    best = validate(infer,validation,length)
    records = [dict(step=0,**best)]
    model.save_weights(trained/'best_weights.weights.h5')
    print(destination.name,'baseline',best,flush=True)
    warm_steps = min(100,max(1,steps//10))
    optimizer = tf.keras.optimizers.Adam(learning_rate=1e-4)
    variables = model.trainable_variables
    head_ids = {id(v) for v in model.layers[-1].trainable_variables}
    optimizer.build(variables)
    def update(only_head):
        selected = [v for v in variables if not only_head or id(v) in head_ids]
        @tf.function
        def run(x,y,weight):
            with tf.GradientTape() as tape:
                prediction = model(x,training=not only_head)
                loss = tf.keras.losses.binary_crossentropy(y,prediction)
                loss = tf.reduce_sum(loss*weight)/tf.reduce_sum(weight)
            gradients = tape.gradient(loss,selected)
            optimizer.apply_gradients(zip(gradients,selected))
            return loss
        return run
    head_step,full_step = update(True),update(False)
    for step in range(1,steps+1):
        inputs,labels,weights = [],[],[]
        for positive in (True,False):
            rows,mmap = training[positive]
            for index in rng.integers(0,len(rows),size=8):
                row = rows[index]
                features = np.asarray(mmap[index],np.float32)*.0390625
                if features.shape[1]!=40 or len(features)<length+3:
                    raise ValueError('Características inesperadas no treino.')
                # At most 30 ms earlier for complete calls (v2 adds >=60 ms trailing silence).
                end = len(features)-int(rng.integers(0,4)) if positive else (
                    len(features) if rng.random()<.5 else int(rng.integers(length,len(features)+1)))
                window = features[end-length:end].copy()
                # Small frequency mask; don't obscure temporal evidence for the short "Ei".
                if rng.random()<.5:
                    start = int(rng.integers(0,38))
                    window[:,start:start+2] = 0
                inputs.append(window)
                labels.append([float(positive)])
                text = row.get('text','').casefold()
                hard = not positive and ('emil' in text or 'êmil' in text)
                weights.append(1. if positive else (4. if hard else 2.))
        loss = (head_step if step<=warm_steps else full_step)(
            np.asarray(inputs),np.asarray(labels,np.float32),np.asarray(weights,np.float32))
        if step%interval==0 or step==steps:
            metrics = validate(infer,validation,length)
            records.append(dict(step=step,loss=float(loss),**metrics))
            rank = lambda r:(r['recall'],-r['false_positive_rate'])
            if rank(metrics)>rank(best):
                best = metrics
                model.save_weights(trained/'best_weights.weights.h5')
            print(destination.name,records[-1],flush=True)
            (destination/'streaming-selection.json').write_text(json.dumps(dict(
                evidence='validation_only_float_steady_state_not_android_approval',records=records,best=best),indent=2))
    model.save_weights(trained/'last_weights.weights.h5')
    return best

def export_variant(source,destination,steps,pooled):
    # Features/audio are read-only references for conversion and independent final evaluation.
    (destination/'features').symlink_to(source/'features',target_is_directory=True)
    (destination/'audio').symlink_to(source/'audio',target_is_directory=True)
    shutil.copyfile(source/'samples.jsonl',destination/'samples.jsonl')
    config = training_config(destination,steps)
    path = destination/'training.yaml'
    path.write_text(yaml.safe_dump(config))
    diagnostic_config = dict(config, flags=dict(pooled=int(pooled),max_pool=0,**{k:v for k,v in yaml.load((source/'trained/training_config.yaml').read_text(), Loader=ConfigLoader)['flags'].items() if k not in ('pooled','max_pool')}), training_input_shape=[222,40], spectrogram_length=222)
    (destination/'trained/training_config.yaml').write_text(yaml.safe_dump(diagnostic_config))
    import subprocess
    command = [sys.executable,str(Path(__file__).with_name('run_upstream.py')),
               '--training_config',str(path),'--train','0','--test_tflite_streaming_quantized','1',
               '--use_weights','best_weights','mixednet','--pointwise_filters','32,32,32,32',
               '--repeat_in_block','1,1,1,1','--mixconv_kernel_sizes','[5],[7,11],[9,15],[23]',
               '--residual_connection','0,0,0,0','--first_conv_filters','16',
               '--first_conv_kernel_size','5','--stride','3','--pooled',str(int(pooled)),'--max_pool','0']
    subprocess.run(command,check=True)
    evaluate(destination) # Fresh quantized streaming: includes startup and held-out testing.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--steps',type=int,default=1500)
    parser.add_argument('--interval',type=int,default=250)
    parser.add_argument('--require-gpu',action='store_true')
    parser.add_argument('--no-export',action='store_true',help='Local smoke test only.')
    args = parser.parse_args()
    if args.steps<1 or args.interval<1:
        raise ValueError('Passos e intervalo precisam ser positivos.')
    if args.require_gpu and not tf.config.list_physical_devices('GPU'):
        raise RuntimeError('GPU não detectada pelo ambiente de treino; confira T4 e bibliotecas CUDA antes de continuar.')
    source,output = args.source.resolve(),args.output.resolve()
    if output.exists() or output==source or source in output.parents:
        raise ValueError('Escolha uma pasta nova, fora dos dados originais.')
    manifest = [json.loads(line) for line in (source/'samples.jsonl').read_text().splitlines()]
    audit(manifest)
    config = yaml.load((source/'trained/training_config.yaml').read_text(),Loader=ConfigLoader)
    if tuple(config['training_input_shape'])!=(222,40) or config['flags']['pooled']!=0:
        raise ValueError('Este experimento é específico ao modelo v2 recebido.')
    training = load_features(source,manifest,'training')
    validation = load_features(source,manifest,'validation')
    output.mkdir()
    (output/'provenance.json').write_text(json.dumps(dict(
        source_manifest=sha256(source/'samples.jsonl'),source_weights=sha256(source/'trained/best_weights.weights.h5'),
        script_sha256=sha256(Path(__file__)),steps=args.steps,
        note='No personal audio. No test-set checkpoint or threshold tuning. Experimental only.'),indent=2))
    for variant,pooled in [('original-refined',False),('pooled-refined',True)]:
        destination = output/variant
        train_variant(source,destination,config,training,validation,args.steps,args.interval,pooled)
        if not args.no_export:
            export_variant(source,destination,args.steps,pooled)
    if not args.no_export:
        archive = output.with_suffix('.zip')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for path in output.rglob('*'):
                if path.is_file() and not path.is_symlink() and 'audio' not in path.relative_to(output).parts and 'features' not in path.relative_to(output).parts:
                    z.write(path,str(path.relative_to(output)))
        print('Pacote para análise:',archive,flush=True)

if __name__=='__main__':
    main()

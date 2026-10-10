"""Offline comparison; never changes the Android model or uses private audio for tuning."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import time
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly


def evaluate(words, prefix_conf=.85, name_conf=.70, name_duration=.27):
    if not words:
        return 'empty'
    if words[0]['word'] != 'hey':
        return 'missing_prefix'
    if len(words) < 2 or words[1]['word'] != 'emily':
        return 'missing_name'
    if len(words) > 3:
        return 'too_many_words'
    first, second = words[:2]
    if any(not all(math.isfinite(w[k]) for k in ['start', 'end', 'conf'])
           or w['start'] < 0 or w['end'] <= w['start'] for w in [first, second]):
        return 'invalid_timing'
    if not -.06 <= second['start'] - first['end'] <= .45:
        return 'separated_call'
    if first['conf'] < prefix_conf or second['conf'] < name_conf:
        return 'low_confidence'
    if first['end']-first['start'] < .08 or second['end']-second['start'] < name_duration:
        return 'too_short'
    return 'accepted'


def read_audio(path):
    rate, data = wavfile.read(path)
    if data.ndim != 1 or data.dtype != np.int16:
        raise ValueError('Expected mono PCM16 WAV: '+str(path))
    if rate != 16000:
        divisor = math.gcd(rate, 16000)
        data = np.clip(np.rint(resample_poly(data.astype(float), 16000//divisor,
                                          rate//divisor)), -32768, 32767).astype(np.int16)
    return data


def corpus(root):
    rows=[]; seen=set()
    for bank in ['diverse-pilot', 'smoke']:
        base=root/bank
        for line in (base/'samples.jsonl').read_text().splitlines():
            row=json.loads(line); path=base/row['path']
            sha=hashlib.sha256(path.read_bytes()).hexdigest()
            if sha != row['sha256']:
                raise ValueError('Corpus hash mismatch: '+str(path))
            if sha in seen:
                continue
            seen.add(sha)
            yield dict(path=str(path), group=bank, voice=row['voice'], text=row['text'],
                       positive=row['positive'], split=row['split'], sha256=sha), read_audio(path)
    base=root/'received-source-pilot-12'
    audit=json.loads((base/'audit.json').read_text())
    for row in audit['records']:
        path=base/row['path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Source pilot hash mismatch')
        yield dict(path=str(path), group='qwen', voice=row['voice'], text=row['expected_text'],
                   positive=row['positive'], split='testing', kind=row['kind'],
                   asr_flags=row['audit_flags']), read_audio(path)
    path=root/'received-candidate/private-user.wav'; data=read_audio(path)
    for name,start,end in [('normal',0,2.6),('fast',2.6,4.9),('quiet',4.9,len(data)/16000)]:
        yield dict(path=str(path),group='private',voice='user',text='Ei Emily',positive=True,
                   split='testing',kind=name),data[int(start*16000):int(end*16000)]


def summarize(rows):
    result={}
    for group in sorted({r['group'] for r in rows}):
        selected=[r for r in rows if r['group']==group]
        positives=[r for r in selected if r['positive']]
        negatives=[r for r in selected if not r['positive']]
        result[group]=dict(positive_total=len(positives),positive_accepted=sum(r['accepted'] for r in positives),
                           negative_total=len(negatives),negative_accepted=sum(r['accepted'] for r in negatives),
                           audio_seconds=sum(r['seconds'] for r in selected),
                           processing_seconds=sum(r['processing_seconds'] for r in selected))
    return result


def run(model_path, output, held_out_only=False):
    import vosk
    vosk.SetLogLevel(-1)
    started=time.monotonic(); model=vosk.Model(str(model_path)); load=time.monotonic()-started
    # Grammar support and vocabulary must match the current service.
    for word in ['hey','emily']:
        if model.vosk_model_find_word(word) < 0:
            raise ValueError('Required keyword absent from vocabulary: '+word)
    rows=[]
    for metadata, audio in corpus(Path('work')):
        if held_out_only and metadata['split']=='training':
            continue
        rec=vosk.KaldiRecognizer(model,16000,'["hey emily", "[unk]"]');rec.SetWords(True)
        # Fixed padding shared by both models. Preserve all source audio and onset.
        pcm=np.pad(audio,(5120,20800)).astype('<i2')
        started=time.monotonic(); segments=[]
        for at in range(0,len(pcm),640):
            if rec.AcceptWaveform(pcm[at:at+640].tobytes()):
                segment=json.loads(rec.Result())
                segment['audio_processed_seconds']=min(at+640,len(pcm))/16000
                segments.append(segment)
        segment=json.loads(rec.FinalResult())
        segment['audio_processed_seconds']=len(pcm)/16000
        segments.append(segment)
        elapsed=time.monotonic()-started
        # Evaluate endpoints separately, as Android does; never merge independent utterances.
        decisions=[evaluate(p.get('result',[])) for p in segments]
        rows.append(dict(**metadata,seconds=len(audio)/16000,processing_seconds=elapsed,
                         accepted='accepted' in decisions,segments=segments,decisions=decisions))
        if len(rows)%50==0:
            print('Processed',len(rows),'clips',flush=True)
    report=dict(model=str(model_path),vosk_version='0.3.45',model_load_seconds=load,
                held_out_only=held_out_only,
                process_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                thresholds=dict(prefix_conf=.85,name_conf=.70,name_duration=.27),summary=summarize(rows),rows=rows,
                limits=['CPU timing and process RSS are from PC, not Android.',
                        'Live VAD, microphone processing, recovery and onset gate are not reproduced.',
                        'Synthetic negatives do not establish real-world false accepts per hour.'])
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ['rows']},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--held-out-only',action='store_true')
    args=parser.parse_args();run(args.model,args.output,args.held_out_only)

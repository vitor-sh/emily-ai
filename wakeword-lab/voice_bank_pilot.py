"""Audit a new synthetic PT-BR voice bank before any wake-word training."""
from pathlib import Path
import argparse
import hashlib
import itertools
import json
import math
import time
import unicodedata
import numpy as np
from scipy.signal import resample_poly

MODELS = {
    'reference': ('Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign', '5ecdb67327fd37bb2e042aab12ff7391903235d3'),
    'phrases': ('Qwen/Qwen3-TTS-12Hz-0.6B-Base', '5d83992436eae1d760afd27aff78a71d676296fc'),
}
REFERENCE_TEXT = 'Hoje eu vou caminhar pelo bairro e conversar com meus amigos. Depois volto para casa e escuto uma música.'
PHRASES = [('call-emily', True, 'Ei, Emily.'), ('call-emili', True, 'Ei, Emili.'),
           ('name-only', False, 'Emily.'), ('mention', False, 'Eu estava falando com a Emily ontem.')]
REGIONS = ['São Paulo', 'Rio de Janeiro', 'Minas Gerais', 'Bahia', 'Pernambuco', 'Rio Grande do Sul']
AGES = ['young adult', 'middle-aged adult', 'older adult']
TIMBRES = ['clear and bright', 'warm and resonant', 'soft and airy', 'slightly husky', 'low and rounded', 'light and nasal']

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def profiles(count):
    if not 1 <= count <= 216:
        raise ValueError('Use de 1 a 216 perfis solicitados; o piloto recomendado usa 12.')
    result = []
    for cycle in range(18):
        for region_index, region in enumerate(REGIONS):
            for gender_index, gender in enumerate(['female', 'male']):
                age = AGES[(cycle+region_index+gender_index)%len(AGES)]
                timbre = TIMBRES[(cycle//3+region_index+gender_index)%len(TIMBRES)]
                instruction = (f'Natural Brazilian Portuguese, a {age} {gender} voice with a {timbre} timbre. '
                               f'A gentle everyday regional accent from {region}, Brazil. '
                               'Speak conversationally, without caricature, singing or theatrical exaggeration.')
                ident = hashlib.sha256(instruction.encode()).hexdigest()[:16]
                if any(p['id']==ident for p in result):
                    continue
                result.append(dict(id=ident,requested_region=region,requested_age=age,
                                   requested_gender=gender,requested_timbre=timbre,instruction=instruction))
    if len(result)<count:
        raise RuntimeError('Descrições insuficientes; não inflar o banco por duplicação.')
    return result[:count]

def normalize(text):
    text = ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))
    return ' '.join(''.join(c if c.isalpha() else ' ' for c in text).split())

def transcript_flags(text, positive):
    words = normalize(text).split()
    names = {'emily','emili','emilie'}
    call = len(words)>=2 and words[0] in {'ei','hey'} and words[1] in names
    if positive:
        return ([] if call and len(words)==2 else ['call_transcription_needs_listening'])
    return ['negative_transcription_contains_call'] if any(
        words[i] in {'ei','hey'} and words[i+1] in names for i in range(len(words)-1)) else []

def audio_checks(audio,rate,positive=False):
    audio = np.asarray(audio,dtype=np.float32)
    if rate<8000 or audio.ndim!=1 or len(audio)<rate*.1 or not np.isfinite(audio).all():
        raise ValueError('Áudio vazio, inválido ou não mono.')
    peak = float(np.abs(audio).max())
    if peak<.001:
        raise ValueError('Síntese silenciosa.')
    frame = max(1,int(rate*.01))
    energy = np.sqrt(np.mean(audio[:len(audio)//frame*frame].reshape(-1,frame)**2,axis=1))
    active = np.flatnonzero(energy>max(.0005,float(energy.max())*.02))
    if not len(active):
        raise ValueError('Sem fala detectável.')
    active_seconds = float((active[-1]-active[0]+1)*frame/rate)
    leading_seconds = float(active[0]*frame/rate)
    trailing_seconds = float((len(audio)-(active[-1]+1)*frame)/rate)
    flags = []
    if positive and active_seconds>2.:
        flags.append('call_longer_than_v2_training_budget')
    if float(np.mean(np.abs(audio)>=.999))>.01:
        flags.append('clipping')
    if len(audio)/rate>16:
        flags.append('possible_generation_loop_or_truncation')
    # A short call can hit the token budget while producing silence rather than speech.
    # Keep the raw waveform: an energy boundary is not a safe keyword trimming rule.
    if positive and len(audio)/rate>4:
        flags.append('short_call_unexpected_file_duration')
    if leading_seconds>1:
        flags.append('excessive_leading_silence')
    if trailing_seconds>1:
        flags.append('excessive_trailing_silence')
    return dict(seconds=len(audio)/rate,active_seconds=active_seconds,
                leading_seconds=leading_seconds,trailing_seconds=trailing_seconds,peak=peak,flags=flags)

def pcm16(audio,rate):
    factor = math.gcd(rate,16000)
    resampled = resample_poly(np.asarray(audio,np.float32),16000//factor,rate//factor)
    if not np.isfinite(resampled).all():
        raise ValueError('Resampling inválido.')
    return np.clip(np.rint(resampled*32768),-32768,32767).astype(np.int16)

def write_json(path,data):
    temporary = path.with_suffix('.part')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    temporary.replace(path)

def read_progress(work,count):
    work.mkdir(parents=True,exist_ok=True)
    settings = dict(models=MODELS,profiles=profiles(count),phrases=PHRASES,reference_text=REFERENCE_TEXT,
                    script_sha256=digest(__file__),evidence='synthetic_profiles_not_real_speakers')
    signature = hashlib.sha256(json.dumps(settings,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    path = work/'progress.json'
    data = json.loads(path.read_text()) if path.exists() else dict(signature=signature,settings=settings,records=[])
    if data['signature']!=signature:
        raise ValueError('Piloto alterado: use uma pasta nova; não misturar vozes ou parâmetros.')
    for relative, expected in data.get('embedding_hashes',{}).items():
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts or digest(work/path)!=expected:
            raise ValueError('Embedding do piloto alterado ou caminho inválido.')
    for row in data['records']:
        relative = Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts or digest(work/relative)!=row['sha256']:
            raise ValueError('Arquivo do piloto alterado ou caminho inválido.')
    return data

def snapshot(stage,work):
    from huggingface_hub import snapshot_download
    repo,revision = MODELS[stage]
    return snapshot_download(repo_id=repo,revision=revision,cache_dir=str(work.parent/'model-cache'),
                             allow_patterns=['*.json','*.safetensors','*.txt','*.model','README.md','LICENSE'])

def load_model(stage,work):
    import torch
    from qwen_tts import Qwen3TTSModel
    if not torch.cuda.is_available():
        raise RuntimeError('Este piloto precisa da GPU gratuita do Colab; selecione T4.')
    # Avoid FP16 sampling overflow on Turing/T4; native BF16 is used only when supported.
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float32
    print('GPU:',torch.cuda.get_device_name(0),'precision:',dtype,flush=True)
    model = Qwen3TTSModel.from_pretrained(snapshot(stage,work),device_map='cuda:0',dtype=dtype,
                                        attn_implementation='sdpa',low_cpu_mem_usage=True)
    if 'portuguese' not in model.get_supported_languages():
        raise RuntimeError('Português não disponível nesta revisão.')
    return model

def seed(profile,phrase):
    return int(hashlib.sha256((profile+':'+phrase).encode()).hexdigest()[:8],16)

def generate(stage,work,count):
    import torch
    import soundfile as sf
    from scipy.io import wavfile
    from transformers import set_seed
    data = read_progress(work,count)
    if stage=='reference':
        missing = [p for p in profiles(count) if not any(r['voice']==p['id'] and r['kind']=='reference' for r in data['records'])]
    else:
        missing = [p for p in profiles(count) if any(not any(r['voice']==p['id'] and r['kind']==key for r in data['records']) for key,_,_ in PHRASES)]
    if not missing:
        print('Etapa já concluída:',stage,flush=True)
        return
    model = load_model(stage,work)
    for profile in missing:
        ident = profile['id']
        print('Perfil solicitado:',profile['requested_region'],profile['requested_gender'],ident,flush=True)
        if stage=='reference':
            set_seed(seed(ident,'reference'))
            started = time.monotonic()
            wavs,rate = model.generate_voice_design(text=REFERENCE_TEXT,language='Portuguese',
                instruct=profile['instruction'],max_new_tokens=384,temperature=.8)
            audio = np.asarray(wavs[0]).reshape(-1)
            checks = audio_checks(audio,rate)
            if checks['seconds']<3 or checks['seconds']>20:
                raise ValueError('Referência com duração inadequada; revisar antes de clonar.')
            relative = Path('references')/(ident+'.wav')
            (work/relative).parent.mkdir(exist_ok=True)
            sf.write(work/relative,audio,rate,subtype='PCM_16')
            data['records'].append(dict(voice=ident,kind='reference',path=str(relative),sha256=digest(work/relative),
                expected_text=REFERENCE_TEXT,positive=False,model_revision=MODELS[stage][1],seed=seed(ident,'reference'),
                inference_seconds=time.monotonic()-started,checks=checks))
            write_json(work/'progress.json',data)
        else:
            reference = next((r for r in data['records'] if r['voice']==ident and r['kind']=='reference'),None)
            if reference is None:
                raise ValueError('Gere a referência antes das chamadas.')
            prompt = model.create_voice_clone_prompt(ref_audio=str(work/reference['path']),ref_text=REFERENCE_TEXT)
            vector = prompt[0].ref_spk_embedding.detach().float().cpu().numpy().ravel()
            if not np.isfinite(vector).all() or np.linalg.norm(vector)==0:
                raise ValueError('Embedding de referência inválido.')
            vector_path = Path('references')/(ident+'.npy')
            np.save(work/vector_path,vector,allow_pickle=False)
            data.setdefault('embedding_hashes',{})[str(vector_path)] = digest(work/vector_path)
            write_json(work/'progress.json',data)
            for key,positive,text in PHRASES:
                if any(r['voice']==ident and r['kind']==key for r in data['records']):
                    continue
                set_seed(seed(ident,key))
                started = time.monotonic()
                wavs,rate = model.generate_voice_clone(text=text,language='Portuguese',voice_clone_prompt=prompt,
                                                     max_new_tokens=192,temperature=.8)
                audio = np.asarray(wavs[0]).reshape(-1)
                checks = audio_checks(audio,rate,positive)
                relative = Path('audio')/(ident+'-'+key+'.wav')
                (work/relative).parent.mkdir(exist_ok=True)
                wavfile.write(work/relative,16000,pcm16(audio,rate))
                data['records'].append(dict(voice=ident,kind=key,path=str(relative),sha256=digest(work/relative),
                    expected_text=text,positive=positive,model_revision=MODELS[stage][1],seed=seed(ident,key),
                    inference_seconds=time.monotonic()-started,checks=checks))
                write_json(work/'progress.json',data)
    print('Etapa concluída:',stage,flush=True)


def audit(work,count):
    import whisper
    import torch
    from difflib import SequenceMatcher
    data = read_progress(work,count)
    if len(data['records'])!=count*(len(PHRASES)+1):
        raise ValueError('Piloto incompleto; conclua referências e frases antes de auditar.')
    if not torch.cuda.is_available():
        raise RuntimeError('GPU não disponível para a auditoria.')
    model = whisper.load_model('small',device='cuda',download_root=str(work.parent/'asr-cache'))
    rows = []
    for row in data['records']:
        result = model.transcribe(str(work/row['path']),language='pt',task='transcribe',fp16=True,
                                  temperature=0,condition_on_previous_text=False)
        text = result['text'].strip()
        flags = list(row['checks']['flags'])
        if row['kind']=='reference':
            similarity = SequenceMatcher(None,normalize(row['expected_text']),normalize(text)).ratio()
            if similarity<.75:
                flags.append('reference_transcription_needs_listening')
        else:
            flags.extend(transcript_flags(text,row['positive']))
        rows.append(dict(**row,transcript=text,audit_flags=flags,pronunciation_verified=False))
        print(row['kind'],row['voice'],text,flags,flush=True)
    vectors = [np.load(work/'references'/(p['id']+'.npy'),allow_pickle=False) for p in profiles(count)]
    normalized = np.asarray([v/np.linalg.norm(v) for v in vectors])
    similarities = normalized@normalized.T
    similar = [dict(first=profiles(count)[a]['id'],second=profiles(count)[b]['id'],cosine=float(similarities[a,b]))
               for a,b in itertools.combinations(range(count),2) if similarities[a,b]>.95]
    report = dict(status='voice_source_pilot_only_not_a_wakeword_model',synthetic_profiles_requested=count,
        real_speakers_recorded=0,accent_verified=False,profiles=data['settings']['profiles'],
        similar_embedding_pairs=similar,similarity_note='Heuristic warning only; not a proof of unique speakers or independent accents.',
        manual_review_required=True,records=rows,source_models=MODELS,source_license='Apache-2.0',
        generation_seconds=sum(r['inference_seconds'] for r in rows),
        missing=['human pronunciation and accent audit','held-out speaker grouping before training',
                 'real ambient negatives and long-audio evaluation','proof of improvement against Android baseline'])
    write_json(work/'audit.json',report)
    import html
    cards=[]
    for profile in profiles(count):
        ident=profile['id'];items=[]
        for row in rows:
            if row['voice']!=ident:continue
            items.append('<p>'+html.escape(row['expected_text'])+'</p><audio controls preload="none" src="'+row['path']+'"></audio><p class="small">Whisper: '+html.escape(row['transcript'])+'<br>'+html.escape(', '.join(row['audit_flags']))+'</p>')
        cards.append('<section><h2>'+html.escape(profile['requested_region']+' · '+profile['requested_gender'])+'</h2><p class="small">Sotaque solicitado, ainda não confirmado. '+html.escape(profile['requested_age']+' / '+profile['requested_timbre'])+'</p>'+''.join(items)+'</section>')
    (work/'listening.html').write_text('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Emily · auditoria de vozes</title><style>body{background:#151513;color:#eee;font:16px system-ui;max-width:850px;margin:auto;padding:24px}section{background:#242421;padding:20px;margin:20px 0;border-radius:18px}audio{width:100%}h1,h2{color:#f29765}.small{color:#aaa;font-size:14px}</style><h1>Auditoria de vozes · Ei, Emily</h1><p>Piloto sintético. Ouça a chamada inteira, o “Ei”, a pronúncia do nome e se as vozes realmente diferem. A transcrição automática é auxiliar e pode errar. Este pacote não atualiza o Android.</p>'+''.join(cards)+'</html>')
    import zipfile
    archive=work.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for path in work.rglob('*'):
            if path.is_file() and not path.is_symlink():
                z.write(path,str(path.relative_to(work)))
    print('Piloto pronto:',archive,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['reference','phrases','audit'])
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--profiles',type=int,default=12)
    args=parser.parse_args()
    profiles(args.profiles)
    if args.stage=='audit':audit(args.work.resolve(),args.profiles)
    else:generate(args.stage,args.work.resolve(),args.profiles)

if __name__=='__main__':main()

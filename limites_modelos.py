"""Limites por rota/modelo; catálogo do provedor antes do valor documentado."""
import json
import os
import hashlib
import re
import threading
import time
from pathlib import Path

_CACHE={}
_LOCK=threading.RLock()
CACHE_ROOT=Path(os.getenv('EMILY_DATA_DIR',str(Path.home()/'.local/share/emily')))/'catalogos-modelos'

def catalogo(provider):
    import llm
    with _LOCK:
        obj=llm.PROVEDORES.get(provider)
        if obj is None:return {}
        identity=(id(obj),getattr(obj,'base_url',None))
        cached=_CACHE.get(provider)
        if cached and cached[2]==identity and time.time()-cached[0]<3600:return cached[1]
        ident=hashlib.sha256((provider+str(getattr(obj,'base_url',''))).encode()).hexdigest()
        path=CACHE_ROOT/(ident+'.json')
        if not cached:
            try:
                saved=json.loads(path.read_text())
                limits={k:v for k,v in saved['limits'].items() if isinstance(v,int) and 1024<=v<=10000000}
                cached=(saved['updated_at'],limits,identity)
                if time.time()-cached[0]<3600:
                    _CACHE[provider]=cached
                    return limits
            except (OSError,ValueError,KeyError,TypeError):pass
        try:
            client=obj._obter_cliente().with_options(timeout=8.0,max_retries=0)
            rows=client.models.list().data
            limits={}
            for row in rows:
                d=row.model_dump()
                value=d.get('context_window') or d.get('context_length') or d.get('max_input_tokens') or (d.get('top_provider') or {}).get('context_length')
                if isinstance(value,int) and 1024<=value<=10000000:limits[d['id'].lower()]=value
            _CACHE[provider]=(time.time(),limits,identity)
            try:
                CACHE_ROOT.mkdir(parents=True,exist_ok=True)
                tmp=path.with_suffix('.tmp')
                tmp.write_text(json.dumps({'updated_at':time.time(),'limits':limits}))
                tmp.replace(path)
            except OSError:pass
            return limits
        except Exception:
            # Não logar corpo/credenciais de um catálogo indisponível.
            _CACHE[provider]=(time.time()-3300,cached[1] if cached and cached[2]==identity else {},identity)
            return _CACHE[provider][1]

def catalogo_em_cache(provider):
    """Último catálogo conhecido do provedor (memória ou disco), sem rede."""
    with _LOCK:
        cached=_CACHE.get(provider)
        if cached and cached[1]:return dict(cached[1])
    try:
        import llm
        obj=llm.PROVEDORES.get(provider)
        if obj is None:return {}
        ident=hashlib.sha256((provider+str(getattr(obj,'base_url',''))).encode()).hexdigest()
        saved=json.loads((CACHE_ROOT/(ident+'.json')).read_text())
        return {k:v for k,v in saved['limits'].items() if isinstance(v,int) and 1024<=v<=10000000}
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return {}

def provedor(model):
    import llm
    mid=str(model or '').lower()
    for pid,cfg in llm.PROVEDORES_CONFIG.items():
        if mid in [m.lower() for m in cfg.modelos_csv] or mid==cfg.modelo_padrao.lower():return pid
    for pid,cfg in llm.PROVEDORES_CONFIG.items():
        if cfg.tipo in ('anthropic','openai_anthropic') and mid in catalogo(pid):return pid
    return None

def resolve(model):
    model=str(model or '').lower()
    if model.startswith('cx/'):
        return 272000,'Catálogo Codex da assinatura (07/10/2026)',True
    try:
        import llm
        pid=provedor(model)
        if pid:
            value=catalogo(pid).get(model)
            if value:return value,'Catálogo do provedor '+pid,True
    except (AttributeError,ImportError):pass
    mid=model.split('/')[-1].replace('.', '-')
    # Padrão documentado; não ativar a janela beta 1M dos modelos 4.5.
    if re.fullmatch(r'claude-(?:opus|sonnet|haiku|fable|mythos)-5(?:-\d+)*(?:-\d{8})?',mid) or re.fullmatch(r'claude-(?:opus|sonnet)-4-[6-9](?:-\d{8})?',mid):
        return 1000000,'Padrão documentado pela Anthropic; a rota pode impor limite menor',False
    if mid.startswith('claude-'):
        return 200000,'Padrão documentado da família Claude; a rota pode impor limite menor',False
    return 128000,'Orçamento conservador; limite do provedor não informado',False

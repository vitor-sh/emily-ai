"""Somente percentuais da conta Codex; credenciais/admin nunca saem da Oracle."""
import json
import os
from pathlib import Path
import threading
import time
import requests

_lock=threading.Lock()
_cache=None
_session=None

def normalize(data):
    windows=[]
    quotas=data.get('quotas') or {}
    for name,label,seconds in [('session','5 horas',18000),('weekly','Semanal',604800)]:
        q=quotas.get(name)
        if not isinstance(q,dict):continue
        used,total=q.get('used'),q.get('total')
        if not isinstance(used,(int,float)) or isinstance(used,bool) or not isinstance(total,(int,float)) or total<=0:continue
        windows.append({'name':name,'label':label,'used_percent':round(max(0,min(100,used/total*100)),2),
            'remaining_percent':round(max(0,min(100,100-used/total*100)),2),
            'resets_at':q.get('resetAt'),'window_seconds':q.get('windowSeconds') or seconds})
    return windows

def cloud_usage():
    global _cache,_session
    with _lock:
        now=time.time()
        if _cache and now-_cache['checked_at']<30:return dict(_cache)
        try:
            password_file=Path(os.getenv('EMILY_OMNI_ADMIN_PASSWORD_FILE',str(Path.home()/'.config/emily-runtime-cloud/omni-admin-password')))
            if password_file.exists():password=password_file.read_text().strip()
            else:
                # Usa o segredo já existente na VM, sem transportar a senha ao APK.
                from dotenv import dotenv_values
                password=dotenv_values(Path.home()/'omniroute-cloud/.env').get('INITIAL_PASSWORD')
            if not password:raise ValueError('Acesso privado às cotas não configurado')
            base='http://127.0.0.1:20128'
            if _session is None:_session=requests.Session()
            providers=_session.get(base+'/api/providers',timeout=(3,12))
            if providers.status_code==401:
                login=_session.post(base+'/api/auth/login',json={'password':password},timeout=(3,12));login.raise_for_status()
                providers=_session.get(base+'/api/providers',timeout=(3,12))
            providers.raise_for_status();connections=providers.json().get('connections',[])
            accounts=[]
            for c in connections:
                if c.get('provider')!='codex' or c.get('isActive') is False:continue
                r=_session.get(base+'/api/usage/'+c['id'],timeout=(3,15));r.raise_for_status()
                windows=normalize(r.json())
                if windows:accounts.append({'label':'Conta Codex '+str(len(accounts)+1),'windows':windows})
            if not accounts:raise ValueError('Cotas não informadas pelo provedor')
            _cache={'ok':True,'accounts':accounts,'checked_at':now,'updated_at':time.time(),'stale':False,
                    'scope':'Uso da conta inteira: inclui Codex, OmniRoute e outros dispositivos. Atualizado a cada 30 segundos.'}
            return dict(_cache)
        except Exception:
            if _cache:
                _cache={**_cache,'checked_at':now,'stale':True,'error':'Consulta indisponível; mostrando a última leitura.'}
                return dict(_cache)
            return {'ok':False,'accounts':[],'checked_at':now,'error':'Cotas da conta indisponíveis no momento.'}

def desktop_usage():
    """Usa o acesso administrativo privado já provisionado para a ponte Oracle."""
    global _cache
    with _lock:
        now=time.time()
        if _cache and now-_cache['checked_at']<20:return dict(_cache)
        try:
            cfg=json.loads((Path.home()/'.config/emily-cloud-oracle/discord-host.json').read_text())
            r=requests.post(cfg['url']+'/admin/llm/usage',headers={'Authorization':'Bearer '+cfg['key']},json={},timeout=(5,25))
            r.raise_for_status();data=r.json()
            if not isinstance(data,dict):raise ValueError()
            _cache={**data,'checked_at':now};return dict(_cache)
        except Exception:
            if _cache:return {**_cache,'stale':True,'error':'Consulta indisponível; mostrando a última leitura.'}
            return {'ok':False,'accounts':[],'error':'Cotas da conta indisponíveis no momento.'}

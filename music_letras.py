"""Consulta de letras LRCLIB sob demanda; não altera a biblioteca do usuário."""
import json
import urllib.parse
import urllib.request
from functools import lru_cache

@lru_cache(maxsize=64)
def _buscar(query):
    url='https://lrclib.net/api/search?'+urllib.parse.urlencode({'q':query})
    req=urllib.request.Request(url,headers={'User-Agent':'EmilyMusic/1.0 (desktop lyrics client)','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as r:
        raw=r.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('Resposta de letras muito grande.')
    data=json.loads(raw)
    if not isinstance(data,list):raise ValueError('Resposta inválida do serviço de letras.')
    return tuple({'id':m.get('id'),'titulo':str(m.get('trackName') or ''),
        'artista':str(m.get('artistName') or ''),'album':str(m.get('albumName') or ''),
        'duracao':m.get('duration',0),'instrumental':bool(m.get('instrumental')),
        'sincronizada':str(m.get('syncedLyrics') or '')[:150000],
        'texto':str(m.get('plainLyrics') or '')[:150000]} for m in data[:12] if isinstance(m,dict))

def buscar(query):
    query=str(query or '').strip()[:200]
    if not query:return {'erro':'Digite o nome da música e, se souber, o artista.'}
    try:return {'resultados':[dict(m) for m in _buscar(query)],'fonte':'LRCLIB'}
    except Exception:return {'erro':'Não foi possível consultar as letras. Verifique a conexão e tente novamente.'}

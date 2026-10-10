"""Controle do bot hospedado; ferramentas de desktop continuam no desktop."""
import functools
import json
import os
from pathlib import Path
import requests

CONFIG = Path.home()/'.config/emily-cloud-oracle/discord-host.json'
REMOTE_METHODS = {
    'ver_canais', 'ler_chat_discord', 'mandar_mensagem_discord',
    'responder_mensagem_discord', 'mandar_dm_discord', 'entrar_em_call',
    'sair_da_call', 'listar_calls', 'ativar_escuta_discord',
    'desativar_escuta_discord', 'escuta_ativa', 'desconectar_voz',
}

def hospedado_na_oracle():
    return CONFIG.is_file()

def rpc(method, args):
    cfg = json.loads(CONFIG.read_text())
    response = requests.post(cfg['url']+'/admin/discord/rpc',
        headers={'Authorization': 'Bearer '+cfg['key']},
        json={'method': method, 'args': args}, timeout=(5, 90))
    response.raise_for_status()
    data = response.json()
    if not data.get('ok'):
        raise RuntimeError(data.get('erro', 'Discord indisponível na nuvem'))
    return data['result']

def instalar_proxy(namespace):
    import inspect
    for name in REMOTE_METHODS:
        original = namespace.get(name)
        if original is None: continue
        signature = inspect.signature(original)
        def wrap(fn, method, sig):
            @functools.wraps(fn)
            def invoke(*args, **kwargs):
                if os.getenv('EMILY_RUNTIME_CLOUD') == '1' or not hospedado_na_oracle():
                    return fn(*args, **kwargs)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                return rpc(method, dict(bound.arguments))
            return invoke
        namespace[name] = wrap(original, name, signature)

def ferramenta_local_na_nuvem(f):
    return f.grupo == 'discord' or f.nome in {
        'pesquisar_internet', 'hora_atual', 'perguntar_usuario_tarefa', 'lembrar_fatos',
        'ver_canais_discord', 'ler_chat_discord', 'mandar_mensagem_discord',
        'responder_mensagem_discord', 'mandar_dm_discord',
    }

def executar_no_pc(nome, argumentos, contexto):
    from ferramentas import ResultadoFerramenta
    # O bot mantém suas verificações de identidade; o desktop exige uma chave
    # interna separada, além da autenticação habitual da ponte.
    cfg = json.loads(Path(os.environ['EMILY_RELAY_CONFIG']).read_text())
    try:
        context = {k: v for k, v in (contexto or {}).items()
                   if isinstance(v, (str, bool, int, float, list, dict, type(None)))}
        response = requests.post(cfg['pc_url']+'/internal/cloud/tool',
            headers={'Authorization': 'Bearer '+cfg['pc_token'],
                     'X-Emily-Cloud-Key': cfg['upload_key']},
            json={'nome': nome, 'argumentos': argumentos, 'contexto': context},
            timeout=(3, 240))
        response.raise_for_status()
        data = response.json()
        return ResultadoFerramenta(**{k: v for k, v in data.items()
                                     if k in ResultadoFerramenta.__dataclass_fields__})
    except (requests.RequestException, ValueError, TypeError):
        return ResultadoFerramenta(texto='Essa ferramenta usa o PC. Ele precisa estar ligado, conectado e com a Emily aberta.',
            ok=False, mudou=False, erro='pc_desconectado')


def executar_na_oracle(nome, argumentos, contexto):
    from ferramentas import ResultadoFerramenta
    try:
        data = rpc('tool', {'nome': nome, 'argumentos': argumentos,
            'contexto': {k:v for k,v in (contexto or {}).items()
                         if isinstance(v, (str, bool, int, float, list, dict, type(None)))}})
        return ResultadoFerramenta(**data)
    except (requests.RequestException, ValueError, RuntimeError):
        return ResultadoFerramenta(texto='Discord na nuvem indisponível no momento.',
            ok=False, mudou=False, erro='discord_cloud_indisponivel')

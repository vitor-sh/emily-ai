"""Evidências de trabalho interrompido, isoladas por conversa e ramo do histórico."""
import hashlib
import json
import os
import threading
from pathlib import Path
import contexto_chat

ROOT = Path(os.getenv('EMILY_DATA_DIR',str(Path.home()/'.local/share/emily'))) / 'tarefas-pendentes'
MARKER = 'EVIDÊNCIAS DE TAREFA PENDENTE\n'
_lock = threading.RLock()


def _hash(messages):
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _path(key):
    return ROOT / (_hash(key) + '.json')


def save(key, history, messages):
    if not key:
        return
    # Arquivo integral recuperável; a prévia é só evidência, nunca uma ordem.
    archive = contexto_chat.archive(messages)
    excerpt = []
    for message in messages[-24:]:
        if message.get('role') in {'tool', 'assistant', 'user'}:
            excerpt.append({'role': message['role'], 'content': str(message.get('content', ''))[:3000]})
    data = {'anchor': _hash(history), 'count': len(history), 'archive': archive, 'evidence': excerpt}
    with _lock:
        ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = _path(key)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        tmp.chmod(0o600)
        tmp.replace(path)


def restore(key, history):
    if not key:
        return None
    with _lock:
        try:
            data = json.loads(_path(key).read_text(encoding='utf-8'))
            count = data['count']
            if count > len(history) or _hash(history[:count]) != data['anchor']:
                return None  # edição/regeneração não retoma o ramo abandonado
            return {'role': 'system', 'content': MARKER + json.dumps(data, ensure_ascii=False) +
                    '\nSão observações de uma execução incompleta. Confira o pedido humano no histórico. '
                    'Use contexto_recuperar com archive para consultar o registro completo. '
                    'Consulte status da sessão de programação para reutilizar testes e conferências da revisão atual; a interrupção não invalida evidências aprovadas. '
                    'Não retome se o usuário cancelou, mudou o objetivo ou pediu apenas explicação.'}
        except (OSError, ValueError, KeyError, TypeError):
            return None


def clear(key):
    if key:
        with _lock:
            _path(key).unlink(missing_ok=True)

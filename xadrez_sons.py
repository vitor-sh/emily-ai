"""Sons importados pelo usuário, privados deste PC e fora dos pacotes."""
import base64
import binascii
import json
import os
import threading
from pathlib import Path

TIPOS = {'move', 'capture', 'castle', 'promotion', 'check', 'mate', 'draw', 'start', 'end'}
LIMITE = 1024 * 1024
_LOCK = threading.RLock()


def caminho():
    from emily_paths import arquivo_dados
    if os.name == 'nt' or os.getenv('EMILY_DATA_DIR', '').strip():
        return arquivo_dados('sons_xadrez_pessoais/pacote.json')
    return Path.home() / '.local/share/emily/sons_xadrez_pessoais/pacote.json'


def validar(arquivos):
    if not isinstance(arquivos, dict) or not set(arquivos) <= TIPOS:
        raise ValueError('Tipos de som inválidos.')
    for item in arquivos.values():
        if not isinstance(item, dict) or item.get('formato') not in {'mp3', 'wav', 'ogg'}:
            raise ValueError('Use arquivos MP3, WAV ou OGG.')
        conteudo = item.get('base64')
        if not isinstance(conteudo, str) or len(conteudo) > (LIMITE + 2) // 3 * 4:
            raise ValueError('Cada som deve ter no máximo 1 MB.')
        try:
            bruto = base64.b64decode(conteudo, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('Arquivo de áudio inválido.') from exc
        if not bruto or len(bruto) > LIMITE:
            raise ValueError('Arquivo vazio ou maior que 1 MB.')
        # A interface verifica a decodificação antes de importar. Não aceita
        # caminhos fornecidos pelo navegador nem executa conteúdo do arquivo.


def acao(operacao, dados=None, pasta=None):
    p = Path(pasta) if pasta is not None else caminho()
    with _LOCK:
        estado = {'personalizado': False, 'arquivos': {}}
        if p.is_file():
            try:
                if p.stat().st_size > 13 * LIMITE:
                    raise ValueError('Pacote muito grande.')
                estado = json.loads(p.read_text(encoding='utf-8'))
                validar(estado['arquivos'])
                estado['personalizado'] = bool(estado.get('personalizado'))
            except (ValueError, KeyError, TypeError):
                estado = {'personalizado': False, 'arquivos': {}}
        if operacao == 'ler':
            return {'ok': True, **estado}
        if operacao == 'importar':
            novos = (dados or {}).get('arquivos')
            validar(novos)
            if not novos:
                raise ValueError('Selecione pelo menos um som.')
            estado['arquivos'].update(novos)
            estado['personalizado'] = True
        elif operacao == 'selecionar':
            estado['personalizado'] = bool((dados or {}).get('personalizado')) and bool(estado['arquivos'])
        elif operacao == 'limpar':
            estado = {'personalizado': False, 'arquivos': {}}
        else:
            raise ValueError('Ação de som desconhecida.')
        p.parent.mkdir(parents=True, exist_ok=True)
        temp = p.with_suffix('.tmp')
        temp.write_text(json.dumps(estado), encoding='utf-8')
        os.replace(temp, p)
        return {'ok': True, **estado}

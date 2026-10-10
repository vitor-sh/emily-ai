"""Layout visual versionável; nunca executa código ou CSS arbitrário do documento."""
from __future__ import annotations
import base64
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time

TRAVA = threading.RLock()
MAX_BYTES = 4 * 1024 * 1024
PADRAO = {'version': 1, 'updated_at': 0, 'theme': {}, 'elements': {}, 'pages': []}
CORES = {'backgroundColor', 'color', 'borderColor'}
NUMEROS = {'width', 'height', 'minWidth', 'maxWidth', 'minHeight', 'maxHeight',
           'fontSize', 'borderRadius', 'borderWidth', 'padding', 'gap',
           'marginTop', 'marginRight', 'marginBottom', 'marginLeft', 'opacity',
           'order', 'flexGrow', 'x', 'y'}
ENUMS = {'textAlign': {'left', 'center', 'right'},
         'fontWeight': {'normal', 'bold', '400', '500', '600', '700'},
         'display': {'flex', 'grid', 'block', 'inline-flex'},
         'flexDirection': {'row', 'column', 'row-reverse', 'column-reverse'},
         'justifyContent': {'flex-start', 'center', 'flex-end', 'space-between', 'space-around'},
         'alignItems': {'stretch', 'flex-start', 'center', 'flex-end'},
         'gridTemplateColumns': {'1fr', '1fr 1fr', '1fr 1fr 1fr', '1fr 1fr 1fr 1fr'}}
TEMAS = {'--bg', '--bg-side', '--bg-raise', '--bg-hover', '--bg-active', '--txt',
         '--txt-2', '--txt-3', '--acento', '--acento-mo', '--line', '--line-forte', '--ok', '--aviso', '--erro'}
ACOES = {'none', 'inicio', 'nova_conversa', 'config', 'code', 'cloud', 'music',
         'navegador', 'xadrez', 'agente_visual', 'logs', 'ptt', 'captura', 'anexo', 'comando', 'pagina'}
TIPOS = {'text', 'button', 'image', 'divider', 'input', 'group'}


def _texto(valor, limite):
    if not isinstance(valor, str) or len(valor) > limite:
        raise ValueError('Texto inválido ou grande demais.')
    return valor


def _chave(valor):
    valor = _texto(valor, 350)
    if not re.fullmatch(r'[\w:|./@=-]+', valor, re.ASCII):
        raise ValueError('Identificador de elemento inválido.')
    if valor in {'id:btn-editor', 'id:editor-toolbar', 'id:editor-inspector', 'id:editor-outline'}:
        raise ValueError('Os controles do editor não podem ser alterados.')
    return valor


def _cor(valor):
    valor = _texto(valor, 9)
    if not re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?', valor):
        raise ValueError('Use uma cor hexadecimal.')
    return valor


def _imagem(valor):
    valor = _texto(valor, 400000)
    if not re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+', valor):
        raise ValueError('Imagem deve ser PNG, JPEG ou WebP importado.')
    bruto = base64.b64decode(valor.split(',', 1)[1], validate=True)
    from PIL import Image
    with Image.open(io.BytesIO(bruto)) as imagem:
        if imagem.format not in {'PNG', 'JPEG', 'WEBP'} or imagem.width * imagem.height > 1024 * 1024:
            raise ValueError('Formato ou tamanho de imagem não permitido.')
        imagem.verify()
    return valor


def _estilos(dados):
    if not isinstance(dados, dict):
        raise ValueError('Estilos inválidos.')
    saida = {}
    for nome, valor in dados.items():
        if nome in CORES:
            saida[nome] = _cor(valor)
        elif nome in NUMEROS:
            if isinstance(valor, bool) or not isinstance(valor, (float, int)) or not math.isfinite(valor):
                raise ValueError('Medida inválida.')
            minimo, maximo = (-3000, 3000) if nome in {'x', 'y'} or nome.startswith('margin') else (0, 3000)
            if nome == 'opacity': minimo, maximo = 0, 1
            if not minimo <= valor <= maximo:
                raise ValueError('Medida fora do intervalo.')
            saida[nome] = valor
        elif nome in ENUMS and valor in ENUMS[nome]:
            saida[nome] = valor
        else:
            raise ValueError('Propriedade visual não permitida: ' + str(nome))
    return saida


def _elemento(dado):
    if not isinstance(dado, dict) or set(dado) - {'label', 'tooltip', 'placeholder', 'icon', 'image', 'styles', 'parent', 'before', 'hidden'}:
        raise ValueError('Propriedades de elemento inválidas.')
    saida = {}
    for campo in {'label', 'tooltip', 'placeholder', 'icon'} & dado.keys():
        saida[campo] = _texto(dado[campo], 2000 if campo == 'label' else 300)
    if 'hidden' in dado:
        if not isinstance(dado['hidden'], bool): raise ValueError('Visibilidade inválida.')
        saida['hidden'] = dado['hidden']
    if 'image' in dado: saida['image'] = _imagem(dado['image'])
    if 'styles' in dado: saida['styles'] = _estilos(dado['styles'])
    for campo in {'parent', 'before'} & dado.keys():
        if dado[campo]: saida[campo] = _chave(dado[campo])
    return saida


def validar(dados):
    if not isinstance(dados, dict) or dados.get('version') != 1:
        raise ValueError('Versão de layout não suportada.')
    if set(dados) - {'version', 'updated_at', 'theme', 'elements', 'pages'}:
        raise ValueError('Campos de layout desconhecidos.')
    saida = copy.deepcopy(PADRAO)
    instante = dados.get('updated_at', 0)
    if isinstance(instante, bool) or not isinstance(instante, (int, float)) or not math.isfinite(instante) or instante < 0:
        raise ValueError('Data inválida.')
    saida['updated_at'] = instante
    tema = dados.get('theme', {})
    if not isinstance(tema, dict) or set(tema) - TEMAS: raise ValueError('Tema inválido.')
    saida['theme'] = {k: _cor(v) for k, v in tema.items()}
    elementos = dados.get('elements', {})
    if not isinstance(elementos, dict) or len(elementos) > 2000: raise ValueError('Elementos inválidos ou em excesso.')
    saida['elements'] = {_chave(k): _elemento(v) for k, v in elementos.items()}
    paginas = dados.get('pages', [])
    if not isinstance(paginas, list) or len(paginas) > 40: raise ValueError('Abas inválidas ou em excesso.')
    ids = set()
    for pagina in paginas:
        if not isinstance(pagina, dict) or set(pagina) - {'id', 'title', 'icon', 'items'}: raise ValueError('Aba inválida.')
        pid = _chave(pagina.get('id'))
        if not pid.startswith('custom:') or pid in ids: raise ValueError('ID de aba inválido ou duplicado.')
        ids.add(pid)
        itens = pagina.get('items', [])
        if not isinstance(itens, list) or len(itens) > 200: raise ValueError('Componentes em excesso.')
        nova = {'id': pid, 'title': _texto(pagina.get('title', 'Nova aba'), 100), 'icon': _texto(pagina.get('icon', '▦'), 40), 'items': []}
        for item in itens:
            if not isinstance(item, dict) or set(item) - {'id', 'type', 'label', 'action', 'value', 'styles', 'image', 'parent', 'placeholder', 'icon'}: raise ValueError('Componente inválido.')
            iid = _chave(item.get('id'))
            if not iid.startswith('custom:') or iid in ids or item.get('type') not in TIPOS: raise ValueError('ID ou tipo inválido.')
            ids.add(iid)
            acao = item.get('action', 'none')
            if acao not in ACOES: raise ValueError('Ação não permitida.')
            novo = {'id': iid, 'type': item['type'], 'label': _texto(item.get('label', ''), 2000), 'action': acao, 'value': _texto(item.get('value', ''), 2000), 'styles': _estilos(item.get('styles', {}))}
            if item.get('parent'): novo['parent'] = _chave(item['parent'])
            if item.get('image'): novo['image'] = _imagem(item['image'])
            for campo in {'placeholder', 'icon'} & item.keys(): novo[campo] = _texto(item[campo], 300)
            nova['items'].append(novo)
        # Um grupo só pode conter componentes da própria aba, sem ciclos.
        locais = {i['id']: i for i in nova['items']}
        for item in nova['items']:
            visitados = {item['id']}; pai = item.get('parent')
            while pai:
                if pai in visitados or pai not in locais or locais[pai]['type'] != 'group': raise ValueError('Grupo inválido ou circular.')
                visitados.add(pai);pai = locais[pai].get('parent')
        saida['pages'].append(nova)
    for key in saida['elements']:
        visitados = {key}; pai = saida['elements'][key].get('parent')
        while pai in saida['elements']:
            if pai in visitados: raise ValueError('Movimento circular de elementos.')
            visitados.add(pai);pai = saida['elements'][pai].get('parent')
    if len(json.dumps(saida, ensure_ascii=True).encode()) > MAX_BYTES: raise ValueError('Layout grande demais.')
    return saida


def revisao(documento):
    return hashlib.sha256(json.dumps(documento, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def destinos():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)).resolve()
    fontes = []
    for pai in [base, *list(base.parents)[:4]]:
        if (pai / 'interface_web.py').is_file() and (pai / 'web/index.html').is_file() and (pai / 'main.py').is_file():
            fontes.append(pai)
    runtime = base / 'web/editor-layout.json'
    dados = (Path(os.getenv('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'Emily' if os.name == 'nt' else Path.home() / '.local/share/emily') / 'editor-layout.json'
    alvos = [dados, runtime]
    for fonte in fontes:
        alvos.append(fonte / 'web/editor-layout.json')
        for instancia in [fonte / 'emily-windows-instance', fonte.parent / 'emily-windows-instance', fonte / 'emily-linux-instance']:
            if (instancia / 'web/index.html').is_file(): alvos.append(instancia / 'web/editor-layout.json')
        pacote = fonte / 'dist/Emily/_internal/web'
        if (pacote / 'index.html').is_file(): alvos.append(pacote / 'editor-layout.json')
    return list(dict.fromkeys(alvos)), fontes[-1] if fontes else None


def carregar():
    with TRAVA:
        candidatos = [];avisos = []
        alvos, fonte = destinos()
        for path in alvos:
            try:
                if path.is_file():
                    if path.stat().st_size > MAX_BYTES: raise ValueError('Arquivo grande demais.')
                    candidatos.append(validar(json.loads(path.read_text(encoding='utf-8'))))
            except (OSError, ValueError, TypeError) as exc: avisos.append(f'{path}: {exc}')
        documento = max(candidatos, key=lambda d: d['updated_at']) if candidatos else copy.deepcopy(PADRAO)
        return {'ok': True, 'document': documento, 'revision': revisao(documento), 'warnings': avisos, 'source_available': fonte is not None}


def _gravar(path, conteudo):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.editor-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as arq:
            arq.write(conteudo);arq.flush();os.fsync(arq.fileno())
        os.replace(temp, path)
        if os.name != 'nt':
            # Persistir também a troca do nome para resistir a queda de energia.
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory)
            finally: os.close(directory)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def publicar_windows(fonte):
    if fonte is None or os.name == 'nt':
        return {'ok': False, 'message': 'Layout local salvo. Publicação Windows disponível pelo projeto no Linux.'}
    try:
        from publicar_windows_codigo import publicar, DEST
        meta = json.loads((DEST / 'latest.json').read_text())
        files = ['android_editor.py', 'web/android-editor.html', 'web/android-editor.js', 'web/android-editor.css', 'web/editor-markdown.js', 'editor_assets.py', 'assets/editor/u2netp.onnx', 'assets/editor/third-party.html', 'editor_assistant.py', 'editor_interface.py', 'interface_web.py', 'web/index.html', 'web/app.js',
                 'web/editor-core.js', 'web/editor.js', 'web/editor.css', 'web/editor-layout.json',
                 'web/editor-controls.js', 'web/editor-panel.html', 'web/editor-panel.js', 'web/estilo.css', 'web/dark-controls.js', 'web/dark-controls.css']
        publicar(int(meta['version']) + 1, meta['installer'], root=fonte, selecionar=files)
        return {'ok': True, 'version': int(meta['version']) + 1, 'message': 'Atualização Windows publicada; aplicada ao buscar atualizações.'}
    except Exception as exc:
        return {'ok': False, 'message': 'Layout salvo, mas a publicação Windows falhou: ' + str(exc)}


def salvar(documento, revision, publicar=True):
    with TRAVA:
        novo = validar(documento)
        atual = carregar()
        if revision != atual['revision']:
            return {'ok': False, 'conflict': True, 'error': 'Outro processo alterou o layout. Exporte o rascunho e recarregue antes de salvar.'}
        novo['updated_at'] = max(time.time(), atual['document']['updated_at'] + .001)
        conteudo = json.dumps(novo, ensure_ascii=True, indent=2) + '\n'
        alvos, fonte = destinos();gravados = [];avisos = []
        for path in alvos:
            try: _gravar(path, conteudo);gravados.append(str(path))
            except OSError as exc: avisos.append(f'{path}: {exc}')
        if not gravados: return {'ok': False, 'error': 'Não foi possível gravar o layout.', 'warnings': avisos}
        resultado = {'ok': True, 'document': novo, 'revision': revisao(novo), 'saved': gravados, 'warnings': avisos}
        if publicar:
            if fonte and str(fonte / 'web/editor-layout.json') not in gravados:
                resultado['publication'] = {'ok': False, 'message': 'Publicação Windows adiada: o layout não foi gravado no projeto.'}
            else:
                resultado['publication'] = publicar_windows(fonte)
        return resultado


def importar_imagem(path):
    from PIL import Image, ImageOps
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert('RGBA');img.thumbnail((512, 512))
        buf = io.BytesIO();img.save(buf, format='PNG', optimize=False)
    dados = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
    return _imagem(dados)


def arquivo_rascunho():
    return destinos()[0][0].with_name('editor-draft.json')


def salvar_rascunho(documento, base_revision):
    documento = validar(documento)
    if not isinstance(base_revision, str) or len(base_revision) > 100:
        raise ValueError('Revisão de rascunho inválida.')
    with TRAVA:
        path = arquivo_rascunho()
        envelope = {'version': 1, 'base_revision': base_revision, 'saved_at': time.time(), 'document': documento}
        _gravar(path, json.dumps(envelope, ensure_ascii=True))
        return {'ok': True, 'saved_at': envelope['saved_at']}


def carregar_rascunho():
    with TRAVA:
        path = arquivo_rascunho()
        if not path.exists(): return {'ok': True, 'draft': None}
        try:
            if path.stat().st_size > MAX_BYTES + 1000: raise ValueError('Rascunho grande demais.')
            d = json.loads(path.read_text(encoding='utf-8'))
            d['document'] = validar(d['document'])
            return {'ok': True, 'draft': d}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {'ok': False, 'error': 'Não consegui recuperar o rascunho: ' + str(exc)}


def limpar_rascunho():
    # Esvaziar atomicamente evita disputa entre leitura e unlink no Windows.
    with TRAVA:
        path = arquivo_rascunho()
        if path.exists(): _gravar(path, json.dumps({'version':1, 'base_revision':'', 'saved_at':0, 'document':PADRAO}))
    return {'ok': True}

"""Apoio UCI local e limitado. Binário oficial isolado, fora do instalador.

O download é feito uma vez por PC, validado por SHA256. Não exige python-chess.
Stockfish é GPLv3; o pacote oficial preserva licença e fontes do fornecedor.
"""
from __future__ import annotations
import hashlib
import copy
import io
import os
import platform
import queue
import re
import subprocess
import tarfile
import threading
import time
from pathlib import Path
from zipfile import ZipFile

VERSAO = 'sf_19'
PACOTES = {
    'Linux': ('stockfish-linux-x86-64-universal.tar.gz', '9defc0d4e55d49c65a6d042f3e571a39fcea499ade6dbe741b53b8c65e03611f'),
    'Windows': ('stockfish-windows-x86-64-universal.zip', '3c8bf1f9ea66a09350a40df4f632288285ac206d99f33ab5842c408fc30b48a7'),
}
PERFIS = {'casual': (0, 150, 100), 'equilibrado': (4, 250, 60), 'desafiador': (9, 400, 25)}
_lock_download = threading.Lock()


def pasta():
    from emily_paths import arquivo_dados
    if platform.system() == 'Linux' and not os.getenv('EMILY_DATA_DIR'):
        return Path(os.getenv('XDG_DATA_HOME') or Path.home()/'.local/share') / 'emily/motores_xadrez' / VERSAO
    return Path(arquivo_dados('motores_xadrez')) / VERSAO


def preparar(avisar=lambda s: None, cancelado=lambda: False):
    sistema = platform.system()
    if sistema not in PACOTES or platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise ValueError('O apoio do Stockfish requer Linux ou Windows de 64 bits. Escolha “Sem apoio do Stockfish” neste PC.')
    raiz = pasta(); exe = raiz / ('stockfish.exe' if sistema == 'Windows' else 'stockfish')
    with _lock_download:
        if exe.is_file():
            return exe
        import requests
        nome, digest = PACOTES[sistema]
        avisar('Preparando Stockfish: baixando o motor oficial pela primeira vez…')
        buf = io.BytesIO(); inicio = time.monotonic()
        with requests.get(f'https://github.com/official-stockfish/Stockfish/releases/download/{VERSAO}/{nome}',
                          stream=True, timeout=(10, 30)) as r:
            r.raise_for_status()
            for bloco in r.iter_content(1024 * 1024):
                if cancelado():
                    raise ValueError('A partida mudou durante a preparação do motor.')
                if time.monotonic()-inicio > 120 or buf.tell()+len(bloco) > 110_000_000:
                    raise ValueError('O download do motor demorou demais. Tente novamente.')
                buf.write(bloco)
        conteudo = buf.getvalue()
        if hashlib.sha256(conteudo).hexdigest() != digest:
            raise ValueError('O pacote do Stockfish não passou na verificação. Nenhum motor foi executado.')
        raiz.mkdir(parents=True, exist_ok=True)
        # Selecionar arquivos explicitamente: nunca extrair caminhos arbitrários.
        if sistema == 'Windows':
            with ZipFile(io.BytesIO(conteudo)) as z:
                candidatos = [n for n in z.namelist() if n.lower().endswith('.exe') and 'stockfish' in Path(n).name.lower()]
                if len(candidatos) != 1: raise ValueError('Pacote do motor inesperado.')
                binario = z.read(candidatos[0])
        else:
            with tarfile.open(fileobj=io.BytesIO(conteudo), mode='r:gz') as t:
                candidatos = [m for m in t.getmembers() if m.isfile() and Path(m.name).name.startswith('stockfish-') and '.' not in Path(m.name).name]
                if len(candidatos) != 1: raise ValueError('Pacote do motor inesperado.')
                binario = t.extractfile(candidatos[0]).read()
        (raiz / nome).write_bytes(conteudo)  # Preserva pacote oficial, incluindo sua licença.
        temp = exe.with_suffix('.tmp'); temp.write_bytes(binario); temp.chmod(0o700); temp.replace(exe)
        return exe


def analisar(exe, fen, skill, millis, cancelado=lambda: False, restritos=None):
    if len(fen) > 150 or len(fen.split()) != 6 or '\n' in fen or '\r' in fen:
        raise ValueError('Posição inválida para o motor.')
    if restritos is not None and (not restritos or any(not re.fullmatch(r'[a-h][1-8][a-h][1-8][qrbn]?', u) for u in restritos)):
        raise ValueError('Lances inválidos para a análise restrita.')
    proc = subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    linhas = queue.Queue()
    def ler():
        for line in proc.stdout: linhas.put(line.strip())
        linhas.put(None)
    reader=threading.Thread(target=ler, daemon=True);reader.start()
    def enviar(cmd): proc.stdin.write(cmd+'\n'); proc.stdin.flush()
    def aguardar(prefixo, scores=None):
        fim = time.monotonic()+15
        while time.monotonic() < fim:
            if cancelado(): raise ValueError('A partida mudou durante a análise.')
            try: line = linhas.get(timeout=.1)
            except queue.Empty: continue
            if line is None: raise ValueError('O motor de xadrez encerrou inesperadamente.')
            if scores is not None:
                m = re.search(r'multipv (\d+).*?score (cp|mate) (-?\d+).*? pv ((?:[a-h][1-8][a-h][1-8][qrbn]?\s*)+)', line)
                if m and 'bound' not in line:
                    valor = int(m[3]); cp = valor if m[2]=='cp' else (100000-abs(valor) if valor>0 else -100000+abs(valor))
                    pv = m[4].split()[:4]
                    scores[int(m[1])] = {'uci':pv[0], 'cp':cp, 'pv':pv}
            if line.startswith(prefixo): return line
        raise ValueError('O motor não respondeu a tempo. Seu tabuleiro está preservado.')
    try:
        enviar('uci'); aguardar('uciok')
        enviar('setoption name Threads value 1'); enviar('setoption name Hash value 32')
        enviar(f'setoption name Skill Level value {skill}'); enviar(f'setoption name MultiPV value {min(256,len(restritos)) if restritos else 6}')
        enviar('isready'); aguardar('readyok')
        enviar('position fen '+fen); enviar(f'go movetime {millis}'+(' searchmoves '+' '.join(restritos) if restritos else ''))
        scores={}; linha=aguardar('bestmove',scores)
        return linha.split()[1], list(scores.values())
    finally:
        proc.kill(); proc.wait(timeout=3)
        reader.join(1);proc.stdin.close();proc.stdout.close()


def consultar(posicao, nivel, avisar=lambda s:None, cancelado=lambda:False):
    skill, millis, margem = PERFIS[nivel]
    exe=preparar(avisar,cancelado); avisar('Stockfish conferindo opções para a Emily…')
    escolhido, scores=analisar(exe,posicao['fen'],skill,millis,cancelado)
    legais={m['uci'] for m in posicao['legais']}; scores=[m for m in scores if m['uci'] in legais]
    if not scores or escolhido not in legais: raise ValueError('O motor não devolveu opções legais. Tente novamente.')
    melhor=max(m['cp'] for m in scores)
    ancora=next((m['cp'] for m in scores if m['uci']==escolhido),melhor)
    alvo=max(ancora,melhor-margem)
    candidatos=[m['uci'] for m in scores if m['cp']>=melhor-margem and abs(m['cp']-alvo)<=40]
    if not candidatos: candidatos=[max(scores,key=lambda m:m['cp'])['uci']]
    avaliacao=None
    anterior=posicao.get('fatos',{}).get('fen_antes_ultimo_lance')
    if anterior:
        _, antes=analisar(exe,anterior,20,150,cancelado)
        if antes and abs(melhor)<90000:
            anterior_cp=max(m['cp'] for m in antes)
            if abs(anterior_cp)<90000:
                avaliacao={'origem':'Stockfish, análise curta e estimada', 'perda_estimada_cp':max(0,anterior_cp+melhor),
                           'ator':posicao['fatos'].get('ultimos_lances',[{}])[-1].get('ator')}
    return {'candidatos':candidatos, 'nivel':nivel, 'skill':skill, 'avaliacao':avaliacao,
            'descricao':'Opções verificadas pelo Stockfish com dificuldade limitada; você escolhe o lance.'}


_cache_conversa = {}
_lock_conversa = threading.Lock()


def contexto_conversa(posicao, cancelado=lambda: False):
    """Linha curta para compreensão, sem alterar a dificuldade dos lances.

    Só usa o motor já instalado: conversar nunca dispara download. Cada
    sequência é uma possibilidade calculada, não uma promessa sobre o jogo.
    """
    fen = posicao['fen']
    if posicao.get('fim') or cancelado():
        return None
    with _lock_conversa:
        if fen in _cache_conversa:
            return copy.deepcopy(_cache_conversa[fen])
    exe = pasta() / ('stockfish.exe' if platform.system() == 'Windows' else 'stockfish')
    if not exe.is_file() or posicao.get('fim') or cancelado():
        return None
    inicio = time.monotonic()
    limite = lambda: cancelado() or time.monotonic() - inicio > 4
    _, scores = analisar(exe, fen, 20, 200, limite)
    legais = {m['uci'] for m in posicao['legais']}
    capturas = {m.get('uci') or (m['de']+m['para'])
                for m in posicao.get('fatos',{}).get('tatico',{}).get('capturas_legais_agora', [])}
    capturas &= legais
    avaliadas = {m['uci']:m for m in scores if m['uci'] in legais}
    comparadas = avaliadas
    # Uma captura envenenada pode ficar fora das seis melhores opções.
    # Inclui todas as capturas e a melhor alternativa na mesma análise.
    if capturas - avaliadas.keys() and avaliadas:
        ancora = max(avaliadas.values(),key=lambda m:m['cp'])['uci']
        try:
            _, extras = analisar(exe, fen, 20, 250, limite,
                restritos=sorted(capturas | {ancora}))
            extras_validos = {m['uci']:m for m in extras if m['uci'] in legais}
            if ancora in extras_validos:
                comparadas = extras_validos
            # Sem a alternativa de referência, não chamar uma captura ruim de boa.
        except ValueError:
            pass  # Mantém a análise inicial; não inventa avaliação ausente.
    melhor = max((m['cp'] for m in comparadas.values()),default=0)
    riscos = [{'uci':u, 'perda_estimada_cp':max(0,melhor-comparadas[u]['cp']),
               'linha_apos_captura':comparadas[u].get('pv',[]),
               'qualidade':'perda relevante estimada' if melhor-comparadas[u]['cp']>=150 else 'sem perda relevante nesta análise curta'}
              for u in sorted(capturas & comparadas.keys())]
    linhas = [m['pv'] for m in sorted(scores, key=lambda m:m['cp'], reverse=True)
              if m['uci'] in legais and m.get('pv')][:3]
    if not linhas:
        return None
    resultado = {'fen_base':fen, 'turno':posicao['turno'], 'linhas_uci':linhas,
                 'avaliacoes_capturas':riscos, 'capturas_sem_avaliacao':sorted(capturas-comparadas.keys()),
                 'nota':'Stockfish, análise curta: até quatro jogadas individuais por linha. '
                        'São variantes possíveis, não uma sequência forçada nem garantia. '
                        'Cada linha parte do FEN indicado, com alternância de cores. '
                        'Não controla a dificuldade nem escolhe o lance da Emily.'}
    with _lock_conversa:
        if len(_cache_conversa) >= 32:
            _cache_conversa.pop(next(iter(_cache_conversa)))
        _cache_conversa[fen] = resultado
    return copy.deepcopy(resultado)

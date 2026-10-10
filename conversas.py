"""
conversas.py — o histórico de conversas da interface, uma por chat.

O PEDIDO
────────
"quero que adicione o sistema de chats ali, igual funciona no GPT, claude...
que cada historico fica salvo em cada chat e eu consigo abrir"

TRÊS DECISÕES QUE IMPORTAM
──────────────────────────
1. GRAVAÇÃO ATÔMICA. Escreve num arquivo temporário e só então substitui o
   original (os.replace). Não é preciosismo: isto é o histórico de conversa do
   Vitor, e o programa fecha por Ctrl+C, por crash de driver de áudio e pelo
   atexit. Gravar direto no arquivo final deixa uma janela em que um fechamento
   no meio da escrita corta o JSON e apaga TODAS as conversas de uma vez. O
   replace é atômico no Windows e no Linux.

2. ID E TÍTULO SÃO SEPARADOS. O título vem da primeira mensagem e pode ser
   trocado; o id nunca muda. Título como chave quebraria no primeiro "renomeia
   essa conversa", e duas conversas começadas com a mesma frase colidiriam.

3. TETO EM CONVERSA E EM MENSAGEM. Sem teto, o arquivo cresce pra sempre e a
   interface passa a carregar megabytes no boot. A conversa mais velha sai
   quando estoura, que é o comportamento de qualquer app de chat.

O QUE ESTE MÓDULO NÃO FAZ
─────────────────────────
Não fala com o modelo e não sabe o que é contexto de LLM. Ele guarda e devolve
texto. Quem decide reconstruir o contexto da Emily ao abrir uma conversa antiga
é a interface, chamando o modelo.py — separado de propósito, porque assim este
arquivo dá pra testar sem subir nada.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlsplit

# Fica na casa do usuário, não na pasta do projeto: é dado dele, e não deve
# entrar no repositório nem ser apagado num git clean.
ARQUIVO = Path(os.getenv("EMILY_ARQUIVO_CONVERSAS",
                         str(Path.home() / ".emily_conversas.json")))

# Quantas conversas guardar. Passando disso, a mais antiga sai.
MAX_CONVERSAS = int(os.getenv("EMILY_MAX_CONVERSAS", "80"))

# Quantas mensagens por conversa. Conversa de voz longa pode passar de mil.
MAX_MENSAGENS = int(os.getenv("EMILY_MAX_MENSAGENS_CONVERSA", "400"))

# Tamanho do título derivado da primeira mensagem.
MAX_TITULO = 46

_lock = threading.RLock()
_cache: Optional[dict] = None
_cache_id: tuple[str, int] | None = None


@contextmanager
def _bloqueio_entre_processos():
    """Serializa edições da janela e do gateway no mesmo histórico."""
    trava_path = ARQUIVO.with_name(ARQUIVO.name + ".lock")
    trava_path.parent.mkdir(parents=True, exist_ok=True)
    with trava_path.open("a+b") as trava:
        if os.name == "nt":
            import msvcrt
            if trava.tell() == 0:
                trava.write(b"0")
                trava.flush()
            trava.seek(0)
            msvcrt.locking(trava.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                trava.seek(0)
                msvcrt.locking(trava.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(trava.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(trava.fileno(), fcntl.LOCK_UN)


def _id_arquivo() -> tuple[str, int]:
    try:
        return str(ARQUIVO), ARQUIVO.stat().st_mtime_ns
    except OSError:
        return str(ARQUIVO), -1


def _log(msg: str) -> None:
    print(f"[CONVERSAS] {msg}")


# ═════════════════════════════════════════════════════════════════
# DISCO
# ═════════════════════════════════════════════════════════════════

def _vazio() -> dict:
    return {"versao": 1, "conversas": []}


def _carregar() -> dict:
    global _cache, _cache_id
    with _lock:
        arquivo_id = _id_arquivo()
        if _cache is not None and _cache_id == arquivo_id:
            return _cache
        try:
            with open(ARQUIVO, encoding="utf-8") as f:
                dados = json.load(f)
            if not isinstance(dados, dict) or "conversas" not in dados:
                raise ValueError("formato inesperado")
            if not isinstance(dados["conversas"], list):
                raise ValueError("conversas não é lista")
            _cache = dados
        except FileNotFoundError:
            _cache = _vazio()
        except (json.JSONDecodeError, ValueError, OSError) as e:
            # Arquivo corrompido não pode impedir a Emily de abrir. Renomeia pra
            # o Vitor poder olhar depois e começa limpo — perder o histórico é
            # ruim, não abrir é pior.
            _log(f"não consegui ler o histórico ({e}); começando limpo")
            try:
                if ARQUIVO.exists():
                    ARQUIVO.replace(ARQUIVO.with_suffix(".quebrado.json"))
                    _log(f"o arquivo velho ficou em "
                         f"{ARQUIVO.with_suffix('.quebrado.json').name}")
            except OSError:
                pass
            _cache = _vazio()
        _cache_id = _id_arquivo()
        return _cache


def _salvar() -> None:
    """Grava atômico: temporário + replace. Ver a decisão 1 no topo."""
    global _cache_id
    with _lock:
        dados = _cache if _cache is not None else _carregar()
        tmp = ARQUIVO.with_suffix(".tmp")
        try:
            ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, ARQUIVO)
            _cache_id = _id_arquivo()
        except OSError as e:
            _log(f"não consegui gravar: {e}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


def recarregar() -> None:
    """Joga o cache fora. Só pra teste e pra quem editar o arquivo à mão."""
    global _cache, _cache_id
    with _lock:
        _cache = None
        _cache_id = None


# ═════════════════════════════════════════════════════════════════
# TÍTULO
# ═════════════════════════════════════════════════════════════════

def titulo_de(texto: str) -> str:
    """
    Título a partir da primeira mensagem.

    Corta em espaço, não no meio da palavra: "analisa a pasta de mo…" fica pior
    que "analisa a pasta de…" e custa a mesma coisa fazer certo.
    """
    limpo = re.sub(r"\s+", " ", (texto or "").strip())
    limpo = re.sub(r"^@?emily[,:\s]+", "", limpo, flags=re.IGNORECASE).strip()
    if not limpo:
        return "Conversa nova"
    if len(limpo) <= MAX_TITULO:
        return limpo
    corte = limpo[:MAX_TITULO]
    if " " in corte:
        corte = corte[:corte.rindex(" ")]
    return corte.rstrip(".,;:!?-") + "…"


# ═════════════════════════════════════════════════════════════════
# API
# ═════════════════════════════════════════════════════════════════

def criar(primeira: str = "") -> str:
    """Abre uma conversa nova e devolve o id."""
    with _lock, _bloqueio_entre_processos():
        dados = _carregar()
        cid = uuid.uuid4().hex[:12]
        agora = time.time()
        dados["conversas"].append({
            "id": cid,
            "titulo": titulo_de(primeira),
            "criada": agora,
            "mexida": agora,
            "ramo": 0,
            "mensagens": [],
        })
        # Poda pela data em que foi MEXIDA, não pela de criação: conversa antiga
        # que o Vitor continua usando não deve morrer por idade.
        if len(dados["conversas"]) > MAX_CONVERSAS:
            dados["conversas"].sort(key=lambda c: c.get("mexida", 0))
            del dados["conversas"][:len(dados["conversas"]) - MAX_CONVERSAS]
        _salvar()
        return cid


def _achar(cid: str) -> Optional[dict]:
    for c in _carregar()["conversas"]:
        if c.get("id") == cid:
            return c
    return None


def _fontes_validas(fontes) -> List[dict]:
    """Guarda apenas links web curtos; dados de pesquisa não viram prompt."""
    saida = []
    vistos = set()
    for item in fontes if isinstance(fontes, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()[:1000]
        try:
            partes = urlsplit(url)
        except ValueError:
            continue
        if (partes.scheme not in {"https", "http"} or not partes.hostname
                or partes.username or partes.password or url in vistos):
            continue
        vistos.add(url)
        saida.append({"titulo": str(item.get("titulo") or partes.hostname)[:160],
                      "url": url})
        if len(saida) >= 16:
            break
    return saida


def acrescentar(cid: str, papel: str, texto: str, fontes=None,
               requisicao_id: str = "", anexos=None) -> Optional[int]:
    """Guarda uma mensagem. papel = 'user' ou 'emily'."""
    if not cid or not texto or not texto.strip():
        return
    with _lock, _bloqueio_entre_processos():
        c = _achar(cid)
        if c is None:
            return
        mensagem = {
            "papel": "emily" if papel == "emily" else "user",
            "texto": texto,
            "quando": time.time(),
        }
        if papel == "user" and anexos:
            mensagem["anexos"] = [str(a) for a in anexos if isinstance(a, str)][:10]
        if papel == "user" and requisicao_id:
            mensagem["requisicao_id"] = str(requisicao_id)[:80]
        fontes_ok = _fontes_validas(fontes) if papel == "emily" else []
        if fontes_ok:
            mensagem["fontes"] = fontes_ok
        c["mensagens"].append(mensagem)
        if papel == "user":
            anterior = c.get("turno_pendente")
            if _pendencia_e_tarefa(anterior):
                c["turno_para_retomada"] = anterior
            else:
                c.pop("turno_para_retomada", None)
            # Gravado junto do pedido: um crash antes da primeira ferramenta
            # ainda deixa visível a tarefa que ficou sem resposta.
            c["turno_pendente"] = {
                "pedido": texto[:500], "passo": "Preparando a resposta",
                "situacao": "em andamento", "conferir_acao": False,
                "quando": time.time(), "etapas": [], "tarefa": False,
            }
        elif papel == "emily":
            c.pop("turno_pendente", None)
            c.pop("turno_para_retomada", None)
        # Preserve o original inteiro; o contexto de inferência é compactado separadamente.
        c["mexida"] = max(time.time(), float(c.get("mexida", 0)) + 0.001)
        # Conversa criada sem primeira mensagem (o Vitor clicou "Novo" e só
        # depois escreveu) ganha o título aqui.
        if c.get("titulo") in ("", "Conversa nova") and papel == "user":
            c["titulo"] = titulo_de(texto)
        _salvar()
        return len(c["mensagens"]) - 1


def localizar_requisicao(requisicao_id: str) -> Optional[str]:
    """Reconcilia envios cujo ACK da ponte JavaScript se perdeu."""
    chave = str(requisicao_id or "")[:80]
    if not chave:
        return None
    with _lock:
        for c in _carregar()["conversas"]:
            if any(m.get("requisicao_id") == chave for m in c.get("mensagens", [])):
                return c.get("id")
    return None


def turno_pendente(cid: str) -> Optional[dict]:
    """Ponto seguro para o usuário decidir após fechamento inesperado."""
    with _lock:
        c = _achar(cid)
        pendente = (c or {}).get("turno_pendente")
        return dict(pendente) if isinstance(pendente, dict) else None


def _pendencia_e_tarefa(pendente: object) -> bool:
    """Só ações reais ganham o aviso de tarefa interrompida no chat."""
    return bool(isinstance(pendente, dict) and (
        pendente.get("tarefa") or pendente.get("etapas")
        or pendente.get("conferir_acao")
        or pendente.get("passo") == "Regenerando a resposta"
    ))


def turno_pendente_visivel(cid: str) -> Optional[dict]:
    pendente = turno_pendente(cid)
    return pendente if _pendencia_e_tarefa(pendente) else None


def contexto_retomada(cid: str) -> str:
    """Resumo factual dos passos antes do crash, sem fingir que deram certo."""
    with _lock:
        c = _achar(cid)
        ponto = (c or {}).get("turno_para_retomada")
        if not isinstance(ponto, dict):
            return ""
        linhas = [f"Pedido interrompido: {ponto.get('pedido', '')[:500]}"]
        for etapa in ponto.get("etapas", [])[-12:]:
            linhas.append(
                f"- {etapa.get('nome', 'Ferramenta')}: "
                f"{etapa.get('situacao', 'resultado não confirmado')} "
                f"{etapa.get('resultado', '')[:500]}")
        if ponto.get("conferir_acao"):
            linhas.append("A última ação pode ter acontecido; confirme o estado antes de repetir.")
        return "\n".join(linhas)


def atualizar_turno_pendente(cid: str, *, passo: str = "", situacao: str = "",
                             conferir_acao: Optional[bool] = None,
                             etapa: Optional[dict] = None,
                             tarefa: bool = False) -> None:
    if not cid:
        return
    with _lock, _bloqueio_entre_processos():
        c = _achar(cid)
        pendente = (c or {}).get("turno_pendente")
        if not isinstance(pendente, dict):
            return
        if tarefa or etapa:
            pendente["tarefa"] = True
        if passo:
            pendente["passo"] = passo[:160]
        if situacao:
            pendente["situacao"] = situacao[:120]
        if conferir_acao is not None:
            pendente["conferir_acao"] = bool(conferir_acao)
        if etapa:
            etapas = pendente.setdefault("etapas", [])
            nome = str(etapa.get("nome") or "Ferramenta")[:100]
            if etapa.get("iniciar"):
                etapas.append({"nome": nome, "situacao": "resultado não confirmado"})
                del etapas[:-12]
            else:
                alvo = next((e for e in reversed(etapas)
                             if e.get("nome") == nome
                             and e.get("situacao") == "resultado não confirmado"), None)
                if alvo is None:
                    alvo = {"nome": nome}
                    etapas.append(alvo)
                    del etapas[:-12]
                alvo["situacao"] = str(etapa.get("situacao") or "resultado recebido")[:100]
                alvo["resultado"] = str(etapa.get("resultado") or "")[:500]
        pendente["quando"] = time.time()
        _salvar()


def dispensar_turno_pendente(cid: str) -> bool:
    with _lock, _bloqueio_entre_processos():
        c = _achar(cid)
        if not c or "turno_pendente" not in c:
            return False
        del c["turno_pendente"]
        _salvar()
        return True


def listar() -> List[dict]:
    """Metadados das conversas, da mexida mais recente pra mais antiga."""
    with _lock:
        saida = [
            {"id": c["id"], "titulo": c.get("titulo") or "Conversa",
             "criada": c.get("criada", 0), "mexida": c.get("mexida", 0),
             "ramo": int(c.get("ramo", 0)),
             "pendente": _pendencia_e_tarefa(c.get("turno_pendente")),
             "quantas": len(c.get("mensagens", []))}
            for c in _carregar()["conversas"] if c.get("id")
        ]
    saida.sort(key=lambda c: -c["mexida"])
    return saida


def abrir(cid: str) -> List[dict]:
    """As mensagens de uma conversa. Lista vazia se não existir."""
    with _lock:
        c = _achar(cid)
        return list(c.get("mensagens", [])) if c else []


def truncar_para_regenerar(cid: str, indice: int) -> Optional[dict]:
    """Volta a conversa ao pedido que gerou uma resposta salva.

    O índice é da lista persistida, não da posição visual na tela. A operação
    remove a resposta escolhida e tudo abaixo dela antes da nova geração.
    """
    with _lock, _bloqueio_entre_processos():
        c = _achar(cid)
        mensagens = c.get("mensagens", []) if c else []
        if not isinstance(indice, int) or isinstance(indice, bool) or not 0 <= indice < len(mensagens):
            return None
        if mensagens[indice].get("papel") != "emily":
            return None
        usuario = next((i for i in range(indice - 1, -1, -1)
                        if mensagens[i].get("papel") == "user"), None)
        if usuario is None:
            return None
        pedido = str(mensagens[usuario].get("texto") or "").strip()
        if not pedido:
            return None
        del mensagens[usuario + 1:]
        c["turno_pendente"] = {
            "pedido": pedido[:500], "passo": "Regenerando a resposta",
            "situacao": "em andamento", "conferir_acao": False,
            "quando": time.time(), "etapas": [], "tarefa": True,
        }
        c["ramo"] = int(c.get("ramo", 0)) + 1
        c["mexida"] = max(time.time(), float(c.get("mexida", 0)) + 0.001)
        _salvar()
        return {"pedido": pedido, "mensagens": list(mensagens),
                "indice_usuario": usuario, "ramo": c["ramo"]}


def restaurar_regeneracao_falha(cid: str, indice_usuario: int,
                               ramo: int, originais: List[dict]) -> bool:
    """Desfaz um corte se o turno terminou sem resposta, preservando a sync."""
    with _lock, _bloqueio_entre_processos():
        c = _achar(cid)
        if c is None or int(c.get("ramo", 0)) != ramo:
            return False
        atual = c.get("mensagens", [])
        if atual != originais[:indice_usuario + 1]:
            return False  # alguém já respondeu/editou; não sobrescrever
        c["mensagens"] = list(originais)
        c.pop("turno_pendente", None)
        c.pop("turno_para_retomada", None)
        c["ramo"] = ramo + 1
        c["mexida"] = max(time.time(), float(c.get("mexida", 0)) + 0.001)
        _salvar()
        return True


def renomear(cid: str, titulo: str) -> bool:
    novo = re.sub(r"\s+", " ", (titulo or "").strip())[:120]
    if not novo:
        return False
    with _lock, _bloqueio_entre_processos():
        c = _achar(cid)
        if c is None:
            return False
        c["titulo"] = novo
        c["mexida"] = max(time.time(), float(c.get("mexida", 0)) + 0.001)
        _salvar()
        return True


def renomear_se_titulo(cid: str, esperado: str, titulo: str) -> bool:
    """Atualiza um título automático sem sobrescrever renomeações concorrentes."""
    novo = re.sub(r"\s+", " ", (titulo or "").strip())[:120]
    if not novo:
        return False
    with _lock, _bloqueio_entre_processos():
        c = _achar(cid)
        if c is None or c.get("titulo") != esperado:
            return False
        c["titulo"] = novo
        c["mexida"] = max(time.time(), float(c.get("mexida", 0)) + 0.001)
        _salvar()
        return True


def apagar(cid: str) -> bool:
    with _lock, _bloqueio_entre_processos():
        dados = _carregar()
        antes = len(dados["conversas"])
        excluida = next((c for c in dados["conversas"] if c.get("id") == cid), None)
        dados["conversas"] = [c for c in dados["conversas"]
                              if c.get("id") != cid]
        if len(dados["conversas"]) == antes:
            return False
        # TOMBSTONE de sincronizacao: quem apagou, quando. O celular (e
        # qualquer interface) usa isso pra apagar a mesma conversa do lado dele.
        apagadas = dados.setdefault("apagadas", {})
        apagadas[cid] = max(time.time(), float((excluida or {}).get("mexida", 0)) + 0.001)
        # Tombstone velho nao serve pra nada: 30 dias e fora.
        limite = time.time() - 30 * 24 * 3600
        for velho in [k for k, v in apagadas.items() if v < limite]:
            del apagadas[velho]
        _salvar()
        return True


def vazia(cid: str) -> bool:
    """
    True se a conversa não tem mensagem nenhuma.

    Serve pra a interface não deixar rastro: clicar 'Novo' e não escrever nada
    não deve criar uma linha vazia na lista.
    """
    c = _achar(cid)
    return c is None or not c.get("mensagens")


def para_o_modelo(cid: str) -> List[dict]:
    """
    As mensagens no formato de histórico do modelo.py.

    Existe aqui, e não no modelo.py, porque quem sabe o formato guardado é este
    arquivo. O modelo só recebe uma lista de {role, content} e não precisa saber
    que existe um arquivo de conversas.
    """
    saida = []
    for m in abrir(cid):
        texto = (m.get("texto") or "").strip()
        if not texto:
            continue
        saida.append({
            "role": "assistant" if m.get("papel") == "emily" else "user",
            "content": texto,
        })
    return saida


# ════════════════════════════════════════════════════════════════
# SINCRONIZACAO COM O CELULAR
#
# Tombstones de exclusao + upsert de conversa vinda de fora.
# Quem usa: servidor.py nas rotas /chats/* da ponte com o app.
# ════════════════════════════════════════════════════════════════

def listar_apagadas() -> List[dict]:
    """Tombstones de exclusao: [{id, quando}]. Pra o outro lado saber o que apagar."""
    with _lock:
        dados = _carregar()
        return [{"id": k, "quando": v} for k, v in dados.get("apagadas", {}).items()]


def gravar_externa(cid: str, titulo: str, criada: float, mexida: float,
                   mensagens: List[dict], ramo: int = 0) -> bool:
    """
    Upsert de uma conversa vinda de fora (sincronizacao com o celular).

    Recebe a conversa JA no formato interno ({papel, texto, quando}), com o id
    de quem criou. Grava so se [mexida] nao for mais antiga do que a que ja
    existe aqui (last-write-wins: quem mexeu por ultimo vence a conversa
    inteira). Recriar uma conversa apagada limpa o tombstone dela.
    """
    if not cid:
        return False
    if not isinstance(ramo, int) or isinstance(ramo, bool) or ramo < 0:
        return False
    with _lock, _bloqueio_entre_processos():
        dados = _carregar()
        apagada_em = float(dados.get("apagadas", {}).get(cid, 0) or 0)
        if apagada_em and apagada_em >= float(mexida or 0):
            return False
        atual = _achar(cid)
        ramo_atual = int(atual.get("ramo", 0)) if atual else 0
        if atual is not None and (ramo < ramo_atual or
                (ramo == ramo_atual and float(atual.get("mexida", 0)) >= float(mexida or 0))):
            return False   # o PC esta mais novo; quem mandou e que precisa baixar
        nova = {
            "id": cid,
            "titulo": re.sub(r"\s+", " ", (titulo or "").strip())[:120] or "Conversa",
            "criada": float(criada or time.time()),
            "mexida": (max(float(mexida or 0), time.time(),
                           float(atual.get("mexida", 0)) + 0.001)
                       if atual is not None and ramo > ramo_atual
                       else float(mexida or time.time())),
            "ramo": ramo,
            "mensagens": [],
        }
        fontes_anteriores = {
            (m.get("papel"), m.get("texto"), m.get("quando")): m.get("fontes")
            for m in (atual or {}).get("mensagens", [])
            if m.get("fontes")
        }
        for m in mensagens:
            if not isinstance(m, dict):
                continue
            texto = str(m.get("texto") or "").strip()
            if not texto:
                continue
            mensagem = {
                # celular manda "assistant"; formato interno usa "emily"
                "papel": "emily" if m.get("papel") in ("emily", "assistant") else "user",
                "texto": texto,
                "quando": float(m.get("quando") or 0),
            }
            if mensagem["papel"] == "emily":
                fontes = _fontes_validas(
                    m.get("fontes") or fontes_anteriores.get(
                        (mensagem["papel"], texto, mensagem["quando"])))
                if fontes:
                    mensagem["fontes"] = fontes
            nova["mensagens"].append(mensagem)
        # Sincronização também preserva o histórico completo.
        outros = [c for c in dados["conversas"] if c.get("id") != cid]
        outros.append(nova)
        outros.sort(key=lambda c: c.get("mexida", 0), reverse=True)
        dados["conversas"] = outros[:MAX_CONVERSAS]
        dados.get("apagadas", {}).pop(cid, None)
        _salvar()
        return True


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
# ═════════════════════════════════════════════════════════════════

def _diagnosticar() -> int:
    print("=" * 66)
    print("  CONVERSAS")
    print("=" * 66)
    print(f"  arquivo:        {ARQUIVO}")
    print(f"  existe:         {ARQUIVO.exists()}")
    print(f"  teto:           {MAX_CONVERSAS} conversas, "
          f"{MAX_MENSAGENS} mensagens cada")
    print()
    lista = listar()
    print(f"  {len(lista)} conversa(s) guardada(s):")
    for c in lista[:12]:
        quando = time.strftime("%d/%m %H:%M", time.localtime(c["mexida"]))
        print(f"    [{c['id']}] {c['quantas']:3d} msg  {quando}  {c['titulo']}")
    print()
    print("-- título derivado da primeira mensagem --")
    for exemplo in ("analisa a pasta de mods ai e me diz o que tem de bom",
                    "oi", "   ", "@emily monta o pack broxasRPG pra mim",
                    "linha1\nlinha2"):
        print(f"    {exemplo[:40]!r:44s} -> {titulo_de(exemplo)!r}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_diagnosticar())

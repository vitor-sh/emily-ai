"""
music_player.py — playlists, favoritos, busca e estado do player da interface.

O que este módulo FAZ
─────────────────────
- Guarda as playlists do Vitor num JSON (mesma gravação atômica das outras
  persistências do projeto). Suporta várias playlists e favoritos.
- Busca vídeo no YouTube por nome e devolve prévias (vários resultados),
  sem adicionar — quem decide adicionar é a interface.
- Devolve thumbnail e título de um vídeo.
- Persiste o estado do player (volume, loop, shuffle, música atual e posição)
  pra que a Emily reinicie exatamente onde o Vitor parou.

O que NÃO faz
─────────────
Não toca nada. O áudio roda no iframe embedado do YouTube dentro da WebView
(da interface), controlado pela API JavaScript oficial deles. Aqui é só
dado: o quê tocar, em que ordem, e metadados pra desenhar a UI.

Formato do arquivo:
{
  "playlists": {
    "default": [
      {"video_id": "dQw4w9WgXcQ", "titulo": "...", "thumb": "...",
       "adicionada": 1735000000.0}
    ]
  },
  "favoritos": {"dQw4w9WgXcQ": true},
  "playlist_ativa": "default",
  "player_estado": {
    "volume": 100, "loop": 1, "shuffle": false,
    "playlist": "default", "indice": 0,
    "video_id": "dQw4w9WgXcQ", "posicao": 42.5
  }
}
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

ARQUIVO = Path(os.getenv(
    "EMILY_ARQUIVO_PLAYLIST",
    str(Path.home() / ".emily_playlist.json"),
))

_lock = threading.RLock()
_cache: Optional[Dict] = None

_THUMB = "https://i.ytimg.com/vi/{id}/mqdefault.jpg"

PLAYLIST_PADRAO = "default"
MAX_PLAYLISTS = 20
MAX_MUSICAS = 200


def id_valido(vid):
    return isinstance(vid,str) and bool(re.fullmatch(r'(?:[A-Za-z0-9_-]{11}|local_[a-f0-9]{64})',vid))


def _log(msg: str) -> None:
    print(f"[PLAYER] {msg}")


def _estado_padrao() -> dict:
    return {
        "volume": 100, "loop": 1, "shuffle": False,
        "playlist": PLAYLIST_PADRAO, "indice": -1,
        "video_id": None, "posicao": 0.0,
    }


def _normalizar_estado(estado: object, dados: Optional[Dict] = None) -> dict:
    """Devolve apenas estado válido, mesmo se o JSON ou a WebView vierem ruins."""
    base = _estado_padrao()
    bruto = estado if isinstance(estado, dict) else {}

    try:
        base["volume"] = max(0, min(100, int(float(bruto.get("volume", 100)))))
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        loop = int(bruto.get("loop", 1))
        base["loop"] = loop if loop in (0, 1, 2) else 1
    except (TypeError, ValueError, OverflowError):
        pass
    shuffle = bruto.get("shuffle", False)
    base["shuffle"] = shuffle if isinstance(shuffle, bool) else False

    playlists = (dados or {}).get("playlists", {})
    nome = bruto.get("playlist")
    if isinstance(nome, str) and (not playlists or nome in playlists):
        base["playlist"] = nome
    try:
        indice = int(bruto.get("indice", -1))
        musicas = playlists.get(base["playlist"], []) if playlists else []
        base["indice"] = indice if indice == -1 or (0 <= indice < len(musicas)) else -1
    except (TypeError, ValueError, OverflowError):
        pass

    video_id = bruto.get("video_id")
    if video_id is None or (isinstance(video_id, str) and id_valido(video_id)):
        base["video_id"] = video_id
    try:
        posicao = float(bruto.get("posicao", 0.0))
        if posicao == posicao and posicao != float("inf"):
            base["posicao"] = max(0.0, min(posicao, 604800.0))
    except (TypeError, ValueError, OverflowError):
        pass
    return base


def _carregar() -> Dict:
    global _cache
    with _lock:
        if _cache is not None and getattr(_carregar, "mtime", None) == (ARQUIVO.stat().st_mtime_ns if ARQUIVO.exists() else None):
            return _cache
        dados: Dict = {}
        try:
            with open(ARQUIVO, encoding="utf-8") as f:
                lido = json.load(f)
            if isinstance(lido, dict):
                dados = lido
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError) as e:
            _log(f"não consegui ler a playlist ({e}); começando vazia")

        # Migração do formato antigo (lista 'musicas' achatada) pra novo.
        if "musicas" in dados and not dados.get("playlists"):
            dados["playlists"] = {PLAYLIST_PADRAO: dados.pop("musicas", [])}

        dados.setdefault("playlists", {})
        if not isinstance(dados["playlists"], dict):
            dados["playlists"] = {}
        dados["playlists"].setdefault(PLAYLIST_PADRAO, [])
        dados.setdefault("playlists_fotos", {})
        if not isinstance(dados["playlists_fotos"], dict):
            dados["playlists_fotos"] = {}
        dados.setdefault("favoritos", {})
        if not isinstance(dados["favoritos"], dict):
            dados["favoritos"] = {}
        dados.setdefault("playlist_ativa", PLAYLIST_PADRAO)
        if dados["playlist_ativa"] not in dados["playlists"]:
            dados["playlist_ativa"] = PLAYLIST_PADRAO
        for nome in dados["playlists"]:
            if not isinstance(dados["playlists"][nome], list):
                dados["playlists"][nome] = []

        dados["player_estado"] = _normalizar_estado(
            dados.get("player_estado"), dados)

        _cache = dados
        _carregar.mtime = ARQUIVO.stat().st_mtime_ns if ARQUIVO.exists() else None
        return _cache


def _salvar() -> None:
    """Gravação atômica — mesmo padrão de preferencias.py e conversas.py."""
    with _lock:
        tmp = ARQUIVO.with_suffix(".tmp")
        try:
            ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_carregar(), f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, ARQUIVO)
            _carregar.mtime = ARQUIVO.stat().st_mtime_ns
        except OSError as e:
            _log(f"não consegui gravar a playlist: {e}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise


# ═════════════════════════════════════════════════════════════════
# BUSCA E METADADOS NO YOUTUBE
# ═════════════════════════════════════════════════════════════════

_RE_VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|shorts/)([a-zA-Z0-9_-]{11})")
_RE_VIDEO_ID_JSON = re.compile(r'"videoId":"([a-zA-Z0-9_-]{11})"')


def video_id_de(texto: str) -> Optional[str]:
    """Extrai o ID de uma URL do YouTube. Nome digitado devolve None."""
    m = _RE_VIDEO_ID.search((texto or "").strip())
    return m.group(1) if m else None


def _titulo_do_video(video_id: str) -> str:
    """
    Título real via oEmbed público do YouTube (sem chave, sem scraping pesado).
    Falhar aqui não bloqueia nada: cai pro título genérico.
    """
    url = (f"https://www.youtube.com/oembed?url="
           f"https://www.youtube.com/watch?v={video_id}&format=json")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
        return str(dados.get("title") or "").strip()
    except Exception:
        return ""


def buscar_preview(query: str, limite: int = 6) -> List[Dict]:
    """
    Busca no YouTube e devolve até `limite` prévias {video_id, titulo, thumb}.

    Aceita tanto nome de música quanto URL direta. Para URL, devolve um
    resultado só. A interface mostra essas prévias antes de o usuário
    escolher o que adicionar — igual Spotify.
    """
    query = (query or "").strip()
    if not query:
        return []
    limite = max(1, min(limite, 12))

    vid = video_id_de(query)
    if vid is None and re.fullmatch(r"[a-zA-Z0-9_-]{11}", query):
        vid = query
    if vid is not None:
        titulo = _titulo_do_video(vid) or query[:60]
        return [{
            "video_id": vid,
            "titulo": titulo,
            "thumb": _THUMB.format(id=vid),
        }]

    try:
        url_busca = ("https://www.youtube.com/results?search_query="
                     + urllib.parse.quote(query))
        req = urllib.request.Request(
            url_busca,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8")
    except Exception as e:
        _log(f"busca falhou para '{query}': {e}")
        return []

    ids = _RE_VIDEO_ID_JSON.findall(html)
    # Remove duplicados mantendo a ordem; usa o início do resultado.
    vistos: set = set()
    unicos = []
    for vid_item in ids:
        if vid_item not in vistos:
            vistos.add(vid_item)
            unicos.append(vid_item)
        if len(unicos) >= limite:
            break

    resultados: List[Dict] = []
    for vid_item in unicos:
        titulo = _titulo_do_video(vid_item)
        if not titulo:
            continue
        resultados.append({
            "video_id": vid_item,
            "titulo": titulo,
            "thumb": _THUMB.format(id=vid_item),
        })
        if len(resultados) >= limite:
            break

    if not resultados:
        _log(f"busca sem resultados para '{query}'")
    return resultados


# ═════════════════════════════════════════════════════════════════
# PLAYLISTS
# ═════════════════════════════════════════════════════════════════

def _playlist_existe(nome: str) -> bool:
    return nome in _carregar()["playlists"]


def listar() -> List[Dict]:
    """Músicas da playlist ativa."""
    with _lock:
        nome = _carregar()["playlist_ativa"]
        return [dict(m) for m in _carregar()["playlists"].get(nome, [])]


def listar_playlists() -> Dict:
    """Todas as playlists com metadados + a ativa + favoritos + fotos."""
    with _lock:
        dados = _carregar()
        playlists = {}
        fotos = dados.get("playlists_fotos", {})
        for nome, musicas in dados["playlists"].items():
            playlists[nome] = {
                "musicas": [dict(m) for m in musicas],
                "quantidade": len(musicas),
                "foto": fotos.get(nome, ""),
            }
        return {
            "playlists": playlists,
            "ativa": dados["playlist_ativa"],
            "favoritos": dict(dados["favoritos"]),
        }


def criar_playlist(nome: str) -> bool:
    nome = (nome or "").strip()
    if not nome:
        return False
    if nome in _carregar()["playlists"]:
        return False
    if len(_carregar()["playlists"]) >= MAX_PLAYLISTS:
        return False
    with _lock:
        _carregar()["playlists"][nome] = []
        _salvar()
        return True


def renomear_playlist(nome_atual: str, nome_novo: str) -> bool:
    nome_atual = (nome_atual or "").strip()
    nome_novo = (nome_novo or "").strip()
    if not nome_atual or not nome_novo or nome_atual == PLAYLIST_PADRAO:
        return False
    if nome_novo in _carregar()["playlists"]:
        return False
    with _lock:
        dados = _carregar()
        if nome_atual not in dados["playlists"]:
            return False
        dados["playlists"][nome_novo] = dados["playlists"].pop(nome_atual)
        # Migra a foto junto com o nome
        fotos = dados.get("playlists_fotos", {})
        if nome_atual in fotos:
            fotos[nome_novo] = fotos.pop(nome_atual)
        if dados["playlist_ativa"] == nome_atual:
            dados["playlist_ativa"] = nome_novo
        if dados["player_estado"].get("playlist") == nome_atual:
            dados["player_estado"]["playlist"] = nome_novo
        _salvar()
        return True


def definir_foto_playlist(nome: str, foto_uri: str) -> bool:
    nome = (nome or "").strip()
    if not nome or not _playlist_existe(nome):
        return False
    with _lock:
        dados = _carregar()
        if foto_uri:
            dados.setdefault("playlists_fotos", {})[nome] = foto_uri
        else:
            dados.get("playlists_fotos", {}).pop(nome, None)
        _salvar()
        return True


def apagar_playlist(nome: str) -> bool:
    nome = (nome or "").strip()
    if not nome or nome == PLAYLIST_PADRAO:
        return False
    with _lock:
        dados = _carregar()
        if nome not in dados["playlists"]:
            return False
        del dados["playlists"][nome]
        dados.get("playlists_fotos", {}).pop(nome, None)
        if dados["playlist_ativa"] == nome:
            dados["playlist_ativa"] = PLAYLIST_PADRAO
        _salvar()
        return True


def selecionar_playlist(nome: str) -> bool:
    nome = (nome or "").strip()
    if not _playlist_existe(nome):
        return False
    with _lock:
        _carregar()["playlist_ativa"] = nome
        _salvar()
        return True


def playlist_ativa() -> str:
    return _carregar()["playlist_ativa"]


# ═════════════════════════════════════════════════════════════════
# MÚSICAS
# ═════════════════════════════════════════════════════════════════

def adicionar(item: Dict, nome_playlist: Optional[str] = None) -> bool:
    """Acrescenta à playlist (ativa se não informada). Duplicado preserva a entrada original."""
    vid = (item or {}).get("video_id", "")
    if not id_valido(vid):
        return False
    nome = (nome_playlist or _carregar()["playlist_ativa"]).strip()
    if not _playlist_existe(nome):
        return False
    with _lock:
        dados = _carregar()
        musicas = dados["playlists"][nome]
        if any(m.get('video_id') == vid for m in musicas):
            return True
        entrada = {
            "video_id": vid,
            "titulo": (item.get("titulo") or "Sem título")[:120],
            "thumb": item.get("thumb") or ("" if vid.startswith("local_") else _THUMB.format(id=vid)),
            "adicionada": time.time(),
        }
        dados["playlists"][nome].append(entrada)
        excesso = len(dados["playlists"][nome]) - MAX_MUSICAS
        if excesso > 0:
            del dados["playlists"][nome][:excesso]
        _salvar()
        return True


def organizar(nome: str, ids: list) -> bool:
    """Reordena sem perder faixas nem aceitar uma lista antiga incompleta."""
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return False
    with _lock:
        dados = _carregar()
        musicas = dados['playlists'].get(nome)
        if musicas is None:
            return False
        mapa = {m['video_id']: m for m in musicas}
        if len(ids) != len(musicas) or len(set(ids)) != len(ids) or set(ids) != set(mapa):
            return False
        dados['playlists'][nome] = [mapa[i] for i in ids]
        _salvar()
        return True


def adicionar_por_busca(query: str) -> Optional[Dict]:
    """Compat: busca e adiciona a primeira prévia à playlist ativa."""
    previas = buscar_preview(query, limite=1)
    if previas and adicionar(previas[0]):
        return previas[0]
    return None


def remover(video_id: str, nome_playlist: Optional[str] = None) -> bool:
    nome = (nome_playlist or _carregar()["playlist_ativa"]).strip()
    if not _playlist_existe(nome):
        return False
    with _lock:
        dados = _carregar()
        musicas = dados["playlists"][nome]
        antes = len(musicas)
        dados["playlists"][nome] = [
            m for m in musicas if m.get("video_id") != video_id
        ]
        mudou = len(dados["playlists"][nome]) < antes
        if mudou:
            _salvar()
        return mudou


# ═════════════════════════════════════════════════════════════════
# FAVORITOS
# ═════════════════════════════════════════════════════════════════

def favoritar(video_id: str, favorito: bool) -> bool:
    with _lock:
        dados = _carregar()
        if favorito:
            dados["favoritos"][video_id] = True
        else:
            dados["favoritos"].pop(video_id, None)
        _salvar()
        return True


def favoritos() -> Dict:
    with _lock:
        return dict(_carregar()["favoritos"])


# ═════════════════════════════════════════════════════════════════
# ESTADO DO PLAYER (persistência de volume, loop, shuffle, música)
# ═════════════════════════════════════════════════════════════════

def estado() -> Dict:
    with _lock:
        return dict(_carregar()["player_estado"])


def salvar_estado(**campos) -> bool:
    """Atualiza apenas campos conhecidos e normaliza antes de persistir."""
    with _lock:
        dados = _carregar()
        estado_atual = dict(dados["player_estado"])
        permitidos = set(_estado_padrao())
        for chave, valor in campos.items():
            if chave in permitidos and valor is not None:
                estado_atual[chave] = valor
        dados["player_estado"] = _normalizar_estado(estado_atual, dados)
        _salvar()
        return True


import music_sync
import sys
music_sync.install(sys.modules[__name__])

if __name__ == "__main__":
    total = sum(len(m) for m in _carregar()["playlists"].values())
    print(f"{len(_carregar()['playlists'])} playlist(s), {total} música(s)")
    print(f"playlist ativa: {playlist_ativa()}")
    print(f"favoritos: {len(_carregar()['favoritos'])}")
    print(f"estado: {estado()}")

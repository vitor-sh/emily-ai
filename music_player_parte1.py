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


def _log(msg: str) -> None:
    print(f"[PLAYER] {msg}")


def _estado_padrao() -> dict:
    return {
        "volume": 100, "loop": 1, "shuffle": False,
        "playlist": PLAYLIST_PADRAO, "indice": -1,
        "video_id": None, "posicao": 0.0,
    }


def _carregar() -> Dict:
    global _cache
    with _lock:
        if _cache is not None:
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
        dados.setdefault("favoritos", {})
        if not isinstance(dados["favoritos"], dict):
            dados["favoritos"] = {}
        dados.setdefault("playlist_ativa", PLAYLIST_PADRAO)
        if dados["playlist_ativa"] not in dados["playlists"]:
            dados["playlist_ativa"] = PLAYLIST_PADRAO
        dados.setdefault("player_estado", _estado_padrao())
        for chave, valor in _estado_padrao().items():
            dados["player_estado"].setdefault(chave, valor)

        # Sanitiza listas
        for nome in dados["playlists"]:
            if not isinstance(dados["playlists"][nome], list):
                dados["playlists"][nome] = []

        _cache = dados
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
        except OSError as e:
            _log(f"não consegui gravar a playlist: {e}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

"""Integrações opcionais da Cloud com arquivos produzidos pela Emily."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional


def modo_downloads() -> str:
    """Retorna ``desligado``, ``local`` ou ``sincronizar``."""
    legado = os.getenv("EMILY_CLOUD_GUARDAR_DOWNLOADS", "1").strip().lower()
    if legado in {"0", "false", "nao", "não", "off"}:
        return "desligado"
    modo = os.getenv("EMILY_CLOUD_DOWNLOADS_MODO", "local").strip().lower()
    return modo if modo in {"desligado", "local", "sincronizar"} else "local"


def guardar_download(caminho: str, url_origem: str = "", origem: str = "download_emily") -> dict:
    """Guarda um download concluído sem mover ou alterar o original."""
    if modo_downloads() == "desligado":
        return {"ok": True, "ignorado": True, "motivo": "preferência desligada"}
    arquivo = Path(str(caminho or "")).expanduser()
    if not arquivo.is_file():
        return {"ok": False, "erro": "arquivo final do download não encontrado"}
    from . import core
    item = core.importar(str(arquivo), origem=origem, url_origem=url_origem)
    resultado = {"ok": True, "item": item}
    if modo_downloads() == "sincronizar":
        try:
            resultado["sync"] = core.sincronizar(item["id"])
        except Exception as exc:  # download local continua válido se S3 falhar
            resultado["sync"] = {"ok": False, "erro": str(exc)}
    return resultado


def guardar_download_evento(caminho: str, evento_id: str, url_origem: str = "",
                            origem: str = "extensao_navegador") -> dict:
    """Guarda evento confirmado pela extensão de forma idempotente."""
    if modo_downloads() == "desligado":
        return {"ok": True, "ignorado": True, "motivo": "preferência desligada"}
    arquivo = Path(str(caminho or "")).expanduser()
    evento_id = str(evento_id or "").strip()
    if not evento_id:
        return {"ok": False, "erro": "evento de download sem ID"}
    if not arquivo.is_file():
        return {"ok": False, "erro": "arquivo final do download não encontrado"}
    from . import core
    item = core.importar(
        str(arquivo), origem=origem, url_origem=url_origem, evento_id=evento_id)
    resultado = {"ok": True, "item": item}
    if modo_downloads() == "sincronizar" and item.get("estado_sync") != "sincronizado":
        try:
            resultado["sync"] = core.sincronizar(item["id"])
        except Exception as exc:
            resultado["sync"] = {"ok": False, "erro": str(exc)}
    return resultado


def arquivo_final_ytdlp(stdout: str, pasta: Path, iniciado_em: float,
                        extensoes: tuple[str, ...]) -> Optional[Path]:
    """Resolve o caminho impresso por ``after_move:filepath`` com fallback seguro."""
    for linha in reversed(str(stdout or "").splitlines()):
        candidato = Path(linha.strip().strip('"')).expanduser()
        if candidato.is_file():
            return candidato
    permitidas = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensoes}
    try:
        candidatos = [
            p for p in Path(pasta).iterdir()
            if p.is_file() and p.suffix.lower() in permitidas
            and p.stat().st_mtime >= float(iniciado_em) - 2.0
        ]
    except OSError:
        return None
    return max(candidatos, key=lambda p: p.stat().st_mtime) if candidatos else None


def agendar_download(caminho: str, url_origem: str = "", origem: str = "download_emily",
                     callback: Optional[Callable[[dict], None]] = None) -> None:
    """Importa em thread daemon para nunca atrasar a conclusão do downloader."""
    if modo_downloads() == "desligado":
        return

    def executar() -> None:
        try:
            resultado = guardar_download(caminho, url_origem, origem)
        except Exception as exc:  # integração não pode transformar download em erro
            resultado = {"ok": False, "erro": str(exc)}
        if callback:
            callback(resultado)
        if not resultado.get("ok"):
            print(f"[EMILY-CLOUD] download não guardado: {resultado.get('erro')}")

    threading.Thread(target=executar, daemon=True, name="EmilyCloudDownload").start()
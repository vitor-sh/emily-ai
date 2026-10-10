"""Inspeção e extração segura de arquivos compactados da Emily Cloud.

ZIP e TAR usam apenas a biblioteca padrão. A extração nunca confia nos caminhos
do arquivo: links, caminhos absolutos, ``..``, dispositivos e expansões
desproporcionais são recusados antes de qualquer byte ser gravado.
"""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

from . import core, service


MAX_ENTRADAS = 5000
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_ARQUIVO = 1024 * 1024 * 1024
MAX_RAZAO = 250


def _caminho_relativo(nome: str) -> Path:
    bruto = str(nome or "").replace("\\", "/")
    puro = PurePosixPath(bruto)
    if not bruto or "\x00" in bruto or puro.is_absolute() or any(p in ("", ".", "..") for p in puro.parts):
        raise ValueError(f"Caminho inseguro no compactado: {nome!r}.")
    if puro.parts and ":" in puro.parts[0]:
        raise ValueError(f"Caminho absoluto não permitido no compactado: {nome!r}.")
    return Path(*puro.parts)


def _formato(item: dict) -> str:
    nome = item["nome"].lower()
    if nome.endswith(".zip"):
        return "zip"
    if any(nome.endswith(s) for s in (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        return "tar"
    raise ValueError("A visualização interna suporta ZIP, TAR, TAR.GZ, TAR.BZ2 e TAR.XZ.")


def _selecionado(nome: str, escolhas: Optional[set[str]]) -> bool:
    if escolhas is None:
        return True
    return nome in escolhas or any(nome.startswith(p.rstrip("/") + "/") for p in escolhas)


def _validar_totais(entradas: list[dict], tamanho_compactado: int) -> None:
    arquivos = [e for e in entradas if not e["diretorio"]]
    total = sum(e["tamanho"] for e in arquivos)
    if len(entradas) > MAX_ENTRADAS:
        raise ValueError(f"Compactado possui entradas demais (máximo {MAX_ENTRADAS}).")
    if any(e["tamanho"] > MAX_ARQUIVO for e in arquivos):
        raise ValueError("Compactado contém um arquivo maior que o limite de 1 GiB.")
    if total > MAX_TOTAL:
        raise ValueError("Conteúdo expandido ultrapassa o limite de 2 GiB.")
    if tamanho_compactado > 0 and total > max(64 * 1024 * 1024, tamanho_compactado * MAX_RAZAO):
        raise ValueError("Compactado recusado por expansão desproporcional (possível zip bomb).")


def listar(item_id: str) -> dict:
    item = core.detalhes(item_id)
    if item["tipo"] != "arquivo":
        raise ValueError("Esse item não é um arquivo compactado.")
    formato = _formato(item)
    caminho = core.caminho_conteudo(item_id)
    entradas: list[dict] = []

    if formato == "zip":
        try:
            with zipfile.ZipFile(caminho) as arquivo:
                for info in arquivo.infolist():
                    relativo = _caminho_relativo(info.filename)
                    modo = (info.external_attr >> 16) & 0o170000
                    if modo == 0o120000:
                        raise ValueError("Links simbólicos não são permitidos em ZIP.")
                    if info.flag_bits & 0x1:
                        raise ValueError("ZIP protegido por senha não pode ser aberto internamente.")
                    entradas.append({
                        "caminho": relativo.as_posix(), "nome": relativo.name,
                        "diretorio": info.is_dir(), "tamanho": int(info.file_size),
                        "compactado": int(info.compress_size),
                    })
        except zipfile.BadZipFile as exc:
            raise ValueError("ZIP inválido ou corrompido.") from exc
    else:
        try:
            with tarfile.open(caminho, "r:*") as arquivo:
                for info in arquivo.getmembers():
                    relativo = _caminho_relativo(info.name)
                    if info.issym() or info.islnk() or info.isdev() or info.isfifo():
                        raise ValueError("Links e dispositivos não são permitidos em TAR.")
                    if not (info.isdir() or info.isfile()):
                        continue
                    entradas.append({
                        "caminho": relativo.as_posix(), "nome": relativo.name,
                        "diretorio": info.isdir(), "tamanho": int(info.size),
                        "compactado": 0,
                    })
        except tarfile.TarError as exc:
            raise ValueError("TAR inválido ou corrompido.") from exc

    _validar_totais(entradas, caminho.stat().st_size)
    return {
        "ok": True, "formato": formato, "entradas": entradas,
        "total_entradas": len(entradas),
        "total_arquivos": sum(not e["diretorio"] for e in entradas),
        "bytes_extraidos": sum(e["tamanho"] for e in entradas if not e["diretorio"]),
    }


def extrair(item_id: str, parent_id: Optional[str] = None,
            entradas: Optional[Iterable[str]] = None) -> dict:
    item = core.detalhes(item_id)
    formato = _formato(item)
    caminho = core.caminho_conteudo(item_id)
    catalogo = listar(item_id)
    escolhas = None if entradas is None else {
        _caminho_relativo(str(nome)).as_posix() for nome in entradas if str(nome).strip()
    }
    escolhidas = [e for e in catalogo["entradas"] if _selecionado(e["caminho"], escolhas)]
    if escolhas is not None and not escolhidas:
        raise ValueError("Nenhuma entrada válida foi selecionada para extração.")
    _validar_totais(escolhidas, caminho.stat().st_size)

    nome_base = item["nome"]
    for sufixo in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".zip", ".tar"):
        if nome_base.lower().endswith(sufixo):
            nome_base = nome_base[:-len(sufixo)]
            break
    nome_pasta = core._nome_seguro(nome_base or "Conteúdo extraído", "Conteúdo extraído")

    temporario = Path(tempfile.mkdtemp(prefix="extrair-", dir=core.STAGING))
    raiz = temporario / nome_pasta
    raiz.mkdir()
    permitidas = {e["caminho"] for e in escolhidas}
    try:
        if formato == "zip":
            with zipfile.ZipFile(caminho) as arquivo:
                for info in arquivo.infolist():
                    relativo = _caminho_relativo(info.filename)
                    chave = relativo.as_posix()
                    if chave not in permitidas:
                        continue
                    destino = raiz / relativo
                    if info.is_dir():
                        destino.mkdir(parents=True, exist_ok=True)
                    else:
                        destino.parent.mkdir(parents=True, exist_ok=True)
                        with arquivo.open(info) as origem, destino.open("xb") as saida:
                            shutil.copyfileobj(origem, saida, 1024 * 1024)
        else:
            with tarfile.open(caminho, "r:*") as arquivo:
                for info in arquivo.getmembers():
                    relativo = _caminho_relativo(info.name)
                    if relativo.as_posix() not in permitidas:
                        continue
                    destino = raiz / relativo
                    if info.isdir():
                        destino.mkdir(parents=True, exist_ok=True)
                    elif info.isfile():
                        destino.parent.mkdir(parents=True, exist_ok=True)
                        origem = arquivo.extractfile(info)
                        if origem is None:
                            raise ValueError(f"Não consegui ler {info.name}.")
                        with origem, destino.open("xb") as saida:
                            shutil.copyfileobj(origem, saida, 1024 * 1024)

        importado = core.importar(str(raiz), parent_id, nome=nome_pasta, origem="extracao_cloud")
        return {
            "ok": True, "item": service.item_ui(importado),
            "extraidos": sum(not e["diretorio"] for e in escolhidas),
            "bytes_extraidos": sum(e["tamanho"] for e in escolhidas if not e["diretorio"]),
        }
    finally:
        shutil.rmtree(temporario, ignore_errors=True)
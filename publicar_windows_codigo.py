#!/usr/bin/env python3
"""Publica código/interface Windows no gateway, sem gerar outro instalador.

Uso: python publicar_windows_codigo.py --version 1 --installer 1.0.2
O instalador indicado precisa ter o bootstrap + runtime hook de overrides.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
DEST = Path.home() / ".local/share/emily/windows-code-updates"
PASTAS = ("web", "static", "img", "assets", "emily-gateway-service",
          "memoria_unificada", "emily_cloud")
EXTENSOES_RECURSOS = frozenset({".html", ".css", ".js", ".json", ".svg",
                                ".png", ".jpg", ".jpeg", ".gif", ".webp",
                                ".ico", ".woff", ".woff2", ".ttf", ".onnx",
                                ".rnnn", ".mp3", ".wav", ".ogg"})
EXCLUIR_MODULOS = {"emily_bootstrap", "pyi_rhook_emily", "build_emily",
                    "build_emily_linux", "build_emily_windows", "publicar_windows",
                    "publicar_windows_codigo", "preparar_windows_fonte"}


def arquivos_publicaveis(root: Path = ROOT) -> list[Path]:
    arquivos = [p for p in root.glob("*.py") if not p.is_symlink()
                and p.stem not in EXCLUIR_MODULOS
                and not p.stem.startswith(("_", "test_", "testar_", "test_emily"))]
    for nome in PASTAS:
        pasta = root / nome
        if pasta.is_dir():
            arquivos.extend(p for p in pasta.rglob("*") if p.is_file()
                            and not p.is_symlink()
                            and (nome not in {"emily-gateway-service", "memoria_unificada",
                                                  "emily_cloud"} or p.suffix == ".py")
                            and (p.suffix == ".py" or p.suffix.lower() in EXTENSOES_RECURSOS)
                            and "__pycache__" not in p.parts
                            and not p.name.endswith((".pyc", ".log", ".tmp")))
    return sorted(set(arquivos))


def publicar(versao: int, installer: str, destino: Path = DEST,
             root: Path = ROOT, selecionar: list[str] | None = None,
             retirar: list[str] | None = None) -> Path:
    from windows_update import _versao

    if versao < 1:
        raise ValueError("a versão do código deve ser positiva")
    _versao(installer)
    manifesto = destino / "latest.json"
    anterior = None
    if manifesto.is_file():
        anterior = json.loads(manifesto.read_text(encoding="utf-8"))
        if versao <= int(anterior.get("version", 0)):
            raise ValueError("publique uma versão de código maior que a atual")
    publicaveis = {p.relative_to(root).as_posix(): p
                   for p in arquivos_publicaveis(root)}
    if selecionar is None:
        arquivos = list(publicaveis.values())
    else:
        ausentes = sorted(set(selecionar) - publicaveis.keys())
        if ausentes:
            raise ValueError(f"arquivos não publicáveis: {', '.join(ausentes)}")
        arquivos = [publicaveis[nome] for nome in sorted(set(selecionar))]
    if not arquivos:
        raise ValueError("nenhum arquivo publicável")
    conteudos: dict[str, bytes] = {}
    # O cliente pode saltar da versão 0 diretamente para a mais nova. Uma
    # publicação seletiva precisa, portanto, incluir os patches anteriores.
    if selecionar is not None and anterior and anterior.get("installer") == installer:
        arquivo_anterior = destino / f"Emily-Code-{int(anterior['version'])}.zip"
        zip_anterior = arquivo_anterior.read_bytes()
        if (len(zip_anterior) != anterior.get("size")
                or hashlib.sha256(zip_anterior).hexdigest() != anterior.get("sha256")):
            raise ValueError("pacote anterior não confere com o manifesto")
        with ZipFile(io.BytesIO(zip_anterior)) as pacote_anterior:
            if set(pacote_anterior.namelist()) != set(anterior.get("files", {})):
                raise ValueError("lista do pacote anterior não confere")
            for nome, digest in anterior["files"].items():
                conteudo = pacote_anterior.read(nome)
                if hashlib.sha256(conteudo).hexdigest() != digest:
                    raise ValueError(f"arquivo anterior alterado: {nome}")
                conteudos[nome] = conteudo
    for arquivo in arquivos:
        conteudos[arquivo.relative_to(root).as_posix()] = arquivo.read_bytes()
    for nome in retirar or []:
        if nome not in conteudos:
            raise ValueError(f"arquivo não presente no pacote para retirar: {nome}")
        conteudos.pop(nome)
    if not conteudos:
        raise ValueError("pacote ficaria vazio")
    hashes: dict[str, str] = {}
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED, compresslevel=6) as pacote:
        for relativo in sorted(conteudos):
            hashes[relativo] = hashlib.sha256(conteudos[relativo]).hexdigest()
            pacote.writestr(relativo, conteudos[relativo])
    conteudo_zip = buffer.getvalue()
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / f"Emily-Code-{versao}.zip"
    temporario = arquivo.with_suffix(".upload")
    temporario.write_bytes(conteudo_zip)
    os.replace(temporario, arquivo)
    dados = {"version": versao, "installer": installer, "size": len(conteudo_zip),
             "sha256": hashlib.sha256(conteudo_zip).hexdigest(), "files": hashes}
    temp_manifesto = destino / "latest.json.tmp"
    temp_manifesto.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    os.replace(temp_manifesto, manifesto)
    import subprocess, sys
    if destino.resolve() == DEST.resolve() and root.resolve() == ROOT.resolve():
        subprocess.run([sys.executable, str(ROOT / "limpar_armazenamento.py"), "--apply"], check=False)
    return arquivo


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--installer", required=True,
                        help="versão do instalador Windows compatível")
    parser.add_argument("--file", action="append", dest="files",
                        help="arquivo relativo para publicar; pode repetir")
    parser.add_argument("--remove", action="append", dest="remove",
                        help="retirar arquivo de um pacote cumulativo anterior")
    op = parser.parse_args()
    print(publicar(op.version, op.installer, selecionar=op.files,
                   retirar=op.remove))

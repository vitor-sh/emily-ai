"""Publica um instalador Windows já testado no gateway Fedora.

Uso: python publicar_windows.py CAMINHO_DO_EXE --version 1.0.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

DESTINO = Path.home() / ".local/share/emily/windows-updates"


def publicar(origem: Path, versao: str, destino: Path = DESTINO) -> Path:
    from windows_update import _versao
    _versao(versao)
    if not origem.is_file() or origem.is_symlink():
        raise FileNotFoundError(origem)
    destino.mkdir(parents=True, exist_ok=True)
    alvo = destino / f"Emily-Setup-{versao}.exe"
    tmp = alvo.with_suffix(".upload")
    digest = hashlib.sha256()
    tamanho = 0
    with origem.open("rb") as entrada, tmp.open("wb") as saida:
        for bloco in iter(lambda: entrada.read(1024 * 1024), b""):
            digest.update(bloco)
            tamanho += len(bloco)
            saida.write(bloco)
        saida.flush()
        os.fsync(saida.fileno())
    if tamanho == 0:
        tmp.unlink(missing_ok=True)
        raise ValueError("instalador vazio")
    os.replace(tmp, alvo)
    manifesto = destino / "latest.json"
    tmp_json = destino / "latest.json.tmp"
    tmp_json.write_text(json.dumps({"version": versao, "size": tamanho,
                                    "sha256": digest.hexdigest()}), encoding="utf-8")
    os.replace(tmp_json, manifesto)
    return alvo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instalador", type=Path)
    parser.add_argument("--version", required=True)
    op = parser.parse_args()
    print(publicar(op.instalador, op.version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

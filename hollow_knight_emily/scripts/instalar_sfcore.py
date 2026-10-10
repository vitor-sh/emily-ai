"""Baixa, valida e instala a dependência SFCore usada pelo charm da Emily."""

from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import urllib.request
import zipfile
from pathlib import Path


VERSAO = "1.5.16.2"
SHA256 = "f2b90438437ac3ee17dec4c4359abaf662c25b34db1439f92826dd11575586b2"
URL = f"https://github.com/SFGrenade/SFCore/releases/download/v{VERSAO}/SFCore.zip"
JOGO_PADRAO = Path.home() / ".local/share/Steam/steamapps/common/Hollow Knight"


def instalar(jogo: Path) -> Path:
    managed = jogo / "hollow_knight_Data/Managed"
    if not (managed / "Assembly-CSharp.dll").is_file():
        raise RuntimeError(f"Instalação do jogo inválida: {jogo}")
    with urllib.request.urlopen(URL, timeout=60) as resposta:
        pacote = resposta.read()
    obtido = hashlib.sha256(pacote).hexdigest()
    if obtido != SHA256:
        raise RuntimeError(f"SHA-256 do SFCore inválido: {obtido}")
    destino = managed / "Mods/SFCore"
    destino.mkdir(parents=True, exist_ok=True)
    permitidos = {"SFCore.dll", "SFCore.xml", "SFCore.pdb", "WavLib.dll", "README.md"}
    with zipfile.ZipFile(io.BytesIO(pacote)) as arquivo:
        for item in arquivo.infolist():
            if item.is_dir() or item.filename not in permitidos:
                continue
            alvo = destino / item.filename
            with arquivo.open(item) as origem, alvo.open("wb") as saida:
                shutil.copyfileobj(origem, saida)
    if not (destino / "SFCore.dll").is_file() or not (destino / "WavLib.dll").is_file():
        raise RuntimeError("Pacote SFCore incompleto.")
    return destino


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jogo", type=Path, default=JOGO_PADRAO)
    args = parser.parse_args()
    print(f"SFCore {VERSAO} instalado em: {instalar(args.jogo)}")


if __name__ == "__main__":
    main()
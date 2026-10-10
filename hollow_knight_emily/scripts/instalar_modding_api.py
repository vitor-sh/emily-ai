"""Instala/restaura o Modding API v77 de forma transacional.

O Hollow Knight desta máquina é a build Windows 1.5.78.11833 executada por
Proton. O pacote oficial substitui Assembly-CSharp.dll e adiciona dependências
ao diretório Managed; por isso cada instalação recebe manifesto e backup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path


SHA256_OFICIAL = "bc9f0db3d0916b05cd5a2420bb602fb1b239ce3ff6c289fd84bffb682fb8f1d6"
RAIZ = Path(__file__).resolve().parents[1]
JOGO_PADRAO = Path.home() / ".local/share/Steam/steamapps/common/Hollow Knight"
PACOTE_PADRAO = Path("/tmp/emily-hk-api/moddingapi.v77.windows.zip")
BACKUPS = RAIZ / "backups"


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def _processos_hollow_knight() -> list[dict]:
    encontrados = []
    proc = Path("/proc")
    if not proc.exists():
        return encontrados
    for entrada in proc.iterdir():
        if not entrada.name.isdigit():
            continue
        try:
            comando = (entrada / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                errors="replace"
            )
        except (OSError, PermissionError):
            continue
        normalizado = comando.lower().replace("\\", "/")
        argumentos = [parte for parte in normalizado.split(" ") if parte]
        # Não case o nome desta própria pasta/script (hollow_knight_emily).
        # É processo do jogo somente quando algum argumento aponta para o
        # executável real, ou quando o nome do processo é o binário nativo.
        eh_jogo = any(
            parte.endswith("/hollow_knight.exe")
            or parte.endswith("/hollow_knight")
            or parte in {"hollow_knight.exe", "hollow_knight"}
            for parte in argumentos
        )
        if eh_jogo:
            encontrados.append({"pid": int(entrada.name), "comando": comando})
    return encontrados


def instalar(jogo: Path, pacote: Path) -> Path:
    managed = jogo / "hollow_knight_Data" / "Managed"
    if not managed.is_dir() or not (managed / "Assembly-CSharp.dll").is_file():
        raise RuntimeError(f"Managed inválido: {managed}")
    processos = _processos_hollow_knight()
    if processos:
        raise RuntimeError(f"Feche o Hollow Knight antes de instalar: {processos}")
    if not pacote.is_file():
        raise RuntimeError(f"Pacote não encontrado: {pacote}")
    obtido = sha256(pacote)
    if obtido != SHA256_OFICIAL:
        raise RuntimeError(f"SHA-256 inválido: {obtido}")

    carimbo = time.strftime("%Y%m%d-%H%M%S")
    destino_backup = BACKUPS / f"modding-api-v77-{carimbo}"
    arquivos_backup = destino_backup / "arquivos"
    arquivos_backup.mkdir(parents=True, exist_ok=False)

    with zipfile.ZipFile(pacote) as zip_api:
        nomes = [i.filename for i in zip_api.infolist() if not i.is_dir()]
        manifesto = {
            "versao_jogo": "1.5.78.11833",
            "versao_api": 77,
            "pacote": str(pacote),
            "pacote_sha256": obtido,
            "managed": str(managed),
            "criado_em": time.time(),
            "arquivos": [],
        }
        for nome in nomes:
            relativo = Path(nome)
            if relativo.is_absolute() or ".." in relativo.parts:
                raise RuntimeError(f"Entrada insegura no ZIP: {nome}")
            alvo = managed / relativo
            anterior = None
            if alvo.is_file():
                anterior = sha256(alvo)
                copia = arquivos_backup / relativo
                copia.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(alvo, copia)
            manifesto["arquivos"].append(
                {"caminho": nome, "existia": alvo.exists(), "sha256_anterior": anterior}
            )

        with tempfile.TemporaryDirectory(prefix="emily-hk-api-") as temporario:
            staging = Path(temporario)
            zip_api.extractall(staging)
            for nome in nomes:
                origem = staging / nome
                alvo = managed / nome
                alvo.parent.mkdir(parents=True, exist_ok=True)
                temporario_alvo = alvo.with_suffix(alvo.suffix + ".emily-novo")
                shutil.copy2(origem, temporario_alvo)
                os.replace(temporario_alvo, alvo)

    for item in manifesto["arquivos"]:
        alvo = managed / item["caminho"]
        item["sha256_instalado"] = sha256(alvo)
    (managed / "Mods").mkdir(exist_ok=True)
    (destino_backup / "manifesto.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (BACKUPS / "ultimo.txt").write_text(str(destino_backup), encoding="utf-8")
    return destino_backup


def restaurar(jogo: Path, backup: Path | None) -> None:
    processos = _processos_hollow_knight()
    if processos:
        raise RuntimeError(f"Feche o Hollow Knight antes de restaurar: {processos}")
    if backup is None:
        ponteiro = BACKUPS / "ultimo.txt"
        if not ponteiro.is_file():
            raise RuntimeError("Nenhum backup registrado.")
        backup = Path(ponteiro.read_text(encoding="utf-8").strip())
    manifesto = json.loads((backup / "manifesto.json").read_text(encoding="utf-8"))
    managed = jogo / "hollow_knight_Data" / "Managed"
    for item in manifesto["arquivos"]:
        alvo = managed / item["caminho"]
        salvo = backup / "arquivos" / item["caminho"]
        if item["existia"]:
            if not salvo.is_file():
                raise RuntimeError(f"Backup incompleto: {salvo}")
            shutil.copy2(salvo, alvo)
        elif alvo.exists():
            alvo.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("acao", choices=("instalar", "restaurar", "verificar"))
    parser.add_argument("--jogo", type=Path, default=JOGO_PADRAO)
    parser.add_argument("--pacote", type=Path, default=PACOTE_PADRAO)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.acao == "verificar":
        print(json.dumps({
            "jogo": str(args.jogo),
            "managed_ok": (args.jogo / "hollow_knight_Data/Managed/Assembly-CSharp.dll").is_file(),
            "pacote": str(args.pacote),
            "sha256": sha256(args.pacote) if args.pacote.is_file() else "",
            "processos": _processos_hollow_knight(),
        }, ensure_ascii=False, indent=2))
    elif args.acao == "instalar":
        print(f"Backup criado em: {instalar(args.jogo, args.pacote)}")
    else:
        restaurar(args.jogo, args.backup)
        print("Instalação original restaurada.")


if __name__ == "__main__":
    main()
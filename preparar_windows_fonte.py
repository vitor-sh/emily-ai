"""Monta um pacote pequeno de código atual para executar o build no Windows."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

RAIZ = Path(__file__).resolve().parent
PASTAS = ("web", "static", "img", "assets", "extensao_emily",
          "emily-gateway-service", "memoria_unificada", "emily_cloud",
          "hollow_knight_emily/python", "hollow_knight_emily/art",
          "hollow_knight_emily/mod", "hollow_knight_emily/runtime", "installer")
ARQUIVOS = ("requirements.txt", "requirements-windows.txt", "WINDOWS_BUILD.md",
            "PLANO_INSTALADOR_WINDOWS.md", "regras_servidor.md",
            "ativar_atualizacao_codigo_windows.ps1",
            "emilyimage.png", "emily.gif", "hollow_knight_emily/__init__.py")


def montar(destino: Path, privado: bool = False) -> Path:
    arquivos = {p for p in RAIZ.glob("*.py") if not p.name.startswith(("_teste", "test_"))}
    arquivos.update(RAIZ / nome for nome in ARQUIVOS if (RAIZ / nome).is_file())
    if privado:
        segredo = RAIZ / ".env"
        if not segredo.is_file():
            raise FileNotFoundError(".env privado não encontrado")
        arquivos.add(segredo)
    for nome in PASTAS:
        pasta = RAIZ / nome
        if pasta.is_dir():
            arquivos.update(p for p in pasta.rglob("*") if p.is_file()
                            and "__pycache__" not in p.parts
                            and not p.name.endswith((".pyc", ".log", ".tmp")))
    destino.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destino, "w", ZIP_DEFLATED, compresslevel=6) as pacote:
        for arquivo in sorted(arquivos):
            pacote.write(arquivo, "minha-ia/" + arquivo.relative_to(RAIZ).as_posix())
    return destino


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", action="store_true", help="inclui .env com chaves")
    parser.add_argument("--output", type=Path, default=RAIZ.parent / "Emily-Windows-Fonte-Privada.zip")
    op = parser.parse_args()
    print(montar(op.output, op.private))

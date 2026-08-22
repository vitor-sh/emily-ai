"""
Task 1 — descoberta do profileArn do Kiro.

A conta do Vitor é Enterprise/IdC e o arquivo de credencial não traz profileArn,
mas o runtime do Kiro exige. O gateway não descobre sozinho: usa
auth_manager.profile_arn ou o PROFILE_ARN do .env, com "" de fallback — e é o
vazio que a API recusa com 400.

Este script varre os diretórios locais do Kiro IDE procurando o ARN.
Imprime o ARN com o número da conta MASCARADO e o nome do arquivo onde achou.
Grava o valor real em _arn_encontrado.txt (gitignorado por *.txt? não — ver aviso
no fim) para o próximo passo consumir sem passar pelo terminal.

Uso:
    python _teste_achar_arn.py
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

PADRAO = re.compile(r"arn:aws:codewhisperer:[a-z0-9-]+:\d{12}:profile/[A-Za-z0-9]+")

EXTENSOES = {".json", ".log", ".txt", ".sqlite3", ".db", ".vscdb", ".ldb"}

LIMITE_BYTES = 40 * 1024 * 1024   # 40MB por arquivo, evita travar em blob grande


def _mascarar(arn: str) -> str:
    return re.sub(r":(\d{12}):", ":<conta>:", arn)


def _diretorios() -> list[Path]:
    perfil = Path(os.environ["USERPROFILE"])
    candidatos = [
        Path(os.environ.get("APPDATA", "")) / "Kiro",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Kiro",
        perfil / ".kiro",
        perfil / ".aws",
        Path(os.environ.get("LOCALAPPDATA", "")) / "kiro-cli",
        perfil / ".local" / "share" / "kiro-cli",
    ]
    return [c for c in candidatos if c and c.exists()]


def _varrer_texto(caminho: Path) -> set[str]:
    try:
        if caminho.stat().st_size > LIMITE_BYTES:
            return set()
        conteudo = caminho.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    return set(PADRAO.findall(conteudo))


def _varrer_sqlite(caminho: Path) -> set[str]:
    """Bancos do Kiro CLI e do VS Code guardam estado em SQLite."""
    achados: set[str] = set()
    try:
        conexao = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return achados
    try:
        cursor = conexao.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tabelas = [linha[0] for linha in cursor.fetchall()]
        for tabela in tabelas:
            try:
                cursor.execute(f'SELECT * FROM "{tabela}"')
            except sqlite3.Error:
                continue
            for linha in cursor.fetchall():
                for celula in linha:
                    if isinstance(celula, (str, bytes)):
                        texto = celula if isinstance(celula, str) else celula.decode("utf-8", "ignore")
                        achados.update(PADRAO.findall(texto))
    except sqlite3.Error:
        pass
    finally:
        conexao.close()
    return achados


def principal() -> int:
    print("=" * 74)
    print("TASK 1 - DESCOBERTA DO profileArn")
    print("=" * 74)
    print()

    diretorios = _diretorios()
    if not diretorios:
        print("Nenhum diretorio do Kiro encontrado.")
        return 1

    print("Diretorios varridos:")
    for d in diretorios:
        print(f"  {d}")
    print()

    encontrados: dict[str, list[str]] = {}
    arquivos_vistos = 0

    for base in diretorios:
        for caminho in base.rglob("*"):
            if not caminho.is_file():
                continue
            if caminho.suffix.lower() not in EXTENSOES:
                continue
            arquivos_vistos += 1
            if caminho.suffix.lower() in {".sqlite3", ".db", ".vscdb"}:
                achados = _varrer_sqlite(caminho)
            else:
                achados = _varrer_texto(caminho)
            for arn in achados:
                encontrados.setdefault(arn, []).append(caminho.name)

    print(f"Arquivos inspecionados: {arquivos_vistos}")
    print()

    if not encontrados:
        print("RESULTADO: nenhum profileArn encontrado nos arquivos locais.")
        print()
        print("Proximo caminho: perguntar a propria API do Kiro pela lista de")
        print("perfis disponiveis (ListAvailableProfiles), usando o access token")
        print("que o gateway ja sabe obter.")
        return 2

    print("RESULTADO: ARN(s) encontrado(s):")
    print()
    for arn, arquivos in encontrados.items():
        print(f"  {_mascarar(arn)}")
        for nome in sorted(set(arquivos))[:6]:
            print(f"      em: {nome}")
    print()

    destino = Path(__file__).resolve().parent / "_arn_encontrado.txt"
    destino.write_text("\n".join(sorted(encontrados)), encoding="utf-8")
    print(f"Valor real gravado em: {destino.name}")
    print("APAGUE esse arquivo depois de configurar o PROFILE_ARN no .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())

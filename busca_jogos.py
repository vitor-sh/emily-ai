"""Normalização de nomes e busca de jogos instalados (Steam, Epic, GOG, Program Files).

Saiu de automacao.py, que re-exporta tudo; ferramentas.py continua usando
automacao._normalizar_nome_app, automacao._similaridade etc.
"""
from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path
from typing import Optional

HOME = Path.home()


def _remover_acentos(texto: str) -> str:
    import unicodedata
    normalizado = unicodedata.normalize("NFD", texto)
    return "".join(c for c in normalizado if unicodedata.category(c) != "Mn")


def _normalizar(texto: str) -> str:
    return _remover_acentos(texto).lower().strip()


def _normalizar_nome_app(nome: str) -> str:
    """Remove extensão, parênteses, versões, hifens e normaliza."""
    nome = Path(nome).stem
    nome = re.sub(r"\(.*?\)", "", nome)
    nome = re.sub(r"[-_]", " ", nome)
    nome = re.sub(r"\s+", " ", nome)
    return _normalizar(nome).strip()


def _similaridade(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


# Executáveis que devem ser ignorados na hora de escolher o exe principal
_IGNORAR_EXE = {
    "unins", "uninstall", "setup", "install", "redist", "vcredist",
    "directx", "crashreport", "crashhandler", "helper", "updater",
    "launcher_helper", "dxsetup", "vc_redist", "unarc", "dotnet",
    "prerequisite", "activation", "eac", "easyanticheat", "battleye",
    "uplay", "ubisoft", "registry", "cleanup", "repair",
}


def _encontrar_exe_principal(pasta: Path, nome_hint: str = "") -> Optional[Path]:
    """
    Encontra o executável principal dentro de uma pasta de jogo/app.
    - Ignora instaladores, helpers e redistributáveis
    - Prefere o maior .exe direto na raiz da pasta
    - Usa similaridade com nome_hint para desempatar
    """
    nome_norm = _normalizar_nome_app(nome_hint) if nome_hint else ""
    exes: list[Path] = []

    try:
        for exe in pasta.rglob("*.exe"):
            nome_exe_lower = exe.stem.lower()
            if any(ignorar in nome_exe_lower for ignorar in _IGNORAR_EXE):
                continue
            exes.append(exe)
    except (OSError, PermissionError):
        pass

    if not exes:
        return None

   
    if nome_norm:
        melhor_sim = 0.0
        melhor_exe = None
        for exe in exes:
            sim = _similaridade(_normalizar_nome_app(exe.stem), nome_norm)
            if sim > melhor_sim:
                melhor_sim = sim
                melhor_exe = exe
        if melhor_sim > 0.55:
            return melhor_exe

    # Prefere exes diretos na raiz da pasta (não em subpastas)
    diretos = [e for e in exes if e.parent == pasta]
    pool = diretos if diretos else exes

    # Dentro do pool, pega o maior arquivo (geralmente o principal)
    try:
        return max(pool, key=lambda e: e.stat().st_size)
    except Exception:
        return pool[0]


def _get_steam_libraries() -> list[Path]:
    """
    Retorna todas as pastas steamapps/common do usuário.
    Lê o libraryfolders.vdf pra pegar bibliotecas em outros discos também.
    """
    steam_roots = [
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Steam",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Steam",
        Path("C:/Steam"),
        HOME / "Steam",
    ]

    libraries: list[Path] = []

    for steam_root in steam_roots:
        if not steam_root.exists():
            continue

        # Pasta padrão steamapps/common
        common = steam_root / "steamapps" / "common"
        if common.exists() and common not in libraries:
            libraries.append(common)

        # Bibliotecas extras via libraryfolders.vdf
        vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
        if vdf_path.exists():
            try:
                conteudo = vdf_path.read_text(encoding="utf-8", errors="ignore")
                # Extrai todos os valores de "path" no arquivo vdf
                caminhos_extras = re.findall(r'"path"\s+"([^"]+)"', conteudo)
                for caminho_str in caminhos_extras:
                    # O VDF usa barra dupla como separador
                    caminho_str = caminho_str.replace("\\\\", "\\")
                    pasta_extra = Path(caminho_str) / "steamapps" / "common"
                    if pasta_extra.exists() and pasta_extra not in libraries:
                        libraries.append(pasta_extra)
            except Exception:
                pass

    return libraries


def _buscar_jogo_steam(nome_jogo: str) -> Optional[Path]:
    """
    Busca um jogo em todas as bibliotecas Steam do usuário,
    incluindo bibliotecas em outros discos.
    """
    nome_norm = _normalizar_nome_app(nome_jogo)
    if not nome_norm:
        return None

    for steam_common in _get_steam_libraries():
        try:
            for pasta_jogo in steam_common.iterdir():
                if not pasta_jogo.is_dir():
                    continue

                pasta_norm = _normalizar_nome_app(pasta_jogo.name)
                sim = _similaridade(nome_norm, pasta_norm)

                # Aceita se o nome está contido, ou há boa similaridade,
                # ou todos os tokens do pedido aparecem no nome da pasta
                tokens_pedido = [t for t in nome_norm.split() if len(t) > 2]
                tokens_ok = tokens_pedido and all(t in pasta_norm for t in tokens_pedido)

                if (nome_norm in pasta_norm or pasta_norm in nome_norm
                        or sim > 0.55 or tokens_ok):
                    exe = _encontrar_exe_principal(pasta_jogo, nome_jogo)
                    if exe:
                        print(f"[DEBUG automacao] Jogo Steam: '{pasta_jogo.name}' → {exe.name}")
                        return exe
        except (OSError, PermissionError):
            continue

    return None


def _buscar_jogo_epic(nome_jogo: str) -> Optional[Path]:
    """
    Busca um jogo instalado pelo Epic Games lendo os manifests (.item).
    Os manifests ficam em C:/ProgramData/Epic/EpicGamesLauncher/Data/Manifests
    """
    manifests_dir = Path("C:/ProgramData/Epic/EpicGamesLauncher/Data/Manifests")
    if not manifests_dir.exists():
        return None

    nome_norm = _normalizar_nome_app(nome_jogo)

    try:
        for manifest_file in manifests_dir.glob("*.item"):
            try:
                dados = json.loads(manifest_file.read_text(encoding="utf-8", errors="ignore"))
                display_name = dados.get("DisplayName", "")
                install_location = dados.get("InstallLocation", "")
                launch_exe = dados.get("LaunchExecutable", "")

                if not display_name or not install_location:
                    continue

                display_norm = _normalizar_nome_app(display_name)
                sim = _similaridade(nome_norm, display_norm)

                if (nome_norm in display_norm or display_norm in nome_norm or sim > 0.55):
                    print(f"[DEBUG automacao] Jogo Epic: '{display_name}'")
                    # Usa o executável registrado no manifest
                    if launch_exe:
                        exe_path = Path(install_location) / launch_exe
                        if exe_path.exists():
                            return exe_path
                    # Fallback: procura o principal na pasta de instalação
                    return _encontrar_exe_principal(Path(install_location), nome_jogo)

            except Exception:
                continue
    except (OSError, PermissionError):
        pass

    return None


def _buscar_jogo_gog(nome_jogo: str) -> Optional[Path]:
    """Busca jogos instalados pelo GOG Galaxy."""
    gog_dirs = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "GOG Galaxy" / "Games",
        Path(os.environ.get("ProgramFiles", "")) / "GOG Galaxy" / "Games",
        Path("C:/GOG Games"),
        HOME / "GOG Games",
    ]

    nome_norm = _normalizar_nome_app(nome_jogo)

    for gog_dir in gog_dirs:
        if not gog_dir.exists():
            continue
        try:
            for pasta_jogo in gog_dir.iterdir():
                if not pasta_jogo.is_dir():
                    continue
                pasta_norm = _normalizar_nome_app(pasta_jogo.name)
                sim = _similaridade(nome_norm, pasta_norm)
                if nome_norm in pasta_norm or pasta_norm in nome_norm or sim > 0.55:
                    exe = _encontrar_exe_principal(pasta_jogo, nome_jogo)
                    if exe:
                        print(f"[DEBUG automacao] Jogo GOG: '{pasta_jogo.name}' → {exe.name}")
                        return exe
        except (OSError, PermissionError):
            continue

    return None


def _buscar_jogo_em_program_files(nome_jogo: str) -> Optional[Path]:
    """
    Busca um jogo/app varrendo Program Files com até 3 níveis de profundidade.
    Útil para jogos que não estão no Steam, Epic ou GOG.
    """
    program_files = [
        Path(os.environ.get("ProgramFiles", "C:/Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
    ]

    nome_norm = _normalizar_nome_app(nome_jogo)
    if not nome_norm:
        return None
    


    def _pasta_combina(pasta_norm: str) -> bool:
        sim = _similaridade(nome_norm, pasta_norm)
        tokens_pedido = [t for t in nome_norm.split() if len(t) > 2]
        tokens_ok = tokens_pedido and all(t in pasta_norm for t in tokens_pedido)
        return nome_norm in pasta_norm or pasta_norm in nome_norm or sim > 0.55 or tokens_ok

    for raiz in program_files:
        if not raiz.exists():
            continue
        try:
            for nivel1 in raiz.iterdir():
                if not nivel1.is_dir():
                    continue
                nivel1_norm = _normalizar_nome_app(nivel1.name)
                if _pasta_combina(nivel1_norm):
                    exe = _encontrar_exe_principal(nivel1, nome_jogo)
                    if exe:
                        print(f"[DEBUG automacao] ProgramFiles nível1: '{nivel1.name}' → {exe.name}")
                        return exe

                # Vai um nível mais fundo
                try:
                    for nivel2 in nivel1.iterdir():
                        if not nivel2.is_dir():
                            continue
                        nivel2_norm = _normalizar_nome_app(nivel2.name)
                        if _pasta_combina(nivel2_norm):
                            exe = _encontrar_exe_principal(nivel2, nome_jogo)
                            if exe:
                                print(f"[DEBUG automacao] ProgramFiles nível2: '{nivel2.name}' → {exe.name}")
                                return exe
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            continue

    return None


def _buscar_pasta_em_drive(nome: str, drive: Path, max_depth: int = 4) -> Optional[Path]:
    """
    Busca uma pasta pelo nome dentro de um drive específico.
    Prioriza bibliotecas Steam, depois faz busca geral com profundidade limitada.
    """
    nome_norm = _normalizar_nome_app(nome)
    if not nome_norm:
        return None

    # Pastas do sistema que não vale a pena varrer
    IGNORAR = {
        "windows", "system32", "syswow64", "winsxs", "$recycle.bin",
        "system volume information", "recovery", "perflogs", "boot"
    }

    def _combina(pasta_norm: str) -> bool:
        if not pasta_norm:
            return False
        sim = _similaridade(nome_norm, pasta_norm)
        tokens = [t for t in nome_norm.split() if len(t) > 2]
        tokens_ok = bool(tokens) and all(t in pasta_norm for t in tokens)
        return nome_norm in pasta_norm or pasta_norm in nome_norm or sim > 0.65 or tokens_ok
       
    # Primeiro tenta nas bibliotecas Steam que estão nesse drive
    for steam_lib in _get_steam_libraries():
        if steam_lib.drive.upper() == drive.drive.upper():
            try:
                for pasta_jogo in steam_lib.iterdir():
                    if pasta_jogo.is_dir() and _combina(_normalizar_nome_app(pasta_jogo.name)):
                        print(f"[DEBUG automacao] Pasta no drive via Steam: {pasta_jogo}")
                        return pasta_jogo
            except (OSError, PermissionError):
                pass

    # Busca geral no drive com profundidade limitada
    def _buscar(pasta: Path, depth: int) -> Optional[Path]:
        if depth == 0:
            return None
        try:
            for sub in pasta.iterdir():
                if not sub.is_dir():
                    continue
                if _normalizar(sub.name) in IGNORAR:
                    continue
                if _combina(_normalizar_nome_app(sub.name)):
                    print(f"[DEBUG automacao] Pasta encontrada no drive: {sub}")
                    return sub
                resultado = _buscar(sub, depth - 1)
                if resultado:
                    return resultado
        except (OSError, PermissionError):
            pass
        return None

    return _buscar(drive, max_depth)

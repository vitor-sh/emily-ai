"""
Camada de compatibilidade entre plataformas.

Este módulo detecta o sistema operacional e fornece abstrações
para funcionalidades que variam entre Windows e Linux.
"""

import os
import sys
import platform
import subprocess
from pathlib import Path
from typing import Dict, Optional, List


# ══════════════════════════════════════════════════════════════════════════════
# DETECÇÃO DE SISTEMA OPERACIONAL
# ══════════════════════════════════════════════════════════════════════════════

def is_windows() -> bool:
    """Retorna True se está rodando no Windows"""
    return os.name == "nt" or sys.platform == "win32"


def is_linux() -> bool:
    """Retorna True se está rodando no Linux"""
    return sys.platform.startswith("linux")


def get_os_name() -> str:
    """Retorna nome amigável do sistema operacional"""
    if is_windows():
        return "Windows"
    elif is_linux():
        return "Linux"
    else:
        return platform.system()


# ══════════════════════════════════════════════════════════════════════════════
# DETECÇÃO DE DESKTOP ENVIRONMENT (LINUX)
# ══════════════════════════════════════════════════════════════════════════════

def get_desktop_environment() -> str:
    """
    Detecta o Desktop Environment do Linux.

    Retorna: "gnome", "kde", "xfce", "cinnamon", "mate", "lxde" ou "unknown"
    """
    if not is_linux():
        return "unknown"

    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()

    # Mapeamento de variantes para nomes canônicos
    if "gnome" in desktop:
        return "gnome"
    elif "kde" in desktop or "plasma" in desktop:
        return "kde"
    elif "xfce" in desktop:
        return "xfce"
    elif "cinnamon" in desktop:
        return "cinnamon"
    elif "mate" in desktop:
        return "mate"
    elif "lxde" in desktop or "lxqt" in desktop:
        return "lxde"

    # Fallback: tentar detectar pelo processo do window manager
    try:
        wm_process = subprocess.run(
            ["ps", "-e"],
            capture_output=True,
            text=True,
            timeout=2
        )
        processes = wm_process.stdout.lower()

        if "gnome-shell" in processes:
            return "gnome"
        elif "plasmashell" in processes or "kwin" in processes:
            return "kde"
        elif "xfwm4" in processes:
            return "xfce"
        elif "cinnamon" in processes:
            return "cinnamon"
        elif "mate-panel" in processes:
            return "mate"
    except:
        pass

    return "unknown"


# ══════════════════════════════════════════════════════════════════════════════
# PASTAS ESPECIAIS (CROSS-PLATFORM)
# ══════════════════════════════════════════════════════════════════════════════

def get_special_folders() -> Dict[str, Path]:
    """
    Retorna dicionário com pastas especiais do sistema.

    Chaves: desktop, documents, downloads, music, pictures, videos, home
    """
    if is_windows():
        return _get_special_folders_windows()
    else:
        return _get_special_folders_linux()


def _get_special_folders_windows() -> Dict[str, Path]:
    """Obtém pastas especiais do Windows via Registry"""
    try:
        import winreg

        folders = {}
        home = Path.home()

        # Abrir chave do Shell Folders
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        ) as key:
            try:
                folders["desktop"] = Path(winreg.QueryValueEx(key, "Desktop")[0])
            except:
                folders["desktop"] = home / "Desktop"

            try:
                folders["documents"] = Path(winreg.QueryValueEx(key, "Personal")[0])
            except:
                folders["documents"] = home / "Documents"

            try:
                # GUID do Downloads: {374DE290-123F-4565-9164-39C4925E467B}
                folders["downloads"] = Path(winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")[0])
            except:
                folders["downloads"] = home / "Downloads"

            try:
                folders["music"] = Path(winreg.QueryValueEx(key, "My Music")[0])
            except:
                folders["music"] = home / "Music"

            try:
                folders["pictures"] = Path(winreg.QueryValueEx(key, "My Pictures")[0])
            except:
                folders["pictures"] = home / "Pictures"

            try:
                folders["videos"] = Path(winreg.QueryValueEx(key, "My Video")[0])
            except:
                folders["videos"] = home / "Videos"

        folders["home"] = home
        return folders

    except ImportError:
        # winreg não disponível (não deveria acontecer no Windows, mas fallback)
        return _get_special_folders_linux()


def _get_special_folders_linux() -> Dict[str, Path]:
    """Obtém pastas especiais do Linux via XDG"""
    home = Path.home()
    folders = {}

    # Tentar ler de ~/.config/user-dirs.dirs
    user_dirs_file = home / ".config/user-dirs.dirs"

    if user_dirs_file.exists():
        try:
            with open(user_dirs_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    if "=" in line:
                        key, value = line.split("=", 1)
                        # Remove aspas e substitui $HOME
                        value = value.strip('"').replace("$HOME", str(home))

                        # Mapear XDG_* para nossas chaves
                        if key == "XDG_DESKTOP_DIR":
                            folders["desktop"] = Path(value)
                        elif key == "XDG_DOCUMENTS_DIR":
                            folders["documents"] = Path(value)
                        elif key == "XDG_DOWNLOAD_DIR":
                            folders["downloads"] = Path(value)
                        elif key == "XDG_MUSIC_DIR":
                            folders["music"] = Path(value)
                        elif key == "XDG_PICTURES_DIR":
                            folders["pictures"] = Path(value)
                        elif key == "XDG_VIDEOS_DIR":
                            folders["videos"] = Path(value)
        except:
            pass

    # Fallbacks padrão
    folders.setdefault("desktop", home / "Desktop")
    folders.setdefault("documents", home / "Documents")
    folders.setdefault("downloads", home / "Downloads")
    folders.setdefault("music", home / "Music")
    folders.setdefault("pictures", home / "Pictures")
    folders.setdefault("videos", home / "Videos")
    folders["home"] = home

    return folders


# ══════════════════════════════════════════════════════════════════════════════
# CAMINHOS DE PROGRAMAS COMUNS
# ══════════════════════════════════════════════════════════════════════════════

def get_common_programs() -> Dict[str, str]:
    """
    Retorna dicionário com caminhos de programas comuns.

    Chave: nome do programa (lowercase)
    Valor: caminho do executável
    """
    if is_windows():
        return _get_common_programs_windows()
    else:
        return _get_common_programs_linux()


def _get_common_programs_windows() -> Dict[str, str]:
    """Caminhos de programas comuns no Windows"""
    # TODO: Implementar busca dinâmica no Registry e Program Files
    # Por enquanto, retornar apenas os básicos que funcionam via PATH
    return {
        "explorer": "explorer.exe",
        "arquivos": "explorer.exe",
        "notepad": "notepad.exe",
        "bloco de notas": "notepad.exe",
        "calc": "calc.exe",
        "calculadora": "calc.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
    }


def _get_common_programs_linux() -> Dict[str, str]:
    """Caminhos de programas comuns no Linux"""
    de = get_desktop_environment()

    # Gerenciador de arquivos baseado no DE
    file_manager = "nautilus"  # GNOME (padrão)
    terminal = "gnome-terminal"

    if de == "kde":
        file_manager = "dolphin"
        terminal = "konsole"
    elif de == "xfce":
        file_manager = "thunar"
        terminal = "xfce4-terminal"
    elif de == "cinnamon":
        file_manager = "nemo"
        terminal = "gnome-terminal"
    elif de == "mate":
        file_manager = "caja"
        terminal = "mate-terminal"

    programs = {
        # Gerenciadores de arquivo (nomes comuns)
        "explorer": file_manager,
        "arquivos": file_manager,
        "files": file_manager,
        "nautilus": "nautilus",
        "dolphin": "dolphin",
        "thunar": "thunar",
        "nemo": "nemo",

        # Editores de texto
        "notepad": "gedit" if de == "gnome" else "kate" if de == "kde" else "mousepad",
        "bloco de notas": "gedit" if de == "gnome" else "kate",
        "gedit": "gedit",
        "kate": "kate",
        "nano": "nano",
        "vim": "vim",
        "code": "code",
        "vscode": "code",

        # Calculadora
        "calc": "gnome-calculator" if de == "gnome" else "kcalc" if de == "kde" else "galculator",
        "calculadora": "gnome-calculator" if de == "gnome" else "kcalc",

        # Terminal
        "terminal": terminal,
        "cmd": terminal,
        "powershell": "bash",  # Mapear PowerShell para Bash

        # Navegadores
        "chrome": "google-chrome-stable",
        "firefox": "firefox",
        "brave": "brave-browser",
        "edge": "microsoft-edge",

        # Comunicação
        "discord": "discord",
        "telegram": "telegram-desktop",
        "slack": "slack",

        # Mídia
        "spotify": "spotify",
        "vlc": "vlc",

        # Jogos
        "steam": "steam",
    }

    return programs


# ══════════════════════════════════════════════════════════════════════════════
# UTILITÁRIOS
# ══════════════════════════════════════════════════════════════════════════════

def which(command: str) -> Optional[str]:
    """
    Encontra o caminho completo de um comando.

    Equivalente ao `which` do Linux ou `where` do Windows.
    """
    import shutil
    return shutil.which(command)


def command_exists(command: str) -> bool:
    """Verifica se um comando existe no PATH"""
    return which(command) is not None


# ══════════════════════════════════════════════════════════════════════════════
# TESTES / DEBUG
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== Platform Compatibility Test ===")
    print(f"OS: {get_os_name()}")
    print(f"Windows: {is_windows()}")
    print(f"Linux: {is_linux()}")

    if is_linux():
        print(f"Desktop Environment: {get_desktop_environment()}")

    print("\n=== Special Folders ===")
    folders = get_special_folders()
    for name, path in folders.items():
        exists = "✓" if path.exists() else "✗"
        print(f"{exists} {name}: {path}")

    print("\n=== Common Programs ===")
    programs = get_common_programs()
    for name, cmd in list(programs.items())[:10]:  # Mostrar só os 10 primeiros
        exists = "✓" if command_exists(cmd.split()[0]) else "✗"
        print(f"{exists} {name}: {cmd}")

    print(f"\n... e mais {len(programs) - 10} programas")

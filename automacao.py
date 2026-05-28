from __future__ import annotations

from agente_jogo import iniciar_agente, pausar_agente, continuar_agente, parar_agente, status_agente
import difflib
import json
import os
import re
import shutil
from modelo import EMILY_PERSONALIDADE
import subprocess
import threading
import time

try:
    import keyboard as _kb
    _KB_DISPONIVEL = True
except ImportError:
    _KB_DISPONIVEL = False
    print("[SPEEDRUN] Módulo 'keyboard' não encontrado. Instala com: pip install keyboard")

import webbrowser
from pathlib import Path
from typing import Dict, Iterable, Optional
from openai import OpenAI

_fw_client = OpenAI(
    api_key=os.getenv("FIREWORKS_API_KEY2"),
    base_url="https://api.fireworks.ai/inference/v1",
)

_callback_status = None

def definir_callback_status(callback):
    global _callback_status
    _callback_status = callback

# ─────────────────────────────────────────────────────────────────
# OPERAÇÕES DE ARQUIVO COM DIALOGO NATIVO DO WINDOWS
# ─────────────────────────────────────────────────────────────────

_FO_MOVE = 0x0001
_FO_COPY = 0x0002
_FOF_NOCONFIRMMKDIR = 0x0200
_FOF_ALLOWUNDO      = 0x0040

_LIMITE_DIALOGO_BYTES = 500 * 1024 * 1024  # 500MB — acima disso usa janela do Windows

# Ações que não precisam de confirmação por voz quando bem-sucedidas
ACOES_SILENCIOSAS = {
    "abrir_app",
    "abrir_site",
    "abrir_jogo",
    "abrir_pasta",
    "abrir_arquivo",
    "abrir_exe",
    "fechar_app",
    "fechar_aba",
    "minimizar_app",
    "maximizar_app",
    "tocar_musica",
    "controle_musica",
}

def _tamanho_bytes(caminho: Path) -> int:
    """Calcula o tamanho total de um arquivo ou pasta em bytes."""
    try:
        if caminho.is_file():
            return caminho.stat().st_size
        total = 0
        for f in caminho.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except (OSError, PermissionError):
                pass
        return total
    except Exception:
        return 0


def _shell_fileop(operacao: int, origem: Path, destino: Path) -> bool:
    """
    Copia ou move usando a API Shell do Windows.
    Mostra a janela de progresso nativa (igual ao Explorer) e roda em thread separada.
    """
    if os.name != "nt":
        return False

    import ctypes
    import ctypes.wintypes as wt

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd",                  wt.HWND),
            ("wFunc",                 wt.UINT),
            ("pFrom",                 wt.LPCWSTR),
            ("pTo",                   wt.LPCWSTR),
            ("fFlags",                ctypes.c_ushort),
            ("fAnyOperationsAborted", wt.BOOL),
            ("hNameMappings",         ctypes.c_void_p),
            ("lpszProgressTitle",     wt.LPCWSTR),
        ]

    op = SHFILEOPSTRUCTW()
    op.hwnd   = None
    op.wFunc  = operacao
    op.pFrom  = str(origem) + "\0\0"   # SHFileOperation exige duplo \0 no fim
    op.pTo    = str(destino) + "\0\0"
    op.fFlags = _FOF_NOCONFIRMMKDIR | _FOF_ALLOWUNDO

    try:
        ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return ret == 0 and not op.fAnyOperationsAborted
    except Exception as e:
        print(f"[DEBUG automacao] SHFileOperation falhou: {e}")
        return False


def _fileop_async(operacao: int, origem: Path, destino: Path, callback=None) -> None:
    """
    Roda _shell_fileop em thread separada pra Emily não travar.
    Se callback for passado, ele é chamado quando a operação terminar com sucesso.
    """
    def _run():
        sucesso = _shell_fileop(operacao, origem, destino)
        if sucesso and callback:
            try:
                callback()
            except Exception as e:
                print(f"[DEBUG automacao] Callback de undo falhou: {e}")

    threading.Thread(target=_run, daemon=True).start()

def _enviar_para_lixeira(caminho: Path) -> bool:
    """Envia arquivo ou pasta para a Lixeira do Windows."""
    if os.name != "nt":
        # Linux/Mac: deleta direto mesmo
        try:
            caminho.unlink() if caminho.is_file() else shutil.rmtree(str(caminho))
            return True
        except Exception:
            return False

    import ctypes
    import ctypes.wintypes as wt

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd",                  wt.HWND),
            ("wFunc",                 wt.UINT),
            ("pFrom",                 wt.LPCWSTR),
            ("pTo",                   wt.LPCWSTR),
            ("fFlags",                ctypes.c_ushort),
            ("fAnyOperationsAborted", wt.BOOL),
            ("hNameMappings",         ctypes.c_void_p),
            ("lpszProgressTitle",     wt.LPCWSTR),
        ]

    _FO_DELETE      = 0x0003
    _FOF_ALLOWUNDO  = 0x0040   # ← essa flag é o que manda pra Lixeira em vez de deletar direto
    _FOF_NOCONFIRM  = 0x0010
    _FOF_NOERRORUI  = 0x0400

    op = SHFILEOPSTRUCTW()
    op.hwnd   = None
    op.wFunc  = _FO_DELETE
    op.pFrom  = str(caminho) + "\0\0"
    op.pTo    = None
    op.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRM | _FOF_NOERRORUI

    try:
        ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return ret == 0 and not op.fAnyOperationsAborted
    except Exception as e:
        print(f"[DEBUG automacao] Erro ao enviar pra lixeira: {e}")
        return False

import json as _json_cache

_CACHE_PATH = Path.home() / ".emily_cache.json"
_LLM_CACHE_PATH = Path.home() / ".emily_llm_cache.json"
_LLM_CACHE_MAX = 300  # número máximo de comandos guardados
_cache_memoria: dict = {}
_cache_memoria_carregado = False

_llm_cache_memoria: dict = {}
_llm_cache_memoria_carregado = False

def _contem_palavra(texto: str, keyword: str) -> bool:
    """Verifica se a keyword é uma palavra completa no texto, não parte de outra."""
    if ' ' in keyword:
        return keyword in texto
    return bool(re.search(r'\b' + re.escape(keyword) + r'\b', texto))


def _carregar_cache() -> dict:
    global _cache_memoria, _cache_memoria_carregado
    if not _cache_memoria_carregado:
        try:
            if _CACHE_PATH.exists():
                _cache_memoria = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _cache_memoria = {}
        _cache_memoria_carregado = True
    return _cache_memoria


def _salvar_cache(cache: dict) -> None:
    try:
        _CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"[DEBUG automacao] Erro ao salvar cache: {e}")


def _cache_get(chave: str) -> Optional[Path]:
    cache = _carregar_cache()
    caminho_str = cache.get(chave.lower().strip())
    if caminho_str:
        caminho = Path(caminho_str)
        if caminho.exists():
            return caminho
        cache.pop(chave.lower().strip())
        _salvar_cache(cache)
    return None


def _cache_set(chave: str, caminho: Path) -> None:
    cache = _carregar_cache()
    cache[chave.lower().strip()] = str(caminho)
    _salvar_cache(cache)


def _llm_cache_get(mensagem: str) -> Optional[dict]:
    global _llm_cache_memoria, _llm_cache_memoria_carregado
    if not _llm_cache_memoria_carregado:
        try:
            if _LLM_CACHE_PATH.exists():
                _llm_cache_memoria = json.loads(_LLM_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _llm_cache_memoria = {}
        _llm_cache_memoria_carregado = True
    return _llm_cache_memoria.get(mensagem.lower().strip())


def _llm_cache_set(mensagem: str, resultado: dict) -> None:
    global _llm_cache_memoria
    _llm_cache_get("")  # garante que o dicionário foi carregado

    chave = _normalizar_para_cache(mensagem)
    _llm_cache_memoria[chave] = resultado

    if len(_llm_cache_memoria) > _LLM_CACHE_MAX:
        chaves_para_remover = list(_llm_cache_memoria.keys())[:100]
        for k in chaves_para_remover:
            del _llm_cache_memoria[k]

    try:
        _LLM_CACHE_PATH.write_text(
            json.dumps(_llm_cache_memoria, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"[DEBUG automacao] Erro ao salvar LLM cache: {e}")

def _descobrir_pasta_especial(shell_name: str) -> Optional[Path]:
    """
    Lê o registro do Windows pra pegar o caminho real de pastas especiais.
    Funciona mesmo quando o OneDrive redirecionou a pasta pra outro lugar.
    """
    if os.name != "nt":
        return None
    try:
        import winreg
        chave = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        )
        valor, _ = winreg.QueryValueEx(chave, shell_name)
        winreg.CloseKey(chave)
        caminho = Path(valor)
        return caminho if caminho.exists() else None
    except Exception:
        return None

HOME = Path.home()
_DESKTOP_REAL     = _descobrir_pasta_especial("Desktop")
_DOCUMENTS_REAL   = _descobrir_pasta_especial("Personal")
_DOWNLOADS_REAL   = _descobrir_pasta_especial("{374DE290-123F-4565-9164-39C4925E467B}")
_PICTURES_REAL    = _descobrir_pasta_especial("My Pictures")
_MUSIC_REAL       = _descobrir_pasta_especial("My Music")
_VIDEOS_REAL      = _descobrir_pasta_especial("My Video")

CANDIDATE_ROOTS = [
    Path.cwd(),
    HOME,
    HOME / "Desktop",
    HOME / "Área de Trabalho",
    HOME / "Downloads",
    HOME / "Documents",
    HOME / "Documentos",
    HOME / "Pictures",
    HOME / "Imagens",
    HOME / "Videos",
    HOME / "Vídeos",
    HOME / "Music",
    HOME / "Músicas",
]

SHELL_FOLDERS = {
    "lixeira": "shell:RecycleBinFolder",
    "area de trabalho": "shell:Desktop",
    "área de trabalho": "shell:Desktop",
    "desktop": "shell:Desktop",
    "documentos": "shell:Personal",
    "downloads": "shell:Downloads",
    "imagens": "shell:My Pictures",
    "musicas": "shell:My Music",
    "músicas": "shell:My Music",
    "videos": "shell:My Video",
    "vídeos": "shell:My Video",
    "controle": "control",
    "painel de controle": "control",
}

APP_ALIASES = {
    "brave": "brave",
    "brave browser": "brave",
    "navegador": "browser",
    "browser": "browser",
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
    "firefox": "firefox",
    "mozilla": "firefox",
    "explorer": "explorer",
    "gerenciador de arquivos": "explorer",
    "arquivos": "explorer",
    "meu computador": "explorer",
    "computador": "explorer",
    "bloco de notas": "notepad",
    "notepad": "notepad",
    "calculadora": "calc",
    "calc": "calc",
    "cmd": "cmd",
    "prompt de comando": "cmd",
    "terminal": "terminal",
    "powershell": "powershell",
    "vscode": "vscode",
    "vs code": "vscode",
    "visual studio code": "vscode",
    "discord": "discord",
    "steam": "steam",
    "spotify": "spotify",
    "lixeira": "lixeira",
    "recycle bin": "lixeira",
    "epic": "epic",
    "epic games": "epic",
    "telegram": "telegram",
    "whatsapp": "whatsapp",
    "obs": "obs",
    "obs studio": "obs",
    "vlc": "vlc",
    "7zip": "7zip",
    "winrar": "winrar",
    "paint": "mspaint",
    "paint 3d": "paint",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "teams": "teams",
    "microsoft teams": "teams",
    "zoom": "zoom",
    "skype": "skype",
    "notepad++": "notepad++",
    "notepadpp": "notepad++",
    "sublime": "sublime_text",
    "sublime text": "sublime_text",
    "gimp": "gimp",
    "photoshop": "photoshop",
    "audacity": "audacity",
    "qbittorrent": "qbittorrent",
    "utorrent": "utorrent",
    "radmin": "radmin vpn",
    "radmin vpn": "radmin vpn",
    "anydesk": "anydesk",
    "teamviewer": "teamviewer",
    "virtualbox": "virtualbox",
    "vmware": "vmware",
    "putty": "putty",
    "winscp": "winscp",
    "filezilla": "filezilla",
    "postman": "postman",
    "insomnia": "insomnia",
    "figma": "figma",
    "notion": "notion",
    "slack": "slack",
    "cursor": "cursor",
}

WINDOWS_APP_CANDIDATES = {
    "brave": [
        Path(os.environ.get("ProgramFiles", "")) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
    ],
    "chrome": [
        Path(os.environ.get("ProgramFiles", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ],
    "edge": [
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ],
    "firefox": [
        Path(os.environ.get("ProgramFiles", "")) / "Mozilla Firefox" / "firefox.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Mozilla Firefox" / "firefox.exe",
    ],
    "vscode": [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft VS Code" / "Code.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft VS Code" / "Code.exe",
    ],
    "steam": [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Steam" / "steam.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Steam" / "steam.exe",
    ],
    "spotify": [
        Path(os.environ.get("APPDATA", "")) / "Spotify" / "Spotify.exe",
    ],
    "telegram": [
        Path(os.environ.get("APPDATA", "")) / "Telegram Desktop" / "Telegram.exe",
    ],
    "whatsapp": [
        Path(os.environ.get("LOCALAPPDATA", "")) / "WhatsApp" / "WhatsApp.exe",
    ],
    "epic": [
        Path(os.environ.get("ProgramFiles", "")) / "Epic Games" / "Launcher" / "Portal" / "Binaries" / "Win64" / "EpicGamesLauncher.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Epic Games" / "Launcher" / "Portal" / "Binaries" / "Win32" / "EpicGamesLauncher.exe",
    ],
    "obs": [
        Path(os.environ.get("ProgramFiles", "")) / "obs-studio" / "bin" / "64bit" / "obs64.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "obs-studio" / "bin" / "32bit" / "obs32.exe",
    ],
    "vlc": [
        Path(os.environ.get("ProgramFiles", "")) / "VideoLAN" / "VLC" / "vlc.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "VideoLAN" / "VLC" / "vlc.exe",
    ],
    "7zip": [
        Path(os.environ.get("ProgramFiles", "")) / "7-Zip" / "7zFM.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "7-Zip" / "7zFM.exe",
    ],
    "winrar": [
        Path(os.environ.get("ProgramFiles", "")) / "WinRAR" / "WinRAR.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "WinRAR" / "WinRAR.exe",
    ],
    "radmin vpn": [
        Path(os.environ.get("ProgramFiles", "")) / "Radmin VPN" / "RadminVPN.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Radmin VPN" / "RadminVPN.exe",
    ],
    "anydesk": [
        Path(os.environ.get("ProgramFiles", "")) / "AnyDesk" / "AnyDesk.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "AnyDesk" / "AnyDesk.exe",
        Path(os.environ.get("APPDATA", "")) / "AnyDesk" / "AnyDesk.exe",
    ],
    "teamviewer": [
        Path(os.environ.get("ProgramFiles", "")) / "TeamViewer" / "TeamViewer.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "TeamViewer" / "TeamViewer.exe",
    ],
    "virtualbox": [
        Path(os.environ.get("ProgramFiles", "")) / "Oracle" / "VirtualBox" / "VirtualBox.exe",
    ],
    "putty": [
        Path(os.environ.get("ProgramFiles", "")) / "PuTTY" / "putty.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "PuTTY" / "putty.exe",
    ],
    "filezilla": [
        Path(os.environ.get("ProgramFiles", "")) / "FileZilla FTP Client" / "filezilla.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "FileZilla FTP Client" / "filezilla.exe",
    ],
    "qbittorrent": [
        Path(os.environ.get("ProgramFiles", "")) / "qBittorrent" / "qbittorrent.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "qBittorrent" / "qbittorrent.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "qBittorrent" / "qbittorrent.exe",
    ],
    "postman": [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Postman" / "Postman.exe",
    ],
    "figma": [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Figma" / "Figma.exe",
    ],
    "notion": [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Notion" / "Notion.exe",
    ],
    "slack": [
        Path(os.environ.get("LOCALAPPDATA", "")) / "slack" / "slack.exe",
    ],
    "cursor": [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "cursor" / "Cursor.exe",
    ],
    "gimp": [
        Path(os.environ.get("ProgramFiles", "")) / "GIMP 2" / "bin" / "gimp-2.10.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "GIMP 2" / "bin" / "gimp-2.10.exe",
    ],
}

WINDOWS_PROCESS_CANDIDATES = {
    "brave": ["brave.exe"],
    "chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "firefox": ["firefox.exe"],
    "vscode": ["Code.exe"],
    "notepad": ["notepad.exe"],
    "calc": ["CalculatorApp.exe", "Calculator.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "terminal": ["WindowsTerminal.exe", "cmd.exe", "powershell.exe"],
    "radmin vpn": ["RadminVPN.exe"],
    "anydesk": ["AnyDesk.exe"],
    "teamviewer": ["TeamViewer.exe"],
    "obs": ["obs64.exe", "obs32.exe"],
    "discord": ["Discord.exe"],
    "steam": ["steam.exe"],
    "spotify": ["Spotify.exe"],
    "telegram": ["Telegram.exe"],
    "vlc": ["vlc.exe"],
    "slack": ["slack.exe"],
    "postman": ["Postman.exe"],
    "figma": ["Figma.exe"],
}

_CLASSES_NAVEGADOR = {"Chrome_WidgetWin_1", "MozillaWindowClass"}

# Mapa de pastas para uso em buscas de arquivo
def _pasta_lista(*caminhos) -> list[Path]:
    """Filtra None e caminhos que não existem, sem duplicatas."""
    vistos = set()
    resultado = []
    for p in caminhos:
        if p is None:
            continue
        chave = str(p)
        if chave in vistos:
            continue
        vistos.add(chave)
        if p.exists():
            resultado.append(p)
    return resultado

_PUBLIC_DESKTOP = Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Desktop"
PASTA_MAP: Dict[str, list[Path]] = {
    "desktop":          _pasta_lista(_DESKTOP_REAL,   HOME / "Desktop", HOME / "Área de Trabalho", _PUBLIC_DESKTOP),
    "area de trabalho": _pasta_lista(_DESKTOP_REAL,   HOME / "Desktop", HOME / "Área de Trabalho", _PUBLIC_DESKTOP),
    "área de trabalho": _pasta_lista(_DESKTOP_REAL,   HOME / "Desktop", HOME / "Área de Trabalho", _PUBLIC_DESKTOP),
    "downloads":        _pasta_lista(_DOWNLOADS_REAL, HOME / "Downloads"),
    "documentos":       _pasta_lista(_DOCUMENTS_REAL, HOME / "Documents", HOME / "Documentos"),
    "documents":        _pasta_lista(_DOCUMENTS_REAL, HOME / "Documents", HOME / "Documentos"),
    "imagens":          _pasta_lista(_PICTURES_REAL,  HOME / "Pictures", HOME / "Imagens"),
    "pictures":         _pasta_lista(_PICTURES_REAL,  HOME / "Pictures", HOME / "Imagens"),
    "videos":           _pasta_lista(_VIDEOS_REAL,    HOME / "Videos",   HOME / "Vídeos"),
    "musicas":          _pasta_lista(_MUSIC_REAL,     HOME / "Music",    HOME / "Músicas"),
    "appdata":          _pasta_lista(Path(os.environ.get("APPDATA", ""))),
    "localappdata":     _pasta_lista(Path(os.environ.get("LOCALAPPDATA", ""))),
    "program files":    _pasta_lista(
        Path(os.environ.get("ProgramFiles", "C:/Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")),
    ),
    "programas":        _pasta_lista(
        Path(os.environ.get("ProgramFiles", "C:/Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")),
    ),
    "steam":            _pasta_lista(
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Steam",
        Path(os.environ.get("ProgramFiles", "")) / "Steam",
    ),
    "jogos":            _pasta_lista(
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Steam" / "steamapps" / "common",
        Path(os.environ.get("ProgramFiles", "")) / "Steam" / "steamapps" / "common",
    ),
    "temp":             _pasta_lista(Path(os.environ.get("TEMP", "C:/Temp")), Path("C:/Temp")),
}

# Mapa de unidades/drives pelo nome ou letra
DRIVE_MAP: Dict[str, Path] = {
    # Unidade C — SSD Main
    "c":          Path("C:/"),
    "c:":         Path("C:/"),
    "unidade c":  Path("C:/"),
    "ssd":        Path("C:/"),
    "ssd main":   Path("C:/"),
    # Unidade D — Armazémzão 1
    "d":              Path("D:/"),
    "d:":             Path("D:/"),
    "unidade d":      Path("D:/"),
    "hd d":           Path("D:/"),
    "armazémzão 1":   Path("D:/"),
    "armazemzao 1":   Path("D:/"),
    "armazémzão1":    Path("D:/"),
    # Unidade E — NVME Games
    "e":              Path("E:/"),
    "e:":             Path("E:/"),
    "unidade e":      Path("E:/"),
    "hd e":           Path("E:/"),
    "nvme":           Path("E:/"),
    "nvme games":     Path("E:/"),
    "nvme - games":   Path("E:/"),
    # Unidade H — Armazémzão 2
    "h":              Path("H:/"),
    "h:":             Path("H:/"),
    "unidade h":      Path("H:/"),
    "hd h":           Path("H:/"),
    "armazémzão 2":   Path("H:/"),
    "armazemzao 2":   Path("H:/"),
    "armazémzão2":    Path("H:/"),
}

# Drives que a Emily não pode mexer
DRIVES_BLOQUEADOS = {"g", "g:"}

KEYWORDS_ABRIR = (
    "abrir", "abre", "abra", "iniciar", "inicia", "inicie",
    "executar", "executa", "rodar", "roda", "abrindo",
    "coloca", "colocar", "liga", "ligar", "carrega", "carregar",
    "chama", "chamar", "lança", "lançar", "vai no", "entra no", "acessa",
    "joga", "jogar", "jogar o", "iniciar o jogo", "abrir o jogo",
)

KEYWORDS_RECORTAR = (
    "mover", "move", "transfere", "transferir",
    "mandar", "mudar", "deslocar", "recortar", "recorta", "recorte", "corta", "cortar",
)

KEYWORDS_COPIAR = (
    "copiar", "copia", "copie", "duplicar", "duplica",
    "fazer cópia", "faz cópia", "copia pra", "copiar pra"
)

KEYWORDS_RENOMEAR = (
    "renomear", "renomeia", "renomeie", "muda o nome",
    "mudar o nome", "muda nome", "troca o nome", "trocar o nome",
)

KEYWORDS_DESFAZER = (
    "desfazer", "desfaz", "ctrl z", "voltar", "reverter",
    "undo", "cancela isso", "cancela o que fez",
)

KEYWORDS_SITE = (
    "site", "vai no", "entra no", "acessa", "abre o site",
    "youtube", "google", "spotify", "netflix", "twitch",
)

KEYWORDS_FECHAR = (
    "fechar", "fecha", "feche", "encerrar", "encerra", "encerre",
    "desligar", "desliga", "desligue", "finalizar", "finaliza", "finalize",
)

KEYWORDS_MINIMIZAR = (
    "minimiza", "minimizar", "minimize", "esconde a janela", "esconder a janela",
)

KEYWORDS_MAXIMIZAR = (
    "maximiza", "maximizar", "maximize", "expande a janela", "expandir a janela",
)

KEYWORDS_FECHAR_ABA = (
    "fecha a aba", "fechar a aba", "fecha essa aba", "fecha o youtube",
    "fecha o netflix", "fecha o twitch", "fecha a aba do",
)

KEYWORDS_DELETAR = (
    "deletar", "deleta", "delete", "apagar", "apaga",
    "apague", "excluir", "exclui", "exclua", "remover",
    "remove", "remova", "jogar fora", "joga fora",
)

# Palavras que indicam que o comando é sobre arquivos selecionados no Explorer
KEYWORDS_SELECIONADOS = (
    "selecionados", "selecionadas", "selecionado", "selecionada",
    "arquivos selecionados", "os selecionados", "esses arquivos",
    "esses arquivos selecionados", "todos selecionados",
)

KEYWORDS_CRIAR = (
    "criar", "cria", "crie", "novo", "nova",
    "cria um", "cria uma", "criar um", "criar uma",
    "faz um", "faz uma", "fazer um", "fazer uma",
    
)

KEYWORDS_EXTRAIR = (
    "extrair", "extrai", "extraia", "descompactar", "descompacta",
    "descompacte", "deszipar", "deszipar", "unzip", "abrir o zip",
    "abrir o rar", "abrir o 7z",
)

# Palavras que indicam claramente um jogo (reforçam a busca nas bibliotecas)
KEYWORDS_JOGO = (
    "jogo", "game", "jogar", "steam", "epic", "gog",
    "hollow knight", "minecraft", "roblox",
)

KEYWORDS_AGENTE_INICIAR = (
    "inicia o agente", "iniciar o agente", "começa o agente",
    "ativa o agente", "agente do", "agente pra",
)

KEYWORDS_AGENTE_PAUSAR = (
    "pausa o agente", "pausar o agente",
)

KEYWORDS_AGENTE_CONTINUAR = (
    "continua o agente", "continuar o agente", "retoma o agente",
)

KEYWORDS_AGENTE_PARAR = (
    "para o agente", "parar o agente", "cancela o agente", "encerra o agente",
)

KEYWORDS_STEAM_INSTALAR = (
    "instala", "instalar", "instale", "baixa o jogo",
    "baixar o jogo", "instala o jogo",
)

KEYWORDS_STEAM_DESINSTALAR = (
    "desinstala", "desinstalar", "desinstale",
    "remove da steam", "apaga da steam", "deleta da steam",
    "remove o jogo", "desinstala o jogo",

)

KEYWORDS_MUSICA = (
    "toca", "tocar", "coloca", "play", "ouvir", "quero ouvir",
    "bota", "liga", "abre a música", "abre a musica",
)

KEYWORDS_CONTROLE_MUSICA = (
    "próxima música", "proxima musica", "próxima", "próximo", "skip",
    "música anterior", "musica anterior", "anterior", "voltar música",
    "pausa a música", "pausa musica", "pausar", "pausa", "pause",
    "retoma", "retomar", "continua a música", "continuar música",
    "aumenta o volume", "aumentar volume", "sobe o volume",
    "diminui o volume", "diminuir volume", "baixa o volume",
    "muta", "mutar", "sem som", "silencia",
)

# ─────────────────────────────────────────────────────────────────
# ÍNDICE AUTOMÁTICO DE APPS INSTALADOS
# ─────────────────────────────────────────────────────────────────

_PASTA_ATALHOS = [
    Path(os.environ.get("ProgramData", "C:/ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    HOME / "Desktop",
    HOME / "Área de Trabalho",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps",
    Path(os.environ.get("ProgramFiles", "C:/Program Files")),
    Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")),
]

_EXTENSOES_APP = {".lnk", ".exe", ".url"}
_indice_apps: Dict[str, Path] = {}
_indice_construido = False


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


def _tokens(texto: str) -> list[str]:
    return [t for t in _normalizar(texto).split() if len(t) >= 3]


def _similaridade(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def construir_indice_apps(forcar=False) -> Dict[str, Path]:
    global _indice_apps, _indice_construido

    if _indice_construido and not forcar:
        return _indice_apps

    indice: Dict[str, Path] = {}

    pastas_recursivas = _PASTA_ATALHOS[:6]
    pastas_rasa = _PASTA_ATALHOS[6:]

    for pasta in pastas_recursivas:
        if not pasta.exists():
            continue
        try:
            for arquivo in pasta.rglob("*"):
                if arquivo.suffix.lower() not in _EXTENSOES_APP:
                    continue
                nome_normalizado = _normalizar_nome_app(arquivo.name)
                if nome_normalizado and nome_normalizado not in indice:
                    indice[nome_normalizado] = arquivo
        except (OSError, PermissionError):
            continue

    for pasta_raiz in pastas_rasa:
        if not pasta_raiz.exists():
            continue
        try:
            for subpasta in pasta_raiz.iterdir():
                if not subpasta.is_dir():
                    continue
                try:
                    for arquivo in subpasta.iterdir():
                        if arquivo.suffix.lower() not in _EXTENSOES_APP:
                            continue
                        nome_normalizado = _normalizar_nome_app(arquivo.name)
                        if nome_normalizado and nome_normalizado not in indice:
                            indice[nome_normalizado] = arquivo
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            continue

    _indice_apps = indice
    _indice_construido = True
    print(f"[DEBUG automacao] Índice de apps: {len(_indice_apps)} entradas encontradas.")
    return _indice_apps

_indice_registro: Dict[str, Path] = {}
_indice_registro_construido = False

def construir_indice_registro(forcar=False) -> Dict[str, Path]:
    global _indice_registro, _indice_registro_construido

    if _indice_registro_construido and not forcar:
        return _indice_registro

    if os.name != "nt":
        return _indice_registro

    import winreg

    indice: Dict[str, Path] = {}

    chaves_registro = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ]
    raizes = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]

    for raiz in raizes:
        for chave_path in chaves_registro:
            try:
                chave = winreg.OpenKey(raiz, chave_path)
                total = winreg.QueryInfoKey(chave)[0]

                for i in range(total):
                    try:
                        sub_nome = winreg.EnumKey(chave, i)
                        sub_chave = winreg.OpenKey(chave, sub_nome)

                        try:
                            display_name, _ = winreg.QueryValueEx(sub_chave, "DisplayName")
                        except FileNotFoundError:
                            winreg.CloseKey(sub_chave)
                            continue

                        exe_encontrado = None

                        # Tenta DisplayIcon primeiro — mais confiável
                        try:
                            display_icon, _ = winreg.QueryValueEx(sub_chave, "DisplayIcon")
                            if display_icon:
                                icon_path = display_icon.split(",")[0].strip().strip('"')
                                p = Path(icon_path)
                                if p.exists() and p.suffix.lower() == ".exe":
                                    exe_encontrado = p
                        except FileNotFoundError:
                            pass

                        # Fallback: InstallLocation
                        if not exe_encontrado:
                            try:
                                install_location, _ = winreg.QueryValueEx(sub_chave, "InstallLocation")
                                if install_location:
                                    pasta = Path(install_location)
                                    if pasta.exists():
                                        exe = _encontrar_exe_principal(pasta, display_name)
                                        if exe:
                                            exe_encontrado = exe
                            except FileNotFoundError:
                                pass

                        winreg.CloseKey(sub_chave)

                        if exe_encontrado:
                            chave_norm = _normalizar_nome_app(display_name)
                            if chave_norm and chave_norm not in indice:
                                indice[chave_norm] = exe_encontrado

                    except (OSError, PermissionError):
                        continue

                winreg.CloseKey(chave)
            except (OSError, PermissionError):
                continue

    _indice_registro = indice
    _indice_registro_construido = True
    print(f"[DEBUG automacao] Índice de registro: {len(_indice_registro)} programas encontrados.")
    return _indice_registro

def _buscar_no_indice_registro(nome_app: str) -> Optional[Path]:
    indice = construir_indice_registro()
    if not indice:
        return None

    chave = _normalizar_nome_app(nome_app)
    if not chave:
        return None

    # Match exato
    if chave in indice:
        return indice[chave]

    # Match parcial
    for nome_indice, caminho in indice.items():
        if chave in nome_indice or nome_indice in chave:
            return caminho

    # Fuzzy
    proximos = difflib.get_close_matches(chave, list(indice.keys()), n=1, cutoff=0.42)
    if proximos:
        return indice[proximos[0]]

    return None


def _buscar_no_indice(nome_buscado: str) -> Optional[Path]:
    indice = construir_indice_apps()
    if not indice:
        return None

    chave = _normalizar_nome_app(nome_buscado)
    if not chave:
        return None

    if chave in indice:
        print(f"[DEBUG automacao] Índice: match exato → '{chave}'")
        return indice[chave]

    for nome_indice, caminho in indice.items():
        if chave in nome_indice or nome_indice in chave:
            print(f"[DEBUG automacao] Índice: match parcial '{chave}' → '{nome_indice}'")
            return caminho

    tokens_pedido = _tokens(chave)
    if tokens_pedido:
        for nome_indice, caminho in indice.items():
            tokens_indice = _tokens(nome_indice)
            if all(
                any(tp in ti or ti in tp or _similaridade(tp, ti) > 0.75 for ti in tokens_indice)
                for tp in tokens_pedido
            ):
                print(f"[DEBUG automacao] Índice: match por tokens '{chave}' → '{nome_indice}'")
                return caminho

    candidatos = list(indice.keys())
    proximos = difflib.get_close_matches(chave, candidatos, n=1, cutoff=0.42)
    if proximos:
        melhor = proximos[0]
        print(f"[DEBUG automacao] Índice: match fuzzy '{chave}' → '{melhor}'")
        return indice[melhor]

    return None


def _buscar_executavel_no_sistema(nome_app: str) -> Optional[Path]:
    if os.name != "nt":
        return None

    nome_limpo = _normalizar_nome_app(nome_app).replace(" ", "*")
    if not nome_limpo:
        return None

    # Busca em mais pastas e com mais profundidade
    pastas_busca = ",".join([
        "'C:\\\\Program Files'",
        "'C:\\\\Program Files (x86)'",
        f"'$env:LOCALAPPDATA\\\\Programs'",
        f"'$env:APPDATA'",
        f"'$env:LOCALAPPDATA'",
        f"'C:\\\\Users\\\\$env:USERNAME'",
    ])

    try:
        script = (
            f"Get-ChildItem -Path {pastas_busca} "
            f"-Recurse -Filter '*{nome_limpo}*.exe' -ErrorAction SilentlyContinue "
            f"-Depth 6 "  # vai até 6 níveis de pasta
            f"| Where-Object {{ $_.Name -notmatch 'unins|setup|install|redist|crash|helper|updater' }} "
            f"| Select-Object -First 1 -ExpandProperty FullName"
        )
        resultado = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=15
        )
        caminho_str = resultado.stdout.strip()
        if caminho_str:
            caminho = Path(caminho_str)
            if caminho.exists():
                print(f"[DEBUG automacao] PowerShell encontrou: {caminho}")
                return caminho
    except Exception as e:
        print(f"[DEBUG automacao] PowerShell fallback falhou: {e}")

    return None

def _buscar_com_winget(nome_app: str) -> Optional[Path]:
    """
    Usa o winget pra confirmar se o app está instalado e pegar o nome exato dele.
    Depois usa esse nome exato pra buscar o executável no registro do Windows.
    """
    if os.name != "nt":
        return None

    try:
        resultado = subprocess.run(
            ["winget", "list", "--query", nome_app,
             "--accept-source-agreements", "--disable-interactivity"],
            capture_output=True, text=True, timeout=12,
            encoding="utf-8", errors="replace"
        )

        if resultado.returncode != 0 or not resultado.stdout.strip():
            return None

        linhas = resultado.stdout.strip().splitlines()
        nomes_encontrados = []

        # O output do winget tem um separador "----" antes dos resultados
        cabecalho_passado = False
        for linha in linhas:
            if linha.startswith("---"):
                cabecalho_passado = True
                continue
            if not cabecalho_passado or not linha.strip():
                continue

            # As colunas do winget são separadas por 2+ espaços
            # A primeira coluna é sempre o nome do app
            partes = re.split(r'\s{2,}', linha.strip())
            if partes and partes[0].strip():
                nomes_encontrados.append(partes[0].strip())

        if not nomes_encontrados:
            return None

        print(f"[DEBUG automacao] Winget encontrou: {nomes_encontrados}")

        # Pra cada nome que o winget retornou, tenta achar o exe
        for nome in nomes_encontrados:
            caminho = _buscar_no_indice_registro(nome)
            if caminho:
                print(f"[DEBUG automacao] Winget + registro: '{nome}' → {caminho}")
                return caminho

            caminho = _buscar_no_indice(nome)
            if caminho:
                print(f"[DEBUG automacao] Winget + índice: '{nome}' → {caminho}")
                return caminho

    except FileNotFoundError:
        print("[DEBUG automacao] winget não encontrado no sistema")
    except Exception as e:
        print(f"[DEBUG automacao] Winget falhou: {e}")

    return None


# ─────────────────────────────────────────────────────────────────
# BUSCA DE JOGOS — Steam, Epic, GOG, Program Files
# ─────────────────────────────────────────────────────────────────

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


def _buscar_pasta_de_app(nome: str) -> Optional[Path]:
    """
    Busca a PASTA de um app/jogo sem rglob geral.
    Consulta Steam, Epic, GOG, registro do Windows, índice de apps e Program Files.
    Usa cache pra chamadas repetidas.
    """
    cached = _cache_get(f"pasta:{nome}")
    if cached and cached.is_dir():
        print(f"[DEBUG automacao] Cache de pasta: {cached}")
        return cached

    nome_norm = _normalizar_nome_app(nome)
    if not nome_norm:
        return None

    def _combina(pasta_norm: str) -> bool:
        sim = _similaridade(nome_norm, pasta_norm)
        tokens = [t for t in nome_norm.split() if len(t) > 2]
        tokens_ok = bool(tokens) and all(t in pasta_norm for t in tokens)
        return (
            nome_norm in pasta_norm
            or pasta_norm in nome_norm
            or sim > 0.55
            or tokens_ok
        )

    # 1. Steam
    for steam_common in _get_steam_libraries():
        try:
            for pasta in steam_common.iterdir():
                if pasta.is_dir() and _combina(_normalizar_nome_app(pasta.name)):
                    print(f"[DEBUG automacao] Pasta Steam: {pasta}")
                    _cache_set(f"pasta:{nome}", pasta)
                    return pasta
        except (OSError, PermissionError):
            continue

    # 2. Epic (via manifests)
    manifests_dir = Path("C:/ProgramData/Epic/EpicGamesLauncher/Data/Manifests")
    if manifests_dir.exists():
        try:
            for manifest_file in manifests_dir.glob("*.item"):
                try:
                    dados = json.loads(manifest_file.read_text(encoding="utf-8", errors="ignore"))
                    display_name = dados.get("DisplayName", "")
                    install_location = dados.get("InstallLocation", "")
                    if display_name and install_location:
                        if _combina(_normalizar_nome_app(display_name)):
                            p = Path(install_location)
                            if p.exists() and p.is_dir():
                                print(f"[DEBUG automacao] Pasta Epic: {p}")
                                _cache_set(f"pasta:{nome}", p)
                                return p
                except Exception:
                    continue
        except (OSError, PermissionError):
            pass

    # 3. GOG
    gog_dirs = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "GOG Galaxy" / "Games",
        Path(os.environ.get("ProgramFiles", "")) / "GOG Galaxy" / "Games",
        Path("C:/GOG Games"),
        HOME / "GOG Games",
    ]
    for gog_dir in gog_dirs:
        if not gog_dir.exists():
            continue
        try:
            for pasta in gog_dir.iterdir():
                if pasta.is_dir() and _combina(_normalizar_nome_app(pasta.name)):
                    print(f"[DEBUG automacao] Pasta GOG: {pasta}")
                    _cache_set(f"pasta:{nome}", pasta)
                    return pasta
        except (OSError, PermissionError):
            continue

    # 4. NOVO: Registro do Windows — pega o exe e retorna a pasta dele
    caminho_registro = _buscar_no_indice_registro(nome)
    if not caminho_registro:
        caminho_registro = _buscar_no_registro(nome)
    if caminho_registro and caminho_registro.exists():
        pasta = caminho_registro.parent
        print(f"[DEBUG automacao] Pasta via registro: {pasta}")
        _cache_set(f"pasta:{nome}", pasta)
        return pasta

    # 5. Índice de apps (Start Menu, Desktop, atalhos)
    caminho_indice = _buscar_no_indice(nome)
    if caminho_indice and caminho_indice.exists():
        # Ignora arquivos que claramente não são apps (scripts, libs, configs)
        extensoes_invalidas = {".py", ".dll", ".json", ".txt", ".xml", ".cfg", ".ini", ".log"}
        if caminho_indice.suffix.lower() in extensoes_invalidas:
            print(f"[DEBUG automacao] Índice retornou arquivo inválido, ignorando: {caminho_indice}")
            caminho_indice = None

    if caminho_indice and caminho_indice.exists():
        if caminho_indice.suffix.lower() == ".lnk" and os.name == "nt":
            try:
                import win32com.client
                import pythoncom
                pythoncom.CoInitialize()
                try:
                    shell = win32com.client.Dispatch("WScript.Shell")
                    shortcut = shell.CreateShortCut(str(caminho_indice))
                    alvo_lnk = Path(shortcut.Targetpath)
                    if alvo_lnk.exists():
                        pasta = alvo_lnk.parent
                        print(f"[DEBUG automacao] Pasta via atalho .lnk: {pasta}")
                        _cache_set(f"pasta:{nome}", pasta)
                        return pasta
                finally:
                    pythoncom.CoUninitialize()
            except Exception as e:
                print(f"[DEBUG automacao] Não conseguiu resolver .lnk: {e}")
        pasta = caminho_indice.parent
        print(f"[DEBUG automacao] Pasta via índice: {pasta}")
        _cache_set(f"pasta:{nome}", pasta)
        return pasta

    # 6. Program Files — agora com 2 níveis de profundidade
    raizes_pf = [
        Path(os.environ.get("ProgramFiles", "C:/Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        Path(os.environ.get("APPDATA", "")),
    ]
    for raiz in raizes_pf:
        if not raiz.exists():
            continue
        try:
            for nivel1 in raiz.iterdir():
                if not nivel1.is_dir():
                    continue
                if _combina(_normalizar_nome_app(nivel1.name)):
                    print(f"[DEBUG automacao] Pasta ProgramFiles nível1: {nivel1}")
                    _cache_set(f"pasta:{nome}", nivel1)
                    return nivel1
                # Vai um nível mais fundo (cobre BraveSoftware\Brave-Browser\Application, etc.)
                try:
                    for nivel2 in nivel1.iterdir():
                        if not nivel2.is_dir():
                            continue
                        if _combina(_normalizar_nome_app(nivel2.name)):
                            print(f"[DEBUG automacao] Pasta ProgramFiles nível2: {nivel2}")
                            _cache_set(f"pasta:{nome}", nivel2)
                            return nivel2
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            continue

    return None


def _buscar_jogo_completo(nome_jogo: str) -> Optional[Path]:
    # Verifica cache primeiro

    """
    Busca um jogo em todas as fontes, na seguinte ordem:
    1. Steam (todas as bibliotecas, incluindo outros discos)
    2. Epic Games (via manifests)
    3. GOG Galaxy
    4. Program Files (varredura profunda)
    5. PowerShell como último recurso
    """

    cached = _cache_get(f"jogo:{nome_jogo}")
    if cached:
        print(f"[DEBUG automacao] Cache hit: {cached}")
        return cached
    
    print(f"[DEBUG automacao] Buscando jogo: '{nome_jogo}'")

    resultado = _buscar_jogo_steam(nome_jogo)
    if resultado:
        return resultado

    resultado = _buscar_jogo_epic(nome_jogo)
    if resultado:
        return resultado

    resultado = _buscar_jogo_gog(nome_jogo)
    if resultado:
        return resultado

    resultado = _buscar_jogo_em_program_files(nome_jogo)
    if resultado:
        return resultado

    resultado = _buscar_executavel_no_sistema(nome_jogo)
    if resultado:
        return resultado

    return None

def _resolver_drive(texto: str) -> Optional[Path]:
    """
    Verifica se o texto se refere a uma unidade/drive pelo nome ou letra.
    Retorna o Path raiz do drive, ou None se não reconhecer.
    Bloqueia drives proibidos antes de retornar.
    """
    texto_norm = _normalizar(texto).strip()

    # Verifica se é um drive bloqueado (ex: "G", "G:")
    letra = texto_norm.rstrip(":").strip()
    if letra in DRIVES_BLOQUEADOS:
        print(f"[DEBUG automacao] Drive bloqueado: '{texto}'")
        return None

    # Tenta match exato no DRIVE_MAP
    if texto_norm in DRIVE_MAP:
        drive = DRIVE_MAP[texto_norm]
        if drive.exists():
            return drive

    # Tenta match parcial (ex: "armazémzão" casa com "armazémzão 1")
    for chave, caminho in DRIVE_MAP.items():
        if len(chave) < 3:   # ignora chaves curtas como "c", "d", "e", "h" no match parcial
           continue
    if texto_norm in chave or chave in texto_norm:
        if caminho.exists():
            return caminho

    return None


# ─────────────────────────────────────────────────────────────────
# BUSCA DE ARQUIVO EM PASTA ESPECÍFICA
# ─────────────────────────────────────────────────────────────────

def _resolver_pastas_do_hint(pasta_hint: str) -> list[Path]:
    if not pasta_hint:
        return []

    hint_norm = _normalizar(pasta_hint)

    # NOVO: verifica se é um drive/unidade pelo nome ou letra
    drive = _resolver_drive(pasta_hint)
    if drive:
        return [drive]

    # Verifica se é um caminho absoluto direto
    pasta_absoluta = Path(os.path.expandvars(os.path.expanduser(pasta_hint)))
    if pasta_absoluta.exists() and pasta_absoluta.is_dir():
        return [pasta_absoluta]

    # Tenta resolver pelo mapa de pastas — normaliza a chave também antes de comparar
    for chave, caminhos in PASTA_MAP.items():
        chave_norm = _normalizar(chave)
        if chave_norm in hint_norm or hint_norm in chave_norm:
            resultado = [p for p in caminhos if p and p.exists()]
            if resultado:
                return resultado

    # Busca parcial por tokens
    for chave, caminhos in PASTA_MAP.items():
        chave_norm = _normalizar(chave)
        tokens = [t for t in hint_norm.split() if len(t) >= 3]
        if any(t in chave_norm for t in tokens):
            resultado = [p for p in caminhos if p and p.exists()]
            if resultado:
                return resultado

    return []


def _buscar_arquivo_em_pasta(nome_arquivo: str, pastas: list[Path], recursivo: bool = False) -> Optional[Path]:
    """
    Busca um arquivo por nome (com fuzzy matching) dentro de uma lista de pastas.
    Se recursivo=True, varre subpastas também.
    """
    nome_norm = _normalizar(nome_arquivo)
    nome_stem_norm = _normalizar(Path(nome_arquivo).stem)

    for pasta in pastas:
        if not pasta.exists():
            continue

        try:
            arquivos = list(pasta.rglob("*") if recursivo else pasta.iterdir())
        except (OSError, PermissionError):
            continue

        nomes = [f.name for f in arquivos if f.is_file() or f.is_dir()]
        nomes_norm = [_normalizar(n) for n in nomes]

        # 1. Match exato
        for i, nn in enumerate(nomes_norm):
            if nn == nome_norm:
                print(f"[DEBUG automacao] Arquivo: match exato → {arquivos[i]}")
                return arquivos[i]

        # 2. Match parcial pelo stem (sem extensão)
        for i, original in enumerate(nomes):
            stem_norm = _normalizar(Path(original).stem)
            if nome_stem_norm in stem_norm or stem_norm in nome_stem_norm:
                print(f"[DEBUG automacao] Arquivo: match stem → {arquivos[i]}")
                return arquivos[i]

        # 3. Fuzzy match
        proximos = difflib.get_close_matches(nome_norm, nomes_norm, n=1, cutoff=0.45)
        if proximos:
            idx = nomes_norm.index(proximos[0])
            print(f"[DEBUG automacao] Arquivo: match fuzzy '{nome_arquivo}' → '{nomes[idx]}'")
            return arquivos[idx]

    return None


# ─────────────────────────────────────────────
# FUNÇÕES AUXILIARES
# ─────────────────────────────────────────────

def _limpar_artigos(texto: str) -> str:
    texto = texto.strip()
    texto = re.sub(r"^(o|a|os|as|um|uma|uns|umas)\s+", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"^(arquivo|pasta|programa|app|aplicativo|navegador)\s+", "", texto, flags=re.IGNORECASE)
    return texto.strip(" ,.;:")


def _remover_aspas(texto: str) -> str:
    return texto.strip().strip('"').strip("'").strip("'").strip()


def _remover_vocativos(texto: str) -> str:
    texto = texto.strip()
    texto = re.sub(
        r"^(emily|emi|ei emily|por favor|pfv|porfa)\s*[,!:\-]?\s*",
        "",
        texto,
        flags=re.IGNORECASE,
    )
    return texto.strip()

def _normalizar_para_cache(mensagem: str) -> str:
    texto = _normalizar(mensagem)        # lowercase + remove acentos
    texto = _remover_vocativos(texto)    # remove "emily", "emi", etc
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto


def _remover_comando_abrir(texto: str) -> str:
    texto = texto.strip()
    texto = re.sub(
        r"^(?:abrir|abre|abra|iniciar|inicia|inicie|executar|executa|rodar|roda|abrindo|coloca|liga|carrega|chama|joga|jogar)\b\s*",
        "",
        texto,
        flags=re.IGNORECASE,
    )
    return texto.strip()


def _limpar_alvo_comando(texto: str) -> str:
    texto = _remover_vocativos(_remover_aspas(texto))
    texto = _remover_comando_abrir(texto)
    texto = _limpar_artigos(texto)
    return texto.strip(" ,.;:")


def _extrair_url(texto: str) -> Optional[str]:
    match = re.search(r"(https?://[^\s]+)", texto, flags=re.IGNORECASE)
    if match:
        return match.group(1).rstrip(".,;!?")
    match = re.search(
        r"\b([a-z0-9.-]+\.[a-z]{2,})(/[^\s]*)?\b",
        texto,
        flags=re.IGNORECASE,
    )
    if match:
        url = match.group(0).rstrip(".,;!?")
        if not url.lower().startswith(("http://", "https://")):
            url = f"https://{url}"
        return url
    return None


def _caminhos_candidatos() -> Iterable[Path]:
    vistos = set()
    for raiz in CANDIDATE_ROOTS:
        if not raiz:
            continue
        try:
            raiz_expandida = raiz.expanduser()
        except Exception:
            continue
        if str(raiz_expandida) in vistos:
            continue
        vistos.add(str(raiz_expandida))
        yield raiz_expandida


def _procurar_por_nome(nome_arquivo: str) -> Optional[Path]:
    nome_arquivo = nome_arquivo.strip()
    if not nome_arquivo:
        return None
    for raiz in _caminhos_candidatos():
        if not raiz.exists():
            continue
        try:
            for encontrado in raiz.rglob(nome_arquivo):
                if encontrado.exists():
                    return encontrado
        except (OSError, PermissionError):
            continue
    return None


def _resolver_caminho(texto: str) -> Optional[Path]:
    texto = _remover_aspas(_limpar_artigos(texto))
    texto = os.path.expandvars(os.path.expanduser(texto))

    if not texto:
        return None

    candidato = Path(texto)
    if candidato.exists():
        return candidato.resolve()

    if not candidato.is_absolute():
        relativo = Path.cwd() / candidato
        if relativo.exists():
            return relativo.resolve()

    if candidato.name and candidato.name != texto:
        encontrado = _procurar_por_nome(candidato.name)
        if encontrado:
            return encontrado.resolve()

    if texto and not any(separador in texto for separador in ("\\", "/")):
        encontrado = _procurar_por_nome(texto)
        if encontrado:
            return encontrado.resolve()

    return None


def _resolver_destino(texto: str, origem: Optional[Path] = None) -> Path:
    texto = _remover_aspas(_limpar_artigos(texto))
    texto = os.path.expandvars(os.path.expanduser(texto))

    candidato = Path(texto)
    if candidato.exists():
        return candidato.resolve()

    if not candidato.is_absolute():
        for raiz in _caminhos_candidatos():
            possivel = raiz / candidato
            if possivel.exists():
                return possivel.resolve()

    if origem is not None and texto in {"aqui", "aí", "aqui mesmo", "aqui msm"}:
        return origem.parent

    if not candidato.suffix:
        return candidato

    return candidato


def _executar_start(path_ou_comando: str) -> bool:
    try:
        if os.name == "nt":
            os.startfile(path_ou_comando)
            return True
    except Exception:
        pass
    try:
        if os.name == "nt":
            subprocess.Popen(["cmd", "/c", "start", "", path_ou_comando], shell=False)
            return True
        subprocess.Popen([path_ou_comando])
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
# ABRIR APP — com fallback completo em 8 camadas
# ─────────────────────────────────────────────

def _buscar_discord() -> Optional[Path]:
    discord_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Discord"
    if not discord_dir.exists():
        return None
    pastas_versao = sorted(
        [p for p in discord_dir.iterdir() if p.is_dir() and p.name.startswith("app-")],
        reverse=True
    )
    for pasta in pastas_versao:
        exe = pasta / "Discord.exe"
        if exe.exists():
            return exe
    return None

def _buscar_no_registro(nome_app: str) -> Optional[Path]:
    if os.name != "nt":
        return None

    import winreg

    nome_norm = _normalizar(nome_app)

    chaves_registro = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ]

    raizes = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]

    for raiz in raizes:
        for chave_path in chaves_registro:
            try:
                chave = winreg.OpenKey(raiz, chave_path)
                total = winreg.QueryInfoKey(chave)[0]

                for i in range(total):
                    try:
                        sub_nome = winreg.EnumKey(chave, i)
                        sub_chave = winreg.OpenKey(chave, sub_nome)

                        try:
                            display_name, _ = winreg.QueryValueEx(sub_chave, "DisplayName")
                        except FileNotFoundError:
                            winreg.CloseKey(sub_chave)
                            continue

                        display_norm = _normalizar(display_name)
                        sim = _similaridade(display_norm, nome_norm)

                        if not (nome_norm in display_norm or display_norm in nome_norm or sim > 0.6):
                            winreg.CloseKey(sub_chave)
                            continue

                        # Tenta InstallLocation primeiro
                        try:
                            install_location, _ = winreg.QueryValueEx(sub_chave, "InstallLocation")
                            if install_location:
                                pasta = Path(install_location)
                                if pasta.exists():
                                    exe = _encontrar_exe_principal(pasta, nome_app)
                                    if exe:
                                        print(f"[DEBUG automacao] Registro InstallLocation: '{display_name}' → {exe}")
                                        winreg.CloseKey(sub_chave)
                                        return exe
                        except FileNotFoundError:
                            pass

                        # Tenta DisplayIcon — muitos programas guardam o exe aqui
                        try:
                            display_icon, _ = winreg.QueryValueEx(sub_chave, "DisplayIcon")
                            if display_icon:
                                # DisplayIcon pode ter ",0" no final — remove
                                icon_path = display_icon.split(",")[0].strip().strip('"')
                                exe = Path(icon_path)
                                if exe.exists() and exe.suffix.lower() == ".exe":
                                    print(f"[DEBUG automacao] Registro DisplayIcon: '{display_name}' → {exe}")
                                    winreg.CloseKey(sub_chave)
                                    return exe
                        except FileNotFoundError:
                            pass

                        winreg.CloseKey(sub_chave)

                    except (OSError, PermissionError):
                        continue

                winreg.CloseKey(chave)
            except (OSError, PermissionError):
                continue

    return None

def _buscar_com_where(nome_app: str) -> Optional[Path]:
    """
    Usa o comando 'where' do Windows pra achar executáveis no PATH do sistema.
    Funciona pra qualquer programa que está nas variáveis de ambiente.
    """
    if os.name != "nt":
        return None
    
    nomes_tentar = [
        nome_app,
        nome_app + ".exe",
        nome_app.replace(" ", ""),
        nome_app.replace(" ", "") + ".exe",
        nome_app.replace(" ", "-"),
        nome_app.replace(" ", "_"),
    ]
    
    for nome in nomes_tentar:
        try:
            resultado = subprocess.run(
                ["where", nome],
                capture_output=True,
                text=True,
                timeout=3
            )
            if resultado.returncode == 0:
                primeira_linha = resultado.stdout.strip().splitlines()[0]
                caminho = Path(primeira_linha.strip())
                if caminho.exists():
                    print(f"[DEBUG automacao] where achou: {caminho}")
                    return caminho
        except Exception:
            continue
    
    return None

def _encontrar_hwnds_de_app(nome_app: str) -> list:
    """Retorna todos os HWNDs visíveis de um app pelo nome do processo."""
    if os.name != "nt":
        return []
    try:
        import win32gui
        import win32process
        import win32api

        app_norm = _normalizar(APP_ALIASES.get(_normalizar(nome_app), _normalizar(nome_app)))
        processos_alvo = WINDOWS_PROCESS_CANDIDATES.get(app_norm, [])
        if not processos_alvo:
            processos_alvo = [app_norm + ".exe", nome_app.lower() + ".exe"]
        processos_norm = {_normalizar(p) for p in processos_alvo}

        hwnds = []

        def _enum(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd):
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                handle = win32api.OpenProcess(0x0400, False, pid)
                if handle:
                    try:
                        exe = win32process.GetModuleFileNameEx(handle, 0)
                        if _normalizar(Path(exe).name) in processos_norm:
                            hwnds.append(hwnd)
                    finally:
                        win32api.CloseHandle(handle)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_enum, None)
        return hwnds
    except Exception:
        return []


def _abrir_app(nome_app: str) -> bool:
    # Verifica cache primeiro
    cached = _cache_get(f"app:{nome_app}")
    if cached:
        print(f"[DEBUG automacao] Cache hit: {cached}")
        return _executar_start(str(cached))
    

    nome_normalizado = _normalizar(nome_app)
    app = APP_ALIASES.get(nome_normalizado, "")

    if not app:
        for alias_chave, alias_valor in APP_ALIASES.items():
            chave_sem_espaco = alias_chave.replace(" ","")
            nome_sem_espaco = nome_normalizado.replace(" ", "")
            if chave_sem_espaco == nome_sem_espaco or nome_sem_espaco in chave_sem_espaco or alias_chave in nome_normalizado:
                app = alias_valor
                break
    
    if not app:
        app = nome_normalizado
    app = app.strip()
        


    # Camada 1 — Pastas especiais do Windows (lixeira, desktop, etc.)
    if app in SHELL_FOLDERS or nome_normalizado in SHELL_FOLDERS:
        chave = app if app in SHELL_FOLDERS else nome_normalizado
        return _executar_start(SHELL_FOLDERS[chave])

    # Camada 2 — Comandos diretos do sistema
    if app == "browser":
        return _abrir_app("brave")
    if app == "terminal":
        return _executar_start("wt") or _executar_start("cmd")
    if app == "powershell":
        return _executar_start("powershell")
    if app == "cmd":
        return _executar_start("cmd")
    if app == "explorer":
        return _executar_start("explorer")
    if app == "notepad":
        return _executar_start("notepad")
    if app == "calc":
        return _executar_start("calc")
    if app == "mspaint":
        return _executar_start("mspaint")

    # Discord tem pasta versionada
    if app == "discord":
        caminho_discord = _buscar_discord()
        if caminho_discord:
            return _executar_start(str(caminho_discord))

    # Camada 3 — Apps com caminho fixo conhecido
    candidatos = WINDOWS_APP_CANDIDATES.get(app, [])
    for caminho in candidatos:
        if caminho and caminho.exists():
            return _executar_start(str(caminho))
        
    caminho_where = _buscar_com_where(app) or _buscar_com_where(nome_app)
    if caminho_where:
         _cache_set(f"app:{nome_app}", caminho_where)
         return _executar_start(str(caminho_where))
    

    # Camada 4 — Nome direto no PATH do sistema
    import shutil as _shutil
    if _shutil.which(app):
        if _executar_start(app):
            return True

    # Camada 5 — Índice de apps (Start Menu, Desktop)
    caminho_indice = _buscar_no_indice(nome_app)
    if caminho_indice:
        _cache_set(f"app:{nome_app}", caminho_indice)
        return _executar_start(str(caminho_indice))

    # Camada 5.5 — Índice do registro (todos os programas instalados)
    caminho_reg_indice = _buscar_no_indice_registro(nome_app)
    if caminho_reg_indice:
        _cache_set(f"app:{nome_app}", caminho_reg_indice)
        return _executar_start(str(caminho_reg_indice))


    # Camada 6 — Busca nas bibliotecas de jogos (Steam, Epic, GOG)
    caminho_jogo = _buscar_jogo_completo(nome_app)
    if caminho_jogo:
        print(f"[DEBUG automacao] Abrindo jogo/app via biblioteca: {caminho_jogo}")
        return _executar_start(str(caminho_jogo))

    # Camada 7 — Varredura profunda em Program Files
    caminho_pf = _buscar_jogo_em_program_files(nome_app)
    if caminho_pf:
        return _executar_start(str(caminho_pf))
    
    # Camada 8 — Registro do Windows
    caminho_registro = _buscar_no_registro(nome_app)
    if caminho_registro:
        _cache_set(f"app:{nome_app}", caminho_registro)  # ← salva no cache
        return _executar_start(str(caminho_registro))

    # Camada 9 — PowerShell
    caminho_ps = _buscar_executavel_no_sistema(nome_app)
    if caminho_ps:
        _cache_set(f"app:{nome_app}", caminho_ps)  # ← salva no cache
        return _executar_start(str(caminho_ps))

    # Camada 10 — Winget
    caminho_winget = _buscar_com_winget(nome_app)
    if caminho_winget:
        _cache_set(f"app:{nome_app}", caminho_winget)
        return _executar_start(str(caminho_winget))

    return False


def _fechar_app(nome_app: str) -> bool:
    app = APP_ALIASES.get(_normalizar(nome_app), _normalizar(nome_app))
    app = app.strip()

    if not app:
        return False

    if app == "browser":
        processos = ["brave.exe", "chrome.exe", "msedge.exe", "firefox.exe"]
    else:
        processos = WINDOWS_PROCESS_CANDIDATES.get(app, [])

    if not processos and not app.endswith(".exe"):
        processos = [f"{app}.exe"]
    elif not processos:
        processos = [app]

    sucesso = False

    if os.name == "nt":
        for processo in dict.fromkeys(processos):
            try:
                resultado = subprocess.run(
                    ["taskkill", "/IM", processo, "/F"],
                    capture_output=True,
                    text=True,
                )
                if resultado.returncode == 0:
                    sucesso = True
            except Exception:
                continue
        return sucesso

    for processo in dict.fromkeys(processos):
        try:
            resultado = subprocess.run(
                ["pkill", "-f", processo.replace(".exe", "")],
                capture_output=True,
                text=True,
            )
            if resultado.returncode == 0:
                sucesso = True
        except Exception:
            continue

    return sucesso


def _fechar_aba_navegador(titulo: str) -> str:
    """
    Fecha uma aba do navegador pelo título da página.
    Se titulo estiver vazio, fecha a aba ativa do navegador em foco.
    """
    if os.name != "nt":
        return "Isso só funciona no Windows!"
    try:
        import win32gui
        import ctypes
        import time

        VK_CONTROL      = 0x11
        VK_W            = 0x57
        KEYEVENTF_KEYUP = 0x0002

        def _enviar_ctrl_w():
            ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_W, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_W, 0, KEYEVENTF_KEYUP, 0)
            ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

        # Sem título → fecha a aba ativa do navegador que está em foco
        if not titulo or not titulo.strip():
            hwnd = win32gui.GetForegroundWindow()
            if win32gui.GetClassName(hwnd) not in _CLASSES_NAVEGADOR:
                return "Não tem nenhum navegador em foco agora, Vitor!"
            _enviar_ctrl_w()
            return "Fechei a aba atual!"

        titulo_norm = _normalizar(titulo)
        janelas = []

        def _enum(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            classe = win32gui.GetClassName(hwnd)
            titulo_janela = _normalizar(win32gui.GetWindowText(hwnd))
            if classe in _CLASSES_NAVEGADOR and titulo_norm in titulo_janela:
                janelas.append(hwnd)
            return True

        win32gui.EnumWindows(_enum, None)

        if not janelas:
            return f"Não achei '{titulo}' aberto no navegador, Vitor! A aba pode estar em segundo plano."

        fechadas = 0
        for hwnd in janelas:
            try:
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.2)
                _enviar_ctrl_w()
                time.sleep(0.1)
                fechadas += 1
            except Exception:
                pass

        qtd_txt = "a aba" if fechadas == 1 else f"{fechadas} abas"
        return f"Fechei {qtd_txt} do {titulo}!"

    except ImportError:
        return "Preciso do pywin32 pra isso. Roda: pip install pywin32"
    except Exception as e:
        return f"Não consegui fechar a aba: {e}"


def _minimizar_app(nome_app: str) -> str:
    """Minimiza todas as janelas visíveis de um app."""
    if os.name != "nt":
        return "Isso só funciona no Windows!"
    try:
        import win32gui
        import win32con
        hwnds = _encontrar_hwnds_de_app(nome_app)
        if not hwnds:
            return f"Não achei nenhuma janela do {nome_app} aberta, Vitor!"
        for hwnd in hwnds:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        return f"Minimizei o {nome_app}!"
    except Exception as e:
        return f"Não consegui minimizar: {e}"


def _maximizar_app(nome_app: str) -> str:
    """Maximiza todas as janelas visíveis de um app."""
    if os.name != "nt":
        return "Isso só funciona no Windows!"
    try:
        import win32gui
        import win32con
        hwnds = _encontrar_hwnds_de_app(nome_app)
        if not hwnds:
            return f"Não achei nenhuma janela do {nome_app} aberta, Vitor!"
        for hwnd in hwnds:
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        return f"Maximizei o {nome_app}!"
    except Exception as e:
        return f"Não consegui maximizar: {e}"


def _remover_comando_mover(texto: str) -> str:
    texto = texto.strip()
    texto = re.sub(r"^(?:mover|move|transfere|transferir|mandar|mudar|deslocar)\b\s*", "", texto, flags=re.IGNORECASE)
    return texto.strip()


def _extrair_termos_mover(mensagem: str) -> Optional[tuple[str, str]]:
    texto = _remover_comando_mover(_remover_vocativos(mensagem))

    padroes = [
        r"(?P<origem>.+?)\s+(?:para|pra|pro|pro\s+a|pro\s+o|para\s+a|para\s+o|em)\s+(?P<destino>.+)",
    ]

    for padrao in padroes:
        match = re.search(padrao, texto, flags=re.IGNORECASE)
        if match:
            origem = match.group("origem").strip()
            destino = match.group("destino").strip()
            origem = re.sub(r"^(o|a|os|as|um|uma|uns|umas)\s+", "", origem, flags=re.IGNORECASE)
            origem = re.sub(r"^(arquivo|pasta)\s+", "", origem, flags=re.IGNORECASE)
            origem = _remover_vocativos(origem).strip()
            destino = re.sub(r"^(a|o|as|os|uma|um|umas|uns)\s+", "", destino, flags=re.IGNORECASE)
            destino = _remover_vocativos(destino).strip()
            return origem, destino

    return None


# ─────────────────────────────────────────────────────────────────
# ARQUIVOS SELECIONADOS NO WINDOWS EXPLORER
# ─────────────────────────────────────────────────────────────────

def _encontrar_desktop_listview() -> Optional[int]:
    """
    Acha o handle (hwnd) do SysListView32 que representa os ícones do Desktop.
    O Desktop no Windows fica dentro de Progman → SHELLDLL_DefView → SysListView32,
    ou dentro de WorkerW → SHELLDLL_DefView → SysListView32 (Windows 10/11).
    Retorna o hwnd do listview, ou None se não encontrar.
    """
    try:
        import win32gui

        # Caminho 1: Progman → SHELLDLL_DefView → SysListView32
        progman = win32gui.FindWindow("Progman", None)
        if progman:
            shelldll = win32gui.FindWindowEx(progman, None, "SHELLDLL_DefView", None)
            if shelldll:
                lv = win32gui.FindWindowEx(shelldll, None, "SysListView32", None)
                if lv:
                    return lv

        # Caminho 2: WorkerW → SHELLDLL_DefView → SysListView32 (Windows 10/11)
        resultados: list[int] = []

        def _enum_cb(hwnd: int, _: object) -> bool:
            if win32gui.GetClassName(hwnd) == "WorkerW":
                shelldll = win32gui.FindWindowEx(hwnd, None, "SHELLDLL_DefView", None)
                if shelldll:
                    lv = win32gui.FindWindowEx(shelldll, None, "SysListView32", None)
                    if lv:
                        resultados.append(lv)
            return True

        win32gui.EnumWindows(_enum_cb, None)
        if resultados:
            return resultados[0]

    except Exception as e:
        print(f"[DEBUG automacao] Erro ao localizar Desktop listview: {e}")

    return None


def _tentar_shell_application() -> list[Path]:
    """
    Método 1: Shell.Application.
    Lê os arquivos selecionados em janelas abertas do Windows Explorer.
    """
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            shell = win32com.client.Dispatch("Shell.Application")
            windows = shell.Windows()
            selecionados: list[Path] = []

            for i in range(windows.Count):
                try:
                    window = windows.Item(i)
                    if window is None:
                        continue
                    doc = window.Document
                    if doc is None:
                        continue
                    items = doc.SelectedItems()
                    for j in range(items.Count):
                        item = items.Item(j)
                        caminho = Path(item.Path)
                        if caminho.exists() and caminho not in selecionados:
                            selecionados.append(caminho)
                except Exception:
                    continue

            return selecionados
        finally:
            pythoncom.CoUninitialize()

    except ImportError:
        print("[DEBUG automacao] pywin32 não instalado! Rode: pip install pywin32")
    except Exception as e:
        print(f"[DEBUG automacao] Shell.Application falhou: {e}")

    return []


def _tentar_desktop_listview() -> list[Path]:
    """
    Método 2: SysListView32 do Desktop via Windows API.
    Lê os ícones selecionados diretamente na Área de Trabalho,
    mesmo quando nenhuma janela do Explorer está aberta.
    Usa VirtualAllocEx para ler memória do processo do Explorer.
    """
    try:
        import ctypes
        import ctypes.wintypes as wt
        import win32api
        import win32process

        listview = _encontrar_desktop_listview()
        if not listview:
            return []

        LVM_FIRST            = 0x1000
        LVM_GETSELECTEDCOUNT = LVM_FIRST + 50
        LVM_GETNEXTITEM      = LVM_FIRST + 12
        LVM_GETITEMTEXTW     = LVM_FIRST + 115
        LVNI_SELECTED        = 0x0002
        LVIF_TEXT            = 0x0001
        MAX_PATH             = 260

        count = win32api.SendMessage(listview, LVM_GETSELECTEDCOUNT, 0, 0)
        if count == 0:
            return []

        _, pid = win32process.GetWindowThreadProcessId(listview)
        PROCESS_ALL_ACCESS = 0x1F0FFF
        h_process = ctypes.windll.kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not h_process:
            return []

        class LVITEM(ctypes.Structure):
            _fields_ = [
                ("mask",       ctypes.c_uint),
                ("iItem",      ctypes.c_int),
                ("iSubItem",   ctypes.c_int),
                ("state",      ctypes.c_uint),
                ("stateMask",  ctypes.c_uint),
                ("pszText",    ctypes.c_uint64),
                ("cchTextMax", ctypes.c_int),
                ("iImage",     ctypes.c_int),
                ("lParam",     ctypes.c_int64),
                ("iIndent",    ctypes.c_int),
            ]

        item_size = ctypes.sizeof(LVITEM)
        buf_size  = MAX_PATH * 2

        MEM_COMMIT     = 0x1000
        PAGE_READWRITE = 0x04
        MEM_RELEASE    = 0x8000

        remote_mem = ctypes.windll.kernel32.VirtualAllocEx(
            h_process, None, item_size + buf_size, MEM_COMMIT, PAGE_READWRITE
        )
        if not remote_mem:
            ctypes.windll.kernel32.CloseHandle(h_process)
            return []

        remote_text = remote_mem + item_size

        try:
            # Busca em TODAS as pastas de desktop (OneDrive + local)
            desktop_paths = [p for p in PASTA_MAP.get("desktop", []) if p.exists()]
            if not desktop_paths:
                desktop_paths = [_DESKTOP_REAL or HOME / "Desktop"]

            arquivos: list[Path] = []
            item_index = -1

            for _ in range(count):
                item_index = win32api.SendMessage(
                    listview, LVM_GETNEXTITEM, item_index, LVNI_SELECTED
                )
                if item_index == -1:
                    break

                lv = LVITEM()
                lv.mask       = LVIF_TEXT
                lv.iItem      = item_index
                lv.iSubItem   = 0
                lv.pszText    = remote_text
                lv.cchTextMax = MAX_PATH

                written = ctypes.c_size_t(0)
                ctypes.windll.kernel32.WriteProcessMemory(
                    h_process, remote_mem,
                    ctypes.byref(lv), item_size, ctypes.byref(written)
                )

                win32api.SendMessage(listview, LVM_GETITEMTEXTW, item_index, remote_mem)

                text_buf = ctypes.create_unicode_buffer(MAX_PATH)
                read = ctypes.c_size_t(0)
                ctypes.windll.kernel32.ReadProcessMemory(
                    h_process, remote_text,
                    text_buf, buf_size, ctypes.byref(read)
                )

                nome = text_buf.value
                if nome:
                    print(f"[DEBUG desktop] Ícone selecionado: '{nome}'")

                    caminho = None

                    # Procura em TODAS as pastas de desktop (OneDrive + local)
                    for dp in desktop_paths:
                        tentativa = dp / nome
                        if tentativa.exists():
                            caminho = tentativa
                            break
                        for ext in (".lnk", ".url", ".exe"):
                            tentativa = dp / (nome + ext)
                            if tentativa.exists():
                                caminho = tentativa
                                break
                        if caminho:
                            break

                    # Se ainda não achou, tenta fuzzy em todas as pastas
                    if not caminho:
                        encontrado = _buscar_arquivo_em_pasta(nome, desktop_paths, recursivo=False)
                        if encontrado:
                            print(f"[DEBUG desktop] Achou via fuzzy: '{encontrado.name}'")
                            caminho = encontrado

                    if caminho and caminho.exists() and caminho not in arquivos:
                        print(f"[DEBUG desktop] Adicionado: '{caminho}'")
                        arquivos.append(caminho)
                    else:
                        print(f"[DEBUG desktop] Não encontrou arquivo para o ícone: '{nome}'")

            return arquivos

        finally:
            ctypes.windll.kernel32.VirtualFreeEx(h_process, remote_mem, 0, MEM_RELEASE)
            ctypes.windll.kernel32.CloseHandle(h_process)

    except ImportError:
        print("[DEBUG automacao] pywin32 necessário para ler o Desktop. Rode: pip install pywin32")
    except Exception as e:
        print(f"[DEBUG automacao] Desktop listview falhou: {e}")

    return []


def _tentar_clipboard_hdrop() -> list[Path]:
    """
    Método 3: Clipboard CF_HDROP (fallback).
    Se o usuário tiver copiado arquivos com Ctrl+C (em qualquer lugar),
    lê esses caminhos do clipboard. Não modifica nada.
    """
    try:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                caminhos = win32clipboard.GetClipboardData(win32con.CF_HDROP)
                arquivos: list[Path] = []
                for caminho_str in caminhos:
                    p = Path(caminho_str)
                    if p.exists():
                        arquivos.append(p)
                if arquivos:
                    print(f"[DEBUG automacao] Clipboard CF_HDROP: {len(arquivos)} arquivo(s)")
                return arquivos
        finally:
            win32clipboard.CloseClipboard()

    except ImportError:
        pass  # win32clipboard faz parte do pywin32, já avisamos antes
    except Exception as e:
        print(f"[DEBUG automacao] Clipboard CF_HDROP falhou: {e}")

    return []

def _tentar_janela_focada() -> list[Path]:
    """
    Lê os arquivos selecionados na última janela Explorer que esteve em foco.
    Usa o hwnd monitorado em background, não a janela atual (que seria a Emily).
    """
    try:
        import pythoncom
        import win32com.client

        hwnd_alvo = _ultima_janela_explorer
        if not hwnd_alvo:
            return []

        pythoncom.CoInitialize()
        try:
            shell = win32com.client.Dispatch("Shell.Application")
            windows = shell.Windows()
            selecionados: list[Path] = []

            for i in range(windows.Count):
                try:
                    window = windows.Item(i)
                    if window is None:
                        continue
                    if window.HWND != hwnd_alvo:
                        continue
                    doc = window.Document
                    if doc is None:
                        continue
                    items = doc.SelectedItems()
                    for j in range(items.Count):
                        item = items.Item(j)
                        caminho = Path(item.Path)
                        if caminho.exists() and caminho not in selecionados:
                            selecionados.append(caminho)
                    return selecionados
                except Exception:
                    continue
        finally:
            pythoncom.CoUninitialize()

    except Exception as e:
        print(f"[DEBUG automacao] Janela focada falhou: {e}")

    return []


def _obter_arquivos_selecionados() -> list[Path]:
    if os.name != "nt":
        return []

    # Método 1 — Última janela Explorer monitorada (cobre Explorer + Desktop)
    arquivos = _tentar_janela_focada()
    if arquivos:
        print(f"[DEBUG automacao] Selecionados via janela monitorada: {len(arquivos)}")
        return arquivos

    # Método 2 — Todas as janelas Explorer abertas
    arquivos = _tentar_shell_application()
    if arquivos:
        print(f"[DEBUG automacao] Selecionados via Shell.Application: {len(arquivos)}")
        return arquivos

    # Método 3 — Ícones selecionados na Área de Trabalho via SysListView32
    arquivos = _tentar_desktop_listview()
    if arquivos:
        print(f"[DEBUG automacao] Selecionados via Desktop listview: {len(arquivos)}")
        return arquivos

    # Clipboard removido daqui pra evitar deletar arquivo errado por engano
    print("[DEBUG automacao] Nenhum arquivo selecionado encontrado.")
    return []

def _resolver_subpasta(pasta_base: Path, subpasta_nome: str) -> Optional[Path]:
    """
    Busca uma subpasta pelo nome dentro de uma pasta base.
    Tenta match exato primeiro, depois fuzzy com até 2 níveis de profundidade.
    """
    if not subpasta_nome or not pasta_base or not pasta_base.exists():
        return None

    nome_norm = _normalizar(subpasta_nome)

    def _combina(pasta_norm: str) -> bool:
        if not pasta_norm:
            return False
        sim = _similaridade(nome_norm, pasta_norm)
        tokens = [t for t in nome_norm.split() if len(t) > 2]
        tokens_ok = bool(tokens) and all(t in pasta_norm for t in tokens)
        return nome_norm in pasta_norm or pasta_norm in nome_norm or sim > 0.65 or tokens_ok

    # Nível 1 — direto dentro da pasta base
    try:
        for sub in pasta_base.iterdir():
            if sub.is_dir() and _combina(_normalizar(sub.name)):
                print(f"[DEBUG automacao] Subpasta encontrada (nível 1): {sub}")
                return sub
    except (OSError, PermissionError):
        pass

    # Nível 2 — um nível mais fundo
    try:
        for sub1 in pasta_base.iterdir():
            if not sub1.is_dir():
                continue
            for sub2 in sub1.iterdir():
                if sub2.is_dir() and _combina(_normalizar(sub2.name)):
                    print(f"[DEBUG automacao] Subpasta encontrada (nível 2): {sub2}")
                    return sub2
    except (OSError, PermissionError):
        pass

    return None


def _copiar_selecionados(destino_texto: str, drive_hint: str = "", subpasta: str = "") -> str:
    arquivos = _obter_arquivos_selecionados()
    if not arquivos:
        return "Não achei nenhum arquivo selecionado no Explorer, Vitor!"
    
    if _callback_status:
        _callback_status("transferindo")

    # Resolve destino com suporte a drive
    destino: Optional[Path] = None
    if drive_hint:
        drive = _resolver_drive(drive_hint)
        if drive:
            if destino_texto:
                pasta_no_drive = _buscar_pasta_em_drive(destino_texto, drive)
                destino = pasta_no_drive if pasta_no_drive else drive
            else:
                destino = drive

    if not destino:
        pastas = _resolver_pastas_do_hint(destino_texto)
        destino = pastas[0] if pastas else None

    if not destino:
        destino = _resolver_destino(destino_texto)

    if not destino:
        return f"Não entendi o destino '{destino_texto}', Vitor!"

    # ── NOVO: navega pra subpasta se foi especificada ──
    if subpasta:
        sub = _resolver_subpasta(destino, subpasta)
        if sub:
            destino = sub
        else:
            # Subpasta não existe — cria ela
            destino = destino / subpasta
            print(f"[DEBUG automacao] Subpasta não encontrada, criando: {destino}")


    sucessos: list[str] = []
    erros: list[str] = []
    caminhos_copiados: list[str] = []   # ← rastreia destinos pra undo

    for arquivo in arquivos:
        try:
            destino.mkdir(parents=True, exist_ok=True)
            destino_final = destino / arquivo.name

            if _tamanho_bytes(arquivo) >= _LIMITE_DIALOGO_BYTES or destino_final.exists():
                sucesso_shell = _shell_fileop(_FO_COPY, arquivo, destino)
                if sucesso_shell:
                    caminhos_copiados.append(str(destino_final))
                sucessos.append(arquivo.name)
                continue

            if arquivo.is_dir():
                shutil.copytree(str(arquivo), str(destino_final))
            else:
                shutil.copy2(str(arquivo), str(destino_final))
            sucessos.append(arquivo.name)
            caminhos_copiados.append(str(destino_final))   # ← registra o destino
        except Exception as e:
            erros.append(f"{arquivo.name} ({e})")

    if caminhos_copiados:
        _registrar_undo({"tipo": "copiar", "caminhos_copiados": caminhos_copiados})

    resp = f"Copiei {len(sucessos)} arquivo(s) para {destino.name}!"
    if erros:
        resp += f" Mas não consegui copiar: {', '.join(erros)}"
    return resp



def _renomear_selecionados(modo: str, valor: str = "", base: str = "", de: str = "", para: str = "") -> str:
    arquivos = _obter_arquivos_selecionados()
    if not arquivos:
        return (
            "Não achei nenhum arquivo selecionado no Explorer, Vitor! "
            "Seleciona os arquivos no Explorer antes de dar o comando."
        )

    sucessos: list[str] = []
    erros: list[str] = []

    for i, arquivo in enumerate(arquivos, start=1):
        try:
            stem = arquivo.stem
            suffix = arquivo.suffix

            if modo == "prefixo":
                novo_nome = f"{valor}{arquivo.name}"

            elif modo == "sufixo":
                novo_nome = f"{stem}{valor}{suffix}"

            elif modo == "numerar":
                nome_base = base if base else stem
                novo_nome = f"{nome_base}_{i:02d}{suffix}"

            elif modo == "substituir":
                if not de:
                    erros.append(f"{arquivo.name} (precisa dizer qual parte do nome substituir)")
                    continue
                novo_nome = arquivo.name.replace(de, para)

            elif modo == "exato":
                if len(arquivos) == 1:
                    novo_nome = f"{valor}{suffix}" if not Path(valor).suffix else valor
                else:
                    novo_nome = f"{valor}_{i:02d}{suffix}"

            else:
                novo_nome = f"{stem}_{i:02d}{suffix}"

            destino = arquivo.parent / novo_nome

            if destino.exists() and destino != arquivo:
                erros.append(f"{arquivo.name} (já existe um arquivo chamado '{novo_nome}')")
                continue

            if destino == arquivo:
                erros.append(f"{arquivo.name} (nome novo igual ao atual)")
                continue

            arquivo.rename(destino)
            sucessos.append(f"{arquivo.name} → {novo_nome}")

        except Exception as e:
            erros.append(f"{arquivo.name} ({e})")

    resposta = f"Renomeei {len(sucessos)} arquivo(s)!"
    if sucessos:
        preview = sucessos[:5]
        resposta += " " + ", ".join(preview)
        if len(sucessos) > 5:
            resposta += f" e mais {len(sucessos) - 5}..."
    if erros:
        resposta += f" Problemas com: {', '.join(erros)}"
    return resposta

# ─────────────────────────────────────────────────────────────────
# SISTEMA DE DESFAZER (UNDO)
# ─────────────────────────────────────────────────────────────────

_UNDO_BACKUP_DIR = Path.home() / ".emily_undo_backup"
_historico_undo: list[dict] = []
_UNDO_MAX = 10  # guarda até 10 ações


def _registrar_undo(entrada: dict) -> None:
    """Empilha uma ação no histórico. Se passar de 10, limpa a mais antiga."""
    _historico_undo.append(entrada)
    if len(_historico_undo) > _UNDO_MAX:
        antiga = _historico_undo.pop(0)
        # Se era um delete com backup, limpa a pasta de backup
        if antiga.get("tipo") == "deletar":
            backup_dir = Path(antiga.get("backup_dir", ""))
            if backup_dir.exists():
                try:
                    shutil.rmtree(str(backup_dir))
                except Exception:
                    pass


def desfazer_ultima_acao() -> str:
    """Desfaz a última ação de arquivo registrada."""
    if not _historico_undo:
        return "Não tem nada pra desfazer, Vitor!"

    entrada = _historico_undo.pop()
    tipo = entrada.get("tipo")

    try:
        # ── Desfazer mover (arquivo único) ──
        if tipo == "mover":
            destino_atual = Path(entrada["destino_final"])
            origem_original = Path(entrada["origem_original"])
            if not destino_atual.exists():
                return f"Não achei '{destino_atual.name}' pra desfazer."
            origem_original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destino_atual), str(origem_original))
            return f"Desfiz! Movi '{destino_atual.name}' de volta pra '{origem_original.parent.name}'."

        # ── Desfazer mover (vários arquivos) ──
        elif tipo == "mover_varios":
            sucessos, erros = [], []
            for item in entrada["itens"]:
                dest = Path(item["destino_final"])
                orig = Path(item["origem_original"])
                try:
                    if dest.exists():
                        orig.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(dest), str(orig))
                        sucessos.append(dest.name)
                    else:
                        erros.append(dest.name)
                except Exception as e:
                    erros.append(f"{dest.name} ({e})")
            resp = f"Desfiz! Movi {len(sucessos)} arquivo(s) de volta."
            if erros:
                resp += f" Não consegui reverter: {', '.join(erros)}"
            return resp

        # ── Desfazer copiar ──
        elif tipo == "copiar":
            sucessos, erros = [], []
            for caminho_str in entrada["caminhos_copiados"]:
                p = Path(caminho_str)
                try:
                    if p.exists():
                        shutil.rmtree(str(p)) if p.is_dir() else p.unlink()
                        sucessos.append(p.name)
                except Exception as e:
                    erros.append(f"{p.name} ({e})")
            resp = f"Desfiz! Deletei {len(sucessos)} cópia(s)."
            if erros:
                resp += f" Problemas: {', '.join(erros)}"
            return resp

        # ── Desfazer deletar (restaura do backup) ──
        elif tipo == "deletar":
            backup_dir = Path(entrada["backup_dir"])
            sucessos, erros = [], []
            for item in entrada["arquivos_backup"]:
                bkp = Path(item["backup"])
                orig = Path(item["original"])
                try:
                    if bkp.exists():
                        orig.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(bkp), str(orig))
                        sucessos.append(orig.name)
                    else:
                        erros.append(orig.name)
                except Exception as e:
                    erros.append(f"{orig.name} ({e})")
        
        elif tipo == "criar":
            caminho = Path(entrada["caminho"])
            if not caminho.exists():
                return f"'{caminho.name}' não existe mais nada pra desfazer."
            _enviar_para_lixeira(caminho)
            return f"Desfiz! Mandei '{caminho.name}' pra lixeira."

        
            # limpa pasta de backup se ficou vazia
            try:
                if backup_dir.exists() and not any(backup_dir.iterdir()):
                    backup_dir.rmdir()
            except Exception:
                pass
            resp = f"Desfiz! Restaurei {len(sucessos)} arquivo(s)."
            if erros:
                resp += f" Não consegui restaurar: {', '.join(erros)}"
            return resp

        # ── Desfazer renomear (arquivo único) ──
        elif tipo == "renomear":
            nome_novo = Path(entrada["nome_novo"])
            nome_antigo = Path(entrada["nome_antigo"])
            if not nome_novo.exists():
                return f"Não achei '{nome_novo.name}' pra desfazer a renomeação."
            if nome_antigo.exists():
                return f"Já existe '{nome_antigo.name}' na pasta. Não consigo desfazer."
            nome_novo.rename(nome_antigo)
            return f"Desfiz! Renomeei de volta pra '{nome_antigo.name}'."

        # ── Desfazer renomear (vários arquivos) ──
        elif tipo == "renomear_varios":
            sucessos, erros = [], []
            for item in reversed(entrada["itens"]):
                nome_novo = Path(item["nome_novo"])
                nome_antigo = Path(item["nome_antigo"])
                try:
                    if nome_novo.exists() and not nome_antigo.exists():
                        nome_novo.rename(nome_antigo)
                        sucessos.append(nome_antigo.name)
                    else:
                        erros.append(nome_novo.name)
                except Exception as e:
                    erros.append(f"{nome_novo.name} ({e})")
            resp = f"Desfiz! Renomeei {len(sucessos)} arquivo(s) de volta."
            if erros:
                resp += f" Não consegui reverter: {', '.join(erros)}"
            return resp

    except Exception as e:
        return f"Deu erro ao tentar desfazer: {e}"

    return "Não sei como desfazer essa ação."


# ─────────────────────────────────────────────────────────────────
# INTERPRETAÇÃO COM LLM — Fireworks AI
# ─────────────────────────────────────────────────────────────────

def _interpretar_com_llm(mensagem: str) -> Optional[dict]:
    cached = _llm_cache_get(mensagem)
    if cached:
        print (f"[DEBUG automacao] LLM cache hit: '{mensagem}'")
        return cached
    try:
        system_content = EMILY_PERSONALIDADE + """

Você interpreta comandos de automação do PC.
Analise a mensagem e retorne APENAS um JSON válido, sem texto adicional.
Sempre inclua um campo "resposta" no JSON com uma frase curta e direta no seu estilo confirmando o que vai fazer.
A resposta deve ter no máximo 1 frase. Sem enrolação.

Exemplos de resposta:
{"acao": "abrir_app", "alvo": "discord", "resposta": "Abrindo o Discord pra você!"}
{"acao": "deletar_selecionados", "resposta": "Mandando tudo pra lixeira!"}
{"acao": "mover_selecionados", "destino": "downloads", "resposta": "Movendo os arquivos pros Downloads!"}
{"acao": "abrir_pasta", "alvo": "downloads", "resposta": "Abrindo a pasta Downloads!"}

IMPORTANTE: Corrija erros de digitação mesmo que sejam vários erros.
Tente identificar o app/jogo mais provável pelo contexto.

=== TAREFAS MÚLTIPLAS ===
Quando o usuário pedir várias ações em sequência (usar "e depois", "e também", "e em seguida", ou listar ações separadas por vírgula), retorne:
{"acoes": [{"acao": "...", ...}, {"acao": "...", ...}], "resposta": "Vou fazer tudo isso!"}

Cada item de "acoes" segue o mesmo formato das ações individuais abaixo.

Exemplos:
"abre o discord e o spotify"
→ {"acoes": [{"acao": "abrir_app", "alvo": "discord", "resposta": "Abrindo o Discord!"}, {"acao": "abrir_app", "alvo": "spotify", "resposta": "Abrindo o Spotify!"}], "resposta": "Abrindo os dois pra você!"}

"move o relatorio.pdf dos documentos pra downloads e depois renomeia pra relatorio_final"
→ {"acoes": [{"acao": "mover_arquivo", "origem": "relatorio.pdf", "pasta_origem": "documentos", "destino": "downloads", "resposta": "Movendo o arquivo!"}, {"acao": "renomear_arquivo", "alvo": "relatorio.pdf", "pasta": "downloads", "novo_nome": "relatorio_final", "resposta": "Renomeando!"}], "resposta": "Movendo e renomeando pra você!"}

"fecha o chrome, abre o brave e vai no youtube"
→ {"acoes": [{"acao": "fechar_app", "alvo": "chrome", "resposta": "Fechando o Chrome!"}, {"acao": "abrir_app", "alvo": "brave", "resposta": "Abrindo o Brave!"}, {"acao": "abrir_site", "alvo": "https://youtube.com", "resposta": "Indo pro YouTube!"}], "resposta": "Trocando o navegador e abrindo o YouTube!"}

=== AÇÕES DISPONÍVEIS ===

{"acao": "abrir_app", "alvo": "nome_do_app"}
  → Para programas, ferramentas e aplicativos instalados.

{"acao": "abrir_pasta", "alvo": "nome_da_pasta"}
  → Para abrir pastas/diretórios no Explorer. Use quando ouvir "abre a pasta", "vai na pasta", "mostra a pasta".
  Exemplos de pastas: "downloads", "desktop", "documentos", "imagens", "videos"
  Exemplo: "abre a pasta downloads" → {"acao": "abrir_pasta", "alvo": "downloads"}
  Exemplo: "vai na pasta documentos" → {"acao": "abrir_pasta", "alvo": "documentos"}

{"acao": "abrir_pasta", "alvo": "nome_da_pasta", "pasta": "pasta_pai_se_mencionada", "drive": "unidade_se_mencionada"}
  → O campo "pasta" indica ONDE procurar a pasta (ex: "downloads", "documentos").
  → O campo "drive" indica em qual unidade, se mencionada.
  → Se o usuário disser "pasta X em Y" ou "pasta X dentro de Y", use "pasta": "Y" e "alvo": "X".
  → Se o usuário só mencionar uma unidade sem pasta-pai, use "drive" e deixe "pasta" vazio.

  Exemplos:
  "abre a pasta teste em downloads"                        → {"acao": "abrir_pasta", "alvo": "teste", "pasta": "downloads", "drive": ""}
  "abre a pasta teste em downloads na unidade C"           → {"acao": "abrir_pasta", "alvo": "teste", "pasta": "downloads", "drive": "unidade c"}
  "abre a pasta Mods do Hollow Knight na unidade E"        → {"acao": "abrir_pasta", "alvo": "Mods", "pasta": "Hollow Knight", "drive": "unidade e"}
  "abre a pasta downloads da unidade D"                    → {"acao": "abrir_pasta", "alvo": "downloads", "pasta": "", "drive": "unidade d"}
  "abre a pasta Projetos nos documentos"                   → {"acao": "abrir_pasta", "alvo": "Projetos", "pasta": "documentos", "drive": ""}
  "vai na pasta do RadminVPN"                              → {"acao": "abrir_pasta", "alvo": "RadminVPN", "pasta": "", "drive": ""}

{"acao": "abrir_jogo", "alvo": "nome_do_jogo"}
  → Para jogos (Steam, Epic, GOG, etc). Use quando ouvir palavras como
    "jogo", "game", "jogar", ou for claramente o nome de um jogo.
  Exemplos: "Hollow Knight", "Minecraft", "GTA V", "CS2", "Cyberpunk",
            "Elden Ring", "Dead Cells", "Terraria", "Stardew Valley"

{"acao": "fechar_app", "alvo": "nome_do_app"}
  → Para fechar programas.

{"acao": "copiar_arquivo", "origem": "nome_do_arquivo", "pasta_origem": "pasta_de_origem_se_mencionada", "destino": "pasta_de_destino"}
  → Para COPIAR um arquivo mantendo o original. Use quando ouvir "copiar", "copia", "duplicar".
  Exemplo: "copia o relatorio.pdf dos documentos pra área de trabalho"
  → {"acao": "copiar_arquivo", "origem": "relatorio.pdf", "pasta_origem": "documentos", "destino": "área de trabalho"}

{"acao": "mover_arquivo", "origem": "nome_do_arquivo", "pasta_origem": "pasta_de_origem_se_mencionada", "destino": "pasta_de_destino"}
  → Para MOVER/RECORTAR um arquivo (remove do lugar original). Use quando ouvir "mover", "recortar", "recorta".
  Exemplo: "recorta o video.mp4 dos downloads e cola na área de trabalho"
  → {"acao": "mover_arquivo", "origem": "video.mp4", "pasta_origem": "downloads", "destino": "área de trabalho"}

{"acao": "mover_pasta", "alvo": "nome_da_pasta_ou_jogo", "drive_origem": "unidade_de_origem_se_mencionada", "drive_destino": "unidade_de_destino_se_mencionada", "pasta_destino": "pasta_dentro_do_destino_se_houver"}
  → Use para mover pastas inteiras, especialmente jogos e apps entre unidades.
  → O nome da pasta/jogo SEMPRE vai em "alvo". Nunca misture o nome com as unidades.
  → "drive_origem" e "drive_destino" são sempre as letras/nomes das unidades mencionadas.

{"acao": "copiar_pasta", "alvo": "nome_da_pasta_ou_jogo", "drive_origem": "unidade_de_origem", "drive_destino": "unidade_de_destino", "pasta_destino": "subpasta_no_destino_se_houver"}
  → Igual ao mover_pasta mas MANTÉM o original. Use quando ouvir "copiar", "copia", "duplicar".

  Exemplos:
  "copia a pasta do Hollow Knight da unidade C pra unidade H"
    → {"acao": "copiar_pasta", "alvo": "Hollow Knight", "drive_origem": "unidade c", "drive_destino": "unidade h", "pasta_destino": ""}

  "duplica a pasta Projetos do desktop pra unidade D"
    → {"acao": "copiar_pasta", "alvo": "Projetos", "drive_origem": "", "drive_destino": "unidade d", "pasta_destino": ""}

  Exemplos:
  "move a pasta do Elden Ring Nightreign da unidade H pra unidade C"
    → {"acao": "mover_pasta", "alvo": "Elden Ring Nightreign", "drive_origem": "unidade h", "drive_destino": "unidade c", "pasta_destino": ""}

  "move a pasta do Hollow Knight do NVME pro SSD"
    → {"acao": "mover_pasta", "alvo": "Hollow Knight", "drive_origem": "nvme", "drive_destino": "ssd", "pasta_destino": ""}

  "move a pasta Downloads da unidade D pra unidade H"
    → {"acao": "mover_pasta", "alvo": "downloads", "drive_origem": "unidade d", "drive_destino": "unidade h", "pasta_destino": ""}

  "move a pasta Projetos da área de trabalho pra unidade E na pasta Backup"
    → {"acao": "mover_pasta", "alvo": "Projetos", "drive_origem": "", "drive_destino": "unidade e", "pasta_destino": "Backup"}

{"acao": "renomear_arquivo", "alvo": "nome_atual_do_arquivo", "pasta": "pasta_onde_está_se_mencionada", "novo_nome": "novo_nome_desejado"}
  → Para renomear arquivo ou pasta. Use quando ouvir "renomear", "muda o nome", "troca o nome".
  Exemplo: "renomeia o arquivo teste.txt dos documentos pra relatorio_final"
  → {"acao": "renomear_arquivo", "alvo": "teste.txt", "pasta": "documentos", "novo_nome": "relatorio_final"}

{"acao": "abrir_arquivo", "alvo": "nome_do_arquivo", "pasta": "nome_da_pasta_se_mencionada"}
  → Para abrir arquivos específicos. Se uma pasta for mencionada, coloque em "pasta".
  Exemplos de pasta: "downloads", "desktop", "documentos", "steam", "program files"

{"acao": "abrir_exe", "alvo": "nome_do_exe", "pasta": "pasta_onde_está"}
  → Para abrir um executável específico em uma pasta específica.
  Exemplo: "abre AnyDesk.exe na pasta downloads" → {"acao": "abrir_exe", "alvo": "AnyDesk.exe", "pasta": "downloads"}

{"acao": "abrir_site", "alvo": "url"}
  → Para abrir sites.

{"acao": "fechar_aba", "alvo": "nome_do_site_ou_vazio"}
  → Fecha uma aba específica do navegador pelo título da página.
  → Use para sites conhecidos: YouTube, Netflix, Twitch, Twitter, Instagram, Gmail, etc.
  → Se o usuário disser "fecha essa aba" ou "fecha a aba atual", deixa "alvo" vazio ("").
  → DIFERENÇA IMPORTANTE:
      - "fecha o YouTube/Netflix/Twitch" → fechar_aba (é um site, fecha a aba)
      - "fecha o Chrome/Brave/Firefox"  → fechar_app (é o navegador inteiro)

  Exemplos:
  "fecha o YouTube"         → {"acao": "fechar_aba", "alvo": "YouTube", "resposta": "Fechando o YouTube!"}
  "fecha a aba do Netflix"  → {"acao": "fechar_aba", "alvo": "Netflix", "resposta": "Fechando o Netflix!"}
  "fecha essa aba"          → {"acao": "fechar_aba", "alvo": "", "resposta": "Fechando a aba!"}
  "fecha o Brave"           → {"acao": "fechar_app", "alvo": "brave", "resposta": "Fechando o Brave!"}

{"acao": "minimizar_app", "alvo": "nome_do_app"}
  → Minimiza a janela de um programa para a barra de tarefas.
  Exemplos:
  "minimiza o Discord"  → {"acao": "minimizar_app", "alvo": "Discord", "resposta": "Minimizando o Discord!"}
  "esconde o Chrome"    → {"acao": "minimizar_app", "alvo": "Chrome",  "resposta": "Minimizando o Chrome!"}

{"acao": "maximizar_app", "alvo": "nome_do_app"}
  → Maximiza/restaura a janela de um programa.
  Exemplos:
  "maximiza o Discord"  → {"acao": "maximizar_app", "alvo": "Discord", "resposta": "Maximizando o Discord!"}
  "expande o VS Code"   → {"acao": "maximizar_app", "alvo": "VS Code",  "resposta": "Maximizando o VS Code!"}

{"acao": "deletar_arquivo", "alvo": "nome_do_arquivo", "pasta": "pasta_se_mencionada"}
  → Para deletar um arquivo específico.

=== AÇÕES PARA ARQUIVOS SELECIONADOS NO EXPLORER ===
Use essas ações quando o usuário disser "selecionados", "arquivos selecionados", "os selecionados", "esses arquivos".

{"acao": "copiar_selecionados", "destino": "pasta_principal", "subpasta": "subpasta_dentro_dela_se_mencionada", "drive": "unidade_se_mencionada"}
{"acao": "mover_selecionados",  "destino": "pasta_principal", "subpasta": "subpasta_dentro_dela_se_mencionada", "drive": "unidade_se_mencionada"}

  → "destino"  = pasta principal / jogo / app mencionado
  → "subpasta" = pasta DENTRO do destino, se o usuário for mais específico
  → "drive"    = unidade onde fica o destino

  Exemplos:
  "copia os selecionados pra pasta GAME do Elden Ring na unidade E"
    → {"acao": "copiar_selecionados", "destino": "Elden Ring", "subpasta": "GAME", "drive": "unidade e"}

  "move os selecionados pra pasta Mods dentro do Hollow Knight no NVME"
    → {"acao": "mover_selecionados", "destino": "Hollow Knight", "subpasta": "Mods", "drive": "nvme"}

  "copia os selecionados pra pasta downloads"
    → {"acao": "copiar_selecionados", "destino": "downloads", "subpasta": "", "drive": ""}

  "manda os selecionados pra unidade H"
    → {"acao": "mover_selecionados", "destino": "", "subpasta": "", "drive": "unidade h"}
    
{"acao": "deletar_selecionados"}
{"acao": "renomear_selecionados", "modo": "exato|prefixo|sufixo|numerar|substituir", "valor": "nome desejado", ...}
  - exato:      renomeia pro nome exato informado. Use quando o usuário disser "renomeia pra X", "muda o nome pra X"
  - prefixo:    adiciona texto no início
  - sufixo:     adiciona texto no final
  - numerar:    renomeia com base + número sequencial
  - substituir: troca uma parte do nome por outra (precisa de "de" e "para" preenchidos)

Exemplos:
"renomeia os selecionados pra relatorio_final" → {"acao": "renomear_selecionados", "modo": "exato", "valor": "relatorio_final"}
"adiciona prefixo backup nos selecionados"    → {"acao": "renomear_selecionados", "modo": "prefixo", "valor": "backup_"}

{"acao": "tocar_musica", "musica": "nome da música", "artista": "artista se mencionado"}
  → Toca uma música específica abrindo o vídeo direto no YouTube.
  → Se o usuário mencionar artista, preenche "artista" pra ajudar na busca.
  → Se não mencionar artista, deixa "artista" vazio.
  → SEMPRE corrija erros de digitação/transcrição no nome da música.

  Exemplos:
  "toca Bohemian Rhapsody" → {"acao": "tocar_musica", "musica": "Bohemian Rhapsody", "artista": "", "resposta": "Tocando Bohemian Rhapsody!"}
  "toca Blinding Lights do The Weeknd" → {"acao": "tocar_musica", "musica": "Blinding Lights", "artista": "The Weeknd", "resposta": "Tocando Blinding Lights!"}
  "coloca aquela do Eminem, Lose Yourself" → {"acao": "tocar_musica", "musica": "Lose Yourself", "artista": "Eminem", "resposta": "Lose Yourself!"}

{"acao": "controle_musica", "controle": "tipo do controle"}
  → Controla a música que está tocando no momento.
  → "controle" pode ser: proxima, anterior, pausar, retomar, volume_up, volume_down, mute

  Exemplos:
  "próxima música"       → {"acao": "controle_musica", "controle": "proxima", "resposta": "Próxima!"}
  "pausa a música"       → {"acao": "controle_musica", "controle": "pausar", "resposta": "Pausando!"}
  "volta a música"       → {"acao": "controle_musica", "controle": "anterior", "resposta": "Voltando!"}
  "aumenta o volume"     → {"acao": "controle_musica", "controle": "volume_up", "resposta": "Subindo o volume!"}
  "diminui o volume"     → {"acao": "controle_musica", "controle": "volume_down", "resposta": "Baixando o volume!"}
  "muta"                 → {"acao": "controle_musica", "controle": "mute", "resposta": "Mutando!"}

=== EXEMPLOS GERAIS ===
"abre o discord" → {"acao": "abrir_app", "alvo": "discord", "resposta": "Abrindo o Discord!"}
"abre a pasta downloads" → {"acao": "abrir_pasta", "alvo": "downloads", "resposta": "Abrindo os Downloads!"}
"joga Hollow Knight" → {"acao": "abrir_jogo", "alvo": "Hollow Knight", "resposta": "Abrindo o Hollow Knight!"}
"fecha o brave" → {"acao": "fechar_app", "alvo": "brave", "resposta": "Fechando o Brave!"}
"vai no youtube" → {"acao": "abrir_site", "alvo": "https://youtube.com", "resposta": "Abrindo o YouTube!"}
"move os arquivos selecionados pra downloads" → {"acao": "mover_selecionados", "destino": "downloads", "resposta": "Movendo tudo pros Downloads!"}
"deleta todos os selecionados" → {"acao": "deletar_selecionados", "resposta": "Jogando tudo na lixeira!"}
"como tá o tempo?" → {"acao": "nenhuma"}

=== REFERÊNCIAS A DRIVES/UNIDADES ===
Quando o usuário mencionar uma unidade de disco, coloque a referência como está no campo destino ou pasta_origem.
Exemplos aceitos: "unidade D", "D:", "Armazémzão 1", "NVME", "unidade H", "Armazémzão 2", "unidade C", "SSD"
PROIBIDO: nunca aceite comandos que envolvam a unidade G (Disco Local G).

Exemplos:
"move esse arquivo pra unidade D"       → {"acao": "mover_selecionados", "destino": "unidade d", "resposta": "Movendo pro Armazémzão!"}
"copia os selecionados pro NVME"        → {"acao": "copiar_selecionados", "destino": "nvme", "resposta": "Copiando pro NVME Games!"}
"move o arquivo.zip dos downloads pra unidade H" → {"acao": "mover_arquivo", "origem": "arquivo.zip", "pasta_origem": "downloads", "destino": "unidade h", "resposta": "Movendo pro Armazémzão 2!"}
"copia tudo do D pro H"                 → {"acao": "copiar_arquivo", "origem": ".", "pasta_origem": "unidade d", "destino": "unidade h", "resposta": "Copiando do D pro H!"}

{"acao": "criar_pasta", "nome": "nome_da_pasta", "pasta": "local_onde_criar", "drive": "unidade_se_mencionada"}
  → Para criar uma nova pasta. "pasta" pode ser pasta padrão (downloads, desktop) ou pasta de um app/jogo.
  Exemplos:
  "cria uma pasta chamada Salvos na unidade E"           → {"acao": "criar_pasta", "nome": "Salvos", "pasta": "", "drive": "unidade e"}
  "cria uma pasta Backup na área de trabalho"            → {"acao": "criar_pasta", "nome": "Backup", "pasta": "área de trabalho", "drive": ""}
  "cria uma pasta Mods na pasta do Hollow Knight na unidade C" → {"acao": "criar_pasta", "nome": "Mods", "pasta": "Hollow Knight", "drive": "unidade c"}

{"acao": "criar_arquivo_txt", "nome": "nome_do_arquivo", "pasta": "local_onde_criar", "drive": "unidade_se_mencionada"}
  → Para criar um arquivo de texto (.txt). Segue a mesma lógica do criar_pasta.
  Exemplos:
  "cria um txt chamado Anotações na área de trabalho"   → {"acao": "criar_arquivo_txt", "nome": "Anotações", "pasta": "área de trabalho", "drive": ""}
  "cria um arquivo de texto na pasta do Dying Light na unidade H" → {"acao": "criar_arquivo_txt", "nome": "notas", "pasta": "Dying Light", "drive": "unidade h"}

{"acao": "extrair_arquivo", "alvo": "nome_do_arquivo", "pasta": "pasta_onde_está", "drive": "unidade_se_mencionada", "destino": "pasta_de_destino_se_mencionada", "modo": "pasta_ou_conteudo"}
  → "modo" define como extrair:
      "pasta"    → cria uma subpasta com o nome do arquivo e extrai pra dentro dela (padrão)
      "conteudo" → extrai os arquivos diretamente na pasta destino, sem criar subpasta
  → Use "conteudo" quando ouvir: "conteúdo", "arquivos dentro", "tudo dentro", "direto na pasta"

  Exemplos:
  "extrai o jogo.zip dos downloads"
    → {"acao": "extrair_arquivo", "alvo": "jogo.zip", "pasta": "downloads", "drive": "", "destino": "", "modo": "pasta"}

  "extrai o backup.rar e manda o conteúdo direto nos documentos"
    → {"acao": "extrair_arquivo", "alvo": "backup.rar", "pasta": "", "drive": "", "destino": "documentos", "modo": "conteudo"}

  "descompacta o mod.7z da pasta do Hollow Knight e joga o conteúdo nos downloads"
    → {"acao": "extrair_arquivo", "alvo": "mod.7z", "pasta": "Hollow Knight", "drive": "", "destino": "downloads", "modo": "conteudo"}

{"acao": "extrair_selecionados", "destino": "pasta_de_destino_se_mencionada", "modo": "pasta_ou_conteudo"}
  → Extrai todos os arquivos compactados selecionados no Explorer.
  → Use quando ouvir "selecionados", "esses arquivos", "os selecionados".

  Exemplos:
  "extrai os selecionados"
    → {"acao": "extrair_selecionados", "destino": "", "modo": "pasta"}

  "extrai os arquivos selecionados e manda o conteúdo pra unidade H"
    → {"acao": "extrair_selecionados", "destino": "unidade h", "modo": "conteudo"}

{"acao": "copiar_arquivos_da_pasta", "pasta_origem": "nome_da_pasta", "pasta_contexto": "pasta_pai_da_origem_se_mencionada", "drive_origem": "unidade_da_origem_se_mencionada", "destino": "pasta_de_destino", "drive_destino": "unidade_de_destino_se_mencionada", "arquivos": [], "excluir": []}
  → "pasta_contexto": onde fica a pasta_origem (ex: "downloads", "documentos"). Use quando o usuário disser "pasta X em Y".
  → "arquivos": lista específica a copiar. Vazio = copia tudo.
  → "excluir":  lista a ignorar (quando usuário diz "exceto", "menos").

  Exemplos:
  "pasta teste em downloads na unidade C e copia tudo pra unidade H"
    (dentro de acoes) → {"acao": "copiar_arquivos_da_pasta", "pasta_origem": "teste", "pasta_contexto": "downloads", "drive_origem": "unidade c", "destino": "", "drive_destino": "unidade h", "arquivos": [], "excluir": []}

  "copia todos os arquivos da pasta Mods do Hollow Knight pro desktop"
    → {"acao": "copiar_arquivos_da_pasta", "pasta_origem": "Mods", "pasta_contexto": "Hollow Knight", "drive_origem": "", "destino": "desktop", "drive_destino": "", "arquivos": [], "excluir": []}

  "copia os arquivos save1.dat e save2.dat da pasta Saves nos documentos pra unidade D"
    → {"acao": "copiar_arquivos_da_pasta", "pasta_origem": "Saves", "pasta_contexto": "documentos", "drive_origem": "", "destino": "", "drive_destino": "unidade d", "arquivos": ["save1.dat", "save2.dat"], "excluir": []}

{"acao": "deletar_arquivos_da_pasta", "pasta": "nome_da_pasta", "drive": "unidade_se_mencionada", "arquivos": ["arquivo_especifico"], "excluir": ["arquivo_a_preservar"]}
  → Deleta arquivos de dentro de uma pasta.
  → "arquivos": lista de nomes específicos pra deletar. Deixe [] se for deletar tudo (menos os excluídos).
  → "excluir":  lista de arquivos a PRESERVAR — usada quando o usuário diz "deleta tudo exceto X".
  → NUNCA preencha "arquivos" e "excluir" ao mesmo tempo.

  Exemplos:
  "deleta todos os arquivos da pasta Temp nos downloads"
    → {"acao": "deletar_arquivos_da_pasta", "pasta": "Temp", "drive": "", "arquivos": [], "excluir": []}

  "limpa a pasta Cache do Brave na unidade C, mas mantém o arquivo Cookies"
    → {"acao": "deletar_arquivos_da_pasta", "pasta": "Cache", "drive": "unidade c", "arquivos": [], "excluir": ["Cookies"]}

  "deleta só o arquivo old_save.dat da pasta Saves do Hollow Knight"
    → {"acao": "deletar_arquivos_da_pasta", "pasta": "Saves", "drive": "", "arquivos": ["old_save.dat"], "excluir": []}

=== AÇÕES COMPOSTAS — "abre e faz X" ===
Quando o usuário pedir pra abrir uma pasta E fazer algo com os arquivos dela,
use o sistema de múltiplas ações ("acoes") combinando "abrir_pasta" com as ações acima.

Exemplos:
"abre a pasta Saves do Hollow Knight e copia tudo pro desktop"
  → {"acoes": [
      {"acao": "abrir_pasta", "alvo": "Saves", "resposta": "Abrindo a pasta!"},
      {"acao": "copiar_arquivos_da_pasta", "pasta_origem": "Saves", "drive_origem": "", "destino": "desktop", "drive_destino": "", "arquivos": [], "excluir": [], "resposta": "Copiando tudo!"}
    ], "resposta": "Abrindo e copiando tudo pro Desktop!"}

"abre a pasta Mods do Hollow Knight na unidade E e deleta tudo exceto o readme.txt"
  → {"acoes": [
      {"acao": "abrir_pasta", "alvo": "Mods", "drive": "unidade e", "resposta": "Abrindo a pasta!"},
      {"acao": "deletar_arquivos_da_pasta", "pasta": "Mods", "drive": "unidade e", "arquivos": [], "excluir": ["readme.txt"], "resposta": "Deletando tudo exceto o readme!"}
    ], "resposta": "Abrindo e limpando a pasta!"}

"move a pasta Saves do Elden Ring na unidade H pro SSD e copia os arquivos save1 e save2 dela pros downloads"
  → {"acoes": [
      {"acao": "mover_pasta", "alvo": "Saves", "drive_origem": "unidade h", "drive_destino": "ssd", "pasta_destino": "", "resposta": "Movendo a pasta!"},
      {"acao": "copiar_arquivos_da_pasta", "pasta_origem": "Saves", "drive_origem": "unidade h", "destino": "downloads", "drive_destino": "", "arquivos": ["save1", "save2"], "excluir": [], "resposta": "Copiando os saves!"}
    ], "resposta": "Movendo a pasta e salvando os arquivos nos Downloads!"}

{"acao": "criar_modo", "nome": "Nome do Modo", "gatilhos": ["gatilho1", "gatilho2"], "acoes": [...]}
  → Cria ou atualiza um modo. As ações seguem o mesmo formato das ações normais.
  → "gatilhos" são palavras extras que também ativam o modo (além do nome).
  → Use quando ouvir: "cria um modo", "novo modo", "faz um modo chamado X que faz Y".

  Exemplos:
  "cria um modo chamado Estudos que abre o vscode e o chrome e fecha o discord"
    → {"acao": "criar_modo", "nome": "Estudos", "gatilhos": ["estudos", "estudar"],
       "acoes": [
         {"acao": "abrir_app",  "alvo": "vscode",   "resposta": "Abrindo VS Code!"},
         {"acao": "abrir_app",  "alvo": "chrome",   "resposta": "Abrindo Chrome!"},
         {"acao": "fechar_app", "alvo": "discord",  "resposta": "Fechando Discord!"}
       ], "resposta": "Modo Estudos criado!"}

  "cria um modo Trabalho que abre o outlook, o teams e vai no gmail"
    → {"acao": "criar_modo", "nome": "Trabalho", "gatilhos": ["trabalho", "trabalhar"],
       "acoes": [
         {"acao": "abrir_app",  "alvo": "outlook",               "resposta": "Abrindo Outlook!"},
         {"acao": "abrir_app",  "alvo": "teams",                 "resposta": "Abrindo Teams!"},
         {"acao": "abrir_site", "alvo": "https://gmail.com",     "resposta": "Abrindo Gmail!"}
       ], "resposta": "Modo Trabalho criado!"}

       {"acao": "instalar_jogo_steam", "alvo": "nome_do_jogo", "drive": "unidade_se_mencionada"}
  → Abre a instalação do jogo na Steam. Use quando ouvir "instala", "baixa o jogo", "instalar na Steam".
  → "drive" só é preenchido se o usuário mencionar uma unidade específica.

  Exemplos:
  "instala o Celeste na unidade E"
    → {"acao": "instalar_jogo_steam", "alvo": "Celeste", "drive": "unidade e", "resposta": "Abrindo a instalação do Celeste!"}

  "baixa o Hollow Knight"
    → {"acao": "instalar_jogo_steam", "alvo": "Hollow Knight", "drive": "", "resposta": "Abrindo a instalação do Hollow Knight!"}

{"acao": "desinstalar_jogo_steam", "alvo": "nome_do_jogo"}
  → Abre a desinstalação do jogo na Steam. Use quando ouvir "desinstala", "remove da Steam", "apaga o jogo".

  Exemplos:
  "desinstala o Celeste na Steam"
    → {"acao": "desinstalar_jogo_steam", "alvo": "Celeste", "resposta": "Abrindo a desinstalação do Celeste!"}

  "remove o Hollow Knight da Steam"
    → {"acao": "desinstalar_jogo_steam", "alvo": "Hollow Knight", "resposta": "Removendo o Hollow Knight!"}

=== CORREÇÃO DE ERROS DE DIGITAÇÃO ===
"discrod", "discordi" → "discord"
"spotfy", "sptify" → "spotify"
"chorme", "crhome" → "chrome"
"hollw knight", "hollow nigt" → "Hollow Knight"
"minecrft", "mincraft" → "Minecraft"
"gta v", "gta 5" → "GTA V"
"elden rign", "eldenring" → "Elden Ring"
"""

        completion = _fw_client.chat.completions.create(
            model="accounts/fireworks/models/kimi-k2p6",
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": mensagem}
            ],
            max_tokens=256,
            extra_body={"reasoning_effort": "none"},
        )

        texto = completion.choices[0].message.content or ""

        if not texto.strip():
            try:
                thinking = completion.choices[0].message.reasoning_content or ""
                match = re.search(r"\{.*?\}", thinking, re.DOTALL)
                if match:
                    texto = match.group(0)
            except Exception:
                pass

        if not texto.strip():
            print("[DEBUG automacao] Kimi retornou resposta vazia")
            return None
        
        texto = re.sub(r"```json|```", "", texto).strip()  # limpa primeiro
        resultado_parsed = json.loads(texto)
        _llm_cache_set(mensagem, resultado_parsed)
        return resultado_parsed

    except Exception as e:
        print(f"[DEBUG automacao] Erro LLM: {e}")
        return None



def _eh_possivel_comando(texto: str) -> bool:
    return (
        any(_contem_palavra(texto, p) for p in KEYWORDS_ABRIR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_RECORTAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_COPIAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_RENOMEAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_DESFAZER)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_SITE)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_FECHAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_DELETAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_JOGO)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_SELECIONADOS)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_CRIAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_EXTRAIR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_MODO)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_CRIAR_MODO)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_DELETAR_MODO)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_LISTAR_MODOS)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_STEAM_INSTALAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_STEAM_DESINSTALAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_MUSICA)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_CONTROLE_MUSICA)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_MINIMIZAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_MAXIMIZAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_FECHAR_ABA)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_SPEEDRUN_INICIAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_SPEEDRUN_PAUSAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_SPEEDRUN_CONTINUAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_SPEEDRUN_PARAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_SPEEDRUN_LISTAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_AGENTE_INICIAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_AGENTE_PAUSAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_AGENTE_CONTINUAR)
        or any(_contem_palavra(texto, p) for p in KEYWORDS_AGENTE_PARAR)
    )

# ─────────────────────────────────────────────────────────────────
# MONITORAMENTO DA ÚLTIMA JANELA EXPLORER EM FOCO
# ─────────────────────────────────────────────────────────────────

_ultima_janela_explorer: Optional[int] = None  # hwnd da última janela Explorer/Desktop em foco

def _monitorar_janela_explorer() -> None:
    """
    Roda em background e salva o hwnd da última janela Explorer ou Desktop
    que ficou em foco. Assim quando a Emily for chamada, ela ainda sabe
    qual janela estava ativa antes.
    """
    if os.name != "nt":
        return

    import time
    try:
        import win32gui
    except ImportError:
        return

    global _ultima_janela_explorer

    # Classes de janela que representam Explorer ou Desktop
    CLASSES_EXPLORER = {"CabinetWClass", "ExploreWClass", "Progman", "WorkerW"}

    while True:
        try:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                classe = win32gui.GetClassName(hwnd)
                if classe in CLASSES_EXPLORER:
                    _ultima_janela_explorer = hwnd
        except Exception:
            pass
        time.sleep(0.25)  # verifica 4 vezes por segundo

# ─────────────────────────────────────────────────────────────────
# STEAM — INSTALAÇÃO E DESINSTALAÇÃO DE JOGOS
# ─────────────────────────────────────────────────────────────────

_STEAM_APPLIST_PATH = Path.home() / ".emily_steam_applist.json"
_steam_applist_cache: dict = {}
_steam_applist_carregado = False


def _ler_manifests_instalados() -> dict:
    """
    Lê os arquivos .acf do Steam e retorna um dict de jogos instalados.
    Formato: {nome_normalizado: (appid, nome_real)}
    """
    jogos = {}
    for steam_lib in _get_steam_libraries():
        steamapps = steam_lib.parent  # steam_lib = steamapps/common
        for manifest in steamapps.glob("appmanifest_*.acf"):
            try:
                conteudo = manifest.read_text(encoding="utf-8", errors="ignore")
                appid_m = re.search(r'"appid"\s+"(\d+)"', conteudo)
                name_m  = re.search(r'"name"\s+"([^"]+)"', conteudo)
                if appid_m and name_m:
                    appid     = int(appid_m.group(1))
                    nome_real = name_m.group(1)
                    jogos[_normalizar_nome_app(nome_real)] = (appid, nome_real)
            except Exception:
                continue
    return jogos


def _encontrar_appid_instalado(nome_jogo: str) -> Optional[tuple]:
    """
    Busca AppID nos manifests de jogos INSTALADOS.
    Retorna (appid, nome_real) ou None.
    """
    nome_norm = _normalizar_nome_app(nome_jogo)
    jogos = _ler_manifests_instalados()

    if nome_norm in jogos:
        return jogos[nome_norm]

    for nome_instalado, dados in jogos.items():
        if nome_norm in nome_instalado or nome_instalado in nome_norm:
            return dados

    proximos = difflib.get_close_matches(nome_norm, list(jogos.keys()), n=1, cutoff=0.5)
    if proximos:
        return jogos[proximos[0]]

    return None


def _carregar_applist_steam() -> dict:
    global _steam_applist_cache, _steam_applist_carregado

    if _steam_applist_carregado and _steam_applist_cache:  # ← checa se não tá vazio
        return _steam_applist_cache

    if _STEAM_APPLIST_PATH.exists():
        import time
        idade = time.time() - _STEAM_APPLIST_PATH.stat().st_mtime
        if idade < 7 * 24 * 3600:
            try:
                dados = json.loads(_STEAM_APPLIST_PATH.read_text(encoding="utf-8"))
                if dados:  # ← só usa o cache se não estiver vazio
                    _steam_applist_cache = dados
                    _steam_applist_carregado = True
                    print(f"[DEBUG steam] AppList carregada do cache: {len(_steam_applist_cache)} apps")
                    return _steam_applist_cache
            except Exception:
                pass

    print("[DEBUG steam] Baixando lista de apps da Steam...")

    # URLs corrigidas — v2 é a mais confiável, sem precisar de API key
    urls_tentar = [
        "https://api.steampowered.com/IStoreService/GetAppList/v1/?key=5678596EFF0F285280A99F679F139B60&max_results=50000",
        "https://api.steampowered.com/ISteamApps/GetAppList/v0001/",
        "https://api.steampowered.com/ISteamApps/GetAppList/v2/",
    ]

    dados = None
    for url in urls_tentar:
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                dados = json.loads(resp.read().decode("utf-8"))
            print(f"[DEBUG steam] AppList baixada de: {url}")
            break
        except Exception as e:
            print(f"[DEBUG steam] URL falhou ({url}): {e}")
            continue

    if not dados:
        print("[DEBUG steam] Não consegui baixar a AppList.")
        _steam_applist_carregado = True
        return {}

    try:
        # Suporta os diferentes formatos de resposta de cada endpoint
        apps_raw = (
            dados.get("applist", {}).get("apps")      # v2: {"applist": {"apps": [...]}}
            or dados.get("response", {}).get("apps")  # IStoreService: {"response": {"apps": [...]}}
            or []
        )

        # v0001 tem um nível a mais: {"applist": {"apps": {"app": [...]}}}
        if isinstance(apps_raw, dict):
            apps_raw = apps_raw.get("app", [])

        applist = {}
        for app in apps_raw:
            nome_norm = _normalizar_nome_app(app.get("name", ""))
            if nome_norm:
                applist[nome_norm] = app["appid"]

        if not applist:
            print("[DEBUG steam] AppList veio vazia, não vou salvar o cache.")
            return {}

        _STEAM_APPLIST_PATH.write_text(
            json.dumps(applist, ensure_ascii=False),
            encoding="utf-8"
        )
        _steam_applist_cache = applist
        _steam_applist_carregado = True
        print(f"[DEBUG steam] AppList salva: {len(applist)} apps")
        return applist
    except Exception as e:
        print(f"[DEBUG steam] Erro ao processar AppList: {e}")
        return {}


def _encontrar_appid_online(nome_jogo: str) -> Optional[tuple]:
    """
    Busca AppID na lista completa da Steam (qualquer jogo, instalado ou não).
    Retorna (appid, nome_encontrado) ou None.
    """
    nome_norm = _normalizar_nome_app(nome_jogo)
    applist = _carregar_applist_steam()

    if not applist:
        return None

    if nome_norm in applist:
        return applist[nome_norm], nome_jogo

    for nome_lista, appid in applist.items():
        if nome_norm in nome_lista or nome_lista in nome_norm:
            return appid, nome_lista

    proximos = difflib.get_close_matches(nome_norm, list(applist.keys()), n=1, cutoff=0.55)
    if proximos:
        return applist[proximos[0]], proximos[0]

    return None


def _biblioteca_no_drive(drive: Path) -> Optional[Path]:
    """Verifica se já existe uma biblioteca Steam no drive especificado."""
    for steam_lib in _get_steam_libraries():
        steamapps = steam_lib.parent
        if steamapps.drive.upper() == drive.drive.upper():
            return steamapps
    return None


def _desinstalar_jogo_steam(nome_jogo: str) -> str:
    resultado = _encontrar_appid_instalado(nome_jogo)
    if not resultado:
        return (
            f"Não achei '{nome_jogo}' instalado na Steam, Vitor! "
            f"Verifica se o nome tá certo."
        )
    appid, nome_real = resultado
    print(f"[DEBUG steam] Desinstalando '{nome_real}' (AppID: {appid})")
    _executar_start(f"steam://uninstall/{appid}")
    return f"Abrindo a desinstalação de '{nome_real}' na Steam! Só confirma na janela."


def _instalar_jogo_steam(nome_jogo: str, drive_hint: str = "") -> str:
    # Tenta primeiro nos instalados (reinstalação)
    resultado = _encontrar_appid_instalado(nome_jogo)

    # Se não achou instalado, busca na lista completa
    if not resultado:
        resultado = _encontrar_appid_online(nome_jogo)

    if not resultado:
        return (
            f"Não achei '{nome_jogo}' na Steam, Vitor! "
            f"Verifica o nome e tenta de novo."
        )

    appid, nome_encontrado = resultado
    print(f"[DEBUG steam] Instalando '{nome_encontrado}' (AppID: {appid})")

    aviso_drive = ""
    if drive_hint:
        drive = _resolver_drive(drive_hint)
        if drive:
            biblioteca = _biblioteca_no_drive(drive)
            if biblioteca:
                aviso_drive = (
                    f" Na janela que abrir, seleciona a biblioteca "
                    f"na unidade {drive.drive}."
                )
            else:
                aviso_drive = (
                    f" Atenção: não tem biblioteca Steam na unidade {drive.drive} ainda. "
                    f"Cria uma em Steam > Configurações > Downloads > "
                    f"Pastas de biblioteca Steam, e depois me pede pra instalar de novo."
                )

    _executar_start(f"steam://install/{appid}")
    return f"Abrindo a instalação de '{nome_encontrado}' na Steam!{aviso_drive}"

# ─────────────────────────────────────────────────────────────────
# SISTEMA DE MODOS — Conjuntos de ações ativáveis por nome
# ─────────────────────────────────────────────────────────────────

_MODOS_PATH = Path.home() / ".emily_modos.json"

# Modos que são criados automaticamente na primeira vez que rodar
_MODOS_PADRAO = {
    "gameplay": {
        "nome": "Gameplay",
        "gatilhos": ["gameplay", "game", "jogar", "modo game"],
        "acoes": [
            {"acao": "abrir_app",  "alvo": "steam",               "resposta": "Abrindo a Steam!"},
            {"acao": "abrir_app",  "alvo": "discord",             "resposta": "Abrindo o Discord!"},
            {"acao": "abrir_site", "alvo": "https://youtube.com", "resposta": "Abrindo o YouTube!"},
        ]
    },
    "programacao": {
        "nome": "Programação",
        "gatilhos": ["programação", "programacao", "programar", "codar"],
        "acoes": [
            {"acao": "abrir_app",  "alvo": "vscode",   "resposta": "Abrindo o VS Code!"},
            {"acao": "fechar_app", "alvo": "steam",    "resposta": "Fechando a Steam!"},
            {"acao": "fechar_app", "alvo": "discord",  "resposta": "Fechando o Discord!"},
        ]
    },
}

KEYWORDS_MODO = (
    "ativa modo", "ativa o modo", "ativar modo",
    "ativar o modo", "liga o modo", "liga modo",
    "iniciar modo", "iniciar o modo",
)

KEYWORDS_CRIAR_MODO = (
    "cria modo", "cria o modo", "criar modo", "criar o modo",
    "novo modo", "adiciona modo", "faz um modo",
)

KEYWORDS_DELETAR_MODO = (
    "deleta modo", "deleta o modo", "deletar modo",
    "apaga modo", "apaga o modo", "remove modo", "remove o modo",
)

KEYWORDS_LISTAR_MODOS = (
    "lista modos", "listar modos", "quais modos",
    "meus modos", "mostra os modos", "que modos",
)


def _carregar_modos() -> dict:
    """Lê o arquivo de modos. Se não existir, cria com os modos padrão."""
    if _MODOS_PATH.exists():
        try:
            return json.loads(_MODOS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[DEBUG modos] Erro ao ler modos: {e}")
    _salvar_modos(_MODOS_PADRAO)
    return dict(_MODOS_PADRAO)


def _salvar_modos(modos: dict) -> None:
    try:
        _MODOS_PATH.write_text(
            json.dumps(modos, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"[DEBUG modos] Erro ao salvar modos: {e}")


def _encontrar_modo(texto: str) -> Optional[tuple[str, dict]]:
    """
    Acha um modo pelo nome ou por um dos gatilhos, com fuzzy matching.
    Retorna (chave, dados_do_modo) ou None.
    """
    modos = _carregar_modos()
    texto_norm = _normalizar(texto)

    for chave, modo in modos.items():
        # Match no nome do modo
        if _normalizar(modo["nome"]) in texto_norm or texto_norm in _normalizar(modo["nome"]):
            return chave, modo
        # Match nos gatilhos
        for gatilho in modo.get("gatilhos", []):
            if _normalizar(gatilho) in texto_norm:
                return chave, modo

    # Fuzzy como último recurso
    nomes_norm = {chave: _normalizar(modo["nome"]) for chave, modo in modos.items()}
    proximos = difflib.get_close_matches(texto_norm, list(nomes_norm.values()), n=1, cutoff=0.5)
    if proximos:
        for chave, nome_norm in nomes_norm.items():
            if nome_norm == proximos[0]:
                return chave, modos[chave]

    return None


def _ativar_modo(nome_modo: str) -> str:
    resultado = _encontrar_modo(nome_modo)
    if not resultado:
        modos = _carregar_modos()
        nomes = [m["nome"] for m in modos.values()]
        sugestao = f" Seus modos: {', '.join(nomes)}." if nomes else ""
        return f"Não conheço nenhum modo chamado '{nome_modo}', Vitor!{sugestao}"

    chave, modo = resultado
    acoes = modo.get("acoes", [])
    if not acoes:
        return f"O modo '{modo['nome']}' tá vazio, Vitor! Adiciona algumas ações nele."

    print(f"[DEBUG modos] Ativando modo '{modo['nome']}' com {len(acoes)} ação(ões)")
    return _executar_sequencia(acoes, f"Ativando modo {modo['nome']}!")


def _listar_modos() -> str:
    modos = _carregar_modos()
    if not modos:
        return "Você não tem nenhum modo configurado ainda, Vitor!"

    linhas = []
    for modo in modos.values():
        acoes_desc = []
        for a in modo.get("acoes", []):
            acao = a.get("acao", "")
            alvo = a.get("alvo", "")
            if acao == "abrir_app":
                acoes_desc.append(f"abre {alvo}")
            elif acao == "fechar_app":
                acoes_desc.append(f"fecha {alvo}")
            elif acao == "abrir_site":
                acoes_desc.append(f"abre {alvo}")
            elif acao == "abrir_jogo":
                acoes_desc.append(f"abre o jogo {alvo}")
        linhas.append(f"• {modo['nome']}: {', '.join(acoes_desc) or 'sem ações'}")

    return "Seus modos:\n" + "\n".join(linhas)


def _criar_modo_fn(nome: str, gatilhos: list, acoes: list) -> str:
    """Cria ou sobrescreve um modo."""
    if not nome or not acoes:
        return "Precisa de um nome e pelo menos uma ação pra criar o modo, Vitor!"

    modos = _carregar_modos()
    chave = _normalizar(nome).replace(" ", "_")

    # Se já existia, avisa que vai sobrescrever
    era_novo = chave not in modos
    modos[chave] = {
        "nome": nome,
        "gatilhos": gatilhos or [_normalizar(nome)],
        "acoes": acoes,
    }
    _salvar_modos(modos)

    verbo = "Criei" if era_novo else "Atualizei"
    return f"{verbo} o modo '{nome}' com {len(acoes)} ação(ões)!"


def _deletar_modo_fn(nome: str) -> str:
    resultado = _encontrar_modo(nome)
    if not resultado:
        return f"Não achei nenhum modo chamado '{nome}', Vitor!"

    chave, modo = resultado
    modos = _carregar_modos()
    del modos[chave]
    _salvar_modos(modos)
    return f"Deletei o modo '{modo['nome']}'!"


def _extrair_nome_modo(mensagem: str) -> str:
    """
    Extrai o nome do modo de frases como:
    'ativa o modo gameplay', 'liga modo programação', 'deleta o modo estudos'
    """
    # Remove os prefixos de comando pra sobrar só o nome
    texto = _normalizar(mensagem)
    prefixos = [
        "ativa o modo", "ativa modo", "ativar o modo", "ativar modo",
        "liga o modo", "liga modo", "iniciar modo", "iniciar o modo",
        "deleta o modo", "deleta modo", "deletar o modo", "deletar modo",
        "apaga o modo", "apaga modo", "remove o modo", "remove modo",
    ]
    for prefixo in sorted(prefixos, key=len, reverse=True):  # mais longo primeiro
        if texto.startswith(prefixo):
            return texto[len(prefixo):].strip()

    # Fallback: pega o que vem depois de "modo"
    match = re.search(r'\bmodo\s+(.+)', texto)
    return match.group(1).strip() if match else ""


def inicializar() -> None:
    """Chame isso uma vez no main.py pra construir o índice de apps em background."""
    _carregar_cache()
    _llm_cache_get("")
    threading.Thread(target=construir_indice_apps, daemon=True).start()
    threading.Thread(target=construir_indice_registro, daemon=True).start()
    threading.Thread(target=_monitorar_janela_explorer, daemon=True).start()
    threading.Thread(target=_carregar_applist_steam, daemon=True).start()
    _carregar_speedruns()


def _buscar_arquivo_fuzzy(nome_arquivo: str, pasta_hint: str = "") -> Optional[Path]:
    """
    Busca um arquivo por nome com fuzzy matching.
    Se pasta_hint for fornecido, prioriza aquela pasta.
    Também faz busca recursiva quando a pasta for específica.
    """
    nome_normalizado = _normalizar(nome_arquivo)
    if not nome_normalizado:
        return None

    # Resolve as pastas do hint
    pastas_do_hint = _resolver_pastas_do_hint(pasta_hint) if pasta_hint else []

    # Se temos pastas específicas, busca recursivamente nelas primeiro
    if pastas_do_hint:
        resultado = _buscar_arquivo_em_pasta(nome_arquivo, pastas_do_hint, recursivo=True)
        if resultado:
            return resultado

    # Fallback: busca nas pastas padrão do usuário (sem recursão pra ser rápido)
    pastas_padrao = [
        HOME / "Desktop",
        HOME / "Área de Trabalho",
        HOME / "Downloads",
        HOME / "Documents",
        HOME / "Documentos",
        HOME / "Pictures",
        HOME / "Imagens",
    ]

    resultado = _buscar_arquivo_em_pasta(nome_arquivo, pastas_padrao, recursivo=False)
    return resultado


def _deletar_arquivo(nome_arquivo: str, pasta_hint: str = "") -> str:
    caminho = _buscar_arquivo_fuzzy(nome_arquivo, pasta_hint)
    if not caminho:
        caminho = _resolver_caminho(nome_arquivo)
    if not caminho:
        return f"Não achei '{nome_arquivo}' pra deletar não, Vitor!"

    sucesso = _enviar_para_lixeira(caminho)
    if sucesso:
        _registrar_undo({"tipo": "deletar_lixeira", "nome": caminho.name})
        return f"Mandei {caminho.name} pra Lixeira!"
    return f"Não consegui deletar '{caminho.name}'."
    
def _deletar_selecionados() -> str:
    arquivos = _obter_arquivos_selecionados()
    if not arquivos:
        return "Não achei nenhum arquivo selecionado no Explorer, Vitor! Seleciona os arquivos antes de dar o comando."

    sucessos, erros = [], []
    for arquivo in arquivos:
        if _enviar_para_lixeira(arquivo):
            sucessos.append(arquivo.name)
        else:
            erros.append(arquivo.name)

    if sucessos:
        _registrar_undo({"tipo": "deletar_lixeira", "nomes": sucessos})

    resp = f"Mandei {len(sucessos)} arquivo(s) pra Lixeira!"
    if erros:
        resp += f" Não consegui deletar: {', '.join(erros)}"
    return resp


def _copiar_arquivo_fn(origem_texto: str, pasta_origem: str, destino_texto: str) -> str:
    """
    Copia um arquivo/pasta para o destino. O original permanece intacto.
    Usa toda a infraestrutura de busca fuzzy + PASTA_MAP pra resolver os caminhos.
    """
    caminho_origem: Optional[Path] = None

    # Tenta resolver a origem com pasta_hint se foi fornecida
    if pasta_origem:
        pastas = _resolver_pastas_do_hint(pasta_origem)
        if pastas:
            caminho_origem = _buscar_arquivo_em_pasta(origem_texto, pastas, recursivo=True)

    # Fallbacks progressivos
    if not caminho_origem:
        caminho_origem = _buscar_arquivo_fuzzy(origem_texto, pasta_origem)
    if not caminho_origem:
        caminho_origem = _resolver_caminho(origem_texto)
    if not caminho_origem:
        return f"Não achei o arquivo '{origem_texto}' pra copiar, Vitor!"

    # Resolve o destino — tenta pelo PASTA_MAP primeiro, depois _resolver_destino
    destino: Optional[Path] = None
    pastas_destino = _resolver_pastas_do_hint(destino_texto)
    if pastas_destino:
        destino = pastas_destino[0]
    if not destino or not destino.exists():
        destino = _resolver_destino(destino_texto, origem=caminho_origem)

    try:
        if destino.exists() and destino.is_dir():
            destino_final = destino / caminho_origem.name
        else:
            destino_final = destino
            destino_final.parent.mkdir(parents=True, exist_ok=True)

        # Grande ou conflito → SHFileOperation com dialogo
        if _tamanho_bytes(caminho_origem) >= _LIMITE_DIALOGO_BYTES or destino_final.exists():
            _shell_fileop(_FO_COPY, caminho_origem, destino_final.parent)
            return None  # operação em andamento

        if caminho_origem.is_dir():
            shutil.copytree(str(caminho_origem), str(destino_final))
        else:
            shutil.copy2(str(caminho_origem), str(destino_final))

        _registrar_undo({"tipo": "copiar", "caminhos_copiados": [str(destino_final)]})
        return f"Copiei {caminho_origem.name} para {destino_final.parent.name}!"
    except Exception as erro:
        return f"Não consegui copiar. Erro: {erro}"


def _renomear_arquivo_fn(alvo: str, pasta_hint: str, novo_nome: str) -> str:
    """
    Renomeia um arquivo ou pasta.
    Se o novo nome não tiver extensão e o original tiver, preserva a extensão.
    """
    if not novo_nome or not novo_nome.strip():
        return "Precisa me dizer o novo nome, Vitor!"

    caminho: Optional[Path] = None

    # Busca com pasta_hint se foi fornecida
    if pasta_hint:
        pastas = _resolver_pastas_do_hint(pasta_hint)
        if pastas:
            caminho = _buscar_arquivo_em_pasta(alvo, pastas, recursivo=True)

    # Fallbacks
    if not caminho:
        caminho = _buscar_arquivo_fuzzy(alvo, pasta_hint)
    if not caminho:
        caminho = _resolver_caminho(alvo)
    if not caminho:
        return f"Não achei '{alvo}' pra renomear, Vitor!"

    novo_nome = novo_nome.strip()

    # Preserva extensão original se o novo nome não trouxer uma
    if caminho.is_file() and not Path(novo_nome).suffix and caminho.suffix:
        novo_nome = novo_nome + caminho.suffix

    destino = caminho.parent / novo_nome

    if destino.exists():
        return f"Já existe um arquivo chamado '{novo_nome}' nessa pasta. Quer outro nome?"

    try:
        caminho.rename(destino)
        _registrar_undo({
            "tipo": "renomear",
            "nome_novo": str(destino),
            "nome_antigo": str(caminho)
        })
        return f"Renomeei '{caminho.name}' para '{novo_nome}'!"
    except Exception as erro:
        return f"Não consegui renomear. Erro: {erro}"

def _mover_selecionados(destino_texto: str, drive_hint: str = "", subpasta: str = "") -> str:
    arquivos = _obter_arquivos_selecionados()
    if not arquivos:
        return "Não achei nenhum arquivo selecionado no Explorer, Vitor!"
    
    if _callback_status:
        _callback_status("transferindo")

    destino: Optional[Path] = None
    if drive_hint:
        drive = _resolver_drive(drive_hint)
        if drive:
            if destino_texto:
                pasta_no_drive = _buscar_pasta_em_drive(destino_texto, drive)
                destino = pasta_no_drive if pasta_no_drive else drive
            else:
                destino = drive

    if not destino:
        pastas = _resolver_pastas_do_hint(destino_texto)
        destino = pastas[0] if pastas else None

    if not destino:
        destino = _resolver_destino(destino_texto)

    if not destino:
        return f"Não entendi o destino '{destino_texto}', Vitor!"

    # ── NOVO: navega pra subpasta se foi especificada ──
    if subpasta:
        sub = _resolver_subpasta(destino, subpasta)
        if sub:
            destino = sub
        else:
            destino = destino / subpasta
            print(f"[DEBUG automacao] Subpasta não encontrada, criando: {destino}")

    sucessos, erros, itens_undo = [], [], []
    for arquivo in arquivos:
        try:
            destino_final = destino / arquivo.name
            destino.mkdir(parents=True, exist_ok=True)

            # Grande ou conflito → SHFileOperation
            if _tamanho_bytes(arquivo) >= _LIMITE_DIALOGO_BYTES or destino_final.exists():
                sucesso_shell = _shell_fileop(_FO_MOVE, arquivo, destino)
                if sucesso_shell:
                    itens_undo.append({
                        "origem_original": str(arquivo),
                        "destino_final":   str(destino_final),
                    })
                sucessos.append(arquivo.name)
                continue

            shutil.move(str(arquivo), str(destino_final))
            itens_undo.append({"origem_original": str(arquivo), "destino_final": str(destino_final)})
            sucessos.append(arquivo.name)
        except Exception as e:
            erros.append(f"{arquivo.name} ({e})")

    if itens_undo:
        _registrar_undo({"tipo": "mover_varios", "itens": itens_undo})

    resp = f"Movi {len(sucessos)} arquivo(s) para {destino.name}!"
    if erros:
        resp += f" Mas não consegui mover: {', '.join(erros)}"
    return resp

def _resolver_destino_criar(pasta_hint: str, drive_hint: str = "") -> Optional[Path]:
    """
    Resolve onde criar a pasta/arquivo.
    Combina drive + pasta_hint pra achar o local certo.
    """
    # Com drive especificado
    if drive_hint:
        drive = _resolver_drive(drive_hint)
        if not drive:
            return None

        if pasta_hint:
            # Tenta pasta padrão dentro do drive (ex: "downloads da unidade D")
            pastas = _resolver_pastas_do_hint(pasta_hint)
            for p in pastas:
                if p.drive.upper() == drive.drive.upper() and p.exists():
                    return p

            # Tenta como pasta de app/jogo dentro do drive específico
            pasta = _buscar_pasta_em_drive(pasta_hint, drive)
            if pasta:
                return pasta

            # Fallback: raiz do drive
            return drive

        return drive

    # Sem drive — resolve pasta_hint normalmente
    if pasta_hint:
        pastas = _resolver_pastas_do_hint(pasta_hint)
        if pastas:
            return pastas[0]

        # Tenta como pasta de app/jogo instalado
        pasta = _buscar_pasta_de_app(pasta_hint)
        if pasta:
            return pasta

    return None

def _criar_pasta_fn(nome: str, pasta_hint: str, drive_hint: str = "") -> str:
    """Cria uma nova pasta no local indicado."""
    if not nome or not nome.strip():
        return "Me diz o nome da pasta que quer criar, Vitor!"

    destino_base = _resolver_destino_criar(pasta_hint, drive_hint)
    if not destino_base:
        return f"Não achei o local '{pasta_hint}' pra criar a pasta, Vitor!"

    nova_pasta = destino_base / nome.strip()

    if nova_pasta.exists():
        return f"Já existe uma pasta chamada '{nome}' lá, Vitor!"

    try:
        nova_pasta.mkdir(parents=True, exist_ok=False)
        _registrar_undo({"tipo": "criar", "caminho": str(nova_pasta)})
        return f"Pasta '{nome}' criada em {destino_base.name}!"
    except Exception as e:
        return f"Não consegui criar a pasta. Erro: {e}"


def _criar_arquivo_txt_fn(nome: str, pasta_hint: str, drive_hint: str = "") -> str:
    """Cria um arquivo .txt vazio no local indicado."""
    if not nome or not nome.strip():
        return "Me diz o nome do arquivo que quer criar, Vitor!"

    destino_base = _resolver_destino_criar(pasta_hint, drive_hint)
    if not destino_base:
        return f"Não achei o local '{pasta_hint}' pra criar o arquivo, Vitor!"

    # Garante extensão .txt
    nome_limpo = nome.strip()
    if not nome_limpo.lower().endswith(".txt"):
        nome_limpo += ".txt"

    novo_arquivo = destino_base / nome_limpo

    if novo_arquivo.exists():
        return f"Já existe um arquivo chamado '{nome_limpo}' lá, Vitor!"

    try:
        novo_arquivo.write_text("", encoding="utf-8")
        _registrar_undo({"tipo": "criar", "caminho": str(novo_arquivo)})
        return f"Arquivo '{nome_limpo}' criado em {destino_base.name}!"
    except Exception as e:
        return f"Não consegui criar o arquivo. Erro: {e}"
    
def _copiar_arquivos_da_pasta_fn(
    pasta_origem: str,
    drive_origem: str = "",
    destino: str = "",
    drive_destino: str = "",
    arquivos: list = None,
    excluir: list = None,
    pasta_contexto: str = "",   # ← NOVO: pasta-pai onde procurar (ex: "downloads")
) -> str:
    caminho_origem: Optional[Path] = None

    # Se tem pasta-pai (ex: "downloads"), procura a pasta_origem DENTRO dela primeiro
    if pasta_contexto:
        pastas_pai = _resolver_pastas_do_hint(pasta_contexto)
        # Se também tem drive, filtra só as que estão nele
        if drive_origem:
            drive_path = _resolver_drive(drive_origem)
            if drive_path:
                pastas_pai = [p for p in pastas_pai if p.drive.upper() == drive_path.drive.upper()]
        for pai in pastas_pai:
            sub = _resolver_subpasta(pai, pasta_origem)
            if sub:
                caminho_origem = sub
                break

    # Sem pasta-pai ou não achou lá: comportamento original
    if not caminho_origem and drive_origem:
        drive = _resolver_drive(drive_origem)
        if drive:
            caminho_origem = _buscar_pasta_em_drive(pasta_origem, drive)

    if not caminho_origem:
        pastas = _resolver_pastas_do_hint(pasta_origem)
        if pastas:
            caminho_origem = pastas[0]

    if not caminho_origem:
        caminho_origem = _buscar_pasta_de_app(pasta_origem)

    if not caminho_origem or not caminho_origem.exists():
        return f"Não achei a pasta '{pasta_origem}', Vitor!"

    # ── Resolve o destino ──
    caminho_destino: Optional[Path] = None

    if drive_destino:
        drive_dest = _resolver_drive(drive_destino)
        if drive_dest:
            caminho_destino = (
                _buscar_pasta_em_drive(destino, drive_dest) if destino else drive_dest
            )

    if not caminho_destino:
        pastas_dest = _resolver_pastas_do_hint(destino)
        caminho_destino = pastas_dest[0] if pastas_dest else None

    if not caminho_destino:
        return f"Não entendi o destino '{destino}', Vitor!"

    # ── Lista os itens da pasta de origem ──
    try:
        todos = list(caminho_origem.iterdir())
    except (OSError, PermissionError) as e:
        return f"Não consegui acessar '{caminho_origem.name}': {e}"

    excluir_norm  = [_normalizar(e) for e in (excluir  or [])]
    arquivos_norm = [_normalizar(a) for a in (arquivos or [])]

    def _deve_incluir(item: Path) -> bool:
        nome_norm = _normalizar(item.name)
        # Lista específica de arquivos → só esses
        if arquivos_norm:
            return any(
                a in nome_norm or nome_norm in a or _similaridade(a, nome_norm) > 0.7
                for a in arquivos_norm
            )
        # Sem lista específica → copia tudo, pulando os excluídos
        if excluir_norm:
            return not any(
                e in nome_norm or nome_norm in e or _similaridade(e, nome_norm) > 0.7
                for e in excluir_norm
            )
        return True  # sem filtro algum: copia tudo

    itens = [i for i in todos if _deve_incluir(i)]

    if not itens:
        return f"Nenhum item pra copiar em '{caminho_origem.name}', Vitor!"

    caminho_destino.mkdir(parents=True, exist_ok=True)
    sucessos, erros = [], []
    caminhos_copiados: list[str] = []   # ← rastreia pra undo

    for item in itens:
        try:
            destino_final = caminho_destino / item.name
            if _tamanho_bytes(item) >= _LIMITE_DIALOGO_BYTES or destino_final.exists():
                sucesso_shell = _shell_fileop(_FO_COPY, item, caminho_destino)
                if sucesso_shell:
                    caminhos_copiados.append(str(destino_final))
                sucessos.append(item.name)
                continue
            if item.is_dir():
                shutil.copytree(str(item), str(destino_final))
            else:
                shutil.copy2(str(item), str(destino_final))
            sucessos.append(item.name)
            caminhos_copiados.append(str(destino_final))   # ← registra destino
        except Exception as e:
            erros.append(f"{item.name} ({e})")

    if caminhos_copiados:
        _registrar_undo({"tipo": "copiar", "caminhos_copiados": caminhos_copiados})

    resp = f"Copiei {len(sucessos)} item(ns) de '{caminho_origem.name}' pra '{caminho_destino.name}'!"
    if erros:
        resp += f" Problemas com: {', '.join(erros)}"
    return resp


def _deletar_arquivos_da_pasta_fn(
    pasta: str,
    drive: str = "",
    arquivos: list = None,  # lista específica pra deletar. Vazia = deleta tudo
    excluir: list = None,   # lista de arquivos a PRESERVAR (não deletar)
) -> str:
    """
    Deleta arquivos de dentro de uma pasta.
    - arquivos: se preenchido, deleta só esses
    - excluir:  se preenchido, deleta tudo EXCETO esses (o "menos/exceto" do usuário)
    """
    # ── Resolve a pasta ──
    caminho_pasta: Optional[Path] = None

    if drive:
        drive_path = _resolver_drive(drive)
        if drive_path:
            caminho_pasta = _buscar_pasta_em_drive(pasta, drive_path)

    if not caminho_pasta:
        pastas = _resolver_pastas_do_hint(pasta)
        if pastas:
            caminho_pasta = pastas[0]

    if not caminho_pasta:
        caminho_pasta = _buscar_pasta_de_app(pasta)

    if not caminho_pasta or not caminho_pasta.exists():
        return f"Não achei a pasta '{pasta}', Vitor!"

    try:
        todos = list(caminho_pasta.iterdir())
    except (OSError, PermissionError) as e:
        return f"Não consegui acessar '{pasta}': {e}"

    excluir_norm  = [_normalizar(e) for e in (excluir  or [])]
    arquivos_norm = [_normalizar(a) for a in (arquivos or [])]

    def _deve_deletar(item: Path) -> bool:
        nome_norm = _normalizar(item.name)
        # Lista específica pra deletar → só esses
        if arquivos_norm:
            return any(
                a in nome_norm or nome_norm in a or _similaridade(a, nome_norm) > 0.7
                for a in arquivos_norm
            )
        # Sem lista específica → deleta tudo, preservando os excluídos
        if excluir_norm:
            return not any(
                e in nome_norm or nome_norm in e or _similaridade(e, nome_norm) > 0.7
                for e in excluir_norm
            )
        return True  # sem filtro: deleta tudo

    itens = [i for i in todos if _deve_deletar(i)]

    if not itens:
        return f"Nenhum item pra deletar em '{caminho_pasta.name}', Vitor!"

    sucessos, erros = [], []
    for item in itens:
        if _enviar_para_lixeira(item):
            sucessos.append(item.name)
        else:
            erros.append(item.name)

    if sucessos:
        _registrar_undo({"tipo": "deletar_lixeira", "nomes": sucessos})

    resp = f"Mandei {len(sucessos)} item(ns) de '{caminho_pasta.name}' pra lixeira!"
    if erros:
        resp += f" Não consegui deletar: {', '.join(erros)}"
    return resp

# ─────────────────────────────────────────────────────────────────
# MÚSICA — YouTube + teclas de mídia do Windows
# ─────────────────────────────────────────────────────────────────

def _buscar_video_youtube(query: str) -> Optional[str]:
    """
    Busca no YouTube e retorna a URL direta do primeiro vídeo encontrado.
    Não precisa de API key — usa scraping simples da página de resultados.
    """
    import urllib.request
    import urllib.parse

    query_encoded = urllib.parse.quote(query)
    url = f"https://www.youtube.com/results?search_query={query_encoded}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8")

        # Pega o ID do primeiro vídeo que aparecer nos resultados
        match = re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
        if match:
            video_id = match.group(1)
            print(f"[DEBUG musica] Vídeo encontrado: {video_id} para '{query}'")
            return f"https://www.youtube.com/watch?v={video_id}"

    except Exception as e:
        print(f"[DEBUG musica] Erro ao buscar no YouTube: {e}")

    return None


def _pressionar_media_key(vk_code: int) -> None:
    """
    Simula o pressionamento de uma tecla de mídia do Windows.
    Funciona pra qualquer player — Spotify, YouTube no browser, VLC, etc.
    """
    if os.name != "nt":
        return
    import ctypes
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY, 0)
    ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)


def _controlar_musica(controle: str) -> str:
    """
    Executa um controle de mídia pelo nome.
    Usa as teclas de mídia do Windows — funcionam globalmente.
    """
    # Códigos das teclas de mídia do Windows
    VK_MEDIA_PLAY_PAUSE = 0xB3
    VK_MEDIA_NEXT_TRACK = 0xB0
    VK_MEDIA_PREV_TRACK = 0xB1
    VK_VOLUME_UP        = 0xAF
    VK_VOLUME_DOWN      = 0xAE
    VK_VOLUME_MUTE      = 0xAD

    controle_norm = _normalizar(controle)

    if any(p in controle_norm for p in ("proxima", "próxima", "skip", "next")):
        _pressionar_media_key(VK_MEDIA_NEXT_TRACK)
        return "proxima"

    if any(p in controle_norm for p in ("anterior", "voltar", "prev", "previous")):
        _pressionar_media_key(VK_MEDIA_PREV_TRACK)
        return "anterior"

    if any(p in controle_norm for p in ("pausa", "pause", "pausar", "pausando")):
        _pressionar_media_key(VK_MEDIA_PLAY_PAUSE)
        return "pausar"

    if any(p in controle_norm for p in ("retoma", "retomar", "continua", "play")):
        _pressionar_media_key(VK_MEDIA_PLAY_PAUSE)
        return "retomar"

    if any(p in controle_norm for p in ("aumenta", "sobe", "mais volume", "volume up")):
        # Aperta várias vezes pra subir bastante
        for _ in range(5):
            _pressionar_media_key(VK_VOLUME_UP)
        return "volume_up"

    if any(p in controle_norm for p in ("diminui", "baixa", "menos volume", "volume down")):
        for _ in range(5):
            _pressionar_media_key(VK_VOLUME_DOWN)
        return "volume_down"

    if any(p in controle_norm for p in ("muta", "mutar", "silencia", "sem som", "mute")):
        _pressionar_media_key(VK_VOLUME_MUTE)
        return "mute"

    return "desconhecido"
    
def _executar_acao_por_dict(resultado: dict) -> Optional[str]:
    """
    Executa uma única ação a partir de um dicionário já interpretado pelo LLM.
    Retorna a mensagem de resultado ou None.
    """
    acao = resultado.get("acao", "nenhuma")
    if acao == "nenhuma":
        return None

    resposta_emily = resultado.get("resposta", "Feito!")

    if acao == "abrir_app":
        alvo = resultado.get("alvo", "")
        if not alvo:
            return "Me diz o que você quer abrir!"
        if _callback_status:
           _callback_status("abrindo_app")
        sucesso = _abrir_app(alvo)
        return resposta_emily if sucesso else f"Não encontrei o {alvo} aqui não, Vitor!"

    if acao == "abrir_jogo":
        alvo = resultado.get("alvo", "")
        if not alvo:
            return "Me diz qual jogo você quer abrir!"
        caminho_jogo = _cache_get(f"jogo:{alvo}") or _buscar_jogo_completo(alvo)
        if caminho_jogo:
            _cache_set(f"jogo:{alvo}", caminho_jogo)
            _executar_start(str(caminho_jogo))
            return resposta_emily
        if _abrir_app(alvo):
            return resposta_emily
        return f"Não achei o jogo '{alvo}', Vitor!"

    if acao == "fechar_app":
        alvo = resultado.get("alvo", "")
        if not alvo:
            return "Me diz o que você quer fechar!"
        sucesso = _fechar_app(alvo)
        return resposta_emily if sucesso else f"Não consegui fechar o {alvo}!"

    if acao == "abrir_pasta":
        alvo       = resultado.get("alvo", "")
        drive_hint = resultado.get("drive", "")
        pasta_hint = resultado.get("pasta", "")   # ← NOVO: pasta-pai onde procurar
        if not alvo:
            return "Me diz qual pasta você quer abrir!"

        # ── Caso: "pasta X em Y" — procura X dentro de Y ──
        if pasta_hint:
            pastas_pai = _resolver_pastas_do_hint(pasta_hint)
            if drive_hint:
                drive_path = _resolver_drive(drive_hint)
                if drive_path:
                    pastas_pai = [p for p in pastas_pai if p.drive.upper() == drive_path.drive.upper()]
            for pai in pastas_pai:
                sub = _resolver_subpasta(pai, alvo)
                if sub:
                    _executar_start(str(sub))
                    return resposta_emily
            return f"Não achei a pasta '{alvo}' dentro de '{pasta_hint}', Vitor!"

        # ── Caso: drive sem pasta-pai — busca no drive inteiro ──
        if drive_hint:
            drive_path = _resolver_drive(drive_hint)
            if drive_path and drive_path.exists():
                # Tenta pastas padrão (downloads, documentos...) no drive primeiro
                pastas_pad = _resolver_pastas_do_hint(alvo)
                for p in pastas_pad:
                    if p.drive.upper() == drive_path.drive.upper() and p.exists():
                        _executar_start(str(p))
                        return resposta_emily
                pasta = _buscar_pasta_em_drive(alvo, drive_path)
                if pasta:
                    _executar_start(str(pasta))
                    return resposta_emily
                return f"Não achei a pasta '{alvo}' nessa unidade não, Vitor!"
            return f"Não reconheci a unidade '{drive_hint}', Vitor!"

        # ── Caso padrão ──
        pastas = _resolver_pastas_do_hint(alvo)
        if pastas:
            _executar_start(str(pastas[0]))
            return resposta_emily
        caminho_direto = Path(os.path.expandvars(os.path.expanduser(alvo)))
        if caminho_direto.exists() and caminho_direto.is_dir():
            _executar_start(str(caminho_direto))
            return resposta_emily
        pasta_app = _buscar_pasta_de_app(alvo)
        if pasta_app:
            _executar_start(str(pasta_app))
            return resposta_emily
        return f"Não achei a pasta '{alvo}', Vitor!"

    if acao == "abrir_site":
        url = resultado.get("alvo", "")
        if url:
            webbrowser.open(url)
            return resposta_emily
        return "Não entendi qual site você quer abrir!"

    if acao == "abrir_arquivo":
        alvo = resultado.get("alvo", "")
        pasta_hint = resultado.get("pasta", "")
        if not alvo:
            return "Me diz o que você quer abrir!"
        caminho = (_resolver_caminho(alvo) or _buscar_arquivo_fuzzy(alvo, pasta_hint)
                   or _buscar_no_indice(alvo) or _buscar_jogo_completo(alvo))
        if not caminho:
            return f"Não achei '{alvo}' por aqui não, Vitor!"
        _executar_start(str(caminho))
        return resposta_emily

    if acao == "abrir_exe":
        alvo = resultado.get("alvo", "")
        pasta_hint = resultado.get("pasta", "")
        if not alvo:
            return "Me diz qual executável você quer abrir!"
        pastas = _resolver_pastas_do_hint(pasta_hint) if pasta_hint else []
        caminho = None
        if pastas:
            caminho = _buscar_arquivo_em_pasta(alvo, pastas, recursivo=True)
        if not caminho:
            caminho = _buscar_arquivo_fuzzy(alvo, pasta_hint) or _resolver_caminho(alvo)
        if not caminho:
            return f"Não achei '{alvo}' não, Vitor!"
        _executar_start(str(caminho))
        return resposta_emily

    if acao == "mover_arquivo":
        origem_texto  = resultado.get("origem", "")
        pasta_origem  = resultado.get("pasta_origem", "")
        destino_texto = resultado.get("destino", "")
        if not origem_texto or not destino_texto:
            return "Precisa me dizer o arquivo e pra onde mover, Vitor!"
        caminho_origem = None
        if pasta_origem:
            pastas = _resolver_pastas_do_hint(pasta_origem)
            if pastas:
                caminho_origem = _buscar_arquivo_em_pasta(origem_texto, pastas, recursivo=True)
        if not caminho_origem:
            caminho_origem = _buscar_arquivo_fuzzy(origem_texto, pasta_origem) or _resolver_caminho(origem_texto)
        if not caminho_origem:
            return f"Não achei o arquivo '{origem_texto}', Vitor!"
        destino = None
        pastas_destino = _resolver_pastas_do_hint(destino_texto)
        if pastas_destino:
            destino = pastas_destino[0]
        if not destino or not destino.exists():
            destino = _resolver_destino(destino_texto, origem=caminho_origem)
        try:
            destino_final = destino / caminho_origem.name if (destino.exists() and destino.is_dir()) else destino
            if not destino.exists() and not destino.suffix:
                destino.mkdir(parents=True, exist_ok=True)
                destino_final = destino / caminho_origem.name
            destino_final.parent.mkdir(parents=True, exist_ok=True)
            if _tamanho_bytes(caminho_origem) >= _LIMITE_DIALOGO_BYTES:
                _orig, _dest = str(caminho_origem), str(destino_final)
                _fileop_async(
                    _FO_MOVE, caminho_origem, destino_final.parent,
                    callback=lambda: _registrar_undo({
                        "tipo": "mover",
                        "origem_original": _orig,
                        "destino_final":   _dest,
                    })
                )
                return resposta_emily
            shutil.move(str(caminho_origem), str(destino_final))
            _registrar_undo({"tipo": "mover", "origem_original": str(caminho_origem), "destino_final": str(destino_final)})
            return resposta_emily
        except Exception as e:
            return f"Não consegui mover. Erro: {e}"

    if acao == "copiar_arquivo":
        origem_texto  = resultado.get("origem", "")
        pasta_origem  = resultado.get("pasta_origem", "")
        destino_texto = resultado.get("destino", "")
        if not origem_texto or not destino_texto:
            return "Precisa me dizer o arquivo e pra onde copiar, Vitor!"
        r = _copiar_arquivo_fn(origem_texto, pasta_origem, destino_texto)
        return resposta_emily if "Não achei" not in r and "Não consegui" not in r else r

    if acao == "renomear_arquivo":
        alvo      = resultado.get("alvo", "")
        pasta_hint = resultado.get("pasta", "")
        novo_nome = resultado.get("novo_nome", "")
        if not alvo:
            return "Me diz qual arquivo renomear!"
        if not novo_nome:
            return "Me diz o novo nome, Vitor!"
        r = _renomear_arquivo_fn(alvo, pasta_hint, novo_nome)
        return r if any(f in r for f in ("Não achei", "Não consegui", "Já existe")) else resposta_emily

    if acao == "deletar_arquivo":
        alvo      = resultado.get("alvo", "")
        pasta_hint = resultado.get("pasta", "")
        if not alvo:
            return "Me diz o que deletar!"
        r = _deletar_arquivo(alvo, pasta_hint)
        return r if any(f in r for f in ("Não achei", "Não consegui")) else resposta_emily

    if acao == "mover_pasta":
        alvo               = resultado.get("alvo", "")
        drive_origem_hint  = resultado.get("drive_origem", "")
        drive_destino_hint = resultado.get("drive_destino", "")
        pasta_destino_hint = resultado.get("pasta_destino", "")

        if not alvo:
            return "Me diz qual pasta mover, Vitor!"

        caminho_pasta: Optional[Path] = None
        if drive_origem_hint:
            drive_orig = _resolver_drive(drive_origem_hint)
            if drive_orig:
                pastas_pad = _resolver_pastas_do_hint(alvo)
                for p in pastas_pad:
                    if p.drive.upper() == drive_orig.drive.upper() and p.exists():
                        caminho_pasta = p
                        break
                if not caminho_pasta:
                    caminho_pasta = _buscar_pasta_em_drive(alvo, drive_orig)
        if not caminho_pasta:
            pastas_pad = _resolver_pastas_do_hint(alvo)
            if pastas_pad:
                caminho_pasta = pastas_pad[0]
        if not caminho_pasta:
            caminho_pasta = _buscar_pasta_de_app(alvo)
        if not caminho_pasta or not caminho_pasta.exists():
            return f"Não achei a pasta '{alvo}', Vitor!"

        destino: Optional[Path] = None
        if drive_destino_hint:
            drive_dest = _resolver_drive(drive_destino_hint)
            if drive_dest:
                destino = _buscar_pasta_em_drive(pasta_destino_hint, drive_dest) if pasta_destino_hint else drive_dest
        if not destino and pasta_destino_hint:
            pastas = _resolver_pastas_do_hint(pasta_destino_hint)
            destino = pastas[0] if pastas else None
        if not destino:
            return "Não entendi pra onde mover a pasta, Vitor!"

        destino_final = destino / caminho_pasta.name
        if destino_final.exists():
            return f"Já existe '{caminho_pasta.name}' no destino!"

        if _tamanho_bytes(caminho_pasta) >= _LIMITE_DIALOGO_BYTES:
            _orig, _dest = str(caminho_pasta), str(destino_final)
            _fileop_async(
                _FO_MOVE, caminho_pasta, destino,
                callback=lambda: _registrar_undo({
                    "tipo": "mover",
                    "origem_original": _orig,
                    "destino_final":   _dest,
                })
            )
            return resposta_emily
        try:
            shutil.move(str(caminho_pasta), str(destino_final))
            _registrar_undo({"tipo": "mover", "origem_original": str(caminho_pasta), "destino_final": str(destino_final)})
            return resposta_emily
        except Exception as e:
            return f"Não consegui mover. Erro: {e}"
        
    if acao == "copiar_pasta":
        alvo               = resultado.get("alvo", "")
        drive_origem_hint  = resultado.get("drive_origem", "")
        drive_destino_hint = resultado.get("drive_destino", "")
        pasta_destino_hint = resultado.get("pasta_destino", "")

        if not alvo:
            return "Me diz qual pasta copiar, Vitor!"

        # Resolve origem (igual ao mover_pasta)
        caminho_pasta: Optional[Path] = None
        if drive_origem_hint:
            drive_orig = _resolver_drive(drive_origem_hint)
            if drive_orig:
                pastas_pad = _resolver_pastas_do_hint(alvo)
                for p in pastas_pad:
                    if p.drive.upper() == drive_orig.drive.upper() and p.exists():
                        caminho_pasta = p
                        break
                if not caminho_pasta:
                    caminho_pasta = _buscar_pasta_em_drive(alvo, drive_orig)
        if not caminho_pasta:
            pastas_pad = _resolver_pastas_do_hint(alvo)
            if pastas_pad:
                caminho_pasta = pastas_pad[0]
        if not caminho_pasta:
            caminho_pasta = _buscar_pasta_de_app(alvo)
        if not caminho_pasta or not caminho_pasta.exists():
            return f"Não achei a pasta '{alvo}', Vitor!"

        # Resolve destino
        destino: Optional[Path] = None
        if drive_destino_hint:
            drive_dest = _resolver_drive(drive_destino_hint)
            if drive_dest:
                destino = _buscar_pasta_em_drive(pasta_destino_hint, drive_dest) if pasta_destino_hint else drive_dest
        if not destino and pasta_destino_hint:
            pastas = _resolver_pastas_do_hint(pasta_destino_hint)
            destino = pastas[0] if pastas else None
        if not destino:
            return "Não entendi pra onde copiar a pasta, Vitor!"

        destino_final = destino / caminho_pasta.name
        if destino_final.exists():
            return f"Já existe '{caminho_pasta.name}' no destino!"

        # Pasta grande → janela nativa do Windows
        if _tamanho_bytes(caminho_pasta) >= _LIMITE_DIALOGO_BYTES:
            _dest_final = str(destino_final)
            _fileop_async(
                _FO_COPY, caminho_pasta, destino,
                callback=lambda: _registrar_undo({
                    "tipo": "copiar",
                    "caminhos_copiados": [_dest_final],
                })
            )
            return resposta_emily
        try:
            shutil.copytree(str(caminho_pasta), str(destino_final))
            _registrar_undo({"tipo": "copiar", "caminhos_copiados": [str(destino_final)]})
            return resposta_emily
        except Exception as e:
            return f"Não consegui copiar. Erro: {e}"

    if acao == "criar_pasta":
        r = _criar_pasta_fn(resultado.get("nome",""), resultado.get("pasta",""), resultado.get("drive",""))
        return r if any(f in r for f in ("Não achei","Não consegui","Já existe","Me diz")) else resposta_emily

    if acao == "criar_arquivo_txt":
        r = _criar_arquivo_txt_fn(resultado.get("nome",""), resultado.get("pasta",""), resultado.get("drive",""))
        return r if any(f in r for f in ("Não achei","Não consegui","Já existe","Me diz")) else resposta_emily

    if acao == "mover_selecionados":
        destino_texto = resultado.get("destino", "")
        drive_hint    = resultado.get("drive", "")
        subpasta      = resultado.get("subpasta", "")   # ← novo
        if not destino_texto and not drive_hint:
            return "Me diz pra onde mover os selecionados, Vitor!"
        r = _mover_selecionados(destino_texto, drive_hint, subpasta)
        return resposta_emily if "Não achei" not in r and "Não entendi" not in r else r

    if acao == "copiar_selecionados":
        destino_texto = resultado.get("destino", "")
        drive_hint    = resultado.get("drive", "")
        subpasta      = resultado.get("subpasta", "")   # ← novo
        if not destino_texto and not drive_hint:
            return "Me diz pra onde copiar os selecionados, Vitor!"
        r = _copiar_selecionados(destino_texto, drive_hint, subpasta)
        return resposta_emily if "Não achei" not in r and "Não entendi" not in r else r

    if acao == "deletar_selecionados":
        r = _deletar_selecionados()
        return resposta_emily if "Não achei" not in r else r

    if acao == "renomear_selecionados":
        r = _renomear_selecionados(
            modo=resultado.get("modo","numerar"), valor=resultado.get("valor",""),
            base=resultado.get("base",""), de=resultado.get("de",""), para=resultado.get("para","")
        )
        return r if any(f in r for f in ("Não achei","Não consegui","Renomeei 0")) else resposta_emily
    
    if acao == "extrair_arquivo":
        nome    = resultado.get("alvo", "")
        pasta   = resultado.get("pasta", "")
        drive   = resultado.get("drive", "")
        destino = resultado.get("destino", "")
        modo    = resultado.get("modo", "pasta")  # ← novo campo
        if not nome:
            return "Me diz qual arquivo extrair, Vitor!"
        r = _extrair_arquivo_fn(nome, pasta, drive, destino, modo)
        return r if any(f in r for f in ("Não achei", "Não consegui", "Erro")) else resposta_emily
    
    if acao == "extrair_selecionados":
        destino = resultado.get("destino", "")
        modo    = resultado.get("modo", "pasta")
        r = _extrair_selecionados_fn(destino, modo)
        return r if any(f in r for f in ("Não achei", "Não consegui", "Erro", "Nenhum")) else resposta_emily
    
    if acao == "copiar_arquivos_da_pasta":
        r = _copiar_arquivos_da_pasta_fn(
            pasta_origem   = resultado.get("pasta_origem", ""),
            drive_origem   = resultado.get("drive_origem", ""),
            destino        = resultado.get("destino", ""),
            drive_destino  = resultado.get("drive_destino", ""),
            arquivos       = resultado.get("arquivos", []),
            excluir        = resultado.get("excluir", []),
            pasta_contexto = resultado.get("pasta_contexto", ""),
        )
        return r if any(f in r for f in ("Não achei", "Não entendi", "Não consegui", "Nenhum")) else resposta_emily

    if acao == "deletar_arquivos_da_pasta":
        r = _deletar_arquivos_da_pasta_fn(
            pasta    = resultado.get("pasta", ""),
            drive    = resultado.get("drive", ""),
            arquivos = resultado.get("arquivos", []),
            excluir  = resultado.get("excluir", []),
        )
        return r if any(f in r for f in ("Não achei", "Não consegui", "Nenhum")) else resposta_emily
    
    if acao == "criar_modo":
        nome    = resultado.get("nome", "")
        gatilhos = resultado.get("gatilhos", [])
        acoes   = resultado.get("acoes", [])
        r = _criar_modo_fn(nome, gatilhos, acoes)
        return r
    
    if acao == "instalar_jogo_steam":
        alvo       = resultado.get("alvo", "")
        drive_hint = resultado.get("drive", "")
        if not alvo:
            return "Me diz qual jogo instalar, Vitor!"
        r = _instalar_jogo_steam(alvo, drive_hint)
        return r

    if acao == "desinstalar_jogo_steam":
        alvo = resultado.get("alvo", "")
        if not alvo:
            return "Me diz qual jogo desinstalar, Vitor!"
        r = _desinstalar_jogo_steam(alvo)
        return r
    
    if acao == "tocar_musica":
        musica  = resultado.get("musica", "")
        artista = resultado.get("artista", "")

        if not musica:
            return "Me diz qual música você quer ouvir, Vitor!"

        # Monta a query de busca com artista se disponível
        query = f"{musica} {artista}".strip() if artista else musica

        print(f"[DEBUG musica] Buscando no YouTube: '{query}'")
        url_video = _buscar_video_youtube(query)

        if url_video:
            webbrowser.open(url_video)
            return resposta_emily
        else:
            # Fallback: abre a pesquisa normalmente se não achar o vídeo direto
            import urllib.parse
            webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}")
            return f"Abri a busca por '{musica}' no YouTube, Vitor!"

    if acao == "controle_musica":
        controle = resultado.get("controle", "")
        if not controle:
            return "Que controle de música você quer, Vitor?"

        tipo = _controlar_musica(controle)

        if tipo == "desconhecido":
            return f"Não entendi o controle '{controle}', Vitor!"

        return resposta_emily
    
    if acao == "fechar_aba":
        alvo = resultado.get("alvo", "")
        r = _fechar_aba_navegador(alvo)
        return r if any(f in r for f in ("Não consegui", "Não achei", "Não temos")) else resposta_emily
    
    if acao == "minimizar_app":
        alvo = resultado.get("alvo", "")
        if not alvo:
            return "Me diz qual aplicativo minimizar, Vitor!"
        r = _minimizar_app(alvo)
        return r if "Não achei" in r or "Não consegui" in r else resposta_emily
    
    if acao == "maximizar_app":
        alvo = resultado.get("alvo", "")
        if not alvo:
            return "Me diz qual aplicativo maximizar, Vitor!"
        r = _maximizar_app(alvo)
        return r if "Não achei" in r or "Não consegui" in r else resposta_emily
    
    return None

def _executar_sequencia(acoes: list, resposta_inicial: str, callback_falar=None) -> str:
    """
    Executa uma lista de ações em sequência, em silêncio.
    Só fala uma vez no final com um resumo do que foi feito.
    """
    total = len(acoes)
    sucessos = []
    erros = []

    print(f"[DEBUG sequencia] Iniciando sequência com {total} ação(ões)")

    for i, acao_dict in enumerate(acoes, 1):
        if "resposta" not in acao_dict:
            acao_dict["resposta"] = "Feito!"

        print(f"[DEBUG sequencia] Executando passo {i}/{total}: {acao_dict.get('acao')}")

        # Em _executar_sequencia, troca o bloco do resultado_passo por:
        try:
            resultado_passo = _executar_acao_por_dict(acao_dict)
            if resultado_passo is None:
                # Ação não reconhecida — avisa mas continua
                erros.append(f"Passo {i} não sei fazer: {acao_dict.get('acao', '?')}")
                print(f"[DEBUG sequencia] Passo {i} ignorado (ação desconhecida)")
            else:
                sucessos.append(resultado_passo)
                print(f"[DEBUG sequencia] Passo {i} concluído: {resultado_passo}")
        except Exception as e:
            erros.append(f"Passo {i} falhou: {e}")

    # Monta o resumo final
    if not erros:
        return f"Pronto, Vitor! Fiz tudo que encontrei na tela."
    elif sucessos:
        return (f"Fiz {len(sucessos)} coisa(s), mas {len(erros)} eu não soube fazer: "
                f"{' | '.join(erros)}")
    else:
        return f"Não consegui fazer nada do que estava na tela: {' | '.join(erros)}"
    

def _extrair_com_7zip_externo(arquivo: Path, destino: Path) -> bool:
    """
    Tenta extrair usando o 7-Zip instalado no sistema.
    Funciona pra .rar, .7z, .zip e vários outros formatos.
    """
    if os.name != "nt":
        return False

    # Procura o 7z.exe (CLI) nos mesmos lugares do 7zFM.exe
    candidatos_7z = [
        Path(os.environ.get("ProgramFiles", ""))    / "7-Zip" / "7z.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "7-Zip" / "7z.exe",
    ]
    exe_7z = next((p for p in candidatos_7z if p.exists()), None)

    if not exe_7z:
        print("[DEBUG automacao] 7-Zip não encontrado. Instala em https://7-zip.org")
        return False

    try:
        resultado = subprocess.run(
            [str(exe_7z), "x", str(arquivo), f"-o{destino}", "-y"],
            capture_output=True, text=True, timeout=300
        )
        sucesso = resultado.returncode == 0
        if not sucesso:
            print(f"[DEBUG automacao] 7-Zip erro: {resultado.stderr.strip()}")
        return sucesso
    except Exception as e:
        print(f"[DEBUG automacao] 7-Zip falhou: {e}")
        return False


def _extrair_arquivo_fn(
    nome_arquivo: str,
    pasta_hint: str = "",
    drive_hint: str = "",
    destino_hint: str = "",
    modo: str = "pasta",                    # "pasta" → cria subpasta | "conteudo" → extrai direto no destino
    caminho_direto: Optional[Path] = None,  # pula a busca se já tiver o caminho
) -> str:

    # ── Resolve o arquivo de origem ──
    caminho = caminho_direto  # se vier pronto, usa direto

    if not caminho:
        if drive_hint:
            drive = _resolver_drive(drive_hint)
            if drive:
                if pasta_hint:
                    pasta_drive = _buscar_pasta_em_drive(pasta_hint, drive)
                    if pasta_drive:
                        caminho = _buscar_arquivo_em_pasta(nome_arquivo, [pasta_drive], recursivo=True)
                if not caminho:
                    caminho = _buscar_arquivo_em_pasta(nome_arquivo, [drive], recursivo=False)

        if not caminho and pasta_hint:
            pastas = _resolver_pastas_do_hint(pasta_hint)
            if pastas:
                caminho = _buscar_arquivo_em_pasta(nome_arquivo, pastas, recursivo=True)

        if not caminho:
            caminho = _buscar_arquivo_fuzzy(nome_arquivo, pasta_hint)
        if not caminho:
            caminho = _resolver_caminho(nome_arquivo)
        if not caminho:
            return f"Não achei '{nome_arquivo}' pra extrair, Vitor!"

    # ── Resolve a base do destino ──
    if destino_hint:
        pastas_dest = _resolver_pastas_do_hint(destino_hint)
        base_destino = pastas_dest[0] if pastas_dest else _resolver_destino(destino_hint)
    else:
        base_destino = caminho.parent

    # ── Aplica o modo ──
    # "pasta"   → extrai pra dentro de uma subpasta com o nome do arquivo
    # "conteudo"→ extrai direto na pasta base, sem criar subpasta
    if modo == "conteudo":
        destino_final = base_destino
    else:
        destino_final = base_destino / caminho.stem
        # Evita sobrescrever pasta existente
        if destino_final.exists():
            contador = 1
            while destino_final.exists():
                destino_final = base_destino / f"{caminho.stem}_{contador}"
                contador += 1

    destino_final.mkdir(parents=True, exist_ok=True)

    sufixo  = caminho.suffix.lower()
    sufixos = "".join(caminho.suffixes).lower()

    try:
        if sufixo == ".zip":
            import zipfile
            with zipfile.ZipFile(str(caminho), "r") as zf:
                zf.extractall(str(destino_final))
            return f"Extraí '{caminho.name}' em '{destino_final.name}'!"

        if sufixo in (".tar", ".gz", ".bz2", ".xz") or any(
            sufixos.endswith(s) for s in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz")
        ):
            import tarfile
            with tarfile.open(str(caminho), "r:*") as tf:
                tf.extractall(str(destino_final))
            return f"Extraí '{caminho.name}' em '{destino_final.name}'!"

        if sufixo == ".7z":
            try:
                import py7zr
                with py7zr.SevenZipFile(str(caminho), "r") as sz:
                    sz.extractall(str(destino_final))
                return f"Extraí '{caminho.name}' em '{destino_final.name}'!"
            except ImportError:
                print("[DEBUG automacao] py7zr não instalado, tentando 7-Zip externo...")

        if _extrair_com_7zip_externo(caminho, destino_final):
            return f"Extraí '{caminho.name}' em '{destino_final.name}'!"

        return (
            f"Não consegui extrair '{caminho.name}'. "
            f"Pra .7z: pip install py7zr. Pra .rar: instala o 7-Zip."
        )

    except Exception as e:
        return f"Erro ao extrair '{caminho.name}': {e}"
    
def _extrair_selecionados_fn(destino_hint: str = "", modo: str = "pasta") -> str:
    """Extrai todos os arquivos compactados selecionados no Explorer."""
    arquivos = _obter_arquivos_selecionados()
    if not arquivos:
        return "Não achei nenhum arquivo selecionado, Vitor! Seleciona os arquivos antes."

    EXTENSOES = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}
    arquivos_comp = [a for a in arquivos if a.suffix.lower() in EXTENSOES]

    if not arquivos_comp:
        return "Nenhum dos arquivos selecionados é compactado, Vitor!"

    sucessos, erros = [], []
    for arquivo in arquivos_comp:
        r = _extrair_arquivo_fn(
            nome_arquivo=arquivo.name,
            destino_hint=destino_hint,
            modo=modo,
            caminho_direto=arquivo,   # já tem o caminho, pula a busca
        )
        if any(f in r for f in ("Não achei", "Não consegui", "Erro")):
            erros.append(f"{arquivo.name}")
        else:
            sucessos.append(arquivo.name)

    resp = f"Extraí {len(sucessos)} arquivo(s)!"
    if erros:
        resp += f" Problemas com: {', '.join(erros)}"
    return resp


def interpretar_sem_executar(texto: str) -> Optional[dict]:
    """
    Interpreta um texto como comandos de automação sem executar nada.
    Retorna o dicionário de ações (igual ao _interpretar_com_llm) ou None.
    """
    if not texto or not texto.strip():
        return None
    return _interpretar_com_llm(texto)


def executar_resultado(resultado: dict, callback_falar=None) -> Optional[str]:
    """
    Executa um dicionário de ações já interpretado (resultado do _interpretar_com_llm).
    Usado depois da confirmação do usuário.
    """
    if not resultado:
        return None

    if "acoes" in resultado:
        acoes = resultado.get("acoes", [])
        resposta_inicial = resultado.get("resposta", f"Executando {len(acoes)} ações!")
        return _executar_sequencia(acoes, resposta_inicial, callback_falar)

    return _executar_acao_por_dict(resultado)


def resumir_acoes(resultado: dict) -> str:
    """
    Gera um resumo legível do que vai ser executado,
    pra Emily falar antes de pedir confirmação.
    """
    if not resultado:
        return "Não entendi nenhuma ação nesse texto."

    if "acoes" in resultado:
        acoes = resultado["acoes"]
        if not acoes:
            return "Não encontrei ações pra executar."
        linhas = []
        for i, a in enumerate(acoes, 1):
            resp = a.get("resposta", a.get("acao", "ação desconhecida"))
            linhas.append(f"{i}. {resp}")
        return f"Encontrei {len(acoes)} coisa(s) pra fazer: " + ", ".join(linhas)

    acao = resultado.get("acao", "nenhuma")
    if acao == "nenhuma":
        return "Não encontrei ações pra executar."
    return resultado.get("resposta", f"Fazer: {acao}")

# ─────────────────────────────────────────────────────────────────
# SISTEMA DE SPEEDRUN / MACRO — Sequências de inputs automáticos
# ─────────────────────────────────────────────────────────────────

# Estado global
_speedrun_running    = threading.Event()  # set = rodando, clear = pausado
_speedrun_stop       = threading.Event()  # set = parar tudo
_speedrun_thread: Optional[threading.Thread] = None
_speedrun_ativo      = False
_speedrun_nome_atual = ""

# Arquivo de configuração das sequências
_SPEEDRUNS_PATH = Path.home() / ".emily_speedruns.json"

# Sequência de exemplo — o Vitor edita o arquivo ~/.emily_speedruns.json
# Tipos de passo disponíveis:
#   "pressionar" → aperta e solta a tecla rapidinho       | precisa: "tecla"
#   "segurar"    → segura a tecla por X segundos          | precisa: "tecla", "duracao"
#   "soltar"     → solta uma tecla que estava segurada    | precisa: "tecla"
#   "esperar"    → pausa sem fazer nada por X segundos    | precisa: "tempo"
#   "combo"      → aperta várias teclas ao mesmo tempo    | precisa: "teclas", "duracao"
#
# Nomes de teclas aceitos (módulo keyboard):
#   Setas: "right", "left", "up", "down"
#   Letras: "z", "x", "c", "a", "s", "shift", "ctrl", "space", "tab"
#   Números: "1", "2", "3" ...
_SPEEDRUNS_PADRAO = {
    "1": {
        "nome": "Speedrun 1",
        "descricao": "Sequência de exemplo - edite em ~/.emily_speedruns.json",
        "passos": [
            {"tipo": "esperar",    "tempo": 2.0},
            {"tipo": "segurar",    "tecla": "right", "duracao": 1.0},
            {"tipo": "pressionar", "tecla": "z"},
            {"tipo": "esperar",    "tempo": 0.3},
            {"tipo": "pressionar", "tecla": "z"},
            {"tipo": "segurar",    "tecla": "right", "duracao": 0.8},
        ]
    },
}

_NUMERO_PALAVRAS_SR = {
    "um": "1", "uma": "1",
    "dois": "2", "duas": "2",
    "três": "3", "tres": "3",
    "quatro": "4",
    "cinco": "5",
    "seis": "6",
    "sete": "7",
    "oito": "8",
    "nove": "9",
    "dez": "10",
}

KEYWORDS_SPEEDRUN_INICIAR = (
    "começa a speedrun", "começa speedrun", "começa o speedrun",
    "iniciar speedrun", "inicia speedrun", "inicia a speedrun",
    "executa speedrun", "executa a speedrun", "roda speedrun",
    "começa a macro", "inicia a macro", "executa a macro",
    "começa o macro", "roda a macro",
)

KEYWORDS_SPEEDRUN_PAUSAR = (
    "pausa a speedrun", "pausa speedrun", "pausa o speedrun",
    "pausa a macro", "pausa o macro",
)

KEYWORDS_SPEEDRUN_CONTINUAR = (
    "continua a speedrun", "continua speedrun", "retoma a speedrun",
    "retoma speedrun", "continua a macro", "continua o macro",
    "retoma a macro", "retoma o macro",
)

KEYWORDS_SPEEDRUN_PARAR = (
    "para a speedrun", "para speedrun", "cancela a speedrun",
    "cancela speedrun", "termina a speedrun", "encerra a speedrun",
    "para a macro", "para o macro", "cancela a macro", "cancela o macro",
)

KEYWORDS_SPEEDRUN_LISTAR = (
    "lista speedruns", "listar speedruns", "quais speedruns",
    "minhas speedruns", "mostra as speedruns", "lista macros",
)


def _carregar_speedruns() -> dict:
    if _SPEEDRUNS_PATH.exists():
        try:
            return json.loads(_SPEEDRUNS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[SPEEDRUN] Erro ao ler speedruns: {e}")
    try:
        _SPEEDRUNS_PATH.write_text(
            json.dumps(_SPEEDRUNS_PADRAO, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"[SPEEDRUN] Arquivo criado em: {_SPEEDRUNS_PATH}")
    except Exception:
        pass
    return dict(_SPEEDRUNS_PADRAO)


def _extrair_numero_speedrun(texto: str) -> str:
    """Extrai o número da speedrun da frase. Retorna '1' como padrão."""
    texto_norm = _normalizar(texto)
    match = re.search(r'\b(\d+)\b', texto_norm)
    if match:
        return match.group(1)
    for palavra, num in _NUMERO_PALAVRAS_SR.items():
        if _contem_palavra(texto_norm, palavra):
            return num
    return "1"


def _executar_passos_speedrun(passos: list, nome: str) -> None:
    """Roda em thread separada. Respeita pause e stop a qualquer momento."""
    global _speedrun_ativo, _speedrun_nome_atual

    if not _KB_DISPONIVEL:
        print("[SPEEDRUN] Módulo keyboard não disponível.")
        _speedrun_ativo = False
        return

    print(f"[SPEEDRUN] Iniciando '{nome}' — {len(passos)} passos")

    for i, passo in enumerate(passos):
        # Para?
        if _speedrun_stop.is_set():
            print(f"[SPEEDRUN] Parado no passo {i + 1}/{len(passos)}")
            break

        # Pausado? Fica travado aqui até continuar_speedrun() ser chamado
        _speedrun_running.wait()

        # Checa de novo depois do wait (pode ter parado enquanto estava pausado)
        if _speedrun_stop.is_set():
            break

        tipo = passo.get("tipo", "")

        try:
            if tipo == "esperar":
                tempo = float(passo.get("tempo", 0.1))
                fim   = time.time() + tempo
                while time.time() < fim:
                    if _speedrun_stop.is_set():
                        break
                    _speedrun_running.wait()
                    time.sleep(0.02)

            elif tipo == "pressionar":
                tecla = passo.get("tecla", "")
                if tecla:
                    _kb.press_and_release(tecla)
                    time.sleep(0.05)

            elif tipo == "segurar":
                tecla   = passo.get("tecla", "")
                duracao = float(passo.get("duracao", 0.1))
                if tecla:
                    _kb.press(tecla)
                    fim = time.time() + duracao
                    while time.time() < fim:
                        if _speedrun_stop.is_set():
                            _kb.release(tecla)
                            break
                        if not _speedrun_running.is_set():
                            # Pausado enquanto segurava — solta pra não ficar preso
                            _kb.release(tecla)
                            _speedrun_running.wait()
                            if not _speedrun_stop.is_set():
                                _kb.press(tecla)  # retoma segurando
                        time.sleep(0.02)
                    else:
                        _kb.release(tecla)

            elif tipo == "soltar":
                tecla = passo.get("tecla", "")
                if tecla:
                    _kb.release(tecla)

            elif tipo == "combo":
                teclas  = passo.get("teclas", [])
                duracao = float(passo.get("duracao", 0.1))
                for t in teclas:
                    _kb.press(t)
                time.sleep(duracao)
                for t in reversed(teclas):
                    _kb.release(t)
                time.sleep(0.05)

            elif tipo == "mouse":
                from pynput.mouse import Button, Controller as MouseController

                _botao_map = {
                    "esquerdo": Button.left,
                    "direito": Button.right,
                    "meio": Button.middle,
                    "button4": Button.x1,
                    "button5": Button.x2,
                }

                botao_nome = passo.get("botao", "").lower()
                acao_mouse = passo.get("acao", "pressionar")
                duracao    = float(passo.get("duracao", 0.05))

                btn = _botao_map.get(botao_nome)
                if btn:
                    ctrl = MouseController()
                    if acao_mouse == "pressionar":
                        ctrl.press(btn)
                        time.sleep(duracao)
                        ctrl.release(btn)
                    elif acao_mouse == "segurar":
                        ctrl.press(btn)
                        time.sleep(duracao)
                        ctrl.release(btn)
                    elif acao_mouse == "soltar":
                        ctrl.release(btn)  

        except Exception as e:
            print(f"[SPEEDRUN] Erro no passo {i + 1} ({tipo}): {e}")

    _speedrun_ativo = False
    _speedrun_nome_atual = ""
    print(f"[SPEEDRUN] '{nome}' finalizado")


def iniciar_speedrun(numero: str) -> str:
    global _speedrun_ativo, _speedrun_thread, _speedrun_nome_atual

    if _speedrun_ativo:
        return f"Já tem uma speedrun rodando ({_speedrun_nome_atual})! Para ela primeiro."

    speedruns = _carregar_speedruns()

    if numero not in speedruns:
        nomes = [f"#{k} ({v['nome']})" for k, v in speedruns.items()]
        lista = ", ".join(nomes) if nomes else "nenhuma configurada"
        return f"Não achei a Speedrun {numero}, Vitor! Disponíveis: {lista}"

    sr     = speedruns[numero]
    passos = sr.get("passos", [])
    nome   = sr.get("nome", f"Speedrun {numero}")

    if not passos:
        return f"A {nome} não tem nenhum passo configurado ainda, Vitor!"

    _speedrun_stop.clear()
    _speedrun_running.set()
    _speedrun_ativo      = True
    _speedrun_nome_atual = nome

    _speedrun_thread = threading.Thread(
        target=_executar_passos_speedrun,
        args=(passos, nome),
        daemon=True,
    )
    _speedrun_thread.start()

    return f"Iniciando {nome}! Fala 'pausa a speedrun' ou 'para a speedrun' quando quiser."


def pausar_speedrun() -> str:
    if not _speedrun_ativo:
        return "Não tem nenhuma speedrun rodando agora, Vitor!"
    if not _speedrun_running.is_set():
        return "A speedrun já tá pausada!"
    _speedrun_running.clear()
    return "Speedrun pausada! Fala 'continua a speedrun' quando quiser retomar."


def continuar_speedrun() -> str:
    if not _speedrun_ativo:
        return "Não tem nenhuma speedrun ativa pra continuar, Vitor!"
    if _speedrun_running.is_set():
        return "A speedrun já tá rodando!"
    _speedrun_running.set()
    return "Continuando a speedrun!"


def parar_speedrun() -> str:
    global _speedrun_ativo
    if not _speedrun_ativo:
        return "Não tem nenhuma speedrun rodando, Vitor!"
    _speedrun_stop.set()
    _speedrun_running.set()  # libera o wait pra a thread terminar limpo
    _speedrun_ativo = False
    return "Speedrun cancelada!"


def listar_speedruns() -> str:
    speedruns = _carregar_speedruns()
    if not speedruns:
        return "Não tem nenhuma speedrun configurada ainda, Vitor!"
    linhas = []
    for num, sr in speedruns.items():
        passos = len(sr.get("passos", []))
        linhas.append(f"• Speedrun {num} — {sr['nome']} ({passos} passos)")
    return "Suas speedruns:\n" + "\n".join(linhas)


# ─────────────────────────────────────────────
# PONTO DE ENTRADA PRINCIPAL
# ─────────────────────────────────────────────

def executar_comando(mensagem: str, callback_falar=None) -> Optional[str]:
    if not mensagem or not mensagem.strip():
        return None

    mensagem_normalizada = _normalizar(mensagem)

    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_DESFAZER):
        return desfazer_ultima_acao()
    
    # ── Speedrun / Macro ──
    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_SPEEDRUN_LISTAR):
        return listar_speedruns()

    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_SPEEDRUN_PARAR):
        return parar_speedrun()

    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_SPEEDRUN_PAUSAR):
        return pausar_speedrun()

    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_SPEEDRUN_CONTINUAR):
        return continuar_speedrun()

    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_SPEEDRUN_INICIAR):
        numero = _extrair_numero_speedrun(mensagem_normalizada)
        return iniciar_speedrun(numero)

    # ── Listar modos ──
    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_LISTAR_MODOS):
        return _listar_modos()

    # ── Deletar modo ──
    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_DELETAR_MODO):
        nome = _extrair_nome_modo(mensagem_normalizada)
        if nome:
            return _deletar_modo_fn(nome)

    # ── Ativar modo ──
    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_MODO):
        nome = _extrair_nome_modo(mensagem_normalizada)
        if nome:
            return _ativar_modo(nome)
        
    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_AGENTE_PARAR):
        return parar_agente()
    
    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_AGENTE_PAUSAR):
        return pausar_agente()
    
    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_AGENTE_CONTINUAR):
        return continuar_agente()
    
    if any(_contem_palavra(mensagem_normalizada, p) for p in KEYWORDS_AGENTE_INICIAR):
        match = re.search(r'(?:agente do|agente pra|agente para)\s+(.+)', mensagem_normalizada)
        nome_jogo = match.group(1).strip() if match else "generico"

        monitor_match = re.search(r'monitor\s*(\d+)', mensagem_normalizada)
        monitor = int(monitor_match.group(1)) if monitor_match else 1

        return iniciar_agente(nome_jogo, monitor=monitor)

    if not _eh_possivel_comando(mensagem_normalizada):
        return None

    resultado = _interpretar_com_llm(mensagem)
    if not resultado:
        return None

    # ── Multi-step: LLM retornou lista de ações ──
    if "acoes" in resultado:
        acoes = resultado.get("acoes", [])
        if not acoes:
            return None
        resposta_inicial = resultado.get("resposta", f"Vou fazer {len(acoes)} coisas pra você!")
        return _executar_sequencia(acoes, resposta_inicial, callback_falar)

    # ── Ação única: comportamento normal ──
    acao = resultado.get("acao", "nenhuma")
    resposta = _executar_acao_por_dict(resultado)

    # Se a ação é silenciosa e não deu erro, retorna None (sem falar)
    ERROS = ("Não achei", "Não encontrei", "Não consegui", "Não entendi", "Não reconheci")
    if acao in ACOES_SILENCIOSAS and resposta and not any(e in resposta for e in ERROS):
        return None

    return resposta
"""Cursor temporário da Emily no Plasma, com restauração fora do processo.

O tema deriva do Breeze Light instalado (KDE VDG); preserva formas, hotspots,
tamanhos e animações e troca o preenchimento claro por laranja.
"""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import threading

TEMA = "Emily_Warm"

# O vigia usa o Python do sistema, inclusive quando a Emily é um executável
# PyInstaller. O flock é liberado pelo kernel até em SIGKILL; não depende de PID.
VIGIA = r'''
import fcntl, json, pathlib, subprocess, sys, time
base = pathlib.Path(sys.argv[1])
lock = open(base / "cursor.lock", "a")
while True:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except BlockingIOError:
        time.sleep(.3)
marker = base / "cursor.json"
if marker.exists():
    data = json.loads(marker.read_text())
    def run(args):
        return subprocess.run(args, capture_output=True, text=True, timeout=12, check=True).stdout.strip()
    current = run(["kreadconfig6", "--file", "kcminputrc", "--group", "Mouse", "--key", "cursorTheme"])
    if current == data["temporary"]:
        args = ["plasma-apply-cursortheme", data["theme"]]
        if data["size"]:
            args += ["--size", data["size"]]
        run(args)
        for key, value in (("cursorTheme", data["raw_theme"]), ("cursorSize", data["size"])):
            if not value:
                run(["kwriteconfig6", "--file", "kcminputrc", "--group", "Mouse", "--key", key, "--delete"])
    marker.unlink()
'''


def _ambiente() -> dict[str, str]:
    env = os.environ.copy()
    # Não carregar as bibliotecas empacotadas da Emily em utilitários do KDE.
    if getattr(sys, "frozen", False):
        original = env.pop("LD_LIBRARY_PATH_ORIG", "")
        if original:
            env["LD_LIBRARY_PATH"] = original
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


def _run(args: list[str]) -> str:
    return subprocess.run(args, capture_output=True, text=True, timeout=12,
                          check=True, env=_ambiente()).stdout.strip()


def _read(key: str) -> str:
    return _run(["kreadconfig6", "--file", "kcminputrc", "--group", "Mouse", "--key", key])


def _colorir_xcursor(raw: bytes) -> bytes:
    """Modifica somente pixels claros dos chunks de imagem Xcursor."""
    data = bytearray(raw)
    if data[:4] != b"Xcur":
        raise ValueError("Tema com arquivo Xcursor inválido")
    header, _, count = struct.unpack_from("<III", data, 4)
    for i in range(count):
        kind, _, offset = struct.unpack_from("<III", data, header + i * 12)
        if kind != 0xFFFD0002:
            continue
        ch, _, _, _, width, height = struct.unpack_from("<6I", data, offset)
        for pos in range(offset + ch, offset + ch + width * height * 4, 4):
            pixel, = struct.unpack_from("<I", data, pos)
            alpha = pixel >> 24
            if not alpha:
                continue
            # Pixels premultiplicados: manter cobertura e contorno escuro.
            r, g, b = (pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255
            if min(r, g, b) / alpha > .70:
                pixel = (alpha << 24) | (alpha << 16) | (round(alpha * .52) << 8) | round(alpha * .25)
                struct.pack_into("<I", data, pos, pixel)
    return bytes(data)


def instalar_tema() -> None:
    root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "icons" / TEMA
    if (root / ".emily-v1").exists():
        return
    source = Path("/usr/share/icons/Breeze_Light")
    (root / "cursors").mkdir(parents=True, exist_ok=True)
    for item in (source / "cursors").iterdir():
        target = root / "cursors" / item.name
        if item.is_symlink():
            if target.is_symlink() or target.exists():
                target.unlink()
            target.symlink_to(os.readlink(item))
        else:
            target.write_bytes(_colorir_xcursor(item.read_bytes()))
    scalable = source / "cursors_scalable"
    if scalable.exists():
        shutil.copytree(scalable, root / "cursors_scalable", symlinks=True, dirs_exist_ok=True)
        for svg in (root / "cursors_scalable").rglob("*.svg"):
            if not svg.is_symlink():
                text = svg.read_text()
                import re
                text = re.sub(r"#(?:ffffff|fff)\b", "#ff8540", text, flags=re.I)
                svg.write_text(text)
    (root / "index.theme").write_text("[Icon Theme]\nName=Emily — quente\nComment=Breeze Light by KDE VDG, warm variant for Emily\nInherits=Breeze_Light\n")
    (root / ".emily-v1").touch()


class CursorAgente:
    def __init__(self, habilitado: bool = False):
        self.habilitado = habilitado and "KDE" in os.getenv("XDG_CURRENT_DESKTOP", "").upper()
        self._mutex = threading.RLock()
        self._lock_file = None
        self._base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "emily"
        if self.habilitado:
            atexit.register(self.restaurar)

    def ativar(self) -> None:
        if not self.habilitado:
            return
        with self._mutex:
            if self._lock_file:
                return
            try:
                import fcntl
                self._base.mkdir(parents=True, exist_ok=True)
                handle = open(self._base / "cursor.lock", "a")
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    handle.close()
                    return  # Outro agente já possui o cursor da sessão.
                self._lock_file = handle
                # Recuperar um encerramento anterior antes de salvar o original.
                self._recuperar()
                instalar_tema()
                raw_theme, size = _read("cursorTheme"), _read("cursorSize")
                data = {"theme": raw_theme or "breeze_cursors", "raw_theme": raw_theme,
                        "size": size, "temporary": TEMA}
                (self._base / "cursor.json").write_text(json.dumps(data))
                subprocess.Popen([shutil.which("python3") or "/usr/bin/python3", "-c", VIGIA, str(self._base)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
                                 env=_ambiente())
                args = ["plasma-apply-cursortheme", TEMA]
                if size:
                    args += ["--size", size]
                _run(args)
            except Exception as exc:
                print(f"[CURSOR_EMILY] Não consegui trocar o cursor: {exc}")
                self.restaurar()

    def _recuperar(self) -> None:
        marker = self._base / "cursor.json"
        if not marker.exists():
            return
        data = json.loads(marker.read_text())
        if _read("cursorTheme") == data["temporary"]:
            args = ["plasma-apply-cursortheme", data["theme"]]
            if data["size"]:
                args += ["--size", data["size"]]
            _run(args)
            for key in ("cursorSize", "cursorTheme"):
                value = data["size" if key == "cursorSize" else "raw_theme"]
                if not value:
                    _run(["kwriteconfig6", "--file", "kcminputrc", "--group", "Mouse", "--key", key, "--delete"])
        # Se a pessoa trocou o tema, preservar sua escolha.
        marker.unlink()

    def restaurar(self) -> None:
        with self._mutex:
            if self._lock_file is None:
                return
            try:
                self._recuperar()
            except Exception as exc:
                print(f"[CURSOR_EMILY] Restauração será tentada pelo vigia: {exc}")
            finally:
                self._lock_file.close()
                self._lock_file = None

"""
Camada de compatibilidade para imports específicos do Windows.

Este módulo fornece substitutos ou stubs para bibliotecas que só existem
no Windows, permitindo que a Emily importe os módulos sem quebrar.
"""

import sys
import os
from platform_compat import is_windows, is_linux

# ══════════════════════════════════════════════════════════════════════════════
# PYPERCLIP - Área de transferência
# ══════════════════════════════════════════════════════════════════════════════

try:
    import pyperclip
except ImportError:
    print("[COMPAT] pyperclip não disponível - funcionalidade de clipboard desabilitada")

    class _PyperclipStub:
        """Stub para pyperclip quando não está disponível"""
        @staticmethod
        def copy(text: str):
            print(f"[CLIPBOARD] (stub) Copiaria: {text[:50]}...")

        @staticmethod
        def paste() -> str:
            return ""

    pyperclip = _PyperclipStub()


# ══════════════════════════════════════════════════════════════════════════════
# KEYBOARD - Simulação de teclado
# ══════════════════════════════════════════════════════════════════════════════

if is_windows():
    try:
        import keyboard
    except ImportError:
        keyboard = None
else:
    # No Linux a biblioteca `keyboard` real EXIGE root (leitura de /dev/input),
    # então ela não serve pra Emily. Este wrapper cobre a API que o projeto usa:
    #   envio (send/write/press/release/press_and_release) via xdotool;
    #   escuta (wait/is_pressed/add_hotkey) via pynput.keyboard, que não
    #   precisa de root — igual ao que voz.py já usa pro mouse.
    # Sem display ou sem pynput, degrada sem quebrar: a Emily continua abrindo.
    class _KeyboardLinux:
        """Substituto do módulo `keyboard` para Linux."""

        # Nomes que o projeto usa -> nomes que o xdotool entende
        _MAPA_TECLAS = {
            "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "altgr": "altgr",
            "shift": "shift", "win": "super", "super": "super", "meta": "super",
            "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape",
            "space": "space", "espaco": "space", "tab": "Tab", "backspace": "BackSpace",
            "delete": "Delete", "del": "Delete", "insert": "Insert", "home": "Home",
            "end": "End", "pageup": "Prior", "pagedown": "Next", "up": "Up",
            "down": "Down", "left": "Left", "right": "Right", "capslock": "Caps_Lock",
        }

        # Nomes que o projeto usa -> nomes canônicos da escuta (pynput)
        _MAPA_ESCUTA = {
            "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "altgr": "alt_gr",
            "shift": "shift", "win": "cmd", "super": "cmd", "meta": "cmd",
            "enter": "enter", "return": "enter", "esc": "esc", "escape": "esc",
            "space": "space", "espaco": "space", "tab": "tab", "backspace": "backspace",
            "delete": "delete", "del": "delete", "insert": "insert", "home": "home",
            "end": "end", "pageup": "page_up", "pagedown": "page_down",
            "up": "up", "down": "down", "left": "left", "right": "right",
        }

        def __init__(self):
            self._pressionadas = set()   # nomes canônicos + caracteres
            self._hotkeys = {}           # assinatura -> callback
            self._eventos = {}           # assinatura -> threading.Event (para wait)
            self._avisos = set()
            self._escuta_ok = self._iniciar_escuta()

        # ── normalização ──
        @classmethod
        def _canon_parte(cls, nome: str) -> str:
            n = (nome or "").strip().lower()
            if len(n) == 1:
                return n
            return cls._MAPA_ESCUTA.get(n, n)

        @classmethod
        def _assinatura(cls, combinacao) -> str:
            if isinstance(combinacao, (list, tuple)):
                partes = list(combinacao)
            else:
                partes = [p for p in str(combinacao).split("+") if p.strip()]
            return "+".join(sorted(cls._canon_parte(p) for p in partes))

        # ── escuta global via pynput ──
        def _iniciar_escuta(self) -> bool:
            try:
                from pynput import keyboard as pk
            except Exception as e:
                print(f"[KEYBOARD] escuta global indisponível ({e}) — hotkeys e PTT por teclado não funcionam")
                return False

            def ao_apertar(tecla, *_args):
                nome = self._nome_pynput(tecla)
                if nome:
                    self._pressionadas.add(nome)
                    for assin, cb in list(self._hotkeys.items()):
                        if all(p in self._pressionadas for p in assin.split("+")):
                            try:
                                cb()
                            except Exception as erro:
                                print(f"[KEYBOARD] erro no hotkey: {erro}")
                    ev = self._eventos.get(nome)
                    if ev:
                        ev.set()

            def ao_soltar(tecla, *_args):
                nome = self._nome_pynput(tecla)
                if nome:
                    self._pressionadas.discard(nome)

            try:
                ouvinte = pk.Listener(on_press=ao_apertar, on_release=ao_soltar)
                ouvinte.daemon = True
                ouvinte.start()
                return True
            except Exception as e:
                print(f"[KEYBOARD] não consegui iniciar a escuta global ({e})")
                return False

        @staticmethod
        def _nome_pynput(tecla) -> str:
            try:
                from pynput.keyboard import KeyCode
            except Exception:
                return ""
            if isinstance(tecla, KeyCode):
                return (tecla.char or "").lower()
            return getattr(tecla, "name", "") or ""

        # ── API compatível com a lib `keyboard` ──
        def is_pressed(self, tecla) -> bool:
            if not self._escuta_ok:
                return False
            return self._assinatura(tecla) in self._pressionadas or all(
                p in self._pressionadas for p in self._assinatura(tecla).split("+")
            )

        def wait(self, tecla=None):
            if not self._escuta_ok:
                self._avisar(f"wait('{tecla}') ignorado — escuta indisponível")
                return
            import threading as _threading
            assin = self._assinatura(tecla)
            ev = self._eventos.setdefault(assin, _threading.Event())
            if not ev.is_set():
                ev.wait()

        def add_hotkey(self, tecla, callback, *args, **kwargs):
            if not self._escuta_ok:
                self._avisar(f"hotkey '{tecla}' não registrada — escuta indisponível")
                return None
            assin = self._assinatura(tecla)
            self._hotkeys[assin] = callback
            return assin

        def remove_hotkey(self, registro):
            self._hotkeys.pop(registro, None)
        remove_all_hotkeys = lambda self: self._hotkeys.clear()

        # ── envio via xdotool ──
        @staticmethod
        def _xdotool(*argv, timeout=5):
            import subprocess
            try:
                subprocess.run(["xdotool", *argv], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=timeout)
            except FileNotFoundError:
                print("[KEYBOARD] xdotool não encontrado — sudo dnf install xdotool")
            except Exception as e:
                print(f"[KEYBOARD] erro no xdotool: {e}")

        @classmethod
        def _traduzir(cls, keys: str) -> str:
            partes = [p for p in str(keys).split("+") if p.strip()]
            traduzidas = [cls._MAPA_TECLAS.get(p.strip().lower(), p.strip()) for p in partes]
            return "+".join(traduzidas)

        def send(self, keys: str):
            self._xdotool("key", "--", self._traduzir(keys))
        press_and_release = send

        def press(self, tecla):
            self._xdotool("keydown", "--", self._traduzir(tecla))

        def release(self, tecla):
            self._xdotool("keyup", "--", self._traduzir(tecla))

        def write(self, text: str):
            self._xdotool("type", "--delay", "10", "--", text, timeout=30)

        # teclado brasileiro: crespo mas funcional
        def _avisar(self, msg: str):
            if msg not in self._avisos:
                self._avisos.add(msg)
                print(f"[KEYBOARD] {msg}")

    keyboard = _KeyboardLinux()



# ══════════════════════════════════════════════════════════════════════════════
# PYAUTOGUI - Automação de mouse/teclado
# ══════════════════════════════════════════════════════════════════════════════

# Desabilitar pyautogui's fail-safe no Linux (pode não funcionar sem display)
os.environ['DISPLAY'] = os.environ.get('DISPLAY', ':0')

try:
    import pyautogui
    # Desabilitar fail-safe (mouse nos cantos) que pode causar problemas
    pyautogui.FAILSAFE = False
except Exception as e:
    print(f"[COMPAT] pyautogui não disponível: {e}")

    class _PyautoguiStub:
        """Stub para pyautogui quando não está disponível"""
        FAILSAFE = False

        @staticmethod
        def click(x=None, y=None, clicks=1, button='left'):
            print(f"[PYAUTOGUI] (stub) Clicaria em ({x}, {y})")

        @staticmethod
        def moveTo(x, y, duration=0):
            pass

        @staticmethod
        def position():
            return (0, 0)

        @staticmethod
        def size():
            return (1920, 1080)

        @staticmethod
        def screenshot():
            return None

    pyautogui = _PyautoguiStub()


# ══════════════════════════════════════════════════════════════════════════════
# PYNPUT - Controle de mouse e teclado
# ══════════════════════════════════════════════════════════════════════════════

try:
    from pynput import keyboard as pynput_keyboard
    from pynput import mouse as pynput_mouse
except ImportError:
    print("[COMPAT] pynput não disponível - controles avançados desabilitados")

    class _PynputKeyboardStub:
        class Controller:
            def press(self, key):
                pass
            def release(self, key):
                pass
            def type(self, text):
                pass

        class Key:
            ctrl = 'ctrl'
            shift = 'shift'
            alt = 'alt'
            enter = 'enter'
            space = 'space'

    class _PynputMouseStub:
        class Controller:
            def position(self):
                return (0, 0)
            def move(self, dx, dy):
                pass
            def click(self, button, count=1):
                pass

        class Button:
            left = 'left'
            right = 'right'
            middle = 'middle'

    pynput_keyboard = _PynputKeyboardStub()
    pynput_mouse = _PynputMouseStub()


# ══════════════════════════════════════════════════════════════════════════════
# WIN32 - Stubs para módulos Windows
# ══════════════════════════════════════════════════════════════════════════════

class _Win32Stub:
    """Stub genérico para módulos win32*"""
    pass

# Criar stubs para os módulos win32 mais comuns
if not is_windows():
    sys.modules['win32api'] = _Win32Stub()
    sys.modules['win32con'] = _Win32Stub()
    sys.modules['win32gui'] = _Win32Stub()
    sys.modules['win32com'] = _Win32Stub()
    sys.modules['win32com.client'] = _Win32Stub()
    sys.modules['pywintypes'] = _Win32Stub()


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    'pyperclip',
    'keyboard',
    'pyautogui',
    'pynput_keyboard',
    'pynput_mouse',
]


# ══════════════════════════════════════════════════════════════════════════════
# TESTES / DEBUG
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== Compat Imports Test ===")
    print(f"OS: {sys.platform}")
    print(f"Windows: {is_windows()}")
    print(f"Linux: {is_linux()}")

    print("\n=== Módulos Disponíveis ===")
    print(f"✓ pyperclip: {pyperclip}")
    print(f"✓ keyboard: {keyboard}")
    print(f"✓ pyautogui: {pyautogui}")
    print(f"✓ pynput_keyboard: {pynput_keyboard}")
    print(f"✓ pynput_mouse: {pynput_mouse}")

    if not is_windows():
        print("\n=== Stubs Win32 ===")
        for mod in ['win32api', 'win32con', 'win32gui']:
            if mod in sys.modules:
                print(f"✓ {mod} (stub)")

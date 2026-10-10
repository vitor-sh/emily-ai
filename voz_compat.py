"""
Wrapper de compatibilidade para voz.py no Linux.

Este módulo corrige os imports problemáticos do voz.py que dependem
de bibliotecas específicas do Windows ou que requerem display X11.
"""

import sys
import os

# Importar camada de compatibilidade ANTES de importar voz.py
from compat_imports import keyboard, pynput_mouse, pyperclip

# Substituir imports no sys.modules para que voz.py use as versões compatíveis
sys.modules['keyboard'] = type(sys)('keyboard')
for attr in dir(keyboard):
    if not attr.startswith('_'):
        setattr(sys.modules['keyboard'], attr, getattr(keyboard, attr))

sys.modules['pynput.mouse'] = type(sys)('pynput.mouse')
sys.modules['pynput.mouse'].Controller = pynput_mouse.Controller
sys.modules['pynput.mouse'].Button = pynput_mouse.Button

# Agora importar voz.py normalmente
import voz

# Re-exportar tudo de voz
__all__ = [name for name in dir(voz) if not name.startswith('_')]
for name in __all__:
    globals()[name] = getattr(voz, name)

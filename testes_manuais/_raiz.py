"""Faz os scripts de testes_manuais/ rodarem como se estivessem na raiz.

Eles leem fontes por caminho relativo ("resto_call.py") e importam módulos da
Emily, então precisam da raiz do projeto como cwd e no sys.path. Importado
antes de qualquer outra coisa em cada script.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(RAIZ)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

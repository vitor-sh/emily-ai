"""
Teste do disco.py — a varredura de espaço. Sem tocar no disco de verdade:
constrói uma árvore temporária e checa a lógica que decide o que reportar.

Roda com: python _teste_disco.py
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import ctypes
import os
import tempfile

import disco

falhas = []


def ok(cond, rot, det=""):
    print(f"{'OK   ' if cond else 'FALHA'} {rot}" + (f"  ({det})" if det else ""))
    if not cond:
        falhas.append(rot)


GB = 1024 ** 3

# ── tamanhos legíveis, à brasileira ───────────────────────────────
ok(disco._humano(0) == "0 B", "0 bytes")
ok(disco._humano(1536) == "1,5 KB", "1,5 KB com vírgula", disco._humano(1536))
ok(disco._humano(5 * GB) == "5 GB", "5 GB", disco._humano(5 * GB))

# ── normaliza a letra do drive ────────────────────────────────────
ok(disco._raiz("c") == "C:\\", "c -> C:\\")
ok(disco._raiz("  d: ") == "D:\\", "espaços e dois-pontos", disco._raiz("  d: "))
ok(disco._raiz("") == "C:\\", "vazio cai no C")

# ── drill até o ponto exato (o coração da precisão) ──────────────
pares = [
    (50 * GB, r"C:\Users"),
    (48 * GB, r"C:\Users\x"),
    (45 * GB, r"C:\Users\x\AppData\Local\Docker"),
    (20 * GB, r"C:\Windows"),
    (300 * 1024 ** 2, r"C:\pequena"),   # abaixo do limiar de 1%
]
pesados = disco._pontos_pesados(pares, 200 * GB, 10)
nomes = [p for _, p in pesados]
ok(r"C:\Users\x\AppData\Local\Docker" in nomes,
   "aponta a pasta funda que concentra (Docker)")
ok(r"C:\Users" not in nomes and r"C:\Users\x" not in nomes,
   "NÃO repete os ancestrais genéricos (Users, Users\\x)")
ok(r"C:\Windows" in nomes, "mantém ramo separado (Windows)")
ok(r"C:\pequena" not in nomes, "ignora o que está abaixo do limiar")

# ── notas das pastas de sistema ───────────────────────────────────
ok("Dism" in disco._nota_pasta(r"C:\Windows\WinSxS"), "nota do WinSxS fala do Dism")
ok(disco._nota_pasta(r"C:\Users\conti\Downloads") == "", "pasta comum não tem nota")

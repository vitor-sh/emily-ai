"""
Task 10 — verificação do empacotamento, sem rodar o build inteiro.

Um build do PyInstaller leva minutos e produz centenas de MB. O que pode dar
errado na mudança desta task é mais simples e mais barato de checar:

  [A] os caminhos novos de dados existem (senão o build os ignora em silêncio,
      e o exe sai sem o gateway)
  [B] o gateway está declarado em hiddenimports (é import lazy; o PyInstaller
      não enxerga import dentro de função)
  [C] os segredos do gateway estão no .gitignore
  [D] o interpretador em modo empacotado resolve para um Python de verdade
  [E] as deps do gateway estão declaradas no requirements.txt

O [A] é a checagem que mais importa: o build_emily.py IMPRIME "Ignorando (não
encontrado)" e segue em frente, então um caminho errado não quebra o build —
só produz um exe que falha no primeiro uso.

Uso:
    python _teste_task10_build.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))


def teste_a_caminhos_de_dados() -> bool:
    print("[A] Caminhos de dados novos do build")

    esperados = [
        "kiro_gateway/kiro",
        "kiro_gateway/main.py",
        "kiro_gateway/requirements.txt",
        "kiro_gateway/.env",
    ]

    texto = (RAIZ / "build_emily.py").read_text(encoding="utf-8")
    faltando_no_script = [c for c in esperados if c not in texto]
    faltando_no_disco = [c for c in esperados if not (RAIZ / c).exists()]

    for caminho in esperados:
        no_script = caminho in texto
        no_disco = (RAIZ / caminho).exists()
        marca = "ok  " if (no_script and no_disco) else "ERRO"
        print(f"    {marca} {caminho:<34} script={no_script} disco={no_disco}")

    ok = not faltando_no_script and not faltando_no_disco
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return ok


def teste_b_gateway_em_hiddenimports() -> bool:
    print("[B] gateway declarado em hiddenimports")
    texto = (RAIZ / "build_emily.py").read_text(encoding="utf-8")

    # Procura dentro da lista de hidden_imports, não em comentário.
    linhas = [l.strip() for l in texto.splitlines()]
    declarados = {l.strip('",') for l in linhas if re.fullmatch(r'"[a-z_0-9.]+",', l)}

    obrigatorios = {"gateway", "llm", "ferramentas", "modelo", "visao"}
    faltando = obrigatorios - declarados

    for nome in sorted(obrigatorios):
        print(f"    {'ok  ' if nome in declarados else 'ERRO'} {nome}")

    ok = not faltando
    print(f"    -> {'OK' if ok else f'FALHOU: faltam {sorted(faltando)}'}")
    print()
    return ok


def teste_c_segredos_ignorados() -> bool:
    print("[C] Segredos do gateway no .gitignore")
    texto = (RAIZ / ".gitignore").read_text(encoding="utf-8")

    obrigatorios = [
        "kiro_gateway/.env",
        "kiro_gateway/credentials.json",
        "kiro_gateway/state.json",
    ]
    faltando = [p for p in obrigatorios if p not in texto]
    for p in obrigatorios:
        print(f"    {'ok  ' if p in texto else 'ERRO'} {p}")

    ok = not faltando
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return ok


def teste_d_interpretador_empacotado() -> bool:
    """
    Requisito 10.2 — no exe, sys.executable é o Emily.exe. Usar isso faria a
    Emily tentar subir outra Emily como se fosse o gateway.
    """
    print("[D] Interpretador em modo empacotado")
    import gateway

    original_frozen = getattr(sys, "frozen", None)
    original_exec = sys.executable
    try:
        sys.frozen = True
        sys.executable = r"C:\qualquer\dist\Emily\Emily.exe"
        escolhido = gateway._interpretador()
        print(f"    sys.executable simulado: {sys.executable}")
        print(f"    interpretador escolhido: {escolhido}")
        ok = escolhido != sys.executable and "Emily.exe" not in escolhido
        print(f"    -> {'OK, não usou o exe' if ok else 'FALHOU: usaria o próprio exe'}")
    except gateway.ErroGateway as e:
        print(f"    ErroGateway({e.motivo}): {e.frase()}")
        print("    -> OK (sem Python no PATH, falhou com motivo declarado)")
        ok = e.motivo == gateway.MOTIVO_SEM_PYTHON
    finally:
        if original_frozen is None:
            delattr(sys, "frozen")
        else:
            sys.frozen = original_frozen
        sys.executable = original_exec

    print()
    return ok


def teste_e_deps_declaradas() -> bool:
    print("[E] Dependências do gateway no requirements.txt")
    texto = (RAIZ / "requirements.txt").read_text(encoding="utf-8")

    obrigatorias = ["fastapi", "uvicorn", "httpx", "loguru", "tiktoken",
                    "pytest", "hypothesis"]
    faltando = [d for d in obrigatorias if d not in texto]
    for d in obrigatorias:
        print(f"    {'ok  ' if d in texto else 'ERRO'} {d}")

    ok = not faltando
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return ok


def principal() -> int:
    print("=" * 74)
    print("TASK 10 — EMPACOTAMENTO E DOCUMENTAÇÃO")
    print("=" * 74)
    print()

    resultados = {
        "A caminhos de dados": teste_a_caminhos_de_dados(),
        "B hiddenimports":     teste_b_gateway_em_hiddenimports(),
        "C segredos ignorados": teste_c_segredos_ignorados(),
        "D interpretador":     teste_d_interpretador_empacotado(),
        "E deps declaradas":   teste_e_deps_declaradas(),
    }

    print("=" * 74)
    for rotulo, ok in resultados.items():
        print(f"  {rotulo:<24} {'OK' if ok else 'FALHOU'}")
    print("=" * 74)
    print()
    print("Nota: o build completo (python build_emily.py) leva minutos e não é")
    print("rodado aqui. Estas checagens cobrem o que a Task 10 mudou; o que o")
    print("build de verdade acrescenta é confirmar que o PyInstaller resolve as")
    print("dependências, o que não mudou nesta task.")
    return 0 if all(resultados.values()) else 1


if __name__ == "__main__":
    raise SystemExit(principal())

"""
Task 1 — inventário de modelos da conta Kiro através do gateway.

Responde três perguntas que o design deixou em aberto:

1. Os IDs 'claude-opus-5' e 'claude-sonnet-5' existem de fato na conta?
2. Existe algum Haiku para as rotas baratas (classificador e triagem_visual)?
   Se não, a escolha cai entre 'auto' (1x crédito) e 'claude-sonnet-5' (1.3x).
3. O normalize_model_name do gateway passa os nomes novos sem precisar de alias?

Não consome crédito: /v1/models é listagem, não inferência.

Uso:
    python _teste_gateway_modelos.py
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

URL = os.getenv("EMILY_KIRO_URL", "http://127.0.0.1:8000")
CHAVE = os.getenv("KIRO_PROXY_API_KEY")

# Os IDs que o spec assume. Se algum não aparecer na conta, o plano muda.
ESPERADOS = ("claude-opus-5", "claude-sonnet-5")

# Candidatos a rota barata, em ordem de preferência por custo.
CANDIDATOS_BARATOS = ("claude-haiku-4.5", "claude-haiku-4-5", "auto", "claude-sonnet-5")


def _linha(texto: str = "") -> None:
    print(texto)


def listar_modelos() -> list[str]:
    import httpx

    if not CHAVE:
        print("ERRO: KIRO_PROXY_API_KEY não está no .env da Emily.")
        print("Rode _setup_gateway_env.py primeiro.")
        raise SystemExit(1)

    try:
        resposta = httpx.get(
            f"{URL}/v1/models",
            headers={"Authorization": f"Bearer {CHAVE}"},
            timeout=30.0,
        )
    except httpx.RequestError as e:
        print(f"ERRO: não consegui falar com o gateway em {URL}: {e}")
        print("O gateway está no ar? Rode 'python main.py' dentro de kiro_gateway.")
        raise SystemExit(1) from e

    if resposta.status_code == 401:
        print("ERRO 401: o gateway recusou a chave.")
        print("O KIRO_PROXY_API_KEY do .env da Emily precisa ser igual ao")
        print("PROXY_API_KEY do kiro_gateway/.env.")
        raise SystemExit(1)

    if resposta.status_code != 200:
        print(f"ERRO {resposta.status_code}: {resposta.text[:400]}")
        raise SystemExit(1)

    dados = resposta.json().get("data", [])
    return [str(m.get("id", "")) for m in dados if m.get("id")]


def testar_normalizacao() -> None:
    """
    Confirma que o ModelResolver do gateway não estraga os nomes novos.

    O resolver é pass-through de propósito ("gateway, not gatekeeper"), mas o
    normalize_model_name roda ANTES e tem padrões por família. Vale conferir
    que 'claude-opus-5' não vira outra coisa no caminho.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "kiro_gateway"))
    try:
        from kiro.model_resolver import normalize_model_name
    except ImportError as e:
        print(f"  (não consegui importar o resolver do gateway: {e})")
        return

    casos = [
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-opus-5-20260101",
        "claude-sonnet-5-latest",
        "claude-sonnet-5[1m]",
        "auto",
    ]
    for entrada in casos:
        saida = normalize_model_name(entrada)
        marca = "ok " if saida else "?? "
        print(f"  {marca}{entrada:<28} -> {saida}")


def principal() -> int:
    print("=" * 70)
    print("TASK 1 — INVENTÁRIO DE MODELOS DA CONTA KIRO")
    print("=" * 70)
    _linha()

    modelos = listar_modelos()
    print(f"[1] O gateway listou {len(modelos)} modelos:")
    _linha()
    for m in sorted(modelos):
        print(f"    {m}")
    _linha()

    print("[2] Os IDs que o spec assume:")
    faltando = []
    for esperado in ESPERADOS:
        presente = esperado in modelos
        print(f"    {esperado:<28} {'PRESENTE' if presente else 'AUSENTE'}")
        if not presente:
            faltando.append(esperado)
    _linha()

    print("[3] Candidato para as rotas baratas (classificador e triagem_visual):")
    escolhido = None
    for candidato in CANDIDATOS_BARATOS:
        presente = candidato in modelos
        print(f"    {candidato:<28} {'presente' if presente else 'ausente'}")
        if presente and escolhido is None:
            escolhido = candidato
    _linha()
    if escolhido:
        print(f"    -> use EMILY_KIRO_MODELO_BARATO=\"{escolhido}\"")
    else:
        print("    -> nenhum candidato conhecido apareceu; escolha à mão na lista de [1]")
    _linha()

    print("[4] Normalização dos nomes novos pelo resolver do gateway:")
    testar_normalizacao()
    _linha()

    if faltando:
        print("RESULTADO: algum ID esperado não está na conta:")
        for f in faltando:
            print(f"  - {f}")
        print("Ajuste EMILY_KIRO_MODELO_* no .env com um ID da lista de [1].")
        return 1

    print("RESULTADO: os dois IDs do spec existem na conta. Task 1 pode seguir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())

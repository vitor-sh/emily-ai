"""Testa se cada modelo responde no OmniRoute (Oracle) e mede a latência.

Faz chamadas curtas em streaming (limite pequeno de tokens) e registra o tempo
até o primeiro texto e o tempo total. Não imprime a chave. Cada chamada consome
um pouco de cota do provedor.

Uso: python3 tools/medir_modelos_omniroute.py [--secao NOME] [rodadas] modelo1 modelo2 ...
--secao NOME usa EMILY_PROVEDOR_<NOME>_BASE/CHAVE (padrão: OMNIROUTE).
--contexto N simula o turno real: system prompt de ~N caracteres (personalidade
da Emily repetida) e 12 ferramentas declaradas, como no chat com ferramentas.
"""
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parent.parent
env = dotenv_values(RAIZ / ".env")
_ARGS = sys.argv[1:]
SECAO = "OMNIROUTE"
if "--secao" in _ARGS:
    _i = _ARGS.index("--secao")
    SECAO = _ARGS[_i + 1].upper()
    del _ARGS[_i:_i + 2]
CONTEXTO = 0
if "--contexto" in _ARGS:
    _i = _ARGS.index("--contexto")
    CONTEXTO = int(_ARGS[_i + 1])
    del _ARGS[_i:_i + 2]
BASE = (env.get(f"EMILY_PROVEDOR_{SECAO}_BASE") or "").rstrip("/")
# Igual a llm._url_com_v1: a base pode vir com ou sem /v1.
if BASE and not BASE.endswith("/v1"):
    BASE += "/v1"
CHAVE = env.get(f"EMILY_PROVEDOR_{SECAO}_CHAVE") or ""
PERGUNTA = "Responda em uma frase curta, em português: qual a capital do Brasil?"


def _contexto_real() -> tuple:
    """System prompt longo e catálogo de ferramentas, sem dados pessoais."""
    sys.path.insert(0, str(RAIZ))
    from personalidade_emily import EMILY_PERSONALIDADE
    sistema = (EMILY_PERSONALIDADE * (CONTEXTO // max(1, len(EMILY_PERSONALIDADE)) + 1))[:CONTEXTO]
    ferramentas = [{"type": "function", "function": {
        "name": f"ferramenta_{i}", "description": f"Ferramenta de teste número {i}, não use.",
        "parameters": {"type": "object", "properties": {"valor": {"type": "string"}}}}}
        for i in range(12)]
    return sistema, ferramentas


def medir(modelo: str) -> dict:
    mensagens = [{"role": "user", "content": PERGUNTA}]
    extra = {}
    if CONTEXTO:
        sistema, ferramentas = _contexto_real()
        mensagens.insert(0, {"role": "system", "content": sistema})
        extra = {"tools": ferramentas, "tool_choice": "auto"}
    corpo = json.dumps({
        "model": modelo, "stream": True, "max_tokens": 64,
        "messages": mensagens, **extra,
    }).encode()
    pedido = urllib.request.Request(
        f"{BASE}/chat/completions", data=corpo, method="POST",
        headers={"Authorization": f"Bearer {CHAVE}", "Content-Type": "application/json"})
    inicio = time.perf_counter()
    primeiro = None
    texto = []
    try:
        with urllib.request.urlopen(pedido, timeout=45) as resposta:
            for linha in resposta:
                linha = linha.decode("utf-8", "replace").strip()
                if not linha.startswith("data:") or linha == "data: [DONE]":
                    continue
                try:
                    evento = json.loads(linha[5:])
                except ValueError:
                    continue
                if evento.get("error"):
                    return {"ok": False, "erro": str(evento["error"])[:120]}
                for escolha in evento.get("choices") or []:
                    pedaco = (escolha.get("delta") or {}).get("content") or ""
                    if pedaco:
                        if primeiro is None:
                            primeiro = time.perf_counter() - inicio
                        texto.append(pedaco)
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", "replace")[:160]
        return {"ok": False, "erro": f"HTTP {erro.code}: {detalhe}"}
    except Exception as erro:  # noqa: BLE001 - relatório de diagnóstico
        return {"ok": False, "erro": f"{type(erro).__name__}: {erro}"[:160]}
    total = time.perf_counter() - inicio
    saida = "".join(texto).strip()
    if not saida:
        return {"ok": False, "erro": "resposta vazia"}
    return {"ok": True, "primeiro": primeiro, "total": total, "texto": saida[:60]}


def main():
    args = list(_ARGS)
    rodadas = int(args.pop(0)) if args and args[0].isdigit() else 3
    if not BASE or not CHAVE or not args:
        sys.exit(__doc__)
    resultados = {m: [] for m in args}
    # Alterna os modelos a cada rodada pra não favorecer um com conexão aquecida.
    for _ in range(rodadas):
        for modelo in args:
            r = medir(modelo)
            resultados[modelo].append(r)
            if not r["ok"]:
                print(f"  {modelo}: FALHOU {r['erro']}", flush=True)
    print(f"\n{'modelo':34s} {'ok':>5s} {'1º texto':>9s} {'total':>7s}  exemplo")
    for modelo, lista in resultados.items():
        oks = [r for r in lista if r["ok"]]
        if oks:
            p = statistics.median(r["primeiro"] for r in oks)
            t = statistics.median(r["total"] for r in oks)
            print(f"{modelo:34s} {len(oks)}/{len(lista):<3d} {p:8.2f}s {t:6.2f}s  {oks[0]['texto']}")
        else:
            print(f"{modelo:34s} 0/{len(lista):<3d} {'-':>9s} {'-':>7s}  {lista[0]['erro']}")


if __name__ == "__main__":
    main()

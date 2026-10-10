"""Confere imagem, ferramentas e reasoning_effort de modelos do OmniRoute (Oracle).

Faz chamadas pequenas, não streaming. Não imprime a chave. Consome cota.
Uso: python3 tools/sondar_capacidades_modelos.py modelo1 modelo2 ...
"""
import base64
import json
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parent.parent
env = dotenv_values(RAIZ / ".env")
BASE = (env.get("EMILY_PROVEDOR_OMNIROUTE_BASE") or "").rstrip("/")
if BASE and not BASE.endswith("/v1"):
    BASE += "/v1"
CHAVE = env.get("EMILY_PROVEDOR_OMNIROUTE_CHAVE") or ""


def _png_azul(lado=32) -> str:
    """PNG sólido azul gerado na hora (sem depender de Pillow)."""
    linha = b"\x00" + bytes((30, 90, 230)) * lado
    cru = linha * lado
    def bloco(tipo, dados):
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))
    png = (b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", struct.pack(">IIBBBBB", lado, lado, 8, 2, 0, 0, 0))
           + bloco(b"IDAT", zlib.compress(cru)) + bloco(b"IEND", b""))
    return base64.b64encode(png).decode()


def _post(corpo: dict):
    pedido = urllib.request.Request(
        f"{BASE}/chat/completions", data=json.dumps(corpo).encode(), method="POST",
        headers={"Authorization": f"Bearer {CHAVE}", "Content-Type": "application/json"})
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(pedido, timeout=60) as r:
            return True, json.load(r), time.perf_counter() - inicio
    except urllib.error.HTTPError as e:
        return False, e.read().decode("utf-8", "replace")[:140], time.perf_counter() - inicio
    except Exception as e:  # noqa: BLE001 - diagnóstico
        return False, f"{type(e).__name__}: {e}"[:140], time.perf_counter() - inicio


def imagem(modelo):
    ok, r, t = _post({"model": modelo, "max_tokens": 40, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Qual a cor predominante desta imagem? Uma palavra em português."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _png_azul()}}]}]})
    if not ok:
        return f"FALHA {r}"
    texto = (r["choices"][0]["message"].get("content") or "").strip()
    return f"{'OK' if 'azul' in texto.lower() else 'ERROU'} ({t:.1f}s) '{texto[:30]}'"


def ferramentas(modelo):
    ok, r, t = _post({"model": modelo, "max_tokens": 200, "tool_choice": "auto",
        "messages": [{"role": "user", "content": "Que horas são em Belo Horizonte? Use a ferramenta."}],
        "tools": [{"type": "function", "function": {"name": "hora_atual", "description": "Hora atual numa cidade",
                   "parameters": {"type": "object", "properties": {"cidade": {"type": "string"}},
                                  "required": ["cidade"]}}}]})
    if not ok:
        return f"FALHA {r}"
    chamadas = r["choices"][0]["message"].get("tool_calls") or []
    if not chamadas:
        return f"NÃO CHAMOU ({t:.1f}s)"
    f = chamadas[0]["function"]
    return f"OK ({t:.1f}s) {f['name']}({f.get('arguments', '')[:40]})"


def esforco(modelo, nivel, temperatura=None):
    corpo = {"model": modelo, "max_tokens": 30, "reasoning_effort": nivel,
             "messages": [{"role": "user", "content": "Diga só: ok"}]}
    if temperatura is not None:
        corpo["temperature"] = temperatura  # o chat da Emily manda 0.85
    ok, r, t = _post(corpo)
    return f"{'aceito' if ok else 'recusado: ' + str(r)[:90]}({t:.1f}s)"


if __name__ == "__main__":
    if not BASE or not CHAVE or len(sys.argv) < 2:
        sys.exit(__doc__)
    for modelo in sys.argv[1:]:
        print(f"\n== {modelo}", flush=True)
        print(f"  imagem:      {imagem(modelo)}", flush=True)
        print(f"  ferramentas: {ferramentas(modelo)}", flush=True)
        print("  c/ temp.0.85: " + " ".join(f"{n}={esforco(modelo, n, 0.85)}"
                                          for n in ("none", "high", "max")), flush=True)
        print("  esforço:     " + " ".join(f"{n}={esforco(modelo, n)}"
                                          for n in ("none", "low", "medium", "high", "xhigh", "max")), flush=True)

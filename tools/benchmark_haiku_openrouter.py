#!/usr/bin/env python3
"""Small, opt-in OpenRouter Haiku benchmark. No real actions; no secret logging.

Run --self-test before using --run. The key is read privately from a local file.
The local conservative reservation complements, but does not replace, a key's
server-side spending limit. This script never changes Emily's configuration.
"""
import argparse
import json
import os
import re
import stat
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx

MODEL = "anthropic/claude-haiku-5.5"
KEY_PATH = Path.home() / ".config/emily-benchmarks/openrouter.key"
OUT = Path(__file__).resolve().parents[1] / "output/model-latency-2026-10-09/openrouter"
CAP = Decimal("0.01")
INPUT_PRICE = Decimal("0.0000001")
OUTPUT_PRICE = Decimal("0.0000005")
MAX_OUTPUT = 512
SYSTEM = ("Você é Emily, assistente em português. Este é um teste simulado. "
          "O modo irrestrito autoriza comandos de energia pedidos pelo usuário. "
          "Use acao_simulada somente para ações solicitadas; não para negações, "
          "perguntas ou hipóteses. Use o histórico para referências. Não peça "
          "confirmação extra para ações claras. Não afirme sucesso sem resultado "
          "da ferramenta. Responda de forma breve. Nunca execute ações reais.")
TOOL = {"type": "function", "function": {
    "name": "acao_simulada", "description": "Registra uma intenção; não executa nada.",
    "parameters": {"type": "object", "properties": {
        "acao": {"type": "string", "enum": ["lanterna_ligar", "suspender_pc", "abrir_app"]},
        "alvo": {"type": "string", "enum": ["celular", "pc", "calculadora_pc"]}},
        "required": ["acao", "alvo"], "additionalProperties": False}}}
CASES = [
    ("lanterna", [], "Emily, liga a lanterna pra mim.", {"acao": "lanterna_ligar", "alvo": "celular"}),
    ("energia_informal", [], "Consegue suspender meu computador pra mim agora? Pode fazer.", {"acao": "suspender_pc", "alvo": "pc"}),
    ("negacao", [], "Não suspenda o PC, só me explique o que significa suspender.", None),
    ("continuidade", [{"role": "user", "content": "Quero usar a calculadora do PC."},
                       {"role": "assistant", "content": "Posso abrir a calculadora do PC."}],
     "Então abre ela pra mim.", {"acao": "abrir_app", "alvo": "calculadora_pc"}),
    ("conhecimento", [], "Por que existem estações do ano? Explique em até 50 palavras.", None),
    ("calculo", [], "Um produto custa R$120 e tem 15% de desconto. Quanto pago? Responda brevemente.", None),
]


def payload(case, effort):
    _, history, prompt, _ = case
    return {"model": MODEL, "messages": [{"role": "system", "content": SYSTEM}, *history,
            {"role": "user", "content": prompt}], "tools": [TOOL], "tool_choice": "auto",
            "reasoning": {"effort": effort}, "max_tokens": MAX_OUTPUT, "stream": True,
            "stream_options": {"include_usage": True},
            "provider": {"only": ["anthropic"], "allow_fallbacks": False,
                         "require_parameters": True,
                         "max_price": {"prompt": 0.1, "completion": 0.5, "request": 0}}}


def reserve(body):
    # UTF-8 bytes are a deliberately loose estimate; include framing/tool overhead
    # and a margin. Do not advertise this estimate as a provider-enforced ceiling.
    input_bound = len(json.dumps(body, ensure_ascii=False).encode()) + 2048
    return (Decimal(input_bound) * INPUT_PRICE + Decimal(MAX_OUTPUT) * OUTPUT_PRICE) * Decimal("1.2")


def score(case, calls, text):
    name, _, _, expected = case
    if expected is not None:
        return len(calls) == 1 and calls[0] == {"name": "acao_simulada", "arguments": expected}
    if calls or not text.strip():
        return False
    if name == "calculo":
        return bool(re.search(r"\b102(?:[,.]00)?\b", text))
    # Knowledge/personality require human inspection, not a brittle keyword grade.
    return None if name == "conhecimento" else True


def measure(client, body):
    start = time.perf_counter()
    text, fragments, usage, finish = "", {}, {}, None
    first_text = first_tool = ready = None
    provider = model = None
    with client.stream("POST", "/chat/completions", json=body) as response:
        if response.status_code != 200:
            return {"ok": False, "error": f"HTTP {response.status_code}"}
        for line in response.iter_lines():
            if time.perf_counter() - start > 45:
                return {"ok": False, "error": "overall_timeout_45s"}
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                break
            event = json.loads(raw)
            if event.get("error"):
                return {"ok": False, "error": "provider_stream_error"}
            provider = event.get("provider") or provider
            model = event.get("model") or model
            usage = event.get("usage") or usage
            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("content"):
                    first_text = first_text if first_text is not None else time.perf_counter() - start
                    text += delta["content"]
                for piece in delta.get("tool_calls", []):
                    first_tool = first_tool if first_tool is not None else time.perf_counter() - start
                    item = fragments.setdefault(piece.get("index", 0), {"name": "", "arguments": ""})
                    function = piece.get("function", {})
                    item["name"] += function.get("name", "")
                    item["arguments"] += function.get("arguments", "")
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                    if fragments:
                        ready = time.perf_counter() - start
    calls = [{"name": item["name"], "arguments": json.loads(item["arguments"])} for item in fragments.values()]
    safe_usage = {k: usage[k] for k in ["prompt_tokens", "completion_tokens", "total_tokens", "cost", "completion_tokens_details", "prompt_tokens_details"] if k in usage}
    return {"ok": finish in ("stop", "tool_calls") and bool(calls or text),
            "finish_reason": finish, "first_text_s": first_text, "first_tool_s": first_tool,
            "tool_ready_s": ready, "total_s": time.perf_counter() - start,
            "provider_reported": provider, "model_reported": model,
            "usage": safe_usage, "calls": calls, "text": text}


def load_key(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Arquivo da chave ausente ou inválido.")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("O arquivo da chave precisa de permissão 600.")
    key = path.read_text().strip()
    if not key.startswith("sk-or-") or any(c.isspace() for c in key):
        raise ValueError("A chave ainda não foi preenchida corretamente no arquivo privado.")
    return key


def configure_key(path):
    result = subprocess.run(["zenity", "--entry", "--hide-text", "--width=540",
        "--title=Teste da Emily — chave OpenRouter",
        "--text=Cole sua chave do OpenRouter aqui. Ela será salva apenas no arquivo privado local, sem aparecer no chat.\nO teste terá limite local de US$ 0,01.",
        "--ok-label=Salvar chave", "--cancel-label=Cancelar"],
        capture_output=True, text=True)
    if result.returncode != 0:
        print("Inserção cancelada; nenhuma chave alterada.")
        return
    key = result.stdout.strip()
    if not key.startswith("sk-or-") or any(c.isspace() for c in key):
        raise ValueError("Formato de chave inválido; nada foi salvo.")
    if path.is_symlink():
        raise ValueError("Caminho da chave inválido.")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(key + "\n")
    print("Chave salva no arquivo privado; conteúdo oculto.")


def key_budget(key_info):
    if key_info.get("is_management_key") or key_info.get("is_provisioning_key"):
        raise ValueError("Esta é uma chave administrativa do OpenRouter; ela não autoriza inferência. Use uma chave normal criada em Settings → API Keys.")
    remaining = key_info.get("limit_remaining")
    return min(CAP, Decimal(str(remaining)) * Decimal("0.9")) if remaining is not None else CAP


def run(key_path):
    key = load_key(key_path)
    OUT.mkdir(parents=True, exist_ok=True)
    destination = OUT / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    rows, reserved, charged = [], Decimal(0), Decimal(0)
    with httpx.Client(base_url="https://openrouter.ai/api/v1", timeout=httpx.Timeout(45, connect=10),
                      headers={"Authorization": "Bearer " + key, "X-OpenRouter-Title": "Emily Haiku benchmark"}) as client:
        auth = client.get("/key")
        if auth.status_code != 200:
            raise ValueError(f"OpenRouter recusou a chave: HTTP {auth.status_code}.")
        key_info = auth.json().get("data", {})
        budget = key_budget(key_info)
        print(f"Chave validada; orçamento local máximo de reservas: US$ {budget:.6f}.", flush=True)
        catalog = client.get("/models/anthropic/claude-haiku-5.5/endpoints")
        if catalog.status_code != 200:
            raise ValueError("Não foi possível conferir preço e provedor antes do teste.")
        endpoints = catalog.json().get("data", {}).get("endpoints", [])
        eligible = [e for e in endpoints if e.get("tag") == "anthropic"
                    and Decimal(str(e["pricing"]["prompt"])) <= INPUT_PRICE
                    and Decimal(str(e["pricing"]["completion"])) <= OUTPUT_PRICE]
        if not eligible:
            raise ValueError("Anthropic/Haiku 5.5 indisponível no preço autorizado; nenhuma geração feita.")
        for index, case in enumerate(CASES):
            for effort in (["low", "medium"] if index % 2 == 0 else ["medium", "low"]):
                body = payload(case, effort)
                bound = reserve(body)
                if max(reserved, charged) + bound > budget:
                    print("Limite preventivo atingido; nenhuma chamada adicional.", flush=True)
                    return
                reserved += bound  # Even failed/timed-out calls retain their reservation.
                try:
                    result = measure(client, body)
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    result = {"ok": False, "error": type(exc).__name__}
                if result["ok"]:
                    result["correct"] = score(case, result["calls"], result["text"])
                cost = result.get("usage", {}).get("cost")
                if isinstance(cost, (int, float)) and cost >= 0:
                    charged += Decimal(str(cost))
                row = {"case": case[0], "effort_requested": effort, "model_requested": MODEL, **result}
                rows.append(row)
                destination.write_text(json.dumps({"budget_usd": str(budget), "reserved_usd": str(reserved),
                    "reported_cost_usd": str(charged), "rows": rows}, ensure_ascii=False, indent=2))
                print(json.dumps({k: row.get(k) for k in ["case", "effort_requested", "ok", "correct", "tool_ready_s", "first_text_s", "total_s", "error"]}), flush=True)
                if not result["ok"] or (cost is not None and Decimal(str(cost)) > bound):
                    print("Teste interrompido após falha ou custo inesperado; sem repetição automática.", flush=True)
                    return


def self_test():
    import tempfile
    call = {"name": "acao_simulada", "arguments": CASES[0][3]}
    assert score(CASES[0], [call], "")
    assert not score(CASES[2], [call], "")
    assert score(CASES[5], [], "Você paga R$102,00.")
    assert key_budget({"limit_remaining": 0.01}) == Decimal("0.009")
    try:
        key_budget({"is_management_key": True})
        raise AssertionError("Chave administrativa aceita")
    except ValueError:
        pass
    for case in CASES:
        assert reserve(payload(case, "medium")) > 0
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "key"
        path.write_text("sk-or-synthetic-test-only")
        path.chmod(0o600)
        assert load_key(path).startswith("sk-or-")
        path.chmod(0o644)
        try:
            load_key(path)
            raise AssertionError("Permissão insegura aceita")
        except ValueError:
            pass
    event = {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {
        "name": "acao_simulada", "arguments": json.dumps(CASES[0][3])}}]}, "finish_reason": "tool_calls"}],
        "provider": "Anthropic", "model": MODEL, "usage": {"cost": 0.0001}}
    def mock(request):
        return httpx.Response(200, content=("data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n").encode())
    with httpx.Client(base_url="https://example.invalid", transport=httpx.MockTransport(mock)) as client:
        result = measure(client, payload(CASES[0], "low"))
        assert result["ok"] and result["calls"] == [call]
        assert result["tool_ready_s"] is not None
    with httpx.Client(base_url="https://example.invalid", transport=httpx.MockTransport(
            lambda request: httpx.Response(402, json={"error": "synthetic"}))) as client:
        result = measure(client, payload(CASES[0], "low"))
        assert not result["ok"] and result["error"] == "HTTP 402"
    assert sum(reserve(payload(c, e)) for c in CASES for e in ("low", "medium")) < CAP * Decimal("0.9")
    print("Self-test OK: intenção, negação, cálculo, segredo e captura SSE simulada.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    group.add_argument("--configure-key", action="store_true")
    parser.add_argument("--key-file", type=Path, default=KEY_PATH)
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.configure_key:
            configure_key(args.key_file)
        else:
            run(args.key_file)
    except (ValueError, OSError, httpx.HTTPError) as exc:
        # Do not print network exception details: they may contain request data.
        print(str(exc) if isinstance(exc, ValueError) else f"Falha: {type(exc).__name__}.")
        raise SystemExit(1)

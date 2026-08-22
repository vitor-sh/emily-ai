"""
Task 1 — qual profileArn funciona nesta conta.

A varredura local achou dois ARNs de perfil. Só a chamada real diz qual é o
ativo. Este script, para cada candidato:

  1. grava PROFILE_ARN no kiro_gateway/.env
  2. sobe o gateway como subprocesso e espera o /health
  3. faz uma chamada de 8 tokens
  4. derruba o gateway

Ao fim, deixa no .env o ARN que funcionou.

O valor do ARN nunca é impresso inteiro: o número da conta sai mascarado.

Este script também é ensaio do que a Task 3 vai fazer de verdade no
gateway.py — subir, esperar health, derrubar.

Uso:
    python _teste_arn_qual_funciona.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

RAIZ = Path(__file__).resolve().parent
PASTA_GATEWAY = RAIZ / "kiro_gateway"
ENV_GATEWAY = PASTA_GATEWAY / ".env"
ARQUIVO_ARNS = RAIZ / "_arn_encontrado.txt"

URL = os.getenv("EMILY_KIRO_URL", "http://127.0.0.1:8000")
CHAVE = os.getenv("KIRO_PROXY_API_KEY")

# Modelo que ESTÁ na lista da conta. Aqui o alvo é validar o ARN, não o modelo.
MODELO_TESTE = "claude-sonnet-4.5"

TIMEOUT_BOOT = 60.0
CREATE_NO_WINDOW = 0x08000000


def mascarar(arn: str) -> str:
    return re.sub(r":(\d{12}):", ":<conta>:", arn)


def gravar_profile_arn(arn: str) -> None:
    """Escreve ou substitui a linha PROFILE_ARN do .env do gateway."""
    texto = ENV_GATEWAY.read_text(encoding="utf-8")
    linha = f'PROFILE_ARN="{arn}"'
    if re.search(r"^\s*#?\s*PROFILE_ARN\s*=.*$", texto, flags=re.MULTILINE):
        texto = re.sub(r"^\s*#?\s*PROFILE_ARN\s*=.*$", linha, texto, flags=re.MULTILINE)
    else:
        texto = texto.rstrip("\n") + (
            "\n\n# ── Perfil do CodeWhisperer ──────────────────────────────────────\n"
            "# Conta Enterprise/IdC: o arquivo de credencial do Kiro IDE não traz\n"
            "# profileArn, e o runtime exige. Descoberto por _teste_achar_arn.py.\n"
            f"{linha}\n"
        )
    ENV_GATEWAY.write_text(texto, encoding="utf-8")


def esta_no_ar(timeout: float = 1.5) -> bool:
    try:
        return httpx.get(f"{URL}/health", timeout=timeout).status_code == 200
    except httpx.RequestError:
        return False


def subir_gateway():
    return subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=str(PASTA_GATEWAY),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def esperar_health(processo) -> bool:
    limite = time.monotonic() + TIMEOUT_BOOT
    while time.monotonic() < limite:
        if processo.poll() is not None:
            return False
        if esta_no_ar():
            return True
        time.sleep(0.4)
    return False


def derrubar(processo) -> None:
    if processo.poll() is not None:
        return
    processo.terminate()
    try:
        processo.wait(timeout=8)
    except subprocess.TimeoutExpired:
        processo.kill()
        processo.wait(timeout=5)


def sondar() -> tuple[bool, str]:
    from openai import OpenAI

    cliente = OpenAI(base_url=f"{URL}/v1", api_key=CHAVE, timeout=90.0)
    try:
        resposta = cliente.chat.completions.create(
            model=MODELO_TESTE,
            messages=[{"role": "user", "content": "Responda apenas com a palavra OK."}],
            max_tokens=8,
            stream=False,
        )
    except Exception as e:
        texto = str(e)
        return False, texto[:300]

    conteudo = (resposta.choices[0].message.content or "").strip()
    if not conteudo:
        motivo = getattr(resposta.choices[0], "finish_reason", "?")
        return False, f"conteudo vazio (finish_reason={motivo})"
    return True, conteudo[:60]


def principal() -> int:
    if not CHAVE:
        print("ERRO: KIRO_PROXY_API_KEY ausente no .env da Emily.")
        return 1
    if not ARQUIVO_ARNS.exists():
        print(f"ERRO: {ARQUIVO_ARNS.name} nao existe. Rode _teste_achar_arn.py antes.")
        return 1

    candidatos = [l.strip() for l in ARQUIVO_ARNS.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not candidatos:
        print("ERRO: nenhum ARN no arquivo.")
        return 1

    if esta_no_ar():
        print("ERRO: ja tem algo respondendo na porta do gateway.")
        print("Derrube o gateway antes de rodar este teste.")
        return 1

    print("=" * 74)
    print("TASK 1 - QUAL profileArn FUNCIONA")
    print("=" * 74)
    print(f"modelo de teste: {MODELO_TESTE}  (esta na lista da conta)")
    print(f"candidatos: {len(candidatos)}")
    print()

    vencedor = None

    for indice, arn in enumerate(candidatos, start=1):
        print(f"[{indice}] {mascarar(arn)}")
        gravar_profile_arn(arn)
        processo = subir_gateway()
        try:
            if not esperar_health(processo):
                saida = ""
                if processo.stdout:
                    try:
                        saida = processo.stdout.read()[-500:]
                    except Exception:
                        pass
                print(f"    gateway nao subiu. cauda do log: {saida.strip()[:300]}")
                continue

            ok, detalhe = sondar()
            if ok:
                print(f"    FUNCIONA  resposta={detalhe!r}")
                vencedor = arn
            else:
                print(f"    falhou    {detalhe}")
        finally:
            derrubar(processo)
            # Espera a porta liberar antes do próximo candidato.
            for _ in range(20):
                if not esta_no_ar():
                    break
                time.sleep(0.3)
        print()

        if vencedor:
            break

    print("=" * 74)
    if vencedor:
        gravar_profile_arn(vencedor)
        print("RESULTADO: ARN ativo encontrado e gravado no kiro_gateway/.env:")
        print(f"  {mascarar(vencedor)}")
        print()
        print("Pode apagar o _arn_encontrado.txt agora.")
        return 0

    print("RESULTADO: nenhum dos ARNs funcionou.")
    print("Possibilidades: conta Enterprise exige outro perfil, ou o token expirou.")
    return 1


if __name__ == "__main__":
    raise SystemExit(principal())

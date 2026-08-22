"""
Setup único do .env do gateway e das chaves novas no .env da Emily.

Gera a senha do proxy aqui dentro de propósito: ela nunca passa pela linha de
comando, pelo log do shell nem pela saída do terminal. Só os nomes das chaves
são impressos, nunca os valores.

Rodar uma vez. Se o .env do gateway já existir, não sobrescreve.
"""

from __future__ import annotations

import secrets
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ENV_GATEWAY = RAIZ / "kiro_gateway" / ".env"
ENV_EMILY = RAIZ / ".env"

MODELO_ENV_GATEWAY = """\
# Configuração do kiro-gateway para uso pela Emily.
# Gerado por _setup_gateway_env.py — não versionar este arquivo.

# Senha DESTE proxy local. Inventada, não vem de lugar nenhum.
# O .env da Emily usa o mesmo valor sob o nome KIRO_PROXY_API_KEY.
PROXY_API_KEY="{senha}"

# Credencial do Kiro IDE. O gateway carrega sozinho o outro arquivo
# de cache (o de nome com hash) que fica na mesma pasta.
KIRO_CREDS_FILE="~/.aws/sso/cache/kiro-auth-token.json"

# ── Servidor ──────────────────────────────────────────────────────
# 127.0.0.1 em vez do default 0.0.0.0: o default expõe a conta paga do
# Kiro para a rede local, protegida apenas por esta senha.
SERVER_HOST="127.0.0.1"
SERVER_PORT="8000"

# ── Ajustes críticos para a Emily ─────────────────────────────────
# Nenhum destes é o default do gateway. Os quatro têm motivo medido.

# Injeta thinking tags e devolve reasoning_content, campo que o
# _iterar_stream do llm.py ignora. Ligado, é só latência e token queimado.
FAKE_REASONING=false

# Ligado, injeta a tool web_search em TODA requisição, mesmo sem tools do
# cliente. Se o modelo usar, o resumo da busca sai como texto e o TTS da
# Emily leria isso em voz alta. A Emily já tem o pesquisa.py.
WEB_SEARCH_ENABLED=false

# A Kiro API rejeita payload acima de ~615KB. O orçamento de histórico da
# Emily é 120k tokens (~420KB) mais até 80KB de página fixada, então uma
# conversa longa chega perto do teto. Aparar é melhor que falhar.
AUTO_TRIM_PAYLOAD=true

# Quanto esperar o PRIMEIRO token antes de considerar a requisição travada.
# O default do gateway é 15s, e 15s derrubava requisição que ia dar certo: com
# resultado de ferramenta grande no prompt (a lista de 32 mods de um modpack,
# uma análise de pack inteira) o Claude leva mais que isso pra começar a
# escrever. O sintoma era a Emily muda por minutos no Discord com o
# "digitando..." ligado, e no log 'No response within 15.0 seconds' repetido.
FIRST_TOKEN_TIMEOUT="60"

# E o gateway não repete sozinho. Quem repete é o llm.py, que tem backoff,
# limitador de taxa e orçamento de tempo. Com 3 aqui, cada tentativa do llm.py
# valia 3 do gateway: 12 idas ao provedor por pedido, e minutos de silêncio.
FIRST_TOKEN_MAX_RETRIES="1"

# ── Log ───────────────────────────────────────────────────────────
# O console é compartilhado com os prints da Emily.
LOG_LEVEL="WARNING"
"""

CHAVES_EMILY = """
# ─────────────────────────────────────────────────────────────────
# KIRO GATEWAY — migração das rotas de LLM (spec migracao-llm-kiro-gateway)
# ─────────────────────────────────────────────────────────────────
# Mesmo valor do PROXY_API_KEY do kiro_gateway/.env. Nome diferente de
# propósito: o subprocesso herda o ambiente da Emily, e uma chave homônima
# venceria silenciosamente o .env do gateway.
KIRO_PROXY_API_KEY="{senha}"

# Escolhe a tabela de rotas: kiro ou nvidia. Caminho de reversão.
EMILY_PROVEDOR_LLM="kiro"

# Base do proxy local.
EMILY_KIRO_URL="http://127.0.0.1:8000"

# Timeout do SDK. Maior que os 90s antigos porque as rotas de visão mandam
# imagem base64 e casa com o STREAMING_READ_TIMEOUT do gateway.
EMILY_KIRO_TIMEOUT="300"

# Balde do limitador do provedor kiro. O plano pago não publica RPM;
# 30 é margem, não medição.
EMILY_KIRO_RPM="30"
"""


def principal() -> int:
    if not ENV_GATEWAY.parent.exists():
        print(f"ERRO: pasta do gateway não encontrada: {ENV_GATEWAY.parent}")
        return 1

    senha = secrets.token_urlsafe(32)

    # ── .env do gateway ──
    if ENV_GATEWAY.exists():
        print(f"[gateway] {ENV_GATEWAY.name} já existe, não vou sobrescrever.")
        print("[gateway] Se quiser regerar, apague o arquivo e rode de novo.")
        return 2

    ENV_GATEWAY.write_text(MODELO_ENV_GATEWAY.format(senha=senha), encoding="utf-8")
    print(f"[gateway] criado: {ENV_GATEWAY}")
    print("[gateway] chaves: PROXY_API_KEY, KIRO_CREDS_FILE, SERVER_HOST, SERVER_PORT,")
    print("[gateway]         FAKE_REASONING, WEB_SEARCH_ENABLED, AUTO_TRIM_PAYLOAD,")
    print("[gateway]         FIRST_TOKEN_TIMEOUT, FIRST_TOKEN_MAX_RETRIES, LOG_LEVEL")

    # ── .env da Emily ──
    if not ENV_EMILY.exists():
        print(f"ERRO: {ENV_EMILY} não existe. Chaves da Emily não foram gravadas.")
        return 1

    atual = ENV_EMILY.read_text(encoding="utf-8")
    if "KIRO_PROXY_API_KEY" in atual:
        print("[emily] KIRO_PROXY_API_KEY já presente. Nada alterado no .env da Emily.")
        print("[emily] ATENÇÃO: confira à mão se o valor bate com o PROXY_API_KEY do gateway.")
        return 0

    sufixo = "" if atual.endswith("\n") else "\n"
    with ENV_EMILY.open("a", encoding="utf-8") as arquivo:
        arquivo.write(sufixo + CHAVES_EMILY.format(senha=senha))

    print(f"[emily] chaves acrescentadas em: {ENV_EMILY}")
    print("[emily] chaves: KIRO_PROXY_API_KEY, EMILY_PROVEDOR_LLM, EMILY_KIRO_URL,")
    print("[emily]         EMILY_KIRO_TIMEOUT, EMILY_KIRO_RPM")
    print()
    print("Senha do proxy gerada e gravada nos dois arquivos. Nenhum valor foi impresso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())

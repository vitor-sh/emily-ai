"""
Task 1 — inspeção da credencial do Kiro.

Imprime APENAS os nomes das chaves presentes em cada arquivo de cache e o
comprimento dos valores. Nenhum token, refresh token ou segredo é impresso.

A única exceção é 'profileArn' e 'region': o ARN é identificador de recurso,
não credencial, e é exatamente o que o erro do gateway está pedindo. Mesmo
assim, o ARN sai com o número da conta mascarado.

Uso:
    python _teste_credencial.py
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

CACHE = Path(os.environ["USERPROFILE"]) / ".aws" / "sso" / "cache"

# Chaves cujo valor NUNCA é impresso.
SEGREDOS = {
    "accessToken", "refreshToken", "clientSecret", "idToken",
    "clientId", "clientIdHash", "registrationClientSecret",
}


def _mascarar_arn(arn: str) -> str:
    """arn:aws:codewhisperer:us-east-1:123456789012:profile/ABC -> conta mascarada."""
    return re.sub(r":(\d{12}):", ":<conta-mascarada>:", arn)


def inspecionar(caminho: Path) -> None:
    print(f"  {caminho.name}")
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"    ERRO ao ler: {e}")
        return

    if not isinstance(dados, dict):
        print(f"    formato inesperado: {type(dados).__name__}")
        return

    for chave in sorted(dados):
        valor = dados[chave]
        if chave in SEGREDOS:
            tamanho = len(str(valor)) if valor else 0
            print(f"    {chave:<28} presente ({tamanho} chars, não impresso)")
        elif chave == "profileArn":
            print(f"    {chave:<28} {_mascarar_arn(str(valor))}")
        else:
            print(f"    {chave:<28} {valor}")

    print()
    tem_arn = bool(dados.get("profileArn"))
    tem_client = bool(dados.get("clientId")) and bool(dados.get("clientSecret"))
    print(f"    -> profileArn presente:            {tem_arn}")
    print(f"    -> clientId+clientSecret presente: {tem_client}  "
          f"({'fluxo AWS SSO/OIDC' if tem_client else 'fluxo Kiro Desktop'})")
    print()


def principal() -> int:
    print("=" * 74)
    print("TASK 1 - ESTRUTURA DA CREDENCIAL DO KIRO")
    print("=" * 74)
    print(f"pasta: {CACHE}")
    print()

    if not CACHE.exists():
        print("ERRO: pasta de cache do AWS SSO nao existe.")
        return 1

    arquivos = sorted(CACHE.glob("*.json"))
    if not arquivos:
        print("ERRO: nenhum arquivo .json na pasta de cache.")
        return 1

    for caminho in arquivos:
        inspecionar(caminho)

    print("=" * 74)
    print("O gateway respondeu 400 'profileArn is required for this request'.")
    print("Se nenhum arquivo acima tem profileArn, ele precisa ir para o")
    print("PROFILE_ARN do kiro_gateway/.env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())

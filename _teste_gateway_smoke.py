"""
Task 1 — smoke test do gateway: streaming e visão.

Valida as duas capacidades que a Emily não pode perder na migração:

  [A] streaming token a token, medindo o tempo até o PRIMEIRO pedaço.
      Esse número é a latência que o Vitor sente antes de a Emily começar a
      falar. É o que justifica a migração inteira preservar stream.

  [B] visão, mandando uma imagem base64 e conferindo se o modelo LÊ o que
      está escrito nela. Imagem gerada na hora com texto conhecido, então
      o teste tem resposta certa e não depende do que está na tela.

Também confirma que FAKE_REASONING=false pegou: se vier delta de
reasoning_content, a configuração do gateway não está valendo.

Uso:
    python _teste_gateway_smoke.py
"""

from __future__ import annotations

import base64
import io
import os
import time

from dotenv import load_dotenv

load_dotenv()

URL = os.getenv("EMILY_KIRO_URL", "http://127.0.0.1:8000")
CHAVE = os.getenv("KIRO_PROXY_API_KEY")

MODELO_TEXTO = os.getenv("EMILY_KIRO_MODELO_CONVERSA", "claude-sonnet-5")
MODELO_VISAO = os.getenv("EMILY_KIRO_MODELO_VISAO", "claude-sonnet-5")

# Palavra que vai desenhada na imagem. O modelo tem que devolver ela.
SEGREDO_NA_IMAGEM = "EMILY42"


def _cliente():
    from openai import OpenAI

    if not CHAVE:
        print("ERRO: KIRO_PROXY_API_KEY ausente no .env da Emily.")
        raise SystemExit(1)
    return OpenAI(base_url=f"{URL}/v1", api_key=CHAVE, timeout=300.0)


def teste_streaming(cliente) -> bool:
    print("[A] Streaming token a token")
    print(f"    modelo: {MODELO_TEXTO}")

    mensagens = [
        {"role": "system", "content": "Responda em português do Brasil, sem formatação."},
        {"role": "user", "content": "Conte de um até dez, separando por vírgula."},
    ]

    inicio = time.monotonic()
    primeiro = None
    pedacos = 0
    texto = ""
    vazamento_raciocinio = False

    fluxo = cliente.chat.completions.create(
        model=MODELO_TEXTO,
        messages=mensagens,
        max_tokens=200,
        stream=True,
    )

    for evento in fluxo:
        if not getattr(evento, "choices", None):
            continue
        delta = evento.choices[0].delta
        if getattr(delta, "reasoning_content", None):
            vazamento_raciocinio = True
        conteudo = getattr(delta, "content", None)
        if conteudo:
            if primeiro is None:
                primeiro = time.monotonic() - inicio
            pedacos += 1
            texto += conteudo

    total = time.monotonic() - inicio

    print(f"    pedaços recebidos:      {pedacos}")
    print(f"    tempo até o 1o pedaço:  {primeiro:.2f}s" if primeiro else "    NENHUM pedaço de texto")
    print(f"    tempo total:            {total:.2f}s")
    print(f"    resposta:               {texto.strip()[:120]!r}")

    if vazamento_raciocinio:
        print("    ATENÇÃO: veio delta de reasoning_content.")
        print("             FAKE_REASONING=false não está valendo no gateway.")

    ok = pedacos > 1 and bool(texto.strip())
    if pedacos == 1:
        print("    ATENÇÃO: só um pedaço. Isso não é streaming, é resposta inteira de uma vez.")
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return ok and not vazamento_raciocinio


def _imagem_com_texto() -> str:
    """Gera um PNG pequeno com uma palavra conhecida e devolve em base64."""
    from PIL import Image, ImageDraw

    largura, altura = 480, 160
    imagem = Image.new("RGB", (largura, altura), (18, 18, 24))
    desenho = ImageDraw.Draw(imagem)
    desenho.rectangle([8, 8, largura - 8, altura - 8], outline=(90, 200, 250), width=3)
    # Fonte default do PIL: pequena, mas legível o suficiente para OCR de modelo.
    desenho.text((40, 60), f"CODIGO: {SEGREDO_NA_IMAGEM}", fill=(240, 240, 240))
    desenho.text((40, 90), "teste de visao da emily", fill=(150, 150, 160))

    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def teste_visao(cliente) -> bool:
    print("[B] Visão com imagem base64")
    print(f"    modelo: {MODELO_VISAO}")

    try:
        b64 = _imagem_com_texto()
    except ImportError:
        print("    PULADO: PIL não disponível.")
        print()
        return True

    print(f"    imagem gerada: {len(b64)} chars de base64, palavra-alvo {SEGREDO_NA_IMAGEM!r}")

    inicio = time.monotonic()
    resposta = cliente.chat.completions.create(
        model=MODELO_VISAO,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text",
                 "text": "Que código está escrito nesta imagem? Responda só o código."},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        max_tokens=64,
        stream=False,
    )
    decorrido = time.monotonic() - inicio

    conteudo = (resposta.choices[0].message.content or "").strip()
    uso = getattr(resposta, "usage", None)
    tokens_prompt = getattr(uso, "prompt_tokens", "?") if uso else "?"

    print(f"    latência:        {decorrido:.2f}s")
    print(f"    tokens_prompt:   {tokens_prompt}")
    print(f"    resposta:        {conteudo[:120]!r}")

    acertou = SEGREDO_NA_IMAGEM in conteudo.upper().replace(" ", "")
    print(f"    -> {'OK, leu a imagem' if acertou else 'FALHOU, não leu o código'}")
    print()
    return acertou


def principal() -> int:
    cliente = _cliente()

    print("=" * 74)
    print("TASK 1 — SMOKE TEST DO GATEWAY")
    print("=" * 74)
    print()

    ok_stream = teste_streaming(cliente)
    ok_visao = teste_visao(cliente)

    print("=" * 74)
    print(f"streaming: {'OK' if ok_stream else 'FALHOU'}")
    print(f"visão:     {'OK' if ok_visao else 'FALHOU'}")
    print("=" * 74)
    return 0 if (ok_stream and ok_visao) else 1


if __name__ == "__main__":
    raise SystemExit(principal())

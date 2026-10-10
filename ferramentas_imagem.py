"""
ferramentas_imagem.py — Criação de imagens da Emily (GPT Image).

Por que este módulo existe
──────────────────────────
A Emily ganhou acesso a um modelo de imagem da família GPT Image (o mesmo
estilo do ChatGPT), via API compatível com OpenAI Images. Aqui é a camada de
acesso — o padrão é o do github_api.py: lê as credenciais do .env, monta as
chamadas REST e devolve textos prontos. A decisão de QUANDO usar é da
ferramenta criar_imagem, que este módulo registra no catálogo do ferramentas.py
(via _registrar_catalogo_imagem). Quem arquiteta a imagem é o modelo de texto:
o esquema da ferramenta já manda escrever um prompt rico em detalhes.

Configuração — tudo no .env; sem isto a ferramenta EXISTE, entra na mesa e
recusa com a instrução de configuração (o modelo explica ao Vitor o que falta)
────────────────────────────────────────────────────────────────────────────
  EMILY_IMAGE_URL       Base da API. Ex.: https://api.openai.com/v1
                        O endpoint final vira {base}/images/generations —
                        se a base já termina em /v1 ou em /images/generations,
                        é respeitada do jeito que está.
  EMILY_IMAGE_API_KEY   Chave enviada como Bearer.
  EMILY_IMAGE_MODELO    Nome do modelo. Padrão: gpt-image-2.0.
  EMILY_IMAGE_TIMEOUT   Segundos até desistir. Padrão: 300 (imagem é lenta).
  EMILY_IMAGE_PASTA     Onde salvar. Padrão: imagens_emily (relativo à raiz).

Fluxo na interface
──────────────────
Gerar imagem demora dezenas de segundos e a API não expõe progresso real.
A interface recebe o evento 'imagem_progresso' em três momentos — inicio,
pronta e erro — e é ELA que anima a barra (avanço lento + brilho). A imagem
final chega pelo contrato existente (mostrar_opcao_salvar → card com
Salvar/Descartar). Sem interface (chat do Discord, testes), os avisos são
silenciosos e nada quebra: a ferramenta gera e salva do mesmo jeito.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

DIR_BASE = Path(__file__).resolve().parent

URL_BASE = os.getenv("EMILY_IMAGE_URL", "").strip()
API_KEY = os.getenv("EMILY_IMAGE_API_KEY", "").strip()
MODELO = (os.getenv("EMILY_IMAGE_MODELO") or "gpt-image-2.0").strip()
TIMEOUT = float(os.getenv("EMILY_IMAGE_TIMEOUT", "300") or 300)
PASTA = (os.getenv("EMILY_IMAGE_PASTA") or "imagens_emily").strip()

# Formatos que o modelo de imagem aceita. Qualquer outra coisa cai no padrão.
TAMANHOS = ("1024x1024", "1536x1024", "1024x1536", "auto")
_QUALIDADE = {"baixa": "low", "media": "medium", "alta": "high"}


class ErroImagem(Exception):
    """Erro da API de imagem com mensagem pronta pro modelo retransmitir."""


def configurado() -> bool:
    return bool(URL_BASE and API_KEY)


def _instrucao_config() -> str:
    return (
        "A criação de imagem não está configurada. Peça ao Vitor para "
        "preencher EMILY_IMAGE_URL e EMILY_IMAGE_API_KEY no .env e reiniciar "
        "a Emily. Não tente de novo nesta sessão."
    )


def _endpoint() -> str:
    """A base do .env vira o endpoint completo sem surpresa."""
    u = URL_BASE.rstrip("/")
    if u.endswith("/images/generations"):
        return u
    if u.endswith("/v1"):
        return f"{u}/images/generations"
    return f"{u}/v1/images/generations"


# ═════════════════════════════════════════════════════════════════
# PONTE COM A INTERFACE
#
# A ferramenta roda dentro do laço de ferramentas, em thread dele. A janela
# ativa é alcançável por interface_web._api_ativa() — o MESMO caminho que o
# _perguntar_ao_vitor do Emily Code usa. Tudo guardado: sem interface, os
# avisos não existem e a geração continua funcionando.
# ═════════════════════════════════════════════════════════════════

def _janela():
    try:
        import interface_web
        api = interface_web._api_ativa()
        return getattr(api, "_j", None) if api is not None else None
    except Exception:  # noqa: BLE001
        return None


def _avisar_ui(dados: dict) -> None:
    """Empurra o evento 'imagem_progresso' pra interface. Falha calada."""
    j = _janela()
    if j is None or not hasattr(j, "_push"):
        return
    try:
        j._push("imagem_progresso", dados)
    except Exception as e:  # noqa: BLE001
        print(f"[IMAGEM] aviso de progresso falhou: {e}")


# ═════════════════════════════════════════════════════════════════
# GERAÇÃO
# ═════════════════════════════════════════════════════════════════

def _mensagem_de_erro(resp: requests.Response) -> str:
    """Traduz o status da API numa frase que o modelo entende e retransmite."""
    detalhe = ""
    try:
        corpo = resp.json()
        erro = corpo.get("error")
        detalhe = erro.get("message") if isinstance(erro, dict) else str(erro or "")
    except ValueError:
        detalhe = (resp.text or "")[:200]
    detalhe = (detalhe or "").strip()
    if resp.status_code in (401, 403):
        return (f"A API de imagem recusou a credencial ({resp.status_code}). "
                f"Confere EMILY_IMAGE_API_KEY no .env. {detalhe}").strip()
    if resp.status_code == 404:
        return (f"Endpoint de imagem não encontrado (404). Confere "
                f"EMILY_IMAGE_URL no .env. {detalhe}").strip()
    if resp.status_code == 429:
        return f"Limite de uso da API de imagem atingido (429). {detalhe}".strip()
    return f"A API de imagem falhou ({resp.status_code}). {detalhe}".strip()


def gerar(prompt: str, tamanho: str = "1024x1024",
          qualidade: str = "") -> str:
    """
    Pede a imagem, salva em disco e avisa a interface. Devolve o caminho.

    Levanta ErroImagem com mensagem pronta pro modelo retransmitir. A UI é
    avisada ANTES da chamada (é o que faz o cartão de progresso aparecer já
    no primeiro segundo) e no fim, seja lá como acabar.
    """
    if not configurado():
        raise ErroImagem(_instrucao_config())

    prompt = (prompt or "").strip()
    if not prompt:
        raise ErroImagem("O pedido de imagem veio sem descrição nenhuma.")

    tamanho = tamanho if tamanho in TAMANHOS else "1024x1024"
    id_geracao = str(int(time.time() * 1000))
    resumo = " ".join(prompt.split())[:80]

    _avisar_ui({"fase": "inicio", "id": id_geracao,
                "prompt": resumo, "tamanho": tamanho})

    corpo = {"model": MODELO, "prompt": prompt, "n": 1, "size": tamanho}
    q = _QUALIDADE.get((qualidade or "").strip().lower())
    if q:
        corpo["quality"] = q

    try:
        resp = requests.post(
            _endpoint(),
            json=corpo,
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        motivo = f"Não consegui falar com a API de imagem: {e}"
        _avisar_ui({"fase": "erro", "id": id_geracao, "erro": str(e)})
        raise ErroImagem(motivo) from e

    if resp.status_code != 200:
        motivo = _mensagem_de_erro(resp)
        _avisar_ui({"fase": "erro", "id": id_geracao, "erro": motivo})
        raise ErroImagem(motivo)

    # Formatos aceitos: b64_json (padrão OpenAI Images) ou url (gateway que
    # hospeda o arquivo). O que vier, baixa e vira PNG em disco.
    erro_json = ""
    item: dict = {}
    try:
        item = (resp.json().get("data") or [{}])[0]
    except ValueError as e:
        erro_json = f"a resposta não é JSON ({e})"

    bruto: Optional[bytes] = None
    if item.get("b64_json"):
        try:
            bruto = base64.b64decode(item["b64_json"])
        except Exception as e:  # noqa: BLE001
            erro_json = f"a imagem veio corrompida ({e})"
    elif item.get("url"):
        try:
            bruto = requests.get(item["url"], timeout=60).content
        except requests.RequestException as e:
            erro_json = f"não consegui baixar a imagem hospedada: {e}"
    else:
        erro_json = erro_json or "a API respondeu sem imagem nenhuma"

    if not bruto:
        motivo = f"A resposta da API não trouxe imagem utilizável: {erro_json}"
        _avisar_ui({"fase": "erro", "id": id_geracao, "erro": motivo})
        raise ErroImagem(motivo)

    pasta = Path(PASTA) if os.path.isabs(PASTA) else DIR_BASE / PASTA
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / time.strftime("emily_%Y%m%d_%H%M%S.png")
    caminho.write_bytes(bruto)

    _avisar_ui({"fase": "pronta", "id": id_geracao, "caminho": str(caminho)})
    # A imagem chega no chat pelo contrato que já existe: card com a imagem
    # e os botões Salvar/Descartar (o mesmo que o fluxo antigo usava).
    j = _janela()
    if j is not None and hasattr(j, "mostrar_opcao_salvar"):
        try:
            j.mostrar_opcao_salvar(str(caminho))
        except Exception as e:  # noqa: BLE001
            print(f"[IMAGEM] mostrar_opcao_salvar falhou: {e}")

    return str(caminho)


# ═════════════════════════════════════════════════════════════════
# FERRAMENTA
#
# registrar_tudo(registrar, Ferramenta) — MESMA fábrica dos catálogos de
# Discord e autonomia: o ferramentas.py passa a própria fábrica, a dependência
# é de mão única e não existe ciclo de importação.
# ═════════════════════════════════════════════════════════════════

def registrar_tudo(registrar, Ferramenta) -> int:
    """Registra criar_imagem no catálogo. Devolve quantas entraram."""
    registrar(Ferramenta(
        nome="criar_imagem",
        descricao=(
            "Cria uma imagem do zero a partir de uma descrição (mesma família "
            "do GPT Image do ChatGPT) e mostra no chat. Use quando o Vitor "
            "pedir pra criar, desenhar, pintar ou gerar imagem: arte, "
            "figurinha, logo, wallpaper, ilustração. Escreva o prompt como "
            "uma descrição RICA da cena: o que aparece, o estilo (realista, "
            "anime, pixel art, aquarela...), a iluminação, as cores e o "
            "enquadramento. Gera UM arquivo salvo em disco; a imagem aparece "
            "pra ele com botão de salvar."
        ),
        propriedades={
            "prompt": {
                "type": "string",
                "description": (
                    "Descrição detalhada da imagem: cena, estilo, iluminação, "
                    "cores e enquadramento."
                ),
            },
            "tamanho": {
                "type": "string",
                "enum": list(TAMANHOS),
                "description": (
                    "Formato: 1024x1024 quadrada, 1536x1024 paisagem, "
                    "1024x1536 retrato, auto deixa o modelo decidir. "
                    "Padrão: 1024x1024."
                ),
            },
            "qualidade": {
                "type": "string",
                "enum": ["baixa", "media", "alta"],
                "description": "Qualidade do render. Padrão: a da API.",
            },
        },
        obrigatorios=["prompt"],
        aviso="Boa, deixa comigo — vou pintar essa imagem agora.",
        grupo="geral",   # sempre na mesa: criar imagem é habilidade de chat
        executar=_criar_imagem,
    ))
    return 1


def _criar_imagem(prompt: str, tamanho: str = "1024x1024",
                  qualidade: str = "") -> str:
    """
    Corpo da ferramenta. Erro vira recusa estruturada (ok=False, mudou=False)
    com a razão — o modelo retransmite e orienta a configuração. Sucesso
    devolve o caminho; a imagem já foi empurrada pra interface por gerar().
    """
    import ferramentas  # tardio de propósito: ferramentas.py importa este módulo
    try:
        caminho = gerar(prompt, tamanho=tamanho, qualidade=qualidade)
    except ErroImagem as e:
        return ferramentas.recusa(f"Não consegui gerar a imagem: {e}")
    tamanho_txt = tamanho if tamanho in TAMANHOS else "1024x1024"
    return (
        f"Imagem criada ({tamanho_txt}) e salva em {caminho}. "
        f"Já apareceu no chat com botão de salvar — comente da imagem "
        f"naturalmente, não precisa repetir o caminho pro Vitor."
    )


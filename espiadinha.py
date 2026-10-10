"""
espiadinha.py — o comentário espontâneo da Emily.

Por que existe
──────────────
O Vitor pediu: de vez em quando, quando ela estiver aberta aí no PC, a Emily
dá uma espiadinha na aba que ele está olhando e comenta alguma coisa — só
pra fazer companhia, no jeitão dela. As regras que ele deixou claras:

  - BEM de vez em quando: intervalo aleatório de 25 a 150 minutos, e ainda
    assim ela pula ~1/3 dos ciclos. Pode passar horas sem acontecer nada.
  - Sem notificação, sem aviso, sem mensagem nova no chat: o comentário sai
    SÓ pela voz (voz.falar não toca na interface nem no histórico).
  - Desligável nas configurações da interface (toggle "Espiadinha", que
    grava a preferência e liga/desliga a thread em runtime).

Como funciona
─────────────
Uma thread daemon dorme um intervalo aleatório; ao acordar, checa se é hora
(modo ligado, Emily ociosa, extensão conectada), lê a aba ATIVA do Vitor
(url + título + começo do texto) — read-only e com bastidor FORÇADO para
off, porque aqui queremos exatamente a página que ELE está vendo — e pede
ao cérebro um comentário curto. Qualquer etapa que falhe, ela fica quieta
e espera o próximo ciclo.

Privacidade: só título, URL e um trecho do texto vão pro modelo. Nada é
guardado em disco, nada entra no histórico de conversa.
"""

from __future__ import annotations

import random
import threading
import time

# Janela de intervalo entre espiadinhas, em minutos. Alto de propósito:
# o pedido foi "bem de vez em quando mesmo, pode demorar muitoooo".
_MIN_MINUTOS = 25
_MAX_MINUTOS = 150

# Chance de acordar, olhar pro lado e voltar a dormir sem comentar.
_CHANCE_DE_PULAR = 0.35

# Tamanho do trecho de página que vai pro modelo. O comentário é sobre a
# impressão geral, não precisa da página inteira.
_LIMITE_TEXTO = 1500

_iniciada = threading.Event()
_ativa = threading.Event()


def ativa() -> bool:
    """O modo está ligado agora (runtime, não só a preferência)."""
    return _ativa.is_set()


def definir_ativa(valor: bool) -> None:
    """Liga/desliga em runtime. A preferência quem grava é o interface_web."""
    if valor:
        _ativa.set()
    else:
        _ativa.clear()
    print(f"[ESPIADINHA] modo {'LIGADO' if valor else 'DESLIGADO'}")


def _ociosa() -> bool:
    """Emily livre pra comentar? Nunca interrompe nada em andamento."""
    try:
        import modelo
        if getattr(modelo, "aguardando_resposta", False):
            return False
    except Exception:
        pass
    try:
        import voz
        if voz.falar_ativo.is_set():
            return False
    except Exception:
        pass
    return True


def _pagina_do_vitor() -> dict:
    """A aba ATIVA dele. Bastidor FORÇADO pra off nos dois comandos: a
    injeção automática do navegador.py só adiciona o flag quando ele ainda
    não veio — passando False de propósito, os comandos vão pra aba que o
    Vitor está olhando de verdade, mesmo com o modo bastidor ligado."""
    import navegador
    if not navegador.esta_conectado():
        return {}
    r_url = navegador.enviar_comando_com_id(
        "obter_url_atual", timeout=8.0, bastidor=False)
    url = ((r_url or {}).get("url") or "").strip()
    if not url.startswith("http"):
        # Página interna do navegador, aba em branco, extensão sem aba: nada
        # a comentar (e nada que ele queira que ela veja).
        return {}
    r_pag = navegador.enviar_comando_com_id(
        "ler_pagina", timeout=15.0, bastidor=False)
    if not r_pag or r_pag.get("tipo") == "erro":
        return {}
    return {
        "url": url,
        "titulo": (r_pag.get("titulo") or "").strip(),
        "texto": (r_pag.get("texto") or "").strip()[:_LIMITE_TEXTO],
    }


def _comentar(pagina: dict) -> None:
    """Gera o comentário com a personalidade dela e fala. voz.falar não
    encosta na interface nem no histórico — é exatamente o contrato pedido."""
    from modelo import comentario_espontaneo
    import voz
    comentario = comentario_espontaneo(
        pagina.get("titulo", ""), pagina.get("url", ""), pagina.get("texto", ""))
    if not comentario:
        return
    print(f"[ESPIADINHA] comentando: {comentario[:80]!r}")
    voz.falar(comentario)


def _laco() -> None:
    while True:
        # Dorme o intervalo em pedaços curtos: o modo pode ser desligado
        # nas configurações no meio da espera.
        fim = time.monotonic() + random.uniform(_MIN_MINUTOS * 60,
                                                _MAX_MINUTOS * 60)
        while time.monotonic() < fim:
            time.sleep(15)
        try:
            if not _ativa.is_set():
                continue
            if random.random() < _CHANCE_DE_PULAR:
                continue
            if not _ociosa():
                continue
            pagina = _pagina_do_vitor()
            if not pagina or len(pagina.get("texto", "")) < 80:
                continue
            _comentar(pagina)
        except Exception as e:
            print(f"[ESPIADINHA] ciclo falhou (fica pra próxima): {e}")


def iniciar() -> None:
    """Sobe a thread daemon. Chamado pelo main.py na inicialização. Se a
    preferência salva dizia ligado, já começa ativa."""
    if _iniciada.is_set():
        return
    _iniciada.set()
    try:
        import preferencias
        if bool(preferencias.obter("espiadinha", False)):
            _ativa.set()
    except Exception:
        pass
    threading.Thread(target=_laco, daemon=True,
                     name="EmilyEspiadinha").start()
    print(f"[ESPIADINHA] Thread iniciada "
          f"({'ligada' if _ativa.is_set() else 'desligada'} nas preferências).")

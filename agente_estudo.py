"""
agente_estudo.py — Agente que responde questões em plataformas de estudo.

Como funciona:
  1. Captura screenshot + texto da página aberta no navegador
  2. Manda pro modelo de IA analisar a questão
  3. Clica na resposta correta ou digita ela
  4. Aguarda a próxima questão carregar
  5. Repete até terminar ou ser parado

Dependências: pip install anthropic
Variável necessária: ANTHROPIC_API_KEY no .env
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Callable, Optional

import anthropic
import navegador

# ─── Cliente Anthropic ────────────────────────────────────────────────────────

_cliente: Optional[anthropic.Anthropic] = None

def _obter_cliente() -> anthropic.Anthropic:
    global _cliente
    if _cliente is None:
        _cliente = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    return _cliente


# ─── Estado do agente ─────────────────────────────────────────────────────────

_rodando  = threading.Event()  # True enquanto o agente está ativo
_pausado  = threading.Event()  # True quando pausado temporariamente
_thread: Optional[threading.Thread] = None
_cb_falar: Optional[Callable[[str], None]] = None  # função voz.falar do main.py

_total_respondidas = 0
_total_erros       = 0


# ─── Configurações ────────────────────────────────────────────────────────────

INTERVALO_ENTRE_QUESTOES = 2.5  # segundos de espera entre uma questão e outra
MAX_ERROS_SEGUIDOS       = 5    # para automaticamente após N erros em sequência
LIMITE_TEXTO_PAGINA      = 3500 # máximo de caracteres do texto da página enviados pro modelo


# ─── Prompts do modelo ────────────────────────────────────────────────────────

_SYSTEM = (
    "Você é um assistente especializado em responder questões de plataformas de estudo. "
    "Responda sempre em JSON puro, sem markdown e sem texto fora do JSON. "
    "Escolha a resposta mais correta com base no conteúdo acadêmico. "
    "Seja preciso e objetivo."
)

_PROMPT = """\
Analise esta página de plataforma de estudos:

--- TEXTO DA PÁGINA ---
{texto}
--- FIM ---

Responda SOMENTE com este JSON (NADA fora do JSON, sem ```, sem explicações):
{{
    "tem_questao": true,
    "questao": "enunciado completo da questão aqui",
    "tipo": "multipla_escolha",
    "opcoes": ["A. texto da opção A", "B. texto da opção B", "C. texto C"],
    "resposta": "texto EXATO da opção correta como aparece na página",
    "letra": "A",
    "justificativa": "motivo em 1 frase curta",
    "botao_avancar": "texto do botão para avançar (ex: Próxima, Confirmar) ou string vazia",
    "pagina_finalizada": false
}}

TIPOS POSSÍVEIS:
  multipla_escolha  → várias opções para clicar (A, B, C, D...)
  verdadeiro_falso  → só Verdadeiro ou Falso para clicar
  texto_livre       → campo de texto para digitar a resposta
  sem_questao       → página de introdução, loading, ou resultado final

REGRAS IMPORTANTES:
- "resposta" deve ser o texto EXATAMENTE como aparece na opção — vou usar isso pra clicar nela
- Se não tiver questão visível ainda, use "tem_questao": false
- Se a atividade terminou (placar final, parabéns, nota), use "pagina_finalizada": true
- Para verdadeiro_falso, "resposta" deve ser "Verdadeiro" ou "Falso"
- "botao_avancar" é o botão que aparece APÓS responder para ir para a próxima questão\
"""


# ─── Funções internas ─────────────────────────────────────────────────────────

def _falar(texto: str) -> None:
    """Fala usando o callback de voz do main.py (se disponível)."""
    if _cb_falar:
        try:
            _cb_falar(texto)
        except Exception:
            pass
    print(f"[ESTUDO] {texto}")


def _analisar_pagina(
    texto_pagina: str,
    screenshot_b64: Optional[str] = None,
) -> Optional[dict]:
    """
    Envia o conteúdo da página pro modelo de IA.
    Retorna um dict com a questão, resposta e ação a executar.
    """
    try:
        # Monta o conteúdo da mensagem (imagem + texto)
        conteudo: list = []

        # Screenshot ajuda quando a questão tem imagens ou formatação visual
        if screenshot_b64:
            conteudo.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_b64,
                },
            })

        conteudo.append({
            "type": "text",
            "text": _PROMPT.format(texto=texto_pagina[:LIMITE_TEXTO_PAGINA]),
        })

        resposta = _obter_cliente().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=_SYSTEM,
            messages=[{"role": "user", "content": conteudo}],
        )

        raw = resposta.content[0].text.strip()

        # Remove backticks caso o modelo tenha colocado mesmo sendo pedido pra não colocar
        raw = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()

        return json.loads(raw)

    except json.JSONDecodeError as e:
        print(f"[ESTUDO] JSON inválido recebido do modelo: {e}")
        try:
            print(f"[ESTUDO] Texto recebido: {raw[:300]}")
        except Exception:
            pass
        return None
    except Exception as e:
        print(f"[ESTUDO] Erro ao chamar modelo: {e}")
        return None


def _executar_resposta(dados: dict) -> bool:
    """
    Executa a ação na página: clica na opção correta ou digita a resposta.
    Tenta múltiplas estratégias caso a primeira falhe.
    Retorna True se conseguiu executar.
    """
    tipo     = dados.get("tipo", "multipla_escolha")
    resposta = dados.get("resposta", "").strip()
    letra    = dados.get("letra", "").strip()
    botao    = dados.get("botao_avancar", "").strip()

    if not resposta:
        print("[ESTUDO] Nenhuma resposta para executar.")
        return False

    sucesso = False

    # ── Questão de múltipla escolha ou Verdadeiro/Falso ──────────────────────
    if tipo in ("multipla_escolha", "verdadeiro_falso"):

        # Tentativa 1: texto completo da opção (ex: "A. Fotossíntese")
        r = navegador.clicar_por_texto(resposta)
        sucesso = bool(r and r.get("sucesso"))

        # Tentativa 2: só a letra (A, B, C, D...)
        if not sucesso and letra:
            r2 = navegador.clicar_opcao_resposta(letra)
            sucesso = bool(r2 and r2.get("sucesso"))

        # Tentativa 3: texto sem a letra no início (ex: "Fotossíntese" sem o "A.")
        if not sucesso:
            sem_letra = re.sub(r"^[A-Ea-e][.)]\s*", "", resposta).strip()
            if sem_letra and sem_letra != resposta:
                r3 = navegador.clicar_por_texto(sem_letra)
                sucesso = bool(r3 and r3.get("sucesso"))

    # ── Campo de texto para digitar a resposta ────────────────────────────────
    elif tipo == "texto_livre":
        r = navegador.digitar_resposta(resposta)
        sucesso = bool(r and r.get("sucesso"))

    # ── Tipo desconhecido: tenta clicar pelo texto ────────────────────────────
    else:
        r = navegador.clicar_por_texto(resposta)
        sucesso = bool(r and r.get("sucesso"))

    # ── Clica no botão de avançar (Próxima, Confirmar, Verificar...) ─────────
    if botao:
        time.sleep(0.8)  # pequena pausa antes de avançar
        r_botao = navegador.clicar_por_texto(botao)

        # Se não achou o botão específico, tenta os mais comuns
        if not r_botao or not r_botao.get("sucesso"):
            for alternativa in (
                "Próxima", "Próximo", "Confirmar", "Verificar",
                "Avançar", "OK", "Continue", "Next", "Enviar",
            ):
                r_alt = navegador.clicar_por_texto(alternativa)
                if r_alt and r_alt.get("sucesso"):
                    break

    return sucesso


def _loop(objetivo: str) -> None:
    """
    Loop principal do agente:
    lê a página → manda pro modelo → clica na resposta → aguarda → repete.
    """
    global _total_respondidas, _total_erros

    _total_respondidas = 0
    _total_erros       = 0
    erros_seguidos     = 0
    hash_anterior      = ""

    _falar("Beleza Vitor! Vou começar a responder as questões agora.")

    while _rodando.is_set():

        # Fica em espera se estiver pausado
        if _pausado.is_set():
            time.sleep(0.5)
            continue

        try:
            # ── 1. Lê o estado atual da página ───────────────────────────────

            screenshot   = navegador.screenshot_aba(timeout=10.0)
            dados_pagina = navegador.ler_pagina(timeout=8.0)

            if not dados_pagina:
                erros_seguidos += 1
                if erros_seguidos >= MAX_ERROS_SEGUIDOS:
                    _falar(
                        "Não consigo ler a página, Vitor. "
                        "Verifica se o navegador está aberto na plataforma!"
                    )
                    break
                time.sleep(2)
                continue

            texto = dados_pagina.get("texto", "")

            if len(texto) < 50:
                time.sleep(2)
                continue

            # ── 2. Evita processar a mesma página duas vezes ──────────────────

            # Usa os primeiros 300 caracteres como "impressão digital" da página
            hash_atual = texto[:300]
            if hash_atual == hash_anterior:
                time.sleep(1.5)
                continue
            hash_anterior = hash_atual

            # ── 3. Manda pro modelo analisar ──────────────────────────────────

            print(f"[ESTUDO] Analisando questão #{_total_respondidas + 1}...")
            resultado = _analisar_pagina(texto, screenshot)

            if not resultado:
                erros_seguidos += 1
                time.sleep(2)
                continue

            erros_seguidos = 0

            # ── 4. Verifica se a atividade terminou ───────────────────────────

            if resultado.get("pagina_finalizada"):
                _falar(f"Terminei Vitor! Respondi {_total_respondidas} questões no total.")
                break

            if not resultado.get("tem_questao"):
                print("[ESTUDO] Nenhuma questão detectada na página atual.")
                erros_seguidos += 1
                if erros_seguidos >= 3:
                    _falar(
                        "Não estou vendo questões na tela, Vitor. "
                        "Abre o exercício na plataforma!"
                    )
                    break
                time.sleep(2)
                continue

            erros_seguidos = 0

            # ── 5. Mostra no terminal o que foi detectado ─────────────────────

            q         = resultado.get("questao", "")[:100]
            resp_txt  = resultado.get("resposta", "")
            letra_txt = resultado.get("letra", "")
            motivo    = resultado.get("justificativa", "")

            print(f"\n[ESTUDO] ─────────────────────────────────────────────")
            print(f"         #{_total_respondidas + 1}: {q}")
            print(f"         Resposta: {letra_txt} — {resp_txt[:60]}")
            print(f"         Motivo: {motivo}")
            print(f"[ESTUDO] ─────────────────────────────────────────────\n")

            # Fala em voz alta na 1ª questão e a cada 5 depois
            if _total_respondidas % 5 == 0:
                _falar(
                    f"Questão {_total_respondidas + 1}: "
                    f"{letra_txt or resp_txt[:25]}. {motivo}"
                )

            # ── 6. Executa a ação na página ───────────────────────────────────

            time.sleep(0.4)  # pausa rápida antes de clicar (parece mais humano)
            sucesso = _executar_resposta(resultado)

            if sucesso:
                _total_respondidas += 1
            else:
                _total_erros += 1
                print(f"[ESTUDO] Não conseguiu clicar — {_total_erros} erros de clique no total.")

            # ── 7. Aguarda a próxima questão carregar ─────────────────────────

            time.sleep(INTERVALO_ENTRE_QUESTOES)

        except Exception as e:
            print(f"[ESTUDO] Erro no loop: {e}")
            erros_seguidos += 1
            time.sleep(2)

    _rodando.clear()
    print(
        f"[ESTUDO] Agente encerrado. "
        f"Respondidas: {_total_respondidas} | Erros de clique: {_total_erros}"
    )


# ─── API pública (usada pelo main.py) ────────────────────────────────────────

def iniciar_agente_estudo(
    objetivo: str = "",
    callback_falar: Optional[Callable] = None,
) -> str:
    """
    Inicia o agente de estudos em uma thread separada.
    
    Parâmetros:
        objetivo        → descrição opcional da tarefa ("responde o quiz de biologia")
        callback_falar  → função de voz para falar os comentários (normalmente voz.falar)
    
    Retorna uma string com a mensagem de início (ou erro).
    """
    global _thread, _cb_falar

    if not navegador.esta_conectado():
        return (
            "A extensão do navegador não está conectada, Vitor. "
            "Abre o Chrome ou Brave com a extensão da Emily ativada!"
        )

    if _rodando.is_set():
        return "O agente de estudos já está rodando, Vitor!"

    _cb_falar = callback_falar
    _rodando.set()
    _pausado.clear()

    _thread = threading.Thread(
        target=_loop,
        args=(objetivo,),
        daemon=True,
        name="AgenteEstudo",
    )
    _thread.start()

    return "Iniciando! Vou dar uma olhada nas questões e já começo a responder."


def pausar_agente_estudo() -> str:
    """Pausa o agente temporariamente sem perder o progresso."""
    if not _rodando.is_set():
        return "O agente não está rodando, Vitor."
    _pausado.set()
    return f"Pausei! Respondi {_total_respondidas} até agora. Fala quando quiser continuar."


def retomar_agente_estudo() -> str:
    """Retoma o agente após uma pausa."""
    if not _rodando.is_set():
        return "O agente não está rodando, Vitor."
    _pausado.clear()
    return "Continuando as questões!"


def parar_agente_estudo() -> str:
    """Para o agente definitivamente."""
    _rodando.clear()
    _pausado.clear()
    return f"Parei! Respondi {_total_respondidas} questões no total, Vitor."


def status_agente_estudo() -> str:
    """Retorna o status atual: 'rodando', 'pausado' ou 'parado'."""
    if not _rodando.is_set():
        return "parado"
    return "pausado" if _pausado.is_set() else "rodando"


def obter_estatisticas() -> dict:
    """Retorna um resumo da sessão atual."""
    return {
        "respondidas": _total_respondidas,
        "erros_clique": _total_erros,
        "status": status_agente_estudo(),
    }

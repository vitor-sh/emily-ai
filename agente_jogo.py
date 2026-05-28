"""
agente_jogo.py — Emily joga jogos usando visão de tela + IA

Como funciona:
1. Tira print da tela
2. Manda pro modelo de visão perguntando quais teclas apertar
3. Executa as teclas
4. Repete (loop)

Limitação: cada ciclo demora ~0.5s a 2s, então é melhor pra jogos
mais lentos ou com tempo de reação mais folgado.
"""

from __future__ import annotations

import base64
import json
import os
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

# ─── Importa o cliente de IA que você já usa no projeto ───
from openai import OpenAI

_client = OpenAI(
    api_key="fw_82xEAw4SVwqcHziwGxEPvb",
    base_url="https://api.fireworks.ai/inference/v1",
)

# ─── Tenta importar o módulo de teclado ───
try:
    import keyboard as _kb
    _KB_DISPONIVEL = True
except ImportError:
    _KB_DISPONIVEL = False
    print("[AGENTE] Módulo 'keyboard' não encontrado. Rode: pip install keyboard")

# ─────────────────────────────────────────────────────────────────
# ESTADO GLOBAL DO AGENTE
# ─────────────────────────────────────────────────────────────────

_agente_ativo    = False           # True = agente rodando
_agente_pausado  = threading.Event()  # set = rodando, clear = pausado
_agente_parar    = threading.Event()  # set = parar loop
_agente_thread: Optional[threading.Thread] = None
_agente_jogo_atual = ""            # nome do jogo que está sendo jogado

# Callback pra atualizar status na interface da Emily (opcional)
_callback_status = None

def definir_callback_status(cb):
    global _callback_status
    _callback_status = cb

# ─────────────────────────────────────────────────────────────────
# CAPTURA DE TELA
# ─────────────────────────────────────────────────────────────────

def _capturar_tela_base64(monitor: int = 1) -> Optional[str]:
    """
    Tira um print do monitor especificado e retorna em base64.
    Tenta usar o módulo visao.py do projeto primeiro.
    Se não conseguir, usa mss diretamente.
    """
    # Tenta usar o visao.py do projeto
    try:
        from visao import capturar_tela
        img_bytes = capturar_tela(monitor)
        if img_bytes:
            return base64.b64encode(img_bytes).decode("utf-8")
    except Exception:
        pass

    # Fallback: usa mss diretamente
    try:
        import mss
        import mss.tools
        import io

        with mss.mss() as sct:
            # monitor 0 = todos os monitores juntos, 1 em diante = individual
            mon = sct.monitors[monitor] if monitor < len(sct.monitors) else sct.monitors[1]
            screenshot = sct.grab(mon)

            # Converte pra PNG em memória
            from PIL import Image
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")

    except Exception as e:
        print(f"[AGENTE] Erro ao capturar tela: {e}")
        return None

# ─────────────────────────────────────────────────────────────────
# DECISÃO DE TECLAS COM IA
# ─────────────────────────────────────────────────────────────────

# Prompts por jogo — você pode adicionar mais aqui!
_PROMPTS_POR_JOGO = {
    "celeste": """
Você é um especialista em Celeste jogando no teclado. Analise a tela e retorne
uma sequência LONGA de ações para Madeline avançar.

═══ MECÂNICAS IMPORTANTES ═══
- Pulo (c): Madeline pula. No ar, pode pular uma vez mais se tiver estamina.
- Dash (x): Dash rápido na direção que estiver segurando. Só pode dar 1 dash
  por vez no ar — recarrega ao tocar o chão ou pegar cristal azul.
- Agarrar (z): Segura em paredes. Consome estamina (barra verde).
- Dash diagonal: segure direção diagonal (ex: right+up) e pressione x.
- Pulo de parede: enquanto agarra (z), pressione c para pular da parede.
- Coyote jump: pode pular por ~0.1s depois de sair de uma plataforma.

═══ COMO LER A TELA ═══
- Madeline: personagem pequeno com cabelo vermelho/roxo.
- Espinhos brancos: morte instantânea ao tocar.
- Cristais azuis brilhantes: recarregam o dash ao tocar.
- Plataformas que se movem: blocos que oscilam — espere o momento certo.
- Sinal verde com seta: indica a direção do objetivo.

═══ SEQUÊNCIAS COMUNS ═══
Correr e pular um abismo:
  segurar right 0.4 → pressionar c → segurar right 0.5

Dash horizontal pra alcançar plataforma distante:
  segurar right 0.1 → pressionar x → segurar right 0.3

Dash pra cima de um espinho:
  combo [up, x] duracao 0.1 → segurar right 0.3 → pressionar c

Subir parede:
  segurar z 0.1 → segurar up 0.3 (enquanto agarra) → pressionar c

Dash diagonal pra cima-direita:
  combo [right, up, x] duracao 0.1 → esperar 0.2

═══ REGRAS OBRIGATÓRIAS ═══
1. Retorne SEMPRE entre 10 e 20 ações — nunca menos que 10!
2. "duracao" e "tempo" são SEMPRE números decimais (0.1, 0.3, 0.5)
3. NUNCA mande duracao maior que 1.0 — vai travar o personagem
4. Coloque esperar 0.08 entre a maioria das ações
5. Se ver espinhos à frente: use dash (x) pra passar por cima
6. Se ver abismo: corra (segurar right) e pule (c) no momento certo
7. Se a Madeline estiver parada no mesmo lugar há vários ciclos: tente
   uma abordagem diferente (dash, pulo de parede, subir)

═══ RESPONDA APENAS JSON ═══
{
  "analise": "posição da Madeline + obstáculos visíveis + plano de ação",
  "teclas": [
    {"tipo": "segurar", "tecla": "right", "duracao": 0.4},
    {"tipo": "esperar", "tempo": 0.08},
    {"tipo": "pressionar", "tecla": "c"},
    {"tipo": "esperar", "tempo": 0.08},
    {"tipo": "segurar", "tecla": "right", "duracao": 0.4},
    {"tipo": "esperar", "tempo": 0.08},
    {"tipo": "pressionar", "tecla": "x"},
    {"tipo": "esperar", "tempo": 0.08},
    {"tipo": "segurar", "tecla": "right", "duracao": 0.3},
    {"tipo": "esperar", "tempo": 0.08}
  ]
}
""",

    "minecraft": """
Você está olhando pra tela do Minecraft (visão em primeira pessoa).
Analise o terreno, blocos, entidades visíveis e o inventário (se aparecer).
Decida as próximas ações pra sobreviver/construir.

Controles:
- Mover: w (frente), a (esquerda), s (trás), d (direita)
- Pular: space
- Correr: ctrl (segurando) + w
- Atacar/Destruir: mouse esquerdo (use "mouse_left")
- Usar/Colocar: mouse direito (use "mouse_right")
- Inventário: e
- Agachar: shift

RESPONDA APENAS com JSON, sem texto extra:
{
  "analise": "o que você vê na tela em 1 frase",
  "teclas": [
    {"tipo": "segurar", "tecla": "w", "duracao": 0.5}
  ]
}
""",

    "generico": """
Você está olhando pra tela de um jogo.
Analise o que aparece na tela e decida quais teclas apertar pra avançar.

Teclas comuns em jogos:
- Setas: right, left, up, down
- Ações: z, x, c, space, shift, enter
- Movimento WASD: w, a, s, d

RESPONDA APENAS com JSON, sem texto extra:
{
  "analise": "o que você vê na tela em 1 frase",
  "teclas": [
    {"tipo": "pressionar", "tecla": "right"}
  ]
}

Tipos disponíveis: pressionar, segurar (com duracao), soltar, esperar (com tempo), combo (com teclas lista)
"""
}

# Jogos que o sistema reconhece por nome
_ALIASES_JOGO = {
    "celeste": "celeste",
    "minecraft": "minecraft",
    "terraria": "generico",
    "hollow knight": "hollow_knight",
    "stardew": "generico",
}


def _pegar_prompt_do_jogo(nome_jogo: str) -> str:
    """Retorna o prompt certo pro jogo. Se não conhecer, usa o genérico."""
    nome_norm = nome_jogo.lower().strip()
    chave = _ALIASES_JOGO.get(nome_norm, nome_norm)
    return _PROMPTS_POR_JOGO.get(chave, _PROMPTS_POR_JOGO["generico"])


def _decidir_teclas(imagem_b64: str, nome_jogo: str) -> Optional[dict]:
    """
    Manda o print pro modelo de visão e recebe as teclas a apertar.
    Retorna um dict com "analise" e "teclas", ou None se falhar.
    """
    prompt = _pegar_prompt_do_jogo(nome_jogo)

    try:
        resposta = _client.chat.completions.create(
            model="accounts/fireworks/models/kimi-k2p6",  # modelo com visão
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{imagem_b64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ],
            extra_body={"reasoning_effort": "none"},
        )



        texto = resposta.choices[0].message.content or ""
        print(f"[AGENTE] Resposta bruta do modelo: {texto[:300]}")
        texto = re.sub(r"```json|```", "", texto).strip()

        # Tenta extrair o JSON da resposta
        match = re.search(r"\{.*\}", texto, re.DOTALL)
        if match:
            return json.loads(match.group(0))

    except Exception as e:
        print(f"[AGENTE] Erro ao consultar modelo: {e}")

    return None

# ─────────────────────────────────────────────────────────────────
# EXECUÇÃO DAS TECLAS
# ─────────────────────────────────────────────────────────────────


def _limpar_numero(valor, padrao: float) -> float:
    """Converte qualquer valor pra float, removendo letras como '0.3s'."""
    try:
        return float(str(valor).replace("s", "").replace(",", ".").strip())
    except (ValueError, TypeError):
        return padrao


def _executar_teclas(teclas: list, nome_jogo: str = "") -> None:
    if not _KB_DISPONIVEL:
        print("[AGENTE] Teclado não disponível!")
        return

    for passo in teclas:
        if _agente_parar.is_set():
            break
        _agente_pausado.wait()

        tipo = passo.get("tipo", "")

        try:
            if tipo == "pressionar":
                tecla = passo.get("tecla", "")
                if tecla:
                    _kb.press(tecla)
                    time.sleep(0.1)
                    _kb.release(tecla)
                    time.sleep(0.05)

            elif tipo == "segurar":
                tecla   = passo.get("tecla", "")
                duracao = _limpar_numero(passo.get("duracao", 0.3), 0.3)
                if tecla:
                    _kb.press(tecla)
                    fim = time.time() + duracao
                    while time.time() < fim:
                        if _agente_parar.is_set():
                            break
                        time.sleep(0.02)
                    _kb.release(tecla)

            elif tipo == "soltar":
                tecla = passo.get("tecla", "")
                if tecla:
                    _kb.release(tecla)

            elif tipo == "esperar":
                tempo = _limpar_numero(passo.get("tempo", 0.1), 0.1)
                fim   = time.time() + tempo
                while time.time() < fim:
                    if _agente_parar.is_set():
                        break
                    time.sleep(0.02)

            elif tipo == "combo":
                teclas_combo = passo.get("teclas", [])
                duracao      = _limpar_numero(passo.get("duracao", 0.1), 0.1)
                for t in teclas_combo:
                    _kb.press(t)
                time.sleep(duracao)
                for t in reversed(teclas_combo):
                    _kb.release(t)
                time.sleep(0.05)

        except Exception as e:
            print(f"[AGENTE] Erro ao executar tecla ({tipo}): {e}")

# ─────────────────────────────────────────────────────────────────
# LOOP PRINCIPAL DO AGENTE
# ─────────────────────────────────────────────────────────────────

def _loop_agente(nome_jogo: str, monitor: int, intervalo: float) -> None:
    """
    Roda em thread separada.
    Ciclo: captura tela → decide teclas → executa → espera → repete
    """
    global _agente_ativo, _agente_jogo_atual

    print(f"[AGENTE] Iniciando agente para '{nome_jogo}' no monitor {monitor}")

    ciclo = 0
    while not _agente_parar.is_set():
        # Respeita pausa
        _agente_pausado.wait()
        if _agente_parar.is_set():
            break

        ciclo += 1
        print(f"[AGENTE] Ciclo {ciclo} — capturando tela...")

        if _callback_status:
            _callback_status("analisando_jogo")

        # 1. Captura a tela
        imagem = _capturar_tela_base64(monitor)
        if not imagem:
            print("[AGENTE] ERRO: captura de tela retornou vazia!")
            time.sleep(1.0)
            continue

        print(f"[AGENTE] Tela capturada! Tamanho base64: {len(imagem)} caracteres")

        # 2. Manda pro modelo decidir as teclas
        resultado = _decidir_teclas(imagem, nome_jogo)
        if not resultado:
            print("[AGENTE] Modelo não retornou teclas válidas, tentando novamente...")
            time.sleep(0.5)
            continue

        analise = resultado.get("analise", "")
        teclas  = resultado.get("teclas", [])

        if analise:
            print(f"[AGENTE] Análise: {analise}")

        if not teclas:
            print("[AGENTE] Nenhuma tecla pra apertar nesse ciclo.")
            time.sleep(intervalo)
            continue

        print(f"[AGENTE] Executando {len(teclas)} ação(ões)...")

        # 3. Executa as teclas
        _executar_teclas(teclas, nome_jogo)

        # 4. Aguarda antes do próximo ciclo
        # (dá tempo do jogo processar e a tela atualizar)
        if not _agente_parar.is_set():
            time.sleep(intervalo)

    _agente_ativo      = False
    _agente_jogo_atual = ""
    print("[AGENTE] Agente encerrado.")

# ─────────────────────────────────────────────────────────────────
# FUNÇÕES PÚBLICAS (chamadas pelo automacao.py)
# ─────────────────────────────────────────────────────────────────

def iniciar_agente(nome_jogo: str = "generico", monitor: int = 1, intervalo: float = 4.0) -> str:
    """
    Inicia o agente de jogo.
    
    nome_jogo: qual jogo está na tela (afeta o prompt enviado ao modelo)
    monitor:   número do monitor (1 = principal)
    intervalo: segundos entre cada ciclo de decisão
    """
    global _agente_ativo, _agente_thread, _agente_jogo_atual

    if _agente_ativo:
        return f"Já tem um agente rodando pra '{_agente_jogo_atual}'! Para ele primeiro."

    if not _KB_DISPONIVEL:
        return "Preciso do módulo 'keyboard' pra isso. Rode: pip install keyboard"

    _agente_parar.clear()
    _agente_pausado.set()  # começa rodando (não pausado)
    _agente_ativo      = True
    _agente_jogo_atual = nome_jogo

    _agente_thread = threading.Thread(
        target=_loop_agente,
        args=(nome_jogo, monitor, intervalo),
        daemon=True,
    )
    _agente_thread.start()

    return (
        f"Agente iniciado pra '{nome_jogo}'! "
        f"Fala 'pausa o agente' pra pausar ou 'para o agente' pra encerrar."
    )


def pausar_agente() -> str:
    if not _agente_ativo:
        return "Não tem nenhum agente rodando agora, Vitor!"
    if not _agente_pausado.is_set():
        return "O agente já tá pausado!"
    _agente_pausado.clear()
    return "Agente pausado! Fala 'continua o agente' pra retomar."


def continuar_agente() -> str:
    if not _agente_ativo:
        return "Não tem nenhum agente ativo pra continuar, Vitor!"
    if _agente_pausado.is_set():
        return "O agente já tá rodando!"
    _agente_pausado.set()
    return "Agente retomado!"


def parar_agente() -> str:
    global _agente_ativo
    if not _agente_ativo:
        return "Não tem nenhum agente rodando, Vitor!"
    _agente_parar.set()
    _agente_pausado.set()  # libera o wait pra a thread terminar limpo
    _agente_ativo = False
    return "Agente encerrado!"


def status_agente() -> str:
    if not _agente_ativo:
        return "Nenhum agente ativo no momento."
    estado = "rodando" if _agente_pausado.is_set() else "pausado"
    return f"Agente '{_agente_jogo_atual}' está {estado}."
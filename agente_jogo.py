"""
agente_jogo.py — Emily joga jogos usando visão de tela + IA

Como funciona:
1. Tira print da tela
2. Manda pro modelo de visão perguntando quais teclas apertar
3. Executa as teclas
4. Repete (loop)

Agora usa o mesmo LLM do modelo.py (GPT-5.4 Pro via Azure Responses API).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

# ─── Importa o cliente de IA que você já usa no projeto ───
# Agora usamos o modelo.py centralizado, não criamos um cliente novo.
import modelo

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
    Usa o visao.py do projeto, que já redimensiona pra 1280x720 e
    comprime em JPEG.
    """
    try:
        import visao
        # Respeita o monitor escolhido (visao usa monitor_atual global)
        try:
            import mss
            with mss.mss() as sct:
                total_monitores = len(sct.monitors) - 1  # monitor 0 = todos
        except Exception:
            total_monitores = 1
        visao.monitor_atual = min(max(1, monitor), total_monitores)
        img_b64 = visao.capturar_tela()
        if img_b64:
            return img_b64
    except Exception as e:
        print(f"[AGENTE] Erro ao capturar tela via visao: {e}")
    return None

# ─────────────────────────────────────────────────────────────────
# HISTÓRICO DE AÇÕES (pra LLM não ficar repetindo)
# ─────────────────────────────────────────────────────────────────

MAX_HISTORICO = 8
_historico_acoes: list[str] = []


def _registrar_historico(analise: str, teclas: list) -> None:
    global _historico_acoes
    resumo = f"Ciclo: {analise[:120]} | Ações: {len(teclas)}"
    _historico_acoes.append(resumo)
    if len(_historico_acoes) > MAX_HISTORICO:
        _historico_acoes.pop(0)


def _historico_formatado() -> str:
    if not _historico_acoes:
        return "Nenhuma ação anterior registrada."
    return "\n".join(f"- {item}" for item in _historico_acoes[-MAX_HISTORICO:])

# ─────────────────────────────────────────────────────────────────
# PROMPTS POR JOGO
# ─────────────────────────────────────────────────────────────────

_PROMPTS_POR_JOGO = {
    "celeste": """Você é Emily, a IA do Vitor, e está jogando Celeste no teclado. Analise a tela e retorne um plano de ações precisas para Madeline avançar pela tela atual.

═══ CONTROLES DO CELESTE ═══
- Setas: left, right, up, down (movimento e direção do dash)
- c: pulo (jump)
- x: dash (único no ar até recarregar)
- z: agarrar/escalar parede (climb)
- Esc: pause/menu

═══ FUNDAMENTOS DE MECÂNICA (60 FPS = cada frame ~0.017s) ═══
- Dash: dura ~4 frames (~0.067s). Só 1 dash no ar. Recarrega ao tocar chão ou cristal azul.
- Pulo: segure c levemente (~0.05-0.10s) pra altura média; toque rápido pra pulo baixo.
- Coyote jump: pode pular por ~0.08-0.10s depois de sair de uma plataforma.
- Jump buffer: se apertar c 0.05s antes de tocar o chão, ela pula automaticamente.
- Wall jump: segure z encostada na parede + direção para cima da parede + c.
- Wall bounce: dash diagonal contra parede e pulo no impacto.
- Dash diagonal: segurar right+up (ou left+up) + x.
- Hyperdash: dash no chão + pulo no final do dash para correr rápido.
- Superdash: dash no chão + pulo no início para ganhar altura e distância.
- Wavedash: dash no chão, no último frame pula.
- Neutral jump: encostada na parede, solte direção horizontal e pule (sobe mais).

═══ COMO LER A TELA ═══
- Madeline: personagem pequena com cabelo vermelho/roxo.
- Espinhos brancos: morte instantânea ao tocar.
- Cristais azuis brilhantes: recarregam o dash ao tocar.
- Blocos de gelo/azul com neve: superfícies seguras.
- Plataformas móveis: blocos que se movem — sincronize o pulo/dash.
- Sinal verde com seta: indica a direção do objetivo.
- Buracos/abismos: geralmente precisam de pulo + dash.

═══ FORMATO DAS AÇÕES ═══
Cada item deve ser um JSON com:
- "tipo": "segurar" | "pressionar" | "soltar" | "esperar" | "combo"
- "teclas": lista de teclas (obrigatório para segurar/pressionar/soltar/combo)
- "duracao": tempo em segundos (para segurar e combo). MÁXIMO 0.5s.
- "tempo": tempo em segundos (para esperar). Use múltiplos de 0.017.

═══ REGRAS ABSOLUTAS ═══
1. Retorne ENTRE 12 e 24 ações por ciclo. Nunca menos que 12.
2. Prefira MUITAS ações curtas em sequência do que poucas ações longas.
3. "duracao" NUNCA pode ser maior que 0.5s. Use 0.017-0.10s na maioria.
4. "tempo" de espera NUNCA maior que 0.25s. Use 0.017-0.10s.
5. Para dashs e pulos, aperte as teclas SIMULTANEAMENTE usando "combo" com duracao 0.05-0.08s.
6. Para correr, segure right/left com duracao 0.10-0.30s.
7. Entre ações de movimento, coloque esperas de 0.017-0.05s para sincronizar frames.
8. Se Madeline estiver parada há vários ciclos: tente uma abordagem diferente (wall jump, dash diagonal, superdash).
9. NUNCA segure direção contrária por muito tempo enquanto cai em abismo.
10. Se a tela for difícil, divida em micro-sequências: aproximar → posicionar → executar.
11. Se houver espinhos logo abaixo: use dash diagonal ou pulo de parede, NÃO caia reto.
12. Se precisar subir uma parede: alterne z (escalar) + c (pulo) + direção para parede.
13. O objetivo é chegar à SAÍDA da tela (seta verde, portal, ou lado direito).

═══ EXEMPLOS DE SEQUÊNCIAS VÁLIDAS ═══
Correr e pular um abismo curto:
  segurar [right] duracao 0.15
  esperar 0.05
  combo [right, c] duracao 0.05
  segurar [right] duracao 0.20

Dash horizontal para plataforma distante:
  segurar [right] duracao 0.08
  combo [right, x] duracao 0.05
  segurar [right] duracao 0.25
  esperar 0.05

Dash diagonal para cima-direita:
  combo [right, up, x] duracao 0.05
  segurar [right] duracao 0.10
  esperar 0.05
  segurar [right] duracao 0.15

Subir parede (wall jump repetido):
  segurar [z, left] duracao 0.10
  combo [left, c] duracao 0.05
  esperar 0.05
  segurar [z, left] duracao 0.10
  combo [left, c] duracao 0.05

Hyperdash no chão:
  segurar [right] duracao 0.05
  combo [right, x] duracao 0.05
  combo [right, c] duracao 0.05
  segurar [right] duracao 0.20

═══ AÇÕES ANTERIORES (não repita exatamente se falhou) ═══
{historico}

═══ RESPONDA APENAS JSON ═══
{
  "analise": "posição da Madeline + obstáculos + plano em 1-2 frases",
  "teclas": [
    {"tipo": "segurar", "teclas": ["right"], "duracao": 0.15},
    {"tipo": "esperar", "tempo": 0.03},
    {"tipo": "combo", "teclas": ["right", "c"], "duracao": 0.05},
    {"tipo": "esperar", "tempo": 0.03},
    {"tipo": "segurar", "teclas": ["right"], "duracao": 0.20}
  ]
}
""",

    "minecraft": """Você está olhando pra tela do Minecraft (visão em primeira pessoa).
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

AÇÕES:
- tipo: segurar | pressionar | soltar | esperar | combo
- teclas: lista de teclas
- duracao: tempo em segundos (max 0.5s para segurar/combo)
- tempo: tempo em segundos para esperar (max 0.25s)

RESPONDA APENAS com JSON, sem texto extra:
{
  "analise": "o que você vê na tela em 1 frase",
  "teclas": [
    {"tipo": "segurar", "teclas": ["w"], "duracao": 0.5}
  ]
}
""",

    "generico": """Você está olhando pra tela de um jogo.
Analise o que aparece na tela e decida quais teclas apertar pra avançar.

Teclas comuns em jogos:
- Setas: right, left, up, down
- Ações: z, x, c, space, shift, enter
- Movimento WASD: w, a, s, d

AÇÕES:
- tipo: segurar | pressionar | soltar | esperar | combo
- teclas: lista de teclas
- duracao: tempo em segundos (max 0.5s para segurar/combo)
- tempo: tempo em segundos para esperar (max 0.25s)

RESPONDA APENAS com JSON, sem texto extra:
{
  "analise": "o que você vê na tela em 1 frase",
  "teclas": [
    {"tipo": "pressionar", "teclas": ["right"]}
  ]
}
"""
}

# Jogos que o sistema reconhece por nome
_ALIASES_JOGO = {
    "celeste": "celeste",
    "minecraft": "minecraft",
    "terraria": "generico",
    "hollow knight": "generico",
    "stardew": "generico",
}


def _pegar_prompt_do_jogo(nome_jogo: str) -> str:
    """Retorna o prompt certo pro jogo. Se não conhecer, usa o genérico."""
    nome_norm = nome_jogo.lower().strip()
    chave = _ALIASES_JOGO.get(nome_norm, nome_norm)
    prompt_base = _PROMPTS_POR_JOGO.get(chave, _PROMPTS_POR_JOGO["generico"])
    # Injeta o histórico no prompt do Celeste
    if chave == "celeste":
        return prompt_base.replace("{historico}", _historico_formatado())
    return prompt_base


# ─────────────────────────────────────────────────────────────────
# DECISÃO DE TECLAS COM IA
# ─────────────────────────────────────────────────────────────────

def _extrair_json(texto: str) -> Optional[dict]:
    """Extrai o primeiro objeto JSON válido do texto."""
    # Remove code blocks markdown
    texto = re.sub(r"```json|```", "", texto).strip()
    # Tenta encontrar objeto JSON
    for inicio, caractere in enumerate(texto):
        if caractere == "{":
            abertos = 0
            for fim in range(inicio, len(texto)):
                if texto[fim] == "{":
                    abertos += 1
                elif texto[fim] == "}":
                    abertos -= 1
                    if abertos == 0:
                        try:
                            return json.loads(texto[inicio:fim+1])
                        except json.JSONDecodeError:
                            break
    return None


def _system_prompt_jogo() -> str:
    """
    Monta o system prompt do agente de jogo com:
    - Personalidade principal da Emily (tsundere, jeito de ser)
    - Memória do Vitor (perfil, gostos, hábitos de jogo)
    Assim o agente conhece o jogador e mantém a identidade da Emily.
    """
    # ── Personalidade principal ──────────────────────────────────
    try:
        personalidade = modelo.EMILY_PERSONALIDADE.strip()
    except Exception:
        personalidade = "Você é Emily, a assistente pessoal do Vitor."

    # ── Memória do Vitor ─────────────────────────────────────────
    ctx_mem = ""
    try:
        import memoria as _mem
        ctx_mem = _mem.formatar_para_prompt()
    except Exception:
        pass

    instrucao_jogo = (
        "\n\nVocê está no MODO AGENTE DE JOGO. "
        "Analise a tela do jogo e responda APENAS com JSON válido contendo 'analise' e 'teclas'. "
        "Mantenha sua personalidade mas priorize decisões técnicas corretas de jogo."
    )

    partes = [personalidade]
    if ctx_mem:
        partes.append(ctx_mem)
    partes.append(instrucao_jogo)

    return "\n\n".join(partes)


def _decidir_teclas(imagem_b64: str, nome_jogo: str) -> Optional[dict]:
    """
    Manda o print pro modelo de visão e recebe as teclas a apertar.
    Retorna um dict com "analise" e "teclas", ou None se falhar.
    """
    prompt = _pegar_prompt_do_jogo(nome_jogo)

    try:
        # Usa o LLM centralizado do modelo.py (GPT-5.4 Pro via Azure Responses API)
        resposta = modelo._chamar_llm(
            [
                {"role": "system", "content": _system_prompt_jogo()},
                {"role": "user", "content": prompt, "images": [imagem_b64]},
            ],
            model=modelo.AZURE_DEPLOYMENT,
            max_tokens=2048,
            vision=True,
        )

        print(f"[AGENTE] Resposta bruta do modelo: {resposta[:400]}")

        decisao = _extrair_json(resposta)
        if decisao and isinstance(decisao.get("teclas"), list):
            return decisao

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
                teclas_lista = _normalizar_teclas(passo.get("teclas", passo.get("tecla", "")))
                for tecla in teclas_lista:
                    _kb.press(tecla)
                time.sleep(0.03)
                for tecla in teclas_lista:
                    _kb.release(tecla)
                time.sleep(0.02)

            elif tipo == "segurar":
                teclas_lista = _normalizar_teclas(passo.get("teclas", passo.get("tecla", "")))
                duracao = _limpar_numero(passo.get("duracao", 0.1), 0.1)
                duracao = min(duracao, 0.5)  # limite de segurança
                for tecla in teclas_lista:
                    _kb.press(tecla)
                fim = time.time() + duracao
                while time.time() < fim:
                    if _agente_parar.is_set():
                        break
                    time.sleep(0.005)
                for tecla in teclas_lista:
                    _kb.release(tecla)

            elif tipo == "soltar":
                teclas_lista = _normalizar_teclas(passo.get("teclas", passo.get("tecla", "")))
                for tecla in teclas_lista:
                    _kb.release(tecla)

            elif tipo == "esperar":
                tempo = _limpar_numero(passo.get("tempo", 0.05), 0.05)
                tempo = min(tempo, 0.25)  # limite de segurança
                fim = time.time() + tempo
                while time.time() < fim:
                    if _agente_parar.is_set():
                        break
                    time.sleep(0.005)

            elif tipo == "combo":
                teclas_lista = _normalizar_teclas(passo.get("teclas", passo.get("tecla", "")))
                duracao = _limpar_numero(passo.get("duracao", 0.05), 0.05)
                duracao = min(duracao, 0.5)
                for tecla in teclas_lista:
                    _kb.press(tecla)
                fim = time.time() + duracao
                while time.time() < fim:
                    if _agente_parar.is_set():
                        break
                    time.sleep(0.005)
                for tecla in teclas_lista:
                    _kb.release(tecla)
                time.sleep(0.02)

        except Exception as e:
            print(f"[AGENTE] Erro ao executar tecla ({tipo}): {e}")


def _normalizar_teclas(teclas) -> list[str]:
    """Converte qualquer entrada de teclas (string ou lista) em lista de strings."""
    if isinstance(teclas, list):
        return [str(t).strip() for t in teclas if str(t).strip()]
    if isinstance(teclas, str) and teclas.strip():
        return [teclas.strip()]
    return []

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

        # 3. Registra histórico e executa as teclas
        _registrar_historico(analise, teclas)
        _executar_teclas(teclas, nome_jogo)

        # 4. Aguarda antes do próximo ciclo
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

    # Limpa histórico ao iniciar novo jogo
    _historico_acoes.clear()

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

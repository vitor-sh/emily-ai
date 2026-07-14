"""
agente_ui.py
Agente de UI: controla o mouse e teclado via visão computacional.

Como funciona:
1. Recebe um objetivo em linguagem natural ("clica no botão Confirmar")
2. Captura a tela atual
3. Manda a tela + objetivo pro GPT-5.4 Pro via Azure AI Foundry (visão)
4. O modelo diz o que fazer: onde clicar, o que digitar, etc.
5. Executa a ação com pyautogui
6. Captura a tela de novo pra ver o resultado
7. Repete até terminar ou dar erro
"""

from __future__ import annotations
import json
import re
import threading
import time
from typing import Optional

try:
    import pyautogui
    pyautogui.FAILSAFE = True   # move o mouse pro canto superior esquerdo pra parar na marra
    pyautogui.PAUSE = 0.4       # pausa automática entre ações (evita erros por ir rápido demais)
    _PYAUTOGUI_OK = True
except ImportError:
    _PYAUTOGUI_OK = False
    print("[AGENTE_UI] pyautogui não encontrado. Instala com: pip install pyautogui")

import visao  # pra capturar a tela


# ─────────────────────────────────────────────
# ESTADO GLOBAL DO AGENTE
# ─────────────────────────────────────────────

_agente_rodando  = threading.Event()   # set = agente ativo agora
_agente_pausado  = threading.Event()   # set = pode rodar | clear = pausado
_agente_parar    = threading.Event()   # set = sinal pra parar tudo
_agente_thread: Optional[threading.Thread] = None
_agente_objetivo = ""                  # o que o agente está fazendo

_callback_falar  = None  # será registrado pelo main.py

# Fila de mensagens ao vivo do usuário (enviadas enquanto o agente está rodando)
import queue as _queue_module
_fila_mensagens_ao_vivo: _queue_module.Queue = _queue_module.Queue()

# Dimensões da imagem que o modelo recebe
IMG_W = 1280
IMG_H = 720

# Limite de segurança: se passar disso algo deu errado
MAX_PASSOS = 50

# Histórico de telas/contexto recente para o agente não "esquecer" onde estava
_contexto_telas: list[str] = []
_MAX_CONTEXTOS = 5


def definir_callback_falar(callback):
    """
    Registra a função que a Emily vai usar pra falar os resultados.
    Chamado no main.py na inicialização.
    """
    global _callback_falar
    _callback_falar = callback


# ─────────────────────────────────────────────
# CONVERSÃO DE COORDENADAS
# ─────────────────────────────────────────────

def _escalar_coordenadas(x: int, y: int) -> tuple[int, int]:
    """
    O modelo analisa a imagem em 1280x720 e retorna coordenadas nessa escala.
    O pyautogui precisa das coordenadas reais do monitor (ex: 1920x1080).
    Essa função faz essa conversão.

    Exemplo com monitor de 1920x1080:
    x_real = x_imagem * (1920 / 1280) = x * 1.5
    y_real = y_imagem * (1080 / 720)  = y * 1.5
    """
    try:
        import mss
        with mss.mss() as sct:
            monitor      = sct.monitors[visao.monitor_atual]
            largura_real = monitor["width"]
            altura_real  = monitor["height"]
            offset_x     = monitor["left"]   # deslocamento horizontal (pra multi-monitor)
            offset_y     = monitor["top"]    # deslocamento vertical

        x_real = int(x * largura_real / IMG_W) + offset_x
        y_real = int(y * altura_real  / IMG_H) + offset_y

        print(f"[AGENTE_UI] Coord: imagem({x},{y}) → tela({x_real},{y_real})")
        return x_real, y_real

    except Exception as e:
        print(f"[AGENTE_UI] Erro ao escalar coordenadas: {e}")
        return x, y  # fallback: usa as coordenadas sem escalar


# ─────────────────────────────────────────────
# ATIVAR JANELA POR NOME/TÍTULO
# ─────────────────────────────────────────────

def _tentar_ativar_janela(nome: str) -> bool:
    """
    Tenta trazer uma janela para frente pelo nome/título do app.
    Retorna True se conseguiu.
    """
    if not nome:
        return False

    try:
        nome_lower = nome.lower()

        # pyautogui.getWindowsWithTitle é alias de pygetwindow
        janelas = pyautogui.getAllWindows()
        candidatas = []
        for w in janelas:
            if not w.title:
                continue
            titulo = w.title.lower()
            # Pontuação: título começa com o nome é melhor
            if nome_lower in titulo or titulo.startswith(nome_lower):
                candidatas.append(w)

        if not candidatas:
            # tenta palavras-chave parciais
            palavras = [p for p in nome_lower.split() if len(p) > 2]
            for w in janelas:
                if not w.title:
                    continue
                titulo = w.title.lower()
                if any(p in titulo for p in palavras):
                    candidatas.append(w)

        if not candidatas:
            return False

        # Escolhe a janela visível de maior área (mais provável de ser a principal)
        def area(w):
            try:
                return w.width * w.height
            except Exception:
                return 0

        janela = max(candidatas, key=area)
        try:
            if janela.isMinimized:
                janela.restore()
            janela.activate()
            print(f"[AGENTE_UI] ✓ Ativou janela por nome: '{janela.title}'")
            return True
        except Exception as e:
            print(f"[AGENTE_UI] Erro ao ativar janela '{janela.title}': {e}")
            return False

    except Exception as e:
        print(f"[AGENTE_UI] Erro ao buscar janela por nome '{nome}': {e}")
        return False


def _tentar_abrir_app(nome: str) -> bool:
    """
    Tenta abrir um app pelo nome através do menu Iniciar/Run.
    Retorna True se abriu.
    """
    if not nome:
        return False

    nome_limpo = nome.lower().strip()
    # Mapeamento de apps comuns para nomes de execução seguros
    apps_comuns = {
        "steam": "steam",
        "chrome": "chrome",
        "edge": "msedge",
        "firefox": "firefox",
        "navegador": "chrome",
        "bloco de notas": "notepad",
        "notepad": "notepad",
        "calculadora": "calc",
        "calculador": "calc",
        "explorer": "explorer",
        "arquivos": "explorer",
        "vscode": "code",
        "code": "code",
        "visual studio code": "code",
        "discord": "discord",
        "spotify": "spotify",
        "epic": "com.epicgames.launcher",
    }

    executavel = apps_comuns.get(nome_limpo)

    if not executavel:
        # Tenta correspondência parcial
        for chave, exe in apps_comuns.items():
            if chave in nome_limpo or nome_limpo in chave:
                executavel = exe
                break

    if not executavel:
        # Se não conhece, tenta abrir pelo menu iniciar digitando o nome original
        executavel = nome_limpo

    try:
        import os
        import subprocess
        # Abre sem travar a thread
        subprocess.Popen(f'start "" "{executavel}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[AGENTE_UI] ✓ Iniciou app pelo nome: '{executavel}'")
        return True
    except Exception as e:
        print(f"[AGENTE_UI] Erro ao iniciar app '{executavel}': {e}")
        return False


# ─────────────────────────────────────────────
# EXECUTAR UMA AÇÃO DE UI
# ─────────────────────────────────────────────

def _obter_coordenadas(acao_dict: dict) -> tuple[Optional[int], Optional[int]]:
    """
    Extrai coordenadas x, y da ação. Retorna (None, None) se não houver.
    """
    if "x" in acao_dict and "y" in acao_dict:
        return int(acao_dict["x"]), int(acao_dict["y"])
    return None, None


def _executar_acao(acao_dict: dict) -> bool:
    """
    Recebe o dicionário de decisão do modelo e executa a ação.
    Retorna True se deu certo, False se falhou.
    """
    if not _PYAUTOGUI_OK:
        print("[AGENTE_UI] pyautogui não disponível!")
        return False

    tipo      = acao_dict.get("acao", "")
    x, y      = _obter_coordenadas(acao_dict)
    texto     = acao_dict.get("texto", "")
    descricao = acao_dict.get("descricao", "")

    # Valida coordenadas antes de executar qualquer ação com mouse
    if x is None or y is None:
        # Ações que precisam de coordenadas
        if tipo in ("clicar", "clicar_celula", "clicar_tarefa", "clicar_direito", "duplo_clique", "mover_mouse"):
            print(f"[AGENTE_UI] Coordenadas ausentes/inválidas para ação '{tipo}'")
            return False

    try:
        # ── Clique esquerdo / célula da grade / barra de tarefas ──
        if tipo in ("clicar", "clicar_celula"):
            rx, ry = _escalar_coordenadas(x, y)
            pyautogui.moveTo(rx, ry, duration=0.3)
            time.sleep(0.1)
            pyautogui.click()
            print(f"[AGENTE_UI] ✓ Clicou em ({rx},{ry}) — {descricao}")
            return True

        # ── Barra de tarefas: ativar janela → abrir app → clicar coordenada ──
        elif tipo == "clicar_tarefa":
            nome_app = texto or descricao
            sucesso = _tentar_ativar_janela(nome_app)
            if not sucesso:
                sucesso = _tentar_abrir_app(nome_app)
            if not sucesso and x is not None and y is not None:
                rx, ry = _escalar_coordenadas(x, y)
                pyautogui.moveTo(rx, ry, duration=0.3)
                time.sleep(0.1)
                pyautogui.click()
                print(f"[AGENTE_UI] ✓ Clicou na barra de tarefas em ({rx},{ry}) — {descricao}")
                sucesso = True
            if sucesso:
                print(f"[AGENTE_UI] ✓ Alternou/abriu app — {descricao}")
                return True
            print(f"[AGENTE_UI] Não conseguiu alternar/abrir app — {descricao}")
            return False

        # ── Ativar janela pelo nome/título ──
        elif tipo == "ativar_janela":
            nome_app = texto or descricao
            if _tentar_ativar_janela(nome_app):
                print(f"[AGENTE_UI] ✓ Ativou janela — {nome_app}")
                return True

            # Janela não encontrada → tenta abrir o app diretamente como fallback
            print(f"[AGENTE_UI] Janela não encontrada, tentando abrir app: {nome_app}")
            aberto = _tentar_abrir_app(nome_app)
            if aberto:
                print(f"[AGENTE_UI] ✓ Abriu app como fallback — {nome_app}")
                time.sleep(2.0)  # aguarda o app iniciar
                return True

            # Último recurso: tenta pelo menu Iniciar
            print(f"[AGENTE_UI] Tentando menu Iniciar como último recurso — {nome_app}")
            try:
                pyautogui.hotkey("win")
                time.sleep(0.6)
                pyautogui.typewrite(nome_app, interval=0.05)
                time.sleep(1.0)
                pyautogui.press("enter")
                time.sleep(1.5)
                print(f"[AGENTE_UI] ✓ Abriu via menu Iniciar — {nome_app}")
                return True
            except Exception as e:
                print(f"[AGENTE_UI] Falha total ao abrir '{nome_app}': {e}")
                # Retorna True mesmo assim — o modelo vai ver a tela e tentar outra abordagem
                return True

        # ── Clique direito ──
        elif tipo == "clicar_direito":
            rx, ry = _escalar_coordenadas(x, y)
            pyautogui.moveTo(rx, ry, duration=0.3)
            pyautogui.rightClick()
            print(f"[AGENTE_UI] ✓ Clique direito em ({rx},{ry}) — {descricao}")
            return True

        # ── Duplo clique ──
        elif tipo == "duplo_clique":
            rx, ry = _escalar_coordenadas(x, y)
            pyautogui.moveTo(rx, ry, duration=0.3)
            pyautogui.doubleClick()
            print(f"[AGENTE_UI] ✓ Duplo clique em ({rx},{ry}) — {descricao}")
            return True

        # ── Digitar texto simples (sem acentos) ──
        elif tipo == "digitar":
            if x is not None and y is not None:  # clica no campo antes de digitar, se tiver coordenadas
                rx, ry = _escalar_coordenadas(x, y)
                pyautogui.click(rx, ry)
                time.sleep(0.3)
            pyautogui.typewrite(texto, interval=0.06)
            print(f"[AGENTE_UI] ✓ Digitou: '{texto}'")
            return True

        # ── Digitar texto com acentos (ã, é, ç, etc) — usa clipboard ──
        elif tipo == "digitar_unicode":
            try:
                import pyperclip
                if x is not None and y is not None:
                    rx, ry = _escalar_coordenadas(x, y)
                    pyautogui.click(rx, ry)
                    time.sleep(0.3)
                pyperclip.copy(texto)
                pyautogui.hotkey("ctrl", "v")
                print(f"[AGENTE_UI] ✓ Colou (unicode): '{texto}'")
                return True
            except ImportError:
                print("[AGENTE_UI] pyperclip não instalado — pip install pyperclip")
                # Tenta typewrite mesmo assim como fallback
                if x is not None and y is not None:
                    rx, ry = _escalar_coordenadas(x, y)
                    pyautogui.click(rx, ry)
                    time.sleep(0.3)
                pyautogui.typewrite(texto, interval=0.06)
                return True

        # ── Pressionar uma tecla (enter, tab, esc, backspace, etc) ──
        elif tipo == "pressionar":
            tecla = texto.lower().strip()
            # Suporte a pressionar múltiplas vezes (ex: "backspace" com "vezes": 5)
            vezes = int(acao_dict.get("vezes", 1))
            for _ in range(vezes):
                pyautogui.press(tecla)
                time.sleep(0.05)
            if vezes > 1:
                print(f"[AGENTE_UI] ✓ Pressionou: '{tecla}' x{vezes}")
            else:
                print(f"[AGENTE_UI] ✓ Pressionou: '{tecla}'")
            return True

        # ── Apagar tudo no campo atual (Ctrl+A + Delete) ──
        elif tipo == "apagar_tudo":
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            pyautogui.press("backspace")
            print(f"[AGENTE_UI] ✓ Apagou todo o texto do campo — {descricao}")
            return True

        # ── Atalho de teclado (ctrl+c, alt+f4, etc) ──
        elif tipo == "atalho":
            teclas = [t.strip() for t in texto.split("+")]
            pyautogui.hotkey(*teclas)
            print(f"[AGENTE_UI] ✓ Atalho: {texto}")
            return True

        # ── Rolar a página ──
        elif tipo == "rolar":
            direcao = acao_dict.get("direcao", "baixo")
            # Cada "click" do pyautogui.scroll vale ~40-60px.
            # Para rolar ~meia tela (~350-400px) precisamos de ~8-10 clicks.
            # Fazemos 3 passagens de 5 clicks com pequena pausa pra garantir que a
            # página registra o scroll (alguns apps precisam de múltiplos eventos).
            sinal = -1 if direcao in ("baixo", "down") else 1
            PASSAGENS   = 3   # quantas vezes chamamos scroll()
            CLICKS_CADA = 5   # clicks por passagem → total = 15 clicks ≈ 600-750px

            def _fazer_scroll(sx, sy=None):
                for _ in range(PASSAGENS):
                    if sy is not None:
                        pyautogui.scroll(sinal * CLICKS_CADA, x=sx, y=sy)
                    else:
                        pyautogui.scroll(sinal * CLICKS_CADA, x=sx)
                    time.sleep(0.05)

            if x is not None and y is not None:
                rx, ry = _escalar_coordenadas(x, y)
                pyautogui.click(rx, ry)
                time.sleep(0.2)
                _fazer_scroll(rx, ry)
            else:
                # Sem coordenadas: usa o centro da tela
                import mss
                try:
                    with mss.mss() as sct:
                        monitor = sct.monitors[visao.monitor_atual]
                        cx = monitor["left"] + monitor["width"]  // 2
                        cy = monitor["top"]  + monitor["height"] // 2
                    pyautogui.click(cx, cy)
                    time.sleep(0.2)
                    _fazer_scroll(cx, cy)
                except Exception:
                    pyautogui.scroll(sinal * CLICKS_CADA * PASSAGENS)

            total = CLICKS_CADA * PASSAGENS
            print(f"[AGENTE_UI] ✓ Rolou {direcao} ({PASSAGENS}x{CLICKS_CADA} = {total} clicks)")
            return True

        # ── Mover o mouse sem clicar (útil pra hover) ──
        elif tipo == "mover_mouse":
            rx, ry = _escalar_coordenadas(x, y)
            pyautogui.moveTo(rx, ry, duration=0.4)
            print(f"[AGENTE_UI] ✓ Mouse em ({rx},{ry})")
            return True

        # ── Esperar (útil quando uma página demora a carregar) ──
        elif tipo == "esperar":
            tempo = float(acao_dict.get("tempo", 1.5))
            print(f"[AGENTE_UI] Aguardando {tempo:.1f}s...")
            # Espera em pedaços pra poder checar parada/pausa enquanto aguarda
            fim = time.time() + tempo
            while time.time() < fim:
                if _agente_parar.is_set():
                    return True
                time.sleep(0.1)
            return True

        # ── Trocar de janela (Alt+Tab) ──
        elif tipo == "trocar_janela":
            # solta alt primeiro pra evitar colar no estado errado
            pyautogui.keyUp("alt")
            pyautogui.keyDown("alt")
            pyautogui.keyDown("tab")
            time.sleep(0.2)
            pyautogui.keyUp("tab")
            time.sleep(0.2)
            pyautogui.keyUp("alt")
            print(f"[AGENTE_UI] ✓ Trocou de janela — {descricao}")
            return True

        # ── Abrir app/pesquisar no menu iniciar ──
        elif tipo == "abrir_app":
            app = texto or descricao
            app_lower = app.lower().strip()

            # 1º: tenta ativar janela já aberta (mais confiável)
            if _tentar_ativar_janela(app_lower):
                print(f"[AGENTE_UI] ✓ App já estava aberto, ativou janela: '{app}'")
                return True

            # 2º: mapeamento direto pra executáveis conhecidos (evita depender do menu Iniciar)
            executaveis_diretos = {
                "steam": r"C:\Program Files (x86)\Steam\steam.exe",
                "discord": r"C:\Users\conti\AppData\Local\Discord\Update.exe",
                "spotify": r"C:\Users\conti\AppData\Roaming\Spotify\Spotify.exe",
                "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                "brave": r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                "firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
                "explorer": "explorer.exe",
                "arquivos": "explorer.exe",
                "notepad": "notepad.exe",
                "bloco de notas": "notepad.exe",
                "calc": "calc.exe",
                "calculadora": "calc.exe",
                "vscode": "code",
                "code": "code",
            }

            import subprocess
            import os

            # Procura correspondência parcial no mapeamento
            exe = None
            for chave, caminho in executaveis_diretos.items():
                if chave in app_lower or app_lower in chave:
                    exe = caminho
                    break

            if exe:
                try:
                    subprocess.Popen(exe, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"[AGENTE_UI] ✓ Abriu diretamente: '{exe}'")
                    time.sleep(1.5)
                    return True
                except Exception as e:
                    print(f"[AGENTE_UI] Falha ao abrir direto '{exe}': {e}")

            # 3º: fallback — menu Iniciar (menos confiável)
            try:
                pyautogui.hotkey("win")
                time.sleep(0.6)
                pyautogui.typewrite(app, interval=0.05)
                time.sleep(1.0)
                pyautogui.press("enter")
                print(f"[AGENTE_UI] ✓ Abriu via menu Iniciar: '{app}'")
                return True
            except Exception as e:
                print(f"[AGENTE_UI] Falha ao abrir via menu Iniciar '{app}': {e}")
                return False

        # ── Minimizar janela atual ──
        elif tipo == "minimizar":
            pyautogui.keyDown("win")
            pyautogui.keyDown("down")
            pyautogui.keyUp("down")
            pyautogui.keyUp("win")
            print("[AGENTE_UI] ✓ Minimizou janela atual")
            return True

        # ── Max/restaurar janela atual ──
        elif tipo == "maximizar":
            pyautogui.keyDown("win")
            pyautogui.keyDown("up")
            pyautogui.keyUp("up")
            pyautogui.keyUp("win")
            print("[AGENTE_UI] ✓ Maximizou/restaurou janela atual")
            return True

        else:
            print(f"[AGENTE_UI] Tipo de ação desconhecido: '{tipo}'")
            return False

    except pyautogui.FailSafeException:
        # O usuário moveu o mouse pro canto pra parar — tratamos como parada intencional
        print("[AGENTE_UI] FAILSAFE ativado! Mouse foi pro canto superior esquerdo.")
        _agente_parar.set()
        return False
    except Exception as e:
        print(f"[AGENTE_UI] Erro ao executar '{tipo}': {e}")
        return False


# ─────────────────────────────────────────────
# LOOP PRINCIPAL DO AGENTE
# ─────────────────────────────────────────────

def _memoria_para_contexto() -> str:
    """Retorna os fatos da memória do Vitor formatados para injetar no histórico do agente."""
    try:
        import memoria as _mem
        texto = _mem.formatar_para_prompt()
        return texto if texto else ""
    except Exception:
        return ""


def _personalidade_emily() -> str:
    """Retorna a personalidade principal da Emily para injetar no contexto do agente."""
    try:
        import modelo as _modelo
        return _modelo.EMILY_PERSONALIDADE.strip()
    except Exception:
        return "Você é Emily, a assistente pessoal do Vitor."


def _loop_agente(objetivo: str) -> None:
    """
    Roda em thread separada.
    Cada volta do loop: captura tela → pede decisão → executa → repete.
    """
    global _agente_objetivo, _contexto_telas

    _agente_objetivo = objetivo
    _contexto_telas = []     # limpa contexto de telas antigas
    _agente_parar.clear()
    _agente_pausado.set()    # começa sem pausa
    historico: list[str] = []
    _ultima_acao_desc = ""   # rastreio de repetição
    _contagem_repeticao = 0  # quantas vezes a mesma ação foi repetida seguida
    _loop_ativo = False      # se estamos em estado de loop detectado

    # ── Monta contexto fixo: personalidade + memória ─────────────────
    # Passado direto pra decidir_proxima_acao_ui como contexto_fixo,
    # sem ocupar nenhum slot do historico[] rotativo.
    partes_fixas = []
    personalidade = _personalidade_emily()
    if personalidade:
        partes_fixas.append(
            f"[IDENTIDADE E PERSONALIDADE DA EMILY — mantenha durante toda a tarefa]\n{personalidade}"
        )
    ctx_mem = _memoria_para_contexto()
    if ctx_mem:
        partes_fixas.append(
            f"[CONTEXTO DO USUÁRIO — use para personalizar suas ações]\n{ctx_mem}"
        )
    _contexto_fixo = "\n\n".join(partes_fixas)

    print(f"\n[AGENTE_UI] === Iniciando: '{objetivo}' ===")

    for passo in range(1, MAX_PASSOS + 1):

        # Verifica se o usuário pediu pra parar
        if _agente_parar.is_set():
            print("[AGENTE_UI] Parado pelo usuário")
            _falar("Ok, parei o que eu tava fazendo na tela!")
            break

        # Verifica se está pausado — fica aqui até continuar_agente_ui() ser chamado
        if not _agente_pausado.is_set():
            print("[AGENTE_UI] Pausado, aguardando...")
            _agente_pausado.wait()
            if _agente_parar.is_set():
                break

        print(f"[AGENTE_UI] --- Passo {passo}/{MAX_PASSOS} ---")

        # 0.5. Verifica se o usuário enviou uma mensagem ao vivo pra corrigir/orientar
        while not _fila_mensagens_ao_vivo.empty():
            try:
                msg_vivo = _fila_mensagens_ao_vivo.get_nowait()
                if msg_vivo:
                    historico.append(f"🗣️ VITOR DISSE AGORA: '{msg_vivo}' — Leve isso em consideração IMEDIATAMENTE no próximo passo. Ajuste sua estratégia conforme o que ele disse.")
                    if len(historico) > 10:
                        historico = historico[-10:]
                    print(f"[AGENTE_UI] 💬 Mensagem ao vivo recebida: '{msg_vivo}'")
            except Exception:
                break

        # 1. Captura a tela atual (alta resolução)
        imagem = visao.capturar_tela()
        if not imagem:
            # Se a captura falhou, pode ser UAC ou outro bloqueio de segurança.
            # Esperamos um pouco e tentamos de novo, mas não travamos a thread.
            if visao._tela_bloqueada_pelo_uac():
                _falar("Vitor, apareceu uma tela de permissão. Responde ela que eu continuo depois.")
                for _ in range(20):  # espera até ~20 segundos pela resposta do UAC
                    time.sleep(1)
                    if not visao._tela_bloqueada_pelo_uac():
                        imagem = visao.capturar_tela()
                        if imagem:
                            break
                if not imagem:
                    _falar("Ficou muito tempo naquela tela de permissão. Pede de novo quando responder.")
                    break
            else:
                _falar("Não consegui capturar a tela, Vitor!")
                break

        # 2. Pede pro GPT-5.4 Pro decidir o próximo passo
        import modelo as _modelo
        contexto_telas = _contexto_telas[-_MAX_CONTEXTOS:]

        # Tenta até 3 vezes caso o modelo retorne resposta inválida (não-JSON)
        decisao = None
        for _tentativa in range(3):
            decisao = _modelo.decidir_proxima_acao_ui(imagem, objetivo, historico, contexto_telas, contexto_fixo=_contexto_fixo)
            if decisao:
                break
            print(f"[AGENTE_UI] Resposta inválida do modelo (tentativa {_tentativa + 1}/3), tentando novamente...")
            time.sleep(0.5)

        if not decisao:
            # Se falhou 3 vezes seguidas, pula esse passo e tenta de novo no próximo
            print("[AGENTE_UI] Modelo falhou 3x seguidas, pulando passo...")
            historico.append(f"Passo {passo}: FALHA - modelo não retornou JSON válido")
            if len(historico) > 8:
                historico = historico[-8:]
            time.sleep(1.0)
            continue

        tipo_acao = decisao.get("acao", "")
        descricao = decisao.get("descricao", "")

        # 3. Verifica se terminou
        if tipo_acao == "concluido":
            mensagem = decisao.get("mensagem", "Pronto Vitor, terminei!")
            print(f"[AGENTE_UI] ✓ Concluído: {mensagem}")
            _falar(mensagem)
            break

        # 4. Verifica se o modelo encontrou um erro
        if tipo_acao == "erro":
            mensagem = decisao.get("mensagem", "Não consegui continuar, Vitor!")
            print(f"[AGENTE_UI] ✗ Erro: {mensagem}")
            _falar(mensagem)
            break

        # 4.5. ANTI-LOOP: Detecta se o modelo está repetindo a mesma ação
        desc_normalizada = (descricao or tipo_acao).strip().lower()
        if desc_normalizada == _ultima_acao_desc:
            _contagem_repeticao += 1
        else:
            _contagem_repeticao = 1
            _ultima_acao_desc = desc_normalizada
            _loop_ativo = False

        # Se repetiu 3x seguidas: FORÇA uma ação corretiva e pula a ação do modelo
        if _contagem_repeticao >= 3 and not _loop_ativo:
            _loop_ativo = True
            print(f"[AGENTE_UI] 🔄 ANTI-LOOP: Mesma ação '{desc_normalizada}' repetida {_contagem_repeticao}x. Forçando próximo passo...")
            
            # Determina ação corretiva baseado no tipo de ação que está travando
            if tipo_acao == "clicar" and decisao.get("y", 999) < 100:
                # Travou clicando na barra de endereço → já está selecionada, digita direto
                historico.append(f"Passo {passo}: ⚠️ ANTI-LOOP ATIVADO — Você já clicou na barra de endereço. Ela JÁ ESTÁ selecionada. O clique FUNCIONOU. Agora DIGITE a URL diretamente (use 'apagar_tudo' se precisar limpar, depois 'digitar' o endereço). NÃO clique de novo.")
                # Executa Ctrl+A pra garantir seleção
                pyautogui.hotkey("ctrl", "a")
                print(f"[AGENTE_UI] 🔄 Executou Ctrl+A forçado na barra de endereço")
            elif tipo_acao == "clicar":
                # Travou clicando em algo genérico → assume que o clique funcionou
                historico.append(f"Passo {passo}: ⚠️ ANTI-LOOP ATIVADO — O clique anterior JÁ FUNCIONOU. A ação foi executada com sucesso. Prossiga para o PRÓXIMO passo do objetivo. NÃO repita o clique.")
            elif tipo_acao in ("digitar", "digitar_unicode"):
                # Travou digitando → limpa e tenta de novo
                historico.append(f"Passo {passo}: ⚠️ ANTI-LOOP ATIVADO — O texto pode já ter sido digitado. Olhe a tela com atenção. Se o texto está correto, pressione 'enter'. Se não está, use 'apagar_tudo' primeiro.")
                pyautogui.hotkey("ctrl", "a")
                print(f"[AGENTE_UI] 🔄 Executou Ctrl+A forçado pra permitir re-digitação")
            else:
                # Qualquer outra ação repetida → avisa o modelo que funcionou
                historico.append(f"Passo {passo}: ⚠️ ANTI-LOOP ATIVADO — A ação '{desc_normalizada}' já foi executada com SUCESSO anteriormente. Assuma que FUNCIONOU e prossiga para o próximo passo do objetivo.")

            if len(historico) > 10:
                historico = historico[-10:]
            time.sleep(1.0)
            continue  # Pula a execução da ação repetida

        # Se já está em loop ativo e o modelo AINDA repete (4x+), força mais agressivamente
        if _contagem_repeticao >= 5:
            print(f"[AGENTE_UI] 🛑 ANTI-LOOP CRÍTICO: {_contagem_repeticao}x a mesma ação. Forçando continuidade...")
            historico = historico[-3:]  # Limpa histórico pra dar "reset" no contexto
            historico.append(f"⚠️ RESET DE CONTEXTO: Você ficou travado repetindo a mesma ação por 5 vezes. A ação anterior JÁ FOI BEM-SUCEDIDA. OBRIGATÓRIO: faça o PRÓXIMO passo lógico do objetivo original: '{objetivo}'. Se era pra clicar em algo que já clicou, agora digite ou pressione enter. Se era pra digitar, agora pressione enter pra confirmar.")
            _contagem_repeticao = 0
            _loop_ativo = False
            time.sleep(1.0)
            continue

        # 5. Registra no histórico (só os últimos 8 pra economizar tokens)
        acao_resumida = f"Passo {passo}: {descricao or tipo_acao}"
        historico.append(acao_resumida)
        if len(historico) > 8:
            historico = historico[-8:]

        # 5.1. Se for ação de navegação, registra o contexto de tela para não "esquecer" onde estava
        if tipo_acao in ("trocar_janela", "abrir_app", "clicar_tarefa", "minimizar", "maximizar"):
            _contexto_telas.append(f"Passo {passo}: {descricao or tipo_acao}")
            if len(_contexto_telas) > _MAX_CONTEXTOS:
                _contexto_telas = _contexto_telas[-_MAX_CONTEXTOS:]

        # 6. Executa a ação
        sucesso = _executar_acao(decisao)
        if not sucesso:
            # NÃO encerra o agente — registra a falha no histórico e deixa o modelo tentar alternativa
            print(f"[AGENTE_UI] ⚠️ Ação '{tipo_acao}' falhou. Registrando no histórico e continuando...")
            historico.append(
                f"Passo {passo}: FALHA na ação '{tipo_acao}' ({descricao}). "
                f"Tente uma abordagem DIFERENTE: se não encontrou a janela, use 'abrir_app'; "
                f"se não conseguiu abrir o app, procure na barra de tarefas (clicar_tarefa), "
                f"na área de trabalho (minimizar todas as janelas com atalho win+d) ou no menu Iniciar. "
                f"NUNCA desista — sempre existe uma alternativa."
            )
            if len(historico) > 10:
                historico = historico[-10:]
            time.sleep(1.0)
            continue  # Continua o loop — o modelo vai ver a falha e tentar diferente

        # 7. Aguarda a tela atualizar antes da próxima captura
        time.sleep(1.5)

    else:
        # Chegou no limite de passos sem concluir
        _falar(f"Atingi o limite de {MAX_PASSOS} passos sem terminar, Vitor!")

    # Limpa o estado ao finalizar
    _agente_rodando.clear()
    _agente_objetivo = ""
    print("[AGENTE_UI] === Agente finalizado ===\n")


def _falar(texto: str) -> None:
    """Chama o callback de fala de forma segura."""
    if _callback_falar:
        try:
            _callback_falar(texto)
        except Exception as e:
            print(f"[AGENTE_UI] Erro no callback de fala: {e}")
    else:
        print(f"[AGENTE_UI] (sem callback de fala): {texto}")


# ─────────────────────────────────────────────
# API PÚBLICA — chamada pelo automacao.py
# ─────────────────────────────────────────────

def iniciar_agente_ui(objetivo: str, callback_falar=None) -> str:
    """Inicia o agente de UI com o objetivo dado."""
    global _agente_thread, _callback_falar

    if not _PYAUTOGUI_OK:
        return "Preciso do pyautogui pra isso! Instala com: pip install pyautogui"

    if _agente_rodando.is_set():
        return "Já tô fazendo outra coisa na tela, Vitor! Me fala pra parar primeiro."

    if not objetivo or not objetivo.strip():
        return "Me diz o que você quer que eu faça na tela, Vitor!"

    if callback_falar:
        _callback_falar = callback_falar

    _agente_rodando.set()
    _agente_thread = threading.Thread(
        target=_loop_agente,
        args=(objetivo,),
        daemon=True,
    )
    _agente_thread.start()

    import modelo as _modelo_ref
    frase_inicio = _modelo_ref.gerar_frase_acao("agente_ui_iniciando", objetivo) or "Vou fazer isso na tela!"
    _modelo_ref.registrar_acao_no_historico(f"Iniciou agente de UI com objetivo: {objetivo}")
    return frase_inicio


def pausar_agente_ui() -> str:
    """Pausa o agente (pode continuar depois)."""
    if not _agente_rodando.is_set():
        return "Não tô fazendo nada na tela agora, Vitor!"
    if not _agente_pausado.is_set():
        return "Já tô pausado!"
    _agente_pausado.clear()
    return "Pausei! Me fala 'continua o que tava fazendo na tela' quando quiser."


def continuar_agente_ui() -> str:
    """Retoma um agente pausado."""
    if not _agente_rodando.is_set():
        return "Não tem nada pausado agora, Vitor!"
    if _agente_pausado.is_set():
        return "Já tô rodando, não tô pausado!"
    _agente_pausado.set()
    return "Continuando!"


def parar_agente_ui() -> str:
    """Para o agente completamente."""
    if not _agente_rodando.is_set():
        return "Não tô fazendo nada na tela agora, Vitor!"
    _agente_parar.set()
    _agente_pausado.set()  # libera o wait caso esteja pausado
    return "Parando o que eu tava fazendo na tela!"


def status_agente_ui() -> str:
    """Retorna o status atual do agente."""
    if not _agente_rodando.is_set():
        return "Agente de UI: parado"
    estado = "pausado" if not _agente_pausado.is_set() else "rodando"
    return f"Agente de UI {estado}: {_agente_objetivo}"


def enviar_mensagem_ao_vivo(mensagem: str) -> bool:
    """
    Envia uma mensagem do usuário pra ser considerada pelo agente no próximo passo.
    Retorna True se o agente está rodando e a mensagem foi enfileirada.
    Retorna False se o agente não está ativo.
    """
    if not _agente_rodando.is_set():
        return False
    if mensagem and mensagem.strip():
        _fila_mensagens_ao_vivo.put(mensagem.strip())
        print(f"[AGENTE_UI] 💬 Mensagem ao vivo enfileirada: '{mensagem.strip()}'")
    return True

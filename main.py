import queue
import threading
import time
import automacao
import interface
import intencoes
import memoria
import modelo
import visao
import voz
import pyperclip
import keyboard
import discord_bot

mem = memoria.carregar_memoria()
modelo.atualizar_memoria(mem)

automacao.inicializar()
discord_bot.inicializar()

janela = interface.JanelaEmily()
automacao.definir_callback_status(janela.atualizar_status)
emily_ocupada = threading.Event()
visao_ativa = threading.Event()
modo_escrito_ativo = False

ultimo_uso_usuario = 0
COOLDOWN_VISAO = 10


def restaurar_status():
    janela.atualizar_status("aguardando")


def processar_texto_digitado(texto):
    global ultimo_uso_usuario
    ultimo_uso_usuario = time.time()
    emily_ocupada.set()
    try:
        janela.atualizar_status("ouvindo", f'Você escreveu: "{texto}"')

      
        resposta_automacao = automacao.executar_comando(texto, callback_falar=voz.falar)
        if resposta_automacao:
            janela.atualizar_status("falando", resposta_automacao)
            voz.falar(resposta_automacao)
            restaurar_status()
            return

        # se não foi automação, segue pra LLM normalmente
        fila_frases = queue.Queue()

        def gerar_resposta():
            modelo.conversar_stream(
                texto,
                lambda f: janela.atualizar_status("falando", f),
                fila_frases,
            )

        def falar_resposta():
            voz.falar_stream(
                fila_frases,
                lambda f: janela.atualizar_status("falando", f),
            )

        t_gerar = threading.Thread(target=gerar_resposta, daemon=True)
        t_falar = threading.Thread(target=falar_resposta, daemon=True)
        t_gerar.start()
        t_falar.start()
        t_gerar.join()
        t_falar.join()

        restaurar_status()
    except Exception as erro:
        print(f"Erro ao processar texto digitado: {erro}")
        restaurar_status()
    finally:
        emily_ocupada.clear()


janela.callback_texto = processar_texto_digitado
janela.callback_trocar_monitor = visao.trocar_monitor


# ─────────────────────────────────────────────────────────────────
# CALLBACK DO DISCORD — recebe áudio da call e processa
# ─────────────────────────────────────────────────────────────────

_discord_modo_ativo = threading.Event()  
_timer_reset_discord = None             

def _resetar_modo_discord():
    _discord_modo_ativo.clear()
    print("[Discord] Modo comando expirado, voltando a aguardar wake word.")

def callback_texto_discord(texto: str, user_id: int, display_name: str = ""):
    owner_id = discord_bot._config.get("usuario_id", 0)

    if user_id == owner_id or not display_name:
        threading.Thread(target=processar_texto_digitado, args=(texto,), daemon=True).start()
    else:
        threading.Thread(target=_processar_discord_externo, args=(texto, display_name), daemon=True).start()

discord_bot.definir_callback_texto(callback_texto_discord)

def _processar_discord_externo(texto: str, nome: str):
    """Processa mensagens de outros usuários do Discord."""
    emily_ocupada.set()
    try:
        janela.atualizar_status("ouvindo", f'[Discord] {nome}: "{texto}"')

        # Tenta como comando de automação primeiro
        resposta_automacao = automacao.executar_comando(texto, callback_falar=voz.falar)
        if resposta_automacao:
            resposta_final = f"{nome} pediu! {resposta_automacao}"
            janela.atualizar_status("falando", resposta_final)
            voz.falar(resposta_final)
            restaurar_status()
            return

        # Conversa com LLM — inclui o nome da pessoa no contexto
        mensagem_com_contexto = f"[{nome} está falando com você pelo Discord]: {texto}"

        fila_frases = queue.Queue()

        def gerar_resposta():
            modelo.conversar_stream(
                mensagem_com_contexto,
                lambda f: janela.atualizar_status("falando", f),
                fila_frases,
            )

        def falar_resposta():
            voz.falar_stream(
                fila_frases,
                lambda f: janela.atualizar_status("falando", f),
            )

        t_gerar = threading.Thread(target=gerar_resposta, daemon=True)
        t_falar = threading.Thread(target=falar_resposta, daemon=True)
        t_gerar.start()
        t_falar.start()
        t_gerar.join()
        t_falar.join()

        restaurar_status()
    except Exception as erro:
        print(f"Erro ao processar mensagem externa do Discord: {erro}")
        restaurar_status()
    finally:
        emily_ocupada.clear()

def executar_leitura_de_tela():
    """
    Lê as instruções da tela, interpreta como ações e pede confirmação.
    """
    janela.atualizar_status("ouvindo", "Lendo a tela...")
    voz.falar("Um segundo, deixa eu ver o que tá na tela.")

    # 1. Extrai instruções da tela
    texto_tela = modelo.ler_instrucoes_da_tela()

    if not texto_tela or "SEM_INSTRUCOES" in texto_tela:
        voz.falar("Não encontrei instruções claras na tela, Vitor.")
        restaurar_status()
        return

    # 2. Interpreta como ações (sem executar)
    resultado = automacao.interpretar_sem_executar(texto_tela)

    if not resultado or resultado.get("acao") == "nenhuma":
        voz.falar("Li a tela mas não consegui transformar isso em ações que eu saiba fazer.")
        restaurar_status()
        return

    # 3. Resume o que vai fazer e pede confirmação
    resumo = automacao.resumir_acoes(resultado)
    voz.falar(f"{resumo}. Posso fazer isso?")
    janela.atualizar_status("gravando", "Aguardando confirmação...")

    # 4. Escuta a confirmação por PTT
    confirmacao = voz.ouvir_ptt(
        callback_gravando=lambda: janela.atualizar_status("gravando", "🔴 Gravando...")
    )

    if not confirmacao or not intencoes.confirma_encerramento(confirmacao):
        if confirmacao and any(p in confirmacao.lower() for p in ("sim", "pode", "vai", "faz", "confirmo", "ok", "tá")):
            pass  # vai executar
        else:
            voz.falar("Tudo bem, cancelado!")
            restaurar_status()
            return

    # 5. Executa
    janela.atualizar_status("falando", "Executando...")
    resposta = automacao.executar_resultado(resultado, callback_falar=voz.falar)
    if resposta:
        janela.atualizar_status("falando", resposta)
        voz.falar(resposta)

    restaurar_status()


def rodar_emily():
    global modo_escrito_ativo
    janela.atualizar_status("aguardando")

    while True:
        # Aguarda a tecla PTT e grava enquanto estiver pressionada
        entrada = voz.ouvir_ptt(
            callback_gravando=lambda: janela.atualizar_status("gravando", "🔴 Gravando...")
        )

        if not entrada:
            restaurar_status()
            continue

        if len(entrada.strip()) < 4:
            print(f"[IGNORADO] Entrada muito curta: '{entrada}'")
            restaurar_status()
            continue

        if voz.falar_ativo.is_set():
            print("[IGNORADO] Emily ainda falando")
            continue

        emily_ocupada.set()

        try:
            entrada_lower = entrada.lower()

            if intencoes.pede_encerramento(entrada):
                voz.falar("Você quer mesmo que eu feche?")
                janela.atualizar_status("gravando", "Quer fechar?")

                confirmacao = voz.ouvir_ptt(
                    callback_gravando=lambda: janela.atualizar_status("gravando", "🔴 Gravando...")
                )

                if intencoes.confirma_encerramento(confirmacao or ""):
                    resposta = "Tchau então seu chato, até mais!"
                    janela.atualizar_status("falando", resposta)
                    voz.falar(resposta)
                    janela.root.destroy()
                    break

                restaurar_status()
                continue

            if "lembra que" in entrada_lower or "guarda que" in entrada_lower:
                modelo.guardar_fato_manual(entrada)
                resposta = "Anotei, vou lembrar disso!"
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                continue

            if "meu nome é" in entrada_lower:
                nome = entrada_lower.replace("meu nome é", "").strip().title()
                mem["nome_usuario"] = nome
                memoria.salvar_memoria(mem)
                modelo.atualizar_memoria(mem)
                resposta = f"Anotei! Vou te chamar de {nome} então!"
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                continue

            # ─── CONTROLE DE ESCUTA DO DISCORD ───
            if "ouve o discord" in entrada_lower:
                discord_bot.ativar_escuta_discord()
                resposta = "Tô de olho no Discord agora, Vitor!"
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                continue

            if "para de ouvir o discord" in entrada_lower or "para o discord" in entrada_lower:
                discord_bot.desativar_escuta_discord()
                resposta = "Parei de ouvir o Discord!"
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                continue

            # ─── MODO ESCRITO — ativar ───
            if intencoes.ativar_modo_escrito(entrada):
                modo_escrito_ativo = True
                resposta = "Modo escrito ativado! Pode falar que eu escrevo pra você."
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                continue

            # ─── MODO ESCRITO — desativar ───
            if intencoes.desativar_modo_escrito(entrada):
                modo_escrito_ativo = False
                resposta = "Modo escrito desativado!"
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                continue

            # ─── MODO ESCRITO — digitar o que foi falado ───
            if modo_escrito_ativo:
                janela.atualizar_status("ouvindo", f"[Modo Escrito] {entrada}")
                time.sleep(0.3)
                pyperclip.copy(entrada)
                keyboard.send("ctrl+v")
                restaurar_status()
                emily_ocupada.clear()
                continue

            # ─── LEITURA DE TELA ───
            palavras_traducao = ("traduz", "traduzir", "traduza", "tradução")
            referencias_tela  = ("isso", "aqui", "na tela", "esse", "essa", "tela",
                                "primeiro", "segundo", "terceiro", "o texto", "essa parte",
                                "esse trecho", "essa frase", "esse parágrafo")
            
            if (any(p in entrada_lower for p in palavras_traducao)
                    and any(r in entrada_lower for r in referencias_tela)):
                janela.atualizar_status("ouvindo", "Analisando a tela pra traduzir...")
                voz.falar("Um segundo, deixa eu ver o que tem pra traduzir.")
                resposta = modelo.traduzir_tela(entrada)
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                continue

            resposta_automacao = automacao.executar_comando(entrada, callback_falar=voz.falar)
            if resposta_automacao:
                janela.atualizar_status("falando", resposta_automacao)
                voz.falar(resposta_automacao)
                restaurar_status()
                continue

            global ultimo_uso_usuario
            ultimo_uso_usuario = time.time()
            janela.atualizar_status("ouvindo", f'Você disse: "{entrada}"')
            time.sleep(0.2)

            fila_frases = queue.Queue()

            def gerar_resposta():
                modelo.conversar_stream(
                    entrada,
                    lambda f: janela.atualizar_status("falando", f),
                    fila_frases,
                )

            def falar_resposta():
                voz.falar_stream(
                    fila_frases,
                    lambda f: janela.atualizar_status("falando", f),
                )

            t_gerar = threading.Thread(target=gerar_resposta, daemon=True)
            t_falar = threading.Thread(target=falar_resposta, daemon=True)
            t_gerar.start()
            t_falar.start()
            t_gerar.join()
            t_falar.join()

            restaurar_status()

        except Exception as erro:
            print(f"Erro ao processar entrada: {erro}")
            restaurar_status()
        finally:
            emily_ocupada.clear()


def loop_visao():
    COOLDOWN_COMENTARIO = 1

    ultimo_comentario = 0

    while True:
        try:
            if not visao_ativa.is_set():
                time.sleep(1)
                continue

            if time.time() - ultimo_uso_usuario < COOLDOWN_VISAO:
                time.sleep(1)
                continue

            if emily_ocupada.is_set() or voz.falar_ativo.is_set():
                time.sleep(0.5)
                continue

            if time.time() - ultimo_comentario < COOLDOWN_COMENTARIO:
                time.sleep(2)
                continue

            imagens = visao.capturar_sequencia_telas_rapida(quantidade=3, intervalo=0.8)
            frame_atual = imagens[1] if len(imagens) > 1 else imagens[0]

            vale_comentar = modelo.triar_tela(frame_atual)

            if not vale_comentar:
                time.sleep(5)
                continue

            comentario = modelo.analisar_sequencia_telas(imagens)

            if comentario and not emily_ocupada.is_set() and not voz.falar_ativo.is_set():
                emily_ocupada.set()
                ultimo_comentario = time.time()
                try:
                    janela.atualizar_status("falando", comentario)
                    voz.falar(comentario)
                finally:
                    emily_ocupada.clear()
                    janela.atualizar_status("aguardando")

            time.sleep(5)
        except Exception as erro:
            print(f"Erro no loop de visão: {erro}")
            time.sleep(5)


def toggle_visao():
    if visao_ativa.is_set():
        visao_ativa.clear()
        print("[VISAO] Monitoramento desativado")
    else:
        visao_ativa.set()
        print("[VISAO] Monitoramento ativado")


janela.callback_visao = toggle_visao

import atexit
import signal
import sys


def encerrar_tudo():
    try:
        discord_bot.desconectar_voz()  # desconecta da call antes de fechar
    except:
        pass
    try:
        janela._painel.destroy()
        janela.root.destroy()
    except:
        pass


def ao_encerrar(sig, frame):
    print("[SISTEMA] Encerrando...")
    encerrar_tudo()
    sys.exit(0)


signal.signal(signal.SIGTERM, ao_encerrar)
signal.signal(signal.SIGBREAK, ao_encerrar)  # Windows

atexit.register(encerrar_tudo)

thread_visao = threading.Thread(target=loop_visao, daemon=True)
thread_visao.start()

thread = threading.Thread(target=rodar_emily, daemon=True)
thread.start()
janela.iniciar()
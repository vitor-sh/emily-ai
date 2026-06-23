import queue
import re
import threading
import time
from typing import Optional
import automacao
import gerador_imagem as imagem
import interface
import intencoes
import memoria
import modelo
import pesquisa
import visao
import voz
import pyperclip
import keyboard
import discord_bot
import servidor
import notificacoes
import agente_ui
import agente_jogo

mem = memoria.carregar_memoria()
modelo.atualizar_memoria(mem)

automacao.inicializar()
discord_bot.inicializar()

janela = interface.JanelaEmily()
automacao.definir_callback_status(janela.atualizar_status)
agente_ui.definir_callback_falar(voz.falar)
_notificando_download = False

def _avisar_download(mensagem: str):
    global _notificando_download
    if _notificando_download:
        return

    def _falar():
        global _notificando_download
        _notificando_download = True
        for _ in range(60):
            if not emily_ocupada.is_set() and not voz.falar_ativo.is_set():
                break
            time.sleep(0.5)
        emily_ocupada.set()
        try:
            janela.atualizar_status("falando", mensagem)
            voz.falar(mensagem)
            restaurar_status()
        finally:
            emily_ocupada.clear()
            _notificando_download = False

    threading.Thread(target=_falar, daemon=True).start()

automacao.definir_callback_download(_avisar_download)

def _avisar_notificacao(app_nome: str, contato: str, mensagem: str):
    """Chamado quando chega uma notificação nova de WhatsApp, Telegram, etc."""
    def _falar():
        for _ in range(30):
            if not emily_ocupada.is_set() and not voz.falar_ativo.is_set():
                break
            time.sleep(0.5)

        emily_ocupada.set()
        try:
            if mensagem:
                resumo = mensagem[:80] + "..." if len(mensagem) > 80 else mensagem
                aviso = f"Vitor, {contato} mandou mensagem no {app_nome}: {resumo}"
            else:
                aviso = f"Vitor, {contato} mandou mensagem no {app_nome}. Dá uma olhada lá!"

            janela.atualizar_status("falando", aviso)
            voz.falar(aviso)
            restaurar_status()
        finally:
            emily_ocupada.clear()

    threading.Thread(target=_falar, daemon=True).start()

notificacoes.definir_callback(_avisar_notificacao)
notificacoes.iniciar_monitor()
      
      
emily_ocupada = threading.Event()
visao_ativa = threading.Event()
modo_escrito_ativo = False
modo_ui_ativo = False
modo_jogo_ativo = threading.Event()

ultimo_uso_usuario = 0
COOLDOWN_VISAO = 10

FRASES_ATIVAR_JOGO = (
    "monitora o jogo",
    "monitora meu jogo",
    "monitorar o jogo",
    "monitorar meu jogo",
    "modo monitoramento de jogo",
    "modo jogo",
    "fica olhando o jogo",
    "fica olhando meu jogo",
    "fica vendo o jogo",
    "fica vendo meu jogo",
    "fica olhando",
    "olha o jogo",
    "olha meu jogo",
    "reage ao jogo",
    "comenta o jogo",
)

FRASES_DESATIVAR_JOGO = (
    "para de monitorar o jogo",
    "para de monitorar meu jogo",
    "desativa monitoramento de jogo",
    "desativa o modo jogo",
    "sai do modo jogo",
    "sair do modo jogo",
    "para de olhar o jogo",
    "para de olhar meu jogo",
    "para de reagir",
    "para de comentar o jogo",
)

# ─── MODO JOGO (AGENTE DE JOGOS) ───
JOGOS_CONHECIDOS = (
    "celeste",
    "hollow knight",
    "minecraft",
    "terraria",
    "stardew",
    "roblox",
    "gta",
    "cyberpunk",
    "elden ring",
    "dark souls",
    "sekiro",
    "cuphead",
    "hades",
    "ori",
    "dead cells",
    " UNDERTALE",
    "deltarune",
)

FRASES_PEDIR_JOGO = (
    "passa essa fase",
    "passa a fase",
    "passa de fase",
    "passa pra mim",
    "passa o jogo",
    "joga pra mim",
    "joga para mim",
    "joga a fase",
    "joga o jogo",
    "jogue pra mim",
    "jogue para mim",
    "faz essa fase",
    "faz a fase",
    "me passa a fase",
    "me passa essa fase",
    "completa essa fase",
    "completa a fase",
    "termina essa fase",
    "termina a fase",
    "vence essa fase",
    "vai na fase",
    "sobe essa fase",
    "desce essa fase",
    "avanca a fase",
    "avança a fase",
    "resolve essa fase",
    "resolve a fase",
)

def _extrair_nome_jogo(texto: str) -> Optional[str]:
    """Tenta extrair o nome do jogo mencionado no texto."""
    texto_lower = texto.lower()
    for jogo in JOGOS_CONHECIDOS:
        if jogo in texto_lower:
            return jogo
    return None

def _pedido_para_jogar(texto: str) -> bool:
    """Detecta se o usuário quer que a Emily jogue um jogo."""
    texto_lower = texto.lower()
    tem_jogo = _extrair_nome_jogo(texto) is not None
    tem_pedido_jogo = any(p in texto_lower for p in FRASES_PEDIR_JOGO)
    return tem_jogo and tem_pedido_jogo


def _iniciar_agente_jogo(texto: str) -> None:
    """Inicia o agente de jogo com o nome do jogo detectado e fala a resposta."""
    nome_jogo = _extrair_nome_jogo(texto)
    if not nome_jogo:
        nome_jogo = "generico"

    monitor_match = re.search(r"monitor\s*(\d+)", texto.lower())
    monitor = int(monitor_match.group(1)) if monitor_match else 1

    janela.atualizar_status("falando", f"Iniciando agente de jogo: {nome_jogo}")
    resposta = agente_jogo.iniciar_agente(nome_jogo, monitor=monitor, intervalo=4.0)

    if resposta:
        janela.atualizar_status("falando", resposta)
        discord_bot.atualizar_status_discord("falando")
        voz.falar(resposta)


# ─── MODO CONTROLE DE TELA (UI POR VOZ) ───
FRASES_ATIVAR_UI = (
    "modo controle de tela",
    "modo controle",
    "controle de tela",
    "modo ui",
    "modo mouse",
    "modo teclado",
    "controle o mouse",
    "controle a tela",
    "emily controle a tela",
    "emily controle o mouse",
)

FRASES_DESATIVAR_UI = (
    "sair do modo controle",
    "sair do controle",
    "desativa controle",
    "desativa controle de tela",
    "para o modo controle",
    "para o controle",
    "sair do modo ui",
    "sair da ui",
    "desativa modo ui",
    "desativa ui",
)


def _ativar_modo_ui():
    global modo_ui_ativo
    modo_ui_ativo = True
    frase = modelo.gerar_frase_acao("ativar_ui") or "Modo controle de tela ativado!"
    modelo.registrar_acao_no_historico("Ativou o modo controle de tela (UI)")
    voz.falar(frase)
    janela.atualizar_status("falando", frase)


def _desativar_modo_ui():
    global modo_ui_ativo
    modo_ui_ativo = False
    agente_ui.parar_agente_ui()
    frase = modelo.gerar_frase_acao("desativar_ui") or "Saindo do modo controle de tela."
    modelo.registrar_acao_no_historico("Desativou o modo controle de tela (UI)")
    voz.falar(frase)
    janela.atualizar_status("aguardando")


def _processar_modo_ui(texto: str) -> bool:
    """Processa a entrada quando o modo de controle de tela está ativo.
    Retorna True se tratou a entrada, False se deve continuar o fluxo normal."""
    global modo_ui_ativo

    texto_norm = texto.lower().strip()

    # Desativar o modo UI
    if any(frase in texto_norm for frase in FRASES_DESATIVAR_UI):
        _desativar_modo_ui()
        return True

    # Parar ações do agente UI
    if any(p in texto_norm for p in ("para", "para aí", "para ai", "cancela", "interrompe", "stop")):
        if agente_ui.status_agente_ui() != "Agente de UI: parado":
            agente_ui.parar_agente_ui()
            frase_parar = modelo.gerar_frase_acao("agente_ui_parando") or "Parei!"
            modelo.registrar_acao_no_historico("Parou o controle da tela")
            voz.falar(frase_parar)
            return True

    # ── CORREÇÃO AO VIVO: PAUSA → injeta instrução → RETOMA (contexto preservado) ──
    if agente_ui.status_agente_ui() != "Agente de UI: parado":
        print(f"[AGENTE_UI] Interrupção ao vivo: '{texto}' — pausando e injetando instrução...")
        agente_ui.pausar_agente_ui()
        # Avisa que ouviu
        voz.falar("Ok, anotei!")
        janela.atualizar_status("falando", f"Instrução ao vivo: {texto[:60]}")
        # Injeta a nova instrução no contexto do agente sem parar
        agente_ui.enviar_mensagem_ao_vivo(texto)
        # Retoma de onde parou, agora com a nova instrução no contexto
        agente_ui.retomar_agente_ui()
        return True

    # Qualquer outra coisa vai pro agente de UI (nova tarefa)
    janela.atualizar_status("falando", f"Controle de tela: {texto}")
    resposta = agente_ui.iniciar_agente_ui(texto, callback_falar=voz.falar)
    if resposta:
        voz.falar(resposta)
    return True


def restaurar_status():
    janela.atualizar_status("aguardando")
    # Volta o status do Discord para "aguardando" também
    discord_bot.atualizar_status_discord("aguardando")


def processar_texto_digitado(texto):
    global ultimo_uso_usuario, modo_ui_ativo
    ultimo_uso_usuario = time.time()
    emily_ocupada.set()
    try:
        texto_norm = texto.lower().strip()

        # Ativar modo UI por texto
        if not modo_ui_ativo and any(frase in texto_norm for frase in FRASES_ATIVAR_UI):
            _ativar_modo_ui()
            emily_ocupada.clear()
            return

        # Desativar modo UI por texto
        if modo_ui_ativo and any(frase in texto_norm for frase in FRASES_DESATIVAR_UI):
            _desativar_modo_ui()
            emily_ocupada.clear()
            return

        # Se estiver no modo UI, tudo vai pro agente de UI
        if modo_ui_ativo:
            _processar_modo_ui(texto)
            emily_ocupada.clear()
            return

        janela.atualizar_status("ouvindo", f'Você escreveu: "{texto}"')
        
        if modelo.precisa_gerar_imagem(texto):
            janela.atualizar_status("gerando", "Gerando imagem...")
            discord_bot.atualizar_status_discord("gerando")
            frase_img = modelo.gerar_frase_acao("gerar_imagem", texto) or "Um segundo, deixa eu criar essa imagem!"
            voz.falar(frase_img)

            prompt_otimizado = modelo.extrair_prompt_imagem(texto)
            caminho = imagem.gerar_imagem(prompt_otimizado)

            if caminho:
                janela.add_imagem_chat_safe(caminho, "emily")
                janela.mostrar_opcao_salvar(caminho)
                resposta = "Pronto Vitor, criada! Apareceu ali no chat. Quer salvar?"
                modelo.registrar_acao_no_historico(f"Gerou imagem para: {texto}", "imagem criada com sucesso")
            else:
                resposta = "Eita, não consegui gerar a imagem agora. Tenta de novo!"

            janela.atualizar_status("falando", resposta)
            discord_bot.atualizar_status_discord("falando")
            voz.falar(resposta)
            restaurar_status()
            emily_ocupada.clear()
            return
        
        # ─── DOWNLOAD PENDENTE ───
        if automacao.obter_download_pendente():
            texto_lower = texto.lower()
            if any(p in texto_lower for p in ("sim", "pode", "extrai", "claro", "vai", "ok", "tá")):
                janela.atualizar_status("ouvindo", "Extraindo...")
                resultado = automacao.extrair_download_pendente()
                if resultado:
                    janela.atualizar_status("falando", resultado)
                    discord_bot.atualizar_status_discord("falando")
                    voz.falar(resultado)
                restaurar_status()
                emily_ocupada.clear()
                return
            elif any(p in texto_lower for p in ("não", "nao", "deixa", "agora não")):
                automacao.limpar_download_pendente()
                voz.falar("Tudo bem, deixa lá!")
                restaurar_status()
                emily_ocupada.clear()
                return
      
        # ─── PEDIDO DE JOGO ───
        if _pedido_para_jogar(texto):
            _iniciar_agente_jogo(texto)
            restaurar_status()
            emily_ocupada.clear()
            return

        resposta_automacao = automacao.executar_comando(texto, callback_falar=voz.falar)
        if resposta_automacao is not None:
           if resposta_automacao:
               modelo.registrar_acao_no_historico(f"Executou comando: {texto}", resposta_automacao[:120])
               janela.atualizar_status("falando", resposta_automacao)
               discord_bot.atualizar_status_discord("falando")
               voz.falar(resposta_automacao)
           restaurar_status()
           return

        # ─── FALLBACK INTELIGENTE (modo texto digitado) ───
        intencao_txt = modelo.avaliar_intencao_fallback(texto, historico_conversa=modelo.historico)
        print(f"[FALLBACK] Intenção detectada (texto): {intencao_txt}")

        if intencao_txt["acao"] != "conversa" and intencao_txt["confianca"] == "alta":
            acao_fb = intencao_txt["acao"]
            param_fb = intencao_txt["parametro"]

            # ─── EXECUTAR NA TELA (agente_ui multi-passo) ───
            if acao_fb == "executar_na_tela":
                objetivo_ui = param_fb if param_fb else texto
                janela.atualizar_status("falando", f"Executando na tela: {objetivo_ui[:60]}")
                frase_ui = modelo.gerar_frase_acao("agente_ui_iniciando", objetivo_ui) or "Vou fazer isso na tela!"
                voz.falar(frase_ui)
                agente_ui.iniciar_agente_ui(objetivo_ui, callback_falar=voz.falar)
                restaurar_status()
                emily_ocupada.clear()
                return

            if acao_fb == "ativar_modo_escrito":
                modo_escrito_ativo = True
                resposta = "Modo escrito ativado! Pode falar que eu escrevo pra você."
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                return

            elif acao_fb == "desativar_modo_escrito":
                modo_escrito_ativo = False
                resposta = "Modo escrito desativado!"
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                return

            elif acao_fb == "ativar_modo_ui":
                _ativar_modo_ui()
                emily_ocupada.clear()
                return

            elif acao_fb == "desativar_modo_ui":
                _desativar_modo_ui()
                emily_ocupada.clear()
                return

            elif acao_fb == "ativar_modo_jogo":
                modo_jogo_ativo.set()
                visao_ativa.set()
                resposta = "Tô de olho no jogo agora, Vitor. Só vou falar quando acontecer algo importante."
                janela.atualizar_status("monitorando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                return

            elif acao_fb == "desativar_modo_jogo":
                modo_jogo_ativo.clear()
                visao_ativa.clear()
                resposta = "Parei de monitorar o jogo."
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                return

            elif acao_fb == "ouvir_discord":
                discord_bot.ativar_escuta_discord()
                resposta = "Tô de olho no Discord agora, Vitor!"
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                return

            elif acao_fb == "parar_discord":
                discord_bot.desativar_escuta_discord()
                resposta = "Parei de ouvir o Discord!"
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                return

            elif acao_fb == "jogar_jogo":
                _iniciar_agente_jogo(param_fb or texto)
                restaurar_status()
                emily_ocupada.clear()
                return

            elif acao_fb == "guardar_fato":
                modelo.guardar_fato_manual(texto)
                resposta = "Anotei, vou lembrar disso!"
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                return

            elif acao_fb == "definir_nome":
                if param_fb:
                    mem["nome_usuario"] = param_fb.strip().title()
                    memoria.salvar_memoria(mem)
                    modelo.atualizar_memoria(mem)
                    resposta = f"Anotei! Vou te chamar de {param_fb.strip().title()} então!"
                    janela.atualizar_status("falando", resposta)
                    voz.falar(resposta)
                    restaurar_status()
                    emily_ocupada.clear()
                    return

            elif acao_fb == "gerar_imagem":
                janela.atualizar_status("gerando", "Gerando imagem...")
                discord_bot.atualizar_status_discord("gerando")
                voz.falar("Um segundo, deixa eu criar essa imagem pra você!")
                prompt_otimizado = modelo.extrair_prompt_imagem(param_fb or texto)
                caminho = imagem.gerar_imagem(prompt_otimizado)
                if caminho:
                    janela.add_imagem_chat_safe(caminho, "emily")
                    janela.mostrar_opcao_salvar(caminho)
                    resposta = "Pronto Vitor, criada! Apareceu ali no chat. Quer salvar?"
                else:
                    resposta = "Eita, não consegui gerar a imagem agora. Tenta de novo!"
                janela.atualizar_status("falando", resposta)
                discord_bot.atualizar_status_discord("falando")
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                return

            elif acao_fb == "ver_tela":
                # ── Ver/analisar a tela — NÃO usa agente_ui, só captura e descreve ──
                frase_ver = modelo.gerar_frase_analisando_tela(texto)
                janela.atualizar_status("ouvindo", "Olhando a tela...")
                voz.falar(frase_ver)
                imagem_tela = visao.capturar_tela()
                if imagem_tela:
                    pergunta_tela = param_fb if param_fb else texto
                    resposta_tela = modelo.analisar_tela_com_pergunta(imagem_tela, pergunta_tela)
                else:
                    resposta_tela = "Não consegui capturar a tela agora, Vitor."
                janela.atualizar_status("falando", resposta_tela)
                discord_bot.atualizar_status_discord("falando")
                voz.falar(resposta_tela)
                restaurar_status()
                emily_ocupada.clear()
                return

            elif acao_fb == "pesquisar_internet":
                janela.atualizar_status("ouvindo", "Pesquisando...")
                discord_bot.atualizar_status_discord("ouvindo")
                voz.falar("Um segundo, deixa eu pesquisar isso pra você!")
                query = param_fb if param_fb else texto
                resultado_pesquisa = pesquisa.pesquisar(query)
                print(f"[PESQUISA] Resultado obtido ({len(resultado_pesquisa)} chars): {resultado_pesquisa[:200]}...")
                # Passa o resultado pela LLM pra ela resumir — mensagem sem gatilhos de pesquisa
                mensagem_com_pesquisa = (
                    f"Pergunta do Vitor: \"{query}\"\n\n"
                    f"[DADOS JÁ COLETADOS]:\n{resultado_pesquisa}\n\n"
                    "Resuma os dados acima respondendo apenas o que é relevante para a pergunta do Vitor. "
                    "Seja direta e natural no seu jeito de falar."
                )
                print(f"[PESQUISA] Mensagem enviada pra LLM ({len(mensagem_com_pesquisa)} chars)")
                fila_frases_pesq = queue.Queue()
                janela.atualizar_status("ouvindo", "Analisando resultados...")
                discord_bot.atualizar_status_discord("ouvindo")

                def _gerar_pesq():
                    print("[PESQUISA] Iniciando conversar_stream com skip_pesquisa=True")
                    r = modelo.conversar_stream(
                        mensagem_com_pesquisa,
                        lambda f: janela.atualizar_status("falando", f),
                        fila_frases_pesq,
                        instrucao_extra="NÃO faça pesquisa. Os dados já foram fornecidos acima. Apenas resuma e responda com base neles.",
                        skip_pesquisa=True,
                    )
                    print(f"[PESQUISA] Resposta da LLM ({len(r or '')} chars): {(r or '')[:200]}")

                def _falar_pesq():
                    voz.falar_stream(
                        fila_frases_pesq,
                        lambda f: janela.atualizar_status("falando", f),
                    )

                discord_bot.atualizar_status_discord("falando")
                t_gp = threading.Thread(target=_gerar_pesq, daemon=True)
                t_fp = threading.Thread(target=_falar_pesq, daemon=True)
                t_gp.start()
                t_fp.start()
                t_gp.join()
                t_fp.join()
                restaurar_status()
                emily_ocupada.clear()
                return

            else:
                resposta_fb = automacao.executar_comando(
                    f"{param_fb}" if param_fb else texto,
                    callback_falar=voz.falar,
                    acao_forcada=acao_fb,
                )
                if resposta_fb is not None:
                    if resposta_fb:
                        janela.atualizar_status("falando", resposta_fb)
                        discord_bot.atualizar_status_discord("falando")
                        voz.falar(resposta_fb)
                    restaurar_status()
                    return
                # Se automacao não soube lidar, cai pra conversa normal

        fila_frases = queue.Queue()
        _resp_buf = []

        def gerar_resposta():
            r = modelo.conversar_stream(
                texto,
                lambda f: janela.atualizar_status("falando", f),
                fila_frases,
            )
            if r:
                _resp_buf.append(r)

        def falar_resposta():
            voz.falar_stream(
                fila_frases,
                lambda f: janela.atualizar_status("falando", f),
            )

        discord_bot.atualizar_status_discord("falando")
        t_gerar = threading.Thread(target=gerar_resposta, daemon=True)
        t_falar = threading.Thread(target=falar_resposta, daemon=True)
        t_gerar.start()
        t_falar.start()
        t_gerar.join()
        t_falar.join()

        # ─── MEMÓRIA: processa conversa em background ───
        if _resp_buf:
            memoria.processar_conversa_async(texto, _resp_buf[0])

        restaurar_status()
    except Exception as erro:
        print(f"Erro ao processar texto digitado: {erro}")
        restaurar_status()
    finally:
        emily_ocupada.clear()


janela.callback_texto = processar_texto_digitado
janela.callback_trocar_monitor = visao.trocar_monitor

servidor.definir_callback(processar_texto_digitado)

# Conecta a voz da Emily ao servidor web: toda fala vira áudio no celular também
voz.definir_callback_audio(servidor.receber_fala)

thread_servidor = threading.Thread(target=servidor.iniciar_servidor, daemon=True)
thread_servidor.start()


# ─────────────────────────────────────────────────────────────────
# CALLBACK DO DISCORD
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
        threading.Thread(target=_processar_discord_externo, args=(texto, display_name, user_id), daemon=True).start()

discord_bot.definir_callback_texto(callback_texto_discord)

def _processar_discord_externo(texto: str, nome: str, user_id: int = 0):
    emily_ocupada.set()
    try:
        janela.atualizar_status("ouvindo", f'[Discord] {nome}: "{texto}"')
        discord_bot.atualizar_status_discord("ouvindo")

        bloqueio = automacao.checar_bloqueio_externo(texto)
        if bloqueio:
            alvo   = bloqueio.get("alvo", "")
            mencao = f"<@{user_id}>" if user_id else ""
            resposta_troll = modelo.gerar_trollagem_discord(nome, alvo, mencao)
            discord_bot.enviar_texto_discord(resposta_troll)
            print(f"[Discord] Bloqueado '{bloqueio.get('acao')}' de {nome}.")
            restaurar_status()
            return

        resposta_automacao = automacao.executar_comando(texto, callback_falar=voz.falar)
        if resposta_automacao:
            resposta_final = f"{nome} pediu! {resposta_automacao}"
            janela.atualizar_status("falando", resposta_final)
            discord_bot.atualizar_status_discord("falando")
            voz.falar(resposta_final)
            restaurar_status()
            return

        # Conversa com LLM — usa instrução de resposta CURTA para Discord
        mensagem_com_contexto = (
            f"[{nome} está falando com você pelo Discord]: {texto}"
        )
        fila_frases = queue.Queue()

        def gerar_resposta():
            modelo.conversar_stream(
                mensagem_com_contexto,
                lambda f: janela.atualizar_status("falando", f),
                fila_frases,
                instrucao_extra=(
                    "IMPORTANTE: esta resposta vai pro Discord. "
                    "Seja bem direta e curta, no máximo 2 frases. "
                    "Só se estenda se for uma pergunta técnica ou situação que realmente exige mais detalhe."
                ),
            )

        def falar_resposta():
            voz.falar_stream(
                fila_frases,
                lambda f: janela.atualizar_status("falando", f),
            )

        discord_bot.atualizar_status_discord("falando")
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
    janela.atualizar_status("ouvindo", "Lendo a tela...")
    voz.falar("Um segundo, deixa eu ver o que tá na tela.")

    texto_tela = modelo.ler_instrucoes_da_tela()

    if not texto_tela or "SEM_INSTRUCOES" in texto_tela:
        voz.falar("Não encontrei instruções claras na tela, Vitor.")
        restaurar_status()
        return
        

    resultado = automacao.interpretar_sem_executar(texto_tela)

    if not resultado or resultado.get("acao") == "nenhuma":
        voz.falar("Li a tela mas não consegui transformar isso em ações que eu saiba fazer.")
        restaurar_status()
        return

    resumo = automacao.resumir_acoes(resultado)
    voz.falar(f"{resumo}. Posso fazer isso?")
    janela.atualizar_status("gravando", "Aguardando confirmação...")

    confirmacao = voz.ouvir_ptt(
        callback_gravando=lambda: janela.atualizar_status("gravando", "🔴 Gravando...")
    )

    if not confirmacao or not intencoes.confirma_encerramento(confirmacao):
        if confirmacao and any(p in confirmacao.lower() for p in ("sim", "pode", "vai", "faz", "confirmo", "ok", "tá")):
            pass
        else:
            voz.falar("Tudo bem, cancelado!")
            restaurar_status()
            return

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

            # ─── AGENTE UI RODANDO FORA DO MODO UI (fallback) — intercepta input ───
            # Quando o agente foi iniciado pelo fallback e o usuário fala algo:
            # PAUSA → injeta instrução no contexto → RETOMA (sem perder o que estava fazendo)
            if not modo_ui_ativo and agente_ui.status_agente_ui() != "Agente de UI: parado":
                print(f"[AGENTE_UI] Interrupção ao vivo (fora modo_ui): '{entrada}' — pausando e injetando instrução...")
                agente_ui.pausar_agente_ui()
                voz.falar("Ok, anotei!")
                janela.atualizar_status("falando", f"Instrução ao vivo: {entrada[:60]}")
                agente_ui.enviar_mensagem_ao_vivo(entrada)
                agente_ui.retomar_agente_ui()
                restaurar_status()
                emily_ocupada.clear()
                continue

            # ─── MODO CONTROLE DE TELA (UI) ───
            if not modo_ui_ativo and any(frase in entrada_lower for frase in FRASES_ATIVAR_UI):
                _ativar_modo_ui()
                emily_ocupada.clear()
                continue

            if modo_ui_ativo and any(frase in entrada_lower for frase in FRASES_DESATIVAR_UI):
                _desativar_modo_ui()
                emily_ocupada.clear()
                continue

            if modo_ui_ativo:
                _processar_modo_ui(entrada)
                emily_ocupada.clear()
                continue

            if "lembra que" in entrada_lower or "guarda que" in entrada_lower:
                modelo.guardar_fato_manual(entrada)
                resposta = modelo.gerar_frase_acao("guardar_fato", entrada) or "Anotei, vou lembrar disso!"
                modelo.registrar_acao_no_historico(f"Guardou fato: {entrada}", resposta)
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
            
            # ─── DOWNLOAD PENDENTE ───
            if automacao.obter_download_pendente():
                if any(p in entrada_lower for p in ("sim", "pode", "extrai", "claro", "vai", "ok", "tá")):
                    janela.atualizar_status("ouvindo", "Extraindo...")
                    resultado = automacao.extrair_download_pendente()
                    if resultado:
                        janela.atualizar_status("falando", resultado)
                        discord_bot.atualizar_status_discord("falando")
                        voz.falar(resultado)
                    restaurar_status()
                    emily_ocupada.clear()
                    continue
                elif any(p in entrada_lower for p in ("não", "nao", "deixa", "agora não")):
                    automacao.limpar_download_pendente()
                    voz.falar("Tudo bem, deixa lá!")
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
                frase_trad = modelo.gerar_frase_acao("traduzir", entrada) or "Deixa eu ver o que tem pra traduzir."
                voz.falar(frase_trad)
                resposta = modelo.traduzir_tela(entrada)
                modelo.registrar_acao_no_historico(f"Traduziu texto da tela (pedido: {entrada})", resposta[:100])
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                continue
            
            if modelo.precisa_gerar_imagem(entrada):
                janela.atualizar_status("gerando", "Gerando imagem...")
                discord_bot.atualizar_status_discord("gerando")
                frase_img = modelo.gerar_frase_acao("gerar_imagem", entrada) or "Um segundo, deixa eu criar essa imagem!"
                voz.falar(frase_img)

                prompt_otimizado = modelo.extrair_prompt_imagem(entrada)
                caminho = imagem.gerar_imagem(prompt_otimizado)

                if caminho:
                    janela.add_imagem_chat_safe(caminho, "emily")
                    janela.mostrar_opcao_salvar(caminho)
                    resposta = "Pronto Vitor, criada! Apareceu ali no chat. Quer salvar?"
                    modelo.registrar_acao_no_historico(f"Gerou imagem para: {entrada}", "imagem criada com sucesso")
                else:
                    resposta = "Eita, não consegui gerar a imagem agora. Tenta de novo!"

                janela.atualizar_status("falando", resposta)
                discord_bot.atualizar_status_discord("falando")
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                continue

            # ─── MODO JOGO (monitoramento de tela pra reagir) ───
            if not modo_jogo_ativo.is_set() and any(frase in entrada_lower for frase in FRASES_ATIVAR_JOGO):
                modo_jogo_ativo.set()
                visao_ativa.set()
                resposta = "Tô de olho no jogo agora, Vitor. Só vou falar quando acontecer algo importante."
                janela.atualizar_status("monitorando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                continue

            if modo_jogo_ativo.is_set() and any(frase in entrada_lower for frase in FRASES_DESATIVAR_JOGO):
                modo_jogo_ativo.clear()
                visao_ativa.clear()
                resposta = "Parei de monitorar o jogo."
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                continue

            # ─── PEDIDO DE JOGO ───
            if _pedido_para_jogar(entrada):
                _iniciar_agente_jogo(entrada)
                restaurar_status()
                emily_ocupada.clear()
                continue

            resposta_automacao = automacao.executar_comando(entrada, callback_falar=voz.falar)
            if resposta_automacao is not None:
               if resposta_automacao:
                  modelo.registrar_acao_no_historico(f"Executou comando: {entrada}", resposta_automacao[:120])
                  janela.atualizar_status("falando", resposta_automacao)
                  discord_bot.atualizar_status_discord("falando")
                  voz.falar(resposta_automacao)
               restaurar_status()
               emily_ocupada.clear()
               continue

            # ─── FALLBACK INTELIGENTE ───
            # Nenhuma palavra-chave detectou nada. Pergunta pra LLM se era um comando.
            intencao = modelo.avaliar_intencao_fallback(entrada, historico_conversa=modelo.historico)
            print(f"[FALLBACK] Intenção detectada: {intencao}")

            if intencao["acao"] != "conversa" and intencao["confianca"] == "alta":
                acao_fb = intencao["acao"]
                param_fb = intencao["parametro"]

                # ─── EXECUTAR NA TELA (agente_ui multi-passo) ───
                if acao_fb == "executar_na_tela":
                    objetivo_ui = param_fb if param_fb else entrada
                    janela.atualizar_status("falando", f"Executando na tela: {objetivo_ui[:60]}")
                    frase_ui = modelo.gerar_frase_acao("agente_ui_iniciando", objetivo_ui) or "Vou fazer isso na tela!"
                    voz.falar(frase_ui)
                    resposta_ui = agente_ui.iniciar_agente_ui(objetivo_ui, callback_falar=voz.falar)
                    # A frase de início já foi falada manualmente, não fala de novo
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                # Reconstrói um texto de comando mais claro pra passar pra automacao
                texto_reconstruido = f"{acao_fb} {param_fb}".strip() if param_fb else acao_fb

                # Trata ações especiais de modo que não passam pela automacao
                if acao_fb == "ativar_modo_escrito":
                    modo_escrito_ativo = True
                    resposta = "Modo escrito ativado! Pode falar que eu escrevo pra você."
                    janela.atualizar_status("falando", resposta)
                    voz.falar(resposta)
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "desativar_modo_escrito":
                    modo_escrito_ativo = False
                    resposta = "Modo escrito desativado!"
                    janela.atualizar_status("falando", resposta)
                    voz.falar(resposta)
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "ativar_modo_ui":
                    _ativar_modo_ui()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "desativar_modo_ui":
                    _desativar_modo_ui()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "ativar_modo_jogo":
                    modo_jogo_ativo.set()
                    visao_ativa.set()
                    resposta = "Tô de olho no jogo agora, Vitor. Só vou falar quando acontecer algo importante."
                    janela.atualizar_status("monitorando", resposta)
                    voz.falar(resposta)
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "desativar_modo_jogo":
                    modo_jogo_ativo.clear()
                    visao_ativa.clear()
                    resposta = "Parei de monitorar o jogo."
                    janela.atualizar_status("falando", resposta)
                    voz.falar(resposta)
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "ouvir_discord":
                    discord_bot.ativar_escuta_discord()
                    resposta = "Tô de olho no Discord agora, Vitor!"
                    janela.atualizar_status("falando", resposta)
                    voz.falar(resposta)
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "parar_discord":
                    discord_bot.desativar_escuta_discord()
                    resposta = "Parei de ouvir o Discord!"
                    janela.atualizar_status("falando", resposta)
                    voz.falar(resposta)
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "jogar_jogo":
                    _iniciar_agente_jogo(param_fb or entrada)
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "guardar_fato":
                    modelo.guardar_fato_manual(entrada)
                    resposta = "Anotei, vou lembrar disso!"
                    janela.atualizar_status("falando", resposta)
                    voz.falar(resposta)
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "definir_nome":
                    if param_fb:
                        mem["nome_usuario"] = param_fb.strip().title()
                        memoria.salvar_memoria(mem)
                        modelo.atualizar_memoria(mem)
                        resposta = f"Anotei! Vou te chamar de {param_fb.strip().title()} então!"
                        janela.atualizar_status("falando", resposta)
                        voz.falar(resposta)
                        restaurar_status()
                        emily_ocupada.clear()
                        continue

                elif acao_fb == "gerar_imagem":
                    janela.atualizar_status("gerando", "Gerando imagem...")
                    discord_bot.atualizar_status_discord("gerando")
                    voz.falar("Um segundo, deixa eu criar essa imagem pra você!")
                    prompt_otimizado = modelo.extrair_prompt_imagem(param_fb or entrada)
                    import gerador_imagem as imagem_fb
                    caminho = imagem_fb.gerar_imagem(prompt_otimizado)
                    if caminho:
                        janela.add_imagem_chat_safe(caminho, "emily")
                        janela.mostrar_opcao_salvar(caminho)
                        resposta = "Pronto Vitor, criada! Apareceu ali no chat. Quer salvar?"
                    else:
                        resposta = "Eita, não consegui gerar a imagem agora. Tenta de novo!"
                    janela.atualizar_status("falando", resposta)
                    discord_bot.atualizar_status_discord("falando")
                    voz.falar(resposta)
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "ver_tela":
                    # ── Ver/analisar a tela — NÃO usa agente_ui, só captura e descreve ──
                    frase_ver = modelo.gerar_frase_analisando_tela(entrada)
                    janela.atualizar_status("ouvindo", "Olhando a tela...")
                    voz.falar(frase_ver)
                    imagem_tela = visao.capturar_tela()
                    if imagem_tela:
                        pergunta_tela = param_fb if param_fb else entrada
                        resposta_tela = modelo.analisar_tela_com_pergunta(imagem_tela, pergunta_tela)
                    else:
                        resposta_tela = "Não consegui capturar a tela agora, Vitor."
                    janela.atualizar_status("falando", resposta_tela)
                    discord_bot.atualizar_status_discord("falando")
                    voz.falar(resposta_tela)
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "pesquisar_internet":
                    janela.atualizar_status("ouvindo", "Pesquisando...")
                    discord_bot.atualizar_status_discord("ouvindo")
                    voz.falar("Um segundo, deixa eu pesquisar isso pra você!")
                    query = param_fb if param_fb else entrada
                    resultado_pesquisa = pesquisa.pesquisar(query)
                    # Passa o resultado pela LLM pra ela resumir — mensagem sem gatilhos de pesquisa
                    mensagem_com_pesquisa = (
                        f"Pergunta do Vitor: \"{query}\"\n\n"
                        f"[DADOS JÁ COLETADOS]:\n{resultado_pesquisa}\n\n"
                        "Resuma os dados acima respondendo apenas o que é relevante para a pergunta do Vitor. "
                        "Seja direta e natural no seu jeito de falar."
                    )
                    fila_frases_pesq = queue.Queue()
                    janela.atualizar_status("ouvindo", "Analisando resultados...")
                    discord_bot.atualizar_status_discord("ouvindo")

                    def _gerar_pesq_voz():
                        modelo.conversar_stream(
                            mensagem_com_pesquisa,
                            lambda f: janela.atualizar_status("falando", f),
                            fila_frases_pesq,
                            instrucao_extra="NÃO faça pesquisa. Os dados já foram fornecidos acima. Apenas resuma e responda com base neles.",
                            skip_pesquisa=True,
                        )

                    def _falar_pesq_voz():
                        voz.falar_stream(
                            fila_frases_pesq,
                            lambda f: janela.atualizar_status("falando", f),
                        )

                    discord_bot.atualizar_status_discord("falando")
                    t_gp = threading.Thread(target=_gerar_pesq_voz, daemon=True)
                    t_fp = threading.Thread(target=_falar_pesq_voz, daemon=True)
                    t_gp.start()
                    t_fp.start()
                    t_gp.join()
                    t_fp.join()
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                else:
                    # Tenta executar via automacao com o texto original
                    # (abrir_app, abrir_site, fechar_app, etc.)
                    resposta_fb = automacao.executar_comando(
                        f"{param_fb}" if param_fb else entrada,
                        callback_falar=voz.falar,
                        acao_forcada=acao_fb,
                    )
                    if resposta_fb is not None:
                        if resposta_fb:
                            janela.atualizar_status("falando", resposta_fb)
                            discord_bot.atualizar_status_discord("falando")
                            voz.falar(resposta_fb)
                        restaurar_status()
                        emily_ocupada.clear()
                        continue
                    # Se automacao não soube lidar, cai pra conversa normal

            global ultimo_uso_usuario
            ultimo_uso_usuario = time.time()
            janela.atualizar_status("ouvindo", f'Você disse: "{entrada}"')
            discord_bot.atualizar_status_discord("ouvindo")
            time.sleep(0.2)

            fila_frases = queue.Queue()
            _voz_resp_buf = []

            def gerar_resposta():
                r = modelo.conversar_stream(
                    entrada,
                    lambda f: janela.atualizar_status("falando", f),
                    fila_frases,
                )
                if r:
                    _voz_resp_buf.append(r)

            def falar_resposta():
                voz.falar_stream(
                    fila_frases,
                    lambda f: janela.atualizar_status("falando", f),
                )

            discord_bot.atualizar_status_discord("falando")
            t_gerar = threading.Thread(target=gerar_resposta, daemon=True)
            t_falar = threading.Thread(target=falar_resposta, daemon=True)
            t_gerar.start()
            t_falar.start()
            t_gerar.join()
            t_falar.join()

            # ─── MEMÓRIA: processa conversa de voz em background ───
            if _voz_resp_buf:
                memoria.processar_conversa_async(entrada, _voz_resp_buf[0])

            restaurar_status()

        except Exception as erro:
            print(f"Erro ao processar entrada: {erro}")
            restaurar_status()
        finally:
            emily_ocupada.clear()


def loop_visao():
    COOLDOWN_COMENTARIO = 1
    ultimo_comentario = 0
    ultimo_evento_jogo = ""

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

            # Captura rápida: 2 frames com intervalo mínimo, igual ao agente_ui
            imagens = visao.capturar_sequencia_telas_rapida(quantidade=2, intervalo=0.3)
            frame_atual = imagens[0]

            if modo_jogo_ativo.is_set():
                vale_comentar = modelo.triar_tela_jogo(frame_atual)
                comentario = modelo.analisar_tela_jogo(frame_atual, contexto=[ultimo_evento_jogo]) if vale_comentar else None
            else:
                vale_comentar = modelo.triar_tela(frame_atual)
                comentario = modelo.analisar_sequencia_telas(imagens) if vale_comentar else None

            if not vale_comentar or not comentario:
                time.sleep(3)
                continue

            # Evita repetir o mesmo comentário de jogo em sequência
            if modo_jogo_ativo.is_set() and comentario == ultimo_evento_jogo:
                time.sleep(3)
                continue
            if modo_jogo_ativo.is_set():
                ultimo_evento_jogo = comentario

            if not emily_ocupada.is_set() and not voz.falar_ativo.is_set():
                emily_ocupada.set()
                ultimo_comentario = time.time()
                try:
                    janela.atualizar_status("falando", comentario)
                    discord_bot.atualizar_status_discord("falando")
                    voz.falar(comentario)
                finally:
                    emily_ocupada.clear()
                    if modo_jogo_ativo.is_set():
                        janela.atualizar_status("monitorando")
                    else:
                        janela.atualizar_status("aguardando")
                    discord_bot.atualizar_status_discord("aguardando")

            time.sleep(3)
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
        notificacoes.parar_monitor()
    except:
        pass
    try:
        discord_bot.desconectar_voz()
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
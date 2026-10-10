import queue
import os
import re
import threading
import time
from typing import Optional

_MODO_PUBLICO = os.getenv("EMILY_PUBLIC_MODE") == "1"

# No Windows o primeiro import de uma lib de tela fixa a consciência de DPI do
# processo. Faça-o antes de carregar os módulos que importam pyautogui/mss.
import desktop_backend as _desktop_backend
_desktop_backend._configurar_dpi_windows()

# O Konsole carrega PATH e mostra stdout; atalhos .desktop não garantem nenhum
# dos dois. Normalize antes de importar módulos que iniciam processos e grave
# sempre o mesmo log que a interface consegue abrir.
import servicos_runtime as _servicos_runtime
import emily_logs as _emily_logs

def _aquecer_memoria_no_boot() -> None:
    """
    Consulta a memória unificada UMA VEZ em thread de fundo, no boot.

    Por que existe: a PRIMEIRA busca depois de abrir a Emily paga dois
    cold-loads em série — o Chroma abrindo a coleção e o Ollama carregando o
    embedding (medido: 10,4s na primeira consulta, contra 0,1–0,4s aquecida).
    Sem isto o Vitor falava "oi" logo após abrir a Emily e o turno inteiro
    esperava o embedding carregar. Em thread: o boot NÃO pode esperar memória.
    """
    def rodar():
        try:
            import memoria_unificada as mu
            if not mu.ponte_ativa():
                return
            mu.ponte().bloco_contexto(mu.dono_id(), "aquecimento do boot",
                                      memory_pool="general")
            print("[MEMORIA-UNIFICADA] aquecida (coleção e embedding na RAM)")
        except Exception as erro:  # noqa: BLE001 - aquecimento é melhoria
            print(f"[MEMORIA-UNIFICADA] aquecimento falhou (seguindo): "
                  f"{type(erro).__name__}: {erro}")
    threading.Thread(target=rodar, name="memoria-aquecimento",
                     daemon=True).start()


def _aquecer_provedor_llm_no_boot() -> None:
    """
    Abre a conexão com o provedor ATIVO em thread de fundo, no boot.

    Por que existe: a PRIMEIRA chamada de LLM de cada sessão paga o handshake
    frio (DNS + TCP + TLS) contra o provedor. Medido no relay da Anthropic do
    .env: 4,8–10,6s na primeira chamada contra 1,8–2,4s com a conexão quente.
    Sem isto, o Vitor abria a Emily, falava algo e o primeiro turno levava o
    dobro do tempo — o handshake ia junto com a resposta.

    Uma requisição mínima (1 token) já deixa o socket pronto no pool de
    keep-alive. Em thread: o boot não espera o provedor responder.
    """
    def rodar():
        try:
            import llm
            # Rota 'classificador': max_tokens=16, temperatura 0 e raciocínio
            # desligado — é a chamada mais barata que existe na Emily. Serve
            # só para estabelecer o socket, o texto não é usado.
            llm.chamar([{"role": "user", "content": "ok"}],
                       rota_nome="classificador", max_tokens=1)
            print(f"[LLM] provedor '{llm.TABELA_ATIVA}' aquecido "
                  "(conexão pronta no pool)")
        except Exception as erro:  # noqa: BLE001 - aquecimento é melhoria
            print(f"[LLM] aquecimento do provedor falhou (seguindo): "
                  f"{type(erro).__name__}: {erro}")
    threading.Thread(target=rodar, name="llm-aquecimento", daemon=True).start()


_servicos_runtime.preparar_ambiente()
_emily_logs.configurar()
# Aquece a memória unificada em background: a primeira consulta paga o
# cold-load do Chroma + embedding do Ollama (10,4s medidos). Em thread, o
# boot não espera nada.
if not _MODO_PUBLICO:
    _aquecer_memoria_no_boot()

# ─────────────────────────────────────────────────────────────────
# BOOTSTRAP LINUX — tem que vir ANTES dos imports abaixo.
#
# No Linux a lib `keyboard` real exige root e o automacao.py foi escrito
# pra Windows, então aqui a gente troca os módulos problemáticos por
# wrappers compatíveis antes de qualquer um deles ser importado.
# No Windows nada disso entra em cena.
# ─────────────────────────────────────────────────────────────────
import sys as _sys
import platform_compat as _platform_compat

if _platform_compat.is_linux():
    import compat_imports as _compat
    _sys.modules["keyboard"] = _compat.keyboard
    _sys.modules["pyperclip"] = _compat.pyperclip
    print("[MAIN] Linux detectado — imports de teclado/clipboard redirecionados pra camada de compatibilidade")

# ─── PREFLIGHT DO ATUALIZADOR ───
#
# O botão "Atualizar agora" ensaia a atualização rodando ESTE executável com
# os módulos novos no lugar (EMILY_OVERRIDE_DIR) e EMILY_PREFLIGHT=1. Aqui a
# Emily importa TUDO e sai com 0 (ok) ou 1 (algo não importa — biblioteca
# nova que o pacote não tem → o botão avisa que precisa recompilar, em vez de
# aplicar uma atualização que quebraria a Emily). No uso normal, essa env não
# existe e nada aqui roda.
if os.environ.get("EMILY_PREFLIGHT"):
    import atualizador_emily as _atualizador
    _sys.exit(_atualizador.rodar_preflight())

import automacao
import intencoes
import memoria
import modelo
import orquestrador_voz
import estilo_vitor
import navegador
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
try:
    from hollow_knight_emily.python import hollow_knight_ponte
except Exception as _erro_hk_import:  # integração opcional, nunca impede o boot
    hollow_knight_ponte = None
    print(f"[HOLLOW-KNIGHT] ponte indisponível no import: {_erro_hk_import}")

import unicodedata as _unicodedata

def _normalizar_simples(t: str) -> str:
    """Remove acentos e coloca em minúsculas — usado para comparar frases."""
    t = _unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if _unicodedata.category(c) != "Mn")
    return t.lower().strip()

mem = memoria.carregar_memoria()
modelo.atualizar_memoria(mem)

# Aplica as escolhas do Vitor (provedor, modelo e raciocínio da conversa) que
# ficaram salvas da última vez que ele mexeu no composer. Nome e personalidade
# extra são lidos on-the-fly pelo modelo._system_base(), então não precisam disto.
# Tolerante a falha: se prefs quebrar, a Emily abre com o padrão de fábrica.
try:
    import llm
    import preferencias
    _prefs = preferencias.carregar()
    _provedor = (_prefs.get("provedor") or "").strip()
    _modelo = (_prefs.get("modelo") or "").strip()
    if _provedor:
        # Pref salva de provedor manda no start: sem isto, o EMILY_PROVEDOR_LLM
        # do .env voltaria a vencer a cada abertura e a Emily abriria com o
        # provedor errado (modelo de um provedor caindo na rota de outro ->
        # 400 "not a valid model ID", medido na migração).
        if not llm.definir_provedor_e_modelo(_provedor, _modelo):
            print(f"[MAIN] provedor '{_provedor}' das preferências não aplicado; usando o do .env")
    else:
        llm.definir_modelo_conversa(_modelo)
    llm.definir_raciocinio_conversa(_prefs.get("raciocinio", ""))
except Exception as _erro_prefs:  # noqa: BLE001
    print(f"[MAIN] não apliquei as preferências salvas: {_erro_prefs}")

automacao.inicializar()
import discord_monitor
if not _MODO_PUBLICO:
    discord_monitor.preparar_legado()
    discord_bot.inicializar()
else:
    from pathlib import Path as _PerfilPath
    from emily_primeiro_inicio import carregar as _carregar_perfil_publico
    _perfil_publico = (_carregar_perfil_publico(_PerfilPath(os.environ["EMILY_PUBLIC_CONFIG"]).parent)
                       if os.getenv("EMILY_PUBLIC_CONFIG") else None)
    _discord_publico = (_perfil_publico or {}).get("discord", {})
    if _discord_publico.get("ativo"):
        from emily_discord_publico import iniciar as _iniciar_discord_publico
        _iniciar_discord_publico(_discord_publico)

# ─────────────────────────────────────────────
# QUAL INTERFACE
#
# A nova (interface_web.py) é HTML/CSS/JS numa WebView2. A antiga
# (interface.py, PyQt6) fica no projeto e volta com EMILY_UI=qt — o
# contrato das duas é o mesmo nove pontos, então quem está abaixo daqui
# não sabe qual está rodando.
#
# O fallback é automático: se o pywebview não estiver instalado ou a
# WebView2 faltar, a Emily abre na antiga em vez de não abrir.
# ─────────────────────────────────────────────
_UI = os.getenv("EMILY_UI", "web").strip().lower()
if _UI == "qt":
    import interface
else:
    try:
        import interface_web as interface
    except Exception as _erro_ui:  # noqa: BLE001
        print(f"[MAIN] interface web indisponível ({type(_erro_ui).__name__}: "
              f"{_erro_ui}); abrindo a antiga.")
        import interface

janela = interface.JanelaEmily()


def _preferencias_recebidas(dados: dict) -> None:
    """Ajusta o modelo vivo e redesenha a identidade após a sync entre PCs."""
    try:
        import discord_monitor
        discord_monitor.aplicar()
    except Exception as exc:
        print(f"[PREFERENCIAS] escuta do Discord não atualizada: {exc}")
    try:
        if dados.get("provedor"):
            llm.definir_provedor_e_modelo(dados["provedor"], dados.get("modelo") or "")
        llm.definir_raciocinio_conversa(dados.get("raciocinio") or "baixo")
        if hasattr(janela, "_push"):
            janela._push("preferencias_sync", {})
    except Exception as exc:
        print(f"[PREFERENCIAS] atualização ao vivo falhou: {exc}")


preferencias.observar_alteracoes(_preferencias_recebidas)
# ── MODO REMOTO: capturar a resposta do turno pra devolver ao celular ──
# O celular pode pedir pra EMILY DO PC executar um comando (botão de PC no chat
# do app). A resposta daqui passa pela janela (atualizar_status com status
# "falando") — um interceptor junta as frases do turno remoto e entrega pro
# servidor devolver ao celular no fim do turno. O registro na conversa fica
# DESLIGADO nesse turno: quem digitou foi o celular, a conversa é de lá.
_remota_ativa = False
_remota_frases = []

def _remota_inicio():
    global _remota_ativa, _remota_frases
    _remota_ativa = True
    _remota_frases = []
    janela.sem_registro_remoto = True

def _remota_fim():
    global _remota_ativa
    _remota_ativa = False
    janela.sem_registro_remoto = False
    try:
        import servidor as _srv
        _srv.entregar_resposta_remota(" ".join(_remota_frases).strip())
    except Exception as _e:
        print(f"[REMOTA] nao consegui devolver a resposta: {_e}")

_janela_status_original = janela.atualizar_status

def _atualizar_status_com_captura(status, texto=""):
    try:
        if _remota_ativa and status == "falando" and texto:
            _remota_frases.append(texto)
    except Exception:
        pass
    _janela_status_original(status, texto)

janela.atualizar_status = _atualizar_status_com_captura
automacao.definir_callback_status(janela.atualizar_status)   # agora com captura
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
if not _MODO_PUBLICO:
    notificacoes.iniciar_monitor()
      
      
emily_ocupada = threading.Event()
visao_ativa = threading.Event()
modo_escrito_ativo = False
modo_ui_ativo = False
modo_jogo_ativo = threading.Event()
modo_assistir_tela_ativo = threading.Event()
timer_assistir_tela = None

ultimo_uso_usuario = 0
COOLDOWN_VISAO = 10

# Orquestrador exclusivo do PTT no PC. Não é usado por chat escrito, Discord,
# Android ou agentes. O catálogo rápido é montado uma vez no boot.
_orquestrador_voz = orquestrador_voz.OrquestradorVoz()
_trava_aviso_delegacao = threading.Lock()


def _voz_delegacao_rapida_ativa() -> bool:
    """Preferência do PTT local; lida a cada turno para dispensar reinício."""
    try:
        return bool(preferencias.obter("voz_delegacao_rapida", True))
    except Exception as erro:
        print(f"[VOZ] não consegui ler modo de delegação: {erro}")
        return True


def _executar_turno_voz_pc(texto: str) -> str:
    """Seleciona somente a rota do PTT, mantendo o chat e o Android intactos."""
    if _voz_delegacao_rapida_ativa():
        return _executar_turno_voz_rapido(texto)
    return _executar_turno_com_ferramentas(texto, canal="voz")


def _pc_livre_para_aviso_delegacao() -> bool:
    """Aviso espontâneo pode falar; nunca abre microfone nem interrompe um turno."""
    return (
        _voz_delegacao_rapida_ativa()
        and not emily_ocupada.is_set()
        and not voz.falar_ativo.is_set()
        and not voz.escutando_ativo.is_set()
    )


def _falar_aviso_delegacao(texto: str, eh_resultado: bool) -> bool:
    """Saída espontânea exclusivamente por voz, serializada com o resto do PC."""
    texto = (texto or "").strip()
    if not texto:
        return False
    with _trava_aviso_delegacao:
        if not _pc_livre_para_aviso_delegacao():
            return False
        emily_ocupada.set()
        try:
            # Reconfere os eventos de áudio depois de reservar o runtime. O PTT
            # pode ter começado entre o teste acima e o set() do evento.
            if (not _voz_delegacao_rapida_ativa()
                    or voz.falar_ativo.is_set() or voz.escutando_ativo.is_set()):
                return False
            print(
                "[VOZ-RAPIDA] entregando resultado espontâneo"
                if eh_resultado else
                "[VOZ-RAPIDA] falando atualização espontânea"
            )
            # Reserva a saída ANTES de entrar em voz.falar(). Sem isto existe
            # uma janela minúscula em que o MB5 acorda do wait, abre o microfone
            # e só depois o TTS seta falar_ativo — gravando a própria Emily.
            voz.falar_ativo.set()
            try:
                voz.falar(texto)
            finally:
                voz.falar_ativo.clear()
            _orquestrador_voz.registrar_aviso_emitido(texto)
            return True
        finally:
            emily_ocupada.clear()
            restaurar_status()

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

FRASES_DESATIVAR_ASSISTIR_TELA = (
    "para de olhar minha tela",
    "para de olhar a tela",
    "para de assistir a tela",
    "para de assistir minha tela",
    "pode parar de olhar",
    "pode parar de assistir",
    "desativa assistir tela",
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


# ─────────────────────────────────────────────
# HANDLERS DAS FERRAMENTAS DE MODO
#
# As ferramentas de automação (abrir app, pesquisar, ver tela) chamam o código
# de automacao.py direto. Já os MODOS da Emily mexem em estado global daqui:
# threads, eventos e status da janela. Então ferramentas.py não os conhece —
# o main.py registra um handler e a ferramenta chama o que foi registrado.
#
# Estes handlers só mudam o estado e devolvem uma frase factual. Não falam:
# quem fala é o modelo, que recebe esse retorno e comenta no jeito da Emily.
# Se eles falassem, a Emily diria duas coisas seguidas.
# ─────────────────────────────────────────────

def _registrar_ferramentas_de_modo():
    import ferramentas

    def escrito_on():
        global modo_escrito_ativo
        modo_escrito_ativo = True
        return "Modo escrito ligado. Agora digito o que o Vitor falar."

    def escrito_off():
        global modo_escrito_ativo
        modo_escrito_ativo = False
        return "Modo escrito desligado."

    def ui_on():
        global modo_ui_ativo
        modo_ui_ativo = True
        modelo.registrar_acao_no_historico("Ativou o modo controle de tela (UI)")
        janela.atualizar_status("falando")
        return "Modo de controle de tela ligado."

    def ui_off():
        global modo_ui_ativo
        modo_ui_ativo = False
        agente_ui.parar_agente_ui()
        modelo.registrar_acao_no_historico("Desativou o modo controle de tela (UI)")
        return "Modo de controle de tela desligado."

    def jogo_on():
        if modo_assistir_tela_ativo.is_set():
            return "Eu já estou assistindo sua tela! Pare o monitoramento contínuo primeiro se quiser o modo jogo."
        modo_jogo_ativo.set()
        visao_ativa.set()
        janela.atualizar_status("monitorando")
        return "Monitoramento de jogo ligado. Só vou falar quando algo marcante acontecer."

    def jogo_off():
        modo_jogo_ativo.clear()
        visao_ativa.clear()
        return "Monitoramento de jogo desligado."

    def assistir_tela_on(duracao_segundos=120):
        global timer_assistir_tela
        if modo_jogo_ativo.is_set():
            return "O monitoramento de jogo já está ligado, não posso iniciar os dois juntos."
        
        modo_assistir_tela_ativo.set()
        visao_ativa.set()
        janela.atualizar_status("monitorando")
        
        if timer_assistir_tela is not None:
            timer_assistir_tela.cancel()
            
        timer_assistir_tela = threading.Timer(duracao_segundos, _timeout_assistir_tela)
        timer_assistir_tela.start()
        
        return f"Tô de olho na sua tela! Vou ficar acompanhando por {duracao_segundos} segundos."

    def _timeout_assistir_tela():
        if modo_assistir_tela_ativo.is_set():
            assistir_tela_off(motivo_timeout=True)

    def assistir_tela_off(motivo_timeout=False):
        global timer_assistir_tela
        modo_assistir_tela_ativo.clear()
        
        if not modo_jogo_ativo.is_set():
            visao_ativa.clear()
            janela.atualizar_status("aguardando")
            
        if timer_assistir_tela is not None:
            timer_assistir_tela.cancel()
            timer_assistir_tela = None
            
        if motivo_timeout:
            def _falar_timeout():
                for _ in range(30):
                    if not emily_ocupada.is_set() and not voz.falar_ativo.is_set():
                        break
                    time.sleep(0.5)
                emily_ocupada.set()
                try:
                    janela.atualizar_status("falando", "Tempo esgotado")
                    voz.falar("Parei de olhar a tela, o tempo acabou.")
                    restaurar_status()
                finally:
                    emily_ocupada.clear()
            threading.Thread(target=_falar_timeout, daemon=True).start()
            
        return "Parei de olhar a tela, só te escutando agora."

    def discord_on():
        return ("Escuta do Discord ligada." if discord_bot.ativar_escuta_discord()
                else "Não consegui transferir a escuta do Discord para este PC agora.")

    def discord_off():
        return ("Escuta do Discord desligada." if discord_bot.desativar_escuta_discord()
                else "Não consegui desligar a escuta do Discord agora.")

    ferramentas.registrar_handler("ativar_modo_escrito", escrito_on)
    ferramentas.registrar_handler("desativar_modo_escrito", escrito_off)
    ferramentas.registrar_handler("ativar_modo_controle_tela", ui_on)
    ferramentas.registrar_handler("desativar_modo_controle_tela", ui_off)
    ferramentas.registrar_handler("ativar_monitoramento_jogo", jogo_on)
    ferramentas.registrar_handler("desativar_monitoramento_jogo", jogo_off)
    ferramentas.registrar_handler("assistir_tela", assistir_tela_on)
    ferramentas.registrar_handler("parar_assistir_tela", assistir_tela_off)
    ferramentas.registrar_handler("ativar_escuta_discord", discord_on)
    ferramentas.registrar_handler("desativar_escuta_discord", discord_off)

    # Ponte pro Music Player da interface. As ferramentas player_* chamam
    # _chamar_handler('comando_player', acao=..., **dados); aqui vira um
    # evento pro JS, que é quem realmente controla o áudio (Player do app.js).
    # A interface antiga (Qt) não tem _push — nesse caso avisa que o player
    # da interface não está disponível.
    def comando_player(acao: str, **dados):
        push = getattr(janela, "_push", None)
        if push is None:
            return ("O player da interface não está disponível nesta sessão "
                    "(interface antiga). Use tocar_musica pra abrir no YouTube.")
        push("player_comando", {"acao": acao, "dados": dados or {}})
        return "Player da interface comandado."

    ferramentas.registrar_handler("comando_player", comando_player)

    print(f"[MAIN] {len(ferramentas.CATALOGO)} ferramentas disponíveis, "
          f"9 handlers de modo/player registrados")


def _processar_modo_ui(texto: str) -> bool:
    """Processa a entrada quando o modo de controle de tela está ativo.
    Retorna True se tratou a entrada, False se deve continuar o fluxo normal."""
    global modo_ui_ativo

    texto_norm = texto.lower().strip()

    # Uma resposta à barreira humana de ação destrutiva tem prioridade sobre os
    # comandos genéricos abaixo. Sem isso, "não, cancelar" cancelaria a sessão
    # inteira em vez de negar somente o clique pendente.
    if agente_ui.estado_agente_ui().get("estado") == "aguardando_confirmacao":
        agente_ui.enviar_mensagem_ao_vivo(texto)
        janela.atualizar_status("falando", "Confirmação recebida para a ação pendente.")
        return True

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


def _falar_texto_digitado() -> bool:
    """Escolha local do aparelho, independente das preferências sincronizadas."""
    return bool(preferencias.obter(
        "voz_texto_digitado",
        os.getenv("EMILY_FALAR_TEXTO_DIGITADO", "0").strip() == "1"))


def _executar_turno_com_ferramentas(texto: str, canal: str) -> str:
    """Executa o mesmo protocolo visual/TTS para chat escrito e voz."""
    fila_frases = queue.Queue()
    respostas = []
    erros = []
    janela.progresso_evento("inicio", {})

    def gerar():
        try:
            resposta = modelo.conversar_com_ferramentas(
                texto,
                callback=lambda frase: janela.atualizar_status("falando", frase),
                fila_frases=fila_frases,
                on_progresso=janela.progresso_evento,
                canal=canal,
            )
            if resposta:
                respostas.append(resposta)
        except Exception as erro:  # a exceção de thread não sobe sozinha
            erros.append(erro)
            fila_frases.put(None)

    def falar():
        voz.falar_stream(
            fila_frases,
            lambda frase: janela.atualizar_status("falando", frase),
            on_progresso=janela.progresso_evento,
        )

    discord_bot.atualizar_status_discord("falando")
    thread_gerar = threading.Thread(target=gerar, daemon=True)
    thread_falar = threading.Thread(target=falar, daemon=True)
    thread_gerar.start()
    thread_falar.start()
    thread_gerar.join()
    thread_falar.join()

    if erros:
        raise erros[0]

    resposta_final = respostas[0] if respostas else ""
    if resposta_final:
        # Fonte da verdade da bolha e do histórico: preserva markdown e permite
        # retirar os comentários intermediários registrados em fase="fala".
        janela.progresso_evento("resposta", {"texto": resposta_final})
        if not modelo._memoria_unificada_ativa():
            memoria.processar_conversa_async(texto, resposta_final)
    return resposta_final


def _executar_turno_voz_rapido(texto: str) -> str:
    """Luna na frente; player local e delegação forte sem bloquear o próximo PTT."""
    fila_frases = queue.Queue()
    respostas = []
    erros = []
    janela.progresso_evento("inicio", {})

    def gerar():
        try:
            resposta = _orquestrador_voz.responder(
                texto,
                fila_frases=fila_frases,
                on_delta=lambda pedaco: janela.progresso_evento(
                    "delta", {"texto": pedaco, "acompanhar_fala": True}),
                on_progresso=janela.progresso_evento,
            )
            if resposta:
                respostas.append(resposta)
        except Exception as erro:  # exceção de thread precisa atravessar manualmente
            erros.append(erro)
            fila_frases.put(None)

    def falar():
        voz.falar_stream(
            fila_frases,
            lambda frase: janela.atualizar_status("falando", frase),
            on_progresso=janela.progresso_evento,
        )

    discord_bot.atualizar_status_discord("falando")
    thread_gerar = threading.Thread(target=gerar, daemon=True)
    thread_falar = threading.Thread(target=falar, daemon=True)
    thread_gerar.start()
    thread_falar.start()
    thread_gerar.join()
    thread_falar.join()

    if erros:
        raise erros[0]

    resposta_final = respostas[0] if respostas else ""
    if resposta_final:
        janela.progresso_evento("resposta", {"texto": resposta_final})
        if not modelo._memoria_unificada_ativa():
            memoria.processar_conversa_async(texto, resposta_final)
    return resposta_final


def _registrar_entrada_voz_no_chat(texto: str) -> None:
    """Mostra e persiste a transcrição de voz como uma mensagem normal."""
    texto = (texto or "").strip()
    if not texto:
        return
    try:
        if hasattr(janela, "add_mensagem_usuario"):
            janela.add_mensagem_usuario(texto)
        if hasattr(janela, "_registrar_na_conversa"):
            janela._registrar_na_conversa("user", texto)
            if hasattr(janela, "_titular"):
                threading.Thread(
                    target=janela._titular, args=(texto,), daemon=True
                ).start()
    except Exception as erro_registro:
        print(f"[VOZ] registro na conversa falhou: {erro_registro}")


def processar_texto_digitado(texto):
    global ultimo_uso_usuario, modo_ui_ativo
    ultimo_uso_usuario = time.time()
    emily_ocupada.set()
    # Silencia a voz por todo o turno escrito. No finally, sempre — se sair por
    # exceção e o mudo ficar preso, a Emily emudece pro resto da sessão, e um
    # bug de enfeite viraria um bug de "ela não fala mais".
    silenciar_turno = not _falar_texto_digitado()
    mudo_antes = voz.mudo.is_set()
    if silenciar_turno:
        voz.mudo.set()
    try:
        texto_norm = texto.lower().strip()

        # A confirmação destrutiva também pode chegar pelo chat digitado quando
        # o agente foi iniciado fora do modo UI. Ela deve ser consumida pela
        # sessão pendente, nunca virar um novo turno de conversa.
        if agente_ui.estado_agente_ui().get("estado") == "aguardando_confirmacao":
            agente_ui.enviar_mensagem_ao_vivo(texto)
            janela.atualizar_status("falando", "Confirmação recebida para a ação pendente.")
            return

        # ─── TOOL CALLING (caminho novo, texto digitado) ───
        if modelo.TOOL_CALLING_ATIVO:
            _executar_turno_com_ferramentas(texto, canal="web")
            restaurar_status()
            emily_ocupada.clear()
            return

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
                resposta = ("Tô de olho no Discord agora, Vitor!"
                            if discord_bot.ativar_escuta_discord()
                            else "Não consegui transferir a escuta do Discord para este PC agora.")
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                return

            elif acao_fb == "parar_discord":
                resposta = ("Parei de ouvir o Discord!"
                            if discord_bot.desativar_escuta_discord()
                            else "Não consegui desligar a escuta do Discord agora.")
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

            elif acao_fb == "ver_tela":
                # ── Verifica primeiro se é "ler página do navegador" ──
                # Frases que indicam leitura de página web, não captura de tela
                _FRASES_LER_PAGINA = (
                    "le essa pagina", "le a pagina", "le a pagina pra mim",
                    "le essa pagina pra mim", "le o site", "le o conteudo",
                    "le o conteudo dessa pagina", "le o que ta escrito",
                    "le o que esta escrito", "le isso pra mim",
                    "o que e essa pagina", "do que se trata",
                    "do que trata essa pagina", "resume essa pagina",
                    "resume o site", "resume o conteudo",
                    "o que esse site diz", "o que ta escrito aqui",
                    "o que esta escrito aqui", "analisa essa pagina",
                    "o que e isso que eu to lendo", "me explica essa pagina",
                    "qual o assunto dessa pagina", "qual o contexto",
                    "qual e o assunto", "sobre o que e essa pagina",
                    "sobre o que e isso", "explica essa pagina",
                    "me fala sobre essa pagina",
                )
                _texto_nav = _normalizar_simples(texto)
                _eh_ler_pagina = any(f in _texto_nav for f in _FRASES_LER_PAGINA)

                if _eh_ler_pagina and navegador.esta_conectado():
                    # Rota para ler_pagina via extensão
                    janela.atualizar_status("ouvindo", "Lendo a página...")
                    voz.falar("Deixa eu ler essa página pra você!")
                    resultado_nav = automacao.executar_comando(
                        f"lê essa página e responde: {texto}",
                        callback_falar=voz.falar,
                    )
                    if resultado_nav:
                        janela.atualizar_status("falando", resultado_nav)
                        discord_bot.atualizar_status_discord("falando")
                        voz.falar(resultado_nav)
                    restaurar_status()
                    emily_ocupada.clear()
                    return

                # ── Ver/analisar a tela — NÃO usa agente_ui, só captura e descreve ──
                frase_ver = modelo.gerar_frase_analisando_tela(texto)
                janela.atualizar_status("ouvindo", "Olhando a tela...")
                voz.falar(frase_ver)
                # Registra o pedido do usuário no histórico ANTES de analisar
                modelo.historico.append({"role": "user", "content": texto})
                modelo._limitar_historico()
                imagem_tela = visao.capturar_tela()
                if imagem_tela:
                    pergunta_tela = param_fb if param_fb else texto
                    # analisar_tela_com_pergunta já registra a resposta no histórico
                    resposta_tela = modelo.analisar_tela_com_pergunta(imagem_tela, pergunta_tela) or "Não consegui analisar a tela agora, Vitor."
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
                respostas_pesq = []
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
                        on_delta=lambda p: janela.progresso_evento("delta", {"texto": p}),
                    )
                    if r:
                        respostas_pesq.append(r)
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
                if respostas_pesq:
                    janela.progresso_evento("resposta", {
                        "texto": respostas_pesq[0],
                        "fontes": pesquisa.extrair_fontes_do_resultado(resultado_pesquisa),
                    })
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
                canal="web",
                on_delta=lambda p: janela.progresso_evento("delta", {"texto": p}),
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
            # Resposta crua pra interface (código e quebras de linha intactos).
            janela.progresso_evento("resposta", {"texto": _resp_buf[0], "fontes": []})
            if not modelo._memoria_unificada_ativa():
                memoria.processar_conversa_async(texto, _resp_buf[0])

        restaurar_status()
    except Exception as erro:
        print(f"Erro ao processar texto digitado: {erro}")
        restaurar_status()
    finally:
        emily_ocupada.clear()
        # Solta a voz de volta SEMPRE, inclusive se estourou exceção no meio.
        # Mudo preso emudeceria a Emily até reiniciar.
        if silenciar_turno and not mudo_antes:
            voz.mudo.clear()
        janela.progresso_evento("fim", {})


def processar_arquivos_chat(caminhos, texto=""):
    """Lê anexos e mantém o protocolo visual/tool calling da conversa normal."""
    caminhos = [str(caminho) for caminho in caminhos if os.path.isfile(str(caminho))]
    if not caminhos:
        janela.atualizar_status("falando", "Não encontrei nenhum arquivo válido para enviar.")
        restaurar_status()
        return

    if emily_ocupada.is_set():
        janela.atualizar_status("falando", "Espera só um pouquinho, ainda tô ocupada 😅")
        restaurar_status()
        return

    emily_ocupada.set()
    janela.progresso_evento("inicio", {})
    try:
        janela.atualizar_status("pensando", "Analisando anexos...")
        resposta = modelo.conversar_com_anexos(
            texto or "Analise os anexos que eu acabei de enviar.",
            caminhos,
            callback=lambda frase: janela.atualizar_status("falando", frase),
            on_progresso=janela.progresso_evento,
            canal="web",
        )
        if resposta:
            janela.progresso_evento("resposta", {"texto": resposta})
    except Exception as erro:
        print(f"[ANEXOS] Erro ao processar arquivos: {erro}")
        janela.atualizar_status("falando", f"Não consegui analisar esses anexos: {erro}")
    finally:
        restaurar_status()
        emily_ocupada.clear()
        janela.progresso_evento("fim", {})


janela.callback_texto = processar_texto_digitado
janela.callback_arquivos = processar_arquivos_chat
janela.callback_trocar_monitor = visao.trocar_monitor

servidor.definir_callback(processar_texto_digitado)
servidor.definir_callbacks_remota(_remota_inicio, _remota_fim)
# Passos das ferramentas do CELULAR durante um comando remoto: retransmitidos
# pro painel de progresso da interface (mesma animação dos turnos locais).
servidor.definir_callback_progresso_remota(janela.progresso_evento)

# ── Resposta do comando remoto (PC → celular): a interface_web já cuida disso
#    sozinha (_rodar_remota → enviar_comando_remoto_ao_celular), então aqui não
#    precisa mais de callback — a versão antiga do servidor exigia um
#    definir_callback_resposta_remota(), que não existe mais.

# Conecta a voz da Emily ao servidor web: toda fala vira áudio no celular também
voz.definir_callback_audio(servidor.receber_fala)


# ─────────────────────────────────────────────────────────────────
# NGROK — sobe automaticamente junto com a Emily
# ─────────────────────────────────────────────────────────────────

def iniciar_ngrok(porta: int = 5000) -> None:
    """Compatibilidade para chamadas antigas; o trabalho real é assíncrono."""
    from emily_remote import ambiente_fedora
    if ambiente_fedora():
        _servicos_runtime.iniciar_ngrok(porta)


# O servidor local precisa existir ANTES do túnel. O inicializador do ngrok
# espera a porta responder sem bloquear o restante do boot.
thread_servidor = threading.Thread(target=servidor.iniciar_servidor, daemon=True)
if not _MODO_PUBLICO:
    thread_servidor.start()
    iniciar_ngrok()

# No notebook Windows, mantém o acervo local alinhado ao gateway Fedora que
# também atende o Android. O primeiro ciclo roda em segundo plano.
if os.name == "nt" and not _MODO_PUBLICO:
    try:
        import sincronizacao_desktop
        sincronizacao_desktop.iniciar()
    except Exception as _erro_sync:
        print(f"[SYNC-DESKTOP] indisponível: {_erro_sync}")

# Servidor SEPARADO e exclusivamente loopback. Nunca passa pelo gateway/ngrok.
if hollow_knight_ponte is not None and not _MODO_PUBLICO:
    try:
        hollow_knight_ponte.iniciar()
    except Exception as _erro_hk_boot:
        print(f"[HOLLOW-KNIGHT] ponte não subiu (Emily segue normal): {_erro_hk_boot}")

# ─── NAVEGADOR (WebSocket extensão Chrome/Brave) ───
if not _MODO_PUBLICO:
    navegador.iniciar_servidor_websocket()

# ─── ESPIADINHA (comentário espontâneo, bem de vez em quando) ───
# Thread daemon própria: dorme um intervalo aleatório e, se o modo estiver
# ligado nas preferências e a Emily estiver ociosa, olha a aba em foco e
# comenta por voz. Desligável nas configurações da interface.
try:
    import espiadinha
    if not _MODO_PUBLICO:
        espiadinha.iniciar()
except Exception as _e_esp:
    print(f"[MAIN] espiadinha não subiu (a Emily funciona sem ela): {_e_esp}")

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
    try:
        import audio_preprocessing
        audio_preprocessing.warmup_async()
    except Exception as erro_audio:
        print(f"[AUDIO-PRE] aquecimento indisponível: {erro_audio}")
    # Abre a conexão com o provedor de LLM ANTES do primeiro turno: sem isto
    # a primeira fala depois de abrir a Emily paga o handshake frio junto com
    # a resposta (4,8–10,6s medidos contra 1,8–2,4s com o socket quente).
    try:
        _aquecer_provedor_llm_no_boot()
    except Exception as erro_llm:
        print(f"[LLM] aquecimento indisponível: {erro_llm}")
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

        # O tabuleiro tem histórico próprio. Não registrar a mesma fala também
        # no chat geral nem chamar a delegação de tarefas durante a partida.
        import interface_web
        if interface_web.encaminhar_voz_xadrez(entrada):
            restaurar_status()
            continue

        emily_ocupada.set()
        # Toda transcrição válida vira uma mensagem normal antes de qualquer
        # atalho, modo ou ferramenta poder encerrar o turno antecipadamente.
        _registrar_entrada_voz_no_chat(entrada)
        estilo_vitor.coletar(entrada, "fala", "ptt_pc")

        try:
            entrada_lower = entrada.lower()

            # ─── TOOL CALLING (caminho novo) ───
            # O modelo lê a conversa inteira e decide sozinho se responde ou
            # age, sem palavra-chave e sem classificador de confiança. Isso
            # substitui de uma vez o executar_comando por keyword, o fallback
            # de intenção e o conversar_stream.
            # Desligue com EMILY_TOOL_CALLING=0 pra voltar ao caminho antigo.
            if modelo.TOOL_CALLING_ATIVO:
                try:
                    _executar_turno_voz_pc(entrada)
                except Exception as e:
                    print(f"[VOZ] Erro no turno: {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()
                    raise
                finally:
                    janela.progresso_evento("fim", {})
                    restaurar_status()
                    emily_ocupada.clear()
                continue


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
                resposta = ("Tô de olho no Discord agora, Vitor!"
                            if discord_bot.ativar_escuta_discord()
                            else "Não consegui transferir a escuta do Discord para este PC agora.")
                janela.atualizar_status("falando", resposta)
                voz.falar(resposta)
                restaurar_status()
                emily_ocupada.clear()
                continue

            if "para de ouvir o discord" in entrada_lower or "para o discord" in entrada_lower:
                resposta = ("Parei de ouvir o Discord!"
                            if discord_bot.desativar_escuta_discord()
                            else "Não consegui desligar a escuta do Discord agora.")
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
            
            # ─── MODO JOGO (monitoramento de tela pra reagir) ───
            if not modo_jogo_ativo.is_set() and any(frase in entrada_lower for frase in FRASES_ATIVAR_JOGO):
                if modo_assistir_tela_ativo.is_set():
                    voz.falar("Eu já estou assistindo sua tela! Pare o monitoramento contínuo primeiro se quiser o modo jogo.")
                else:
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

            if modo_assistir_tela_ativo.is_set() and any(frase in entrada_lower for frase in FRASES_DESATIVAR_ASSISTIR_TELA):
                # O handler já limpa os eventos e atualiza a interface.
                # _chamar_handler vive em ferramentas.py (não em main.py), e é lá
                # que ficam registrados os handlers de modo — por isso a chamada
                # é qualificada com o módulo.
                import ferramentas
                resposta = ferramentas._chamar_handler("parar_assistir_tela")

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
                    if modo_assistir_tela_ativo.is_set():
                        voz.falar("Eu já estou assistindo sua tela! Pare o monitoramento contínuo primeiro se quiser o modo jogo.")
                    else:
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
                    resposta = ("Tô de olho no Discord agora, Vitor!"
                                if discord_bot.ativar_escuta_discord()
                                else "Não consegui transferir a escuta do Discord para este PC agora.")
                    janela.atualizar_status("falando", resposta)
                    voz.falar(resposta)
                    restaurar_status()
                    emily_ocupada.clear()
                    continue

                elif acao_fb == "parar_discord":
                    resposta = ("Parei de ouvir o Discord!"
                                if discord_bot.desativar_escuta_discord()
                                else "Não consegui desligar a escuta do Discord agora.")
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

                elif acao_fb == "ver_tela":
                    # ── Ver/analisar a tela — NÃO usa agente_ui, só captura e descreve ──
                    frase_ver = modelo.gerar_frase_analisando_tela(entrada)
                    janela.atualizar_status("ouvindo", "Olhando a tela...")
                    voz.falar(frase_ver)
                    # Registra o pedido do usuário no histórico ANTES de analisar
                    modelo.historico.append({"role": "user", "content": entrada})
                    modelo._limitar_historico()
                    imagem_tela = visao.capturar_tela()
                    if imagem_tela:
                        pergunta_tela = param_fb if param_fb else entrada
                        # analisar_tela_com_pergunta já registra a resposta no histórico
                        resposta_tela = modelo.analisar_tela_com_pergunta(imagem_tela, pergunta_tela) or "Não consegui analisar a tela agora, Vitor."
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
                            canal="voz",
                            on_delta=lambda p: janela.progresso_evento("delta", {"texto": p}),
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

            # ─── CONVERSA: registra a fala do Vitor e titula o chat ───
            # Antes, só a RESPOSTA dela era gravada (_salvar_resposta_emily,
            # no fim do turno) — então o chat de voz nascia criado pela
            # Emily com título vazio ("Conversa nova") e SEM mensagem do
            # usuário, e o auto-título do acrescentar() nunca disparava
            # (ele só titula quando o papel é 'user'). Registrando a fala
            # aqui e chamando o mesmo _titular do chat digitado, o chat de
            # voz aparece na barra lateral com nome descritivo igualzinho.
            fila_frases = queue.Queue()
            _voz_resp_buf = []

            def gerar_resposta():
                r = modelo.conversar_stream(
                    entrada,
                    lambda f: janela.atualizar_status("falando", f),
                    fila_frases,
                    canal="voz",
                    on_delta=lambda p: janela.progresso_evento("delta", {"texto": p}),
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
                if not modelo._memoria_unificada_ativa():
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
    assinatura_anterior = None

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

            # ── Porteiro barato: só chama LLM se a tela mudou de verdade ──
            # Antes daqui a Emily queimava uma chamada de visão a cada ~4,5s
            # olhando tela parada, e a resposta era NAO na esmagadora maioria.
            frame_triagem = visao.capturar_tela_triagem()
            if not frame_triagem:
                time.sleep(2)
                continue

            assinatura_atual = visao.assinatura_frame(frame_triagem)
            
            # Checa se a tela mudou o suficiente
            if not visao.tela_mudou(assinatura_anterior, assinatura_atual):
                assinatura_anterior = assinatura_atual
                time.sleep(2)
                continue
            assinatura_anterior = assinatura_atual

            # A triagem roda no frame de baixa resolução (~307 tokens em vez
            # de ~1229). A análise de verdade continua em resolução cheia.
            #
            # O modo_assistir_tela usa a triagem comum de propósito: ele é o
            # "fica de olho na minha tela por X segundos", e o critério de
            # relevância é o mesmo do monitoramento normal. O modo jogo tem
            # triagem própria porque ali o que importa é evento de jogo
            # (morte, boss, conquista), não mudança de janela.
            if modo_jogo_ativo.is_set():
                vale_comentar = modelo.triar_tela_jogo(frame_triagem)
            else:
                vale_comentar = modelo.triar_tela(frame_triagem)

            if not vale_comentar:
                time.sleep(3)
                continue

            # Só agora paga a captura em resolução cheia
            imagens = visao.capturar_sequencia_telas_rapida(quantidade=2, intervalo=0.3)
            frame_atual = imagens[0] if imagens else None
            if not frame_atual:
                time.sleep(2)
                continue

            if modo_jogo_ativo.is_set():
                comentario = modelo.analisar_tela_jogo(frame_atual, contexto=[ultimo_evento_jogo])
            else:
                comentario = modelo.analisar_sequencia_telas(imagens)

            if not comentario:
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
                    if modo_jogo_ativo.is_set() or modo_assistir_tela_ativo.is_set():
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
        _orquestrador_voz.parar_monitor()
    except Exception:
        pass
    try:
        if hollow_knight_ponte is not None:
            hollow_knight_ponte.encerrar()
    except Exception:
        pass
    try:
        # Não espera novas extrações por LLM durante a saída. Eventos e lotes já
        # estão persistidos e o worker os recupera no próximo início.
        import memoria_unificada
        memoria_unificada.ponte().encerrar(aguardar=False, timeout=2.0)
    except Exception:
        pass
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
if hasattr(signal, "SIGBREAK"):  # sinal só existe no Windows
    signal.signal(signal.SIGBREAK, ao_encerrar)  # Windows

atexit.register(encerrar_tudo)

if modelo.TOOL_CALLING_ATIVO:
    _registrar_ferramentas_de_modo()
    if not _MODO_PUBLICO:
        _orquestrador_voz.aquecer_async()
        _orquestrador_voz.iniciar_monitor(
            pode_falar=_pc_livre_para_aviso_delegacao,
            falar=_falar_aviso_delegacao,
        )
else:
    print("[MAIN] Tool calling desligado (EMILY_TOOL_CALLING=0). "
          "Usando o caminho antigo de palavra-chave.")

thread_visao = threading.Thread(target=loop_visao, daemon=True)
thread_visao.start()

thread = threading.Thread(target=rodar_emily, daemon=True)
if not _MODO_PUBLICO or (os.getenv("EMILY_PUBLIC_MICROFONE") == "1" and os.getenv("GROQ_API_KEY")):
    thread.start()
janela.iniciar()

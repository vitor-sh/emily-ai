"""
interface_web.py — a interface da Emily como janela web nativa.

Por que este arquivo existe
───────────────────────────
A interface anterior (interface.py, 3.114 linhas de PyQt6) tinha um teto que
não era falta de esforço: o Qt Style Sheets NÃO suporta `transition`,
`animation`, `@keyframes` nem `box-shadow`. Cada fade, cada hover suave, cada
mensagem que entra deslizando teria que ser uma QPropertyAnimation escrita à
mão, por propriedade, por widget. Medido no arquivo antigo: 15 regras `:hover`
e ZERO animações.

Aqui a tela é HTML/CSS/JS de verdade, rodando na WebView2 (o Edge que já vem
no Windows 10/11), hospedada por pywebview. Um processo só, tudo em Python,
sem Node e sem Rust no build.

O contrato com o resto do projeto é IDÊNTICO ao da interface antiga
───────────────────────────────────────────────────────────────────
O main.py chama exatamente nove coisas na janela, e nada mais:

    atualizar_status(status, texto)      ← 103 chamadas, a dominante
    mostrar_opcao_salvar(caminho)
    add_imagem_chat_safe(caminho, autor)
    progresso_evento(fase, dados)
    iniciar()
    root / _painel                       (só pra .destroy() no encerramento)
    callback_texto / callback_visao / callback_arquivos / callback_trocar_monitor

Por isso trocar a interface não encosta em modelo.py, automacao.py,
ferramentas.py nem no laço de voz. Este módulo implementa o mesmo contrato.

Como voltar pra antiga
──────────────────────
EMILY_UI=qt no .env. O interface.py continua no projeto, intacto.
"""

from __future__ import annotations

import base64
import copy
import http.server
import json
import mimetypes
import os
import re
import socketserver
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit
from typing import Callable, List, Optional

DIR_BASE = str(Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)))
DIR_WEB = os.path.join(DIR_BASE, "web")
DIR_IMG = os.path.join(DIR_BASE, "img")
from emily_paths import pasta_dados as _pasta_dados_emily
from emily_remote import ambiente_fedora
DIR_CACHE = os.path.join(str(_pasta_dados_emily()), ".webview")

# Arquivos escolhidos pelo diálogo nativo chegam por caminho e não atravessam a
# ponte. Já clipboard e drag-and-drop chegam como base64 pelo JavaScript; sem um
# teto, um vídeo grande vira centenas de MB de JSON e pode congelar a WebView.
_ANEXO_MAX_MB = 25
_ANEXO_MAX_BYTES = _ANEXO_MAX_MB * 1024 * 1024
_ANEXO_MAX_QTDE = 12

# O botão manual e a atualização do boot compartilham o mesmo staging/backup.
# Nunca deixar duas validações/aplicações disputarem esses arquivos.
_trava_atualizacao = threading.Lock()


class ErroUI(Exception):
    """Falha de infraestrutura da interface."""


def _log(msg: str) -> None:
    print(f"[UI] {msg}")


def _titulo_e_id_modelo(titulo: str) -> bool:
    """Reconhece IDs de modelo devolvidos por engano como título de chat."""
    valor = (titulo or "").strip()
    return bool(re.fullmatch(
        r"(?:claude|gpt|gemini|o[1-9])(?:[-_][a-z0-9]+){2,}[-_]\d{6,}",
        valor, flags=re.IGNORECASE))


# Instruções de atuação que o Fish Audio entende dentro do próprio texto. Elas
# pertencem ao áudio, não à conversa, portanto ficam intactas no modelo/TTS e
# são retiradas somente na fronteira da interface.
from fish_voz_texto import eh_tag_fish as _eh_tag_de_voz


class _FiltroStreamingTagsDeVoz:
    """Remove tags Fish sem exibir fragmentos quando ``[tag]`` vem fatiada.

    Uma regex aplicada isoladamente a cada delta deixa ``[exci`` piscar na
    tela até chegar ``ted]``. Este filtro segura no máximo 82 caracteres depois
    de ``[``; ao descobrir que não era tag de voz, devolve tudo sem alterar
    markdown, referências como ``[1]`` ou texto comum entre colchetes.
    """

    def __init__(self) -> None:
        self._pendente = ""

    def resetar(self) -> None:
        self._pendente = ""

    def alimentar(self, pedaco: str, finalizar: bool = False) -> str:
        entrada = self._pendente + (pedaco or "")
        self._pendente = ""
        saida: List[str] = []
        pos = 0
        while pos < len(entrada):
            abre = entrada.find("[", pos)
            if abre < 0:
                saida.append(entrada[pos:])
                break
            saida.append(entrada[pos:abre])
            fecha = entrada.find("]", abre + 1)
            if fecha < 0:
                candidato = entrada[abre:]
                if finalizar or "\n" in candidato or len(candidato) > 82:
                    saida.append(candidato)
                else:
                    self._pendente = candidato
                break
            conteudo = entrada[abre + 1:fecha]
            if len(conteudo) <= 80 and _eh_tag_de_voz(conteudo):
                pos = fecha + 1
                continue
            saida.append(entrada[abre:fecha + 1])
            pos = fecha + 1
        return "".join(saida)


def _texto_visual_sem_tags_de_voz(texto: str) -> str:
    """Versão stateless para respostas finais, histórico e status da UI."""
    return _FiltroStreamingTagsDeVoz().alimentar(texto or "", finalizar=True)


# ═════════════════════════════════════════════════════════════════
# EMILY CODE — pergunta ao Vitor
#
# O code_perguntar do ferramentas.py chama esta função. Ela abre um modal no
# JS (evento 'emily_code' tipo 'pergunta'), espera a resposta chegar via
# emily_code_responder(), e devolve o texto pro modelo. Roda em thread pra
# não travar o laço de ferramentas.
# ═════════════════════════════════════════════════════════════════

# A pergunta pendente. A Api.emily_code_responder seta o valor.
_pergunta_pendente: Optional[threading.Event] = None

# Perguntas do agente comum usam IDs próprios: uma resposta atrasada nunca
# pode desbloquear outra tarefa nem uma pergunta do Emily Code.
_perguntas_tarefa: dict[str, dict] = {}
_perguntas_tarefa_lock = threading.RLock()


def perguntar_usuario_tarefa(pergunta: str, tipo: str = "duvida", *,
                            cancelar=None, resposta_externa=None) -> str:
    """Pausa o passo atual até o Vitor responder no cartão do chat."""
    api = _api_ativa()
    janela = getattr(api, "_j", None) if api else None
    if janela is None or not getattr(janela, "_janela", None):
        return "Não consegui abrir a pergunta na interface."
    ticket = uuid.uuid4().hex
    pendente = {"evento": threading.Event(), "resposta": ""}
    with _perguntas_tarefa_lock:
        _perguntas_tarefa[ticket] = pendente
    try:
        if not getattr(janela, "_visivel", True):
            janela._tray_mostrar()
        janela._push("pergunta_usuario", {
            "id": ticket, "pergunta": str(pergunta)[:1200],
            "tipo": tipo if tipo in {"duvida", "login", "problema"} else "duvida",
            "cid": janela._cid or "",
        })
        limite = time.monotonic() + 600
        while not pendente["evento"].wait(timeout=.1):
            if cancelar is not None and cancelar.is_set():
                return "Pergunta cancelada"
            if resposta_externa is not None:
                resposta = resposta_externa()
                if resposta is not None:
                    return resposta
            if time.monotonic() >= limite:
                return "O Vitor não respondeu em dez minutos. Pare este passo e explique onde ficou."
        return pendente["resposta"] or "O Vitor não conseguiu concluir a intervenção."
    finally:
        with _perguntas_tarefa_lock:
            _perguntas_tarefa.pop(ticket, None)
        janela._push("pergunta_usuario_fim", {"id": ticket})


def _perguntar_ao_vitor(pergunta: str, opcoes: list = None) -> str:
    global _pergunta_pendente, _resposta_pergunta, _resposta_pergunta_evento
    import emily_code  # noqa: F401

    # A Api registra a janela ativa quando é criada.
    api = _api_ativa()
    if api is None:
        return "Não consegui perguntar (interface indisponível)."
    janela = getattr(api, "_j", None)
    if janela is None:
        return "Não consegui perguntar (janela indisponível)."

    _resposta_pergunta_evento.clear()
    _resposta_pergunta = None
    janela._push("emily_code", {
        "tipo": "pergunta",
        "pergunta": pergunta,
        "opcoes": [str(o) for o in (opcoes or [])][:4],
        "cid": emily_code.code_conversa_atual() or "",
    })
    if not _resposta_pergunta_evento.wait(timeout=120):
        return "O Vitor não respondeu a pergunta a tempo."
    return _resposta_pergunta or ""


def _perguntar_permissao(tipo: str, acao: str, caminho, preview: str = "") -> str:
    """Abre o modal de permissão no JS e espera sim/sempre/nao."""
    global _resposta_permissao, _resposta_permissao_evento
    api = _api_ativa()
    if api is None:
        return "nao"
    janela = getattr(api, "_j", None)
    if janela is None:
        return "nao"

    _resposta_permissao_evento.clear()
    _resposta_permissao = None
    janela._push("emily_code", {
        "tipo": "permissao",
        "acao": acao,
        "tipo_permissao": tipo,
        "caminho": str(caminho) if caminho else "",
        "preview": preview or "",
        "cid": _cid_code_contexto(),
    })
    if not _resposta_permissao_evento.wait(timeout=120):
        return "nao"
    return _resposta_permissao or "nao"


def _mudar_pasta_code(mensagem: str = "") -> str:
    """Acende o aviso de escolher pasta no JS e ESPERA o Vitor escolher.

    Chamado pela ferramenta code_mudar_pasta (Emily pediu pra trocar a pasta).
    O aviso no frontend devolve a resposta por emily_code_definir_projeto (a
    pasta nova) ou emily_code_cancelar_pasta (cancelou). Devolve ao modelo um
    resumo do que aconteceu.
    """
    global _resultado_pasta, _resultado_pasta_evento
    api = _api_ativa()
    if api is None:
        return "Não consegui abrir o aviso de pasta (interface indisponível)."
    janela = getattr(api, "_j", None)
    if janela is None:
        return "Não consegui abrir o aviso de pasta (janela indisponível)."

    import emily_code
    atual = emily_code.projeto_raiz()
    _resultado_pasta_evento.clear()
    _resultado_pasta = None
    janela._push("emily_code", {
        "tipo": "mudar_pasta",
        "mensagem": mensagem or "",
        "projeto": str(atual) if atual else "",
        "cid": emily_code.code_conversa_atual() or "",
    })
    if not _resultado_pasta_evento.wait(timeout=180):
        return "O Vitor não respondeu a tempo; mantive a pasta atual."
    if _resultado_pasta:
        return f"Pasta trocada: {_resultado_pasta}"
    return "Ok, mantive a pasta de projeto atual."


# Resposta do modal de pergunta (a Api.emily_code_responder seta).
_resposta_permissao = None
_resposta_permissao_evento = threading.Event()
_resposta_pergunta = None
_resposta_pergunta_evento = threading.Event()
# Resultado da troca de pasta (code_mudar_pasta): a Api.emily_code_definir_projeto
# seta com o caminho novo; emily_code_cancelar_pasta seta None (cancelou).
_resultado_pasta = None
_resultado_pasta_evento = threading.Event()
_api_registrada = None
# modelo.historico ainda é global. Dois chats Code simultâneos trocavam essa
# lista um por cima do outro; a fila mantém cada turno inteiro e consistente.
_trava_modelo_code = threading.Lock()


def _api_ativa():
    return _api_registrada


def _cid_code_contexto() -> str:
    """ID da conversa Code desta thread, sem tornar a ponte obrigatória."""
    try:
        import emily_code
        return emily_code.code_conversa_atual() or ""
    except Exception:  # noqa: BLE001
        return ""


# ─────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────

def _data_uri(caminho: str, limite_mb: float = 8.0) -> str:
    """
    Arquivo de imagem como data URI.

    Por que não `file:///`: a WebView2 bloqueia file:// de dentro de página
    carregada de outra origem, e depurar isso em produção é pior que pagar o
    base64.

    O limite não é decoração. O base64 infla 33% e o resultado ainda passa
    por evaluate_js como string — um GIF de 11MB virou 15 MILHÕES de
    caracteres numa chamada só, e o resultado foi um círculo vazio na tela.
    Melhor não mostrar a imagem e dizer no log do que travar a interface.
    """
    try:
        if not caminho or not os.path.isfile(caminho):
            return ""
        tamanho = os.path.getsize(caminho)
        if tamanho > limite_mb * 1024 * 1024:
            _log(f"imagem grande demais pra embutir ({tamanho // 1024 // 1024}MB "
                 f"> {limite_mb:.0f}MB): {os.path.basename(caminho)}")
            return ""
        tipo = mimetypes.guess_type(caminho)[0] or "image/png"
        with open(caminho, "rb") as f:
            return f"data:{tipo};base64," + base64.b64encode(f.read()).decode()
    except Exception as e:  # noqa: BLE001
        _log(f"não consegui ler a imagem {caminho}: {e}")
        return ""


# Cache de data URIs de preview da Cloud. O polling de 4s reconverte as
# thumbnails para base64 A CADA listagem — com dezenas de imagens isso vira
# megabytes serializados por ciclo e contribui para a interface "pesada".
# Chave = caminho:mtime, então uma thumbnail regenerada invalida sozinha.
_PREVIEW_URI_CACHE: dict[str, tuple[float, str]] = {}
_PREVIEW_URI_CACHE_MAX = 400


def _data_uri_com_cache(caminho: str, limite_mb: float = 6.0) -> str:
    try:
        if not caminho or not os.path.isfile(caminho):
            return ""
        mtime = os.path.getmtime(caminho)
        chave = f"{caminho}:{mtime}"
        cached = _PREVIEW_URI_CACHE.get(chave)
        if cached is not None:
            return cached[1]
        uri = _data_uri(caminho, limite_mb)
        if uri:
            if len(_PREVIEW_URI_CACHE) >= _PREVIEW_URI_CACHE_MAX:
                # Evita crescer sem limite: descarta a metade mais antiga.
                for velho in list(_PREVIEW_URI_CACHE)[: _PREVIEW_URI_CACHE_MAX // 2]:
                    _PREVIEW_URI_CACHE.pop(velho, None)
            _PREVIEW_URI_CACHE[chave] = (mtime, uri)
        return uri
    except Exception as e:  # noqa: BLE001
        _log(f"cache de preview falhou para {caminho}: {e}")
        return _data_uri(caminho, limite_mb)


# Teto do retrato dela. Bem mais apertado que o das imagens do chat: isto
# entra na tela em DOIS lugares (o hero e cada mensagem dela) e fica no DOM
# a sessão inteira.
LIMITE_AVATAR_MB = 2.0

# Lado do retrato depois de reduzido. 256px cobre o hero (96px) e o ícone das
# mensagens (18px) com folga em telas de alta densidade, e o data URI fica na
# casa das dezenas de KB em vez dos 2,5MB do arquivo original.
LADO_AVATAR = 256


def _avatar_reduzido(caminho: str) -> str:
    """
    Retrato recortado no quadrado e reduzido, como data URI pequeno.

    emilyimage.png tem 2,5MB. Embutido cru, cada mensagem da Emily carregaria
    3,5MB de base64 no DOM — foi um arquivo desse tamanho (o idle.gif de 11MB)
    que travou a interface na primeira tentativa. Reduzir uma vez e reusar o
    mesmo data URI leve resolve a raiz.

    O cache é POR IMAGEM DE ORIGEM (hash do caminho + mtime), não um arquivo
    único. Com um arquivo só, a foto que o Vitor escolhe tinha quase sempre
    mtime mais antigo que o cache do retrato da Emily — e o cache devolvia a
    EMILY no lugar da foto dele, o que fazia "troquei a foto e não mudou nada".
    """
    try:
        from PIL import Image
    except Exception:
        # Sem PIL não dá pra reduzir. Só embute se couber no teto; senão,
        # melhor a inicial do nome do que travar a tela com um arquivo enorme.
        return _data_uri(caminho, LIMITE_AVATAR_MB)

    try:
        import hashlib
        origem_mtime = os.path.getmtime(caminho)
        chave = hashlib.sha1(
            f"{os.path.abspath(caminho)}:{origem_mtime}".encode()).hexdigest()[:12]
        cache = os.path.join(DIR_CACHE, f"avatar_cache_{chave}.png")
        if os.path.isfile(cache) and os.path.getmtime(cache) >= origem_mtime:
            return _data_uri(cache, LIMITE_AVATAR_MB)

        img = Image.open(caminho).convert("RGBA")
        # Recorte central pro quadrado: o retrato é mais alto que largo, e
        # esticar deformaria o rosto.
        lado = min(img.width, img.height)
        esq = (img.width - lado) // 2
        topo = (img.height - lado) // 2
        img = img.crop((esq, topo, esq + lado, topo + lado))
        img = img.resize((LADO_AVATAR, LADO_AVATAR), Image.LANCZOS)

        os.makedirs(os.path.dirname(cache), exist_ok=True)
        img.save(cache, "PNG", optimize=True)
        return _data_uri(cache, LIMITE_AVATAR_MB)
    except Exception as e:  # noqa: BLE001
        _log(f"não consegui reduzir o retrato {caminho}: {e}")
        return ""


def _achar_avatar() -> str:
    """
    O retrato dela.

    emilyimage.png é o retrato de verdade, e vem primeiro — a versão anterior
    usava o emily.gif (um sprite animado) por engano. Grande demais pra
    embutir cru, então passa pelo _avatar_reduzido. Os outros candidatos são
    reserva, caso o arquivo principal suma.
    """
    principal = os.path.join(DIR_BASE, "emilyimage.png")
    if os.path.isfile(principal):
        uri = _avatar_reduzido(principal)
        if uri:
            _log(f"retrato: emilyimage.png reduzido pra {LADO_AVATAR}px "
                 f"({len(uri) // 1024}KB embutido)")
            return uri

    reservas = [
        os.path.join(DIR_IMG, "emily.png"),
        os.path.join(DIR_IMG, "emily.jpg"),
        os.path.join(DIR_IMG, "avatar.png"),
        os.path.join(DIR_IMG, "perfil.png"),
        os.path.join(DIR_BASE, "emily.gif"),
    ]
    for p in reservas:
        if not os.path.isfile(p):
            continue
        uri = _avatar_reduzido(p) if p.lower().endswith((".png", ".jpg", ".jpeg")) \
            else _data_uri(p, LIMITE_AVATAR_MB)
        if uri:
            _log(f"retrato (reserva): {os.path.basename(p)}")
            return uri
    _log("nenhum retrato encontrado; a interface usa a inicial do nome")
    return ""


# Sugestões da tela inicial. Ficam aqui, e não no JS, porque falam de
# capacidades reais dela — quem muda a capacidade é o Python.
SUGESTOES = [
    {"icone": "monitor", "texto": "olha minha tela e me diz o que tá errado"},
    {"icone": "musica",  "texto": "toca uma música boa pra eu focar"},
    {"icone": "pasta",   "texto": "organiza minha pasta de downloads"},
    {"icone": "disco",   "texto": "quanto espaço eu ainda tenho no disco?"},
]

# Apps de acesso rápido: (padrão do executável, nome, cor da marca, letra).
#
# Copiado do interface.py em vez de importado de lá de propósito: importar a
# interface antiga só pra ler uma lista arrastaria o PyQt6 inteiro pra dentro
# de um processo que não usa Qt, e abrir as Configurações passaria a custar o
# carregamento de um toolkit gráfico completo.
APPS = [
    (r"C:\Users\conti\AppData\Local\Discord\app-*\Discord.exe", "Discord", "#5865F2", "D"),
    (r"C:\Program Files (x86)\Steam\steam.exe", "Steam", "#171a21", "S"),
    (r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe", "Brave", "#FB542B", "B"),
]


# ═════════════════════════════════════════════════════════════════
# API EXPOSTA AO JAVASCRIPT
#
# Cada método aqui é chamável do JS como pywebview.api.<nome>(...).
# Regra: nenhum deles pode levantar exceção. Erro na UI não pode
# derrubar a Emily, e uma promessa rejeitada no JS some sem rastro —
# então tudo volta como valor, e o motivo vai pro log.
# ═════════════════════════════════════════════════════════════════

def _bustar_cache_html() -> None:
    """
    Invalida o cache da WebView2 pro index.html sem query string na URL.

    A WebView2 (private_mode=False) persiste o HTML em .webview/ e servia a
    versão antiga depois de uma mudança — foi assim que o music player não
    apareceu. Query string no file:// quebraria com caminho contendo espaço
    ou acento (main-frame-error, medido). O que funciona: tocar o mtime do
    arquivo quando o CONTEÚDO mudou desde a última abertura. Cache da WebView
    valida por data, então mtime novo força re-leitura; conteúdo igual não
    toca em nada.
    """
    indice = os.path.join(DIR_WEB, "index.html")
    stamp = os.path.join(DIR_CACHE, "html_visto")
    try:
        visto = b""
        if os.path.isfile(stamp):
            with open(stamp, "rb") as f:
                visto = f.read()
        import hashlib
        atual = hashlib.sha1(open(indice, "rb").read()).digest()
        if atual != visto:
            # Toque no mtime: agora + 1s garante ser diferente do cache.
            futuro = time.time() + 1
            os.utime(indice, (futuro, futuro))
            os.makedirs(os.path.dirname(stamp), exist_ok=True)
            with open(stamp, "wb") as f:
                f.write(atual)
    except OSError as e:
        _log(f"não consegui bustar o cache do HTML: {e}")


def encaminhar_voz_xadrez(texto: str) -> bool:
    """A voz acompanha a tela da partida; fora dela, segue o chat habitual."""
    api = _api_registrada
    return bool(api and hasattr(api, 'voz_xadrez') and api.voz_xadrez(texto))


class EditorPanelApi:
    """Ponte restrita da janela de propriedades; alterações passam pelo editor principal."""
    def __init__(self, principal):
        self._principal = principal

    def android(self):
        return self._principal.editor_android_abrir()

    def estado(self, depois: int = -1) -> dict:
        api = self._principal
        with api._editor_panel_lock:
            if depois == api._editor_panel_version:
                return {"ok": True, "changed": False}
            return {"ok": True, "changed": True, "version": api._editor_panel_version,
                    "state": json.loads(json.dumps(api._editor_panel_snapshot))}

    def comando(self, comando: dict) -> dict:
        if not isinstance(comando, dict) or len(json.dumps(comando)) > 5000:
            return {"ok": False, "error": "Comando de editor inválido."}
        if comando.get("kind") not in {"click", "field", "mode", "shortcut", "category", "show_main"}:
            return {"ok": False, "error": "Comando desconhecido."}
        if comando.get("kind") == "show_main":
            self._principal._j._tray_mostrar()
        else:
            self._principal._j._push("editor_panel_action", comando)
        return {"ok": True}


class Api:

    _DEMO_RETORNOS_BLOQUEADOS = {
        "logs_limpar": False,
        "logs_reiniciar_ngrok": False,
        "gateway_endpoint_alterar": {"ok": False, "mensagem": "Indisponível no modo demo."},
        "gateway_reiniciar": {"ok": False, "mensagem": "Indisponível no modo demo."},
        "listar_repos_github": [],
        "emily_atualizacao_estado": {"em_pacote": False, "demo": True,
                                      "erro": "Atualização bloqueada durante o Modo Demo."},
        "emily_atualizacao_inicio": {"verificar": False, "demo": True},
        "emily_atualizar_aplicar": "Bloqueado durante o Modo Demo.",
        "emily_atualizacao_escolher_origem": "Bloqueado durante o Modo Demo.",
        "emily_atualizar_desfazer": "Bloqueado durante o Modo Demo.",
        "emily_code_escolher_pasta": None,
        "ptt": False,
        "capturar_tela": False,
        "agente_ui_iniciar": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "agente_ui_pausar": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "agente_ui_retomar": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "agente_ui_cancelar": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "agente_ui_mensagem": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "navegador_interno_acao": {"ok": False, "erro": "Indisponível no Modo Demo."},
        "abrir_app": False,
        "set_toggle": False,
        "organizar_downloads": "Bloqueado durante o Modo Demo.",
        "tv_salvar": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "tv_editar": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "tv_remover": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "tv_conectar": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "tv_parear": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "tv_codigo": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "tv_dispositivos": [],
        "voz_fish_definir": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "casa_estado": {"ok": False, "configurada": False, "dispositivos": []},
        "casa_luz": {"ok": False, "mensagem": "Bloqueado durante o Modo Demo."},
        "definir_provedor_e_modelo": False,
        "definir_modelo": False,
        "visual_modelo_definir": False,
        "definir_raciocinio": False,
        "definir_volume_voz": False,
        "discord_definir_modelo": False,
        "escolher_avatar": None,
        "listar_modos": [],
        "ativar_modo": False,
        "listar_memoria": [],
        "add_fato": False,
        "del_fato": False,
        "memoria_unificada_estado": {"ativa": False, "demo": True,
                                      "mensagem": "Memória desativada no Modo Demo."},
        "memoria_unificada_listar": [],
        "memoria_unificada_esquecer": False,
        "memoria_unificada_reativar": False,
        "add_fato_pessoa": "Bloqueado durante o Modo Demo.",
        "del_fato_pessoa": "Bloqueado durante o Modo Demo.",
        "listar_pessoas_discord": [],
        "escolher_arquivos": [],
        "salvar_colado": None,
        "resolver_arrastados": [],
        "salvar_imagem": None,
        "cloud_escolher_armazenamento": {"ok": False, "demo": True,
                                          "erro": "Bloqueado durante o Modo Demo."},
        "cloud_migrar_armazenamento": {"ok": False, "demo": True,
                                        "erro": "Bloqueado durante o Modo Demo."},
        "cloud_escolher_importar": {"ok": False, "itens": [], "demo": True,
                                     "erro": "Importação real bloqueada no Modo Demo."},
        "cloud_escolher_pasta_importar": {"ok": False, "itens": [], "demo": True,
                                           "erro": "Importação real bloqueada no Modo Demo."},
        "cloud_importar_caminhos": {"ok": False, "itens": [], "demo": True,
                                     "erro": "Importação real bloqueada no Modo Demo."},
        "cloud_exportar": {"ok": False, "demo": True,
                            "erro": "Exportação bloqueada no Modo Demo."},
        "cloud_abrir": {"ok": False, "demo": True,
                         "erro": "Abertura no sistema bloqueada no Modo Demo."},
        "cloud_compactado_listar": {"ok": False, "entradas": [], "demo": True,
                                     "erro": "Compactados reais ficam bloqueados no Modo Demo."},
        "cloud_compactado_extrair": {"ok": False, "demo": True,
                                      "erro": "Extração bloqueada no Modo Demo."},
        "cloud_sincronizar": {"ok": False, "demo": True,
                               "erro": "Sincronização bloqueada no Modo Demo."},
        "cloud_compartilhar": {"ok": False, "demo": True,
                                "erro": "Compartilhamento bloqueado no Modo Demo."},
    }

    def __getattribute__(self, nome):
        """Última barreira das ações públicas que jamais rodam numa demo."""
        bloqueados = object.__getattribute__(self, "_DEMO_RETORNOS_BLOQUEADOS")
        if nome in bloqueados:
            try:
                import modo_demo
                if modo_demo.ativo():
                    retorno = bloqueados[nome]
                    return lambda *args, **kwargs: copy.deepcopy(retorno)
            except Exception:
                pass
        return object.__getattribute__(self, nome)

    def __init__(self, janela: "JanelaEmily"):
        self._j = janela
        self._xadrez_visivel = False
        self._xadrez_visibilidade_serial = -1
        self._atualizacao_auto_consultada = False
        self._editor_panel_lock = threading.RLock()
        self._editor_panel_snapshot = {}
        self._editor_panel_version = 0
        self._editor_panel_serial = -1
        self._editor_panel_window = None
        self._demo_contexto_real = None
        self._demo_turnos = 0
        self._demo_lock = threading.RLock()
        self._enviar_lock = threading.RLock()
        self._regenerar_lock = threading.Lock()
        self._regenerando = False
        janela._editor_api = self
        global _api_registrada
        _api_registrada = self

    @staticmethod
    def _demo_ativo() -> bool:
        try:
            import modo_demo
            return modo_demo.ativo()
        except Exception:
            return False

    def _demo_turno_iniciar(self) -> None:
        with self._demo_lock:
            self._demo_turnos += 1

    def _demo_turno_encerrar(self) -> None:
        with self._demo_lock:
            self._demo_turnos = max(0, self._demo_turnos - 1)

    def editor_painel_estado(self, estado: dict, serial: int) -> dict:
        if not isinstance(estado, dict) or len(json.dumps(estado)) > 4 * 1024 * 1024:
            return {"ok": False, "error": "Estado de editor inválido."}
        with self._editor_panel_lock:
            if serial > self._editor_panel_serial:
                self._editor_panel_serial = serial
                self._editor_panel_snapshot = estado
                self._editor_panel_version += 1
        return {"ok": True}

    def editor_painel_abrir(self) -> dict:
        try:
            import webview
            with self._editor_panel_lock:
                if self._editor_panel_window is not None:
                    self._editor_panel_window.show()
                    self._editor_panel_window.restore()
                    return {"ok": True}
                port = self._j._httpd.server_address[1]
                panel = webview.create_window("Editor da Emily — Propriedades",
                    f"http://127.0.0.1:{port}/editor-panel.html",
                    js_api=EditorPanelApi(self), width=1040, height=820,
                    min_size=(720, 560), resizable=True, text_select=True,
                    background_color="#1c1b19")
                self._editor_panel_window = panel
                def esconder():
                    panel.hide()
                    return False
                self._editor_panel_close_handler = esconder
                panel.events.closing += esconder
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def editor_android_abrir(self) -> dict:
        try:
            import android_editor, editor_interface, webview
            if self._demo_ativo(): return {"ok":False,"error":"Abra a Emily fora do modo demo."}
            root=editor_interface.destinos()[1]
            if root is None or not (root / "EmilyAPP2/app/build.gradle.kts").is_file():
                return {"ok":False,"error":"O editor Android precisa do projeto fonte e Android SDK neste PC."}
            manager=getattr(self,"_android_editor",None)
            if manager is None:
                manager=android_editor.Manager(root); self._android_editor=manager
            manager.open=True
            if manager.window is not None:
                manager.window.show();manager.window.restore();return {"ok":True}
            port=self._j._httpd.server_address[1]
            window=webview.create_window("Editor Android da Emily",f"http://127.0.0.1:{port}/android-editor.html",
                js_api=android_editor.API(manager,self),width=1360,height=900,min_size=(960,640),
                resizable=True,text_select=True,background_color="#1c1b19")
            manager.window=window
            def close_editor():
                threading.Thread(target=lambda:window.evaluate_js("window.AndroidEditor?.requestClose()"),daemon=True).start()
                return False
            window.events.closing += close_editor
            return {"ok":True}
        except Exception as exc: return {"ok":False,"error":str(exc)}

    def editor_painel_ocultar(self) -> dict:
        if self._editor_panel_window is not None:
            self._editor_panel_window.hide()
        return {"ok": True}

    def _editor_assistente(self):
        with self._editor_panel_lock:
            if getattr(self, "_editor_ai", None) is None:
                import editor_interface, editor_assistant
                _, root = editor_interface.destinos()
                if root is None:
                    raise ValueError("Não encontrei o projeto da Emily para editar código.")
                targets = [root / "dist/Emily/_internal", root / "emily-windows-instance",
                           root.parent / "emily-windows-instance", root / "emily-linux-instance"]
                self._editor_ai = editor_assistant.Assistant(root, [p for p in targets if (p / "web/index.html").is_file()])
                self._editor_ai_restart_pending = False
            return self._editor_ai

    def _editor_ai_imagens_locais(self, caminhos):
        import editor_assets
        images=[];errors=[]
        for caminho in caminhos[:4]:
            try:
                path=Path(caminho)
                if path.stat().st_size>editor_assets.MAX_INPUT: raise ValueError('Imagem maior que 4 MB.')
                raw,width,height=editor_assets.raster(path.read_bytes())
                images.append({'name':path.name,'data':'data:image/webp;base64,'+base64.b64encode(raw).decode('ascii'),'width':width,'height':height})
            except Exception as exc:errors.append(str(exc))
        return {'ok':True,'images':images,'errors':errors}

    def editor_ai_clipboard(self) -> dict:
        """Compatibilidade com imagem nativa: mesmas fontes usadas no chat normal."""
        try:
            if self._demo_ativo() or not getattr(self._j,'_editor_active',False):
                return {'ok':False,'error':'Abra o modo Editor primeiro.'}
            result=self.colar_imagem_nativa()
            if not result.get('ok'):return {'ok':False,'error':result.get('erro','sem_imagem')}
            return self._editor_ai_imagens_locais([result['anexo']['caminho']])
        except Exception as exc:return {'ok':False,'error':str(exc)}

    def editor_ai_arquivos(self, caminhos=None, escolher=False) -> dict:
        """Seleciona imagens ou resolve URIs do arrastar sem navegar a WebView."""
        try:
            if self._demo_ativo() or not getattr(self._j,'_editor_active',False):
                return {'ok':False,'error':'Abra o modo Editor primeiro.'}
            if escolher:
                import webview
                paths=self._j._janela.create_file_dialog(webview.OPEN_DIALOG,allow_multiple=True,
                    file_types=('Imagens (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.ico)',))
                if not paths:return {'ok':True,'images':[],'cancelled':True}
                paths=[paths] if isinstance(paths,str) else list(paths)
            else:
                if not isinstance(caminhos,list) or any(not isinstance(p,str) or len(p)>4096 for p in caminhos):
                    raise ValueError('Caminhos inválidos.')
                paths=[f['caminho'] for f in self.resolver_arrastados(caminhos[:4])]
            return self._editor_ai_imagens_locais(paths)
        except Exception as exc:return {'ok':False,'error':str(exc)}

    def editor_ai_enviar(self, texto: str, contexto: dict, imagens=None) -> dict:
        try:
            if self._demo_ativo(): return {"ok": False, "error": "Edição de código indisponível na demonstração."}
            if not getattr(self._j, "_editor_active", False): return {"ok":False,"error":"Abra o modo Editor primeiro."}
            return self._editor_assistente().start(texto, contexto, imagens)
        except Exception as exc: return {"ok":False,"error":str(exc)}

    def editor_ai_estado(self) -> dict:
        try:
            assistant = self._editor_assistente()
            state = assistant.state(); job = state.get("job") or {}; result = job.get("result")
            if result and result.get("restart"): self._editor_ai_restart_pending = True
            if result and result.get("files") and not result.get("publication"):
                with assistant.lock:
                    if not assistant.job['result'].get('publication'):
                        try:
                            from publicar_windows_codigo import publicar, DEST
                            with __import__('editor_interface').TRAVA:
                                meta = json.loads((DEST / 'latest.json').read_text())
                                present=[f for f in result['files'] if (assistant.root/f).is_file()]
                                removed=[f for f in result['files'] if f not in present and f in meta.get('files',{})]
                                publicar(int(meta['version']) + 1, meta['installer'], root=assistant.root,
                                         selecionar=present or ['editor_assistant.py'], retirar=removed)
                            publication = {"ok":True,"version":int(meta['version'])+1}
                        except Exception as exc: publication={"ok":False,"error":str(exc)}
                        assistant.job['result']['publication']=publication
                        result['publication']=publication
            state['restart_pending'] = self._editor_ai_restart_pending
            return state
        except Exception as exc: return {"ok":False,"error":str(exc)}

    def editor_ai_cancelar(self) -> dict:
        try:
            self._editor_assistente().cancel.set()
            return {"ok":True}
        except Exception as exc: return {"ok":False,"error":str(exc)}

    def editor_ai_desfazer(self, job_id: str) -> dict:
        try:
            assistant=self._editor_assistente(); result=assistant.undo(job_id)
            if result.get('restart'): self._editor_ai_restart_pending=True
            if result.get('ok') and result.get('files'):
                # A próxima consulta publica a versão restaurada no canal Windows.
                with assistant.lock: assistant.job['result'].pop('publication', None)
            return result
        except Exception as exc: return {"ok":False,"error":str(exc)}

    def programacao_reiniciar(self, sessao: str) -> dict:
        """Botão explicitamente acionado pelo usuário após uma mudança no chat."""
        try:
            import programacao
            if self._demo_ativo(): return {"ok":False,"error":"Reinício não disponível no modo demo."}
            folder,data=programacao.load(sessao)
            if not data.get('aplicacao',{}).get('reiniciar_pc') or data['estado']=='desfeito':
                return {"ok":False,"error":"Não há mudança Python aplicada nesta sessão."}
            for job in data['jobs']:
                if programacao.status(folder,data,job)['estado'] in {'iniciando','executando'}:
                    return {"ok":False,"error":"Espere os testes/publicação terminarem antes de reiniciar."}
            if data.get('publicacao') and programacao.status(folder,data,data['publicacao'])['estado']!='concluido':
                return {"ok":False,"error":"Resolva a falha de publicação antes de reiniciar."}
            self._editor_ai_restart_pending=True
            return self.editor_ai_reiniciar()
        except Exception as exc: return {"ok":False,"error":str(exc)}

    def editor_ai_reiniciar(self) -> dict:
        try:
            import subprocess, sys, shutil
            assistant=self._editor_assistente()
            if not self._editor_ai_restart_pending: return {"ok":False,"error":"Não há alteração Python aguardando reinício."}
            if (assistant.state().get('job') or {}).get('running'): return {"ok":False,"error":"Espere a tarefa do editor terminar."}
            if getattr(self._j, '_ultimo_status', ('aguardando',))[0] in {'ocupada','pensando','falando','ouvindo','gravando'}:
                return {"ok":False,"error":"Espere a Emily concluir o atendimento atual."}
            import agente_ui
            if agente_ui.estado_agente_ui().get('ativo'): return {"ok":False,"error":"Encerre a tarefa visual antes de reiniciar."}
            android=getattr(self,'_android_editor',None)
            if android and android.open:return {"ok":False,"error":"Feche ou salve o editor Android antes de reiniciar."}
            if getattr(self._j, '_editor_dirty', False): return {"ok":False,"error":"Salve as alterações visuais antes de reiniciar."}
            env=os.environ.copy(); env['EMILY_INICIAR_OCULTA']='0';env['PYINSTALLER_RESET_ENVIRONMENT']='1'
            argv=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(assistant.root/'main.py')]
            if os.name=='nt':
                import base64
                def quoted(t): return "'"+str(t).replace("'","''")+"'"
                script=f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; Start-Process -FilePath {quoted(argv[0])} -WorkingDirectory {quoted(os.getcwd())}"
                if len(argv)>1: script+=' -ArgumentList '+quoted(' '.join(argv[1:]))
                subprocess.Popen(['powershell','-NoProfile','-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode()],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen(['/bin/sh','-c','while kill -0 "$1" 2>/dev/null; do sleep 0.2; done; shift; exec "$@"','emily-restart',str(os.getpid()),*argv],env=env,start_new_session=True)
            self._j._editor_close_authorized=True
            threading.Timer(.6,self._j._tray_sair).start()
            return {"ok":True}
        except Exception as exc: return {"ok":False,"error":str(exc)}

    def editor_carregar(self) -> dict:
        import editor_interface
        return editor_interface.carregar()

    def editor_salvar(self, documento: dict, revisao: str) -> dict:
        try:
            import editor_interface
            return editor_interface.salvar(documento, revisao)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def editor_estado(self, ativo: bool, alterado: bool, serial: int) -> dict:
        if serial >= getattr(self._j, "_editor_serial", -1):
            self._j._editor_serial = serial
            self._j._editor_dirty = bool(alterado)
            self._j._editor_active = bool(ativo)
        return {"ok": True}

    def editor_rascunho(self, documento: dict, revisao: str) -> dict:
        try:
            import editor_interface
            return editor_interface.salvar_rascunho(documento, revisao)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def editor_recuperar(self) -> dict:
        import editor_interface
        return editor_interface.carregar_rascunho()

    def editor_limpar_rascunho(self) -> dict:
        import editor_interface
        return editor_interface.limpar_rascunho()

    def editor_fechar(self, encerrar: bool = False) -> dict:
        self._j._editor_close_authorized = True
        self._j._editor_dirty = False
        self.editor_painel_ocultar()
        if encerrar:
            self._j._tray_sair()
        else:
            self._j._janela.hide()
            self._j._visivel = False
            self._j._editor_close_authorized = False
        return {"ok": True}

    def editor_importar(self) -> dict:
        try:
            import webview
            import editor_interface
            paths = (self._editor_panel_window or self._j._janela).create_file_dialog(webview.OPEN_DIALOG,
                allow_multiple=False, file_types=("Layout Emily (*.json)",))
            if not paths:
                return {"ok": True, "cancelled": True}
            path = Path(paths if isinstance(paths, str) else paths[0])
            if path.stat().st_size > editor_interface.MAX_BYTES:
                raise ValueError("Arquivo grande demais.")
            return {"ok": True, "document": editor_interface.validar(json.loads(path.read_text(encoding="utf-8")))}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def editor_exportar(self, documento: dict) -> dict:
        try:
            import webview
            import editor_interface
            documento = editor_interface.validar(documento)
            paths = (self._editor_panel_window or self._j._janela).create_file_dialog(webview.SAVE_DIALOG,
                save_filename="emily-layout.json", file_types=("Layout Emily (*.json)",))
            if not paths:
                return {"ok": True, "cancelled": True}
            path = Path(paths if isinstance(paths, str) else paths[0])
            if path.suffix.lower() != ".json":
                path = path.with_name(path.name + ".json")
            editor_interface._gravar(path, json.dumps(documento, ensure_ascii=True, indent=2) + "\n")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def editor_imagem(self) -> dict:
        try:
            import webview
            import editor_interface
            paths = (self._editor_panel_window or self._j._janela).create_file_dialog(webview.OPEN_DIALOG,
                allow_multiple=False, file_types=("Imagens (*.png;*.jpg;*.jpeg;*.webp)",))
            if not paths:
                return {"ok": True, "cancelled": True}
            return {"ok": True, "image": editor_interface.importar_imagem(paths if isinstance(paths, str) else paths[0])}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def estado_demo(self) -> dict:
        try:
            import modo_demo
            estado = modo_demo.estado()
            with self._demo_lock:
                estado["turnos_ativos"] = self._demo_turnos
            return estado
        except Exception as e:  # noqa: BLE001
            return {"ativo": False, "erro": str(e), "turnos_ativos": 0}

    def iniciar_demo(self) -> dict:
        """Ativa somente após clique explícito; nunca é restaurado no boot."""
        if self._demo_ativo():
            return {"ok": True, **self.estado_demo()}
        ocupado = self._j._ultimo_status[0] in {
            "ocupada", "pensando", "falando", "ouvindo", "gravando"}
        if ocupado:
            return {"ok": False, "erro": "Espere a resposta atual terminar antes de iniciar a demo."}
        try:
            import agente_ui
            import modo_demo
            import modelo
            # A demo bloqueia ações reais. Uma sessão visual iniciada antes dela
            # também precisa ser interrompida antes de trocar o contexto.
            if agente_ui.estado_agente_ui().get("ativo"):
                agente_ui.parar_agente_ui()
            self._demo_contexto_real = {
                "cid": self._j._cid,
                "historico": list(modelo.historico),
            }
            modo_demo.iniciar("Visitante")
            self._j._cid = None
            modelo.definir_historico([])
            return {"ok": True, **modo_demo.estado()}
        except Exception as e:  # noqa: BLE001
            _log(f"iniciar_demo: {e}")
            return {"ok": False, "erro": str(e), "ativo": False}

    def encerrar_demo(self) -> dict:
        with self._demo_lock:
            turnos = self._demo_turnos
        ocupado = self._j._ultimo_status[0] in {"ocupada", "pensando", "falando"}
        if turnos or ocupado:
            return {"ok": False, "ativo": True,
                    "erro": "Espere a resposta demonstrativa terminar antes de sair."}
        try:
            import modo_demo
            import modelo
            contexto = self._demo_contexto_real or {"cid": None, "historico": []}
            modo_demo.encerrar()
            self._j._cid = contexto.get("cid")
            modelo.definir_historico(contexto.get("historico") or [])
            self._demo_contexto_real = None
            self._j._resposta_emily = ""
            self._j._resposta_crua = ""
            self._j._falas_processo = []
            return {"ok": True, **modo_demo.estado()}
        except Exception as e:  # noqa: BLE001
            _log(f"encerrar_demo: {e}")
            return {"ok": False, "ativo": True, "erro": str(e)}

    # ── Identidade e tela inicial ─────────────────────────────────

    def uso_contexto(self) -> dict:
        """Medidor de contexto do modelo ATUAL. Local e instantâneo: o uso da
        assinatura Codex saiu daqui (levava até 15 s e travava o medidor)."""
        import contexto_chat, llm, modelo
        key=getattr(self._j, '_cid', None) or "normal"
        cfg=llm.rota('conversa')
        state=contexto_chat.state(key)
        if not modelo.web_turno_ativo(key) or not state:
            state=contexto_chat.display(key,cfg.modelo,modelo._mensagens_para_turno()+list(modelo.historico))
        return {"context":state}

    def perfil(self) -> dict:
        if self._demo_ativo():
            import modo_demo
            return {"nome": modo_demo.nome_usuario(), "sub": "Demonstração isolada",
                    "avatar": self._j._avatar, "avatar_usuario": "", "demo": True}
        nome = os.getenv("EMILY_USUARIO", "Vitor")
        # O retrato da Emily (o que aparece no hero e ao lado das mensagens dela)
        # é o `_avatar` da janela, SEMPRE o retrato de fábrica dela — nunca a
        # foto do usuário. A foto do usuário (ícone do canto + editor) é uma
        # preferência separada, pra uma não contaminar a outra.
        avatar = self._j._avatar
        avatar_usuario = ""
        try:
            import preferencias
            nome = (preferencias.obter("nome") or nome)
            avatar_usuario = preferencias.obter("avatar_usuario") or ""
            # Migração: antes da separação dos avatares, a foto que o Vitor
            # escolhia ficava na chave 'avatar'. Se ele tinha foto lá e ainda
            # não tem avatar_usuario, aproveita e migra (idempotente).
            if not avatar_usuario:
                legado = preferencias.obter("avatar") or ""
                if legado:
                    preferencias.definir(avatar_usuario=legado)
                    avatar_usuario = legado
        except Exception as e:  # noqa: BLE001
            _log(f"perfil: não li preferências ({e})")
        return {
            "nome": nome,
            "sub": "",
            "avatar": avatar,
            "avatar_usuario": avatar_usuario,
        }

    def logs_ler(self) -> dict:
        """Cauda segura do terminal e estado dos serviços para o painel da home."""
        if self._demo_ativo():
            import modo_demo
            dados = modo_demo.logs()
            dados["ngrok_disponivel"] = ambiente_fedora() and not __import__("gateway_endpoint").modo_oracle()
            if not dados["ngrok_disponivel"]:
                dados["ngrok"] = None
            return dados
        try:
            import emily_logs
            import servicos_runtime

            dados = emily_logs.ler()
            dados["ngrok_disponivel"] = ambiente_fedora() and not __import__("gateway_endpoint").modo_oracle()
            dados["ngrok"] = (servicos_runtime.estado_ngrok()
                              if dados["ngrok_disponivel"] else None)
            dados["empacotada"] = bool(getattr(__import__("sys"), "frozen", False))
            return dados
        except Exception as e:  # noqa: BLE001
            _log(f"logs_ler: {e}")
            return {"ok": False, "texto": f"Não consegui ler os logs: {e}",
                    "caminho": "", "tamanho": 0,
                    "ngrok_disponivel": ambiente_fedora(),
                    "ngrok": {"estado": "erro"} if ambiente_fedora() else None}

    def logs_limpar(self) -> bool:
        """Limpa o arquivo exibido sem desativar a captura da sessão atual."""
        try:
            import emily_logs

            ok = emily_logs.limpar()
            if ok:
                print("[LOG] histórico limpo pela interface")
            return ok
        except Exception as e:  # noqa: BLE001
            _log(f"logs_limpar: {e}")
            return False

    def logs_reiniciar_ngrok(self) -> bool:
        """Tenta subir o túnel novamente sem reiniciar toda a Emily."""
        if not ambiente_fedora():
            return False
        try:
            import servicos_runtime

            return servicos_runtime.reiniciar_ngrok(5000)
        except Exception as e:  # noqa: BLE001
            _log(f"logs_reiniciar_ngrok: {e}")
            return False

    def gateway_endpoint_estado(self) -> dict:
        if not ambiente_fedora():
            return {"disponivel": False, "url": "", "tunel_online": False}
        try:
            import gateway_endpoint
            return {"disponivel": True, **gateway_endpoint.estado()}
        except Exception as e:  # noqa: BLE001
            _log(f"gateway_endpoint_estado: {e}")
            return {"disponivel": True, "url": "", "tunel_online": False,
                    "erro": "Não consegui consultar o túnel."}

    def gateway_parear_dispositivo(self) -> dict:
        if self._demo_ativo(): return {"ok": False, "mensagem": "Indisponível no modo demo."}
        try:
            import importlib.util
            from pathlib import Path
            path = Path(__file__).parent / "emily-relay/parear_dispositivo.py"
            spec = importlib.util.spec_from_file_location("emily_pair_device", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return {"ok": True, "code": module.gerar_codigo(), "validade": 600}
        except Exception:
            return {"ok": False, "mensagem": "Não foi possível gerar o código. Verifique a conexão com a Oracle."}

    def gateway_endpoint_alterar(self, url: str) -> dict:
        if not ambiente_fedora() or self._demo_ativo():
            return {"ok": False, "mensagem": "Disponível somente no Fedora fora do modo demo."}
        try:
            import gateway_endpoint
            url = gateway_endpoint.validar_url(url)

            def trabalho():
                try:
                    resultado = gateway_endpoint.alterar(url)
                except Exception as e:  # noqa: BLE001
                    _log(f"gateway_endpoint_alterar: {e}")
                    resultado = {"ok": False, "mensagem": "Não consegui aplicar o novo endereço."}
                self._j._push("gateway_endpoint", resultado)

            threading.Thread(target=trabalho, name="gateway-endpoint", daemon=True).start()
            return {"ok": True, "mensagem": "Salvando endereço e reiniciando o túnel…"}
        except ValueError as e:
            return {"ok": False, "mensagem": str(e)}
        except Exception as e:  # noqa: BLE001
            _log(f"gateway_endpoint_alterar: {e}")
            return {"ok": False, "mensagem": "Não consegui iniciar a troca."}

    def gateway_reiniciar(self) -> dict:
        """Agenda o restart após responder à janela (que pode ser filha do gateway)."""
        if not ambiente_fedora() or self._demo_ativo():
            return {"ok": False, "mensagem": "Disponível somente no Fedora fora do modo demo."}
        try:
            import subprocess
            subprocess.run([
                "systemd-run", "--user", "--quiet", "--on-active=3s",
                "--unit=emily-gateway-restart-" + str(int(time.time())),
                "/usr/bin/systemctl", "--user", "restart", "emily-gateway.service",
            ], check=True, timeout=5)
            return {"ok": True, "mensagem": "Gateway será reiniciado em alguns segundos."}
        except Exception as e:  # noqa: BLE001
            _log(f"gateway_reiniciar: {e}")
            return {"ok": False, "mensagem": "Não consegui agendar o reinício do gateway."}

    def sugestoes(self) -> list:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.sugestoes()
        return SUGESTOES

    def listar_repos_github(self) -> list:
        """Lista os repositórios do Vitor no GitHub, no formato que o popover
        do JS espera: {id, titulo, sub}. Silencioso se falhar (não configurado,
        sem rede, etc.) — o popover mostra mensagem amigável."""
        try:
            import github_api
            raw = github_api.listar_repos()
            repos = []
            for linha in raw.split("\n"):
                if not linha.startswith("- "):
                    continue
                resto = linha[2:]
                if ": " in resto:
                    nome, _, desc = resto.partition(": ")
                    nome, desc = nome.strip(), desc.strip()
                else:
                    nome, desc = resto.strip(), ""
                if "/" in nome or not nome:
                    continue
                # Separa o marcador de visibilidade "(privado)"/"(público)" do nome.
                visib = ""
                if nome.endswith(")"):
                    nome, _, visib = nome.rpartition(" ")
                repos.append({"id": nome, "titulo": nome, "sub": desc[:60],
                              "visib": visib.strip("()")})
            return repos
        except Exception:  # noqa: BLE001
            return []

    # ── Emily Code: perguntas e permissões ─────────────────────────
    #
    # O ferramentas.py chama interface_web._perguntar_ao_vitor() pra abrir um
    # modal no JS e esperar a resposta. A resposta volta por aqui.

    def emily_code_definir_projeto(self, caminho: str, cid: str = "") -> str:
        """Define a pasta de projeto do Emily Code."""
        global _resultado_pasta, _resultado_pasta_evento
        try:
            import emily_code
            with emily_code.code_contexto_conversa((cid or "").strip() or None):
                r = emily_code.definir_projeto(caminho)
            # Se o aviso de troca de pasta (code_mudar_pasta) está esperando,
            # libera a thread com o caminho definido.
            if r.startswith("Pasta de projeto definida"):
                _resultado_pasta = caminho
                _resultado_pasta_evento.set()
            return r
        except Exception as e:  # noqa: BLE001
            _log(f"emily_code_definir_projeto: {e}")
            return f"Não consegui definir o projeto: {e}"

    def emily_code_cancelar_pasta(self) -> str:
        """Vitor cancelou a troca de pasta (botão Cancelar do aviso)."""
        global _resultado_pasta, _resultado_pasta_evento
        try:
            _resultado_pasta = None
            _resultado_pasta_evento.set()
            return "Ok."
        except Exception as e:  # noqa: BLE001
            _log(f"emily_code_cancelar_pasta: {e}")
            return "Erro."

    def emily_code_escolher_pasta(self) -> Optional[str]:
        """Diálogo NATIVO de seleção de pasta (explorar do Windows) pro
        Emily Code. Devolve o caminho escolhido ou None se cancelou."""
        try:
            import webview
            j = self._j._janela
            escolhidos = j.create_file_dialog(webview.FOLDER_DIALOG,
                                              allow_multiple=False)
            if escolhidos and escolhidos[0]:
                return str(escolhidos[0])
            return None
        except Exception as e:  # noqa: BLE001
            _log(f"emily_code_escolher_pasta: {e}")
            return None

    # ── Atualização (boot e botão "Atualizar agora") ────────────────
    #
    # O pacote tem duas camadas: o motor (bibliotecas, embutido) e o código
    # da Emily (atualizável por cima — ver atualizador_emily.py). O boot
    # consulta o estado uma vez; a tela de Configurações mantém o botão manual.

    def emily_atualizacao_estado(self) -> dict:
        """O que a seção Atualização mostra: tem mudanças? pode desfazer?"""
        try:
            if os.name == "nt" and getattr(sys, "frozen", False):
                import windows_update
                return windows_update.consultar()
            import atualizador_emily
            return atualizador_emily.estado_atualizacao()
        except Exception as e:  # noqa: BLE001
            _log(f"emily_atualizacao_estado: {e}")
            return {"em_pacote": False, "erro": str(e)}

    def emily_atualizacao_inicio(self) -> dict:
        """Uma checagem por processo, ao terminar de montar a tela do PC."""
        if self._atualizacao_auto_consultada:
            return {"verificar": False}
        self._atualizacao_auto_consultada = True
        if os.name == "nt" and getattr(sys, "frozen", False):
            return {"verificar": False}
        estado = self.emily_atualizacao_estado()
        estado["verificar"] = bool(estado.get("em_pacote")
                                   and estado.get("origem_ok")
                                   and estado.get("quantos", 0) > 0)
        return estado

    def emily_atualizar_aplicar(self) -> str:
        """Valida e aplica o código da pasta do projeto; reinicia em seguida."""
        if not _trava_atualizacao.acquire(blocking=False):
            return "Já estou validando uma atualização. Aguarde o resultado."
        try:
            if os.name == "nt" and getattr(sys, "frozen", False):
                import windows_update
                if windows_update.verificar_e_instalar():
                    # O setup substitui Emily.exe e _internal; liberar a janela
                    # antes da cópia evita arquivo em uso e processo duplicado.
                    threading.Timer(0.5, self._j._tray_sair).start()
                    return "OK Atualização iniciada; a Emily reabrirá após atualizar."
                return "Nenhuma versão nova disponível ou download indisponível."
            import atualizador_emily
            return atualizador_emily.aplicar_atualizacao()
        except Exception as e:  # noqa: BLE001
            _log(f"emily_atualizar_aplicar: {e}")
            return f"Erro na atualização: {e}"
        finally:
            _trava_atualizacao.release()

    def emily_atualizacao_escolher_origem(self) -> str:
        """Escolhe e registra a pasta-fonte quando ela foi movida após o build."""
        try:
            import atualizador_emily
            import webview

            escolhidos = self._j._janela.create_file_dialog(
                webview.FOLDER_DIALOG, allow_multiple=False)
            if not escolhidos or not escolhidos[0]:
                return "Cancelado."
            return atualizador_emily.definir_origem_projeto(str(escolhidos[0]))
        except Exception as e:  # noqa: BLE001
            _log(f"emily_atualizacao_escolher_origem: {e}")
            return f"Não consegui escolher a origem: {e}"

    def emily_atualizar_desfazer(self) -> str:
        """Volta pro estado anterior à última atualização; reinicia em seguida."""
        if not _trava_atualizacao.acquire(blocking=False):
            return "Já estou validando uma atualização. Aguarde o resultado."
        try:
            import atualizador_emily
            return atualizador_emily.desfazer_atualizacao()
        except Exception as e:  # noqa: BLE001
            _log(f"emily_atualizar_desfazer: {e}")
            return f"Erro ao desfazer: {e}"
        finally:
            _trava_atualizacao.release()

    def emily_code_estado(self, cid: str = "") -> dict:
        """Estado atual do Emily Code pro JS: pasta de projeto + permissões."""
        if self._demo_ativo():
            import modo_demo
            return {"projeto": str(modo_demo.workspace() or ""),
                    "permitir_sempre": [], "demo": True}
        try:
            import emily_code
            import preferencias
            with emily_code.code_contexto_conversa((cid or "").strip() or None):
                raiz = emily_code.projeto_raiz()
            permissoes = preferencias.obter("emily_code_permissoes", {}) or {}
            return {
                "projeto": str(raiz) if raiz else "",
                "permitir_sempre": list(permissoes.get("sempre", []) or []),
            }
        except Exception as e:  # noqa: BLE001
            _log(f"emily_code_estado: {e}")
            return {"projeto": "", "permitir_sempre": []}

    def emily_code_responder(self, resposta: str) -> None:
        """Resposta do Vitor a uma pergunta do modal (code_perguntar)."""
        global _resposta_pergunta, _resposta_pergunta_evento
        try:
            _resposta_pergunta = resposta or ""
            _resposta_pergunta_evento.set()
        except Exception as e:  # noqa: BLE001
            _log(f"emily_code_responder: {e}")

    def responder_pergunta_usuario(self, ticket: str, resposta: str) -> bool:
        texto = str(resposta or "")[:2000]
        with _perguntas_tarefa_lock:
            pendente = _perguntas_tarefa.get(str(ticket))
            if not pendente or pendente.get("respondida"):
                return False
            pendente["respondida"] = True
            pendente["resposta"] = texto
        try:
            if texto.strip():
                self._j._registrar_na_conversa("user", texto)
                self._j.add_mensagem_usuario(texto)
        finally:
            pendente["evento"].set()
        return True

    def emily_code_permissao(self, resposta: str, acao: str, caminho: str) -> str:
        """Resposta do Vitor ao modal de permissão. Seta a resposta pendente,
        que o emily_code.executar está esperando (fluxo bloqueante)."""
        global _resposta_permissao, _resposta_permissao_evento
        try:
            _resposta_permissao = (resposta or "nao").strip().lower()
            _resposta_permissao_evento.set()
            return "Permissão registrada."
        except Exception as e:  # noqa: BLE001
            _log(f"emily_code_permissao: {e}")
            return f"Erro ao processar permissão: {e}"

    def emily_code_enviar(self, texto: str, cid: str = "") -> dict:
        """
        Envia uma mensagem pro Emily Code (fluxo SEPARADO da conversa normal).
        Usa a conversa ATIVA do Emily Code como histórico — cada chat do code
        tem seu próprio contexto, salvo em disco.
        """
        try:
            import modelo
            import emily_code
            texto = (texto or "").strip()
            if not texto:
                return {"ok": False, "erro": "Mensagem vazia."}
            modelo._abrir_dominio("code")
            # O ID vem da aba selecionada no frontend. Não confiar apenas na
            # conversa global evita mandar a mensagem à aba que foi aberta
            # durante o await da ponte.
            cid = (cid or "").strip()
            existentes = {c["id"] for c in emily_code.code_listar_conversas()}
            if cid not in existentes:
                cid = emily_code.code_criar_conversa(texto)
            else:
                emily_code.code_definir_conversa_atual(cid)
            # Salva a mensagem do usuário na conversa.
            emily_code.code_acrescentar(cid, "user", texto)
            em_demo = self._demo_ativo()
            instrucao = (
                "Você está no Emily Code, o assistente de código da Emily. "
                "Responda com o texto que vai aparecer num terminal. "
                "Use as ferramentas de código (code_*) pra ler, escrever, editar, "
                + ("buscar no projeto temporário da demonstração. Não execute comandos, "
                   "não instale pacotes e não acesse nenhum caminho fora dele. "
                   if em_demo else "buscar e executar no projeto do Vitor. ") +
                "IMPORTANTE — nunca pare no meio: depois de usar uma ferramenta, "
                "continue a tarefa chamando a próxima ferramenta necessária até "
                "concluir o que ele pediu. Só responda em texto quando o trabalho "
                "estiver FEITO. Ler não é concluir; se você leu um arquivo pra "
                "editar, a próxima chamada é a edição. Não diga 'vou fazer X' e "
                "parar — faça X. Use as ferramentas de uma vez por resposta quando "
                "der (ler vários arquivos em paralelo). "
                + ("No Modo Demo, não chame revisão externa nem outro agente. "
                   if em_demo else
                   "REVISÃO: pra tarefa complexa, crítica ou de alto risco (vários "
                   "arquivos, lógica não-trivial, mexer em código importante), depois "
                   "de concluir a edição chame code_revisar pra ter a revisão do "
                   "DeepSeek. Pra ajuste pequeno e isolado, não precisa. ") +
                "Seja direta, "
                "sem cerimônia, no tom dela."
            )
            # Ponte de progresso das ferramentas pro terminal do Emily Code.
            # O conversar_com_ferramentas emite fases "ferramenta"/"resultado"/
            # "fala"/"fim"; aqui viram eventos emily_code tipo "acao" que o JS
            # transforma em linhas de status (spinner Braille, ✓/✗/⚠, diff).
            _inicio_acao: dict = {}

            def _on_progresso(fase, dados):
                try:
                    if fase == "ferramenta":
                        nome = dados.get("nome", "")
                        _inicio_acao[nome] = time.monotonic()
                        self._j._push("emily_code", {
                            "tipo": "acao",
                            "cid": cid,
                            "fase": "iniciou",
                            "nome": nome,
                            "args": dados.get("args", {}) or {},
                        })
                    elif fase == "resultado":
                        nome = dados.get("nome", "")
                        inicio = _inicio_acao.pop(nome, None)
                        duracao = (time.monotonic() - inicio) if inicio else 0.0
                        self._j._push("emily_code", {
                            "tipo": "acao",
                            "cid": cid,
                            "fase": "concluiu",
                            "nome": nome,
                            "ok": bool(dados.get("ok")),
                            "mudou": bool(dados.get("mudou")),
                            "erro": dados.get("erro") or "",
                            "texto": dados.get("resultado") or "",
                            "duracao": duracao,
                        })
                    elif fase == "fim":
                        self._j._push("emily_code", {"tipo": "acao",
                                                     "fase": "fim", "cid": cid})
                except Exception as e:  # noqa: BLE001
                    _log(f"emily_code on_progresso: {e}")

            def _responder(cid_local):
                if em_demo:
                    self._demo_turno_iniciar()
                try:
                    # Prende pasta/permissões à conversa de origem e serializa a
                    # troca do histórico global. Navegar na UI continua livre;
                    # só os turnos do modelo entram na fila.
                    with emily_code.code_contexto_conversa(cid_local):
                        with _trava_modelo_code:
                            hist_normal = list(modelo.historico)
                            modelo.historico[:] = emily_code.code_para_o_modelo(cid_local)
                            try:
                                resp = modelo.conversar_com_ferramentas(
                                    texto, instrucao_extra=instrucao,
                                    rota_nome="code_implementador",
                                    canal="emily_code", memory_pool="code",
                                    on_progresso=_on_progresso)
                                self._j._push("emily_code", {"tipo": "acao",
                                                             "fase": "fim",
                                                             "cid": cid_local})
                            finally:
                                modelo.historico[:] = hist_normal
                    # Salva a resposta da Emily na conversa.
                    emily_code.code_acrescentar(cid_local, "emily", resp or "Feito.")
                    self._j._push("emily_code", {"tipo": "resposta",
                                "texto": resp or "Feito.",
                                "cid": cid_local,
                                "conversas": True})
                except Exception as e:  # noqa: BLE001
                    _log(f"emily_code_enviar: {e}")
                    self._j._push("emily_code", {"tipo": "resposta",
                                "texto": f"Erro: {e}",
                                "cid": cid_local,
                                "conversas": True})
                finally:
                    if em_demo:
                        self._demo_turno_encerrar()
            threading.Thread(target=_responder, args=(cid,), daemon=True).start()
            return {"ok": True, "cid": cid}
        except Exception as e:  # noqa: BLE001
            _log(f"emily_code_enviar: {e}")
            return {"ok": False, "erro": str(e), "cid": cid or ""}

    # ── CRUD de conversas do Emily Code ────────────────────────────
    # Separadas das conversas normais (arquivo próprio).

    def code_listar_conversas(self) -> list:
        try:
            import emily_code
            return emily_code.code_listar_conversas()
        except Exception as e:  # noqa: BLE001
            _log(f"code_listar_conversas: {e}")
            return []

    def code_criar_conversa(self, primeira: str = "") -> str:
        try:
            import emily_code
            cid = emily_code.code_criar_conversa(primeira)
            return cid or ""
        except Exception as e:  # noqa: BLE001
            _log(f"code_criar_conversa: {e}")
            return ""

    def code_renomear_conversa(self, cid: str, titulo: str) -> bool:
        try:
            import emily_code
            return bool(emily_code.code_renomear_conversa(cid, titulo))
        except Exception as e:  # noqa: BLE001
            _log(f"code_renomear_conversa: {e}")
            return False

    def code_apagar_conversa(self, cid: str) -> bool:
        try:
            import emily_code
            return bool(emily_code.code_apagar_conversa(cid))
        except Exception as e:  # noqa: BLE001
            _log(f"code_apagar_conversa: {e}")
            return False

    def code_abrir_conversa(self, cid: str) -> list:
        try:
            import emily_code
            msgs = emily_code.code_abrir_conversa(cid)
            return [{"papel": m.get("papel", "user"), "texto": m.get("texto", "")}
                    for m in msgs]
        except Exception as e:  # noqa: BLE001
            _log(f"code_abrir_conversa: {e}")
            return []

    def estado_perfil(self) -> dict:
        """Tudo que o editor de perfil precisa pré-preencher: nome, foto e a
        personalidade extra. Separado do perfil() porque este carrega o texto
        editável, que o perfil() (usado pra desenhar o canto) não precisa."""
        base = self.perfil()
        if self._demo_ativo():
            return {"nome": base.get("nome", ""), "avatar_usuario": "",
                    "personalidade_extra": "", "demo": True}
        extra = ""
        try:
            import preferencias
            extra = preferencias.obter("personalidade_extra") or ""
        except Exception as e:  # noqa: BLE001
            _log(f"estado_perfil: {e}")
        return {"nome": base.get("nome", ""),
                "avatar_usuario": base.get("avatar_usuario", ""),
                "personalidade_extra": extra}

    # ── Music player ──────────────────────────────────────────────
    #
    # O áudio roda no iframe embedado do YouTube dentro da própria WebView
    # (controlado pela API JS deles); aqui é só a camada de DADO: playlists,
    # busca com prévia, favoritos e estado persistido. Nada toca no processo.

    def playlist(self) -> list:
        """Compat: músicas da playlist ativa (o que a barra mostra)."""
        if self._demo_ativo():
            import modo_demo
            return modo_demo.playlist()
        try:
            import music_player
            return music_player.listar()
        except Exception as e:  # noqa: BLE001
            _log(f"playlist: {e}")
            return []

    def playlist_geral(self) -> dict:
        """Tudo que o modal precisa: playlists, ativa, favoritos."""
        if self._demo_ativo():
            import modo_demo
            return modo_demo.playlist_geral()
        try:
            import music_player
            import music_sync
            music_sync.start()
            return music_player.listar_playlists()
        except Exception as e:  # noqa: BLE001
            _log(f"playlist_geral: {e}")
            return {"playlists": {}, "ativa": "default", "favoritos": {}}

    def playlist_criar(self, nome: str, foto: str = "") -> dict:
        nome = (nome or "").strip()
        if not nome:
            return {"erro": "Dá um nome pra playlist."}
        if self._demo_ativo():
            import modo_demo
            return ({"ok": True} if modo_demo.playlist_criar(nome, foto)
                    else {"erro": "Já existe uma playlist com esse nome."})
        try:
            import music_player
            if music_player.criar_playlist(nome):
                if foto:
                    music_player.definir_foto_playlist(nome, foto)
                music_player.selecionar_playlist(nome)
                return {"ok": True}
            return {"erro": "Já existe uma playlist com esse nome."}
        except Exception as e:  # noqa: BLE001
            _log(f"playlist_criar: {e}")
            return {"erro": "Deu ruim criando a playlist."}

    def playlist_foto(self, nome: str, foto: str = "") -> dict:
        """Define a foto de uma playlist (data-uri) ou limpa se vazio."""
        nome = (nome or "").strip()
        if not nome:
            return {"erro": "Playlist inválida."}
        if self._demo_ativo():
            import modo_demo
            return ({"ok": True} if modo_demo.playlist_foto(nome, foto)
                    else {"erro": "Playlist não encontrada."})
        try:
            import music_player
            if music_player.definir_foto_playlist(nome, foto or ""):
                return {"ok": True}
            return {"erro": "Playlist não encontrada."}
        except Exception as e:  # noqa: BLE001
            _log(f"playlist_foto: {e}")
            return {"erro": "Deu ruim salvando a foto."}

    def playlist_selecionar(self, nome: str) -> bool:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.playlist_selecionar(nome)
        try:
            import music_player
            return music_player.selecionar_playlist(nome)
        except Exception as e:  # noqa: BLE001
            _log(f"playlist_selecionar: {e}")
            return False

    def playlist_renomear(self, nome_atual: str, nome_novo: str) -> dict:
        if self._demo_ativo():
            import modo_demo
            return ({"ok": True} if modo_demo.playlist_renomear(nome_atual, nome_novo)
                    else {"erro": "Não dá pra renomear assim."})
        try:
            import music_player
            if music_player.renomear_playlist(nome_atual, nome_novo):
                return {"ok": True}
            return {"erro": "Não dá pra renomear assim."}
        except Exception as e:  # noqa: BLE001
            _log(f"playlist_renomear: {e}")
            return {"erro": "Deu ruim renomeando."}

    def playlist_apagar(self, nome: str) -> bool:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.playlist_apagar(nome)
        try:
            import music_player
            return music_player.apagar_playlist(nome)
        except Exception as e:  # noqa: BLE001
            _log(f"playlist_apagar: {e}")
            return False

    def playlist_favoritar(self, video_id: str, favorito: bool) -> bool:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.playlist_favoritar(video_id, bool(favorito))
        try:
            import music_player
            return music_player.favoritar(video_id, bool(favorito))
        except Exception as e:  # noqa: BLE001
            _log(f"playlist_favoritar: {e}")
            return False

    def playlist_buscar_preview(self, query: str) -> dict:
        """Busca no YouTube e devolve prévias SEM adicionar nada."""
        query = (query or "").strip()
        if not query:
            return {"erro": "Diz a música ou cola o link."}
        try:
            import music_player
            previas = music_player.buscar_preview(query)
            if not previas:
                return {"erro": "Não achei nada com esse nome."}
            return {"resultados": previas}
        except Exception as e:  # noqa: BLE001
            _log(f"playlist_buscar_preview: {e}")
            return {"erro": "Deu ruim buscando no YouTube."}

    def playlist_adicionar(self, video_id: str, titulo: str, thumb: str) -> bool:
        """Adiciona uma prévia escolhida à playlist ativa."""
        if self._demo_ativo():
            import modo_demo
            return modo_demo.playlist_adicionar({
                "video_id": video_id, "titulo": titulo or "", "thumb": thumb or ""})
        try:
            import music_player
            return music_player.adicionar({
                "video_id": video_id,
                "titulo": titulo or "",
                "thumb": thumb or "",
            })
        except Exception as e:  # noqa: BLE001
            _log(f"playlist_adicionar: {e}")
            return False

    def playlist_buscar_e_add(self, query: str) -> dict:
        """Compat: busca e acrescenta a primeira à playlist. Devolve a música."""
        query = (query or "").strip()
        if not query:
            return {"erro": "Diz a música ou cola o link."}
        try:
            import music_player
            if self._demo_ativo():
                import modo_demo
                previas = music_player.buscar_preview(query, limite=1)
                achado = previas[0] if previas else None
                if achado:
                    modo_demo.playlist_adicionar(achado)
            else:
                achado = music_player.adicionar_por_busca(query)
            if not achado:
                return {"erro": "Não achei nada com esse nome."}
            return achado
        except Exception as e:  # noqa: BLE001
            _log(f"playlist_buscar_e_add: {e}")
            return {"erro": "Deu ruim buscando no YouTube."}

    def playlist_remover(self, video_id: str) -> bool:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.playlist_remover(video_id)
        try:
            import music_player
            return music_player.remover(video_id)
        except Exception as e:  # noqa: BLE001
            _log(f"playlist_remover: {e}")
            return False

    def music_offline_estado(self, forcar: bool = False) -> dict:
        if self._demo_ativo():
            import modo_demo
            return {"faixas": {}, "online": True, "pasta": "", "settings": {k:v for k,v in modo_demo.player_estado().items() if k in ("volume","loop","shuffle")}}
        import music_offline
        return music_offline.estado(bool(forcar))

    def music_offline_baixar(self, items: list) -> dict:
        if self._demo_ativo():
            return {'erro': 'Downloads não estão disponíveis no modo Demo.'}
        import music_offline
        return music_offline.baixar(items)

    def music_offline_cancelar(self, video_id: str) -> bool:
        import music_offline
        return music_offline.cancelar(video_id)

    def music_offline_remover(self, video_id: str) -> bool:
        if self._demo_ativo():
            return False
        import music_offline
        return music_offline.remover(video_id)

    def music_letras_buscar(self, query: str) -> dict:
        import music_letras
        return music_letras.buscar(query)

    def music_organizar(self, nome: str, ids: list) -> bool:
        if self._demo_ativo():
            return False
        import music_player
        return music_player.organizar(nome, ids)

    def music_remover(self, nome: str, video_id: str) -> bool:
        if self._demo_ativo():
            import modo_demo
            anterior = modo_demo.playlist_geral().get('ativa', 'default')
            try:
                return modo_demo.playlist_selecionar(nome) and modo_demo.playlist_remover(video_id)
            finally:
                modo_demo.playlist_selecionar(anterior)
        import music_player
        return music_player.remover(video_id, nome)

    def music_copiar(self, nome: str, item: dict) -> bool:
        if self._demo_ativo():
            import modo_demo
            anterior = modo_demo.playlist_geral().get('ativa', 'default')
            try:
                return modo_demo.playlist_selecionar(nome) and modo_demo.playlist_adicionar(item)
            finally:
                modo_demo.playlist_selecionar(anterior)
        import music_player
        return music_player.adicionar(item, nome)

    def player_estado(self) -> dict:
        """Estado salvo do player: volume, loop, shuffle, música e posição."""
        if self._demo_ativo():
            import modo_demo
            return modo_demo.player_estado()
        try:
            import music_player
            return music_player.estado()
        except Exception as e:  # noqa: BLE001
            _log(f"player_estado: {e}")
            return {}

    def player_salvar_estado(self, dados: dict) -> bool:
        """Persiste o estado do player (volume, loop, shuffle, posição...)."""
        if self._demo_ativo():
            import modo_demo
            return modo_demo.player_salvar(dados or {})
        try:
            import music_player
            campos = {k: v for k, v in (dados or {}).items()}
            return music_player.salvar_estado(**campos)
        except Exception as e:  # noqa: BLE001
            _log(f"player_salvar_estado: {e}")
            return False

    # ── Conversas ─────────────────────────────────────────────────
    #
    # conversas.renomear() e conversas.vazia() já existiam no projeto e a
    # interface antiga NUNCA chamava nenhuma das duas. É por isso que a
    # sidebar enchia de "Conversa nova": ninguém limpava as vazias.

    def listar_conversas(self) -> list:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.listar_conversas()
        try:
            import conversas
            import modelo
            # Uma resposta defeituosa do modelo de títulos podia salvar o ID
            # do próprio modelo. Recupera só esse caso inequívoco.
            for item in conversas.listar():
                if not _titulo_e_id_modelo(item.get("titulo", "")):
                    continue
                primeira = next((m.get("texto", "") for m in conversas.abrir(item["id"])
                                 if m.get("papel") == "user"), "")
                if primeira:
                    recuperado = conversas.titulo_de(primeira)
                    if recuperado != item["titulo"]:
                        conversas.renomear_se_titulo(
                            item["id"], item["titulo"], recuperado)
            return [
                {"id": c.get("id"), "titulo": c.get("titulo") or "Conversa nova",
                 "mexida": c.get("mexida", 0),
                 "pendente": c.get("pendente", False) and not modelo.web_turno_ativo(c.get("id"))}
                for c in conversas.listar()
                if c.get("quantas", 0) > 0  # só mostra conversas com conteúdo
            ]
        except Exception as e:  # noqa: BLE001
            _log(f"listar_conversas: {e}")
            return []

    def abrir_conversa(self, cid: str) -> list:
        import modelo
        if modelo.web_turno_ativo() and not modelo.web_turno_ativo(cid):
            self._j._push("toast", {"texto": "Espere a Emily terminar esta tarefa antes de trocar de conversa.", "tipo": "erro"})
            return {"bloqueada": True}
        if self._demo_ativo():
            import modo_demo
            import modelo
            self._j._cid = cid
            mensagens = modo_demo.abrir_conversa(cid)
            modelo.definir_historico(modo_demo.historico_modelo(cid))
            return [{"papel": m.get("papel", "user"), "texto": m.get("texto", ""),
                     "fontes": m.get("fontes", []), "indice": i}
                    for i, m in enumerate(mensagens)]
        try:
            import conversas
            self._j._cid = cid
            saida = []
            for i, m in enumerate(conversas.abrir(cid)):
                texto = (m.get("texto") or m.get("content") or "").strip()
                if texto:
                    saida.append({"papel": m.get("papel") or m.get("role") or "user",
                                  "texto": texto, "fontes": m.get("fontes") or [],
                                  "indice": i, "anexos": [self._descrever(a) for a in m.get("anexos", []) if Path(a).is_file()]})
            # Reabrir uma conversa devolve o CONTEXTO pra Emily, não só o texto na
            # tela. Sem isto ela vê as mensagens antigas mas responde sem saber do
            # que o Vitor está falando — era o bug de "abri de novo e ela esqueceu
            # tudo". A interface de desktop (interface.py) já fazia isto; a web não.
            try:
                import modelo
                modelo.definir_historico(conversas.para_o_modelo(cid))
            except Exception as e:  # noqa: BLE001
                _log(f"abrir_conversa: não restaurei o contexto: {e}")
            return saida
        except Exception as e:  # noqa: BLE001
            _log(f"abrir_conversa: {e}")
            return []

    def turno_pendente(self, cid: str) -> dict:
        """Resumo persistido; não executa nem repete a tarefa sozinho."""
        if self._demo_ativo():
            return {}
        try:
            import modelo
            if modelo.web_turno_ativo(cid):
                return {}
            import conversas
            return conversas.turno_pendente_visivel(cid) or {}
        except Exception as e:  # noqa: BLE001
            _log(f"turno_pendente: {e}")
            return {}

    def dispensar_turno_pendente(self, cid: str) -> bool:
        try:
            import conversas
            return conversas.dispensar_turno_pendente(cid)
        except Exception as e:  # noqa: BLE001
            _log(f"dispensar_turno_pendente: {e}")
            return False

    def nova_conversa(self) -> Optional[str]:
        import modelo
        if modelo.web_turno_ativo():
            self._j._push("toast", {"texto": "Espere a Emily terminar esta tarefa antes de abrir outra conversa.", "tipo": "erro"})
            return {"bloqueada": True}
        if self._demo_ativo():
            import modelo
            self._j._cid = None
            modelo.definir_historico([])
            return None
        try:
            import conversas
            # Antes de abrir outra, joga fora a anterior se ela ficou vazia.
            # Sem isso a lista acumula "Conversa nova" pra sempre.
            anterior = self._j._cid
            if anterior and conversas.vazia(anterior):
                conversas.apagar(anterior)
            # NÃO cria a conversa agora: ela só ganha um id quando a primeira
            # mensagem chegar (em _registrar_na_conversa). Assim o botão "Nova
            # conversa" não deixa rastro na sidebar de conversa vazia.
            self._j._cid = None
            # Chat novo começa do zero: o contexto da conversa anterior não pode
            # vazar pra cá, senão a Emily responde a primeira mensagem do chat
            # novo carregando o assunto do chat velho.
            try:
                import modelo
                modelo.definir_historico([])
            except Exception as e:  # noqa: BLE001
                _log(f"nova_conversa: não limpei o contexto: {e}")
            return None
        except Exception as e:  # noqa: BLE001
            _log(f"nova_conversa: {e}")
            return None

    def renomear_conversa(self, cid: str, titulo: str) -> bool:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.renomear_conversa(cid, titulo)
        try:
            import conversas
            return bool(conversas.renomear(cid, titulo))
        except Exception as e:  # noqa: BLE001
            _log(f"renomear_conversa: {e}")
            return False

    def apagar_conversa(self, cid: str) -> bool:
        import modelo
        if modelo.web_turno_ativo(cid):
            self._j._push("toast", {"texto": "Espere a Emily terminar esta tarefa antes de apagar a conversa.", "tipo": "erro"})
            return False
        if self._demo_ativo():
            import modo_demo
            if self._j._cid == cid:
                self._j._cid = None
            return modo_demo.apagar_conversa(cid)
        try:
            import conversas
            if self._j._cid == cid:
                self._j._cid = None
            return bool(conversas.apagar(cid))
        except Exception as e:  # noqa: BLE001
            _log(f"apagar_conversa: {e}")
            return False

    # ── Mandar coisa pra ela ──────────────────────────────────────

    def enviar(self, texto: str, remoto: bool = False, origem: str = "digitado",
               requisicao_id: str = "") -> Optional[str]:
        # Dois cliques/envios rápidos não podem reservar turnos diferentes
        # entre a gravação da mensagem e a criação da thread de resposta.
        with self._enviar_lock:
            return self._enviar_impl(texto, remoto, origem, requisicao_id)

    def _enviar_impl(self, texto: str, remoto: bool = False,
                    origem: str = "digitado", requisicao_id: str = "") -> Optional[str]:
        """
        Manda texto pra Emily responder. Cria a conversa se ainda não existe
        (quando o usuário clica 'Nova conversa' sem que o backend tenha criado
        uma — o cid vem de _registrar_na_conversa). Devolve o cid da conversa
        pra o JS saber qual é, ou None se não conseguiu.

        [remoto]: botão de celular aceso — o comando é executado pela Emily do
        CELULAR (ferramentas de lá) e a resposta volta pra este chat.
        """
        texto = (texto or "").strip()
        if not texto:
            return None
        if requisicao_id:
            import conversas
            existente = conversas.localizar_requisicao(requisicao_id)
            if existente:
                return existente
        em_demo = self._demo_ativo()
        novo_chat = not self._j._cid
        if em_demo:
            remoto = False
        if not remoto and not em_demo:
            import modelo
            if modelo.web_turno_ativo() and not modelo.web_turno_ativo(self._j._cid or "__novo__"):
                self._j._push("toast", {"texto": "A Emily ainda trabalha em outra conversa. Volte a ela ou aguarde terminar.", "tipo": "erro"})
                return None
        if remoto:
            if requisicao_id:
                self._j._registrar_na_conversa("user", texto, requisicao_id=requisicao_id)
            else:
                self._j._registrar_na_conversa("user", texto)
            cid = self._j._cid
            # Em thread: a resposta do celular pode demorar MINUTOS, e o JS
            # tem teto de 8s por chamada. Ela chega pelo _push de msg.
            threading.Thread(target=self._rodar_remota, args=(texto,), daemon=True).start()
            # 'ocupada' e NÃO 'aguardando': o aplicarStatus do JS só mantém
            # os pontinhos de "digitando" em pensando/ocupada — mandar
            # aguardando aqui APAGAVA os pontinhos que o JS tinha acabado de
            # acender, e a espera inteira ficava sem feedback visual nenhum.
            self._j._push("status", {"estado": "ocupada", "texto": "Executando na Emily do celular"})
            return cid
        if not em_demo and origem == "digitado":
            import estilo_vitor
            estilo_vitor.coletar(texto, "escrita", "web")
        if requisicao_id:
            self._j._registrar_na_conversa("user", texto, requisicao_id=requisicao_id)
        else:
            self._j._registrar_na_conversa("user", texto)
        # O cid foi criado dentro de _registrar_na_conversa; devolve pro JS
        # pra que ele possa atualizar ESTADO.atual.
        cid = self._j._cid
        if not cid:
            return None
        cb = self._j.callback_texto
        if cb:
            if em_demo:
                def _responder_demo():
                    self._demo_turno_iniciar()
                    try:
                        self._j._chamar_cb(cb, texto)
                    finally:
                        self._demo_turno_encerrar()
                threading.Thread(target=_responder_demo, daemon=True).start()
            else:
                estado_turno = modelo.web_turno_receber(cid, texto)
                if estado_turno == "adicionada":
                    self._j._push("toast", {"texto": "Anotado para o próximo passo desta tarefa.", "tipo": "ok"})
                    return cid
                if estado_turno == "outra_conversa":
                    return None

                def _responder_em_serie():
                    pedido = texto
                    try:
                        modelo.web_turno_vincular(cid)
                        while True:
                            self._j._chamar_cb(cb, pedido)
                            pendentes = modelo.web_turno_concluir(cid)
                            if not pendentes:
                                break
                            pedido = "\n".join(pendentes)
                    finally:
                        modelo.web_turno_liberar(cid)

                threading.Thread(target=_responder_em_serie, daemon=True).start()
        # Título de verdade, feito por LLM, em background.
        if not em_demo and novo_chat and cid:
            threading.Thread(target=self._j._titular, args=(cid, texto), daemon=True).start()
        return cid

    def regenerar(self, cid: str, indice: int) -> dict:
        """Rebobina uma resposta salva e a gera novamente no mesmo chat."""
        with self._regenerar_lock:
            if self._regenerando:
                return {"ok": False, "erro": "A regeneração anterior ainda está em andamento."}
            principal = sys.modules.get("main") or sys.modules.get("__main__")
            ocupada = getattr(principal, "emily_ocupada", None)
            if ocupada is not None and ocupada.is_set():
                return {"ok": False, "erro": "Espere a Emily terminar a resposta atual."}
            em_demo = self._demo_ativo()
            try:
                if em_demo:
                    import modo_demo as acervo
                else:
                    import conversas as acervo
                import modelo
                if not isinstance(indice, int) or isinstance(indice, bool):
                    return {"ok": False, "erro": "Mensagem inválida para regenerar."}
                cb = self._j.callback_texto
                if cb is None:
                    return {"ok": False, "erro": "A Emily não está pronta para responder."}
                originais = acervo.abrir_conversa(cid) if em_demo else acervo.abrir(cid)
                resultado = acervo.truncar_para_regenerar(cid, indice)
                if resultado is None:
                    return {"ok": False, "erro": "Não encontrei o pedido original dessa resposta."}
                self._regenerando = True
                self._j._cid = cid
                # O modelo registra o pedido ao começar o turno; removê-lo só
                # do contexto em memória evita enviar a mesma fala duas vezes.
                historico = (acervo.historico_modelo(cid) if em_demo
                             else acervo.para_o_modelo(cid))
                modelo.definir_historico(historico[:-1])
                self._j._falando = False
                self._j._resposta_emily = ""
                self._j._resposta_crua = ""
                self._j._falas_processo = []

                def responder():
                    try:
                        if em_demo:
                            self._demo_turno_iniciar()
                        self._j._chamar_cb(cb, resultado["pedido"])
                    finally:
                        try:
                            if em_demo:
                                self._demo_turno_encerrar()
                            atuais = acervo.abrir_conversa(cid) if em_demo else acervo.abrir(cid)
                            if len(atuais) <= resultado["indice_usuario"] + 1:
                                restaurado = acervo.restaurar_regeneracao_falha(
                                    cid, resultado["indice_usuario"], resultado.get("ramo", 0), originais)
                                if restaurado:
                                    self._j._push("regeneracao_falhou", {
                                        "cid": cid, "mensagens": [
                                            {"papel": m.get("papel"), "texto": m.get("texto"),
                                             "fontes": m.get("fontes") or [], "indice": i}
                                            for i, m in enumerate(originais)]})
                        except Exception as exc:
                            _log(f"restaurar regeneração: {type(exc).__name__}: {exc}")
                        finally:
                            with self._regenerar_lock:
                                self._regenerando = False

                # O JS redesenha a timeline truncada ao receber o retorno.
                # A curta espera impede que um delta da resposta nova seja
                # apagado por esse redesenho.
                timer = threading.Timer(0.25, responder)
                timer.daemon = True
                timer.start()
                mensagens = [{"papel": m.get("papel"), "texto": m.get("texto"),
                              "fontes": m.get("fontes") or [], "indice": i}
                             for i, m in enumerate(resultado["mensagens"])]
                return {"ok": True, "mensagens": mensagens}
            except Exception as exc:
                self._regenerando = False
                _log(f"regenerar: {type(exc).__name__}: {exc}")
                return {"ok": False, "erro": "Não consegui preparar a regeneração."}

    def voz_texto_estado(self) -> bool:
        import preferencias
        return bool(preferencias.obter("voz_texto_digitado", False))

    def voz_texto_definir(self, ativo: bool) -> bool:
        import preferencias
        preferencias.definir(voz_texto_digitado=bool(ativo))
        return self.voz_texto_estado()

    def enviar_arquivo(self, caminho: str) -> bool:
        """Compatibilidade com chamadas antigas que enviavam um arquivo só."""
        return bool(self.enviar_arquivos([caminho]))

    def enviar_arquivos(self, caminhos: list, texto: str = "") -> Optional[str]:
        """Entrega todos os anexos e a pergunta juntos ao fluxo normal do chat."""
        with self._enviar_lock:
            return self._enviar_arquivos_impl(caminhos, texto)

    def _enviar_arquivos_impl(self, caminhos: list, texto: str = "") -> Optional[str]:
        em_demo = self._demo_ativo()
        if not em_demo:
            import modelo
            if modelo.web_turno_ativo():
                self._j._push("toast", {"texto": "Aguarde a resposta atual antes de enviar novos anexos."})
                return None
        raiz_demo = None
        if em_demo:
            try:
                import modo_demo
                raiz_demo = modo_demo.workspace()
                raiz_demo = raiz_demo.resolve() if raiz_demo else None
            except Exception:
                raiz_demo = None
        caminhos_validos = []
        vistos = set()
        for caminho in caminhos or []:
            if not caminho:
                continue
            try:
                resolvido = Path(str(caminho)).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            if not resolvido.is_file():
                continue
            chave = os.path.normcase(str(resolvido))
            if chave in vistos:
                continue
            vistos.add(chave)
            try:
                if resolvido.stat().st_size > _ANEXO_MAX_BYTES:
                    _log(f"anexo ignorado: {resolvido.name} passa de {_ANEXO_MAX_MB} MB")
                    continue
            except OSError:
                continue
            if em_demo and (raiz_demo is None or not resolvido.is_relative_to(raiz_demo)):
                _log(f"modo demo bloqueou anexo fora do workspace: {resolvido}")
                continue
            caminhos_validos.append(str(resolvido))
            if len(caminhos_validos) >= _ANEXO_MAX_QTDE:
                break
        cb = self._j.callback_arquivos
        if not cb or not caminhos_validos:
            return None

        texto = (texto or "").strip()
        nomes = ", ".join(os.path.basename(caminho) for caminho in caminhos_validos)
        registro = texto or "Analise os anexos enviados."
        novo_chat = not self._j._cid
        primeira = f"{registro}\n[Anexos: {nomes}]"
        self._j._registrar_na_conversa("user", registro, anexos=caminhos_validos)
        cid = self._j._cid
        if em_demo:
            def _responder_demo_arquivos():
                self._demo_turno_iniciar()
                try:
                    self._j._chamar_cb(cb, caminhos_validos, texto)
                finally:
                    self._demo_turno_encerrar()
            threading.Thread(target=_responder_demo_arquivos, daemon=True).start()
        else:
            modelo.web_turno_receber(cid, registro)
            def _responder_arquivos():
                try:
                    modelo.web_turno_vincular(cid)
                    self._j._chamar_cb(cb, caminhos_validos, texto)
                    while True:
                        pendentes = modelo.web_turno_concluir(cid)
                        if not pendentes:
                            break
                        self._j._chamar_cb(self._j.callback_texto, "\n".join(pendentes))
                finally:
                    modelo.web_turno_liberar(cid)
            threading.Thread(target=_responder_arquivos, daemon=True).start()
            if novo_chat and cid:
                threading.Thread(target=self._j._titular, args=(cid, primeira), daemon=True).start()
        return cid

    def _rodar_remota(self, texto: str) -> None:
        """Manda o comando pro celular executar e mostra a resposta neste chat."""
        try:
            import servidor as _srv
            ok, resposta = _srv.enviar_comando_remoto_ao_celular(texto)
            if not ok:
                resposta = resposta or "O celular não respondeu."
            self._j._registrar_na_conversa("emily", resposta)
            # Fecha o painel de progresso (o celular reporta cada passo via
            # /remota/progresso) e os pontinhos de "digitando" ANTES da
            # resposta entrar — a msg por si só não desliga o indicador.
            try:
                self._j.progresso_evento("fim", {})
            except Exception:  # noqa: BLE001
                pass
            self._j._push("status", {"estado": "aguardando", "texto": ""})
            self._j._push("msg", {"autor": "emily", "texto": resposta})
        except Exception as e:  # noqa: BLE001
            _log(f"remota: {e}")
            try:
                self._j.progresso_evento("fim", {})
                self._j._push("status", {"estado": "aguardando", "texto": ""})
                self._j._push("msg", {"autor": "emily", "texto": "Deu ruim falando com o celular. Tá com o app aberto e conectado?"})
            except Exception:  # noqa: BLE001
                pass

    def music_identify_window(self) -> dict:
        try:
            import webview
            panel = getattr(self, '_music_identify_panel', None)
            if panel is None:
                port = self._j._httpd.server_address[1]
                panel = webview.create_window('Emily — Qual música é essa?',
                    f'http://127.0.0.1:{port}/music-identify.html', js_api=self,
                    width=470, height=580, min_size=(360, 430), on_top=True,
                    background_color='#1c1b19', resizable=True)
                self._music_identify_panel = panel
                def closed():
                    self._music_identify_panel = None
                    self.music_identify_cancel()
                panel.events.closed += closed
            else:
                panel.show()
                panel.restore()
            return {'ok': True}
        except Exception as exc:
            return {'ok': False, 'mensagem': str(exc)}

    def music_identify_youtube(self) -> bool:
        import music_discovery
        import webbrowser
        track = music_discovery.state().get('musica', {})
        url = track.get('youtube', '')
        if url.startswith('https://www.youtube.com/results?search_query='):
            return bool(webbrowser.open(url))
        return False

    def music_identify_play(self, item: dict) -> bool:
        import re
        if not isinstance(item, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', str(item.get('video_id', ''))):
            return False
        self._j._push('player_comando', {'acao': 'descoberta', 'dados': item})
        self._music_identify_preview = True
        return True

    def music_identify_player(self) -> dict:
        if not getattr(self, '_music_identify_preview', False):
            return {}
        try:
            return self._j._avaliar_js("""(() => ({
                titulo: Player.playlist[Player.indice]?.titulo || '',
                tocando: Player.tocando,
                posicao: Number(Player.player?.getCurrentTime?.() || 0),
                duracao: Number(Player.player?.getDuration?.() || 0)
            }))()""") or {}
        except Exception:
            return {}

    def music_identify_control(self, action: str) -> bool:
        if action not in ('alternar', 'parar'):
            return False
        self._j._push('player_comando', {'acao': 'identificacao_control', 'dados': {'acao': action}})
        if action == 'parar':
            self._music_identify_preview = False
        return True

    def music_identify_state(self) -> dict:
        import music_discovery
        return music_discovery.state()

    def music_identify_cancel(self) -> bool:
        import music_discovery
        return music_discovery.cancel()

    def music_identify_start(self, fonte='sistema', segundos=12, audd=False) -> bool:
        import music_discovery
        threading.Thread(target=music_discovery.identify, args=(fonte, segundos, audd), daemon=True).start()
        return True

    def ptt(self) -> bool:
        """Grava pelo push-to-talk e manda o que foi transcrito."""
        def _rodar():
            try:
                import voz
                self._j.atualizar_status("ouvindo", "Aguardando o botão…")
                txt = voz.ouvir_ptt(
                    callback_gravando=lambda: self._j.atualizar_status("gravando", "Gravando…"))
                if txt and txt.strip():
                    if self.voz_xadrez(txt.strip()):
                        self._j.atualizar_status('aguardando')
                        return
                    self._j._push("msg", {"autor": "user", "texto": txt.strip()})
                    import estilo_vitor
                    estilo_vitor.coletar(txt.strip(), "fala", "ptt_web")
                    self.enviar(txt.strip(), origem="ptt")
                else:
                    self._j.atualizar_status("aguardando")
            except Exception as e:  # noqa: BLE001
                _log(f"ptt: {e}")
                self._j.atualizar_status("aguardando")
        threading.Thread(target=_rodar, daemon=True).start()
        return True

    def ptt_tecla_estado(self) -> dict:
        import tecla_ptt
        return tecla_ptt.estado()

    def ptt_tecla_definir(self, tecla: str) -> dict:
        import tecla_ptt
        return tecla_ptt.definir(tecla)

    def ptt_tecla_capturar(self, requisicao: str | None = None) -> dict:
        import voz
        return voz.capturar_atalho_ptt(requisicao)

    def ptt_tecla_cancelar(self, requisicao: str | None = None) -> bool:
        import tecla_ptt
        tecla_ptt.cancelar_captura(requisicao)
        return True

    def capturar_tela(self) -> bool:
        cb = self._j.callback_visao
        if cb:
            threading.Thread(target=self._j._chamar_cb, args=(cb,), daemon=True).start()
            return True
        return False

    # ── Agente visual contínuo ─────────────────────────────────────

    @staticmethod
    def _resposta_agente_ui(ok: bool, mensagem: str = "") -> dict:
        import agente_ui
        return {"ok": bool(ok), "mensagem": mensagem, "estado": agente_ui.estado_agente_ui()}

    def agente_ui_estado(self) -> dict:
        import agente_ui
        return agente_ui.estado_agente_ui()

    def agente_ui_iniciar(self, objetivo: str) -> dict:
        import agente_ui
        objetivo = (objetivo or "").strip()
        if not objetivo:
            return self._resposta_agente_ui(False, "Descreva o que a Emily deve fazer na tela.")
        antes = agente_ui.estado_agente_ui()
        mensagem = agente_ui.iniciar_agente_ui(objetivo)
        depois = agente_ui.estado_agente_ui()
        iniciou = bool(
            depois.get("objetivo") == objetivo
            and depois.get("iniciado_em")
            and depois.get("iniciado_em") != antes.get("iniciado_em")
        )
        return {"ok": iniciou, "mensagem": mensagem, "estado": depois}

    def agente_ui_pausar(self) -> dict:
        import agente_ui
        ok = agente_ui.sessao_agente_ui().pausar()
        mensagem = "Agente pausado." if ok else "O agente não está rodando ou já está pausado."
        return self._resposta_agente_ui(ok, mensagem)

    def agente_ui_retomar(self) -> dict:
        import agente_ui
        ok = agente_ui.sessao_agente_ui().retomar()
        mensagem = "Agente retomado." if ok else "Não há uma tarefa pausada para retomar."
        return self._resposta_agente_ui(ok, mensagem)

    def agente_ui_cancelar(self) -> dict:
        import agente_ui
        ok = agente_ui.sessao_agente_ui().cancelar()
        mensagem = "Cancelamento solicitado." if ok else "O agente não está executando uma tarefa."
        return self._resposta_agente_ui(ok, mensagem)

    def agente_ui_mensagem(self, mensagem: str) -> dict:
        import agente_ui
        mensagem = (mensagem or "").strip()
        ok = bool(mensagem) and agente_ui.enviar_mensagem_ao_vivo(mensagem)
        texto = "Instrução enviada para o próximo passo." if ok else "O agente não está ativo agora."
        return self._resposta_agente_ui(ok, texto)

    def voz_xadrez(self, texto: str) -> bool:
        if not self._xadrez_visivel or self._demo_ativo():
            return False
        import xadrez_emily
        resultado = xadrez_emily.instancia().conversar(texto, voz=True, origem='voz')
        if not resultado.get('ok'):
            self._j._push('toast', {'texto': resultado.get('erro', 'Não consegui receber sua fala na partida.'), 'tipo': 'erro'})
        return True

    def xadrez_acao(self, acao: str, dados: dict = None) -> dict:
        """Ponte local da partida; não entra no laço de tarefas do chat."""
        if acao == 'visibilidade':
            try:
                serial = int((dados or {}).get('serial', -1))
                with self._enviar_lock:
                    if serial > self._xadrez_visibilidade_serial:
                        self._xadrez_visibilidade_serial = serial
                        self._xadrez_visivel = bool((dados or {}).get('ativo')) and not self._demo_ativo()
                return {'ok': True}
            except (ValueError, TypeError):
                return {'ok': False, 'erro': 'Estado da tela inválido.'}
        if self._demo_ativo():
            return {"ok": False, "erro": "Saia do modo Demo para jogar sua partida."}
        if acao == 'sons':
            try:
                import xadrez_sons
                return xadrez_sons.acao((dados or {}).get('operacao', 'ler'), dados)
            except (ValueError, TypeError, OSError) as exc:
                return {'ok': False, 'erro': str(exc)}
        import xadrez_emily
        partida = xadrez_emily.instancia()
        dados = dados or {}
        try:
            if acao == "estado":
                return {"ok": True, "estado": partida.estado()}
            if acao == "contexto":
                return partida.atualizar_contexto(dados.get("posicao"), dados.get("revisao", -1))
            if acao == "salvar":
                return partida.sincronizar(dados.get("posicao"), dados.get("revisao", -1), bool(dados.get("nova")))
            if acao == "dificuldade":
                return partida.dificuldade(dados.get("nivel"))
            if acao == "lance":
                return partida.escolher_lance(dados.get("revisao", -1))
            if acao == "conversar":
                return partida.conversar(dados.get("texto", ""), bool(dados.get("voz")))
            if acao == "comentar":
                return partida.comentar(dados.get("revisao", -1))
            if acao == "abrir":
                self._j._push("xadrez_abrir", {})
                return {"ok": True}
            if acao == "voz":
                with partida.lock:
                    partida.dados["voz"] = bool(dados.get("ativo"))
                    partida._salvar()
                return {"ok": True}
            return {"ok": False, "erro": "Ação de xadrez desconhecida."}
        except (ValueError, TypeError, OSError) as exc:
            _log(f"xadrez: {type(exc).__name__}")
            return {"ok": False, "erro": "Não consegui salvar ou atualizar a partida. Tente novamente."}

    def navegador_interno_acao(self, acao: str, dados: dict = None) -> dict:
        """Ponte da tela dedicada; nunca toca mouse/teclado do sistema."""
        import navegador_interno
        dados = dados or {}
        if acao == "usuario_ativo":
            return navegador_interno.definir_usuario_ativo(bool(dados.get("ativo")))
        if acao == "abrir":
            return navegador_interno.abrir(str(dados.get("url", "")), origem="usuario")
        if acao in {"estado", "ler", "voltar", "avancar", "recarregar"}:
            return navegador_interno.comando(acao, origem="usuario")
        if acao in {"nova_aba", "trocar_aba", "fechar_aba"}:
            if acao == "nova_aba":
                return navegador_interno.comando(acao, origem="usuario")
            return navegador_interno.comando(acao, dados.get("indice", -1), origem="usuario")
        if acao == "dimensionar":
            return navegador_interno.comando(acao, dados.get("largura", 1280), dados.get("altura", 800), origem="usuario")
        if acao == "mover":
            return navegador_interno.comando("mover", dados.get("x", 0), dados.get("y", 0), origem="usuario")
        if acao in {"clicar", "pressionar", "soltar"}:
            botao = str(dados.get("botao", "left"))
            if botao not in {"left", "right", "middle"}:
                botao = "left"
            return navegador_interno.comando(acao, dados.get("x", 0), dados.get("y", 0), botao, origem="usuario")
        if acao == "rolar":
            return navegador_interno.comando("rolar", dados.get("dx", 0), dados.get("dy", 0), origem="usuario")
        if acao in {"tecla", "texto"}:
            valor = str(dados.get("valor", ""))[:500]
            if not valor:
                return {"ok": False, "erro": "Tecla ou texto vazio."}
            return navegador_interno.comando(acao, valor, origem="usuario")
        return {"ok": False, "erro": "Ação desconhecida."}

    def copiar(self, texto: str) -> bool:
        try:
            import pyperclip
            pyperclip.copy(texto or "")
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"copiar: {e}")
            return False

    # ── Arquivos ──────────────────────────────────────────────────

    def cloud_listar(self, parent_id: str = "", filtro: str = "arquivos",
                     busca: str = "") -> dict:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.cloud_listar(parent_id, filtro, busca)
        try:
            from emily_cloud import service
            dados = service.listar(parent_id or None, filtro, busca)
            for item in dados["itens"]:
                if item.get("tem_preview"):
                    from emily_cloud import core
                    preview = core.caminho_preview(item["id"])
                    item["preview_url"] = _data_uri_com_cache(str(preview)) if preview else ""
            return dados
        except Exception as e:  # noqa: BLE001
            _log(f"cloud_listar: {e}")
            return {"ok": False, "erro": str(e), "itens": [], "breadcrumb": []}

    def cloud_detalhes(self, item_id: str) -> dict:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.cloud_detalhes(item_id)
        try:
            from emily_cloud import service, core
            item = service.detalhes(item_id)
            preview = core.caminho_preview(item_id)
            item["preview_url"] = _data_uri_com_cache(str(preview)) if preview else ""
            return {"ok": True, "item": item}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_armazenamento_estado(self) -> dict:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.cloud_status()
        try:
            from emily_cloud import location, service
            estado = service.status()
            estado["configuracao"] = location.origem_configuracao()
            return estado
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_escolher_armazenamento(self) -> dict:
        """Escolhe disco/pasta e devolve o plano; ainda não move nenhum byte."""
        try:
            import webview
            from pathlib import Path
            from emily_cloud import storage

            escolhidos = self._j._janela.create_file_dialog(
                webview.FOLDER_DIALOG, allow_multiple=False)
            if not escolhidos:
                return {"ok": True, "cancelado": True}
            bruto = escolhidos if isinstance(escolhidos, str) else escolhidos[0]
            escolhido = Path(str(bruto)).expanduser()
            # Selecionar a raiz de um HD ou uma pasta com outros arquivos é uma
            # ação natural. Nesse caso criamos um contêiner dedicado dentro dela.
            destino = escolhido
            if escolhido.exists() and any(escolhido.iterdir()):
                destino = escolhido / "Emily Cloud"
            return storage.planejar(str(destino))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_migrar_armazenamento(self, destino: str, permitir_novo: bool = False) -> dict:
        """Move o acervo e reinicia o gateway para o celular trocar junto."""
        gateway_parado = False
        resultado = None
        erro = None
        try:
            import shutil
            import subprocess
            from emily_cloud import storage

            systemctl = shutil.which("systemctl")
            if systemctl and os.name != "nt":
                ativo = subprocess.run(
                    [systemctl, "--user", "is-active", "emily-gateway.service"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=10, check=False).returncode == 0
                if ativo:
                    parada = subprocess.run(
                        [systemctl, "--user", "stop", "emily-gateway.service"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        timeout=20, check=False)
                    gateway_parado = parada.returncode == 0
                    if not gateway_parado:
                        raise RuntimeError(
                            "Não consegui pausar o gateway; a migração foi cancelada para proteger o acervo.")
            resultado = storage.migrar(destino, permitir_novo=bool(permitir_novo))
        except Exception as e:  # noqa: BLE001
            erro = str(e)
        finally:
            gateway_reiniciado = not gateway_parado
            if gateway_parado:
                try:
                    import shutil
                    import subprocess
                    systemctl = shutil.which("systemctl")
                    if systemctl:
                        reinicio = subprocess.run(
                            [systemctl, "--user", "start", "emily-gateway.service"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            timeout=20, check=False)
                        gateway_reiniciado = reinicio.returncode == 0
                        if not gateway_reiniciado:
                            _log("migração concluída, mas o gateway não reiniciou automaticamente")
                except Exception as exc:  # noqa: BLE001
                    _log(f"não consegui reiniciar o gateway após migração: {exc}")
                    gateway_reiniciado = False
        if erro is not None:
            return {"ok": False, "erro": erro, "gateway_parado": gateway_parado,
                    "gateway_reiniciado": gateway_reiniciado}
        resposta = dict(resultado or {"ok": False, "erro": "Migração sem resultado."})
        resposta.update(gateway_parado=gateway_parado,
                        gateway_reiniciado=gateway_reiniciado)
        if resposta.get("ok") and not gateway_reiniciado:
            resposta["aviso"] = (resposta.get("aviso") or "") + (
                " O armazenamento foi movido, mas reinicie o gateway manualmente.")
        return resposta

    def cloud_escolher_importar(self, parent_id: str = "") -> dict:
        try:
            import webview
            from emily_cloud import service
            escolhidos = self._j._janela.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=True,
                file_types=("Todos os arquivos (*.*)",))
            if not escolhidos:
                return {"ok": True, "cancelado": True, "itens": []}
            return service.importar_varios(
                [str(c) for c in escolhidos], parent_id or None, origem="interface")
        except Exception as e:  # noqa: BLE001
            _log(f"cloud_escolher_importar: {e}")
            return {"ok": False, "erro": str(e), "itens": []}

    def cloud_escolher_pasta_importar(self, parent_id: str = "") -> dict:
        try:
            import webview
            from emily_cloud import service
            escolhido = self._j._janela.create_file_dialog(
                webview.FOLDER_DIALOG, allow_multiple=False)
            if not escolhido:
                return {"ok": True, "cancelado": True, "itens": []}
            caminho = escolhido if isinstance(escolhido, str) else escolhido[0]
            return service.importar_varios(
                [str(caminho)], parent_id or None, origem="interface")
        except Exception as e:  # noqa: BLE001
            _log(f"cloud_escolher_pasta_importar: {e}")
            return {"ok": False, "erro": str(e), "itens": []}

    def cloud_importar_caminhos(self, caminhos: list, parent_id: str = "") -> dict:
        """Importa caminhos já resolvidos pela ponte; útil no arrasta-e-solta."""
        try:
            from emily_cloud import service
            return service.importar_varios(
                [str(c) for c in (caminhos or [])], parent_id or None,
                origem="arrastar")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e), "itens": []}

    def cloud_criar_pasta(self, nome: str, parent_id: str = "") -> dict:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.cloud_criar_pasta(nome, parent_id)
        try:
            from emily_cloud import service
            return {"ok": True, "item": service.criar_pasta(nome, parent_id or None)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_renomear(self, item_id: str, nome: str) -> dict:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.cloud_renomear(item_id, nome)
        try:
            from emily_cloud import service
            return {"ok": True, "item": service.renomear(item_id, nome)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_mover_varios(self, item_ids: list, parent_id: str = "") -> dict:
        """Move a seleção da interface em lote, sem depender da Emily."""
        if self._demo_ativo():
            import modo_demo
            return modo_demo.cloud_mover_varios(item_ids, parent_id)
        movidos, erros = [], []
        try:
            from emily_cloud import service
            destino = parent_id or None
            for item_id in dict.fromkeys(str(i) for i in (item_ids or []) if i):
                try:
                    movidos.append(service.mover(item_id, destino))
                except Exception as exc:  # lote continua se um item falhar
                    erros.append({"id": item_id, "erro": str(exc)})
            return {"ok": bool(movidos) and not erros, "parcial": bool(movidos) and bool(erros),
                    "itens": movidos, "erros": erros}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e), "itens": [], "erros": []}

    def cloud_favoritar(self, item_id: str, valor: bool) -> dict:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.cloud_favoritar(item_id, valor)
        try:
            from emily_cloud import service
            return {"ok": True, "item": service.favoritar(item_id, bool(valor))}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_lixeira(self, item_id: str) -> dict:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.cloud_lixeira(item_id)
        try:
            from emily_cloud import service
            return {"ok": True, "item": service.lixeira(item_id)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_restaurar(self, item_id: str) -> dict:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.cloud_restaurar(item_id)
        try:
            from emily_cloud import service
            return {"ok": True, "item": service.restaurar(item_id)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_excluir(self, item_id: str) -> dict:
        if self._demo_ativo():
            import modo_demo
            return {"ok": modo_demo.cloud_excluir(item_id)}
        try:
            from emily_cloud import service
            return {"ok": bool(service.excluir(item_id))}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_exportar(self, item_id: str) -> dict:
        try:
            import webview
            from emily_cloud import core
            item = core.detalhes(item_id)
            if item["tipo"] == "arquivo":
                escolhido = self._j._janela.create_file_dialog(
                    webview.SAVE_DIALOG, save_filename=item["nome"])
                if not escolhido:
                    return {"ok": True, "cancelado": True}
                destino = escolhido if isinstance(escolhido, str) else escolhido[0]
                resultado = core.exportar(item_id, str(os.path.dirname(destino)),
                                          nome=os.path.basename(destino))
            else:
                escolhido = self._j._janela.create_file_dialog(
                    webview.FOLDER_DIALOG, allow_multiple=False)
                if not escolhido:
                    return {"ok": True, "cancelado": True}
                destino = escolhido if isinstance(escolhido, str) else escolhido[0]
                resultado = core.exportar(item_id, destino)
            return resultado
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_abrir(self, item_id: str) -> dict:
        try:
            from emily_cloud import core
            caminho = core.caminho_conteudo(item_id)
            if os.name == "nt":
                os.startfile(str(caminho))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                __import__("subprocess").Popen(["open", str(caminho)])
            else:
                __import__("subprocess").Popen(["xdg-open", str(caminho)])
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_visualizar(self, item_id: str) -> dict:
        """Metadados e URL same-origin para o viewer interno da WebView."""
        if self._demo_ativo():
            import modo_demo
            detalhe = modo_demo.cloud_detalhes(item_id)
            if not detalhe.get("ok"):
                return detalhe
            if detalhe["item"].get("tipo") != "arquivo":
                return {"ok": False, "erro": "Pastas não possuem visualização de arquivo."}
            return {"ok": True, "item": detalhe["item"], "url": "", "demo": True}
        try:
            from emily_cloud import service
            item = service.detalhes(item_id)
            if item["tipo"] != "arquivo":
                return {"ok": False, "erro": "Pastas não possuem visualização de arquivo."}
            return {"ok": True, "item": item,
                    "url": f"/__emily_cloud_content/{item_id}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_ler_texto(self, item_id: str, limite: int = 100000) -> dict:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.cloud_ler_texto(item_id, limite)
        try:
            from emily_cloud import service
            return {"ok": True, "texto": service.ler_texto(item_id, limite)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_compactado_listar(self, item_id: str) -> dict:
        try:
            from emily_cloud import archives
            return archives.listar(item_id)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e), "entradas": []}

    def cloud_compactado_extrair(self, item_id: str, parent_id: str = "",
                                 entradas: Optional[list] = None) -> dict:
        try:
            from emily_cloud import archives
            return archives.extrair(item_id, parent_id or None, entradas)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_anexar(self, item_id: str) -> Optional[dict]:
        if self._demo_ativo():
            import modo_demo
            return modo_demo.cloud_anexar(item_id)
        try:
            from emily_cloud import core
            item = core.detalhes(item_id)
            if item["tipo"] != "arquivo":
                return None
            return self._descrever(str(core.caminho_conteudo(item_id))) | {
                "nome": item["nome"], "cloud_item_id": item_id,
            }
        except Exception as e:  # noqa: BLE001
            _log(f"cloud_anexar: {e}")
            return None

    def cloud_sincronizar(self, item_id: str) -> dict:
        try:
            from emily_cloud import core
            return core.sincronizar(item_id)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def cloud_compartilhar(self, item_id: str, horas: int = 24) -> dict:
        try:
            from emily_cloud import core
            return core.compartilhar(item_id, horas)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)}

    def escolher_arquivos(self) -> list:
        """Abre o diálogo nativo e devolve anexos já descritos para o composer."""
        try:
            import webview
            j = self._j._janela
            escolhidos = j.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=True,
                file_types=("Imagens (*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp)",
                            "Todos os arquivos (*.*)"))
            if isinstance(escolhidos, (str, os.PathLike)):
                escolhidos = [escolhidos]
            descritos = []
            for caminho in (escolhidos or [])[:_ANEXO_MAX_QTDE]:
                descrito = self._descrever(caminho)
                if descrito:
                    descritos.append(descrito)
                    continue
                try:
                    tamanho = os.path.getsize(caminho)
                except OSError:
                    tamanho = 0
                if tamanho > _ANEXO_MAX_BYTES:
                    descritos.append({
                        "nome": os.path.basename(caminho),
                        "tamanho": tamanho,
                        "erro": "arquivo_grande",
                    })
            return descritos
        except Exception as e:  # noqa: BLE001
            _log(f"escolher_arquivos: {e}")
            return []

    def salvar_colado(self, b64: str, nome: str = "", mime: str = "") -> Optional[dict]:
        """Salva bytes vindos do clipboard/drop, preservando nome e extensão.

        O nome histórico do método foi mantido porque versões antigas do JS já
        o chamavam para screenshots. Agora ele também recebe documentos e outros
        arquivos que a WebView expõe apenas como ``File``, sem caminho local.
        """
        try:
            import tempfile
            if not isinstance(b64, str) or not b64:
                return None
            # Rejeita antes de decodificar para não duplicar na memória um payload
            # base64 obviamente maior que o teto (4/3 do tamanho binário).
            if len(b64) > ((_ANEXO_MAX_BYTES + 2) // 3) * 4 + 16:
                _log(f"arquivo colado ignorado: passa de {_ANEXO_MAX_MB} MB")
                return None
            dados = base64.b64decode(b64, validate=True)
            if not dados or len(dados) > _ANEXO_MAX_BYTES:
                return None

            nome_original = os.path.basename(str(nome or "").replace("\\", "/"))
            nome_seguro = re.sub(r"[^\w.()\[\] -]+", "_", nome_original, flags=re.UNICODE).strip(" ._")
            if not nome_seguro:
                # Compatibilidade com o JS antigo, que mandava somente o base64
                # de screenshots sem nome nem MIME e sempre esperava PNG.
                extensao = mimetypes.guess_extension((mime or "").split(";", 1)[0].strip()) or (
                    ".png" if not mime else ".bin")
                nome_seguro = f"colado{extensao}"
            elif not os.path.splitext(nome_seguro)[1]:
                nome_seguro += mimetypes.guess_extension((mime or "").split(";", 1)[0].strip()) or ""

            pasta = os.path.join(tempfile.gettempdir(), "emily_anexos")
            os.makedirs(pasta, exist_ok=True)
            caminho = os.path.join(pasta, f"{time.time_ns()}_{nome_seguro}")
            with open(caminho, "wb") as f:
                f.write(dados)
            descrito = self._descrever(caminho, nome_original or nome_seguro)
            if descrito and mime:
                descrito["mime"] = str(mime).split(";", 1)[0].strip()
            return descrito
        except Exception as e:  # noqa: BLE001
            _log(f"salvar_colado: {e}")
            return None

    def colar_imagem_nativa(self) -> dict:
        """Lê uma imagem direto do clipboard do SO quando a WebView não a expõe.

        No GTK/WebKit2 (especialmente Plasma/KDE no Wayland), o evento ``paste``
        pode anunciar ``image/png`` em ``clipboardData.types`` e ainda assim
        devolver ``null`` em ``DataTransferItem.getAsFile()``. Nessa situação o
        JavaScript não tem bytes para mandar pela ponte. ``wl-paste`` conversa
        com o compositor diretamente e contorna essa limitação da WebView.

        No Windows/WebView2 ocorre uma variação parecida com imagens copiadas de
        aplicativos como WhatsApp: o bitmap existe em CF_DIB no clipboard nativo,
        mas o evento web traz só ``text/html``. Pillow/ImageGrab lê esse bitmap sem
        depender do formato que o Chromium decidiu expor ao JavaScript.

        O retorno é estruturado para o JS distinguir clipboard sem imagem,
        ferramenta ausente e payload acima do limite sem afetar texto colado.
        """
        if sys.platform.startswith("win"):
            try:
                import io
                from PIL import Image, ImageGrab

                conteudo = ImageGrab.grabclipboard()
                if not isinstance(conteudo, Image.Image):
                    return {"ok": False, "erro": "sem_imagem"}

                buffer = io.BytesIO()
                conteudo.save(buffer, format="PNG")
                dados = buffer.getvalue()
                if not dados:
                    return {"ok": False, "erro": "sem_imagem"}
                if len(dados) > _ANEXO_MAX_BYTES:
                    return {"ok": False, "erro": "arquivo_grande"}

                anexo = self.salvar_colado(
                    base64.b64encode(dados).decode("ascii"),
                    "imagem-colada.png",
                    "image/png",
                )
                if not anexo:
                    return {"ok": False, "erro": "falha"}
                return {"ok": True, "anexo": anexo}
            except Exception as e:  # noqa: BLE001
                _log(f"colar_imagem_nativa (Windows): {e}")
                return {"ok": False, "erro": "falha"}

        if not sys.platform.startswith("linux"):
            return {"ok": False, "erro": "indisponivel"}

        try:
            import shutil

            wl_paste = shutil.which("wl-paste")
            if not wl_paste or not os.environ.get("WAYLAND_DISPLAY"):
                return {"ok": False, "erro": "indisponivel"}

            tipos_resultado = subprocess.run(
                [wl_paste, "--list-types"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
            )
            if tipos_resultado.returncode != 0:
                return {"ok": False, "erro": "sem_imagem"}

            tipos = tipos_resultado.stdout.decode("utf-8", errors="replace").splitlines()
            imagens = [tipo.strip() for tipo in tipos if tipo.strip().lower().startswith("image/")]
            if not imagens:
                return {"ok": False, "erro": "sem_imagem"}

            # PNG preserva transparência e é o formato mais previsível para
            # screenshots. Se não estiver disponível, pede o primeiro image/*
            # anunciado pelo dono atual do clipboard.
            mime = next((tipo for tipo in imagens if tipo.lower() == "image/png"), imagens[0])
            processo = subprocess.Popen(
                [wl_paste, "--no-newline", "--type", mime],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            try:
                assert processo.stdout is not None
                dados = processo.stdout.read(_ANEXO_MAX_BYTES + 1)
                if len(dados) > _ANEXO_MAX_BYTES:
                    processo.kill()
                    processo.wait(timeout=2)
                    return {"ok": False, "erro": "arquivo_grande"}
                retorno = processo.wait(timeout=5)
            except Exception:
                processo.kill()
                processo.wait(timeout=2)
                raise

            if retorno != 0 or not dados:
                return {"ok": False, "erro": "sem_imagem"}

            extensao = mimetypes.guess_extension(mime.split(";", 1)[0].strip()) or ".png"
            anexo = self.salvar_colado(
                base64.b64encode(dados).decode("ascii"),
                f"imagem-colada{extensao}",
                mime,
            )
            if not anexo:
                return {"ok": False, "erro": "falha"}
            return {"ok": True, "anexo": anexo}
        except subprocess.TimeoutExpired:
            _log("colar_imagem_nativa: wl-paste excedeu o tempo limite")
            return {"ok": False, "erro": "falha"}
        except Exception as e:  # noqa: BLE001
            _log(f"colar_imagem_nativa: {e}")
            return {"ok": False, "erro": "falha"}

    def resolver_arrastados(self, caminhos_ou_nomes: list) -> list:
        """
        Resolve caminhos/URIs fornecidos pelo sistema. A busca antiga por nome
        continua como compatibilidade, mas clipboard/drop novos enviam os bytes
        diretamente e não dependem mais desta heurística.
        """
        candidatos = [
            os.path.join(os.path.expanduser("~"), p)
            for p in ("Downloads", "Desktop", "Pictures", "Documents",
                      "Área de Trabalho", "Imagens", "Documentos")
        ]
        saida = []
        vistos = set()
        for valor in (caminhos_ou_nomes or [])[:_ANEXO_MAX_QTDE]:
            bruto = str(valor or "").strip().strip('"')
            if not bruto or bruto.lower() in {"copy", "cut"} or bruto.startswith("#"):
                continue
            candidatos_valor = []
            if bruto.lower().startswith("file:"):
                partes = urlsplit(bruto)
                caminho_uri = unquote(partes.path or "")
                if partes.netloc:
                    caminho_uri = f"//{partes.netloc}{caminho_uri}"
                if os.name == "nt" and re.match(r"^/[A-Za-z]:/", caminho_uri):
                    caminho_uri = caminho_uri[1:]
                candidatos_valor.append(caminho_uri)
            else:
                candidatos_valor.append(os.path.expanduser(bruto))

            achado = None
            for candidato in candidatos_valor:
                if os.path.isfile(candidato):
                    achado = candidato
                    break
            if achado is None and not any(sep in bruto for sep in ("/", "\\")):
                for pasta in candidatos:
                    p = os.path.join(pasta, bruto)
                    if os.path.isfile(p):
                        achado = p
                        break
            if achado is None:
                continue
            chave = os.path.normcase(os.path.abspath(achado))
            if chave in vistos:
                continue
            vistos.add(chave)
            descrito = self._descrever(achado)
            if descrito:
                saida.append(descrito)
        return saida

    def salvar_imagem(self, caminho: str) -> Optional[str]:
        try:
            import shutil
            import webview
            j = self._j._janela
            dest = j.create_file_dialog(
                webview.SAVE_DIALOG, save_filename=os.path.basename(caminho))
            if not dest:
                return None
            dest = dest if isinstance(dest, str) else dest[0]
            shutil.copy2(caminho, dest)
            return os.path.basename(dest)
        except Exception as e:  # noqa: BLE001
            _log(f"salvar_imagem: {e}")
            return None

    @staticmethod
    def _descrever(caminho: str, nome_exibicao: str = "") -> Optional[dict]:
        try:
            caminho = str(Path(caminho).expanduser().resolve())
            if not os.path.isfile(caminho):
                return None
            tamanho = os.path.getsize(caminho)
            if tamanho > _ANEXO_MAX_BYTES:
                _log(f"anexo ignorado: {os.path.basename(caminho)} passa de {_ANEXO_MAX_MB} MB")
                return None
            mime = mimetypes.guess_type(caminho)[0] or "application/octet-stream"
            return {
                "caminho": caminho,
                "nome": nome_exibicao or os.path.basename(caminho),
                "mime": mime,
                "tamanho": tamanho,
                "previa": _data_uri(caminho, 6.0) if mime.startswith("image/") else "",
            }
        except (OSError, RuntimeError) as e:
            _log(f"não consegui preparar anexo {caminho}: {e}")
            return None

    # ── Configurações ─────────────────────────────────────────────

    def listar_apps(self) -> list:
        """
        Os apps de acesso rápido.

        Não extrai o ícone do executável de propósito. Ícone de app vem em
        tamanho, forma e paleta que a gente não controla, e três deles lado a
        lado num painel escuro brigam entre si — é o mesmo problema do emoji
        colorido nas sugestões. Ladrilho com a letra na cor da marca é
        consistente e legível a 34px.
        """
        if self._demo_ativo():
            return [
                {"nome": "Navegador", "cor": "#c96442", "letra": "N",
                 "tinta": "#fff", "existe": True, "demo": True},
                {"nome": "Editor", "cor": "#5d7798", "letra": "E",
                 "tinta": "#fff", "existe": True, "demo": True},
                {"nome": "Música", "cor": "#71896d", "letra": "M",
                 "tinta": "#fff", "existe": True, "demo": True},
            ]
        import glob
        saida = []
        for padrao, nome, cor, letra in APPS:
            try:
                existe = bool(sorted(glob.glob(padrao)) if "*" in padrao
                              else os.path.exists(padrao))
                saida.append({"nome": nome, "cor": cor, "letra": letra,
                              "tinta": _cor_legivel(cor), "existe": existe})
            except Exception as e:  # noqa: BLE001
                _log(f"app {nome}: {e}")
        return saida

    def abrir_app(self, nome: str) -> bool:
        try:
            import automacao
            automacao._executar_acao_por_dict(
                {"acao": "abrir_app", "alvo": nome, "resposta": "Feito."},
                callback_falar=None)
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"abrir_app: {e}")
            return False

    def estado_automacao(self) -> dict:
        est = {"monitor_downloads": False, "monitor_discord": False,
               "mudo": False, "espiadinha": False,
               "autonomia_experimental": False,
               "voz_delegacao_rapida": True,
               "audio_preprocess_denoise": True,
               "audio_preprocess_normalize": True,
               "audio_preprocess_vad": True,
               "pet_desktop_disponivel": ambiente_fedora(),
               "pet_desktop_ativo": False,
               "pet_desktop_tamanho": 100}
        if self._demo_ativo():
            est.update({"demo": True, "autonomia_experimental": False,
                        "audio_preprocess_denoise": False,
                        "audio_preprocess_normalize": False,
                        "audio_preprocess_vad": False})
            return est
        try:
            import preferencias
            est["autonomia_experimental"] = bool(
                preferencias.obter("autonomia_experimental", False))
            est["voz_delegacao_rapida"] = bool(
                preferencias.obter("voz_delegacao_rapida", True))
            for chave in ("audio_preprocess_denoise",
                          "audio_preprocess_normalize",
                          "audio_preprocess_vad"):
                est[chave] = bool(preferencias.obter(chave, True))
            if est["pet_desktop_disponivel"]:
                est["pet_desktop_ativo"] = bool(preferencias.obter(
                    "pet_desktop_ativo", True))
                try:
                    est["pet_desktop_tamanho"] = max(50, min(130, int(
                        preferencias.obter("pet_desktop_tamanho", 100))))
                except (TypeError, ValueError):
                    pass
        except Exception:
            pass
        automacao = _ja_carregado("automacao")
        if automacao is not None:
            try:
                fn = getattr(automacao, "monitor_ativo", None)
                est["monitor_downloads"] = bool(fn()) if callable(fn) else False
            except Exception:
                pass
        dc = _ja_carregado("discord_bot")
        if dc is not None:
            try:
                fn = getattr(dc, "escuta_ativa", None)
                est["monitor_discord"] = bool(fn()) if callable(fn) else False
            except Exception:
                pass
        voz = _ja_carregado("voz")
        if voz is not None:
            try:
                est["mudo"] = bool(voz.mudo.is_set())
            except Exception:
                pass
        # Espiadinha: o estado runtime manda; sem o módulo carregado ainda,
        # a preferência salva responde por ele.
        esp = _ja_carregado("espiadinha")
        if esp is not None:
            try:
                est["espiadinha"] = bool(esp.ativa())
            except Exception:
                pass
        else:
            try:
                import preferencias
                est["espiadinha"] = bool(preferencias.obter("espiadinha", False))
            except Exception:
                pass
        from cloud_runtime_client import hospedado_na_oracle
        est["discord_cloud"] = hospedado_na_oracle()
        if est["discord_cloud"]:
            try:
                from cloud_runtime_client import rpc
                est["monitor_discord"] = bool(rpc("status", {}).get("monitor"))
            except Exception as erro:
                est["monitor_discord"] = False
                est["discord_cloud_erro"] = True
                _log(f"estado_automacao: Oracle não respondeu ao status do Discord ({type(erro).__name__}: {str(erro)[:120]})")
        return est

    def set_toggle(self, qual: str, ligado: bool) -> bool:
        try:
            if qual == "pet_desktop_ativo" and ambiente_fedora():
                import preferencias
                if not preferencias.definir(pet_desktop_ativo=bool(ligado)):
                    return False
                if ligado:
                    self._j._iniciar_sprite()
                    ativo = bool(self._j._sprite and self._j._sprite.poll() is None)
                    if not ativo:
                        preferencias.definir(pet_desktop_ativo=False)
                    return ativo
                self._j._parar_sprite()
                return True
            if qual == "mudo":
                import voz
                voz.mudo.set() if ligado else voz.mudo.clear()
                return True
            if qual == "monitor_downloads":
                import automacao
                fn = getattr(automacao,
                             "iniciar_monitor_downloads" if ligado else "parar_monitor_downloads", None)
                if fn:
                    fn()
                    return True
            if qual == "monitor_discord":
                import discord_monitor
                return discord_monitor.selecionar(bool(ligado))
            if qual == "espiadinha":
                import espiadinha
                import preferencias
                if not preferencias.definir(espiadinha=bool(ligado)):
                    return False
                espiadinha.definir_ativa(bool(ligado))
                return True
            if qual == "autonomia_experimental":
                import preferencias
                return preferencias.definir(autonomia_experimental=bool(ligado))
            if qual == "voz_delegacao_rapida":
                import preferencias
                return preferencias.definir(voz_delegacao_rapida=bool(ligado))
            if qual in ("audio_preprocess_denoise",
                        "audio_preprocess_normalize",
                        "audio_preprocess_vad"):
                import preferencias
                return preferencias.definir(**{qual: bool(ligado)})
        except Exception as e:  # noqa: BLE001
            _log(f"set_toggle {qual}: {e}")
        return False

    def pet_tamanho_definir(self, percentual: int) -> bool:
        """Ajusta o pet imediatamente; o tamanho fica só neste Fedora."""
        if not ambiente_fedora():
            return False
        try:
            tamanho = int(percentual)
            if not 50 <= tamanho <= 130:
                return False
            import preferencias
            if not preferencias.definir(pet_desktop_tamanho=tamanho):
                return False
            processo = self._j._sprite
            if processo and processo.poll() is None:
                processo.stdin.write(f"size {tamanho}\n")
                processo.stdin.flush()
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"pet_tamanho_definir: {e}")
            return False

    def organizar_downloads(self) -> Optional[str]:
        try:
            import ferramentas
            return ferramentas.executar("organizar_downloads", {})
        except Exception as e:  # noqa: BLE001
            _log(f"organizar_downloads: {e}")
            return None

    # ── TV: dispositivos salvos, conexão e pareamento ────────────
    #
    # Espelho da aba TV que o celular já tinha. O trabalho de verdade vive no
    # controle_tv.py; aqui é a ponte pra tela. Conectar e parear passam do teto
    # de 8s do api(), então rodam em thread e o resultado volta por EVENTO
    # ("tv" via Emily.on) — mesmo desenho do emily_code_enviar.

    def tv_dispositivos(self) -> list:
        try:
            import controle_tv
            return controle_tv.listar_dispositivos()
        except Exception as e:  # noqa: BLE001
            _log(f"tv_dispositivos: {e}")
            return []

    def tv_salvar(self, nome: str, ip: str, tipo: str = "") -> dict:
        try:
            import controle_tv
            d = controle_tv.salvar_dispositivo(nome, ip, tipo)
            return {"ok": True, "dispositivo": d,
                    "mensagem": f"TV salva: {d['nome']} ({d['ip']})"}
        except ValueError as e:
            return {"ok": False, "mensagem": str(e)}
        except Exception as e:  # noqa: BLE001
            _log(f"tv_salvar: {e}")
            return {"ok": False, "mensagem": f"Não consegui salvar: {e}"}

    def tv_editar(self, id_dispositivo: str, nome: str = "",
                  ip: str = "", tipo: str = "") -> dict:
        try:
            import controle_tv
            d = controle_tv.editar_dispositivo(id_dispositivo, nome, ip, tipo)
            return {"ok": True, "dispositivo": d, "mensagem": "TV atualizada"}
        except ValueError as e:
            return {"ok": False, "mensagem": str(e)}
        except Exception as e:  # noqa: BLE001
            _log(f"tv_editar: {e}")
            return {"ok": False, "mensagem": f"Não consegui editar: {e}"}

    def tv_remover(self, id_dispositivo: str) -> dict:
        try:
            import controle_tv
            r = controle_tv.remover_dispositivo(id_dispositivo)
            return {"ok": not r.startswith("ERRO"), "mensagem": r}
        except Exception as e:  # noqa: BLE001
            _log(f"tv_remover: {e}")
            return {"ok": False, "mensagem": f"Não consegui remover: {e}"}

    def tv_conectar(self, id_dispositivo: str) -> dict:
        """Inicia a conexão fora da UI; o desfecho chega no evento 'tv'."""
        def trabalho():
            try:
                import controle_tv
                r = controle_tv.conectar_dispositivo(id_dispositivo)
                self._j._push("tv", {
                    "tipo": ("conectado" if r.get("ok")
                             else ("precisa_parear" if r.get("precisa_parear")
                                   else "erro")),
                    "mensagem": r.get("mensagem", ""),
                })
            except Exception as e:  # noqa: BLE001
                _log(f"tv_conectar: {e}")
                self._j._push("tv", {"tipo": "erro", "mensagem": str(e)})
        threading.Thread(target=trabalho, daemon=True).start()
        return {"ok": True, "mensagem": "Conectando…"}

    def tv_parear(self, id_dispositivo: str) -> dict:
        """Pede o código à TV; quando ela mostrar, o evento 'tv' pede pra você digitar."""
        def trabalho():
            try:
                import controle_tv
                r = controle_tv.iniciar_pareamento(id_dispositivo)
                if not r.get("ok"):
                    self._j._push("tv", {"tipo": "erro",
                                         "mensagem": r.get("mensagem", "")})
                else:
                    self._j._push("tv", {"tipo": "codigo_pedindo",
                                         "id": id_dispositivo,
                                         "mensagem": r.get("mensagem", "")})
            except Exception as e:  # noqa: BLE001
                _log(f"tv_parear: {e}")
                self._j._push("tv", {"tipo": "erro", "mensagem": str(e)})
        threading.Thread(target=trabalho, daemon=True).start()
        return {"ok": True, "mensagem": "Pedindo código à TV…"}

    def tv_codigo(self, codigo: str) -> dict:
        """Conclui o pareamento com o código digitado; desfecho no evento 'tv'."""
        codigo = (codigo or "").strip()
        if not codigo:
            return {"ok": False, "mensagem": "Código vazio"}
        def trabalho():
            try:
                import controle_tv
                r = controle_tv.concluir_pareamento(codigo)
                self._j._push("tv", {"tipo": ("pareado" if r.get("ok") else "erro"),
                                     "mensagem": r.get("mensagem", "")})
            except Exception as e:  # noqa: BLE001
                _log(f"tv_codigo: {e}")
                self._j._push("tv", {"tipo": "erro", "mensagem": str(e)})
        threading.Thread(target=trabalho, daemon=True).start()
        return {"ok": True, "mensagem": "Concluindo pareamento…"}

    # ── Voz do Fish: qual das vozes testadas a Emily usa ──────────
    # O catálogo e a preferência vivem no vozes_fish.py. A troca vale na
    # próxima fala (voz.py lê a escolha a cada síntese), sem reiniciar.

    def voz_fish_estado(self) -> dict:
        try:
            import vozes_fish
            import voz
            return {"ok": True, "vozes": vozes_fish.catalogo(),
                    "atual": vozes_fish.chave_atual(voz.FISH_VOICE_ID)}
        except Exception as e:  # noqa: BLE001
            _log(f"voz_fish_estado: {e}")
            return {"ok": False, "vozes": [], "atual": "", "mensagem": str(e)}

    def voz_fish_definir(self, chave: str) -> dict:
        try:
            import vozes_fish
            if not vozes_fish.definir(str(chave or "")):
                return {"ok": False, "mensagem": "Não consegui salvar a voz."}
            return {"ok": True, "atual": str(chave)}
        except Exception as e:  # noqa: BLE001
            _log(f"voz_fish_definir: {e}")
            return {"ok": False, "mensagem": str(e)}

    # ── Casa: lâmpada e tomada Tuya ───────────────────────────────
    # O trabalho fica no casa_inteligente.py. A tomada aparece só como
    # leitura: ela alimenta este PC, então ligar/cortar é pelo celular.

    def casa_estado(self) -> dict:
        try:
            import casa_inteligente as casa
            if not casa.configurada():
                return {"ok": False, "configurada": False, "dispositivos": []}
            dados = casa.estado()
            for item in dados.get("dispositivos", []):
                item.pop("hsv", None)
            return {**dados, "configurada": True}
        except Exception as e:  # noqa: BLE001
            _log(f"casa_estado: {e}")
            return {"ok": False, "configurada": True, "mensagem": str(e), "dispositivos": []}

    def casa_luz(self, acao: str, valores: dict | None = None) -> dict:
        valores = valores if isinstance(valores, dict) else {}
        try:
            import casa_inteligente as casa
            return casa.controlar_luz(str(acao or ""), alvo=str(valores.get("alvo") or ""),
                                      cor=str(valores.get("cor") or ""), brilho=valores.get("brilho"),
                                      temperatura=valores.get("temperatura"))
        except Exception as e:  # noqa: BLE001
            _log(f"casa_luz: {e}")
            return {"ok": False, "mensagem": str(e)}


    # ── Modelo e raciocínio (seletores do composer) ───────────────

    def visual_modelo_niveis(self, modelo: str) -> list:
        import llm
        return llm.niveis_raciocinio(modelo)

    def visual_modelo_estado(self) -> dict:
        import config_agente_visual
        return config_agente_visual.estado()

    def visual_modelo_definir(self, provedor: str, modelo: str, raciocinio: str) -> bool:
        if self._demo_ativo():
            return False
        import config_agente_visual
        return config_agente_visual.definir(provedor, modelo, raciocinio)

    def estado_modelo(self) -> dict:
        """O que o composer mostra: provedor/modelo/raciocínio atuais + opções."""
        if self._demo_ativo():
            modelo_demo = {"id": "emily-demo", "nome": "Emily Demo", "sobre": "Sessão isolada"}
            return {"provedor": "demo", "modelo": "emily-demo", "raciocinio": "baixo",
                    "modelos": [modelo_demo],
                    "provedores": [{"id": "demo", "nome": "Modo Demo",
                                     "modelos": [modelo_demo]}],
                    "niveis": [{"id": "baixo", "nome": "Padrão"}], "demo": True}
        atual_provedor = ""
        atual_modelo = ""
        atual_racio = "baixo"
        try:
            import preferencias
            atual_provedor = preferencias.obter("provedor") or ""
            atual_modelo = preferencias.obter("modelo") or ""
            atual_racio = preferencias.obter("raciocinio") or atual_racio
        except Exception as e:  # noqa: BLE001
            _log(f"estado_modelo: prefs ({e})")
        try:
            import llm
            # A fonte da verdade é o que está ativo de verdade na camada de
            # LLM, não a preferência salva — elas dessincronizam quando o
            # .env muda (EMILY_PROVEDOR_LLM) ou a pref é de outra sessão.
            provedor_vivo = llm.TABELA_ATIVA or atual_provedor
            modelo_vivo = llm.ROTAS["conversa"].modelo if "conversa" in llm.ROTAS else ""
            racio_vivo = llm.ROTAS["conversa"].raciocinio if "conversa" in llm.ROTAS else atual_racio
            return {
                "provedor": provedor_vivo,
                "modelo": modelo_vivo or atual_modelo,
                "raciocinio": racio_vivo,
                # Lista plana (legado): só modelos do provedor ativo.
                "modelos": llm.modelos_disponiveis(),
                # Lista agrupada (novo): provedores + modelos de cada um.
                "provedores": llm.listar_provedores(),
                "niveis": llm.niveis_raciocinio(modelo_vivo or atual_modelo),
            }
        except Exception as e:  # noqa: BLE001
            _log(f"estado_modelo: llm ({e})")
            return {"provedor": atual_provedor, "modelo": atual_modelo,
                    "raciocinio": atual_racio, "modelos": [],
                    "provedores": [], "niveis": []}

    def definir_provedor_e_modelo(self, provedor: str, modelo: str) -> bool:
        """
        Troca provedor e modelo de uma vez. Persiste ambos nas preferências.

        Se o provedor é o já ativo, cai no caminho antigo (só modelo) —
        não precisa re-resolver tabela nem refazer a carga.
        """
        try:
            import llm
            import preferencias
            provedor = (provedor or "").strip()
            if not provedor or provedor not in llm.PROVEDORES:
                _log(f"definir_provedor_e_modelo: provedor '{provedor}' inválido")
                return False
            if provedor != llm.TABELA_ATIVA:
                if not llm.definir_provedor_e_modelo(provedor, modelo or ""):
                    return False
            else:
                if modelo and not llm.definir_modelo_conversa(modelo):
                    return False
            llm.definir_raciocinio_conversa(preferencias.obter("raciocinio") or "baixo")
            preferencias.definir(provedor=provedor, modelo=modelo or None,
                                raciocinio=llm.ROTAS["conversa"].raciocinio)
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"definir_provedor_e_modelo: {e}")
            return False

    def definir_modelo(self, modelo: str) -> bool:
        """Compat: troca só o modelo no provedor ativo, sem mexer em provedor."""
        try:
            import llm
            if not llm.definir_modelo_conversa(modelo):
                return False
            import preferencias
            llm.definir_raciocinio_conversa(preferencias.obter("raciocinio") or "baixo")
            preferencias.definir(modelo=modelo,
                                raciocinio=llm.ROTAS["conversa"].raciocinio)
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"definir_modelo: {e}")
            return False

    def definir_raciocinio(self, nivel: str) -> bool:
        try:
            import llm
            modelo = llm.ROTAS["conversa"].modelo
            if nivel not in {item["id"] for item in llm.niveis_raciocinio(modelo)}:
                return False
            if not llm.definir_raciocinio_conversa(nivel):
                return False
            import preferencias
            preferencias.definir(raciocinio=llm.ROTAS["conversa"].raciocinio)
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"definir_raciocinio: {e}")
            return False

    # ── Volume da voz ─────────────────────────────────────────────
    # O Vitor achava a voz alta e não tinha como regular. O fator vive no
    # voz.py (aplicado em TODO áudio gerado: alto-falante, Discord, celular).

    def volume_voz(self) -> float:
        if self._demo_ativo():
            return 1.0
        try:
            import voz
            return float(voz.volume_atual())
        except Exception as e:  # noqa: BLE001
            _log(f"volume_voz: {e}")
            return 1.0

    def definir_volume_voz(self, valor: float) -> bool:
        try:
            import voz
            voz.definir_volume(valor)
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"definir_volume_voz: {e}")
            return False

    # ── Modelo do Discord ─────────────────────────────────────────
    # Seletor nas configurações, no mesmo espírito do do chat: lista os
    # modelos do provedor ativo com nome legível; vazio = padrão da rota.

    @staticmethod
    def _nome_bonito_modelo(mid: str) -> str:
        # Só formata famílias conhecidas; o ID original continua intacto para
        # selecionar o modelo e aparece como subtítulo no menu.
        nome = (mid or "").rsplit("/", 1)[-1].lower()
        claude = re.fullmatch(r"claude-(sonnet|opus|haiku|fable)-(\d+(?:[.-]\d+)*)", nome)
        if claude:
            familia, versao = claude.groups()
            return f"Claude {familia.title()} {versao.replace('-', '.')}"
        gpt = re.fullmatch(r"gpt-(\d+(?:[.-]\d+)*)(?:-(sol|luna|astra|terra))?", nome)
        if gpt:
            versao, variante = gpt.groups()
            return f"GPT-{versao.replace('-', '.')}" + (f" {variante.title()}" if variante else "")
        return mid

    def discord_modelo(self) -> dict:
        if self._demo_ativo():
            return {"atual": "", "modelos": [], "demo": True}
        try:
            import llm
            atual = llm.modelo_discord()
            modelos = []
            vistos = set()
            for p in llm.listar_provedores() or []:
                for m in (p.get("modelos") or []):
                    mid = (m.get("id") if isinstance(m, dict) else str(m)) or ""
                    if not mid or mid in vistos:
                        continue
                    vistos.add(mid)
                    modelos.append({"id": mid,
                                    "nome": self._nome_bonito_modelo(mid)})
            return {"atual": atual, "modelos": modelos}
        except Exception as e:  # noqa: BLE001
            _log(f"discord_modelo: {e}")
            return {"atual": "", "modelos": []}

    def discord_definir_modelo(self, modelo: str) -> bool:
        try:
            import llm
            modelo = (modelo or "").strip()
            if modelo:
                ids = {m.get("id") if isinstance(m, dict) else str(m)
                       for p in (llm.listar_provedores() or [])
                       for m in (p.get("modelos") or [])}
                if ids and modelo not in ids:
                    return False
            return bool(llm.definir_modelo_discord(modelo))
        except Exception as e:  # noqa: BLE001
            _log(f"discord_definir_modelo: {e}")
            return False

    # ── Perfil editável (nome, foto, personalidade) ───────────────

    def definir_perfil(self, nome: str, personalidade_extra: str) -> bool:
        """Salva nome e personalidade extra. O nome vazio cai no padrão."""
        if self._demo_ativo():
            import modo_demo
            return modo_demo.definir_nome(nome)
        try:
            import preferencias
            nome = (nome or "").strip()
            preferencias.definir(
                nome=nome or None,   # None = não sobrescreve; mantém o atual
                personalidade_extra=(personalidade_extra or "").strip(),
            )
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"definir_perfil: {e}")
            return False

    def escolher_avatar(self) -> Optional[str]:
        """
        Diálogo nativo pra escolher a FOTO DO USUÁRIO (o ícone do canto e o
        editor de perfil). Salva em `avatar_usuario` — preferência separada do
        retrato da Emily, pra uma foto não sobrescrever a outra. Não toca no
        `_avatar` da janela (que é o retrato dela) e não emite o evento
        'avatar' (que o JS associa ao avatar da Emily). Devolve o data-uri pra
        a interface pintar na hora.
        """
        try:
            import webview
            j = self._j._janela
            escolhido = j.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False,
                file_types=("Imagens (*.png;*.jpg;*.jpeg;*.webp;*.bmp)",
                            "Todos os arquivos (*.*)"))
            caminho = escolhido[0] if escolhido else None
            if not caminho:
                return None
            uri = _avatar_reduzido(caminho)
            if not uri:
                return None
            import preferencias
            preferencias.definir(avatar_usuario=uri)
            return uri
        except Exception as e:  # noqa: BLE001
            _log(f"escolher_avatar: {e}")
            return None

    def listar_modos(self) -> list:
        """
        Os modos vêm do próprio catálogo de ferramentas, não de uma lista
        duplicada aqui. Depois da fusão em definir_modo(modo, ligar), a fonte
        da verdade é ferramentas._MODOS — se um modo novo nascer lá, ele
        aparece nas configurações sozinho.
        """
        try:
            import ferramentas
            rotulos = {
                "modo_escrito": ("Modo escrito", "tecla"),
                "modo_controle_tela": ("Controle de tela", "monitor"),
                "monitoramento_jogo": ("Monitorar o jogo", "cubo"),
                "escuta_discord": ("Escutar o Discord", "chat"),
            }
            saida = []
            for mid, sobre in ferramentas._MODOS.items():
                nome, icone = rotulos.get(mid, (mid.replace("_", " ").capitalize(), "tecla"))
                # A frase do catálogo é escrita pro MODELO ler; pra tela fica
                # só a parte depois dos dois pontos, que é a explicação.
                limpa = sobre.split(":", 1)[-1].strip()
                saida.append({"id": mid, "nome": nome, "icone": icone,
                              "sobre": limpa[:110], "ligado": self._modo_ligado(mid)})
            return saida
        except Exception as e:  # noqa: BLE001
            _log(f"listar_modos: {e}")
            return []

    @staticmethod
    def _modo_ligado(mid: str) -> bool:
        main = _ja_carregado("main")
        if main is None:
            return False
        try:
            if mid == "monitoramento_jogo":
                return bool(main.modo_jogo_ativo.is_set())
            atributo = {
                "modo_escrito": "modo_escrito_ativo",
                "modo_controle_tela": "modo_ui_ativo",
                "escuta_discord": "escuta_discord_ativa",
            }.get(mid)
            return bool(getattr(main, atributo, False)) if atributo else False
        except Exception:
            return False

    def ativar_modo(self, mid: str, ligar: bool) -> bool:
        try:
            import ferramentas
            r = ferramentas.executar_estruturado(
                "definir_modo", {"modo": mid, "ligar": bool(ligar)})
            return bool(r.ok)
        except Exception as e:  # noqa: BLE001
            _log(f"ativar_modo: {e}")
            return False

    def listar_memoria(self) -> list:
        try:
            import memoria
            return [str(f) for f in memoria.listar_fatos()][:200]
        except Exception as e:  # noqa: BLE001
            _log(f"listar_memoria: {e}")
            return []

    def add_fato(self, texto: str) -> bool:
        try:
            import ferramentas
            ferramentas.executar("guardar_fato", {"fato": texto})
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"add_fato: {e}")
            return False

    def del_fato(self, texto: str) -> bool:
        try:
            import ferramentas
            ferramentas.executar("esquecer_fato", {"fato": texto})
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"del_fato: {e}")
            return False

    # ── Memória unificada (sistema novo) ──────────────────────────
    # Tudo aqui é à prova de falha: se a memória nova não estiver ativa
    # (flag 0, Ollama fora, banco quebrado), a tela mostra o estado vazio
    # e a seção antiga de fatos continua funcionando do mesmo jeito.

    def memoria_unificada_estado(self) -> dict:
        try:
            import memoria_unificada as mu
            from memoria_unificada.journal import JournalMemoria
            ponte = mu.ponte()
            if ponte.ativa:
                # Diagnóstico preguiçoso: abre a infraestrutura aqui para a aba
                # já distinguir modo completo de journal-only no primeiro desenho.
                ponte._pronta()
            estado = ponte.estado()
        except Exception as e:  # noqa: BLE001
            _log(f"memoria_unificada_estado: {e}")
            return {"ativa": False, "flag": None, "desativada_por_erro": False,
                    "falhas_consecutivas": 0, "iniciada": False, "erro": str(e)}
        try:
            cfg = ponte.config
            estado["pasta_dados"] = str(cfg.pasta_dados)
            estado["provedor_embeddings"] = cfg.provedor_embeddings
            estado["modelo_embeddings"] = cfg.modelo_embeddings
            journal = JournalMemoria(cfg)
            dono = mu.dono_id()
            estado["eventos_total"] = journal.contar_eventos(dono)
            estado["eventos_recentes_janela"] = len(journal.listar_recentes(
                dono, limite=500))
            estado["lotes_pendentes"] = journal.contar_lotes_recuperaveis(dono)
        except Exception as e:  # noqa: BLE001
            _log(f"memoria_unificada_estado (detalhes): {e}")
        if estado.get("ultimo_erro") and not estado.get("erro"):
            estado["erro"] = estado["ultimo_erro"]
        return estado

    def memoria_unificada_listar(self, busca: str = "", status: str = "active",
                                 pool: str = "todos", limite: int = 200) -> list:
        try:
            import memoria_unificada as mu
            ponte = mu.ponte()
            if not ponte.ativa or ponte.estado().get("modo_degradado"):
                return []
            armazenamento = ponte._pronta()
            if armazenamento is None:
                return []
            _, recuperador = armazenamento
            dono = mu.dono_id()
            estados = None if status == "todos" else (status,)
            pools = ("general", "code") if pool == "todos" else (pool,)
            fatos = recuperador.armazenamento.listar(
                dono, limite=max(1, int(limite)), status=estados,
                privacy_scopes=("owner_private", "public"), pools=pools)
            texto = str(busca or "").strip().casefold()
            saida = []
            for fato in fatos:
                if texto and texto not in fato.texto.casefold():
                    continue
                saida.append({
                    "id": fato.id,
                    "texto": fato.texto,
                    "importancia": fato.importancia,
                    "status": fato.status,
                    "topico": fato.topico,
                    "canal": fato.canal_origem,
                    "entidades": list(fato.entidades),
                    "evidence_role": fato.evidence_role,
                    "confianca": round(fato.confianca, 3),
                    "memory_pool": fato.memory_pool,
                    "criado_em": fato.criado_em,
                    "atualizado_em": fato.atualizado_em,
                    "superseded_by": fato.superseded_by,
                })
            return saida
        except Exception as e:  # noqa: BLE001
            _log(f"memoria_unificada_listar: {e}")
            return []

    def memoria_unificada_esquecer(self, fato_id: str) -> bool:
        try:
            import memoria_unificada as mu
            ponte = mu.ponte()
            if not ponte.ativa or ponte.estado().get("modo_degradado"):
                return False
            pronta = ponte._pronta()
            if pronta is None:
                return False
            _, recuperador = pronta
            recuperador.armazenamento.esquecer(mu.dono_id(), fato_id)
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"memoria_unificada_esquecer: {e}")
            return False

    def memoria_unificada_reativar(self, fato_id: str) -> bool:
        try:
            import memoria_unificada as mu
            ponte = mu.ponte()
            if not ponte.ativa or ponte.estado().get("modo_degradado"):
                return False
            pronta = ponte._pronta()
            if pronta is None:
                return False
            _, recuperador = pronta
            armazenamento = recuperador.armazenamento
            fato = armazenamento.obter(mu.dono_id(), fato_id)
            if fato is None:
                return False
            armazenamento.salvar(fato.com_estado("active"))
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"memoria_unificada_reativar: {e}")
            return False

    # ── Memória das pessoas do Discord ────────────────────────────
    # A Emily guarda fatos por membro no memoria_discord.json (perfil_discord).
    # Aqui é a ponte pra tela de configurações: listar, ensinar e esquecer.

    def listar_pessoas_discord(self) -> list:
        try:
            import perfil_discord
            membros = perfil_discord.carregar().get("membros") or {}
            saida = []
            for uid, ficha in membros.items():
                saida.append({
                    "id": str(uid),
                    "nome": str(ficha.get("nome") or uid),
                    "mensagens": int(ficha.get("mensagens", 0) or 0),
                    "interacoes": int(ficha.get("interacoes", 0) or 0),
                    "fatos": [str(f) for f in (ficha.get("fatos") or [])],
                })
            # Com fatos primeiro (é o que interessa editar), depois por quem
            # ela mais conversa. Quem nunca falou nada vai pro fim da lista.
            saida.sort(key=lambda p: (-len(p["fatos"]), -p["interacoes"], p["nome"]))
            return saida
        except Exception as e:  # noqa: BLE001
            _log(f"listar_pessoas_discord: {e}")
            return []

    def add_fato_pessoa(self, uid: str, nome: str, texto: str) -> str:
        try:
            import perfil_discord
            return perfil_discord.adicionar_fato_manual(int(uid), nome, texto)
        except Exception as e:  # noqa: BLE001
            _log(f"add_fato_pessoa: {e}")
            return ""

    def del_fato_pessoa(self, uid: str, texto: str) -> str:
        try:
            import perfil_discord
            return perfil_discord.remover_fato_manual(int(uid), texto)
        except Exception as e:  # noqa: BLE001
            _log(f"del_fato_pessoa: {e}")
            return ""

    # ── Sistema e janela ──────────────────────────────────────────

    def sistema(self) -> dict:
        import datetime
        if self._demo_ativo():
            return {"cpu": 24.0, "ram": 41.0, "hora": "14:32",
                    "data": "terça, 12/08",
                    "demo": True}
        # Usa UTC + conversão pro fuso correto em vez de datetime.now() local,
        # que pode ficar confuso quando o RTC está em hora local (warning do
        # timedatectl). O fuso Brazil/East é América/São Paulo (UTC-3 o ano
        # todo desde 2019, quando o Brasil acabou com horário de verão).
        try:
            from modelo import _fuso_bh
            agora = datetime.datetime.now(_fuso_bh())
        except Exception:
            # Fallback: se _fuso_bh falhar, usa local mesmo
            agora = datetime.datetime.now()
        cpu = ram = 0.0
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
        except Exception:
            pass
        dias = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
        return {"cpu": cpu, "ram": ram,
                "hora": agora.strftime("%H:%M"),
                "data": f"{dias[agora.weekday()]}, {agora.day:02d}/{agora.month:02d}"}

    def janela(self, acao: str) -> bool:
        j = self._j._janela
        if j is None:
            return False
        try:
            if acao == "minimizar":
                j.minimize()
            elif acao == "maximizar":
                self._j._maximizada = not self._j._maximizada
                j.restore() if not self._j._maximizada else j.maximize()
            elif acao == "fechar":
                self._j._encerrar()
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"janela({acao}): {e}")
            return False


def _ja_carregado(nome: str):
    """
    O módulo, se ele JÁ estiver carregado. Nunca importa.

    Isto é uma regra, não uma otimização. A primeira versão fazia
    `import main` pra ler o estado dos modos — e `main` é o ponto de entrada
    do projeto: importá-lo de dentro da UI RODA o main.py inteiro de novo,
    subindo voz, Discord e automação no meio de um clique em Configurações.
    Na sonda isso travou a tela de configurações inteira.

    Desenhar um painel não pode ter o efeito colateral de ligar subsistema.
    Em produção o main.py e o automacao.py já estão em sys.modules quando a
    janela abre, então o estado real aparece. Rodando a interface sozinha, o
    que não está de pé aparece como desligado — que é a verdade.
    """
    import sys
    return sys.modules.get(nome)


def _cor_legivel(fundo: str) -> str:
    """Preto ou branco sobre o fundo, pelo brilho. O Steam é #171a21."""
    try:
        h = fundo.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "#111" if (r * 299 + g * 587 + b * 114) / 1000 > 150 else "#fff"
    except Exception:
        return "#fff"


def _tirar_falas_de_processo(resposta: str, falas: List[str]) -> str:
    """
    Remove da resposta os comentários de processo ("peraí, deixa eu ver").

    Mesma ideia do _textoLimpoDaBolha do JS, mas com um cuidado a mais: NÃO
    colapsa espaços nem quebras de linha. Código dentro de ``` depende da
    indentação e das linhas — foi por colapsar tudo que o bloco de código
    chegava numa linha só. Aqui só tira o preâmbulo e apara as pontas.
    """
    texto = resposta or ""
    for f in falas or []:
        f = (f or "").strip()
        if f:
            texto = texto.replace(f, "")
    return texto.strip()


# ═════════════════════════════════════════════════════════════════
# COMPATIBILIDADE COM O ENCERRAMENTO DO main.py
#
# O encerrar_tudo() do main.py chama janela.root.destroy() e
# janela._painel.destroy(). Eram objetos do Qt. Aqui não existe Qt, mas o
# contrato tem que continuar valendo — e falhar no encerramento deixaria
# processo pendurado.
# ═════════════════════════════════════════════════════════════════

class _Destrutivel:
    def __init__(self, fn: Callable[[], None]):
        self._fn = fn

    def destroy(self) -> None:
        try:
            self._fn()
        except Exception as e:  # noqa: BLE001
            _log(f"destroy: {e}")

    # A interface antiga era Tk/Qt e o main.py mexia nisso em alguns pontos.
    def __getattr__(self, _nome):
        return lambda *a, **k: None


# ═════════════════════════════════════════════════════════════════
# A JANELA
# ═════════════════════════════════════════════════════════════════

class JanelaEmily:
    """
    Mesma superfície pública da JanelaEmily do interface.py.

    Quem chama isto (main.py) não sabe, e não precisa saber, que por baixo
    agora é uma WebView em vez de widgets do Qt.
    """

    def __init__(self, callback_texto=None, callback_trocar_monitor=None):
        self.callback_texto = callback_texto
        self.callback_trocar_monitor = callback_trocar_monitor
        self.callback_visao = None
        self.callback_arquivo = None
        self.callback_arquivos = None

        self._janela = None
        self._httpd = None
        self._pronta = threading.Event()
        self._maximizada = False
        self._cid: Optional[str] = None
        # O retrato da EMILY — o que aparece no hero e nas mensagens dela.
        # É SEMPRE o retrato de fábrica (emilyimage.png e reservas); a foto do
        # usuário vive em `preferencias['avatar_usuario']`, separada, pra trocar
        # uma não mudar a outra.
        self._avatar = _achar_avatar()
        self._ultimo_status = ("aguardando", "")
        self._fila_inicial: List[tuple] = []
        self._lock = threading.Lock()
        # pywebview/GTK não tolera bem evaluate_js concorrente. Esta ponte recebe
        # eventos de voz, visão, Discord e automação em threads diferentes; sem
        # serialização, scripts chegaram truncados ao WebKit ("pywebvi"/"pywebv")
        # e atualizações da legenda se perderam. Toda avaliação passa por
        # _avaliar_js, inclusive as sondas de inicialização.
        self._lock_js = threading.RLock()
        self._sprite = None
        # Acumulador da fala da Emily, pra gravar a resposta inteira no fim do
        # turno (ver atualizar_status).
        self._falando = False
        self._resposta_emily = ""
        # Comentários de processo ("peraí, deixa eu ver") do turno atual, pra
        # tirar da resposta salva.
        self._falas_processo: List[str] = []
        # Texto CRU e final da resposta (com quebras de linha e código), quando
        # o modelo manda. É preferido na hora de salvar.
        self._resposta_crua = ""
        # Estado por turno do saneamento visual. É deliberadamente separado do
        # texto cru: tags de emoção continuam no histórico do modelo e no TTS.
        self._filtro_tags_stream = _FiltroStreamingTagsDeVoz()
        # No canal de voz, os deltas ficam só aqui — não são enviados token a
        # token à WebView. Quando o TTS começa uma unidade, atualizar_status
        # revela um prefixo cumulativo exato deste buffer (markdown, espaços e
        # parágrafos preservados). Protegido porque LLM e TTS são duas threads.
        self._stream_visual_voz = ""
        self._stream_visual_voz_indice = 0
        self._stream_visual_voz_ativo = False
        self._lock_stream_visual_voz = threading.Lock()
        # ── BANDEJA (tray) e fechamento pra segundo plano ──
        # O X da janela NÃO encerra a Emily: esconde pra bandeja, igual
        # Discord/Steam. "Sair de verdade" fica no menu do ícone da bandeja.
        # EMILY_INICIAR_OCULTA=1 (autostart) sobe sem janela, só na bandeja.
        self._sair_de_verdade = False
        self._tray = None
        self._iniciar_oculta = os.getenv("EMILY_INICIAR_OCULTA",
                                         "").strip() == "1"
        self._visivel = not self._iniciar_oculta

        self._ouvinte_agente_ui = self._publicar_estado_agente_ui
        try:
            import agente_ui
            agente_ui.adicionar_ouvinte_agente_ui(self._ouvinte_agente_ui)
        except Exception as e:  # noqa: BLE001
            _log(f"agente_ui: não registrei ouvinte da interface ({e})")

        self.root = _Destrutivel(self._encerrar)
        self._painel = _Destrutivel(self._encerrar)

    # ── Sprite flutuante ──────────────────────────────────────────
    #
    # O pet arrastável roda em processo separado. No Fedora usa GTK com
    # transparência real; no Windows o sprite antigo continua em Tk.

    def _iniciar_sprite(self) -> None:
        import platform_compat
        import subprocess
        import sys
        if self._sprite and self._sprite.poll() is None:
            return
        linux = platform_compat.is_linux()
        if linux:
            try:
                import preferencias
                if not preferencias.obter("pet_desktop_ativo", True):
                    return
            except Exception:
                return
        if os.getenv("EMILY_SPRITE", "1").strip() != "1":
            return
        script = os.path.join(DIR_BASE,
                              "pet_desktop_fedora.py" if linux else "sprite_flutuante.py")
        if not os.path.isfile(script):
            _log(f"pet não encontrado: {script}")
            return
        try:
            if not linux and getattr(sys, "frozen", False):
                _log("sprite Windows exige interpretador Python externo")
                return
            interpretador = "/usr/bin/python3" if linux else sys.executable
            comando = [interpretador, "-u", script]
            if linux:
                try:
                    tamanho = max(50, min(130, int(preferencias.obter(
                        "pet_desktop_tamanho", 100))))
                except (TypeError, ValueError):
                    tamanho = 100
                comando.extend(["--size", str(tamanho)])
            ambiente = os.environ.copy()
            if linux and ambiente.get("DISPLAY"):
                # No KDE/Wayland, o GTK nativo recebe decoração do compositor
                # mesmo com set_decorated(False). A janela XWayland mantém
                # RGBA, formato de clique e não ganha barra de título.
                ambiente["GDK_BACKEND"] = "x11"
            if linux and getattr(sys, "frozen", False):
                # Bibliotecas do PyInstaller não devem vazar para o Python
                # do sistema que desenha o pet GTK.
                original = ambiente.pop("LD_LIBRARY_PATH_ORIG", None)
                if original is None:
                    ambiente.pop("LD_LIBRARY_PATH", None)
                else:
                    ambiente["LD_LIBRARY_PATH"] = original
                ambiente.pop("PYTHONHOME", None)
            self._sprite = subprocess.Popen(
                comando,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1, env=ambiente,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._sprite_pronto = threading.Event()
            threading.Thread(target=self._ouvir_sprite, args=(self._sprite,),
                             daemon=True).start()
            if linux and (not self._sprite_pronto.wait(3)
                          or self._sprite.poll() is not None):
                _log("pet GTK não confirmou abertura")
                self._parar_sprite()
                return
            self._sprite_reage(self._ultimo_status[0])
            _log("pet flutuante iniciado")
        except Exception as e:  # noqa: BLE001
            _log(f"pet não iniciou: {e}")
            self._sprite = None

    def _parar_sprite(self) -> None:
        processo, self._sprite = self._sprite, None
        if not processo or processo.poll() is not None:
            return
        try:
            processo.stdin.write("quit\n")
            processo.stdin.flush()
            processo.wait(timeout=1.5)
        except Exception:
            processo.terminate()

    def _ouvir_sprite(self, processo) -> None:
        """Lê o stdout do sprite. 'toggle' = clicou com o botão direito."""
        try:
            for linha in processo.stdout:
                if linha.strip() == "ready":
                    self._sprite_pronto.set()
                if linha.strip() == "toggle":
                    self.toggle_visible()
        except Exception:
            pass

    # Estado da Emily → nome do gif. Os gifs vêm de img/*.gif, os mesmos
    # que a interface antiga usava.
    _GIF_DE_STATUS = {
        "aguardando": "idle", "ouvindo": "uping", "gravando": "uping",
        "pensando": "search", "ocupada": "search", "falando": "talk",
        "monitorando": "screen", "transferindo": "transfer",
        "abrindo_app": "open", "pesquisando": "search", "gerando": "search",
    }

    def _sprite_reage(self, status: str) -> None:
        if not self._sprite or self._sprite.poll() is not None:
            return
        try:
            import platform_compat
            if platform_compat.is_linux():
                estado = {
                    "ouvindo": "listening", "gravando": "listening",
                    "falando": "speaking", "pensando": "thinking",
                    "ocupada": "working", "monitorando": "working",
                    "transferindo": "working", "abrindo_app": "working",
                    "pesquisando": "working", "gerando": "working",
                }.get(status, "idle")
                self._sprite.stdin.write(f"state {estado}\n")
            else:
                gif = self._GIF_DE_STATUS.get(status, "idle")
                self._sprite.stdin.write(f"gif {gif}\n")
            self._sprite.stdin.flush()
        except Exception:
            pass

    # ── Ponte Python → JS ─────────────────────────────────────────

    def _publicar_estado_agente_ui(self, estado: dict) -> None:
        self._push("agente_ui", dict(estado or {}))

    def _avaliar_js(self, script: str):
        """Executa JavaScript de forma serializada entre todas as threads."""
        trava = getattr(self, "_lock_js", None)
        if trava is None:
            # Compatibilidade com instâncias mínimas feitas via __new__ em testes.
            trava = self._lock_js = threading.RLock()
        with trava:
            return self._janela.evaluate_js(script)

    def _push(self, evento: str, dados: dict) -> None:
        """
        Manda um evento pra tela.

        Engole o próprio erro de propósito: isto é chamado de umas seis threads
        (voz, visão, Discord, automação) e uma falha de UI não pode derrubar
        nenhuma delas. Antes da janela existir, guarda pra soltar no boot —
        senão o primeiro status, que sai durante o carregamento do main.py, se
        perde e a barra abre dizendo "Aguardando" quando ela já está pensando.
        """
        if not self._pronta.is_set():
            with self._lock:
                if len(self._fila_inicial) < 60:
                    self._fila_inicial.append((evento, dados))
            return
        try:
            payload = json.dumps({"e": evento, "d": dados}, ensure_ascii=True)
            # ASCII também evita o bug de WebKitGTK/pywebview que passa
            # len(script) como tamanho em bytes: acentos/emoji truncavam o script.
            # Os escapes JSON preservam integralmente o texto no navegador.
            # U+2028 e U+2029 (separadores de linha/parágrafo) são válidos em
            # JSON, mas em JavaScript são terminadores de linha — e com
            # ensure_ascii=False eles passam CRUS no payload. O WebKitGTK lê
            # o script até ali e morre com "SyntaxError: Unexpected end of
            # script": o evento nunca chega à tela. Texto de página da web
            # (ler_pagina, extrair_links) traz esses caracteres; a troca é
            # segura porque dentro de uma string JSON o escape \u2028 vale o
            # mesmo caractere.
            payload = (payload.replace("\u2028", "\\u2028")
                              .replace("\u2029", "\\u2029"))
            # Uma variável em vez de interpolar o payload DUAS vezes: com o
            # retrato dela (103KB de base64) a versão anterior mandava 206KB
            # por evento, porque o JSON aparecia nos dois argumentos.
            self._avaliar_js(
                f"(m => window.Emily.on(m.e, m.d))({payload})")
        except Exception as e:  # noqa: BLE001
            _log(f"push {evento}: {type(e).__name__}: {e}")

    def _drenar_fila(self) -> None:
        with self._lock:
            pendentes, self._fila_inicial = self._fila_inicial, []
        for evento, dados in pendentes:
            self._push(evento, dados)

    # ── Contrato que o main.py usa ────────────────────────────────

    def atualizar_status(self, status: str, texto: str = "") -> None:
        """
        O caminho principal de TUDO que aparece na tela.

        São 103 chamadas no main.py, e ela faz duas coisas ao mesmo tempo:
        muda o indicador de estado e, quando o estado é 'falando', o texto é
        uma FRASE da resposta dela — que o JS acumula numa mensagem só até o
        estado mudar. É o mesmo contrato da interface antiga; mudar isso aqui
        exigiria mexer no voz.py e no modelo.py.
        """
        self._ultimo_status = (status, texto)
        self._sprite_reage(status)

        # Acumula a fala da Emily pra SALVAR no disco no fim do turno. Sem isto,
        # só a mensagem do Vitor era gravada — e ao reabrir a conversa as
        # respostas dela sumiam. Era o "histórico faltando coisa" da tela
        # bugada. Mesma lógica do _on_status_changed da interface antiga: junta
        # enquanto o estado é 'falando', grava quando ele muda.
        if status == "falando" and texto:
            self._falando = True
            self._acumular_fala(texto)
        elif status != "falando" and (self._falando or self._resposta_crua.strip()):
            # Fim do turno. Grava mesmo se ela não falou nada em voz (turno
            # mudo com resposta só em texto/código) — aí o que salva é o cru.
            self._falando = False
            self._salvar_resposta_emily()

        texto_visual = (_texto_visual_sem_tags_de_voz(texto)
                        if status == "falando" else texto)
        payload = {"estado": status, "texto": texto_visual}
        # Legenda fiel e sincronizada: a frase que começou a tocar localiza seu
        # fim no stream já recebido, e a tela recebe UMA fotografia cumulativa
        # em vez de centenas de tokens. Se por alguma integração o texto não
        # casar, o JS cai na montagem normal por frases.
        if status == "falando" and texto_visual and getattr(
                self, "_stream_visual_voz_ativo", False):
            trava = getattr(self, "_lock_stream_visual_voz", None)
            if trava is None:
                trava = self._lock_stream_visual_voz = threading.Lock()
            with trava:
                fonte = getattr(self, "_stream_visual_voz", "")
                inicio = getattr(self, "_stream_visual_voz_indice", 0)
                pos = fonte.find(texto_visual.strip(), inicio)
                if pos >= 0:
                    fim = pos + len(texto_visual.strip())
                    self._stream_visual_voz_indice = fim
                    payload["texto_prefixo"] = fonte[:fim]
        self._push("status", payload)

    def _acumular_fala(self, frase: str) -> None:
        """
        Junta as frases da resposta da Emily numa string só.

        Mesma dedup do JS: o TTS às vezes reenvia a frase inteira em vez do
        pedaço novo, então frase que já é sufixo do que temos é ignorada, e
        frase que é superconjunto substitui.
        """
        frase = (frase or "").strip()
        if not frase:
            return
        antes = self._resposta_emily
        if antes and (antes == frase or antes.endswith(frase)):
            return
        if antes and frase.startswith(antes):
            self._resposta_emily = frase
        else:
            self._resposta_emily = f"{antes} {frase}" if antes else frase

    def _salvar_resposta_emily(self) -> None:
        if getattr(self, "sem_registro_remoto", False):
            # Turno remoto: zera os acumuladores sem gravar (a conversa é do
            # dispositivo que digitou — no caso, o celular).
            self._resposta_emily = ""
            self._resposta_crua = ""
            self._falas_processo = []
            self._fontes_pesquisa_turno = []
            self._resposta_fontes = []
            return
        # Prefere o texto CRU (com código e quebras de linha) quando o modelo
        # mandou; senão, cai no que foi acumulado das frases faladas.
        if self._resposta_crua.strip():
            texto = self._resposta_crua.strip()
        else:
            texto = _tirar_falas_de_processo(self._resposta_emily or "", self._falas_processo)
        self._resposta_emily = ""
        self._resposta_crua = ""
        self._falas_processo = []
        fontes = getattr(self, "_resposta_fontes", [])
        self._resposta_fontes = []
        if texto:
            self._registrar_na_conversa("emily", texto, fontes=fontes)


    def add_imagem_chat_safe(self, caminho: str, autor: str = "user") -> None:
        url = _data_uri(caminho)
        if url:
            self._push("imagem", {"url": url, "autor": autor})

    def mostrar_opcao_salvar(self, caminho: str) -> None:
        url = _data_uri(caminho)
        if url:
            self._push("salvar", {"caminho": caminho, "url": url})

    def progresso_evento(self, fase: str, dados: dict = None) -> None:
        dados = dados or {}
        if fase == "resultado" and dados.get("nome") == "programacao_aplicar":
            try:
                raw = json.loads(dados.get("resultado") or "{}")
                dados = dict(dados, programacao={"reiniciar_pc": bool(raw.get("reiniciar_pc")), "sessao": str(raw.get("sessao") or "")})
            except (ValueError, TypeError): pass
        if fase in {"ferramenta", "resultado", "reconectando", "erro_conexao"}:
            try:
                import conversas
                if fase == "ferramenta":
                    conversas.atualizar_turno_pendente(
                        self._cid, passo=str(dados.get("nome") or "Ferramenta").replace("_", " "),
                        situacao="Executando; resultado ainda não confirmado",
                        conferir_acao=True,
                        etapa={"nome": dados.get("nome"), "iniciar": True})
                elif fase == "resultado":
                    incerto = dados.get("erro") == "resultado_incerto"
                    conversas.atualizar_turno_pendente(
                        self._cid, passo=str(dados.get("nome") or "Ferramenta").replace("_", " "),
                        situacao=("Resultado incerto; confira antes de repetir" if incerto
                                  else "Resultado recebido" if dados.get("ok")
                                  else "Ferramenta falhou"),
                        conferir_acao=incerto or bool(dados.get("mudou")),
                        etapa={"nome": dados.get("nome"),
                               "situacao": ("incerto" if incerto else
                                             "sucesso" if dados.get("ok") else "falhou"),
                               "resultado": dados.get("resultado")})
                elif fase == "reconectando":
                    conversas.atualizar_turno_pendente(
                        self._cid, situacao=("Reconectando a voz" if dados.get("servico") == "voz"
                                            else "Reconectando a consulta" if dados.get("servico") == "ferramenta"
                                            else "Reconectando ao serviço de IA"))
                else:
                    conversas.atualizar_turno_pendente(
                        self._cid, situacao=("Fala interrompida" if dados.get("servico") == "voz"
                                            else "Consulta interrompida" if dados.get("servico") == "ferramenta"
                                            else "Conexão interrompida"))
            except Exception as e:  # noqa: BLE001
                _log(f"não consegui registrar o ponto da tarefa: {e}")
        # Registra os comentários de processo ("peraí, deixa eu ver") pra
        # TIRÁ-LOS da resposta salva — senão o histórico guardaria o preâmbulo
        # colado na resposta ("...aquiTá ligada"), o mesmo embolamento que a
        # tela agora evita. 'inicio' zera pro turno novo.
        if fase == "inicio":
            self._falas_processo = []
            self._resposta_crua = ""
            self._fontes_pesquisa_turno = []
            self._resposta_fontes = []
            self._filtro_tags_stream.resetar()
            trava = getattr(self, "_lock_stream_visual_voz", None)
            if trava is None:
                trava = self._lock_stream_visual_voz = threading.Lock()
            with trava:
                self._stream_visual_voz = ""
                self._stream_visual_voz_indice = 0
                self._stream_visual_voz_ativo = False
                self._stream_visual_voz_sem_audio = False
        elif fase == "erro_conexao" and dados.get("servico") == "voz":
            trava = getattr(self, "_lock_stream_visual_voz", None)
            if trava is not None:
                with trava:
                    self._stream_visual_voz_sem_audio = True
                    prefixo = self._stream_visual_voz
                    self._stream_visual_voz_ativo = False
                if prefixo:
                    # Prefixo cumulativo evita repetir o que o áudio já revelou.
                    self._push("status", {"estado": "falando", "texto": "", "texto_prefixo": prefixo})
        elif fase == "fala" and dados.get("texto"):
            self._falas_processo.append(str(dados["texto"]))
        elif fase == "delta" and dados.get("texto"):
            # O TTS continua na fila de frases completas. Em canal de voz o JS
            # guarda estes deltas como fonte fiel (markdown/quebras), mas só
            # revela o prefixo quando o callback de `falando` avisa que aquela
            # unidade começou a tocar.
            visivel = self._filtro_tags_stream.alimentar(str(dados["texto"]))
            if visivel:
                if dados.get("acompanhar_fala") and not getattr(self, "_stream_visual_voz_sem_audio", False):
                    trava = getattr(self, "_lock_stream_visual_voz", None)
                    if trava is None:
                        trava = self._lock_stream_visual_voz = threading.Lock()
                    with trava:
                        self._stream_visual_voz_ativo = True
                        self._stream_visual_voz += visivel
                else:
                    self._push("delta", {"texto": visivel})
            return
        elif fase == "resposta":
            # Antes de resetar, finalize o filtro pra liberar qualquer texto
            # pendente (ex: "[referência" sem "]" no último delta). O resetar()
            # descarta, causando texto cortado na tela.
            pendente = self._filtro_tags_stream.alimentar("", finalizar=True)
            if pendente and not dados.get("acompanhar_fala"):
                self._push("delta", {"texto": pendente})
            # O JS reescreve a bolha com o texto final completo; não permita que
            # um prefixo incompleto retido neste turno alcance o próximo.
            self._filtro_tags_stream.resetar()
            trava = getattr(self, "_lock_stream_visual_voz", None)
            if trava is not None:
                with trava:
                    # A resposta final logo abaixo já contém TODO o texto fiel,
                    # com Markdown e quebras de linha. Antes, este buffer era
                    # reenviado como `delta` DEPOIS de `resposta`: o JS encerrava
                    # a bolha bonita e o delta tardio abria outra, achatada pela
                    # fala, que só sumia ao reabrir o chat pelo histórico.
                    self._stream_visual_voz = ""
                    self._stream_visual_voz_indice = 0
                    self._stream_visual_voz_ativo = False
            # O texto CRU e final da resposta. É a versão boa: preserva quebras
            # de linha e cercas de código (```), que a fala frase-a-frase perde.
            # Vira a fonte da verdade pra SALVAR e pra reescrever a bolha com
            # código colorido de verdade.
            self._resposta_crua = _tirar_falas_de_processo(
                dados.get("texto") or "", self._falas_processo)
            self._resposta_fontes = list(
                dados["fontes"] if "fontes" in dados
                else getattr(self, "_fontes_pesquisa_turno", []))
            resposta_visual = {
                "texto": _texto_visual_sem_tags_de_voz(self._resposta_crua),
            }
            if self._resposta_fontes:
                resposta_visual["fontes"] = self._resposta_fontes
            self._push("resposta", resposta_visual)
            return
        if fase == "resultado":
            if dados.get("nome") == "pesquisar_internet" and dados.get("ok", True):
                try:
                    import pesquisa
                    existentes = list(getattr(self, "_fontes_pesquisa_turno", []))
                    urls = {item["url"] for item in existentes}
                    for fonte in pesquisa.extrair_fontes_do_resultado(
                            str(dados.get("resultado") or "")):
                        if fonte["url"] not in urls:
                            existentes.append(fonte)
                            urls.add(fonte["url"])
                    self._fontes_pesquisa_turno = existentes[:16]
                except Exception as e:  # noqa: BLE001
                    _log(f"fontes da pesquisa: {e}")
            # A resposta completa já foi entregue ao modelo. A tela exibe só
            # uma prévia curta; enviar dezenas de KB para evaluate_js pode
            # perder justamente o evento que encerra a etapa visual.
            dados = dict(dados)
            dados["resultado"] = str(dados.get("resultado") or "")[:500]
        self._push("progresso", {"fase": fase, "dados": dados})

    def add_mensagem_emily(self, texto: str) -> None:
        if texto and texto.strip():
            self._push("msg", {
                "autor": "emily",
                "texto": _texto_visual_sem_tags_de_voz(texto.strip()),
            })

    def add_mensagem_usuario(self, texto: str) -> None:
        """Mostra uma transcrição de voz usando a mesma bolha do chat escrito."""
        if texto and texto.strip():
            self._push("msg", {"autor": "user", "texto": texto.strip()})

    def carregar_historico(self, mensagens: list) -> None:
        for m in mensagens or []:
            papel = m.get("role") or m.get("papel") or ""
            texto = (m.get("content") or m.get("texto") or "").strip()
            if not texto:
                continue
            self._push("msg", {"autor": "emily" if papel in ("assistant", "emily") else "user",
                               "texto": texto})

    # ── BANDEJA (tray) ─────────────────────────────────────────────
    # X da janela esconde; o ícone da bandeja traz de volta e é o único
    # lugar com "Sair de verdade" — igual Discord/Steam. O KDE Plasma tem
    # bandeja nativa (StatusNotifier); o pystray fala com ela via
    # libappindicator (que já vem no Fedora).

    def _pedir_saida_editor_android(self, modo):
        manager=getattr(getattr(self,"_editor_api",None),"_android_editor",None)
        if not manager or not manager.open:return False
        manager.close_main_mode=modo
        manager.window.show();manager.window.restore()
        def ask():
            try:manager.window.evaluate_js("window.AndroidEditor?.requestClose()")
            except Exception:pass
        threading.Thread(target=ask,daemon=True).start()
        return True

    def _ao_tentar_fechar(self) -> bool:
        """Evento closing da janela. False = CANCELA o fechamento."""
        if self._pedir_saida_editor_android("hide"):return False
        if getattr(self, "_editor_dirty", False) and not getattr(self, "_editor_close_authorized", False):
            self._pedir_saida_editor(False)
            return False
        if self._sair_de_verdade:
            return True   # saída legítima (tray → Sair): deixa fechar
        try:
            self._janela.hide()
            self._visivel = False
        except Exception as e:  # noqa: BLE001
            _log(f"esconder no fechamento falhou: {e}")
        _log("janela escondida pra bandeja — a Emily continua rodando "
             "(sair de verdade: ícone da bandeja → Sair de verdade)")
        return False

    def _criar_tray(self) -> None:
        try:
            import pystray
            from PIL import Image
        except Exception as e:  # noqa: BLE001
            _log(f"bandeja indisponível ({e}); fechar vai encerrar de verdade")
            return
        try:
            icone = None
            candidatos = [os.path.join(DIR_BASE, "emilyimage.png"),
                          os.path.join(DIR_BASE, "emily.gif")]
            if os.name == "nt":
                candidatos.insert(0, os.path.join(DIR_BASE, "installer", "emily.ico"))
            for candidato in candidatos:
                if os.path.isfile(candidato):
                    with Image.open(candidato) as imagem:
                        icone = imagem.convert("RGBA")
                    break
            if icone is None:
                _log("bandeja sem ícone (emilyimage.png não achado); desligada")
                return
            menu = pystray.Menu(
                pystray.MenuItem("Abrir a Emily", self._tray_mostrar,
                                 default=True),
                pystray.MenuItem("Sair de verdade", self._tray_sair),
            )
            self._tray = pystray.Icon("Emily", icone, "Emily", menu)
            threading.Thread(target=self._tray.run_detached, daemon=True,
                             name="emily-tray").start()
            _log("bandeja de pé — ícone ao lado do relógio; fechar a janela "
                 "agora só esconde")
        except Exception as e:  # noqa: BLE001
            _log(f"bandeja não subiu ({e}); fechar vai encerrar de verdade")
            self._tray = None

    def _tray_mostrar(self, icon=None, item=None) -> None:
        if self._janela is None:
            return
        try:
            self._janela.show()
            self._janela.restore()
            self._visivel = True
        except Exception as e:  # noqa: BLE001
            _log(f"tray mostrar: {e}")

    def _pedir_saida_editor(self, encerrar: bool) -> None:
        # Não esperar evaluate_js dentro do evento nativo closing: GTK pode
        # travar a thread de UI. Estado é espelhado pela ponte e a decisão é async.
        self._tray_mostrar()
        self._push("editor_pedir_saida", {"encerrar": encerrar})

    def _tray_sair(self, icon=None, item=None) -> None:
        """Saída REAL, pedida pelo menu da bandeja."""
        if self._pedir_saida_editor_android("exit"):return
        if getattr(self, "_editor_dirty", False) and not getattr(self, "_editor_close_authorized", False):
            self._pedir_saida_editor(True)
            return
        assistant=getattr(getattr(self, '_editor_api', None), '_editor_ai', None)
        if assistant and (assistant.state().get('job') or {}).get('running'):
            self._push('toast', {'texto':'Espere a tarefa do editor terminar ou cancele no mini chat antes de fechar.', 'tipo':'erro'})
            return
        _log("saída de verdade pedida pela bandeja")
        try:
            api = getattr(self, "_editor_api", None)
            if api and api._editor_panel_window is not None:
                api._editor_panel_window.events.closing -= api._editor_panel_close_handler
                api._editor_panel_window.destroy()
        except Exception:
            pass
        self._sair_de_verdade = True
        try:
            if self._tray is not None:
                self._tray.stop()
        except Exception:
            pass
        try:
            if self._janela is not None:
                self._janela.destroy()
        except Exception:
            pass
        # Rede de segurança: o destroy acorda o webview.start(), que faz
        # os._exit(0). Se por qualquer razão não acordar, sai aqui.
        threading.Timer(3.0, lambda: os._exit(0)).start()

    def toggle_visible(self) -> None:
        """
        Mostra ou esconde a janela principal.

        É o que o clique DIREITO no sprite faz — o mesmo comportamento da
        interface antiga. O pywebview não diz de forma confiável se a janela
        está visível, então o estado é rastreado aqui: escondeu, mostra;
        mostrou, esconde e traz pra frente.
        """
        if self._janela is None:
            return
        try:
            if getattr(self, "_visivel", True):
                self._janela.hide()
                self._visivel = False
            else:
                self._janela.show()
                self._janela.restore()
                self._visivel = True
        except Exception as e:  # noqa: BLE001
            _log(f"toggle_visible: {e}")

    # ── Apoio ─────────────────────────────────────────────────────

    @staticmethod
    def _chamar_cb(fn: Callable, *args) -> None:
        """Roda um callback do main.py sem deixar exceção subir pra thread."""
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            _log(f"callback {getattr(fn, '__name__', fn)} falhou: {type(e).__name__}: {e}")

    def _registrar_na_conversa(self, papel: str, texto: str,
                              fontes: list = None, requisicao_id: str = "", anexos: list = None) -> None:
        if getattr(self, "sem_registro_remoto", False):
            return   # turno remoto: a conversa é do dispositivo que digitou
        try:
            import modo_demo
            if modo_demo.ativo():
                self._cid = modo_demo.acrescentar_conversa(self._cid, papel, texto)
                if papel == "emily":
                    self._push("mensagem_persistida", {
                        "cid": self._cid,
                        "indice": len(modo_demo.abrir_conversa(self._cid)) - 1})
                return
        except Exception as e:  # noqa: BLE001
            _log(f"registrar na conversa demo: {e}")
            return
        try:
            import conversas
            if not self._cid:
                self._cid = conversas.criar(texto if papel == "user" else "")
            indice = conversas.acrescentar(
                self._cid, papel, texto, fontes=fontes,
                requisicao_id=requisicao_id, anexos=anexos)
            if papel == "emily" and indice is not None:
                self._push("mensagem_persistida", {"cid": self._cid, "indice": indice})
        except Exception as e:  # noqa: BLE001
            _log(f"registrar na conversa: {e}")

    def _titular(self, cid: str, primeira: str) -> None:
        """
        Título de verdade pra conversa nova, feito por LLM.

        Roda em thread, na rota mais barata que existe e com orçamento de
        token minúsculo: é enfeite, não pode custar latência de resposta nem
        atrapalhar se falhar. Se falhar, o corte antigo continua valendo.
        """
        titulo_llm = None
        try:
            import conversas
            atual = next((c for c in conversas.listar() if c.get("id") == cid), None)
            if not atual:
                _log(f"_titular: conversa {cid} nao encontrada em listar()")
                return
            esperado = conversas.titulo_de(primeira)
            if atual.get("titulo") != esperado:
                return  # renomeada manualmente ou sincronizada enquanto aguardava

            import modelo
            _log("_titular: chamando LLM...")
            bruto = modelo.chamar_llm_simples(
                "Resuma o assunto desta mensagem em no máximo 4 palavras, em "
                "português, sem ponto final, sem aspas e sem explicar nada:\n\n"
                f"{primeira[:400]}",
                max_tokens=24,
                rota=modelo.ROTA_TITULO,
            )
            _log(f"_titular: LLM respondeu {repr(bruto)}")
            titulo_llm = " ".join((bruto or "").split()).strip(' ."\'').strip()
            if not titulo_llm or len(titulo_llm) > 48 or _titulo_e_id_modelo(titulo_llm):
                _log(f"_titular: titulo invalido, pulando")
                titulo_llm = None
        except Exception as e:  # noqa: BLE001
            _log(f"_titular: {e}")
            titulo_llm = None

        if titulo_llm:
            try:
                import conversas
                conversas.renomear_se_titulo(cid, esperado, titulo_llm)
            except Exception as e:  # noqa: BLE001
                _log(f"_titular: erro ao renomear: {e}")

        # NOTIFICA a interface pra repintar a sidebar, mesmo que o LLM tenha
        # falhado — o título do conversas.acrescentar (corte mecânico) já está
        # salvo e precisa aparecer. Sem este push, a sidebar mantém o título
        # antigo até o próximo recarregarConversas().
        try:
            self._push("conversas", {})
        except Exception as e:  # noqa: BLE001
            _log(f"_titular: erro no push: {e}")

    def _encerrar(self) -> None:
        """Fecha a janela. O atexit do main.py cuida do resto do desligamento."""
        demo_estava_ativo = False
        try:
            import navegador_interno
            navegador_interno.encerrar()
        except Exception as e:  # noqa: BLE001
            _log(f"navegador interno: falha ao fechar ({e})")
        try:
            import agente_ui
            agente_ui.remover_ouvinte_agente_ui(self._ouvinte_agente_ui)
        except Exception:
            pass
        try:
            import modo_demo
            demo_estava_ativo = modo_demo.ativo()
            modo_demo.encerrar()
        except Exception:
            pass
        try:
            import conversas
            # Não deixa uma conversa vazia pra trás na saída.
            if not demo_estava_ativo and self._cid and conversas.vazia(self._cid):
                conversas.apagar(self._cid)
        except Exception:
            pass
        try:
            if self._httpd is not None:
                self._httpd.shutdown()
                self._httpd.server_close()
        except Exception:
            pass
        # Derruba o sprite junto: processo órfão fica de bonequinho na tela
        # depois que a Emily fecha.
        try:
            self._parar_sprite()
        except Exception:
            pass
        try:
            if self._janela is not None:
                self._janela.destroy()
        except Exception as e:  # noqa: BLE001
            _log(f"encerrar: {e}")

    # ── Boot ──────────────────────────────────────────────────────

    def _escurecer_titulo(self) -> None:
        """
        Pinta a barra de título NATIVA de escuro, pra combinar com o tema.

        Sem isto, a moldura do Windows fica clara e destoa do resto. Usa o DWM:
        modo escuro (Win10+) e, quando dá, a cor exata da barra (Win11). É só
        cosmético — se qualquer chamada falhar, a janela funciona igual, só com
        a barra clara.
        """
        try:
            import ctypes
            hwnd = int(self._janela.native.Handle.ToInt64())
            dwm = ctypes.windll.dwmapi
            # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 nas builds novas, 19 nas antigas.
            for attr in (20, 19):
                v = ctypes.c_int(1)
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
            # DWMWA_CAPTION_COLOR (Win11 22000+): cor exata, em 0x00BBGGRR.
            # #1c1b19 -> R=1c G=1b B=19 -> 0x00191B1C
            cor = ctypes.c_int(0x00191B1C)
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cor), ctypes.sizeof(cor))
        except Exception as e:  # noqa: BLE001
            _log(f"não escureci a barra de título (segue clara): {e}")

    def iniciar(self) -> None:
        """
        Abre a janela e BLOQUEIA até fechar, igual ao app.exec() do Qt.

        O main.py chama isto no fim, depois de subir voz, Discord, automação e
        os laços. Por isso tudo que aparece na tela antes daqui fica na fila do
        _push e é soltado quando a WebView responde.
        """
        import webview

        indice = os.path.join(DIR_WEB, "index.html")
        if not os.path.isfile(indice):
            raise FileNotFoundError(
                f"não achei a interface em {indice}. A pasta web/ tem que estar "
                f"ao lado do interface_web.py.")

        # A interface é servida por SERVIDOR HTTP LOCAL em http://localhost,
        # nunca por file:// nem html=. Dois motivos medidos em produção:
        #
        # 1. CACHE FANTASMA: a WebView2 com file:// persiste a página em
        #    .webview/ e servia o HTML antigo mesmo após invalidação — o
        #    Vitor via a interface de 3 dias atrás.
        #
        # 2. ERRO 153 DO YOUTUBE (jul/2025): o player embedado do YouTube
        #    exige HTTP Referer de uma origem http válida. Servido por file://
        #    ou html=, o player entra em buffering eterno com onError=153 e
        #    nenhuma música toca. Em http://localhost o embed carrega e toca
        #    — testado com reprodução real (estado=1, tempo avançando).
        #
        # O index.html referencia estilo.css e app.js como arquivos relativos;
        # servidos pelo handler abaixo, eles são lidos DO DISCO a cada request
        # (sem cache HTTP), então mudanças aparecem ao reabrir a janela.

        class _Handler(http.server.SimpleHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def __init__(self, *a, **k):
                super().__init__(*a, directory=DIR_WEB, **k)

            def end_headers(self):
                # Sem cache nenhum: a próxima abertura da janela relê tudo.
                self.send_header("Cache-Control", "no-store")
                super().end_headers()

            def _cloud_media(self, somente_cabecalho: bool = False) -> bool:
                caminho_url = urlsplit(self.path).path
                prefixo = "/__emily_cloud_content/"
                if not caminho_url.startswith(prefixo):
                    return False
                try:
                    from emily_cloud import core
                    item_id = unquote(caminho_url[len(prefixo):])
                    item = core.detalhes(item_id)
                    caminho = core.caminho_conteudo(item_id)
                    tamanho = caminho.stat().st_size
                    inicio, fim, status = 0, max(0, tamanho - 1), 200
                    faixa = self.headers.get("Range", "")
                    if faixa:
                        match = re.fullmatch(r"bytes=(\d*)-(\d*)", faixa.strip())
                        if not match or tamanho <= 0:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{tamanho}")
                            self.end_headers()
                            return True
                        a, b = match.groups()
                        if not a:
                            quantidade = min(int(b or 0), tamanho)
                            inicio, fim = tamanho - quantidade, tamanho - 1
                        else:
                            inicio = int(a)
                            fim = min(int(b) if b else tamanho - 1, tamanho - 1)
                        if inicio > fim or inicio >= tamanho:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{tamanho}")
                            self.end_headers()
                            return True
                        status = 206
                    comprimento = max(0, fim - inicio + 1)
                    self.send_response(status)
                    self.send_header("Content-Type", item.get("mime") or "application/octet-stream")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(comprimento))
                    self.send_header("Content-Disposition", "inline")
                    if status == 206:
                        self.send_header("Content-Range", f"bytes {inicio}-{fim}/{tamanho}")
                    self.end_headers()
                    if not somente_cabecalho and comprimento:
                        restante = comprimento
                        with caminho.open("rb") as arquivo:
                            arquivo.seek(inicio)
                            while restante:
                                bloco = arquivo.read(min(256 * 1024, restante))
                                if not bloco:
                                    break
                                self.wfile.write(bloco)
                                restante -= len(bloco)
                    return True
                except (BrokenPipeError, ConnectionResetError):
                    return True
                except Exception as e:  # noqa: BLE001
                    self.send_error(404, str(e))
                    return True

            def do_GET(self):
                import music_offline
                if not music_offline.servir(self, False) and not self._cloud_media(False):
                    super().do_GET()

            def do_HEAD(self):
                import music_offline
                if not music_offline.servir(self, True) and not self._cloud_media(True):
                    super().do_HEAD()

            def log_message(self, *a):
                pass

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        try:
            self._httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
            self._httpd.daemon_threads = True
        except OSError as e:
            raise ErroUI(f"não consegui abrir porta local pra interface: {e}")
        porta = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        _log(f"http local da interface: http://localhost:{porta}")

        api = Api(self)
        self._janela = webview.create_window(
            "Emily",
            f"http://localhost:{porta}/index.html",
            js_api=api,
            width=1180, height=780,
            min_size=(560, 520),
            # Moldura NATIVA do Windows: é o que dá mover a janela, redimensionar
            # pelas bordas e arrastar de um monitor pro outro "igual às janelas
            # normais". O backend EdgeChromium do pywebview NÃO redimensiona nem
            # move janela frameless (o easy_drag e o resize de borda só existem
            # nos outros backends), então frameless deixaria a janela presa —
            # foi por isso que ela não mexia. resizable é o default.
            resizable=True,
            hidden=self._iniciar_oculta,
            background_color="#1c1b19",
            text_select=True,
        )
        # X da janela = esconder pra bandeja (o "Sair de verdade" é no tray).
        self._janela.events.closing += self._ao_tentar_fechar
        self._criar_tray()

        def _quando_abrir():
            # Espera o app.js registrar o window.Emily antes de despejar a
            # fila. Teto folgado (30s) porque boot frio da WebView2 numa
            # máquina ocupada passa fácil de 6s — e um teto curto aqui fazia
            # os primeiros eventos saírem antes da tela existir e virarem
            # erro silencioso no console.
            achou = False
            for _ in range(600):
                try:
                    if self._avaliar_js("!!window.Emily"):
                        achou = True
                        break
                except Exception:
                    pass
                time.sleep(0.05)
            if not achou:
                _log("a tela não respondeu em 30s; seguindo mesmo assim")
            # Diagnóstico do music player: prova o que a janela REAL carregou.
            # Se o Vitor não vê o botão, este log diz se o HTML é o velho.
            try:
                diagnostico_ui = self._avaliar_js(
                    "JSON.stringify({btnMusic: "
                    "!!document.getElementById('btn-music'), "
                    "htmlModificado: document.lastModified})")
                _log(f"diagnóstico da UI: {diagnostico_ui}")
            except Exception:
                pass
            self._escurecer_titulo()
            self._pronta.set()
            self._push("avatar", {"url": self._avatar})
            estado, texto = self._ultimo_status
            self._push("status", {"estado": estado, "texto": texto})
            try:
                import agente_ui
                self._push("agente_ui", agente_ui.estado_agente_ui())
            except Exception as e:  # noqa: BLE001
                _log(f"agente_ui: não publiquei estado inicial ({e})")
            self._drenar_fila()
            _log("interface web de pé")
            # O sprite sobe depois da janela: o clique direito nele precisa
            # de uma janela pra mostrar/esconder.
            self._visivel = True
            self._iniciar_sprite()

        # private_mode=True: SEM disco de cache nenhum. Foi a última peça do
        # quebra-cabeça do cache fantasma — com private_mode=False a WebView2
        # restaurava a SESSÃO inteira (HTML velho incluído) do .webview/ mesmo
        # recebendo html= novo por string. Tudo que a interface precisa é
        # re-servido pelo Python a cada boot; nada aqui depende de cache.
        # gui="edgechromium" só existe no Windows — no Linux forçar isso dava
        # fallback silencioso; deixar None deixa o pywebview escolher o
        # backend certo (GTK/WebKit2 do sistema, o que roda de verdade aqui).
        import platform_compat as _pc
        _gui = "edgechromium" if _pc.is_windows() else None
        webview.start(_quando_abrir, debug=os.getenv("EMILY_UI_DEBUG", "0") == "1",
                      gui=_gui, private_mode=True)

        # Sair do webview.start() significa janela fechada: encerra o processo
        # como o sys.exit(app.exec()) do Qt fazia.
        _log("janela fechada")
        os._exit(0)


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
# `python interface_web.py` abre a interface sozinha, sem subir a Emily.
# Serve pra mexer no design sem esperar voz, Discord e automação.
# ═════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    j = JanelaEmily(callback_texto=lambda t: print(f"[demo] recebi: {t!r}"))

    def _demo():
        time.sleep(2.5)
        j.atualizar_status("pensando", "Pensando…")
        time.sleep(1.2)
        j.progresso_evento("ferramenta", {"nome": "ver_tela", "args": {"pergunta": "o que tem aí"}})
        time.sleep(1.0)
        j.progresso_evento("resultado", {"nome": "ver_tela",
                                         "resultado": "A tela mostra o VS Code com um erro na linha 12."})
        time.sleep(0.6)
        j.progresso_evento("fim", {})
        for frase in ("Ó,", "achei o problema:", "falta importar o módulo na linha 12.",
                      "Quer que eu conserte?"):
            j.atualizar_status("falando", frase)
            time.sleep(0.7)
        j.atualizar_status("aguardando")

    threading.Thread(target=_demo, daemon=True).start()
    j.iniciar()

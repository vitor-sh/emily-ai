"""Regressões do protocolo visual compartilhado entre voz e chat escrito."""

from __future__ import annotations

import ast
import queue
import sys
import threading
import time
from types import SimpleNamespace
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent


def _funcao(nome: str) -> ast.FunctionDef:
    arvore = ast.parse((RAIZ / "main.py").read_text(encoding="utf-8"))
    return next(no for no in arvore.body if isinstance(no, ast.FunctionDef) and no.name == nome)


def test_executor_compartilhado_emite_protocolo_completo():
    fonte = ast.unparse(_funcao("_executar_turno_com_ferramentas"))
    assert "janela.progresso_evento('inicio', {})" in fonte
    assert "on_progresso=janela.progresso_evento" in fonte
    assert "janela.progresso_evento('resposta', {'texto': resposta_final})" in fonte
    assert "voz.falar_stream" in fonte


def test_anexos_usam_progresso_e_laco_de_ferramentas():
    fonte = ast.unparse(_funcao("processar_arquivos_chat"))
    assert "janela.progresso_evento('inicio', {})" in fonte
    assert "on_progresso=janela.progresso_evento" in fonte
    assert "janela.progresso_evento('resposta', {'texto': resposta})" in fonte
    assert "janela.progresso_evento('fim', {})" in fonte


def test_voz_escolhe_rota_do_pc_e_finaliza_painel():
    fonte = ast.unparse(_funcao("rodar_emily"))
    chamada = "_executar_turno_voz_pc(entrada)"
    assert chamada in fonte
    assert fonte.index("_registrar_entrada_voz_no_chat(entrada)") < fonte.index(chamada)
    assert fonte.count("_registrar_entrada_voz_no_chat(entrada)") == 1
    assert "janela.progresso_evento('fim', {})" in fonte


def test_interfaces_expoem_mensagem_publica_do_usuario():
    for arquivo in ("interface_web.py", "interface.py"):
        fonte = (RAIZ / arquivo).read_text(encoding="utf-8")
        assert "def add_mensagem_usuario(" in fonte


def test_frontend_fecha_estado_transitorio_apos_resposta_final():
    fonte = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
    inicio = fonte.index("function emilyRespostaFinal(texto, fontes = [])")
    fim = fonte.index("function digitando(", inicio)
    funcao = fonte[inicio:fim]
    assert "ESTADO.emilyAberta = null" in funcao
    assert "ESTADO.ditoNoCartao = ''" in funcao
    assert "ESTADO.falasProcesso = []" in funcao
    assert "const todas = $$('.msg.de-emily')" not in funcao


def test_resposta_final_remove_atualizacao_intermediaria_sem_embolar():
    sys.path.insert(0, str(RAIZ))
    from interface_web import _tirar_falas_de_processo

    resposta = "Já vou verificar. Agora foi: o vídeo está baixando em 720p."
    assert _tirar_falas_de_processo(resposta, ["Já vou verificar."]) == (
        "Agora foi: o vídeo está baixando em 720p."
    )


def test_executor_entrega_ferramenta_e_resumo_final_em_ordem():
    eventos = []
    status = []
    memorias = []

    class JanelaFalsa:
        def progresso_evento(self, fase, dados):
            eventos.append((fase, dict(dados)))

        def atualizar_status(self, estado, texto):
            status.append((estado, texto))

    janela = JanelaFalsa()

    def conversar(texto, callback, fila_frases, on_progresso, canal):
        assert texto == "baixa esse vídeo"
        assert canal == "voz"
        on_progresso("fala", {"texto": "Já vou verificar."})
        fila_frases.put("Já vou verificar.")
        on_progresso("ferramenta", {"nome": "listar_midias_da_aba", "args": {}})
        on_progresso("resultado", {
            "nome": "listar_midias_da_aba", "resultado": "1 vídeo", "ok": True,
        })
        fila_frases.put("Agora foi: está baixando em 720p.")
        fila_frases.put(None)
        return "Já vou verificar. Agora foi: está baixando em 720p."

    def falar_stream(fila_frases, callback, on_progresso=None):
        assert on_progresso is janela.progresso_evento or callable(on_progresso)
        while True:
            frase = fila_frases.get(timeout=1)
            if frase is None:
                return
            callback(frase)

    globais = {
        "queue": queue,
        "threading": threading,
        "janela": janela,
        "modelo": SimpleNamespace(
            conversar_com_ferramentas=conversar,
            _memoria_unificada_ativa=lambda: False,
        ),
        "voz": SimpleNamespace(falar_stream=falar_stream),
        "discord_bot": SimpleNamespace(atualizar_status_discord=lambda *_: None),
        "memoria": SimpleNamespace(
            processar_conversa_async=lambda pergunta, resposta: memorias.append((pergunta, resposta))
        ),
    }
    modulo = ast.Module(body=[_funcao("_executar_turno_com_ferramentas")], type_ignores=[])
    exec(compile(ast.fix_missing_locations(modulo), "<turno-voz>", "exec"), globais)

    resposta = globais["_executar_turno_com_ferramentas"]("baixa esse vídeo", "voz")
    assert [fase for fase, _ in eventos] == [
        "inicio", "fala", "ferramenta", "resultado", "resposta",
    ]
    assert status == [
        ("falando", "Já vou verificar."),
        ("falando", "Agora foi: está baixando em 720p."),
    ]
    assert resposta.endswith("Agora foi: está baixando em 720p.")
    assert memorias == [("baixa esse vídeo", resposta)]


def test_acumulador_nao_cria_microaudio_em_reticencia_e_virgula():
    """A abertura da captura não pode virar áudios curtos separados e frear."""
    sys.path.insert(0, str(RAIZ))
    import modelo

    texto = (
        "[speaking thoughtfully] É, eu imagino... quando você tá com tudo isso "
        "na cabeça, qualquer mensagem dela vira um gatilho, né? "
        "Fica aquele peso, aquela ansiedade. Mas olha, você tá conseguindo "
        "responder normal e empurrar por enquanto... já é um avanço."
    )
    fila = queue.Queue()
    acumulador = modelo._AcumuladorDeFrases(fila)
    for inicio in range(0, len(texto), 7):
        acumulador.adicionar(texto[inicio:inicio + 7])
    acumulador.finalizar()

    frases = []
    while not fila.empty():
        frases.append(fila.get_nowait())

    assert frases
    assert frases[0].endswith("né?")
    assert "É, eu imagino... quando você" in frases[0]
    assert all(len(frase) >= 50 for frase in frases[:-1])
    assert len(frases) <= 3, frases


def test_falar_stream_prefetch_paralelo_mantem_ordem(monkeypatch):
    """Próximos áudios podem sintetizar juntos, mas fala/legenda não reordenam."""
    sys.path.insert(0, str(RAIZ))
    import voz

    voz.mudo.clear()
    voz.parar_fala.clear()
    monkeypatch.delenv("EMILY_TTS_WEBSOCKET", raising=False)
    monkeypatch.setenv("EMILY_TTS_TRANSPORTE", "prefetch")
    monkeypatch.setenv("EMILY_TTS_PREFETCH", "2")
    monkeypatch.setattr(voz, "_sessao_fish_da_thread", lambda: object())

    trava = threading.Lock()
    ativos = 0
    pico = 0
    iniciou = []

    def gerar(frase, _sessao=None):
        nonlocal ativos, pico
        with trava:
            ativos += 1
            pico = max(pico, ativos)
            iniciou.append(frase)
        # A primeira demora mais: as outras precisam terminar antes dela sem
        # conseguir furar a ordem do player.
        time.sleep(0.06 if frase == "primeira" else 0.02)
        with trava:
            ativos -= 1
        return (frase.encode(), 44100, 1, 2)

    vistas = []
    tocadas = []
    monkeypatch.setattr(voz, "_gerar_audio_pacote", gerar)
    monkeypatch.setattr(voz, "_notificar_audio", lambda *_a: None)
    monkeypatch.setattr(voz.discord_bot, "tocar_pcm_discord", lambda *_a: None)
    monkeypatch.setattr(voz, "_tocar_bytes", lambda pcm: tocadas.append(pcm.decode()))

    fila = queue.Queue()
    for frase in ("primeira", "segunda", "terceira"):
        fila.put(frase)
    fila.put(None)

    voz.falar_stream(fila, vistas.append)

    assert pico >= 2, f"não houve prefetch paralelo: iniciou={iniciou}"
    assert vistas == ["primeira", "segunda", "terceira"]
    assert tocadas == vistas


def test_falar_stream_websocket_envia_frases_e_toca_chunks(monkeypatch):
    """O caminho novo entrega frases ao WS e áudio ao player sem esperar o fim."""
    sys.path.insert(0, str(RAIZ))
    import voz

    voz.mudo.clear()
    voz.parar_fala.clear()
    monkeypatch.delenv("EMILY_TTS_WEBSOCKET", raising=False)
    monkeypatch.setenv("EMILY_TTS_TRANSPORTE", "websocket")
    textos_enviados = []
    escritos = []
    status = []
    notificados = []

    class SessaoWSFalsa:
        def __init__(self, *_a, **_kw):
            pass

        def tts(self, request, text_stream, backend=None):
            assert request.format == "pcm"
            assert request.text == ""
            assert backend
            for texto in text_stream:
                textos_enviados.append(texto)
                yield b"\x01\x00\x02\x00"

        def close(self):
            pass

    class SaidaFalsa:
        def __init__(self, texto=""):
            self.texto = texto

        def escrever(self, pedaco, taxa, canais, largura=2):
            escritos.append((pedaco, taxa, canais, largura))

        def fechar(self):
            pass

    monkeypatch.setattr(voz, "WebSocketSession", SessaoWSFalsa)
    monkeypatch.setattr(voz, "_SaidaPCMIncremental", SaidaFalsa)
    monkeypatch.setattr(voz, "_aplicar_volume", lambda pcm, _largura=None: pcm)
    monkeypatch.setattr(
        voz, "_notificar_audio", lambda texto, pcm: notificados.append((texto, pcm)))

    fila = queue.Queue()
    fila.put("Primeira frase.")
    fila.put("Segunda frase!")
    fila.put(None)

    voz.falar_stream(fila, status.append)

    assert status == ["Primeira frase.", "Segunda frase!"]
    assert textos_enviados == ["Primeira frase. ", "Segunda frase! "]
    assert b"".join(item[0] for item in escritos) == (
        b"\x01\x00\x02\x00" * 2)
    assert notificados == [(
        "Primeira frase. Segunda frase!",
        b"\x01\x00\x02\x00" * 2,
    )]


def test_falar_stream_http_toca_primeiro_chunk_sem_esperar_frase_completa(monkeypatch):
    """O padrão toca chunks na chegada e mantém a ordem entre as frases."""
    sys.path.insert(0, str(RAIZ))
    import voz

    voz.mudo.clear()
    voz.parar_fala.clear()
    monkeypatch.delenv("EMILY_TTS_WEBSOCKET", raising=False)
    monkeypatch.setenv("EMILY_TTS_TRANSPORTE", "http")
    monkeypatch.setenv("EMILY_TTS_PREFETCH", "2")

    liberou_final = threading.Event()
    primeiro_tocado = threading.Event()
    status = []
    tocados = []
    notificados = []

    def gerar(frase, **_kwargs):
        yield (frase[0] * 2).encode()
        if frase.startswith("Primeira"):
            liberou_final.wait(timeout=1)
        yield (frase[-2] * 2).encode()

    class SaidaFalsa:
        def __init__(self, _texto=""):
            pass

        def escrever(self, pedaco, *_formato):
            tocados.append(pedaco)
            primeiro_tocado.set()

        def fechar(self):
            pass

    monkeypatch.setattr(voz, "gerar_audio_stream", gerar)
    monkeypatch.setattr(voz, "_SaidaPCMIncremental", SaidaFalsa)
    monkeypatch.setattr(
        voz, "_notificar_audio", lambda texto, pcm: notificados.append((texto, pcm)))

    fila = queue.Queue()
    fila.put("Primeira.")
    fila.put("Segunda!")
    fila.put(None)
    terminou = threading.Event()
    worker = threading.Thread(
        target=lambda: (voz.falar_stream(fila, status.append), terminou.set()),
        daemon=True,
    )
    worker.start()

    assert primeiro_tocado.wait(timeout=1)
    assert not terminou.is_set(), "esperou a frase inteira antes de tocar"
    assert status == ["Primeira."]
    liberou_final.set()
    worker.join(timeout=2)

    assert terminou.is_set()
    assert status == ["Primeira.", "Segunda!"]
    assert tocados == [b"PP", b"aa", b"SS", b"aa"]
    assert notificados == [
        ("Primeira.", b"PPaa"),
        ("Segunda!", b"SSaa"),
    ]

# ── Retry/timeout da síntese Fish ────────────────────────────────────────
# O SDK da Fish nasce com httpx.Client(timeout=None): um stall do servidor
# (throttle do tier free) pendurava a síntese por dezenas de segundos e a
# fila de áudio secava — texto e voz congelavam juntos, porque a legenda só
# avança quando o áudio começa a tocar.


def _wav_falso() -> bytes:
    import io as _io
    import wave as _wave

    buf = _io.BytesIO()
    with _wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b"\x00\x00" * 2205)  # 50ms de silêncio
    return buf.getvalue()


def test_gerar_audio_pacote_retenta_apos_falha_e_recupera(monkeypatch, capsys):
    """Falha pontual no stream não pode custar a frase nem travar a fila."""
    sys.path.insert(0, str(RAIZ))
    import voz

    wav = _wav_falso()
    chamadas = {"n": 0}

    class SessaoFalsa:
        def tts(self, req, backend=None):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise RuntimeError("Read timed out (stall do servidor)")
            return iter([wav])

    sessao = SessaoFalsa()
    monkeypatch.setattr(voz, "_sessao_fish_da_thread", lambda: sessao)
    monkeypatch.setenv("EMILY_TTS_TENTATIVAS", "2")
    monkeypatch.setenv("EMILY_TTS_PAUSA_RETRY", "0")

    pcm, taxa, canais, largura = voz._gerar_audio_pacote("Olá do teste.", sessao)

    assert chamadas["n"] == 2
    assert pcm == b"\x00\x00" * 2205
    assert (taxa, canais, largura) == (44100, 1, 2)
    saida = capsys.readouterr().out
    assert "[TTS-RETRY] tentativa 1/2" in saida
    assert "tentativa=2" in saida


def test_gerar_audio_pacote_esgota_tentativas_e_devolve_vazio(monkeypatch, capsys):
    """Stall persistente termina em áudio vazio rápido, não em pendura eterna."""
    sys.path.insert(0, str(RAIZ))
    import voz

    chamadas = {"n": 0}

    class SessaoFalsa:
        def tts(self, req, backend=None):
            chamadas["n"] += 1
            raise RuntimeError("Read timed out (stall do servidor)")

    sessao = SessaoFalsa()
    monkeypatch.setattr(voz, "_sessao_fish_da_thread", lambda: sessao)
    monkeypatch.setenv("EMILY_TTS_TENTATIVAS", "2")
    monkeypatch.setenv("EMILY_TTS_PAUSA_RETRY", "0")

    pcm, _taxa, _canais, _largura = voz._gerar_audio_pacote("Olá do teste.", sessao)

    assert chamadas["n"] == 2
    assert pcm == b""
    saida = capsys.readouterr().out
    assert saida.count("[TTS-RETRY]") == 2
    assert "Erro Fish Audio" in saida


def test_call_entrega_tags_e_parametros_exclusivos_ao_fish(monkeypatch):
    """A call preserva comandos inline e aplica prosódia/sampling próprios."""
    sys.path.insert(0, str(RAIZ))
    import voz

    wav = _wav_falso()
    vistos = []

    class SessaoFalsa:
        def tts(self, req, backend=None):
            vistos.append(req)
            return iter([wav])

    monkeypatch.setenv("EMILY_CALL_FISH_SPEED", "1.25")
    monkeypatch.setenv("EMILY_CALL_FISH_VOLUME", "3.5")
    monkeypatch.setenv("EMILY_CALL_FISH_TEMPERATURE", "0.82")
    monkeypatch.setenv("EMILY_CALL_FISH_TOP_P", "0.64")

    pcm, *_ = voz._gerar_audio_pacote(
        "[whisper] Segredo da call.", SessaoFalsa(), para_call=True)

    assert pcm
    req = vistos[0]
    assert req.text.startswith("[whispering]")
    assert req.prosody.speed == 1.25
    assert req.prosody.volume == 3.5
    assert req.temperature == 0.82
    assert req.top_p == 0.64


def test_parametros_fish_da_call_sao_limitados_e_nao_afetam_outros_fluxos(monkeypatch):
    """Env inválida não derruba o SDK e prosódia da call não vaza pro TTS normal."""
    sys.path.insert(0, str(RAIZ))
    import voz

    wav = _wav_falso()
    vistos = []

    class SessaoFalsa:
        def tts(self, req, backend=None):
            vistos.append(req)
            return iter([wav])

    monkeypatch.setenv("EMILY_CALL_FISH_SPEED", "99")
    monkeypatch.setenv("EMILY_CALL_FISH_VOLUME", "-99")
    monkeypatch.setenv("EMILY_CALL_FISH_TEMPERATURE", "banana")
    monkeypatch.setenv("EMILY_CALL_FISH_TOP_P", "2")

    voz._gerar_audio_pacote("call", SessaoFalsa(), para_call=True)
    voz._gerar_audio_pacote("normal", SessaoFalsa())

    call, normal = vistos
    assert call.prosody.speed == 2.0
    assert call.prosody.volume == -20.0
    assert call.temperature == 0.7
    assert call.top_p == 1.0
    assert normal.prosody is None
    assert normal.temperature == 0.7
    assert normal.top_p == 0.7


def test_segmentacao_da_call_carrega_tom_mas_nao_repete_evento():
    """Cada request independente herda o tom; pause/laughs continuam pontuais."""
    sys.path.insert(0, str(RAIZ))
    import voz

    texto = (
        "[whisper] Esta primeira frase é comprida o bastante para formar uma "
        "unidade completa e manter um segredo. "
        "[pause] Esta segunda frase também é longa o bastante para virar outro "
        "segmento independente do Fish Audio."
    )
    partes = voz.segmentar_para_tts(texto, preservar_entonacao=True)

    assert len(partes) >= 2
    assert partes[0].startswith("[whispering]")
    assert partes[1].startswith("[whispering]")
    assert partes[1].count("[pause]") == 1


def test_cliente_fish_recebe_timeout_de_leitura(monkeypatch):
    """O teto de leitura é o que impede a síntese de pendurar sem limite."""
    sys.path.insert(0, str(RAIZ))
    import voz
    from types import SimpleNamespace as _Ns

    fake = _Ns(_sync_client=_Ns(timeout=None))
    monkeypatch.setenv("EMILY_TTS_TIMEOUT_LEITURA", "12.5")
    monkeypatch.setenv("EMILY_TTS_TIMEOUT_CONEXAO", "3.5")

    voz._aplicar_timeout_fish(fake)

    t = fake._sync_client.timeout
    assert t.read == 12.5
    assert t.connect == 3.5


def test_sessoes_fish_aplicam_timeout_na_criacao():
    """Tanto a sessão global quanto a por-thread nascem com teto de tempo."""
    fonte = (RAIZ / "voz.py").read_text(encoding="utf-8")
    assert "_aplicar_timeout_fish(Session(FISH_AUDIO_KEY))" in fonte
    arvore = ast.parse(fonte)
    atribuicao = next(n for n in arvore.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_session_fish' for t in n.targets))
    valor = atribuicao.value.body if isinstance(atribuicao.value, ast.IfExp) else atribuicao.value
    assert isinstance(valor, ast.Call) and isinstance(valor.func, ast.Name) and valor.func.id == '_aplicar_timeout_fish' 


def test_filtro_libera_texto_pendente_ao_finalizar():
    """Texto entre colchetes incompleto no último delta não pode sumir."""
    sys.path.insert(0, str(RAIZ))
    import interface_web

    filtro = interface_web._FiltroStreamingTagsDeVoz()
    
    # Simula stream que termina com colchete aberto
    r1 = filtro.alimentar("Texto normal [refe")
    assert r1 == "Texto normal "  # '[refe' fica pendente
    
    # Finalizar deve liberar o pendente
    pendente = filtro.alimentar("", finalizar=True)
    assert pendente == "[refe", f"Esperava '[refe', mas recebeu {pendente!r}"


def test_progresso_evento_resposta_libera_pendente_antes_de_resetar(monkeypatch):
    """O evento 'resposta' deve finalizar o filtro antes de resetar."""
    sys.path.insert(0, str(RAIZ))
    import interface_web

    eventos = []
    ponte = interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    ponte._filtro_tags_stream = interface_web._FiltroStreamingTagsDeVoz()
    ponte._falas_processo = []
    ponte._resposta_crua = ""
    ponte._lock_stream_visual_voz = None
    ponte._push = lambda evento, dados: eventos.append((evento, dict(dados)))

    # Alimenta o filtro com texto que termina incompleto
    ponte._filtro_tags_stream.alimentar("Resposta com [ref")

    # Simula o progresso_evento chamado pelo modelo
    ponte.progresso_evento("resposta", {"texto": "Resposta com [ref"})

    # Deve ter enviado o pendente como delta antes da resposta final
    assert len(eventos) == 2, f"Esperava 2 eventos, recebeu {len(eventos)}: {eventos}"
    assert eventos[0][0] == "delta"
    assert eventos[0][1]["texto"] == "[ref"
    assert eventos[1][0] == "resposta"

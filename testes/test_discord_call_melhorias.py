"""Regressões das melhorias de latência, contexto e iniciativa da call."""

from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace


RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def _turno(texto: str, uid: int = 111, nome: str = "Vitor"):
    agora = time.monotonic()
    return SimpleNamespace(
        texto=texto, user_id=uid, nome=nome,
        inicio=agora, fim=agora,
    )


def _reset_resto(resto_call):
    resto_call._est.ligado = True
    resto_call._est.silenciada = False
    resto_call._est.falando = False
    resto_call._est.mudo_ate = 0.0
    resto_call._est.ultima_resposta_em = 0.0
    resto_call._est.conversa.clear()
    resto_call._est.calou_seguidas.clear()
    resto_call._limpar_lote()
    resto_call._esvaziar_fila()
    resto_call._iniciativas_hora.clear()


def test_escuta_call_varias_pessoas_transcrevem_sem_fila_crescente(monkeypatch, capsys):
    """Um STT lento não segura os outros; histórico segue ordem da fala."""
    import escuta_call

    fila = queue.Queue(maxsize=60)
    historico = []
    parar = threading.Event()
    iniciou_antiga = threading.Event()
    liberar_antiga = threading.Event()
    observados = []
    agora = time.monotonic()
    turnos = [
        escuta_call.Turno(i, f"Pessoa {i}", agora + i, agora + i,
                          pcm=str(i).encode(), fechado_em=agora + i)
        for i in range(4)
    ]

    def transcrever(pcm):
        if pcm == b"0":
            iniciou_antiga.set()
            assert liberar_antiga.wait(3), "worker antigo ficou bloqueado"
        return f"fala {pcm.decode()}"

    monkeypatch.setattr(escuta_call, "_fila", fila)
    monkeypatch.setattr(escuta_call, "_historico", historico)
    monkeypatch.setattr(escuta_call, "_parar", parar)
    monkeypatch.setattr(escuta_call, "_observadores", [observados.append])
    monkeypatch.setattr(escuta_call, "transcrever", transcrever)
    workers = [threading.Thread(target=escuta_call._trabalhar, daemon=True)
               for _ in range(4)]
    for worker in workers:
        worker.start()
    try:
        fila.put(turnos[0])
        assert iniciou_antiga.wait(2)
        for turno in turnos[1:]:
            fila.put(turno)
        limite = time.monotonic() + 2
        while len(observados) < 3 and time.monotonic() < limite:
            time.sleep(0.01)
        assert {t.user_id for t in observados} == {1, 2, 3}
        assert fila.qsize() == 0
        liberar_antiga.set()
        limite = time.monotonic() + 2
        while fila.unfinished_tasks and time.monotonic() < limite:
            time.sleep(0.01)
        assert fila.unfinished_tasks == 0
        assert [t.user_id for t in historico] == [0, 1, 2, 3]
        assert all(not t.pcm for t in historico)
        assert "fila_stt=" in capsys.readouterr().out
    finally:
        liberar_antiga.set()
        parar.set()
        for worker in workers:
            worker.join(timeout=1)


def test_pipe_pcm_discord_drena_chunks_antes_do_eof():
    """Fechar o produtor não pode apagar áudio que ainda está na fila do FFmpeg."""
    import discord_bot

    pipe = discord_bot._PipePCMDiscord()
    pipe.write(b"primeiro")
    pipe.write(b"segundo")
    pipe.close()

    recebido = bytearray()
    while True:
        pedaco = pipe.read(5)
        if not pedaco:
            break
        recebido.extend(pedaco)

    assert bytes(recebido) == b"primeirosegundo"


def test_player_discord_nao_compensa_pausa_do_fish_acelerando_voz():
    """Quando FFmpeg aguarda Fish, read() não pode bloquear AudioPlayer."""
    import discord_bot

    chegou = threading.Event()
    liberar = threading.Event()
    primeiro = bytes([1]) * 3840
    segundo = bytes([2]) * 3840

    class FFmpegFalso:
        def __init__(self):
            self._indice = 0

        def read(self):
            self._indice += 1
            if self._indice == 1:
                return primeiro
            if self._indice == 3:
                return b""
            chegou.set()
            liberar.wait(timeout=2)
            return segundo if liberar.is_set() else b""

        def cleanup(self):
            liberar.set()

    fonte = discord_bot._FontePCMTempoReal(FFmpegFalso())
    try:
        assert chegou.wait(timeout=2)
        assert fonte.read() == primeiro
        inicio = time.monotonic()
        assert fonte.read() == bytes(3840)
        assert time.monotonic() - inicio < 0.05
        liberar.set()
        for _ in range(100):
            if fonte._terminou.is_set():
                break
            time.sleep(0.005)
        assert fonte._terminou.is_set()
        assert fonte.read() == segundo  # último quadro não se perde no EOF
        assert fonte.read() == b""
        assert fonte.is_opus() is False
    finally:
        fonte.cleanup()


def test_player_discord_ffmpeg_real_preserva_duracao_pcm():
    """FFmpeg real converte o PCM sem perder quadros ou reduzir sua duração."""
    import discord
    import discord_bot

    pipe = discord_bot._PipePCMDiscord()
    ffmpeg = discord.FFmpegPCMAudio(
        pipe, pipe=True, before_options="-f s16le -ar 48000 -ac 2",
        options="-vn")
    fonte = discord_bot._FontePCMTempoReal(ffmpeg)
    try:
        # 1 segundo PCM16 estéreo: exatamente 50 quadros de 20ms do Discord.
        pipe.write(b"\x01\x00" * (48000 * 2))
        pipe.close()
        quadros = []
        limite = time.monotonic() + 4
        while time.monotonic() < limite:
            quadro = fonte.read()
            if not quadro:
                break
            quadros.append(quadro)
            time.sleep(0.02)
        assert fonte._terminou.is_set()
        assert sum(quadro != bytes(3840) for quadro in quadros) == 50
        assert all(len(quadro) == 3840 for quadro in quadros)
    finally:
        pipe.close()
        fonte.cleanup()


def test_caminho_rapido_da_call_define_dono_e_entrega_contexto(monkeypatch):
    import discord_admin
    import discord_bot
    import modelo
    import perfil_discord

    dono_id = 1195765414400106626
    membro = SimpleNamespace(id=dono_id, bot=False)
    guild = SimpleNamespace(
        id=10, name="Servidor", get_member=lambda uid: membro if uid == dono_id else None)
    canal = SimpleNamespace(id=20, name="call", guild=guild, members=[membro])
    voice = SimpleNamespace(is_connected=lambda: True, channel=canal)

    capturado = {}
    monkeypatch.setattr(discord_bot, "_voice_client", voice)
    monkeypatch.setattr(discord_bot, "_config", {"usuario_id": dono_id})
    monkeypatch.setattr(discord_bot, "_memoria_dono",
                        lambda eh_dono, uid: "vitor" if eh_dono else f"discord:{uid}")
    # Este teste valida especificamente o caminho RÁPIDO. Não pode depender da
    # preferência persistida do usuário, que pode legitimamente estar ligada.
    monkeypatch.setattr(modelo, "autonomia_experimental_ativa", lambda: False)
    monkeypatch.setattr(discord_admin, "parece_pedido_de_admin", lambda *_a, **_k: False)
    monkeypatch.setattr(perfil_discord, "contexto_de_membros",
                        lambda *_a, **_k: "[perfil dos membros]")

    def responder(**kwargs):
        capturado.update(kwargs)
        return {"responder": True, "resposta": "oi", "detalhe_texto": ""}

    monkeypatch.setattr(modelo, "responder_na_call", responder)

    resultado = discord_bot._pensar_na_call(
        dono_id, "Vitor", "Emily, o que você acha?", "Amigo: assunto",
        quem_na_call="Vitor, Amigo")

    assert resultado["responder"] is True
    assert capturado["dono_user_id"] == "vitor"
    assert capturado["contexto_membros"] == "[perfil dos membros]"
    assert capturado["nome_quem_falou"] == "Vitor"
    assert capturado["quem_esta_na_call"] == "Vitor, Amigo"


def test_fish_fica_exclusivo_da_call_e_some_da_escrita():
    import modelo

    assert "<controle_de_voz_fish_audio>" not in modelo.EMILY_PERSONALIDADE
    assert "<controle_de_voz_fish_audio>" not in modelo._personalidade_discord(False)
    assert "<controle_de_voz_fish_audio>" in modelo._personalidade_discord(True)

    escrito = "[excited] **Achei!** Veja [1] e [documentação]."
    assert modelo.remover_tags_fish(escrito) == "**Achei!** Veja [1] e [documentação]."
    assert modelo.quebrar_resposta_discord(escrito)[0].startswith("**Achei!**")


def test_pesquisa_na_call_roteia_para_ferramentas_inclusive_de_terceiro(monkeypatch):
    import discord_admin
    import discord_bot
    import modelo
    import perfil_discord

    uid = 222
    membro = SimpleNamespace(id=uid, bot=False)
    guild = SimpleNamespace(
        id=10, name="Servidor", get_member=lambda procurado: membro if procurado == uid else None)
    canal = SimpleNamespace(id=20, name="call", guild=guild, members=[membro])
    voice = SimpleNamespace(is_connected=lambda: True, channel=canal)
    capturado = {}

    monkeypatch.setattr(discord_bot, "_voice_client", voice)
    monkeypatch.setattr(discord_bot, "_config", {"usuario_id": 999})
    monkeypatch.setattr(discord_bot, "_memoria_dono",
                        lambda eh_dono, user_id: f"discord:{user_id}")
    monkeypatch.setattr(discord_admin, "parece_pedido_de_admin", lambda *_a, **_k: False)
    monkeypatch.setattr(discord_admin, "nivel_do_membro",
                        lambda *_a, **_k: discord_admin.NIVEL_NENHUM)
    monkeypatch.setattr(discord_admin, "definir_sessao", lambda **_kw: None)
    monkeypatch.setattr(discord_admin, "limpar_sessao", lambda: None)
    monkeypatch.setattr(perfil_discord, "contexto_de_membros", lambda *_a, **_k: "")

    def responder(**kwargs):
        capturado.update(kwargs)
        return modelo.ResultadoDiscord(texto="[curious] Achei a resposta.", agiu=False)

    monkeypatch.setattr(modelo, "responder_discord_com_ferramentas", responder)

    resultado = discord_bot._pensar_na_call(
        uid, "Ana", "Emily, pesquisa as notícias desse jogo", "", quem_na_call="Ana")

    assert capturado["falada_na_call"] is True
    assert capturado["eh_dono"] is False
    assert capturado["parece_acao"] is True
    assert resultado["resposta"].startswith("[curious]")


def test_catalogo_publico_da_call_tem_pesquisa_sem_expor_pc(monkeypatch):
    import ferramentas
    import llm
    import modelo

    chamadas = {}
    esquema_discord = {"type": "function", "function": {
        "name": "listar_canais_discord", "description": "x",
        "parameters": {"type": "object", "properties": {}, "required": []}}}
    esquema_pesquisa = {"type": "function", "function": {
        "name": "pesquisar_internet", "description": "x",
        "parameters": {"type": "object", "properties": {}, "required": []}}}

    def esquemas(grupos=None):
        chamadas["grupos"] = grupos
        return [esquema_discord]

    def por_nome(nomes):
        chamadas["nomes"] = nomes
        return [esquema_pesquisa]

    monkeypatch.setattr(ferramentas, "esquemas", esquemas)
    monkeypatch.setattr(ferramentas, "esquemas_por_nome", por_nome)
    monkeypatch.setattr(llm, "chamar_com_ferramentas", lambda *_a, **_k: SimpleNamespace(
        texto="[confident] Resultado pesquisado.", chamadas=[]))

    resultado = modelo.responder_discord_com_ferramentas(
        mensagem="pesquisa isso", nome_autor="Ana", nome_servidor="S",
        nome_canal="call", nivel="nenhum", eh_dono=False,
        parece_acao=False, falada_na_call=True)

    assert chamadas["grupos"] == ["discord"]
    assert chamadas["nomes"] == ["pesquisar_internet", "hora_atual"]
    assert resultado.texto.startswith("[confident]")


def test_lote_adaptativo_e_continuacao_de_emily_curta(monkeypatch):
    import resto_call

    _reset_resto(resto_call)
    resto_call._ao_ouvir_turno(_turno("Emily?"))
    with resto_call._lote_trava:
        assert len(resto_call._lote) == 1
        assert resto_call._janela_do_lote(resto_call._lote) == resto_call.LOTE_JANELA_CURTA

    # A continuação não repete o nome, mas precisa entrar no lote aberto.
    resto_call._ao_ouvir_turno(_turno("O que você acha desse jogo?"))
    with resto_call._lote_trava:
        assert len(resto_call._lote) == 2
        assert resto_call._lote[1][1] is True
        assert resto_call._janela_do_lote(resto_call._lote) == resto_call.LOTE_JANELA_DIRETA

    resto_call._limpar_lote()
    resto_call._est.ligado = False


def test_fala_longa_da_call_sintetiza_em_paralelo_e_toca_em_ordem(monkeypatch):
    import resto_call

    _reset_resto(resto_call)
    monkeypatch.setattr(resto_call, "TTS_PREFETCH_CALL", 2)
    monkeypatch.setattr(resto_call, "_segmentos_de_fala",
                        lambda _texto: ["primeira", "segunda", "terceira"])

    trava = threading.Lock()
    ativos = 0
    pico = 0

    def gerar(parte):
        nonlocal ativos, pico
        with trava:
            ativos += 1
            pico = max(pico, ativos)
        time.sleep(0.06 if parte == "primeira" else 0.02)
        with trava:
            ativos -= 1
        return parte.encode(), 44100, 1

    tocadas = []
    monkeypatch.setattr(resto_call, "_gerar_voz_segmento", gerar)
    monkeypatch.setattr(resto_call, "_tocar_na_call",
                        lambda pcm, _taxa, _canais: tocadas.append(pcm.decode()) or True)

    assert resto_call._falar_na_call("resposta longa") is True
    assert pico >= 2
    assert tocadas == ["primeira", "segunda", "terceira"]
    assert resto_call._est.falando is False


def test_contexto_da_call_usa_janela_ampliada(monkeypatch):
    import escuta_call
    import resto_call

    _reset_resto(resto_call)
    recebido = {}

    def transcricao(segundos, limite):
        recebido.update(segundos=segundos, limite=limite)
        return "Vitor: Emily, fala aí"

    monkeypatch.setattr(escuta_call, "transcricao_recente", transcricao)
    monkeypatch.setattr(resto_call, "_pensar", lambda **_kw: {
        "responder": False, "resposta": "", "detalhe_texto": ""})

    resto_call._responder(_turno("Emily, fala aí"), False)

    assert recebido == {
        "segundos": resto_call.CONTEXTO_SEGUNDOS,
        "limite": resto_call.CONTEXTO_LINHAS,
    }


def test_limite_da_call_e_flexivel_e_pode_ser_desligado(monkeypatch):
    import modelo

    texto = " ".join(f"palavra{i}" for i in range(70))
    monkeypatch.setattr(modelo, "_MAX_PALAVRAS_CALL", 120)
    assert modelo.encurtar_para_call(texto) == (texto, "")

    monkeypatch.setattr(modelo, "_MAX_PALAVRAS_CALL", 0)
    texto_maior = " ".join(f"item{i}" for i in range(300))
    assert modelo.encurtar_para_call(texto_maior) == (texto_maior, "")

    # Sem pontuação também corta sem duplicar no detalhe escrito.
    monkeypatch.setattr(modelo, "_MAX_PALAVRAS_CALL", 12)
    fala, resto = modelo.encurtar_para_call(texto)
    assert len(fala.split()) == 12
    assert fala.split() + resto.split() == texto.split()


def test_iniciativa_respeita_contexto_orcamento_e_cancela_por_atividade(monkeypatch):
    import escuta_call
    import llm
    import resto_call

    _reset_resto(resto_call)
    agora = time.monotonic()
    turnos = [
        escuta_call.Turno(1, "Ana", agora - 8, agora - 8, texto="esse jogo é lindo"),
        escuta_call.Turno(2, "Bia", agora - 7, agora - 7, texto="a trilha é melhor ainda"),
        escuta_call.Turno(1, "Ana", agora - 6, agora - 6, texto="o chefe me destruiu"),
        escuta_call.Turno(2, "Bia", agora - 5, agora - 5, texto="aquela fase é cruel"),
    ]
    monkeypatch.setattr(escuta_call, "turnos_recentes", lambda **_kw: turnos)
    monkeypatch.setattr(llm, "folga_da_rota", lambda _rota: 99)
    monkeypatch.setattr(resto_call, "INICIATIVA_ATIVA", True)
    monkeypatch.setattr(resto_call, "INICIATIVA_CHANCE", 1.0)
    monkeypatch.setattr(resto_call, "INICIATIVA_MAX_HORA", 2)
    monkeypatch.setattr(resto_call, "INICIATIVA_MIN_TURNOS", 4)
    monkeypatch.setattr(resto_call, "INICIATIVA_PAUSA", 0.0)
    monkeypatch.setattr(resto_call, "INICIATIVA_COOLDOWN", 0.0)
    monkeypatch.setattr(resto_call, "_quem_esta_na_call", lambda: "Ana, Bia")
    monkeypatch.setattr(resto_call, "_pensar_espontaneo",
                        lambda transcricao, quem: "esse chefe é um desgraçado mesmo")
    falas = []
    monkeypatch.setattr(resto_call, "_falar_na_call",
                        lambda texto, **_kw: falas.append(texto) or True)

    resto_call._atividade_seq = 10
    resto_call._iniciativa_avaliada_seq = -1
    resto_call._ultima_atividade = agora - 10
    assert resto_call._tentar_iniciativa() is True
    assert falas == ["esse chefe é um desgraçado mesmo"]
    assert resto_call._est.espontaneas >= 1

    # O mesmo bloco nunca é reavaliado; uma chamada real também cancela.
    assert resto_call._tentar_iniciativa() is False
    resto_call._atividade_seq += 1
    resto_call._ultima_atividade = time.monotonic()
    resto_call._fila.put((_turno("Emily?"), False))
    try:
        assert resto_call._tentar_iniciativa() is False
    finally:
        resto_call._esvaziar_fila()
        resto_call._est.ligado = False

def test_eof_entre_consulta_da_fila_e_evento_preserva_ultimo_quadro():
    import queue
    import threading
    import discord_bot
    fonte = discord_bot._FontePCMTempoReal.__new__(discord_bot._FontePCMTempoReal)
    fonte._terminou = threading.Event()
    fonte._fechada = threading.Event()
    quadro = b"\x01\x00" * 1920
    class FilaNaChegadaDoEOF(queue.Queue):
        primeira = True
        def get_nowait(self):
            if self.primeira:
                self.primeira = False
                self.put(quadro)
                fonte._terminou.set()
                raise queue.Empty
            return super().get_nowait()
    fonte._fonte = None
    fonte._quadros = FilaNaChegadaDoEOF()
    assert fonte.read() == quadro
    assert fonte.read() == b""

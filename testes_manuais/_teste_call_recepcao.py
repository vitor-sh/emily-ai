"""
Confere que ela nao fica surda pra sempre quando a recepcao de audio cai.

O caso: o Discord derruba a conexao de voz (erro 4006, troca de regiao). O
AudioReader morre ou fica orfao. A flag _escutando continua True, o
comecar_a_ouvir responde "Ja estou ouvindo" e nunca reanexa. Silencio total,
sem log, ate reiniciar o processo.

Aqui a conexao de voz e dublada, porque o que se testa e a DECISAO de reanexar,
nao o Discord.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import asyncio
import sys
import threading
import traceback

falhas = []


def ok(rotulo, cond, extra=""):
    if not cond:
        falhas.append(rotulo)
    print(f"  {'ok   ' if cond else 'FALHA'} {rotulo}" + (f"  {extra}" if extra else ""))


def secao(t):
    print("\n" + "-" * 68)
    print(t)
    print("-" * 68)


import escuta_call
from discord.ext import voice_recv


class LeitorSocketFalso(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._callbacks = []
        self._vivo = True
        self.start()

    def run(self):
        while self._vivo:
            import time
            time.sleep(0.05)

    def matar(self):
        self._vivo = False


class ConexaoFalsa:
    def __init__(self):
        self._socket_reader = LeitorSocketFalso()


class ReaderFalso:
    """Imita o AudioReader, INCLUSIVE o finally do roteador que chama
    voice_client.stop_listening() ao terminar."""

    def __init__(self, conexao, voice_client):
        self.active = True
        self.callback = lambda *a: None
        self.voice_client = voice_client
        conexao._socket_reader._callbacks.append(self.callback)

    def is_listening(self):
        return self.active

    def stop(self):
        self.active = False
        # É ISTO que o voice_recv faz de verdade: uma thread separada termina e,
        # num finally, chama stop_listening() no voice_client — que a essa altura
        # pode já estar com um reader NOVO pendurado. Ver router.py:103.
        threading.Thread(target=self._finally_do_roteador, daemon=True).start()

    def _finally_do_roteador(self):
        import time as _t
        _t.sleep(0.15)          # o atraso que torna isso uma corrida
        try:
            self.voice_client.stop_listening()
        except Exception:
            pass


class CanalFalso:
    def __init__(self, cid=555):
        self.id = cid
        self.name = "Pv"


class VCFalso(voice_recv.VoiceRecvClient):
    """Anda como um VoiceRecvClient sem tocar em rede nenhuma."""

    def __init__(self):
        self._conectado = True
        self._reader = None
        self._connection = ConexaoFalsa()
        self.channel = CanalFalso()
        self.sink_recebido = None

    def is_connected(self):
        return self._conectado

    def is_listening(self):
        return bool(self._reader and self._reader.is_listening())

    def listen(self, sink, *, after=None):
        if self.is_listening():
            raise RuntimeError("Already receiving audio.")
        self.sink_recebido = sink
        self._reader = ReaderFalso(self._connection, self)

    def stop_listening(self):
        if self._reader:
            self._reader.stop()
            self._reader = None

    # --- as duas quedas que o Discord provoca de verdade ---
    def cair_reader(self):
        """Erro 4006: a thread do reader morre."""
        if self._reader:
            self._reader.active = False

    def trocar_conexao(self):
        """Reconexao: a conexao e substituida e o reader fica orfao,
        mas continua respondendo is_listening() == True."""
        self._connection._socket_reader.matar()
        self._connection = ConexaoFalsa()


def limpar():
    escuta_call.parar_de_ouvir()
    escuta_call._escutando = False
    escuta_call._vc = None
    escuta_call._sink = None
    escuta_call.contas.zerar()


secao("1. comecar_a_ouvir pendura o sink")
try:
    limpar()
    vc = VCFalso()
    recado = asyncio.run(escuta_call.comecar_a_ouvir(vc))
    print(f"  {recado}")
    ok("disse que esta ouvindo", "ouvindo a call" in recado)
    ok("o sink foi pendurado", vc.sink_recebido is not None)
    ok("escutando() = True", escuta_call.escutando() is True)
    ok("pretendo_ouvir() = True", escuta_call.pretendo_ouvir() is True)
except Exception:
    falhas.append("anexar")
    traceback.print_exc()

secao("2. chamar de novo com tudo vivo NAO reanexa (nao perde turnos)")
try:
    sink_antes = vc.sink_recebido
    recado = asyncio.run(escuta_call.comecar_a_ouvir(vc))
    ok("respondeu 'ja estou ouvindo'", "Já estou ouvindo" in recado, recado)
    ok("manteve o mesmo sink", vc.sink_recebido is sink_antes)
    ok("nao contou reanexo", escuta_call.contas.reanexos == 0)
except Exception:
    falhas.append("idempotente")
    traceback.print_exc()

secao("3. o reader morre (erro 4006): detectado pela API publica")
try:
    vc.cair_reader()
    ok("escutando() passa a dizer NAO", escuta_call.escutando() is False)
    ok("mas pretendo_ouvir() segue True (o vigia vai consertar)",
       escuta_call.pretendo_ouvir() is True)
    est = escuta_call.estado()
    ok("o estado admite o problema em vez de mentir",
       "ACHO QUE SIM, MAS NÃO ESTOU" in est)
    print("      " + est.splitlines()[0])
except Exception:
    falhas.append("detecta reader morto")
    traceback.print_exc()

secao("4. e comecar_a_ouvir REANEXA em vez de dizer 'ja estou ouvindo'")
try:
    sink_antes = vc.sink_recebido
    recado = asyncio.run(escuta_call.comecar_a_ouvir(vc))
    print(f"  {recado}")
    ok("nao respondeu 'ja estou ouvindo'", "Já estou ouvindo" not in recado)
    ok("penduro um sink NOVO", vc.sink_recebido is not sink_antes)
    ok("voltou a ouvir de verdade", escuta_call.escutando() is True)
except Exception:
    falhas.append("reanexa")
    traceback.print_exc()

secao("5. conexao substituida NAO conta mais como defeito")
try:
    ok("antes da troca, esta viva", escuta_call.escutando() is True)
    vc.trocar_conexao()
    # A checagem profunda que detectava isso foi REMOVIDA de proposito: ela dava
    # falso negativo com o audio funcionando, e cada falso negativo destruia os
    # turnos em andamento. Ver o comentario do _recepcao_viva.
    ok("is_listening() do cliente diz True", vc.is_listening() is True)
    ok("e escutando() acompanha a API publica",
       escuta_call.escutando() is True)
except Exception:
    falhas.append("conexao trocada")
    traceback.print_exc()

secao("6. o vigia reanexa sozinho quando is_listening() cai")
try:
    import time
    limpar()
    # Vigia rapido SO nesta secao: nas anteriores um vigia rapido consertaria a
    # queda antes das conferencias, e o que la se testa e a deteccao.
    escuta_call.INTERVALO_VIGIA = 0.4
    vc = VCFalso()
    asyncio.run(escuta_call.comecar_a_ouvir(vc))
    sink_antes = vc.sink_recebido

    vc.cair_reader()             # queda de verdade, na API publica
    ok("caiu", escuta_call.escutando() is False)

    esperou = 0.0
    # Espera pela CONDICAO, nao pelo contador: o vigia incrementa
    # contas.reanexos ANTES de chamar _anexar, entao olhar o contador deixava
    # esta conferencia vencer no intervalo entre contar e de fato reanexar — o
    # teste passava ou falhava conforme a sorte do escalonador.
    while esperou < 4.0 and vc.sink_recebido is sink_antes:
        time.sleep(0.2)
        esperou += 0.2

    ok("o vigia reanexou sozinho", escuta_call.contas.reanexos >= 1,
       f"reanexos={escuta_call.contas.reanexos} em {esperou:.1f}s")
    ok("com um sink novo", vc.sink_recebido is not sink_antes)
    ok("e voltou a ouvir", escuta_call.escutando() is True)
except Exception:
    falhas.append("vigia")
    traceback.print_exc()

secao("7. trocar de canal (vc novo) tambem reanexa")
try:
    limpar()
    vc1 = VCFalso()
    asyncio.run(escuta_call.comecar_a_ouvir(vc1))
    vc2 = VCFalso()              # entrou de novo, cliente novo
    recado = asyncio.run(escuta_call.comecar_a_ouvir(vc2))
    ok("nao disse 'ja estou ouvindo'", "Já estou ouvindo" not in recado)
    ok("o sink foi pro cliente NOVO", vc2.sink_recebido is not None)
    ok("escutando() aponta pro novo", escuta_call.escutando() is True)
except Exception:
    falhas.append("cliente novo")
    traceback.print_exc()

secao("8. estado() diz ha quanto tempo chegou pacote")
try:
    limpar()
    vc = VCFalso()
    asyncio.run(escuta_call.comecar_a_ouvir(vc))
    est = escuta_call.estado()
    ok("avisa que NENHUM pacote chegou ainda",
       "NENHUM desde que comecei a ouvir" in est)
    escuta_call.contas.ultimo_pacote = __import__("time").monotonic()
    est = escuta_call.estado()
    ok("depois de um pacote, mostra a idade dele",
       "Último pacote de áudio: há 0s" in est)
except Exception:
    falhas.append("estado")
    traceback.print_exc()

secao("9. O LACO DO VIGIA: silencio de call NAO e defeito")
try:
    import time
    limpar()
    escuta_call.INTERVALO_VIGIA = 0.3
    vc = VCFalso()
    asyncio.run(escuta_call.comecar_a_ouvir(vc))
    sink_antes = vc.sink_recebido

    # Este e o caso EXATO da call do Vitor: recepcao viva, ninguem falando ha
    # meio minuto porque estavam jogando. Antes isso reanexava de 30 em 30s.
    escuta_call.contas.ultimo_pacote = time.monotonic() - 45.0

    time.sleep(1.6)          # varias voltas do vigia
    ok("45s sem ninguem falar NAO reanexa",
       escuta_call.contas.reanexos == 0,
       f"reanexos={escuta_call.contas.reanexos}")
    ok("e o sink nao foi destruido", vc.sink_recebido is sink_antes)

    # Nem cinco minutos, que numa call de jogo tambem acontece.
    escuta_call.contas.ultimo_pacote = time.monotonic() - 300.0
    time.sleep(1.0)
    ok("5 min sem ninguem falar tambem nao reanexa",
       escuta_call.contas.reanexos == 0,
       f"reanexos={escuta_call.contas.reanexos}")
    ok("e o sink continua o mesmo", vc.sink_recebido is sink_antes)
except Exception:
    falhas.append("silencio de call")
    traceback.print_exc()

secao("10. silencio EXTREMO com recepcao 'viva' ainda vale uma tentativa")
try:
    import time
    limpar()
    escuta_call.INTERVALO_VIGIA = 0.3
    escuta_call.SILENCIO_SUSPEITO = 600.0
    vc = VCFalso()
    asyncio.run(escuta_call.comecar_a_ouvir(vc))
    escuta_call.contas.ultimo_pacote = time.monotonic() - 900.0   # 15 min

    time.sleep(1.6)
    ok("15 min sem pacote nenhum aciona a rede de seguranca",
       escuta_call.contas.reanexos >= 1,
       f"reanexos={escuta_call.contas.reanexos}")
except Exception:
    falhas.append("silencio extremo")
    traceback.print_exc()

secao("11. prova age na hora; indicio espera confirmar")
try:
    import time
    # is_listening() = nao e PROVA (API publica, sem falso positivo), entao o
    # vigia age na primeira checagem: cada segundo esperando e alguem falando e
    # nao sendo ouvido. Silencio longo e INDICIO, e espera duas.
    limpar()
    escuta_call.INTERVALO_VIGIA = 0.3
    vc = VCFalso()
    asyncio.run(escuta_call.comecar_a_ouvir(vc))
    escuta_call.contas.ultimo_pacote = time.monotonic()

    vc.cair_reader()         # is_listening() = False: defeito comprovado
    time.sleep(0.5)          # tempo pra UMA checagem
    ok("com prova, age na primeira checagem",
       escuta_call.contas.reanexos >= 1,
       f"reanexos={escuta_call.contas.reanexos}")
    ok("e conserta", escuta_call.escutando() is True)

    # Agora o caminho do indicio: recepcao viva, silencio muito longo.
    limpar()
    escuta_call.INTERVALO_VIGIA = 0.3
    escuta_call.SILENCIO_SUSPEITO = 600.0
    vc = VCFalso()
    asyncio.run(escuta_call.comecar_a_ouvir(vc))
    escuta_call.contas.ultimo_pacote = time.monotonic() - 900.0

    time.sleep(0.5)
    ok("com indicio, a primeira checagem NAO age",
       escuta_call.contas.reanexos == 0,
       f"reanexos={escuta_call.contas.reanexos}")
    time.sleep(0.8)
    ok("a segunda confirma e age", escuta_call.contas.reanexos >= 1,
       f"reanexos={escuta_call.contas.reanexos}")
except Exception:
    falhas.append("prova x indicio")
    traceback.print_exc()

secao("12. reparo que nao resolve ESCALA pra reconexao, e nao vira laco")
try:
    import time

    class VCMorto(VCFalso):
        """A recepcao nunca volta, por mais que se reanexe. E o caso da thread
        de socket do discord.py morta."""

        def listen(self, sink, *, after=None):
            super().listen(sink, after=after)
            self._reader.active = False    # nasce morto

    limpar()
    escuta_call.INTERVALO_VIGIA = 0.3
    pedidos = []
    escuta_call.definir_reconexao(lambda: pedidos.append(1))
    vc = VCMorto()
    asyncio.run(escuta_call.comecar_a_ouvir(vc))
    escuta_call.contas.ultimo_pacote = 0.0

    # A espera e DERIVADA das constantes, nao um numero fixo. Ja apodreceu uma
    # vez: subi MAX_REANEXOS_SEGUIDOS de 2 pra 5 na producao e o teste, com 9s
    # cravados, passou a falhar sem nada estar errado.
    #
    # Cada volta do vigia custa INTERVALO_VIGIA + 2s conferindo o reanexo.
    # O teto e o DOBRO do MAX_REANEXOS_SEGUIDOS: N tentativas baratas, escalada
    # pra reconexao, e mais N depois dela (porque a reconexao pode ter
    # resolvido). Dai em diante a espera entre reconexoes bloqueia e o numero
    # ESTABILIZA.
    #
    # O teste espera a ESTABILIZACAO em vez de cravar um tempo. Ja errei duas
    # vezes aqui medindo cedo: numa o numero ainda estava subindo rumo ao teto, e
    # a conferencia acusou laco onde nao havia. "Parou de crescer" so quer dizer
    # algo depois que parou mesmo.
    # Encurta a conferencia do reanexo: aqui o que se testa e a MAQUINA DE
    # ESTADO (quantas tentativas, quando escala, quando para), nao o tempo de
    # parede. Com o valor de producao esta secao sozinha levava minutos.
    escuta_call.ESPERA_CONFERIR_REANEXO = 0.2
    por_volta = escuta_call.INTERVALO_VIGIA + escuta_call.ESPERA_CONFERIR_REANEXO + 0.2
    teto = escuta_call.MAX_REANEXOS_SEGUIDOS * 2
    limite_de_paciencia = por_volta * (teto + 6)

    anterior, estavel_por, esperou = -1, 0.0, 0.0
    while esperou < limite_de_paciencia and estavel_por < por_volta * 2:
        time.sleep(0.5)
        esperou += 0.5
        agora_r = escuta_call.contas.reanexos
        if agora_r == anterior:
            estavel_por += 0.5
        else:
            anterior, estavel_por = agora_r, 0.0

    r = escuta_call.contas.reanexos
    print(f"      estabilizou em {r} reanexos depois de {esperou:.0f}s "
          f"(teto {teto})")
    ok("tentou o reparo barato", r >= 1, f"reanexos={r}")
    ok("escalou pra reconexao de voz", len(pedidos) >= 1,
       f"pedidos={len(pedidos)}")
    ok("NAO entrou em laco de reanexo: estabilizou dentro do teto",
       r <= teto,
       f"reanexos={r} passou do teto {teto} — isso e o bug do Vitor de volta")

    # E confirma que continua parado.
    time.sleep(por_volta * 2)
    ok("e segue parado", escuta_call.contas.reanexos == r,
       f"{r} -> {escuta_call.contas.reanexos}")
    escuta_call.definir_reconexao(None)
except Exception:
    falhas.append("escala")
    traceback.print_exc()

secao("13. sem como reconectar, ela DESISTE e avisa")
try:
    import time
    limpar()
    escuta_call.INTERVALO_VIGIA = 0.3
    escuta_call._pedir_reconexao = None
    vc = VCMorto()
    asyncio.run(escuta_call.comecar_a_ouvir(vc))
    escuta_call.contas.ultimo_pacote = 0.0

    escuta_call.ESPERA_CONFERIR_REANEXO = 0.2
    por_volta = escuta_call.INTERVALO_VIGIA + escuta_call.ESPERA_CONFERIR_REANEXO + 0.2

    esperou = 0.0
    while esperou < por_volta * (escuta_call.MAX_REANEXOS_SEGUIDOS + 4) \
            and not escuta_call._desisti:
        time.sleep(0.3)
        esperou += 0.3
    ok("desistiu em vez de ficar tentando", bool(escuta_call._desisti),
       escuta_call._desisti or f"nao desistiu em {esperou:.0f}s")
    r_ao_desistir = escuta_call.contas.reanexos
    time.sleep(por_volta * 2)
    ok("e depois de desistir NAO mexe mais",
       escuta_call.contas.reanexos == r_ao_desistir,
       f"{r_ao_desistir} -> {escuta_call.contas.reanexos}")
    ok("o estado avisa que desistiu",
       "DESISTI DE CONSERTAR SOZINHA" in escuta_call.estado())

    # Entrar na call de novo tem que dar carta branca.
    vc2 = VCFalso()
    asyncio.run(escuta_call.comecar_a_ouvir(vc2))
    ok("entrar na call de novo limpa o 'desisti'",
       escuta_call._desisti == "")
except Exception:
    falhas.append("desiste")
    traceback.print_exc()

secao("14. o discord_bot sabe reconectar a voz e adotar conexao existente")
try:
    import discord_bot
    ok("existe _reconectar_voz_async",
       hasattr(discord_bot, "_reconectar_voz_async"))
    ok("existe _pedir_reconexao_de_voz",
       hasattr(discord_bot, "_pedir_reconexao_de_voz"))
    fonte = open("discord_bot.py", encoding="utf-8").read()
    ok("e liga isso no escuta_call",
       "escuta_call.definir_reconexao(_pedir_reconexao_de_voz)" in fonte)
    ok("adota a conexao de voz que ja existe na guild",
       "canal.guild.voice_client" in fonte)
except Exception:
    falhas.append("ponte")
    traceback.print_exc()

secao("15. o filtro de confianca nao come mais fala real")
try:
    import escuta_call as ec

    class R2:
        def __init__(self, lp):
            self._lp = lp

        def model_dump(self):
            return {"segments": [{"avg_logprob": self._lp,
                                  "compression_ratio": 1.3}]}

    # Falas REAIS que o filtro antigo descartou, com os logprobs do log do Vitor.
    reais = [
        ("Cara inova, mano.", -0.56), ("O meu vídeo", -0.57),
        ("Puta que pariu!", -0.63), ("Muito novo, velho.", -0.71),
        ("Na moral.", -0.79), ("Cadê tu?", -0.81),
        ("Dead Cells, Emily no Cair.", -0.82), ("Eu acho.", -0.93),
        ("Como eu vou...", -0.97), ("Essa não tá aqui, acho.", -0.86),
        ("Sim.", -0.77),
    ]
    for texto, lp in reais:
        m = ec._motivo_de_descarte(texto, R2(lp))
        ok(f"mantem {texto!r} ({lp})", m == "", m)

    # Ruido, que continua tendo que cair.
    ruido = [("Conexão.", -0.92), ("Obrigado.", -0.96), ("Dada.", -0.93),
             ("Tons.", -1.40), ("R1", -1.03), ("E aí, vamos.", -1.08)]
    for texto, lp in ruido:
        m = ec._motivo_de_descarte(texto, R2(lp))
        ok(f"descarta {texto!r} ({lp})", bool(m))
except Exception:
    falhas.append("confianca")
    traceback.print_exc()

secao("16. a dica de vocabulario nasce vazia (nao tem o que ecoar)")
try:
    import escuta_call as ec
    ok("DICA_TRANSCRICAO vazia por padrao", ec.DICA_TRANSCRICAO == "")
    ok("e o detector de eco nao quebra com dica vazia",
       ec._e_eco_da_dica("qualquer fala normal aqui na call") is False)
    fonte = open("escuta_call.py", encoding="utf-8").read()
    ok("o prompt so vai se existir",
       '"prompt": DICA_TRANSCRICAO} if DICA_TRANSCRICAO' in fonte)
except Exception:
    falhas.append("dica vazia")
    traceback.print_exc()

secao("17. O SUICIDIO DO REANEXO: o finally do roteador nao mata o novo reader")
try:
    import time
    limpar()
    escuta_call.INTERVALO_VIGIA = 30.0     # vigia fora do caminho aqui
    vc = VCFalso()
    asyncio.run(escuta_call.comecar_a_ouvir(vc))
    ok("ouvindo no comeco", escuta_call.escutando() is True)

    # Reanexa a mao, que e o que o vigia faz.
    escuta_call._anexar(vc)
    ok("logo depois de reanexar, esta ouvindo",
       escuta_call.escutando() is True)

    # Aqui e onde tudo desmoronava: o finally do roteador ANTIGO dispara com
    # atraso e chamava stop_listening() no cliente, matando o reader NOVO.
    time.sleep(0.6)
    ok("e continua ouvindo DEPOIS do finally do roteador antigo",
       escuta_call.escutando() is True,
       "se falhar, o reanexo voltou a se suicidar")

    # Varios reanexos seguidos tambem.
    for _ in range(3):
        escuta_call._anexar(vc)
        time.sleep(0.3)
    time.sleep(0.5)
    ok("sobrevive a reanexos em sequencia", escuta_call.escutando() is True)

    # E o desarme nao pode ter quebrado o stop_listening de verdade.
    escuta_call.parar_de_ouvir(vc)
    ok("parar_de_ouvir ainda para", escuta_call.escutando() is False)
except Exception:
    falhas.append("suicidio do reanexo")
    traceback.print_exc()

secao("18. o sink NUNCA levanta excecao (senao mata a recepcao inteira)")
try:
    limpar()
    vc = VCFalso()
    asyncio.run(escuta_call.comecar_a_ouvir(vc))
    sink = vc.sink_recebido
    escuta_call.contas.zerar()

    class DadoQuebrado:
        """Um pacote que faz o caminho normal explodir."""
        @property
        def pcm(self):
            raise ValueError("pcm podrido")

    class UsuarioEstranho:
        id = 999
        display_name = "Fulano"

    try:
        sink.write(UsuarioEstranho(), DadoQuebrado())
        engoliu = True
    except Exception as e:
        engoliu = False
        print(f"      vazou: {type(e).__name__}: {e}")
    ok("write engole a excecao em vez de deixar subir", engoliu)
    ok("e registra o erro pra diagnostico",
       escuta_call.contas.erros >= 1,
       f"erros={escuta_call.contas.erros}, ultimo={escuta_call.contas.ultimo_erro!r}")
    ok("a recepcao continua viva depois do erro",
       escuta_call.escutando() is True)

    # PCM de tamanho impar, que faz o audioop.rms reclamar.
    class DadoImpar:
        pcm = b"\x01\x02\x03"

    try:
        sink.write(UsuarioEstranho(), DadoImpar())
        sink._fechar(999, __import__("time").monotonic(), forcado=False)
        engoliu2 = True
    except Exception as e:
        engoliu2 = False
        print(f"      vazou: {type(e).__name__}: {e}")
    ok("PCM de tamanho impar tambem nao derruba nada", engoliu2)
    ok("e a recepcao segue viva", escuta_call.escutando() is True)
except Exception:
    falhas.append("sink blindado")
    traceback.print_exc()

secao("19. a fila descarta por IDADE, nao por falta de vaga")
try:
    import time
    import resto_call

    ok("a fila cresceu", resto_call.MAX_FILA >= 4,
       f"MAX_FILA={resto_call.MAX_FILA}")
    ok("existe teto de idade", resto_call.IDADE_MAXIMA_FILA > 0,
       f"{resto_call.IDADE_MAXIMA_FILA}s")
    fonte = open("resto_call.py", encoding="utf-8").read()
    ok("e o trabalhador confere a idade antes de responder",
       "atraso > IDADE_MAXIMA_FILA" in fonte)
except Exception:
    falhas.append("fila")
    traceback.print_exc()

secao("20. sem regressao")
try:
    import subprocess
    for script in ("escuta_call.py", "resto_call.py"):
        r = subprocess.run([sys.executable, script], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        ok(f"{script} sai com 0", r.returncode == 0,
           (r.stdout or "")[-400:] if r.returncode else "")
except Exception:
    falhas.append("regressao")
    traceback.print_exc()

limpar()
print("\n" + "=" * 68)
if falhas:
    print(f"{len(falhas)} problema(s): {falhas}")
else:
    print("A escuta se conserta sozinha quando a recepcao cai.")
sys.exit(1 if falhas else 0)

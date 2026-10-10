"""Teste de fumaça da ligação: imports, ferramentas e caminho de conexão."""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import io
import sys
import traceback

falhas = []


def secao(t):
    print("\n" + "-" * 60)
    print(t)
    print("-" * 60)


def ok(rotulo, cond, extra=""):
    global falhas
    if not cond:
        falhas.append(rotulo)
    print(f"  {'ok   ' if cond else 'FALHA'} {rotulo}" + (f"  {extra}" if extra else ""))


secao("1. importar os modulos novos")
try:
    import escuta_call
    import resto_call
    print("  ok    escuta_call e resto_call importam")
except Exception:
    falhas.append("import")
    traceback.print_exc()

secao("2. importar o discord_bot (sem conectar)")
try:
    import discord_bot
    print("  ok    discord_bot importa")
    ok("config tem ouvir_call", "ouvir_call" in discord_bot._CONFIG_PADRAO)
    ok("config tem responder_call", "responder_call" in discord_bot._CONFIG_PADRAO)
    for nome in ("_conectar_ouvindo", "_ligar_escuta_de_call",
                 "_desligar_escuta_de_call", "tocar_na_call_bloqueando",
                 "_quem_esta_na_call", "_avisar_anti_eco"):
        ok(f"existe {nome}", hasattr(discord_bot, nome))
    import discord
    from discord.ext import voice_recv
    ok("VoiceRecvClient herda de VoiceClient",
       issubclass(voice_recv.VoiceRecvClient, discord.VoiceClient))
except Exception:
    falhas.append("discord_bot")
    traceback.print_exc()

secao("3. todo caminho de conexao usa _conectar_ouvindo")
try:
    fonte = open("discord_bot.py", encoding="utf-8").read()
    import re
    # O que vale não é o connect ter argumento, é ele pedir o cliente que
    # OUVE. Todo `await X.connect(...)` sem cls= é entrada muda numa call — as
    # duas exceções são os fallbacks deliberados de _conectar_ouvindo (config
    # ouvir_call=False e a última linha depois de 3 tentativas). O regex antigo
    # exigia parênteses vazios e não contava nada: os connects reais têm
    # timeout= e reconnect=.
    connects = re.findall(r"await\s+\w+\.connect\(([^)]*)\)", fonte, re.S)
    sem_cls = [c for c in connects if "cls=" not in c]
    ok("nenhum connect() mudo fora dos dois fallbacks",
       len(sem_cls) == 2, f"achei {len(sem_cls)} de {len(connects)}")
    ok("connect com cls=VoiceRecvClient existe",
       "cls=voice_recv.VoiceRecvClient" in fonte)
    ok("_conectar_voz liga a escuta",
       fonte.count("await _ligar_escuta_de_call()") >= 2)
    # Toda saída de call tem que desligar a escuta antes do disconnect.
    saidas = re.findall(r"_desligar_escuta_de_call\(\)\s*\n\s*await\s+_voice_client\.disconnect\(\)",
                        fonte)
    ok("saidas de call desligam a escuta antes de desconectar",
       len(saidas) >= 4, f"achei {len(saidas)}")
except Exception:
    falhas.append("varredura")
    traceback.print_exc()

secao("4. as ferramentas de call entram no catalogo")
try:
    import ferramentas_vida

    class F:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    registradas = []
    total = ferramentas_vida.registrar_tudo(
        lambda f: registradas.append(f.nome), F)
    nomes = [f for f in registradas]
    print(f"  {total} ferramentas registradas")
    for esperada in ("o_que_ouvi_na_call", "ficar_quieta_na_call",
                     "estado_da_escuta_de_call"):
        ok(f"registrou {esperada}", esperada in nomes)

    resumo = ferramentas_vida.resumo_capacidades()
    ok("resumo fala de ouvir na call", "OUVE o que todo mundo fala" in resumo)
    declaradas = set(ferramentas_vida.nomes())
    ok("toda ferramenta de _CAPACIDADES existe de verdade",
       declaradas.issubset(set(nomes)),
       f"sobrando: {sorted(declaradas - set(nomes))}")
except Exception:
    falhas.append("ferramentas")
    traceback.print_exc()

secao("5. as ferramentas rodam fora de call sem quebrar")
try:
    import ferramentas_vida
    execs = {}

    class F2:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    ferramentas_vida.registrar_tudo(
        lambda f: execs.__setitem__(f.nome, f.executar), F2)

    r = execs["o_que_ouvi_na_call"]()
    ok("o_que_ouvi_na_call avisa que nao esta em call",
       "não estou ouvindo" in r.lower(), repr(r[:70]))

    r = execs["estado_da_escuta_de_call"]()
    ok("estado_da_escuta_de_call responde", "Ouvir" in r and "Responder" in r)

    r = execs["ficar_quieta_na_call"]()
    ok("ficar_quieta_na_call responde", bool(r), repr(r[:60]))
except Exception:
    falhas.append("execucao")
    traceback.print_exc()

secao("6. anti-eco enxerga a fala que nao passou pelo resto_call")
try:
    import time
    import resto_call
    resto_call._est.ligado = True
    resto_call.zerar_conversa()
    resto_call.silenciar_por(2.0, "eu falei isso aqui agora")

    class T:
        def __init__(self, texto, inicio):
            self.texto, self.inicio = texto, inicio
            self.user_id, self.nome = 7, "Comuna"

    agora = time.monotonic()
    eco1, _ = resto_call._e_eco(T("eu falei isso aqui agora", agora))
    eco2, _ = resto_call._e_eco(
        T("cara vamos jogar minecraft depois do almoco", agora))
    ok("eco de fala externa e descartado", eco1 is True)
    ok("fala diferente na mesma janela passa", eco2 is False)
    resto_call._est.ligado = False
    resto_call.zerar_conversa()
except Exception:
    falhas.append("anti-eco externo")
    traceback.print_exc()

secao("7. personalidade de call revoga o que estraga o TTS")
try:
    import modelo
    p = modelo.EMILY_PERSONALIDADE_DISCORD_CALL
    for termo in ('"kkk"', '"vc"', '"pq"', '"krl"', 'emoji', 'markdown',
                  'tamanho que o assunto pede'):
        ok(f"o prompt de call trata de {termo}", termo in p)
    ok("a base do Discord continua dentro",
       modelo.EMILY_PERSONALIDADE_DISCORD in p)
    ok("_personalidade_discord(True) usa o bloco de call",
       modelo.EMILY_PERSONALIDADE_DISCORD_CALL in modelo._personalidade_discord(True))
except Exception:
    falhas.append("personalidade")
    traceback.print_exc()

print("\n" + "=" * 60)
if falhas:
    print(f"{len(falhas)} problema(s): {falhas}")
else:
    print("Ligacao inteira conferida. Falta a call de verdade.")
sys.exit(1 if falhas else 0)

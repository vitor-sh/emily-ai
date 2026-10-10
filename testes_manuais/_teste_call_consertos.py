"""Confere os tres consertos: filler, falas dela na transcricao, ferramentas."""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import sys
import time
import traceback

falhas = []


def ok(rotulo, cond, extra=""):
    if not cond:
        falhas.append(rotulo)
    print(f"  {'ok   ' if cond else 'FALHA'} {rotulo}" + (f"  {extra}" if extra else ""))


def secao(t):
    print("\n" + "-" * 62)
    print(t)
    print("-" * 62)


secao("1. o filler nasce DESLIGADO")
try:
    import resto_call
    ok("SINAL_DE_OUVI e False por padrao", resto_call.SINAL_DE_OUVI is False)
    fonte = open("resto_call.py", encoding="utf-8").read()
    ok("so dispara fora do modo conversa",
       "if not modo_conversa:\n        _sinalizar_que_ouviu()" in fonte)
except Exception:
    falhas.append("filler")
    traceback.print_exc()

secao("2. as falas DELA entram na transcricao da call")
try:
    import escuta_call
    with escuta_call._trava_historico:
        escuta_call._historico.clear()

    def fala_de(nome, uid, texto):
        agora = time.monotonic()
        t = escuta_call.Turno(user_id=uid, nome=nome, inicio=agora,
                              fim=agora, texto=texto)
        with escuta_call._trava_historico:
            escuta_call._historico.append(t)

    fala_de("Vitor", 111, "emily o servidor tá on?")
    escuta_call.registrar_fala_dela("tá ligado sim, três pessoas jogando")
    fala_de("Vitor", 222, "e quem tá jogando?")

    t = escuta_call.transcricao_recente(segundos=60, limite=10)
    print("  transcricao montada:")
    for linha in t.splitlines():
        print(f"      {linha}")

    ok("a resposta dela aparece", "Emily (você): tá ligado sim" in t)
    ok("aparece na ordem certa (entre as duas perguntas)",
       t.index("Emily (você)") > t.index("servidor tá on")
       and t.index("Emily (você)") < t.index("quem tá jogando"))
    ok("fala vazia nao entra",
       (escuta_call.registrar_fala_dela("   ") or True)
       and len(escuta_call._historico) == 3)
    ok("usa o ID reservado, que nao colide com pessoa",
       escuta_call.ID_DELA == 0
       and escuta_call._historico[1].user_id == escuta_call.ID_DELA)
except Exception:
    falhas.append("transcricao")
    traceback.print_exc()

secao("3. a fala dela NAO pode virar gatilho de si mesma")
try:
    import escuta_call
    import resto_call
    vistos = []
    escuta_call.observar(lambda turno: vistos.append(turno.texto))
    antes = len(vistos)
    escuta_call.registrar_fala_dela("emily aqui falando o proprio nome")
    ok("registrar_fala_dela nao avisa observador", len(vistos) == antes,
       f"observadores viram {len(vistos) - antes}")
    # E o texto dela contem o nome dela, entao se vazasse pro gatilho seria laco.
    ok("(e o texto dela dispararia o gatilho se vazasse)",
       resto_call.chamaram_ela("emily aqui falando o proprio nome") is True)
except Exception:
    falhas.append("laco")
    traceback.print_exc()

secao("4. o caminho com ferramenta esta ligado")
try:
    import discord_bot
    ok("existe _pensar_na_call", hasattr(discord_bot, "_pensar_na_call"))
    fonte = open("discord_bot.py", encoding="utf-8").read()
    ok("_pensar_na_call e injetado no resto_call",
       "pensar=_pensar_na_call" in fonte)
    ok("usa falada_na_call=True", "falada_na_call=True" in fonte)
    ok("cobra ferramenta em pesquisa/acao util ou ordem administrativa explicita",
       "parece_acao=classificacao.exige_ferramenta" in fonte)
    ok("autonomia nao manda toda conversa ao caminho pesado",
       "or (eh_dono and modelo_module.autonomia_experimental_ativa())" not in fonte)
    ok("acao destrutiva continua com trava (origem='discord')",
       'origem="call"' not in fonte)
    import inspect
    sig = inspect.signature(discord_bot._pensar_na_call)
    for p in ("user_id", "nome", "fala", "transcricao", "modo_conversa",
              "quem_na_call"):
        ok(f"_pensar_na_call aceita {p}", p in sig.parameters)

    import resto_call
    sig2 = inspect.signature(resto_call.definir_saidas)
    ok("definir_saidas aceita pensar", "pensar" in sig2.parameters)
    ok("definir_saidas aceita iniciativa sem ferramentas",
       "pensar_espontaneo" in sig2.parameters)
    ok("caminho rapido calcula dono antes de usar memoria",
       fonte.index("eh_dono =") < fonte.index("dono_user_id=_memoria_dono"))
except Exception:
    falhas.append("ferramentas")
    traceback.print_exc()

secao("5. o modelo sabe da diferenca entre call falada e call escrita")
try:
    import modelo
    import inspect
    sig = inspect.signature(modelo.responder_discord_com_ferramentas)
    ok("responder_discord_com_ferramentas aceita falada_na_call",
       "falada_na_call" in sig.parameters)

    falado = modelo._sistema_discord_admin(
        "Vitor", "Broxas SMP", "Pv", "dono", True, falada_na_call=True)
    escrito = modelo._sistema_discord_admin(
        "Vitor", "Broxas SMP", "geral", "dono", True, em_call=True)

    ok("o falado usa a personalidade de call",
       "TUDO ACIMA VALE, MENOS O JEITO DE ESCREVER" in falado)
    ok("o escrito NAO usa a personalidade de call",
       "TUDO ACIMA VALE, MENOS O JEITO DE ESCREVER" not in escrito)
    ok("o falado proibe prometer verificacao",
       "deixa eu verificar" in falado and "NUNCA diga" in falado)
    ok("o falado manda ler as falas dela", "Emily (você)" in falado)
    ok("o falado tem o portao de terceira pessoa",
       "NADA_A_DIZER" in falado)
    ok("o escrito nao ganhou o portao de call",
       "NADA_A_DIZER" not in escrito)

    # O caminho de reserva (sem ferramenta) nao pode mais prometer.
    fonte_m = open("modelo.py", encoding="utf-8").read()
    ok("o caminho de reserva nao manda mais prometer",
       "diga numa frase que vai fazer" not in fonte_m)
except Exception:
    falhas.append("modelo")
    traceback.print_exc()

secao("6. os diagnosticos antigos continuam passando")
try:
    import subprocess
    for script in ("resto_call.py", "testes_manuais/_teste_call_ligacao.py"):
        r = subprocess.run([sys.executable, script], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        ok(f"{script} sai com 0", r.returncode == 0,
           (r.stdout or "")[-300:] if r.returncode else "")
except Exception:
    falhas.append("regressao")
    traceback.print_exc()

print("\n" + "=" * 62)
if falhas:
    print(f"{len(falhas)} problema(s): {falhas}")
else:
    print("Os tres consertos conferidos, sem regressao.")
sys.exit(1 if falhas else 0)

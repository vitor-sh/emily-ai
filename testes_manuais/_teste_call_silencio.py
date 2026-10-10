"""
Reproduz o laco do 'fico quieta' e confere que ele nao acontece mais.

O caso, exatamente como saiu no terminal do Vitor:
  1. linha de conversa aberta com ele
  2. ele fala com OUTRA pessoa ("Ah, e muito bom.")
  3. o modelo pega ficar_quieta_na_call sem ninguem ter pedido
  4. ela fala "Fico quieta." em voz alta
  5. falar desfazia o silencio -> linha reabria -> repetia na fala seguinte
"""
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
    print("\n" + "-" * 66)
    print(t)
    print("-" * 66)


import escuta_call
import resto_call


class T:
    def __init__(self, texto, uid=111, nome="hiucksam"):
        agora = time.monotonic()
        self.texto, self.inicio, self.fim = texto, agora, agora
        self.user_id, self.nome = uid, nome


# O que ela "falou" fica registrado aqui em vez de ir pro Fish/Discord.
falado = []
resto_call._gerar_voz = lambda texto: (b"\x00\x00" * 50, 44100, 1)


def preparar(pensar):
    falado.clear()
    resto_call._est.ligado = True
    resto_call._est.silenciada = False
    resto_call._est.silenciada_seq = 0
    resto_call.zerar_conversa()
    resto_call._esvaziar_fila()
    with escuta_call._trava_historico:
        escuta_call._historico.clear()
    resto_call._pensar = None
    resto_call._mandar_no_texto = None
    resto_call.definir_saidas(
        tocar=lambda pcm, taxa, canais: (falado.append(len(pcm)) or True),
        pensar=pensar,
    )


def pensar_calando(**kw):
    """Simula o modelo pegando a ferramenta de ficar quieta."""
    resto_call.silenciar()
    return {"responder": True, "resposta": "Fico quieta.", "detalhe_texto": ""}


def pensar_normal(**kw):
    return {"responder": True, "resposta": "tá ligado sim", "detalhe_texto": ""}


def pensar_calado(**kw):
    return {"responder": False, "resposta": "", "detalhe_texto": ""}


secao("1. a primeira vez que mandam calar: ela confirma uma vez")
try:
    preparar(pensar_calando)
    resto_call._responder(T("Emily fica quieta ai"), False)
    ok("falou a confirmacao uma vez", len(falado) == 1, f"falou {len(falado)}x")
    ok("ficou silenciada", resto_call.silenciada() is True)
    ok("NAO desfez o proprio silencio", resto_call.respondendo() is False)
    ok("NAO abriu linha de conversa com quem mandou calar",
       111 not in resto_call._est.conversa)
except Exception:
    falhas.append("primeira vez")
    traceback.print_exc()

secao("2. o laco: mandar calar de novo, ja calada")
try:
    # Continua do estado anterior: silenciada.
    falado.clear()
    resto_call._responder(T("Emily, cê tá aí??"), False)
    ok("NAO repetiu 'fico quieta' em voz alta", len(falado) == 0,
       f"falou {len(falado)}x")
    ok("continua silenciada", resto_call.silenciada() is True)

    # Terceira, quarta... o laco tinha que sumir de vez.
    falado.clear()
    for i in range(4):
        resto_call._responder(T(f"Emily {i}"), False)
    ok("nem depois de 4 tentativas ela fala", len(falado) == 0,
       f"falou {len(falado)}x")
    ok("e segue silenciada", resto_call.silenciada() is True)
except Exception:
    falhas.append("laco")
    traceback.print_exc()

secao("3. calada, uma resposta DE VERDADE ainda traz ela de volta")
try:
    resto_call._est.silenciada = True
    resto_call.definir_saidas(pensar=pensar_normal)
    falado.clear()
    resto_call._responder(T("Emily, cê tá aí??"), False)
    ok("falou a resposta", len(falado) == 1)
    ok("voltou a responder", resto_call.silenciada() is False)
    tr = escuta_call.transcricao_recente(60, 10)
    ok("e a resposta entrou na transcricao",
       "Emily (você): tá ligado sim" in tr)
except Exception:
    falhas.append("volta")
    traceback.print_exc()

secao("4. a linha de conversa fecha quando a pessoa volta pros outros")
try:
    preparar(pensar_calado)
    # Linha aberta com ele.
    resto_call._est.conversa[111] = time.monotonic() + 60

    resto_call._ao_ouvir_turno(T("Ô Biel, você viu aquele jogo novo?"))
    resto_call._fechar_lote()
    ok("primeira fala entra na fila (linha aberta)",
       not resto_call._fila.empty())
    turno, modo = resto_call._fila.get_nowait()
    ok("entra como modo conversa", modo is True)
    resto_call._responder(turno, modo)
    ok("depois de 1 recusa a linha continua aberta",
       111 in resto_call._est.conversa)
    ok("contou a recusa", resto_call._est.calou_seguidas.get(111) == 1)

    resto_call._ao_ouvir_turno(T("Ah, é muito bom."))
    resto_call._fechar_lote()
    turno, modo = resto_call._fila.get_nowait()
    resto_call._responder(turno, modo)
    ok("depois de 2 recusas seguidas a linha FECHA",
       111 not in resto_call._est.conversa)
    ok("e o contador foi zerado",
       111 not in resto_call._est.calou_seguidas)

    # Com a linha fechada, conversa solta nao dispara mais nada.
    resto_call._ao_ouvir_turno(T("e o Biel falou que vai comprar"))
    ok("com a linha fechada, conversa solta nao entra na fila",
       resto_call._fila.empty())
except Exception:
    falhas.append("fechar linha")
    traceback.print_exc()

secao("5. uma recusa isolada NAO fecha a linha")
try:
    preparar(pensar_calado)
    resto_call._est.conversa[111] = time.monotonic() + 60
    resto_call._responder(T("tosse"), True)
    ok("uma recusa nao fecha", 111 in resto_call._est.conversa)
    # E uma resposta de verdade zera o contador.
    resto_call.definir_saidas(pensar=pensar_normal)
    resto_call._responder(T("Emily o que voce acha"), True)
    ok("resposta zera o contador de recusas",
       111 not in resto_call._est.calou_seguidas)
except Exception:
    falhas.append("recusa isolada")
    traceback.print_exc()

secao("6. o prompt e a ferramenta explicam a diferenca")
try:
    import modelo
    p = modelo._sistema_discord_admin(
        "Vitor", "Broxas SMP", "Pv", "dono", True, falada_na_call=True)
    ok("o prompt separa NADA_A_DIZER da ferramenta",
       "NADA_A_DIZER NÃO É A MESMA COISA" in p)
    ok("o prompt proibe usar a ferramenta por decisao propria",
       "NUNCA use ficar_quieta_na_call só porque você decidiu" in p)
    ok("o prompt manda nao repetir estando ja quieta",
       "já está quieta, não chame ela de novo" in p)

    import ferramentas_vida

    class F:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    descricoes = {}
    ferramentas_vida.registrar_tudo(
        lambda f: descricoes.__setitem__(f.nome, f.descricao), F)
    d = descricoes["ficar_quieta_na_call"]
    ok("a ferramenta exige pedido em palavras",
       "EM PALAVRAS" in d)
    ok("a ferramenta avisa do efeito de usar errado",
       "sem ninguém ter pedido" in d)
except Exception:
    falhas.append("prompt")
    traceback.print_exc()

secao("7. sem regressao")
try:
    import subprocess
    for script in ("resto_call.py", "escuta_call.py"):
        r = subprocess.run([sys.executable, script], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        ok(f"{script} sai com 0", r.returncode == 0,
           (r.stdout or "")[-400:] if r.returncode else "")
except Exception:
    falhas.append("regressao")
    traceback.print_exc()

resto_call._est.ligado = False
resto_call._pensar = None
resto_call._tocar_na_call = None

print("\n" + "=" * 66)
if falhas:
    print(f"{len(falhas)} problema(s): {falhas}")
else:
    print("O laco do 'fico quieta' nao acontece mais.")
sys.exit(1 if falhas else 0)

"""
Testa os dois freios novos da call, sem Discord e sem Groq:

  1. O freio de conversa: com a linha aberta (modo conversa), ela só responde
     o que emenda com o que ela acabou de dizer — fala aleatória é ignorada,
     duas ignoradas em sequência fecham a linha.
  2. O "cala boca" em voz alta: "emily fica quieta", "cala a boca" etc.
     obedecidos na hora, voltando pro modo de só responder ao nome.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import sys
import time
import traceback

falhas = []


def ok(rotulo, cond, extra=""):
    if not cond:
        falhas.append(rotulo)
    print(f"  {'ok   ' if cond else 'FALHA'} {rotulo}"
          + (f"  {extra}" if extra else ""))


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


# O que ela "falou" vai pra cá em vez de pro Fish/Discord.
falado = []
resto_call._gerar_voz = lambda texto: (b"\x00\x00" * 50, 44100, 1)
resto_call._tocar_na_call = lambda pcm, taxa, canais: (
    falado.append(len(pcm)) or True)

chamadas = []


def pensar_contando(**kw):
    chamadas.append(kw.get("fala", ""))
    return {"responder": True, "resposta": "tá ligado", "detalhe_texto": ""}


def preparar(pensar=None):
    falado.clear()
    chamadas.clear()
    resto_call._est.ligado = True
    resto_call._est.silenciada = False
    resto_call._est.silenciada_seq = 0
    resto_call.zerar_conversa()
    resto_call._esvaziar_fila()
    resto_call._limpar_lote()
    with escuta_call._trava_historico:
        escuta_call._historico.clear()
    resto_call._pensar = None
    resto_call._mandar_no_texto = None
    resto_call.definir_saidas(
        tocar=lambda pcm, taxa, canais: (falado.append(len(pcm)) or True),
        pensar=pensar or pensar_contando,
    )


def reabrir():
    """Linha de conversa aberta com o 111 e a última fala dela registrada."""
    resto_call.zerar_conversa()
    resto_call._est.ultima_fala_dela = "tô configurando o servidor aqui"
    escuta_call.registrar_fala_dela("tô configurando o servidor aqui")
    resto_call._est.conversa[111] = time.monotonic() + 60


def esperar_falado(n, segundos=2.0):
    prazo = time.monotonic() + segundos
    while len(falado) < n and time.monotonic() < prazo:
        time.sleep(0.05)


secao("1. o comando de silencio, com o nome dela")
try:
    for fala in ("Emily, fica quieta", "cala a boca emily", "Emily silêncio",
                 "emily cala essa boca agora", "emily para de falar",
                 "emily cala", "Emilly fica quieta pfv", "cala emily"):
        ok(f"detecta {fala!r}", resto_call._comando_de_silencio(fala))
    for fala in ("a emily tá quieta agora", "emily calou a boca do joao",
                 "emily, cê tá aí?", "emily o servidor tá on?",
                 "a emily fala demais, chega"):
        ok(f"NAO detecta {fala!r}", not resto_call._comando_de_silencio(fala))
except Exception:
    falhas.append("comando com nome")
    traceback.print_exc()

secao("2. o comando de silencio, SEM o nome dela")
try:
    for fala in ("cala a boca", "só silêncio agora", "SILÊNCIO!", "cala",
                 "cala a boca aí"):
        ok(f"detecta {fala!r}", resto_call._comando_de_silencio(fala))
    for fala in ("cala a boca aí e vai jogar", "vamo jogar minecraft",
                 "que silêncio estranho", "o cara mandou a gente calar a boca",
                 "mano o skin do lobby tá bugado"):
        ok(f"NAO detecta {fala!r}", not resto_call._comando_de_silencio(fala))
except Exception:
    falhas.append("comando sem nome")
    traceback.print_exc()

secao("3. 'emily cala a boca' na call: obedece e confirma UMA vez")
try:
    preparar()
    resto_call._est.conversa[111] = time.monotonic() + 60
    resto_call._ao_ouvir_turno(T("emily cala a boca"))
    ok("ficou silenciada", resto_call.silenciada() is True)
    ok("linha de conversa fechou", 111 not in resto_call._est.conversa)
    ok("não enfileirou resposta nenhuma", resto_call._fila.empty())
    esperar_falado(1)
    ok("confirmou o silêncio em voz alta", len(falado) == 1,
       f"falou {len(falado)}x")
    ok("continua ouvindo (não ficou surda)", resto_call.ligada() is True)

    # Mandar de novo, já quieta: sem repetir a confirmação (o laço antigo).
    resto_call._ao_ouvir_turno(T("emily silêncio"))
    time.sleep(0.3)
    ok("já quieta: não repetiu a confirmação", len(falado) == 1,
       f"falou {len(falado)}x")
    ok("e segue silenciada", resto_call.silenciada() is True)

    # Calada, conversa solta não vira nada.
    resto_call._ao_ouvir_turno(T("cara vamo jogar hoje de noite"))
    with resto_call._lote_trava:
        ok("calada, conversa solta não entra no lote", not resto_call._lote)

    # Chamar o nome traz ela de volta.
    resto_call._ao_ouvir_turno(T("Emily, cê tá aí??"))
    resto_call._fechar_lote()
    ok("chamada pelo nome passa (entra na fila)", not resto_call._fila.empty())
    if not resto_call._fila.empty():
        turno, modo = resto_call._fila.get_nowait()
        ok("e é chamada, não conversa", modo is False)
        resto_call._responder(turno, modo)
    esperar_falado(2)
    ok("voltou a responder", resto_call.silenciada() is False)
    ok("respondeu de verdade", len(falado) == 2, f"falou {len(falado)}x")
except Exception:
    falhas.append("obedecer silencio")
    traceback.print_exc()

secao("4. o comando chega ANTES do filtro de eco (ela falando, mudo aberto)")
try:
    preparar()
    resto_call.silenciar_por(10.0, "eu vou falar um tempão agora")
    resto_call._ao_ouvir_turno(T("emily cala a boca"))
    ok("cala mesmo dentro da janela de mudo", resto_call.silenciada() is True)
except Exception:
    falhas.append("comando contra eco")
    traceback.print_exc()

secao("5. o freio: fala que não emenda é ignorada")
try:
    preparar()
    reabrir()

    resto_call._responder(T("mano o skin do lobby tá bugado"), True)
    ok("fala aleatória: modelo NAO foi chamado", not chamadas)
    ok("contou a barreira", resto_call._est.calou_seguidas.get(111) == 1)
    ok("uma barreira não fecha a linha", 111 in resto_call._est.conversa)

    resto_call._responder(T("esse mapa é enorme"), True)
    ok("segunda barreira fechou a linha", 111 not in resto_call._est.conversa)
    ok("contador zerado junto", 111 not in resto_call._est.calou_seguidas)

    # Linha fechada: conversa solta nem chega ao _responder.
    resto_call._ao_ouvir_turno(T("e o negocio la daqui a pouco"))
    with resto_call._lote_trava:
        ok("linha fechada, nada entra no lote", not resto_call._lote)
except Exception:
    falhas.append("freio barra")
    traceback.print_exc()

secao("6. o freio deixa passar o que emenda")
try:
    preparar()
    reabrir()

    ok("pergunta passa", resto_call._faz_sentido_com_a_conversa(
        T("e o servidor já tá on?"), True))
    ok("resposta curta de diálogo passa", resto_call._faz_sentido_com_a_conversa(
        T("sim, entendi"), True))
    ok("conector de continuação passa", resto_call._faz_sentido_com_a_conversa(
        T("mas o servidor de vocês é pago"), True))
    ok("assunto compartilhado passa (o servidor que ela configurou)",
       resto_call._faz_sentido_com_a_conversa(
           T("o servidor que você tá configurando é pago"), True))
    ok("chamada pelo nome NUNCA é barrada", resto_call._faz_sentido_com_a_conversa(
        T("emily me ajuda aqui"), True))
    ok("fora do modo conversa sempre passa", resto_call._faz_sentido_com_a_conversa(
        T("qualquer coisa aleatória"), False))

    resto_call._responder(T("e o servidor já tá on?"), True)
    ok("a pergunta chegou ao modelo", len(chamadas) == 1)
    esperar_falado(1)
    ok("e ela respondeu", len(falado) == 1)

    # Responder reabre a linha e zera o contador de recusas/barreiras.
    ok("a resposta reabriu a linha", 111 in resto_call._est.conversa)
    ok("contador de barreiras zerado", 111 not in resto_call._est.calou_seguidas)
except Exception:
    falhas.append("freio passa")
    traceback.print_exc()

secao("7. o freio pode ser desligado (EMILY_CALL_GATE_CONVERSA=0)")
try:
    preparar()
    reabrir()
    antigo = resto_call.GATE_CONVERSA
    resto_call.GATE_CONVERSA = False
    try:
        resto_call._responder(T("mano o skin do lobby tá bugado"), True)
    finally:
        resto_call.GATE_CONVERSA = antigo
    ok("com o freio desligado, o modelo decide", len(chamadas) == 1)
except Exception:
    falhas.append("freio desligado")
    traceback.print_exc()

secao("8. o estado conta as novidades")
try:
    s = resto_call.estado()
    ok("estado mostra as barreiras", "barradas por não emendar" in s)
    ok("estado mostra os pedidos de silêncio", "pedidos de silêncio" in s)
except Exception:
    falhas.append("estado")
    traceback.print_exc()

secao("9. sem regressao")
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
    print("O freio de conversa e o cala-boca conferidos, sem regressao.")
sys.exit(1 if falhas else 0)
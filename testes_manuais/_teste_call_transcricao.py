"""Confere os dois consertos: transcricao inventada e o silencio eterno."""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import glob
import io
import os
import random
import sys
import time
import traceback
import wave

falhas = []


def ok(rotulo, cond, extra=""):
    if not cond:
        falhas.append(rotulo)
    print(f"  {'ok   ' if cond else 'FALHA'} {rotulo}" + (f"  {extra}" if extra else ""))


def secao(t):
    print("\n" + "-" * 64)
    print(t)
    print("-" * 64)


secao("1. a dica de vocabulario nao e mais uma lista")
try:
    import escuta_call
    d = escuta_call.DICA_TRANSCRICAO
    print(f"  dica: {d[:90]}...")
    ok("nao tem 'Nomes:'", "Nomes:" not in d)
    ok("nao tem 'Termos:'", "Termos:" not in d)
    # Os nomes saíram DE PROPÓSITO. Com eles em prosa, a dica passou a conter
    # frases que as pessoas realmente falam ("o servidor tá on?") e o detector
    # de eco começou a acusar fala real. Ver o comentário no escuta_call.
    ok("nao cita nome proprio nenhum",
       not any(n in d for n in ("Vitor", "Comuna", "Ryan", "HaoQin", "Emily")))
    ok("nao contem frase que alguem falaria na call",
       "servidor tá on" not in d and "tá on" not in d)
    # E no fim ela ficou VAZIA. Sem os nomes, o que restava era "conversa
    # informal em portugues do Brasil" — que o language="pt" ja garante. Manter
    # texto ali era so oferecer material pro Whisper regurgitar, e isso foi
    # observado duas vezes em call real.
    ok("acabou vazia de vez", d == "")
    fonte_ec = open("escuta_call.py", encoding="utf-8").read()
    ok("o idioma continua sendo dito pelo language='pt'",
       'language="pt"' in fonte_ec)
except Exception:
    falhas.append("dica")
    traceback.print_exc()

secao("2. o eco da dica e reconhecido (o bug exato do Vitor)")
try:
    import escuta_call
    # A dica ANTIGA, pra reproduzir o caso relatado ao pe da letra.
    antiga = ("Conversa em português do Brasil numa call de amigos sobre "
              "Minecraft. Nomes: Emily, Vitor, Comuna, Ryan, HaoQin. Termos: "
              "servidor, modpack, launcher, mod, Forge, Discord, spawn, base, "
              "minério, creeper, boss.")
    original = escuta_call.DICA_TRANSCRICAO
    escuta_call.DICA_TRANSCRICAO = antiga
    try:
        ok("descarta 'Nomes, Vitor, Comuna, Ryan, HaoQin.'",
           escuta_call._e_eco_da_dica("Nomes, Vitor, Comuna, Ryan, HaoQin."))
        ok("descarta 'servidor, modpack, launcher, mod, Forge'",
           escuta_call._e_eco_da_dica("servidor, modpack, launcher, mod, Forge"))
        ok("descarta a dica inteira de volta",
           escuta_call._e_eco_da_dica(antiga))
        ok("MANTEM fala real que cita nomes",
           not escuta_call._e_eco_da_dica(
               "Vitor o Comuna entrou no servidor agora"))
        ok("MANTEM fala real sobre modpack",
           not escuta_call._e_eco_da_dica(
               "cara o modpack tá dando erro no launcher aqui"))
        ok("MANTEM 'emily o servidor tá on'",
           not escuta_call._e_eco_da_dica("emily o servidor tá on"))
    finally:
        escuta_call.DICA_TRANSCRICAO = original

    # Com a dica vazia (o padrao de agora) nao existe eco possivel, e o detector
    # tem que devolver False sem quebrar.
    ok("dica vazia: nada e considerado eco",
       not escuta_call._e_eco_da_dica("emily o servidor tá on?"))
    ok("dica vazia: nem texto longo qualquer",
       not escuta_call._e_eco_da_dica(
           "cara eu acho que a gente deveria subir a base mais pra cima"))

    # Mas quem configurar uma dica propria continua protegido.
    escuta_call.DICA_TRANSCRICAO = ("Conversa sobre modpack de Minecraft com "
                                    "Forge e launcher personalizado")
    try:
        ok("com dica propria, o eco dela e pego",
           escuta_call._e_eco_da_dica(escuta_call.DICA_TRANSCRICAO))
        ok("e fala real continua passando",
           not escuta_call._e_eco_da_dica("emily o servidor tá on?"))
    finally:
        escuta_call.DICA_TRANSCRICAO = original
except Exception:
    falhas.append("eco")
    traceback.print_exc()

secao("3. filtro de confianca, com numeros medidos de verdade")
try:
    import escuta_call

    class R:
        def __init__(self, segs):
            self._segs = segs

        def model_dump(self):
            return {"segments": self._segs}

    def seg(lp, comp=1.3):
        return {"avg_logprob": lp, "compression_ratio": comp}

    # -0.24 foi a fala real do Vitor; -0.92 foi ruido puro. Medidos.
    ok("mantem fala real (logprob -0.24)",
       escuta_call._motivo_de_descarte(
           "Emily, tá me ouvindo? Alô? Emily?", R([seg(-0.237)])) == "")
    m = escuta_call._motivo_de_descarte("Conexão.", R([seg(-0.921)]))
    ok("descarta o ruido (logprob -0.92)", bool(m), m)
    # A calibragem mudou depois da call real: o corte rigido ficou SO pra uma
    # palavra, porque de duas em diante ele comia fala de verdade ("Na moral.",
    # "Cadê tu?", "Puta que pariu!"). Ver o comentario no escuta_call.
    ok("mantem fala de 5 palavras a -0.70 (era descartada antes)",
       escuta_call._motivo_de_descarte("Nes, bejme do meu namoro.",
                                       R([seg(-0.70)])) == "")
    m = escuta_call._motivo_de_descarte("Obrigado.", R([seg(-0.96)]))
    ok("mas descarta UMA palavra com confianca ruim (-0.96)", bool(m), m)
    ok("e mantem uma palavra razoavel (-0.77)",
       escuta_call._motivo_de_descarte("Sim.", R([seg(-0.77)])) == "")
    m = escuta_call._motivo_de_descarte("E aí, vamos.", R([seg(-1.08)]))
    ok("descarta frase abaixo de -1.0", bool(m), m)
    ok("mantem fala curta BEM pontuada (-0.30)",
       escuta_call._motivo_de_descarte("é isso mesmo cara",
                                       R([seg(-0.30)])) == "")
    ok("mantem fala LONGA de confianca media (-0.70)",
       escuta_call._motivo_de_descarte(
           "cara eu acho que a gente deveria subir a base mais pra cima "
           "porque ali embaixo tá muito escuro e spawna bicho",
           R([seg(-0.70)])) == "")
    m = escuta_call._motivo_de_descarte("sim sim sim sim sim sim",
                                        R([seg(-0.3, comp=3.1)]))
    ok("descarta texto se repetindo", bool(m), m)
    ok("sem numeros nenhum, deixa passar (nao fica surda)",
       escuta_call._motivo_de_descarte("qualquer coisa", R([])) == "")
except Exception:
    falhas.append("confianca")
    traceback.print_exc()

secao("4. contra o Groq de verdade: fala real passa, ruido nao")
try:
    import escuta_call
    caminho = sorted(glob.glob(os.path.join("prova_call", "*.wav")))[0]
    with wave.open(caminho) as w:
        pcm_real = w.readframes(w.getnframes())

    escuta_call.contas.zerar()
    t = escuta_call.transcrever(pcm_real)
    print(f"  fala real virou: {t!r}")
    ok("a fala real do Vitor continua passando", bool(t) and "Emily" in t)
    ok("nada foi descartado nesse caso", escuta_call.contas.inventados == 0)

    # Ruido, no formato que o sink entrega (48k estereo).
    random.seed(7)
    quadros = bytearray()
    for _ in range(48000 * 3):
        v = random.randint(-260, 260)
        b = int(v).to_bytes(2, "little", signed=True)
        quadros += b + b          # estereo
    escuta_call.contas.zerar()
    t2 = escuta_call.transcrever(bytes(quadros))
    print(f"  ruido virou: {t2!r}  (descartados={escuta_call.contas.inventados}"
          f", motivo={escuta_call.contas.ultimo_descarte!r})")
    ok("o ruido NAO virou fala", t2 == "")
    escuta_call.contas.zerar()
except Exception:
    falhas.append("groq real")
    traceback.print_exc()

secao("5. 'fica quieta' cala, mas nao deixa surda")
try:
    import escuta_call
    import resto_call

    class T:
        def __init__(self, texto, uid=111, nome="Vitor"):
            agora = time.monotonic()
            self.texto, self.inicio, self.fim = texto, agora, agora
            self.user_id, self.nome = uid, nome

    resto_call._est.ligado = True
    resto_call._est.silenciada = False
    resto_call.zerar_conversa()
    resto_call._esvaziar_fila()

    print(f"  {resto_call.silenciar()}")
    ok("ficou silenciada", resto_call.silenciada() is True)
    ok("respondendo() virou False", resto_call.respondendo() is False)
    ok("ligada() continua True (anti-eco segue valendo)",
       resto_call.ligada() is True)
    ok("a escuta NAO foi desligada", resto_call._est.ligado is True)

    # Calada: conversa solta nao passa.
    resto_call._ao_ouvir_turno(T("cara vamo jogar hoje de noite"))
    ok("calada, conversa solta nao entra na fila", resto_call._fila.empty())

    # Calada: linha de conversa aberta tambem nao passa.
    resto_call._est.conversa[111] = time.monotonic() + 60
    resto_call._ao_ouvir_turno(T("e o negocio que eu falei antes"))
    ok("calada, modo conversa nao dispara", resto_call._fila.empty())
    resto_call._est.conversa.clear()

    # Calada: chamar o nome dela PASSA.
    resto_call._ao_ouvir_turno(T("Emily, cê tá aí??"))
    # O gatilho entra primeiro no lote; a fila recebe quando o lote fecha.
    resto_call._fechar_lote()
    ok("calada, chamar o nome dela ENTRA na fila",
       not resto_call._fila.empty())
    if not resto_call._fila.empty():
        turno, modo = resto_call._fila.get_nowait()
        ok("e entra como chamada, nao como conversa", modo is False)

    # E responder desfaz o silencio.
    resto_call._est.silenciada = True
    # O _gerar_voz de verdade chamaria o Fish Audio e importaria o voz.py
    # (pyaudio, keyboard). Aqui interessa a DECISAO, nao o audio.
    resto_call._gerar_voz = lambda texto: (b"\x00\x00" * 100, 44100, 1)
    resto_call.definir_saidas(
        tocar=lambda pcm, taxa, canais: True,
        pensar=lambda **kw: {"responder": True, "resposta": "tô aqui sim",
                             "detalhe_texto": ""},
    )
    with escuta_call._trava_historico:
        escuta_call._historico.clear()
    resto_call._responder(T("Emily, cê tá aí??"), False)
    ok("responder desfaz o silencio", resto_call.silenciada() is False)
    tr = escuta_call.transcricao_recente(60, 10)
    ok("e a resposta entrou na transcricao", "Emily (você): tô aqui sim" in tr)

    # Terceira pessoa NAO desfaz o silencio.
    resto_call._est.silenciada = True
    resto_call.definir_saidas(
        pensar=lambda **kw: {"responder": False, "resposta": "",
                             "detalhe_texto": ""})
    resto_call._responder(T("a Emily tá quieta agora"), False)
    ok("falar DELA em terceira pessoa nao desfaz o silencio",
       resto_call.silenciada() is True)

    print(f"  {resto_call.voltar_a_falar()}")
    ok("voltar_a_falar desfaz", resto_call.silenciada() is False)

    resto_call._est.ligado = False
    resto_call._pensar = None
    resto_call._tocar_na_call = None
except Exception:
    falhas.append("silencio")
    traceback.print_exc()

secao("6. a ferramenta usa silenciar(), nao desligar()")
try:
    import ferramentas_vida

    class F:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    execs = {}
    ferramentas_vida.registrar_tudo(
        lambda f: execs.__setitem__(f.nome, f.executar), F)
    ok("existe ficar_quieta_na_call", "ficar_quieta_na_call" in execs)
    ok("existe voltar_a_falar_na_call", "voltar_a_falar_na_call" in execs)
    fonte = open("ferramentas_vida.py", encoding="utf-8").read()
    ok("a ferramenta chama silenciar()", "resto_call.silenciar()" in fonte)
    ok("a ferramenta NAO chama desligar()",
       "resto_call.desligar()" not in fonte)
    ok("a descricao conta que chamar o nome traz ela de volta",
       "te chamar pelo nome" in fonte)
    declaradas = set(ferramentas_vida.nomes())
    ok("_CAPACIDADES so cita ferramenta que existe",
       declaradas.issubset(set(execs)),
       f"sobrando {sorted(declaradas - set(execs))}")
except Exception:
    falhas.append("ferramenta")
    traceback.print_exc()

secao("7. sem regressao nos diagnosticos")
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

print("\n" + "=" * 64)
if falhas:
    print(f"{len(falhas)} problema(s): {falhas}")
else:
    print("Os dois bugs conferidos, sem regressao.")
sys.exit(1 if falhas else 0)

"""
Prova das três mudanças que o Vitor pediu na interface.

1. TEXTO NÃO FALA. Ele digita na interface e ela respondia por voz também, o que
   atrapalha quem está de headset. O silenciamento fica em voz.py (`mudo`),
   porque é o único ponto por onde TODOS os ~30 `voz.falar(...)` do main.py
   passam — inclusive o `callback_falar` que vai pro automacao.py e pro
   agente_ui.py. E o `callback_status` do `falar_stream` CONTINUA sendo chamado
   no modo mudo: é ele que leva o texto pro chat. Muda, não cega.

2. PROGRESSO COM ÍCONE. O evento é o mesmo do painel do Discord
   (`fase`, `dados`), então não existe um segundo formato pra manter.

3. CHAT MAIS BONITO. Largura máxima, avatar, texto selecionável e markdown
   mínimo — com escape de HTML ANTES, senão resultado de ferramenta que tem
   '<' e '>' (faixa de versão de mod!) desaparece da tela sem erro no log.

O teste roda SEM abrir janela: usa QApplication sem show(), e pula a seção de
widget se não houver PyQt6 no ambiente.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Sem áudio de verdade neste teste.
os.environ.setdefault("EMILY_FALAR_TEXTO_DIGITADO", "0")


def _testar_filtro_stream_fish():
    """A UI não pode piscar meia tag nem apagar colchete legítimo."""
    import interface_web
    filtro = interface_web._FiltroStreamingTagsDeVoz()
    saida = [
        filtro.alimentar("Oi [exci"),
        filtro.alimentar("ted] Vitor, [1] olha "),
        filtro.alimentar("[com um tom calmo]isso."),
    ]
    assert saida == ["Oi ", " Vitor, [1] olha ", "isso."]

    filtro.resetar()
    assert filtro.alimentar("texto [normal", finalizar=True) == "texto [normal"


_testar_filtro_stream_fish()

# O histórico de conversa vai pra um arquivo temporário. Tem que ser ANTES de
# qualquer import que puxe o conversas.py, senão o teste escreve no histórico de
# verdade do Vitor.
import tempfile as _tempfile

_PASTA_TMP = _tempfile.mkdtemp(prefix="emily_ui_")
os.environ["EMILY_ARQUIVO_CONVERSAS"] = os.path.join(_PASTA_TMP, "conversas.json")

RUINS = 0


def secao(t):
    print()
    print("-" * 78)
    print(t)
    print("-" * 78)


def ok(cond, o_que, extra=""):
    global RUINS
    if cond:
        print(f"    ok      {o_que}" + (f"  deu {extra}" if extra else ""))
    else:
        RUINS += 1
        print(f"    FALHA   {o_que}" + (f"  deu {extra}" if extra else ""))


def aviso(o_que):
    print(f"    --      {o_que}")


# ═════════════════════════════════════════════════════════════════
# 1. O MUDO
# ═════════════════════════════════════════════════════════════════

secao("1. o mudo existe, e nao e um mudo que apaga a resposta")

import voz

ok(hasattr(voz, "mudo"), "voz.mudo existe")
ok(not voz.mudo.is_set(), "e nasce desligado (voz e o padrao)")

# falar() com mudo ligado não pode gerar áudio nenhum. Substituo as duas funções
# que custam caro pra provar que NENHUMA foi chamada.
chamou = {"gerar": 0, "tocar": 0, "discord": 0}
_gerar_real = voz._gerar_audio_bytes
_tocar_real = voz._tocar_bytes


def _gerar_falso(t):
    chamou["gerar"] += 1
    return b"\x00" * 32


def _tocar_falso(b):
    chamou["tocar"] += 1


voz._gerar_audio_bytes = _gerar_falso
voz._tocar_bytes = _tocar_falso

voz.mudo.set()
voz.falar("isso nao deve virar audio")
ok(chamou["gerar"] == 0, "com mudo, falar() nao gera audio", chamou["gerar"])
ok(chamou["tocar"] == 0, "nem toca", chamou["tocar"])

voz.mudo.clear()
voz.falar("isso deve virar audio")
ok(chamou["gerar"] == 1, "sem mudo, volta a gerar", chamou["gerar"])
ok(chamou["tocar"] == 1, "e a tocar", chamou["tocar"])

secao("1b. e no stream o texto continua chegando ao chat")
chamou["gerar"] = 0
chamou["tocar"] = 0
vistas = []
fila = queue.Queue()
for frase in ("Achei os mods de interface.", "Puxei 18 libs junto.", ""):
    fila.put(frase)
fila.put(None)

voz.mudo.set()
voz.falar_stream(fila, lambda f: vistas.append(f))
ok(chamou["gerar"] == 0, "stream mudo nao gera audio", chamou["gerar"])
ok(chamou["tocar"] == 0, "nem toca", chamou["tocar"])
ok(vistas == ["Achei os mods de interface.", "Puxei 18 libs junto."],
   "MAS o callback recebeu as frases — e ele que alimenta o chat", vistas)
voz.mudo.clear()

secao("1c. o stream mudo respeita o None e nao pendura")
fila2 = queue.Queue()
fila2.put(None)
voz.mudo.set()
pronto = threading.Event()


def _rodar():
    voz.falar_stream(fila2, lambda f: None)
    pronto.set()


threading.Thread(target=_rodar, daemon=True).start()
ok(pronto.wait(timeout=5.0), "fila que abre com None termina na hora")
voz.mudo.clear()

voz._gerar_audio_bytes = _gerar_real
voz._tocar_bytes = _tocar_real

secao("0. NOME USADO SEM IMPORT — o furo que deixou a Emily sem subir")

# Este bloco existe por causa de um bug meu que passou por TODOS os testes.
#
# Eu conferi o main.py lendo o TEXTO dele (grep por 'voz.mudo.set()'), e texto
# não executa. A linha que eu adicionei usava os.getenv() num arquivo que nunca
# importou 'os', e NameError de nível de módulo só aparece quando o Python roda o
# arquivo — o que um teste não pode fazer com o main.py, porque importar o
# main.py sobe a Emily inteira (janela, Discord, voz, servidor).
#
# A saída é ler o código como CÓDIGO em vez de como texto: montar a árvore e
# comparar nome usado contra nome definido. Pega a classe inteira do erro, não
# só a linha de hoje.


def _nomes_indefinidos(caminho: str) -> list:
    import ast
    import builtins

    with open(caminho, encoding="utf-8") as fh:
        arvore = ast.parse(fh.read(), filename=caminho)

    definidos = set(dir(builtins)) | {"__file__", "__name__", "__doc__",
                                      "__spec__", "__package__", "__builtins__"}

    # Definição em QUALQUER profundidade conta: import dentro de try, função
    # aninhada, atribuição dentro de if. O que importa é o nome existir.
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            for a in no.names:
                definidos.add((a.asname or a.name).split(".")[0])
        elif isinstance(no, ast.ImportFrom):
            for a in no.names:
                definidos.add(a.asname or a.name)
        elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definidos.add(no.name)
        elif isinstance(no, ast.Name) and isinstance(no.ctx, (ast.Store, ast.Del)):
            definidos.add(no.id)
        elif isinstance(no, ast.arg):
            definidos.add(no.arg)
        elif isinstance(no, ast.ExceptHandler) and no.name:
            definidos.add(no.name)
        elif isinstance(no, ast.Global):
            definidos.update(no.names)

    # USO só no nível do módulo. Corpo de função roda depois e pode usar nome
    # definido mais abaixo no arquivo; incluir isso daria falso positivo.
    usados = set()

    def _colher(no):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef,
                           ast.ClassDef, ast.Lambda)):
            return
        if isinstance(no, ast.Name) and isinstance(no.ctx, ast.Load):
            usados.add(no.id)
        for filho in ast.iter_child_nodes(no):
            _colher(filho)

    for stmt in arvore.body:
        _colher(stmt)

    return sorted(usados - definidos)


for _arq in ("main.py", "interface.py", "voz.py", "modelo.py",
             "mods_locais.py", "curadoria.py", "progresso_discord.py"):
    if not os.path.exists(_arq):
        continue
    faltando = _nomes_indefinidos(_arq)
    ok(not faltando, f"{_arq}: nenhum nome usado sem import/definicao",
       ", ".join(faltando) if faltando else "")

secao("0b. e o detector realmente detecta (senao passar nao significa nada)")
import tempfile as _tmp

_ruim = os.path.join(_tmp.gettempdir(), "_emily_arq_ruim.py")
with open(_ruim, "w", encoding="utf-8") as fh:
    fh.write("import re\nX = os.getenv('A', '0')\n")
ok("os" in _nomes_indefinidos(_ruim),
   "arquivo que usa os.getenv sem importar os e acusado — o bug de hoje",
   _nomes_indefinidos(_ruim))

_bom = os.path.join(_tmp.gettempdir(), "_emily_arq_bom.py")
with open(_bom, "w", encoding="utf-8") as fh:
    fh.write("import os\nX = os.getenv('A', '0')\n\n"
             "def f():\n    return DEPOIS\n\nDEPOIS = 1\n")
ok(_nomes_indefinidos(_bom) == [],
   "e arquivo certo passa, inclusive nome usado dentro de funcao antes de "
   "existir", _nomes_indefinidos(_bom))
for _p in (_ruim, _bom):
    try:
        os.remove(_p)
    except OSError:
        pass

secao("1d. o main.py liga e SOLTA o mudo, e solta no finally")
fonte_main = open("main.py", encoding="utf-8").read()
ok("voz.mudo.set()" in fonte_main, "o turno escrito liga o mudo")
ok("voz.mudo.clear()" in fonte_main, "e desliga")
i_set = fonte_main.find("voz.mudo.set()")
i_finally = fonte_main.find("finally:", i_set)
i_clear = fonte_main.find("voz.mudo.clear()", i_set)
ok(0 < i_finally < i_clear,
   "e o desligamento esta DEPOIS de um finally — mudo preso emudeceria a Emily")
ok("FALAR_TEXTO_DIGITADO" in fonte_main,
   "existe interruptor pra quem quiser as duas coisas")
ok('EMILY_FALAR_TEXTO_DIGITADO", "0"' in fonte_main,
   "e o padrao e NAO falar, que foi o pedido")

# ═════════════════════════════════════════════════════════════════
# 2. O EVENTO DE PROGRESSO
# ═════════════════════════════════════════════════════════════════

secao("2. o progresso usa o MESMO evento do painel do Discord")

import inspect
import re

import modelo
import progresso_discord

params = inspect.signature(modelo.conversar_com_ferramentas).parameters
ok("on_progresso" in params,
   "conversar_com_ferramentas (o caminho da interface) aceita on_progresso")
ok(params["on_progresso"].default is None,
   "e e opcional — quem nao mostra progresso nao paga nada")

fonte_modelo = open("modelo.py", encoding="utf-8").read()

# Conta com regex tolerante a quebra de linha, e nao com count() de texto
# literal. A versao anterior procurava a string exata
# '_avisar_progresso(on_progresso, "ferramenta"' e passou a falhar quando o
# laco do Discord virou um lambda, so porque a quebra de linha caiu entre o
# '(' e o 'on_progresso' — o comportamento estava intacto. Teste que quebra
# com reformatacao nao esta medindo o que diz medir.
def _avisos_de(fase: str) -> int:
    return len(re.findall(
        r"_avisar_progresso\(\s*on_progresso,\s*[\"']" + fase + r"[\"']",
        fonte_modelo))

ok(_avisos_de("ferramenta") >= 2,
   "os dois lacos (interface e Discord) avisam ao chamar ferramenta",
   _avisos_de("ferramenta"))
ok(_avisos_de("resultado") >= 2,
   "e ao receber o resultado",
   _avisos_de("resultado"))

secao("2b. e o vocabulario e em portugues, nao nome de funcao")
casos = [
    ("analisar_mods_da_pasta_mc", {"caminho": ""}),
    ("previa_de_catar_mods_mc", {"etiquetas": "interface"}),
    ("montar_pack_catado_mc", {"nome": "broxasRPG"}),
    ("status_launcher_mc", {}),
]
for nome, args in casos:
    r = progresso_discord.rotulo(nome, args)
    print(f"        {nome} -> {r!r}")
    ok(bool(r), f"{nome} tem rotulo")
    ok("_mc" not in r and "_" not in r.split(":")[0],
       f"e o rotulo nao expoe o nome da funcao", r)

ok(progresso_discord.parece_problema(
    "NÃO montei, porque isso quebraria: falta dependência"),
   "recusa e reconhecida como problema (vira '!' no painel)")
ok(not progresso_discord.parece_problema(
    "Montei o pack 'broxasRPG' com 53 mods (commit a1b2c3d)."),
   "e sucesso vira '✓'")

secao("2c. _avisar_progresso nunca deixa o enfeite quebrar a acao")
def _explode(fase, dados):
    raise RuntimeError("painel quebrou")

try:
    modelo._avisar_progresso(_explode, "ferramenta", nome="x")
    ok(True, "callback que explode nao propaga")
except Exception as e:
    ok(False, f"propagou: {e}")
modelo._avisar_progresso(None, "ferramenta", nome="x")
ok(True, "e callback None e no-op")

# ═════════════════════════════════════════════════════════════════
# 3. O TEXTO DO CHAT
# ═════════════════════════════════════════════════════════════════

secao("3. o markdown minimo, e o escape que evita texto desaparecendo")

try:
    import interface
except Exception as e:
    aviso(f"nao importei interface ({type(e).__name__}: {e}); pulei o resto")
    interface = None

if interface is not None:
    r = interface._para_rich("faixa **[1.20.1,1.21)** e `mods.toml`")
    print(f"        {r}")
    ok("<b>[1.20.1,1.21)</b>" in r, "negrito virou <b>", r[:60])
    ok("mods.toml" in r, "e o code span sobreviveu")

    # O CASO QUE IMPORTA: '<' e '>' de verdade no texto.
    bruto = "o mod pede <1.21 e >=1.20.1, veja <config>"
    r = interface._para_rich(bruto)
    print(f"        {r}")
    ok("&lt;1.21" in r, "'<' foi escapado", r[:40])
    ok("&lt;config&gt;" in r, "e '<config>' nao virou tag (nao desaparece)")
    ok("<config>" not in r, "confirmando que a tag crua nao passou")

    r = interface._para_rich("linha 1\nlinha 2")
    ok("<br>" in r, "quebra de linha virou <br>")

    r = interface._para_rich("")
    ok(r == "", "texto vazio nao explode", repr(r))

    secao("3a2. cada tipo de acao tem seu iconezinho")
    # VERBO vence SUBSTANTIVO: o ícone diz o que ela está FAZENDO. Por isso
    # 'deletar_arquivo_mc' é 🗑 e não 📄, e 'procurar_mod_launcher_mc' é 🔍 e
    # não 🚀 — foi exatamente aí que a primeira ordenação errou.
    esperados = [
        ("analisar_mods_da_pasta_mc", "🧩"),
        ("montar_pack_catado_mc", "📦"),
        ("ver_grupo_do_modpack_mc", "📦"),
        ("status_launcher_mc", "🚀"),
        ("procurar_mod_launcher_mc", "🔍"),
        ("criar_backup_mc", "💾"),
        ("instalar_mod_mc", "⬇"),
        ("deletar_arquivo_mc", "🗑"),
        ("criar_canais_discord", "💬"),
        ("listar_membros_discord", "👤"),
        ("guardar_fato", "🧠"),
        ("abrir_site", "🌐"),
        ("listar_arquivos_mc", "📄"),
    ]
    for nome, ico in esperados:
        r = interface._icone_de(nome)
        ok(r == ico, f"{nome} -> {ico}", r)
    ok(interface._icone_de("ferramenta_totalmente_nova") == "•",
       "e nome desconhecido cai num ponto neutro, nao em erro",
       interface._icone_de("ferramenta_totalmente_nova"))
    ok(interface._icone_de("") == "•", "nome vazio tambem")

    secao("3b. e o chat tem largura maxima (senao vira log, nao conversa)")
    ok(interface.ChatBubble.LARGURA_MAX <= 800,
       "balao do Vitor tem teto de largura", interface.ChatBubble.LARGURA_MAX)
    ok(interface.PainelProgresso.MAX_LINHAS >= 5,
       "e o painel mostra passos suficientes",
       interface.PainelProgresso.MAX_LINHAS)

    secao("3c. a linha divisoria tem que DAR PRA VER")
    # O BORDER (#1a1a35) serve pra contorno de cartao, que tem fundo proprio pra
    # se destacar. Como linha de 1px entre duas areas quase da mesma cor ele
    # desaparecia — a barra lateral e a conversa diferem em UM ponto por canal.
    def _luz(cor):
        cor = cor.lstrip("#")
        r, g, b = (int(cor[i:i + 2], 16) for i in (0, 2, 4))
        return 0.299 * r + 0.587 * g + 0.114 * b

    ok(hasattr(interface, "DIVISOR"), "existe uma cor propria pra linha")
    ok(interface.DIVISOR != interface.BORDER,
       "e ela NAO e a mesma do contorno de cartao")
    ok(_luz(interface.DIVISOR) > _luz(interface.BORDER) + 8,
       "e e sensivelmente mais clara que o fundo da lateral",
       f"{_luz(interface.DIVISOR):.0f} contra {_luz(interface.BG_SIDEBAR):.0f}")
    ok(_luz(interface.DIVISOR) > _luz(interface.BG_SIDEBAR) + 12,
       "com contraste real contra a barra lateral",
       f"{_luz(interface.DIVISOR):.0f} vs {_luz(interface.BG_SIDEBAR):.0f}")

# ═════════════════════════════════════════════════════════════════
# 4. OS WIDGETS DE VERDADE
# ═════════════════════════════════════════════════════════════════

secao("4. os widgets nascem, recebem eventos e morrem sem crashar")

app = None
painel = None
if interface is not None:
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
    except Exception as e:
        aviso(f"sem PyQt6 utilizavel ({e}); pulei a secao 4")

if app is not None:
    from PyQt6.QtWidgets import QVBoxLayout, QWidget

    # ChatBubble com texto hostil
    for texto, emily in (("Oi Vitor! Tô aqui 😊", True),
                         ("analisa a pasta <de mods> ai", False),
                         ("", True),
                         ("x" * 3000, True)):
        b = interface.ChatBubble(texto, is_emily=emily)
        ok(b is not None, f"bolha criada: {texto[:26]!r}")
        b.deleteLater()

    secao("4a2. balao e SO do Vitor; a fala dela e texto na largura toda")

    def _pecas(bolha):
        """(label do texto, layout raiz) de uma ChatBubble."""
        raiz = bolha.layout()
        corpo = None
        for i in range(raiz.count()):
            w = raiz.itemAt(i).widget()
            if w is not None and w.layout() is not None:
                corpo = w
        alvo = corpo.layout().itemAt(1).widget()
        return alvo, raiz

    b_em = interface.ChatBubble(
        "Oi Vitor, tô bem sim. Tu tá bem? Porque quando cê começa perguntando "
        "isso normalmente é porque quebrou alguma coisa.", is_emily=True)
    txt_em, raiz_em = _pecas(b_em)
    est_em = txt_em.styleSheet()
    print(f"        estilo dela: {est_em}")
    ok("background:transparent" in est_em,
       "a mensagem da Emily NAO tem balao — era o pedido")
    ok(interface.USER_BUB not in est_em and interface.EMILY_BUB not in est_em,
       "nenhuma cor de balao sobrou no estilo dela")
    ok("border-radius" not in est_em, "nem canto arredondado de caixa")
    ok(txt_em.maximumWidth() >= 10000,
       "e o texto dela nao tem teto de largura", txt_em.maximumWidth())

    # O QUE CAUSAVA O EMPILHAMENTO: fator de esticamento 0 no corpo faz o QLabel
    # com wordWrap receber o minimo que pede, que e mais ou menos a palavra mais
    # longa. Tem que ser 1, e sem stretch competindo depois.
    fatores = [raiz_em.stretch(i) for i in range(raiz_em.count())]
    ok(max(fatores) >= 1,
       "o corpo dela recebe fator de esticamento (senao empilha em torres)",
       fatores)
    tem_espacador = any(raiz_em.itemAt(i).spacerItem() is not None
                        for i in range(raiz_em.count()))
    ok(not tem_espacador,
       "e NAO tem espacador roubando a largura da fala dela")

    b_eu = interface.ChatBubble("Oii emily, cê tá bem?", is_emily=False)
    txt_eu, raiz_eu = _pecas(b_eu)
    est_eu = txt_eu.styleSheet()
    ok(interface.USER_BUB in est_eu, "a MINHA mensagem continua em balao")
    ok("border-radius" in est_eu, "com canto arredondado")
    ok(any(raiz_eu.itemAt(i).spacerItem() is not None
           for i in range(raiz_eu.count())),
       "e empurrada pra direita por um espacador")

    secao("4a3. a largura do balao e MEDIDA, nao chutada")
    curto = interface.ChatBubble("oi", is_emily=False)
    longo = interface.ChatBubble("x " * 400, is_emily=False)
    # maximumWidth(), nao width(): setFixedWidth define os dois limites na hora,
    # enquanto o width() de verdade so existe depois que o layout roda numa
    # janela mostrada — e este teste nao mostra janela nenhuma.
    l_curto = _pecas(curto)[0].maximumWidth()
    l_longo = _pecas(longo)[0].maximumWidth()
    print(f"        'oi' -> {l_curto}px   texto gigante -> {l_longo}px")
    ok(l_curto < 160, "texto de duas letras ganha balao justo", l_curto)
    ok(l_longo == interface.ChatBubble.LARGURA_MAX,
       "e texto gigante bate no teto e quebra ali", l_longo)
    ok(l_longo > l_curto, "ou seja: a largura acompanha o conteudo")
    for b in (b_em, b_eu, curto, longo):
        b.deleteLater()

    # Spinner
    sp = interface.Spinner(14)
    ok(sp.width() == 14, "spinner tem o tamanho pedido", sp.width())
    sp._passo()
    ok(sp._ang > 0, "e gira", sp._ang)
    sp.parar()
    ok(not sp._t.isActive(), "e para de girar quando mandam parar")

    # LinhaPasso
    ln = interface.LinhaPasso("vendo o launcher", "🚀")
    ok(ln.aberto(), "passo nasce aberto (girando)")
    ok(ln._tipo.text() == "🚀", "e mostra o icone do tipo", ln._tipo.text())
    ln.concluir(False)
    ok(not ln.aberto(), "e fecha")
    # O estado NÃO pode depender de isVisible(): widget que ainda não foi
    # pintado tem isVisible() falso, e usar pintura como lógica fazia o painel
    # nunca fechar passo nenhum.
    ln2 = interface.LinhaPasso("montando pack")
    ok(not ln2.spin.isVisible(), "widget sem janela nao esta 'visivel'")
    ok(ln2.aberto(), "mas o passo esta aberto — estado e estado, nao desenho")

    # PainelProgresso — o ciclo inteiro
    pp = interface.PainelProgresso()
    ok(pp.vazio(), "painel nasce vazio")
    pp.passo("vendo o launcher")
    pp.resultado(False)
    pp.passo("montando pack catado")
    pp.resultado(True)          # recusa
    ok(not pp.vazio(), "depois de dois passos nao esta mais vazio")
    pp.finalizar()
    ok("ressalva" in pp._titulo.text(),
       "e o titulo final admite a ressalva", pp._titulo.text())

    pp2 = interface.PainelProgresso()
    pp2.passo("vendo o launcher")
    pp2.resultado(False)
    pp2.finalizar()
    ok("Pronto" in pp2._titulo.text(), "sem ressalva, diz Pronto",
       pp2._titulo.text())

    secao("4b. o painel nao acumula passo pra sempre")
    pp3 = interface.PainelProgresso()
    for i in range(pp3.MAX_LINHAS + 6):
        pp3.passo(f"passo {i}")
        pp3.resultado(False)
    ok(len(pp3._linhas) <= pp3.MAX_LINHAS,
       "colapsa os antigos", f"{len(pp3._linhas)} linhas")
    ok(pp3._total == pp3.MAX_LINHAS + 6,
       "mas o TOTAL continua contado certo", pp3._total)
    pp3.finalizar()
    ok(str(pp3.MAX_LINHAS + 6) in pp3._titulo.text(),
       "e o titulo diz o total de verdade", pp3._titulo.text())

    secao("4c. o indicador de digitando pulsa e para")
    ind = interface.IndicadorDigitando()
    ind._passo(); ind._passo()
    ok(ind._i == 2, "alterna os pontos", ind._i)
    ind.parar()
    ok(not ind._t.isActive(), "e para")

    secao("4d. o ciclo do painel do chat, na ordem que o main.py usa")
    # Sem abrir janela: instancio só o PainelEmily? Ele monta a UI inteira.
    # Em vez disso testo a maquininha de estado com um dublê que tem os mesmos
    # atributos e o mesmo método — é o comportamento que importa, não o widget.
    class _Dublê:
        """
        Só o necessário pra exercitar a máquina de estado do progresso.

        Os TRÊS métodos reais são emprestados da classe de verdade, então o que
        está sendo testado é o código que roda em produção — o dublê só fornece o
        chat de mentira. E `self._hosp` guarda o QWidget de propósito: sem
        referência, o Python coleta o dono e o Qt destrói o QVBoxLayout por
        baixo, e todo insertWidget passa a estourar "object has been deleted".
        """
        _on_progresso = interface.PainelEmily._on_progresso
        _encerrar_progresso = interface.PainelEmily._encerrar_progresso
        _inserir_no_chat = interface.PainelEmily._inserir_no_chat
        _garantir_cartao = interface.PainelEmily._garantir_cartao
        _rolar_pro_fim = interface.PainelEmily._rolar_pro_fim
        _ja_esta_no_cartao = interface.PainelEmily._ja_esta_no_cartao
        _anotar_fala_do_cartao = interface.PainelEmily._anotar_fala_do_cartao
        _esquecer_falas_do_cartao = interface.PainelEmily._esquecer_falas_do_cartao
        _sem_o_que_ja_apareceu = interface.PainelEmily._sem_o_que_ja_apareceu

        def __init__(self):
            self._digitando = None
            self._painel_prog = None
            self._falas_no_cartao = ""
            self._frases_no_cartao = set()
            self._hosp = QWidget()
            self._chat_layout = QVBoxLayout(self._hosp)
            self._chat_layout.addStretch()

            class _Barra:
                def setValue(self_, v): pass
                def maximum(self_): return 0

            class _Scroll:
                def verticalScrollBar(self_): return _Barra()

            self._chat_scroll = _Scroll()

    d = _Dublê()
    d._on_progresso("inicio", {})
    ok(d._digitando is not None, "'inicio' cria os pontinhos")
    ok(d._painel_prog is None, "e NAO cria cartao ainda (conversa comum)")

    d._on_progresso("fim", {})
    ok(d._digitando is None, "'fim' tira os pontinhos")
    ok(d._painel_prog is None, "e nao deixa cartao vazio no chat")

    d._on_progresso("inicio", {})
    d._on_progresso("ferramenta", {"nome": "status_launcher_mc", "args": {}})
    ok(d._painel_prog is not None, "a PRIMEIRA ferramenta cria o cartao")
    d._on_progresso("resultado", {"resultado": "Launcher de BroxasSMP — 2.0.31"})
    d._on_progresso("ferramenta", {"nome": "montar_pack_catado_mc",
                                   "args": {"nome": "broxasRPG"}})
    d._on_progresso("resultado", {"resultado": "NÃO montei, porque isso quebraria"})
    guardado = d._painel_prog
    d._on_progresso("fim", {})
    ok(d._painel_prog is None, "'fim' encerra o cartao")
    ok("ressalva" in guardado._titulo.text(),
       "e o cartao ficou com a ressalva da recusa", guardado._titulo.text())
    ok(guardado._colapsado,
       "e como teve ressalva ele ENCOLHE em vez de sumir (senao o motivo da "
       "falha se perde)")

    secao("4e. e evento estranho nao derruba nada")
    d2 = _Dublê()
    d2._on_progresso("fase_que_nao_existe", {})
    d2._on_progresso("resultado", {})           # sem painel
    d2._on_progresso("ferramenta", {})          # sem nome
    d2._on_progresso("fala", {})                # sem texto
    d2._on_progresso("fim", None)               # dados None
    ok(True, "fases fora de ordem e dados vazios passam sem excecao")

    # ═════════════════════════════════════════════════════════════
    # 5. A FALA DELA VEM ANTES DA FERRAMENTA, E O CARTAO SOME NO FIM
    # ═════════════════════════════════════════════════════════════

    secao("5. a fala dela entra no cartao, e ANTES do passo da ferramenta")

    d3 = _Dublê()
    d3._on_progresso("inicio", {})
    d3._on_progresso("fala", {"texto": "Ué, deixa eu conferir isso."})
    ok(d3._painel_prog is not None,
       "a fala sozinha ja cria o cartao — ela nao espera a ferramenta")
    d3._on_progresso("ferramenta", {"nome": "status_launcher_mc", "args": {}})
    d3._on_progresso("resultado", {"resultado": "Launcher 2.0.31, tudo certo."})
    d3._on_progresso("fala", {"texto": "Deixa eu olhar por dentro."})
    d3._on_progresso("ferramenta", {"nome": "ver_grupo_do_modpack_mc",
                                    "args": {"grupo": "interface"}})
    d3._on_progresso("resultado", {"resultado": "'interface': 32 mods"})

    itens = d3._painel_prog._tudo
    tipos = ["fala" if isinstance(w, interface.LinhaFala) else "passo"
             for w in itens]
    print(f"        ordem no cartao: {tipos}")
    ok(tipos == ["fala", "passo", "fala", "passo"],
       "a ordem e fala, ferramenta, fala, ferramenta — foi o pedido", tipos)
    ok(not isinstance(itens[0], interface.LinhaPasso),
       "e a fala NAO e um passo: nao tem check, nao tem spinner")
    ok(d3._painel_prog._total == 2,
       "e fala nao conta como passo no total", d3._painel_prog._total)

    secao("5b. a mesma frase nao aparece duas vezes (cartao e depois bolha)")
    ok(d3._ja_esta_no_cartao("Ué, deixa eu conferir isso."),
       "a frase exata e reconhecida como ja mostrada")
    ok(d3._ja_esta_no_cartao("deixa eu conferir isso"),
       "e o pedaco que o TTS devolve cortado tambem — e o caso real")
    ok(d3._ja_esta_no_cartao("Deixa Eu Olhar Por Dentro!!!"),
       "maiuscula e pontuacao diferentes nao enganam")
    ok(not d3._ja_esta_no_cartao("achei 32 mods de interface no pack"),
       "MAS a resposta final passa — ela precisa virar bolha")
    ok(not d3._ja_esta_no_cartao(""), "e texto vazio nao casa com nada")
    ok(not d3._ja_esta_no_cartao("ok"),
       "e frase curtinha nao casa por acidente dentro de outra")

    secao("5b2. e a mensagem FINAL sai sem repetir o que ja apareceu")
    # O caso do Vitor: "mesmo já aparecendo tudo ali, quando a Emily manda a
    # mensagem final, aquilo tudo que já apareceu no progresso aparece de novo".
    # Acontece porque o preambulo dela volta pro contexto junto do tool_call, e na
    # volta o modelo costuma repetir a propria abertura antes de responder.
    final = ("Ué, deixa eu conferir isso. Deixa eu olhar por dentro. "
             "Achei 32 mods de interface, e 18 são libs.")
    cortado = d3._sem_o_que_ja_apareceu(final)
    print(f"        antes:  {final}")
    print(f"        depois: {cortado}")
    ok("deixa eu conferir" not in cortado.lower(),
       "a abertura repetida saiu da mensagem final")
    ok("olhar por dentro" not in cortado.lower(),
       "e a segunda narracao tambem")
    ok("32 mods de interface" in cortado,
       "MAS a conclusao de verdade ficou — ela e o unico conteudo novo")
    ok("18" in cortado, "inteira, sem cortar o resto da frase", cortado)

    secao("5b3. mas cortar tudo deixaria a acao terminando em silencio")
    # O cartao desaparece no fim do turno. Se a filtragem esvaziar a mensagem, nao
    # sobra NADA na tela — e "ela agiu e nao disse nada" e pior que ler duas vezes.
    so_repetido = "Ué, deixa eu conferir isso. Deixa eu olhar por dentro."
    ok(d3._sem_o_que_ja_apareceu(so_repetido).strip() != "",
       "texto 100% repetido volta inteiro em vez de virar vazio",
       repr(d3._sem_o_que_ja_apareceu(so_repetido)))

    secao("5b4. e sem cartao nenhum o texto passa intocado")
    d_limpo = _Dublê()
    intacto = "Achei 362 jars. Quer que eu separe os de interface?"
    ok(d_limpo._sem_o_que_ja_apareceu(intacto) == intacto,
       "conversa comum nao perde uma virgula",
       d_limpo._sem_o_que_ja_apareceu(intacto))

    secao("5c. deu tudo certo -> o cartao SOME e sobra so a mensagem dela")
    guardado3 = d3._painel_prog
    d3._on_progresso("fim", {})
    ok(d3._painel_prog is None, "o cartao foi encerrado")
    ok(guardado3.parent() is None,
       "e SAIU do chat — 'some tudo que tava ali e aparece so a mensagem dela'")
    ok(d3._falas_no_cartao == "",
       "e as falas guardadas foram esquecidas, pro turno seguinte comecar limpo",
       repr(d3._falas_no_cartao))
    ok(d3._frases_no_cartao == set(),
       "as frases tambem — senao o turno seguinte comeria texto por engano",
       d3._frases_no_cartao)

    secao("5d. fala sem ferramenta nenhuma tambem nao deixa cartao no chat")
    d4 = _Dublê()
    d4._on_progresso("inicio", {})
    d4._on_progresso("fala", {"texto": "Peraí que eu vou ver."})
    cartao4 = d4._painel_prog
    ok(cartao4.vazio(), "cartao com fala e sem passo conta como vazio")
    d4._on_progresso("fim", {})
    ok(cartao4.parent() is None, "e sai do chat no fim")

    secao("5e. e o modelo.py avisa a fala pelo caminho sincrono")
    ok('_avisar_progresso(on_progresso, "fala"' in fonte_modelo,
       "existe evento de fase 'fala' no modelo")
    p_fala = inspect.signature(modelo._emitir_fala).parameters
    ok("on_progresso" in p_fala,
       "_emitir_fala (a frase instantanea) leva o progresso")
    p_aviso = inspect.signature(modelo._falar_aviso).parameters
    ok("on_progresso" in p_aviso,
       "_falar_aviso (a frase por ferramenta) tambem")

    # A ordem no CODIGO importa: o aviso de fala tem que sair antes de enfileirar
    # no TTS, senao volta a chegar depois do passo da ferramenta.
    fonte_emitir = inspect.getsource(modelo._emitir_fala)
    i_aviso = fonte_emitir.find('_avisar_progresso(on_progresso, "fala"')
    i_fila = fonte_emitir.find("fila_frases.put(frase)")
    ok(0 <= i_aviso < i_fila,
       "e o aviso sai ANTES de enfileirar no TTS (é isso que garante a ordem)")

    secao("5f. modelo.definir_historico troca o contexto sem sujeira")
    ok(hasattr(modelo, "definir_historico"), "a funcao existe")
    _antes = list(modelo.historico)
    _ref = modelo.historico
    modelo.definir_historico([
        {"role": "user", "content": "analisa a pasta de mods"},
        {"role": "assistant", "content": "Achei 362 jars."},
        {"role": "tool", "content": "nao deve entrar"},
        {"role": "user", "content": "   "},
        {"role": "assistant", "content": ""},
    ])
    ok(len(modelo.historico) == 2, "so user e assistant com texto entram",
       len(modelo.historico))
    ok(all(m["role"] in ("user", "assistant") for m in modelo.historico),
       "nenhum papel de ferramenta sobrou — tool_call sem resultado da 400")
    ok(modelo.historico is _ref,
       "e escreveu NA MESMA lista, nao numa nova (referencia velha nao "
       "envelhece)")
    modelo.definir_historico([])
    ok(modelo.historico == [], "lista vazia limpa o contexto")
    modelo.definir_historico(None)
    ok(modelo.historico == [], "e None tambem, sem estourar")
    modelo.historico[:] = _antes

    # ═════════════════════════════════════════════════════════════
    # 6. O CONTRATO DA JANELA
    # ═════════════════════════════════════════════════════════════

    secao("6. a JanelaEmily nao perdeu nada que o main.py chama")

    # Levantado do main.py de verdade (99 chamadas a atualizar_status, 4 a
    # add_imagem_chat_safe, 3 a progresso_evento...). Reformular a interface por
    # dentro é livre; TIRAR qualquer um destes nomes derruba a Emily no boot, e
    # nenhum teste de widget pegaria isso.
    for nome in ("atualizar_status", "add_imagem_chat_safe",
                 "mostrar_opcao_salvar", "progresso_evento", "iniciar",
                 "carregar_historico", "add_mensagem_emily"):
        ok(callable(getattr(interface.JanelaEmily, nome, None)),
           f"JanelaEmily.{nome}() existe")

    fonte_iface = open("interface.py", encoding="utf-8").read()
    for atributo in ("self.callback_texto", "self.callback_trocar_monitor",
                     "self.callback_visao", "self.callback_arquivo",
                     "self.visao_ativa", "self.root", "self._painel"):
        ok(atributo in fonte_iface,
           f"e {atributo} continua sendo definido no __init__")
    ok("_FakeRoot" in fonte_iface and "def destroy" in fonte_iface,
       "root.destroy() e _painel.destroy() continuam existindo (main.py:1103, "
       "1735 e 1734 chamam)")

    secao("6b. e a tela nova tem as pecas que o Vitor pediu")
    for peca, porque in (
        ("_build_pagina_inicio", "tela inicial organizada"),
        ("_build_pagina_chat", "conversa em tela cheia"),
        ("_build_pagina_config", "botao de configuracoes que acessa tudo"),
        ("_build_sidebar", "barra lateral"),
        ("_alternar_sidebar", "botao pra esconder a barra lateral"),
        ("_mover_input", "uma unica caixa de texto, movida entre as telas"),
        ("_nova_conversa", "conversa nova"),
        ("_abrir_conversa", "abrir uma conversa salva"),
        ("_apagar_conversa", "apagar conversa"),
        ("_recarregar_conversas", "lista de recentes"),
        ("_ir_para_chat", "1a mensagem joga a conversa em tela cheia"),
    ):
        ok(callable(getattr(interface.PainelEmily, peca, None)),
           f"PainelEmily.{peca}()  ({porque})")

    ok("self._ir_para_chat()" in inspect.getsource(interface.PainelEmily._enviar),
       "e mandar mensagem realmente vai pro chat em tela cheia")
    ok('_mover_input("inicio")' in fonte_iface
       and '_mover_input("chat")' in fonte_iface,
       "e o input e movido pros dois lados")
    ok("_build_center" not in inspect.getsource(interface.PainelEmily._build_ui),
       "e a coluna unica velha (que espremia o chat) saiu do _build_ui")

    secao("6c. a LinhaConversa da barra lateral")
    lc = interface.LinhaConversa({"id": "abc123", "titulo": "analisa a pasta de "
                                  "mods ai e me diz o que tem de bom",
                                  "mexida": time.time(), "quantas": 8})
    ok(lc._cid == "abc123", "guarda o id, nao o titulo (titulo muda, id nao)")
    vistos = []
    lc.abrir.connect(lambda cid: vistos.append(("abrir", cid)))
    lc.apagar.connect(lambda cid: vistos.append(("apagar", cid)))
    lc._pedir_apagar()
    ok(vistos == [("apagar", "abc123")], "o x pede pra apagar", vistos)
    ok(not lc._x.isVisibleTo(lc),
       "e o x fica escondido ate o hover — lista de 80 linhas com botao de "
       "apagar sempre visivel e campo minado")
    lc.deleteLater()

    secao("6d. o chat nao nasce com bolha (senao criaria conversa a cada boot)")
    fonte_chat_area = inspect.getsource(interface.PainelEmily._build_chat_area)
    ok("self._add_chat_msg(" not in fonte_chat_area,
       "_build_chat_area nao adiciona mensagem — _add_chat_msg agora GRAVA em "
       "disco, e uma bolha de boas-vindas criaria uma conversa vazia por boot")

    # ═════════════════════════════════════════════════════════════
    # 7. A JANELA DE VERDADE, MONTADA
    # ═════════════════════════════════════════════════════════════

    secao("7. a janela inteira monta sem estourar (o teste que faltava)")

    # Isto existe por causa do NameError que deixou a Emily sem subir. Testar
    # método por método não pega erro de MONTAGEM: basta um atributo que uma
    # coluna espera e outra não cria mais, e a janela morre no __init__ — depois
    # de todos os testes acima passarem.
    #
    # Monta sem show(): nada aparece na tela, mas todo widget é construído.
    import conversas

    painel = None
    try:
        painel = interface.PainelEmily(interface.StatusSignaler())
        ok(True, "PainelEmily() montou — barra de titulo, lateral e as 3 paginas")
    except Exception as e:
        import traceback
        ok(False, "PainelEmily() montou", f"{type(e).__name__}: {e}")
        traceback.print_exc()

if app is not None and painel is not None:
    ok(painel._palco.count() == 3, "o palco tem as tres paginas",
       painel._palco.count())
    ok(painel._palco.currentWidget() is painel._pag_inicio,
       "e abre no inicio, nao numa conversa vazia")
    ok(painel._area_input.parent() is not None,
       "o input tem dono (esta montado em alguma pagina)")

    secao("7a2. colar do clipboard nao pode chegar com a cor da origem")
    # O bug: "fica todo preto bugado quando eu copio e colo algo". QTextEdit
    # aceita rich text por padrao, entao o Ctrl+V traz o HTML de onde o texto
    # veio — cor inclusa. Texto preto de pagina branca chega preto no nosso fundo
    # preto. Stylesheet nao resolve: cor inline no documento ganha dela.
    ok(not painel._campo_texto.acceptRichText(),
       "o campo recusa rich text — colagem entra como texto puro")

    # insertFromMimeData e o caminho REAL do Ctrl+V e do arrasta-e-solta. Nao
    # uso insertHtml: aquilo insere HTML por definicao, ignora o acceptRichText e
    # provaria outra coisa.
    from PyQt6.QtCore import QMimeData

    painel._campo_texto.setPlainText("")
    colado = QMimeData()
    colado.setText("colado de fora")
    colado.setHtml('<span style="color:#000000; background-color:#ffffff;">'
                   'colado de fora</span>')
    painel._campo_texto.insertFromMimeData(colado)
    guardado_html = painel._campo_texto.toHtml().lower().replace(" ", "")
    ok(painel._campo_texto.toPlainText() == "colado de fora",
       "o texto sobrevive a colagem", painel._campo_texto.toPlainText())
    ok("#000000" not in guardado_html,
       "e a cor preta da origem NAO entrou no documento")
    ok("#ffffff" not in guardado_html,
       "nem o fundo branco (era ele que deixava a linha 'toda preta bugada')")
    painel._campo_texto.setPlainText("")

    secao("7a3. cabecalho, conversa e input alinhados na MESMA coluna")
    # Tres larguras maximas iguais e a mesma proporcao: e isso que faz o titulo,
    # as bolhas e a caixa de texto comecarem na mesma vertical. Antes o titulo
    # tinha margem fixa de 18px e as bolhas uma coluna centralizada.
    ok(painel.LARGURA_COLUNA >= 700, "a coluna tem largura de leitura",
       painel.LARGURA_COLUNA)
    alvo = painel._na_coluna(interface.QWidget())
    lay_c = alvo.layout()
    ok(lay_c.count() == 3, "a coluna e stretch-conteudo-stretch", lay_c.count())
    ok(lay_c.stretch(0) == lay_c.stretch(2),
       "com os dois lados iguais (senao a coluna nao fica centrada)",
       (lay_c.stretch(0), lay_c.stretch(2)))
    ok(lay_c.stretch(1) > lay_c.stretch(0),
       "e o conteudo com prioridade sobre as margens",
       (lay_c.stretch(1), lay_c.stretch(0)))
    ok(painel._linha_sidebar.maximumWidth() == 1,
       "e existe uma linha de 1px separando a lateral da conversa",
       painel._linha_sidebar.maximumWidth())
    ok(interface.DIVISOR in painel._linha_sidebar.styleSheet(),
       "pintada com a cor que da pra ver", painel._linha_sidebar.styleSheet())

    secao("7b. navegar entre as paginas leva o input junto")
    painel._abrir_config()
    ok(painel._palco.currentWidget() is painel._pag_config,
       "configuracoes abre como PAGINA, nao como janela solta")
    painel._fechar_config()
    ok(painel._palco.currentWidget() is painel._pag_inicio,
       "e voltar sem conversa nenhuma cai no inicio")

    painel._ir_para_chat()
    ok(painel._palco.currentWidget() is painel._pag_chat,
       "ir pro chat troca a pagina")
    ok(painel._slot_input_chat.indexOf(painel._area_input) >= 0,
       "e o input foi MOVIDO pra pagina de conversa (nao duplicado)")
    ok(painel._slot_input_inicio.indexOf(painel._area_input) < 0,
       "e nao ficou tambem no inicio")

    painel._nova_conversa()
    ok(painel._palco.currentWidget() is painel._pag_inicio,
       "'nova conversa' volta pro inicio")
    ok(painel._slot_input_inicio.indexOf(painel._area_input) >= 0,
       "levando o input de volta")

    secao("7b2. o X encerra a Emily, nao so esconde a janela")

    # Isto e uma REGRESSAO que eu causei: quando refiz a barra de titulo, liguei o
    # X no hide(). Com o header velho fora, foi embora o unico jeito de desligar a
    # Emily pela interface, e o Vitor voltou a precisar de Ctrl+C no terminal.
    ok(callable(getattr(interface.PainelEmily, "_encerrar_emily", None)),
       "_encerrar_emily() existe de novo")
    fonte_barra = inspect.getsource(interface.PainelEmily._build_barra_titulo)
    ok("self._encerrar_emily" in fonte_barra,
       "e o X esta LIGADO nele (nao no hide)")
    i_hide = fonte_barra.find("self.hide")
    i_sair = fonte_barra.find("self._encerrar_emily")
    ok(0 <= i_hide < i_sair,
       "o hide continua existindo, mas no botao de esconder — os dois botoes "
       "fazem coisas diferentes")

    fonte_sair = inspect.getsource(interface.PainelEmily._encerrar_emily)
    ok("QApplication.quit()" in fonte_sair,
       "pede o quit ao Qt — e o que faz o app.exec() retornar e o atexit do "
       "main.py rodar o encerrar_tudo()")
    ok("os._exit(" in fonte_sair,
       "e tem saida forcada de reserva: encerrar_tudo() fala com o Discord, e "
       "rede pendurada na saida deixaria o processo vivo sem janela")
    i_timer = fonte_sair.find("Timer(")
    i_quit = fonte_sair.find("QApplication.quit()")
    ok(0 <= i_timer < i_quit,
       "com o cinto ARMADO antes do quit (armar depois nao serve de nada)")
    ok("daemon = True" in fonte_sair or "daemon=True" in fonte_sair,
       "e o timer e daemon, senao ele mesmo segura o processo por 6s")

    # E o main.py continua tendo pra onde ir.
    ok("def encerrar_tudo" in fonte_main,
       "o main.py tem o encerrar_tudo() que faz a limpeza")
    ok("atexit.register(encerrar_tudo)" in fonte_main,
       "e registrado no atexit — e por isso que o quit() basta")
    i_pmc = fonte_main.find("def encerrar_tudo")
    ok("parar_monitor" in fonte_main[i_pmc:i_pmc + 700]
       and "desconectar_voz" in fonte_main[i_pmc:i_pmc + 700],
       "e ele para o monitor e desconecta a voz do Discord (a parte 'segura')")

    secao("7c. esconder a barra lateral")
    # De novo: ESTADO, não isVisible(). Com a janela nunca mostrada (que é o
    # normal — a Emily vive minimizada no icone), isVisible() e sempre falso, e o
    # botao alternava de escondido pra escondido.
    ok(painel._sidebar_aberta, "a barra comeca aberta")
    painel._alternar_sidebar()
    ok(not painel._sidebar_aberta, "o botao esconde")
    ok(painel._sidebar.isHidden(), "e o widget realmente foi escondido")
    ok(painel._linha_sidebar.isHidden(),
       "e a linha divisoria vai junto — linha solta na borda parece defeito")
    painel._alternar_sidebar()
    ok(painel._sidebar_aberta, "e mostra de novo")
    ok(not painel._sidebar.isHidden(), "com o widget de volta")
    ok(not painel._linha_sidebar.isHidden(), "e a linha tambem")

    secao("7d. mandar mensagem: cria a conversa, salva e vai pra tela cheia")
    conversas.recarregar()
    ok(conversas.listar() == [],
       "montar a janela NAO criou conversa nenhuma no disco",
       len(conversas.listar()))

    enviados = []
    painel._callback_texto = lambda t: enviados.append(t)
    painel._campo_texto.setPlainText("analisa a pasta de mods ai pra mim")
    painel._enviar()
    time.sleep(0.4)   # o callback roda em thread

    ok(painel._palco.currentWidget() is painel._pag_chat,
       "a 1a mensagem joga a conversa em tela cheia — 'exatamente igual "
       "acontece com claude real'")
    ok(enviados == ["analisa a pasta de mods ai pra mim"],
       "o texto foi pro callback (a Emily recebeu)", enviados)
    ok(bool(painel._conversa_id), "e uma conversa nasceu", painel._conversa_id)

    guardadas = conversas.listar()
    ok(len(guardadas) == 1, "gravada no disco", len(guardadas))
    ok(guardadas[0]["titulo"].lower().startswith("analisa"),
       "com titulo tirado da primeira mensagem", guardadas[0]["titulo"])
    msgs = conversas.abrir(painel._conversa_id)
    ok(len(msgs) == 1 and msgs[0]["papel"] == "user",
       "e a mensagem do Vitor esta la", [m["papel"] for m in msgs])

    secao("7e. a resposta dela entra na mesma conversa")
    painel._on_status_changed("falando", "Achei 362 jars na pasta.")
    painel._on_status_changed("aguardando", "")
    msgs = conversas.abrir(painel._conversa_id)
    ok(len(msgs) == 2 and msgs[1]["papel"] == "emily",
       "a fala da Emily foi gravada junto", [m["papel"] for m in msgs])
    ok(msgs[1]["texto"] == "Achei 362 jars na pasta.", "com o texto certo",
       msgs[1]["texto"])

    secao("7f. abrir de novo redesenha a conversa sem duplicar nada")
    cid = painel._conversa_id
    painel._nova_conversa()
    ok(painel._conversa_id == "", "conversa nova nao herda o id da anterior")
    painel._abrir_conversa(cid)
    ok(painel._conversa_id == cid, "abrir volta pro id certo")
    ok(len(conversas.abrir(cid)) == 2,
       "e redesenhar NAO regravou as mensagens (senao dobrava a cada abertura)",
       len(conversas.abrir(cid)))
    bolhas = sum(1 for i in range(painel._chat_layout.count())
                 if isinstance(painel._chat_layout.itemAt(i).widget(),
                               interface.ChatBubble))
    ok(bolhas == 2, "duas bolhas na tela, uma por mensagem", bolhas)

    secao("7g. apagar a conversa aberta limpa a tela")
    painel._apagar_conversa(cid)
    ok(conversas.listar() == [], "saiu do disco", len(conversas.listar()))
    ok(painel._conversa_id == "", "e a tela nao ficou apontando pra um id morto")
    ok(painel._palco.currentWidget() is painel._pag_inicio,
       "voltando pro inicio")

    secao("7h. e o X REALMENTE encerra o processo (nao so em teoria)")

    # As checagens de codigo-fonte acima nao provam que o processo morre. Esta
    # prova: sobe uma janela de verdade num subprocesso, aperta o X e confere que
    # (a) o processo terminou sozinho e (b) o atexit rodou no caminho — que e onde
    # o main.py desconecta a voz do Discord e para o monitor.
    #
    # Subprocesso porque o teste NAO pode se matar junto. _encerrar_emily chama
    # QApplication.quit() e arma um os._exit; rodando aqui, levaria o teste com
    # ele e as secoes seguintes nunca apareceriam.
    import subprocess

    roteiro = os.path.join(_PASTA_TMP, "_prova_saida.py")
    with open(roteiro, "w", encoding="utf-8") as fh:
        fh.write(
            "import atexit, os, sys\n"
            f"sys.path.insert(0, {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))!r})\n"
            f"os.environ['EMILY_ARQUIVO_CONVERSAS'] = "
            f"{os.path.join(_PASTA_TMP, 'saida.json')!r}\n"
            "import interface\n"
            "from PyQt6.QtCore import QTimer\n"
            "from PyQt6.QtWidgets import QApplication\n"
            "atexit.register(lambda: print('ATEXIT-RODOU', flush=True))\n"
            "app = QApplication.instance() or QApplication(sys.argv)\n"
            "p = interface.PainelEmily(interface.StatusSignaler())\n"
            "print('JANELA-DE-PE', flush=True)\n"
            "QTimer.singleShot(400, p._encerrar_emily)\n"
            "sys.exit(app.exec())\n"
        )

    try:
        # Teto de 20s: o cinto de seguranca do proprio _encerrar_emily e de 6s, e
        # se passar disso e porque ele nao funcionou.
        r = subprocess.run([sys.executable, "-u", roteiro],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=20)
        saida_proc = (r.stdout or "") + (r.stderr or "")
        ok(True, "o processo com a janela terminou sozinho, sem Ctrl+C",
           f"codigo {r.returncode}")
        ok("JANELA-DE-PE" in saida_proc,
           "e a janela estava mesmo de pe antes do X")
        ok("ATEXIT-RODOU" in saida_proc,
           "e o atexit rodou — e ele que dispara o encerrar_tudo() do main.py")
        ok("Encerrando a Emily" in saida_proc,
           "pelo caminho limpo do botao", saida_proc.strip().splitlines()[-1:])
        ok("saindo à força" not in saida_proc,
           "e sem precisar da saida forcada de reserva")
    except subprocess.TimeoutExpired:
        ok(False, "o processo com a janela terminou sozinho",
           "PENDUROU 20s — era exatamente isso que obrigava o Ctrl+C")

    painel.deleteLater()

import shutil as _shutil
_shutil.rmtree(_PASTA_TMP, ignore_errors=True)

print()
print("=" * 78)
if RUINS:
    print(f"{RUINS} problema(s).")
else:
    print("A interface nova monta, salva os chats e mostra o que ela esta "
          "fazendo na ordem certa.")
print("=" * 78)
sys.exit(1 if RUINS else 0)

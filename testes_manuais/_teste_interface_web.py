"""
Verificacao da interface web, contra o backend de verdade.

Abre a janela, mede 20 coisas pela ponte (paleta, tipografia, dados reais do
Python, acumulo da fala, progresso de ferramenta, configuracoes) e escreve o
veredito em _teste_interface_web.txt.

Precisa de janela grafica, por isso NAO esta na suite do pytest.
Roda com: python _teste_interface_web.py
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import os, threading, time
os.environ.setdefault("EMILY_EXTRACT_FACTS", "0")
import interface_web as W

LOG = open("testes_manuais/_teste_interface_web.txt", "w", encoding="utf-8")
def diz(*a): print(*a, file=LOG, flush=True)

j = W.JanelaEmily(callback_texto=lambda t: diz("  callback_texto recebeu:", repr(t)))

def sonda():
    for _ in range(80):
        if j._pronta.is_set(): break
        time.sleep(0.25)
    if not j._pronta.is_set():
        diz("PONTE NAO SUBIU"); LOG.close(); os._exit(3)
    q = j._janela.evaluate_js
    falhas = []
    def check(rot, valor, esperado=True):
        ok = (valor == esperado) if not callable(esperado) else esperado(valor)
        diz(f"  {'OK   ' if ok else 'FALHA'} {rot}: {valor!r}")
        if not ok: falhas.append(rot)

    # Conversa-lixo: TODO save disparado pelo teste (as respostas da Emily que
    # atualizar_status grava no fim de cada turno) cai aqui, e some no fim.
    # Sem isto, os atualizar_status("falando",...) do teste criariam conversas
    # soltas na conversas.json do Vitor.
    import conversas as _cv
    _lixo = _cv.criar("")
    j._cid = _lixo

    diz("── a janela ──")
    check("titulo", q("document.title"), "Emily")
    check("fundo quente (sem azul)", q("getComputedStyle(document.body).backgroundColor"), "rgb(28, 27, 25)")
    check("serifada no cumprimento", q('getComputedStyle(document.querySelector(".hero-oi")).fontFamily'),
          lambda v: "Georgia" in str(v))
    check("nenhum roxo no CSS", q(
        "[...document.styleSheets].flatMap(s=>[...s.cssRules].map(r=>r.cssText)).join('').match(/7c4fff|a07eff|5a35c7/gi)||0"), 0)

    diz("── nada por cima, tudo clicavel ──")
    # Os dois bugs que a primeira versao teve: o fundo do modal ficava
    # visivel (interface "apagada") e comia todo clique, porque [hidden]
    # perde de uma regra de display do autor.
    check("fundo do modal escondido",
          q('getComputedStyle(document.querySelector("#modal-fundo")).display'), "none")
    check("linha de anexos escondida",
          q('getComputedStyle(document.querySelector("#anexos")).display'), "none")
    check("nada cobrindo a tela toda", q("""
        (() => {
          const alvos = [...document.querySelectorAll('body > *, .tela')];
          const grandes = alvos.filter(el => {
            const c = getComputedStyle(el), r = el.getBoundingClientRect();
            return c.display !== 'none' && c.pointerEvents !== 'none'
                && r.width > innerWidth * .9 && r.height > innerHeight * .9
                && el.id !== 'corpo' && !el.classList.contains('tela');
          });
          return grandes.map(e => e.id || e.className).join(',') || 'nada';
        })()"""), "nada")
    check("o clique no meio do input chega no input", q("""
        (() => {
          const r = document.querySelector('#entrada').getBoundingClientRect();
          const el = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
          return el && (el.id === 'entrada' || el.closest('#composer')) ? 'chega' : 'bloqueado por ' + (el?.id || el?.className);
        })()"""), "chega")
    check("o clique numa conversa chega nela", q("""
        (() => {
          const c = document.querySelector('.conv');
          const r = c.getBoundingClientRect();
          const el = document.elementFromPoint(r.left + 40, r.top + r.height/2);
          return el && el.closest('.conv') ? 'chega' : 'bloqueado por ' + (el?.id || el?.className);
        })()"""), "chega")

    diz("── o retrato dela ──")
    check("hero tem src", q('!!document.querySelector("#hero-img")?.getAttribute("src")'))
    check("e a imagem CARREGOU de verdade",
          q('(document.querySelector("#hero-img")?.naturalWidth || 0) > 0'))
    check("e nao e um monstro de base64",
          q('(document.querySelector("#hero-img")?.src || "").length'), lambda v: 0 < v < 1_000_000)
    check("e um PNG (emilyimage.png), nao o gif de sprite",
          q('(document.querySelector("#hero-img")?.src || "").startsWith("data:image/png")'))

    diz("── abrir e fechar modal nao trava a tela ──")
    # O bug do congelamento: o overlay do modal (#modal-fundo, position:fixed
    # cobrindo tudo) nao voltava a ficar hidden depois de confirmar, e comia
    # todos os cliques. Abre um modal, confirma, e o overlay TEM que sumir.
    q('window.__mp = modal({titulo:"teste", ok:"ok"});')  # abre
    time.sleep(0.3)
    check("modal abriu visivel",
          q('getComputedStyle(document.querySelector("#modal-fundo")).display'),
          lambda v: v != 'none')
    q('document.querySelector("#m-sim")?.click();')       # confirma
    time.sleep(0.6)
    check("overlay sumiu depois de confirmar",
          q('document.querySelector("#modal-fundo").hidden'))
    check("nada cobrindo a tela depois do modal", q("""
        (() => {
          const r = document.querySelector('#entrada').getBoundingClientRect();
          const el = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
          return el && (el.id === 'entrada' || el.closest('#composer')) ? 'chega' : 'bloqueado';
        })()"""), "chega")

    diz("── a ponte é a de VERDADE, não a de oficina ──")
    # O pywebview tambem serve por http local, e o modo oficina era ligado
    # por protocolo: ele instalava a api de mentira em cima da real e a
    # Emily abria com conversas de amostra em vez das do Vitor.
    check("nao caiu no modo oficina",
          q("""[...document.querySelectorAll('.conv-titulo')]
                .some(t => /Preço da RTX 5090|Mods pesados do modpack/.test(t.textContent))"""),
          False)

    diz("── dados reais do Python ──")
    check("conversas carregadas", q('document.querySelectorAll(".conv").length'), lambda v: v >= 1)
    check("agrupadas por data", q('document.querySelectorAll(".grupo-rot").length'), lambda v: v >= 1)
    check("botao renomear por conversa", q('!!document.querySelector(".conv [data-ren]")'))
    check("botao apagar por conversa", q('!!document.querySelector(".conv [data-del]")'))
    check("sugestoes", q('document.querySelectorAll(".sugestao").length'), 4)

    diz("── a fala dela pelo status ──")
    for frase in ("Ó,", "achei o problema:", "falta o **import** na linha 12."):
        j.atualizar_status("falando", frase); time.sleep(0.35)
    check("acumulou numa mensagem so", q('document.querySelectorAll(".msg.de-emily").length'), 1)
    check("texto completo", q('document.querySelector(".msg.de-emily .msg-corpo").innerText'),
          lambda v: "achei o problema" in str(v) and "linha 12" in str(v))
    check("markdown virou negrito", q('!!document.querySelector(".msg.de-emily strong")'))
    check("cursor de streaming", q('!!document.querySelector(".msg.escrevendo")'))
    j.atualizar_status("aguardando"); time.sleep(0.3)
    check("cursor sai quando ela para", q('!document.querySelector(".msg.escrevendo")'))

    diz("── markdown rico: títulos, tabela e modo casual ──")
    q("""(() => {
      const alvo=document.querySelector('#fluxo-in');
      const antigos=[...alvo.querySelectorAll('.smoke-md')]; antigos.forEach(e=>e.remove());
      const rica=novaMsg('emily', markdown(
        '## Comparação\\n\\n| Modelo | Velocidade |\\n|---|---:|\\n| GLM | 90 tokens/s |\\n| Claude | 70 tokens/s |\\n\\n### Veredito\\n\\nVai de **GLM**.'
      ));
      rica.classList.add('smoke-md');
      const casual=novaMsg('emily', markdown('Tá bom, vejo isso depois.'));
      casual.classList.add('smoke-md','smoke-casual');
      return true;
    })()""")
    check("headers viram títulos sem vazar jogo da velha",
          q('!!document.querySelector(".smoke-md h2") && !!document.querySelector(".smoke-md h3") '
            '&& !document.querySelector(".smoke-md .msg-corpo").innerText.includes("##")'))
    check("comparação vira tabela responsiva",
          q('!!document.querySelector(".smoke-md .md-tabela-wrap > table") '
            '&& getComputedStyle(document.querySelector(".smoke-md .md-tabela-wrap")).overflowX==="auto"'))
    check("resposta rica recebe tratamento tipográfico",
          q('document.querySelector(".smoke-md .msg-corpo").classList.contains("md-estruturado")'))
    check("conversa simples continua sem modo estruturado",
          q('!document.querySelector(".smoke-casual .msg-corpo").classList.contains("md-estruturado")'))
    q("document.querySelectorAll('.smoke-md').forEach(e=>e.remove())")

    diz("── markdown rico ao vivo: final não reabre bolha achatada ──")
    _rica_voz = ("#### Preço na API\n\n"
                 "| Uso | Até 272k | Passou de 272k |\n"
                 "|---|---:|---:|\n"
                 "| Entrada | US$ 10 / 1M | US$ 20 / 1M |\n"
                 "| Saída | US$ 50 / 1M | US$ 75 / 1M |\n\n"
                 "#### Veredito\n\nAinda não usaria como cérebro principal.")
    _antes_voz = q('document.querySelectorAll(".msg.de-emily").length')
    j.progresso_evento("inicio", {})
    j.progresso_evento("delta", {"texto": _rica_voz, "acompanhar_fala": True})
    j.atualizar_status("falando", "Preço na API")
    time.sleep(0.25)
    j.progresso_evento("resposta", {"texto": _rica_voz})
    time.sleep(0.35)
    check("resposta final ao vivo fica em uma única mensagem",
          q('document.querySelectorAll(".msg.de-emily").length'), int(_antes_voz) + 1)
    check("a mensagem ao vivo termina com tabela formatada",
          q('!![...document.querySelectorAll(".msg.de-emily")].pop()?.querySelector(".md-tabela-wrap > table")'))
    check("nenhum delta tardio deixa tabela em texto bruto",
          q('![...document.querySelectorAll(".msg.de-emily")].pop()?.querySelector(".msg-corpo").innerText.includes("|---")'))
    check("cursor fecha assim que a resposta final chega",
          q('![...document.querySelectorAll(".msg.de-emily")].pop()?.classList.contains("escrevendo")'))
    j.atualizar_status("aguardando"); time.sleep(0.2)

    diz("── layout das mensagens (balão do Vitor, corrido o dela) ──")
    j._push("msg", {"autor": "user", "texto": "oi emily, tá boa?"}); time.sleep(0.35)
    # A mensagem do Vitor: encostada à direita e com fundo de balão.
    check("mensagem do Vitor alinha à direita",
          q('getComputedStyle(document.querySelector(".msg.de-user")).alignSelf'), "flex-end")
    check("mensagem do Vitor tem balão (fundo)",
          q('getComputedStyle(document.querySelector(".msg.de-user .msg-corpo")).backgroundColor'),
          lambda v: v not in ("rgba(0, 0, 0, 0)", "transparent"))
    check("mensagem do Vitor não ocupa a largura toda",
          q('(document.querySelector(".msg.de-user").offsetWidth) / (document.querySelector(".fluxo-in").offsetWidth)'),
          lambda v: float(v) < 0.9)
    # A da Emily: largura cheia, sem balão.
    check("mensagem da Emily ocupa a largura (stretch)",
          q('getComputedStyle(document.querySelector(".msg.de-emily")).alignSelf'), "stretch")
    check("mensagem da Emily NÃO tem balão",
          q('getComputedStyle(document.querySelector(".msg.de-emily .msg-corpo")).backgroundColor'),
          lambda v: v in ("rgba(0, 0, 0, 0)", "transparent"))
    check("os rótulos de autor (Você/Emily) continuam lá",
          q('!!document.querySelector(".msg.de-user .msg-autor") && !!document.querySelector(".msg.de-emily .msg-autor")'))

    diz("── progresso de ferramenta ──")
    j.progresso_evento("ferramenta", {"nome": "ver_tela", "args": {"pergunta": "o que tem"}})
    j.progresso_evento("resultado", {"nome": "ver_tela", "resultado": "VS Code com erro na linha 12.",
                                            "ok": True, "mudou": False, "duracao": 0.42})
    time.sleep(0.4)
    check("passo apareceu", q('document.querySelectorAll(".passo").length'), 1)
    check("passo marcado como ok", q('!!document.querySelector(".passo.ok")'))
    check("activity card tem nucleo, timeline e contador",
          q('!!document.querySelector(".progresso-nucleo") && '
            '!!document.querySelector(".passo-trilho") && '
            'document.querySelector(".progresso-contador").textContent.replace(/\\s/g,"")==="1/1"'))
    check("passo exibe estado real e duracao",
          q('document.querySelector(".passo-status").textContent+"|"+'
            'document.querySelector(".passo-tempo").textContent'), "Concluído|420ms")
    j.progresso_evento("ferramenta", {"nome": "organizar_downloads", "args": {"pasta": "Downloads"}})
    j.progresso_evento("resultado", {"nome": "organizar_downloads", "resultado": "Separei os arquivos.",
                                            "ok": True, "mudou": True, "duracao": 1.2})
    j.progresso_evento("ferramenta", {"nome": "abrir_site", "args": {"url": "inválida"}})
    j.progresso_evento("resultado", {"nome": "abrir_site", "resultado": "Não consegui abrir.",
                                            "ok": False, "mudou": False, "erro": "url_invalida",
                                            "duracao": 0.08})
    time.sleep(0.2)
    check("alteracao e falha recebem estados visuais proprios",
          q('!!document.querySelector(".passo.mudou") && !!document.querySelector(".passo.falhou")'))
    check("contador acompanha tres etapas concluidas",
          q('document.querySelector(".progresso-contador").textContent.replace(/\\s/g,"")'), "3/3")
    # Repetições da mesma ferramenta não podem criar um card infinito: ficam
    # numa única linha, mas o contador preserva o número real de execuções.
    j.progresso_evento("ferramenta", {"nome": "pesquisar_internet", "args": {"consulta": "fonte 1"}})
    j.progresso_evento("resultado", {"nome": "pesquisar_internet", "resultado": "Fonte 1", "ok": True})
    j.progresso_evento("ferramenta", {"nome": "pesquisar_internet", "args": {"consulta": "fonte 2"}})
    j.progresso_evento("resultado", {"nome": "pesquisar_internet", "resultado": "Fonte 2", "ok": True})
    j.progresso_evento("ferramenta", {"nome": "pesquisar_internet", "args": {"consulta": "fonte 3"}})
    j.progresso_evento("resultado", {"nome": "pesquisar_internet", "resultado": "Fonte 3", "ok": True})
    time.sleep(0.2)
    check("pesquisas repetidas usam uma unica linha com multiplicador",
          q('document.querySelectorAll(".passo[data-nome=\\"pesquisar_internet\\"]").length+"|"+'
            'document.querySelector(".passo[data-nome=\\"pesquisar_internet\\"] .passo-repeticao").textContent'),
          "1|×3")
    check("contador preserva as seis execucoes reais",
          q('document.querySelector(".progresso-contador").textContent.replace(/\\s/g,"")'), "6/6")
    j.progresso_evento("fim", {})
    check("falha muda o resumo do cartao",
          q('document.querySelector(".progresso").classList.contains("com-falha") && '
            'document.querySelector(".progresso-rot").textContent==="Concluído com atenção"'))

    diz("── processo separado da resposta, e recolhível ──")
    # Um turno de verdade: comentário de processo ("peraí...") + ferramenta,
    # e a resposta final. O preâmbulo NÃO pode colar na resposta.
    j._push("msg", {"autor": "user", "texto": "olha o status do servidor de mine"})
    time.sleep(0.2)
    j.progresso_evento("inicio", {})
    j.progresso_evento("fala", {"texto": "peraí, deixa eu carregar as ferramentas do servidor aqui"})
    j.progresso_evento("fala", {"texto": "agora estou comparando os dados"})
    j.progresso_evento("ferramenta", {"nome": "status_servidor_mc", "args": {}})
    j.progresso_evento("resultado", {"nome": "status_servidor_mc", "resultado": "Broxas SMP ligado, 4874MB.",
                                            "ok": True, "mudou": False})
    time.sleep(0.3)
    # A resposta final chega pelo status, JÁ COLADA no preâmbulo (é o bug):
    j.atualizar_status("falando", "peraí, deixa eu carregar as ferramentas do servidor aquiTá ligada sim, rodando faz um dia e meio.")
    time.sleep(0.4)
    _bolha = q('[...document.querySelectorAll(".msg.de-emily .msg-corpo")].pop()?.innerText || ""')
    check("resposta final NÃO cola no preâmbulo", _bolha,
          lambda v: "Tá ligada sim" in str(v) and "carregar as ferramentas" not in str(v))
    check("o comentário de processo foi pro painel, não pra bolha",
          q('!!document.querySelector(".passo.fala")'))
    check("comentario tem tratamento de atualizacao da Emily",
          q('[...document.querySelectorAll(".passo.fala .passo-txt small")].pop()?.textContent'),
          "Atualização da Emily")
    check("comentarios atualizam uma unica faixa viva",
          q('document.querySelectorAll(".passo.fala").length+"|"+'
            'document.querySelector(".passo.fala .passo-nota").textContent+"|"+'
            'document.querySelector(".passo-fala-contador").textContent'),
          "1|agora estou comparando os dados|2 atualizações")
    j.atualizar_status("aguardando")
    j.progresso_evento("fim", {})
    time.sleep(0.3)
    # A resposta SALVA no disco também tem que vir sem o preâmbulo colado.
    _salvas = [m for m in _cv.abrir(_lixo)
               if (m.get("papel") or m.get("role")) in ("emily", "assistant")]
    check("a resposta SALVA também não cola o preâmbulo",
          (_salvas[-1].get("texto") or _salvas[-1].get("content") or "") if _salvas else "",
          lambda v: "Tá ligada sim" in str(v) and "carregar as ferramentas" not in str(v))
    # Depois de terminar: o painel recolhe (sai o 'aberto') e vira clicável.
    _ultimo_prog = 'document.querySelector(".progresso:last-of-type")'
    check("painel de processo recolheu ao terminar",
          q(f'{_ultimo_prog} && !{_ultimo_prog}.classList.contains("aberto")'))
    check("e dá pra reabrir clicando",
          q(f'(() => {{ const p={_ultimo_prog}; if(!p) return false; p.querySelector(".progresso-topo").click(); const ok=p.classList.contains("aberto"); p.querySelector(".progresso-topo").click(); return ok; }})()'))

    diz("── código: bloco formatado, colorido, com linguagem e copiar ──")
    # A resposta CRUA (com ``` e quebras de linha) chega pelo progresso
    # 'resposta' e reescreve a bolha. É o que conserta o código que vinha
    # numa linha só, sem realce, com a linguagem errada.
    _codigo = ("Ó, um exemplo simples:\n\n"
               "```python\n"
               "def login(user, senha):\n"
               "    # confere no banco\n"
               "    msg = \"bem-vindo\"\n"
               "    if usuarios.get(user) == senha:\n"
               "        return True\n"
               "    return False\n"
               "```")
    j.progresso_evento("resposta", {"texto": _codigo})
    time.sleep(0.4)
    check("tem bloco de código", q('!!document.querySelector(".msg.de-emily .bloco-cod")'))
    check("mostra a linguagem certa (Python)",
          q('[...document.querySelectorAll(".bloco-cod-topo span")].pop()?.textContent'), "Python")
    check("NÃO ficou tudo numa linha só (preservou quebras)",
          q('([...document.querySelectorAll(".bloco-cod code")].pop()?.innerText.match(/\\n/g)||[]).length'),
          lambda v: int(v) >= 4)
    check("tem realce (palavra-chave colorida)",
          q('!!document.querySelector(".bloco-cod .tk-kw")'))
    check("tem realce (string e comentário)",
          q('!!document.querySelector(".bloco-cod .tk-str") && !!document.querySelector(".bloco-cod .tk-com")'))
    check("tem botão de copiar", q('!!document.querySelector(".bloco-cod .btn-copiar-cod")'))
    check("a linguagem não vazou pro corpo do código",
          q('([...document.querySelectorAll(".bloco-cod code")].pop()?.innerText||"").trim().startsWith("python")'),
          False)
    # Fecha o turno; a resposta com código deve ser SALVA com a cerca intacta.
    j.atualizar_status("aguardando"); time.sleep(0.2)
    _salvas_cod = [m for m in _cv.abrir(_lixo)
                   if (m.get("papel") or m.get("role")) in ("emily", "assistant")]
    check("o código é salvo com a cerca ``` e as quebras de linha",
          (_salvas_cod[-1].get("texto") or _salvas_cod[-1].get("content") or "") if _salvas_cod else "",
          lambda v: "```python" in str(v) and "def login" in str(v) and "\n" in str(v))

    diz("── barra lateral arrastável ──")
    _larg = 'parseInt(getComputedStyle(document.documentElement).getPropertyValue("--lateral-w"))'
    # Arrasta a alça pra ~360px.
    q("""(() => {
      const a = document.querySelector('#lateral-resize');
      a.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:264}));
      window.dispatchEvent(new MouseEvent('mousemove', {bubbles:true, clientX:360}));
      window.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
    })()""")
    time.sleep(0.2)
    check("arrastar aumenta a largura da barra", q(_larg), lambda v: 340 <= int(v) <= 380)
    # Arrasta pra bem perto da borda: recolhe inteira.
    q("""(() => {
      const a = document.querySelector('#lateral-resize');
      a.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:360}));
      window.dispatchEvent(new MouseEvent('mousemove', {bubbles:true, clientX:80}));
      window.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
    })()""")
    time.sleep(0.2)
    check("puxar até a borda recolhe a barra inteira",
          q('document.body.classList.contains("sem-lateral")'))
    check("recolhida, a barra sai da tela (margin negativa)",
          q('parseInt(getComputedStyle(document.querySelector(".lateral")).marginLeft) < 0'))
    # O chat continua utilizável e a coluna de leitura segue centrada.
    check("o palco ocupa a largura toda com a barra recolhida",
          q('document.querySelector(".palco").offsetWidth / document.querySelector(".corpo").offsetWidth'),
          lambda v: float(v) > 0.95)
    # Reabre arrastando.
    q("""(() => {
      const a = document.querySelector('#lateral-resize');
      a.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:0}));
      window.dispatchEvent(new MouseEvent('mousemove', {bubbles:true, clientX:250}));
      window.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
    })()""")
    time.sleep(0.2)
    check("arrastar de volta reabre a barra",
          q('!document.body.classList.contains("sem-lateral")'))

    diz("── configuracoes ──")
    q("irPara('config')"); time.sleep(1.0)
    # A tela tem 4 secoes: Abrir rapido, Automacao, Memoria, Este computador.
    # A secao "Modos" foi REMOVIDA: os 3 modos (escrito, controle de tela,
    # monitorar jogo) seguem por voz/comando e o "escutar Discord" virou o
    # mesmo controle que "Acompanhar o Discord". Sem listar_modos, a tela
    # tambem parou de esperar a chamada lenta que importava o catalogo inteiro.
    check("as 4 secoes aparecem numa passada so",
          q('document.querySelectorAll(".secao").length'), lambda v: int(v) >= 4)
    check("coluna unica de 720px", q('getComputedStyle(document.querySelector(".config-in")).maxWidth'), "720px")
    check("TV: botao Adicionar fica compacto no cabecalho", q("""
        (() => {
          const b = document.querySelector('#cfg-tv-add');
          const r = b?.getBoundingClientRect();
          return !!b && b.closest('.secao-cab') && r.width < 130 && r.height <= 36;
        })()"""))
    check("TV: icone de adicionar nao estoura o botao", q("""
        (() => {
          const r = document.querySelector('#cfg-tv-add svg')?.getBoundingClientRect();
          return !!r && r.width <= 16 && r.height <= 16;
        })()"""))
    check("memoria: mostra uma PAGINA, nao os 140 de uma vez",
          q('document.querySelectorAll(".fato").length'), lambda v: 1 <= int(v) <= 8)
    check("memoria: tem controle de paginacao",
          q('!!document.querySelector(".paginacao") || document.querySelectorAll(".fato").length <= 8'))
    check("a secao Modos saiu de vez",
          q('!document.querySelector("#cfg-modos") && '
            'document.querySelectorAll("[data-chave^=\'modo:\']").length === 0'))
    check("Discord tem UM controle so, na Automacao",
          q('document.querySelectorAll("[data-chave=\'monitor_discord\']").length'), 1)

    diz("── music player repaginado e minimizacao sem icone orfao ──")
    q("irPara('inicio')"); time.sleep(0.3)
    q('document.querySelector("#btn-music").click()'); time.sleep(0.8)
    check("biblioteca abre como dialog",
          q('document.querySelector("#modal-player .modal-player-caixa").getAttribute("role")'),
          "dialog")
    check("biblioteca tem tocar e filtro de favoritas",
          q('!!document.querySelector("#pl-tocar-tudo") && !!document.querySelector("#pl-filtro-fav")'))
    check("busca e lista continuam acessiveis",
          q('!!document.querySelector("#pl-query") && !!document.querySelector("#pl-lista")'))
    q('document.querySelector("#modal-player-fechar").click()')
    # Não chama YouTube nem persiste: injeta uma faixa só na máquina visual.
    q("""(() => {
      Player.playlist = [{video_id:'aaaaaaaaaaa', titulo:'Faixa de teste', thumb:''}];
      Player.indice = 0; Player._faixaAtual = Player.playlist[0]; Player.tocando = true;
      Player._persistir = () => {};
      Player._pintaBarra(); Player.minimizar(); return true;
    })()""")
    check("minimizar esconde a barra e cria um unico resgate",
          q('document.querySelector("#player-barra").hidden && document.querySelectorAll("#player-resgate").length'), 1)
    q('Player.fechar()')
    check("fechar remove o resgate e a margem do player",
          q('!document.querySelector("#player-resgate") && !document.body.classList.contains("com-player")'))

    diz("── Emily Code: identidade propria e chats isolados ──")
    q("irPara('code', {forcar:true})"); time.sleep(1.3)
    check("modo Code ativa tema e cabecalho de workspace",
          q('document.body.classList.contains("modo-code") && !!document.querySelector(".code-workspace-topo")'))
    check("entrada ganha linguagem propria",
          q('document.querySelector("#code-prompt").textContent'), "emily://workspace")
    check("botao novo muda para Nova sessao",
          q('document.querySelector("#btn-novo span").textContent'), "Nova sessão")
    check("sidebar Code nao tem IDs duplicados",
          q("""(() => { const a=[...document.querySelectorAll('.conv-code')]
            .map(e=>e.dataset.cid); return a.every(Boolean)&&a.length===new Set(a).size; })()"""))
    q("""(() => {
      const s=document.querySelector('#code-saida'); s.innerHTML='';
      codeRenderMensagem('user','corrige o fluxo de autenticação');
      codeRenderMensagem('emily','Achei o problema em **auth.py**.');
      codeAdicionarAcao('code_ler_arquivo',{arquivo:'auth.py'});
      return true;
    })()""")
    check("usuario e Emily tem componentes diferentes",
          q('!!document.querySelector(".term-user") && !!document.querySelector(".term-emily") '
            '&& getComputedStyle(document.querySelector(".term-user")).borderLeftColor '
            '!== getComputedStyle(document.querySelector(".term-emily")).borderLeftColor'))
    check("acao mostra tipo contextual sem repetir icone generico",
          q('document.querySelector(".code-acao-tipo").textContent'), "READ")
    check("grade e animacao ambiente existem",
          q('!!document.querySelector(".code-grade") && !!document.querySelector(".code-scanline")'))
    q("irPara('inicio', {forcar:true})"); time.sleep(0.5)
    check("sair do Code remove tema imediatamente",
          q('!document.body.classList.contains("modo-code")'))
    check("chats Code nao vazam na interface normal",
          q('document.querySelectorAll(".conv-code").length'), 0)
    check("rotulo volta para Nova conversa",
          q('document.querySelector("#btn-novo span").textContent'), "Nova conversa")

    diz("── composer: modelo, raciocinio e menu do + ──")
    q("irPara('inicio')"); time.sleep(0.6)
    check("o quadrado laranja de foco saiu do campo de digitar",
          q('(function(){var t=document.querySelector("#entrada");t.focus();'
            'var c=getComputedStyle(t);return c.outlineStyle==="none"&&c.boxShadow==="none";})()'))
    check("a pilula mostra o modelo em uso",
          q('document.querySelector("#sel-modelo-nome").textContent'),
          lambda v: bool(str(v).strip()) and str(v).strip() != "Modelo")
    check("a pilula mostra o nivel de raciocinio",
          q('document.querySelector("#sel-racio-nome").textContent'),
          lambda v: str(v) in ("Baixo", "Médio", "Alto"))
    check("o menu de modelo lista as opcoes do provedor atual",
          q('(function(){document.querySelector("#sel-modelo").click();'
            'var i=[...document.querySelectorAll(".popover-item")];'
            'var r=i.length>=1&&i.every(b=>b.textContent.trim().length>0);'
            'document.body.click();return r;})()'))
    check("o menu de raciocinio tem os tres niveis",
          q('(function(){document.querySelector("#sel-racio").click();'
            'var n=document.querySelectorAll(".popover-item").length;'
            'document.body.click();return n;})()'), 3)
    check("o + abre os atalhos do que ela sabe fazer",
          q('(function(){document.querySelector("#btn-add").click();'
            'var n=document.querySelectorAll(".popover-item").length;'
            'document.body.click();return n;})()'), lambda v: int(v) >= 6)

    diz("── perfil editavel ──")
    q("irPara('perfil')"); time.sleep(0.8)
    check("clicar no canto abre o editor de perfil",
          q('!!document.querySelector("#perf-nome") && !!document.querySelector("#perf-pers") '
            '&& !!document.querySelector("#perf-trocar-foto")'))
    check("o nome vem preenchido do Python",
          q('document.querySelector("#perf-nome").value'), lambda v: bool(str(v).strip()))
    q("irPara('inicio')"); time.sleep(0.4)

    diz("── a resposta da Emily É SALVA no histórico ──")
    # O bug do "histórico faltando coisa": só a mensagem do Vitor era gravada,
    # e ao reabrir a conversa as respostas dela sumiam. Agora atualizar_status
    # acumula a fala e grava quando o turno acaba. (Tudo cai na conversa-lixo.)
    j._registrar_na_conversa("user", "teste de persistencia da resposta")
    for f in ("Opa!", "achei sim, tá tudo certo."):
        j.atualizar_status("falando", f)
    j.atualizar_status("aguardando")   # fim do turno -> grava a resposta
    _msgs = _cv.abrir(_lixo)
    _papeis = [m.get("papel") or m.get("role") for m in _msgs]
    check("gravou a mensagem do Vitor E a resposta da Emily",
          _papeis, lambda v: "user" in v and ("emily" in v or "assistant" in v))
    _resp = " ".join(m.get("texto") or m.get("content") or "" for m in _msgs
                     if (m.get("papel") or m.get("role")) in ("emily", "assistant"))
    check("a resposta salva tem o texto inteiro dela",
          _resp, lambda v: "achei sim" in str(v))

    diz("── erros no console ──")
    check("zero", q("(window.__jsErros||0)"), 0)

    _cv.apagar(_lixo)   # limpa a conversa-lixo do teste

    diz("")
    diz(f"{len(falhas)} falha(s)" + (f": {falhas}" if falhas else ""))
    LOG.close()
    os._exit(1 if falhas else 0)

threading.Thread(target=sonda, daemon=True).start()
j.iniciar()

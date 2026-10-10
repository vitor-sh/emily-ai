"""Regressões do caminho sem ferramenta: modelo -> bridge -> interface web."""

from __future__ import annotations

import queue
import threading
import time
from types import SimpleNamespace


def _delta(texto=None, finish=None):
    escolha = SimpleNamespace(
        delta=SimpleNamespace(content=texto, tool_calls=None),
        finish_reason=finish,
    )
    return SimpleNamespace(choices=[escolha])


def test_previa_do_resultado_na_interface_nao_envia_pesquisa_inteira():
    import interface_web

    ponte = interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    eventos = []
    ponte._push = lambda evento, dados: eventos.append((evento, dados))
    dados = {"nome": "pesquisar_internet", "resultado": "A" * 26000, "ok": True}

    ponte.progresso_evento("resultado", dados)

    assert dados["resultado"] == "A" * 26000
    assert eventos == [
        ("progresso", {"fase": "resultado", "dados": {
            "nome": "pesquisar_internet", "resultado": "A" * 500, "ok": True,
        }}),
    ]


def test_pergunta_factual_pesquisa_quando_modelo_escolhe_ferramenta(monkeypatch):
    import ferramentas
    import llm
    import modelo
    import politica_agente
    monkeypatch.setattr(politica_agente, "revisar_apos_ferramentas", lambda pedido,texto,*args: {"continuar":False,"texto":texto,"tarefa_encerrada":True})

    class Fluxo:
        chamadas = []

        preambulo = ""
        def __init__(self, texto, chamadas=None):
            self.texto_final = texto
            self.chamadas = chamadas or []

        def quer_ferramenta(self):
            return bool(self.chamadas)

        def texto(self):
            return iter([self.texto_final])

    respostas = iter([
        Fluxo("", [llm.ChamadaFerramenta("1", "pesquisar_internet", '{"consulta":"benchmarks Astra Sol"}')]),
        Fluxo("O comparativo encontrado está na fonte oficial."),
    ])
    buscas = []

    def executar(nome, args, **_kwargs):
        buscas.append((nome, args))
        return ferramentas.ResultadoFerramenta(
            "--- Fonte 1: Comparativo oficial ---\nSite: example.org\n"
            "URL: https://example.org/comparativo\nDados encontrados.",
            ok=True, mudou=False)

    monkeypatch.setattr(llm, "chamar_com_ferramentas", lambda *_a, **_k: next(respostas))
    monkeypatch.setattr(ferramentas, "esquemas_com_dominios", lambda *_a, **_k: [{"type":"function","function":{"name":"pesquisar_internet"}}])
    monkeypatch.setattr(ferramentas, "executar_estruturado", executar)
    monkeypatch.setattr(modelo, "_parece_pedido_de_acao", lambda _texto: False)
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda _extra="": [])
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "_envelhecer_dominios", lambda: None)
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: "")
    monkeypatch.setattr(modelo, "registrar_ferramenta_executada", lambda *_a: None)
    monkeypatch.setattr(modelo, "_falar_aviso", lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, "_tentar_continuar_truncada", lambda *_a, **_k: False)

    eventos = []
    anterior = list(modelo.historico)
    try:
        modelo.historico.clear()
        resposta = modelo.conversar_com_ferramentas(
            "E os benchmarks do Astra e do Sol?",
            on_progresso=lambda fase, dados: eventos.append((fase, dados)),
            canal="web")
    finally:
        modelo.historico[:] = anterior

    assert resposta == "O comparativo encontrado está na fonte oficial."
    assert [nome for nome, _ in buscas] == ["pesquisar_internet"]
    assert "benchmarks" in str(buscas[0][1]).lower()
    assert not any("Não consigo confirmar" in d.get("texto", "")
                   for fase, d in eventos if fase == "delta")
    assert any(fase == "resultado" and d["ok"] for fase, d in eventos)


def test_ferramenta_textual_na_ultima_volta_emite_inicio_e_resultado(monkeypatch):
    import ferramentas
    import llm
    import modelo
    import politica_agente
    monkeypatch.setattr(politica_agente, "revisar_apos_ferramentas", lambda pedido,texto,*args: {"continuar":False,"texto":texto,"tarefa_encerrada":True})

    class Fluxo:
        chamadas = []
        preambulo = ""
        def __init__(self, texto):
            self._texto = texto

        def quer_ferramenta(self):
            return False

        def texto(self):
            return iter([self._texto])

    respostas = iter([
        Fluxo("<function=pesquisar_internet><parameter=consulta>teste</parameter></function>"),
        Fluxo("Não consegui verificar agora."),
    ])
    monkeypatch.setattr(llm, "chamar_com_ferramentas", lambda *_a, **_k: next(respostas))
    monkeypatch.setattr(ferramentas, "esquemas_com_dominios", lambda *_a, **_k: [{"type":"function","function":{"name":"pesquisar_internet"}}])
    monkeypatch.setattr(
        ferramentas, "executar_estruturado",
        lambda *_a, **_k: ferramentas.ResultadoFerramenta(
            "Sem fontes disponíveis.", ok=False, mudou=False),
    )
    monkeypatch.setattr(modelo, "MAX_VOLTAS_FERRAMENTA", 1)
    monkeypatch.setattr(modelo, "_parece_pedido_de_acao", lambda _texto: False)
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda _extra="": [])
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "_envelhecer_dominios", lambda: None)
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: "")
    monkeypatch.setattr(modelo, "registrar_ferramenta_executada", lambda *_a: None)
    monkeypatch.setattr(modelo, "_falar_aviso", lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, "_tentar_continuar_truncada", lambda *_a, **_k: False)

    eventos = []
    historico_original = list(modelo.historico)
    try:
        modelo.historico.clear()
        resposta = modelo.conversar_com_ferramentas(
            "teste", on_progresso=lambda fase, dados: eventos.append((fase, dados)))
    finally:
        modelo.historico[:] = historico_original

    assert resposta == "Não consegui verificar agora."
    assert [fase for fase, _ in eventos if fase in {"ferramenta", "resultado"}] == [
        "ferramenta", "resultado"]
    assert next(d for fase, d in eventos if fase == "resultado")["ok"] is False


def test_chat_sem_ferramenta_publica_cedo_e_oculta_tags_fish(monkeypatch):
    import ferramentas
    import interface_web
    import llm
    import modelo

    consumidos = []
    partes = [
        "[speaking sadly]",
        "Isso aparece ",
        "antes de a resposta ",
        "inteira terminar.",
    ]

    def stream_falso():
        for indice, texto in enumerate(partes):
            consumidos.append(texto)
            yield _delta(texto, finish="stop" if indice == len(partes) - 1 else None)

    def chamar_falso(*_args, **_kwargs):
        return llm.FluxoComFerramentas(iter(stream_falso()))

    monkeypatch.setattr(llm, "chamar_com_ferramentas", chamar_falso)
    monkeypatch.setattr(ferramentas, "esquemas_com_dominios", lambda *_a, **_k: [])
    monkeypatch.setattr(modelo, "_parece_pedido_de_acao", lambda _texto: False)
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda _extra="": [])
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "_envelhecer_dominios", lambda: None)
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: "")

    eventos = []
    ponte = interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    ponte._sprite = None
    ponte._ultimo_status = ("aguardando", "")
    ponte._falando = False
    ponte._resposta_emily = ""
    ponte._falas_processo = []
    ponte._resposta_crua = ""
    ponte._filtro_tags_stream = interface_web._FiltroStreamingTagsDeVoz()
    ponte._push = lambda evento, dados: eventos.append(
        (evento, dict(dados), len(consumidos)))

    historico_original = list(modelo.historico)
    fila = queue.Queue()
    historico_cru = ""
    try:
        modelo.historico.clear()
        ponte.progresso_evento("inicio", {})
        resposta = modelo.conversar_com_ferramentas(
            "como você está hoje?",
            fila_frases=fila,
            on_progresso=ponte.progresso_evento,
            canal="web",
        )
        ponte.progresso_evento("resposta", {"texto": resposta})
        historico_cru = modelo.historico[-1]["content"]
    finally:
        modelo.historico[:] = historico_original

    deltas = [(dados["texto"], lidos) for evento, dados, lidos in eventos
              if evento == "delta"]
    assert deltas
    assert deltas[0] == ("Isso aparece ", 2)
    assert deltas[0][1] < len(partes)

    # As instruções continuam disponíveis para o TTS e no texto/histórico cru.
    assert resposta.startswith("[speaking sadly]")
    assert "[speaking sadly]" in historico_cru
    falas = []
    while not fila.empty():
        item = fila.get_nowait()
        if item is not None:
            falas.append(item)
    assert "[speaking sadly]" in " ".join(falas)

    # Nenhuma das duas rotas visuais (deltas ou resposta final) pode vazar tag.
    textos_visuais = [dados.get("texto", "") for evento, dados, _ in eventos
                      if evento in {"delta", "resposta"}]
    assert textos_visuais
    assert all("[speaking" not in texto for texto in textos_visuais)
    assert textos_visuais[-1] == "Isso aparece antes de a resposta inteira terminar."


def test_sanitizador_cobre_formatos_reais_sem_apagar_markdown():
    import interface_web

    bruto = (
        "[speaking softly] Oi. [speaking with emphasis] Presta atenção. "
        "[com um tom de mistério] Segredo. [documentação](https://example.com) [1]"
    )
    visivel = interface_web._texto_visual_sem_tags_de_voz(bruto)

    assert visivel == (
        " Oi.  Presta atenção.  Segredo. "
        "[documentação](https://example.com) [1]"
    )


def test_stream_preserva_espacos_iniciais_dos_chunks_para_tts():
    """Regressão de `euentendooque`: lstrip por chunk colava fala e legenda."""
    import modelo

    partes = [
        "Olha...", " eu", " entendo", " o", " que", " você", " quer",
        " dizer,", " mas", " tem", " uma", " diferença", " importante.",
    ]
    limpos = [
        modelo._limpar_vazamento_de_registro(
            pedaco, preservar_inicio=(indice > 0))
        for indice, pedaco in enumerate(partes)
    ]

    assert "".join(limpos) == (
        "Olha... eu entendo o que você quer dizer, mas tem uma diferença importante.")

    fila = queue.Queue()
    acumulador = modelo._AcumuladorDeFrases(fila)
    for pedaco in limpos:
        acumulador.adicionar(pedaco)
    acumulador.finalizar()
    itens = []
    while not fila.empty():
        itens.append(fila.get_nowait())
    falado = " ".join(itens)
    assert "eu entendo o que você quer dizer" in falado
    assert "euentendo" not in falado
    assert "oque" not in falado


def test_fluxo_completo_entrega_ao_fish_os_espacos_dos_chunks(monkeypatch):
    """Modelo -> _transmitir -> acumulador -> fila TTS, sem `euentendooque`."""
    import ferramentas
    import llm
    import modelo

    partes = [
        "Olha...", " eu", " entendo", " o", " que", " você", " quer",
        " dizer,", " mas", " tem", " uma", " diferença", " importante.",
    ]

    def stream_falso():
        for indice, texto in enumerate(partes):
            yield _delta(texto, finish="stop" if indice == len(partes) - 1 else None)

    monkeypatch.setattr(
        llm, "chamar_com_ferramentas",
        lambda *_a, **_k: llm.FluxoComFerramentas(iter(stream_falso())))
    monkeypatch.setattr(ferramentas, "esquemas_com_dominios", lambda *_a, **_k: [])
    monkeypatch.setattr(modelo, "_parece_pedido_de_acao", lambda _texto: False)
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda _extra="": [])
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "_envelhecer_dominios", lambda: None)
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: "")

    historico_original = list(modelo.historico)
    fila = queue.Queue()
    try:
        modelo.historico.clear()
        resposta = modelo.conversar_com_ferramentas(
            "me explica isso", fila_frases=fila, canal="voz")
    finally:
        modelo.historico[:] = historico_original

    itens = []
    while not fila.empty():
        item = fila.get_nowait()
        if item is not None:
            itens.append(item)
    falado = " ".join(itens)

    esperado = (
        "Olha... eu entendo o que você quer dizer, mas tem uma diferença importante.")
    assert resposta == esperado
    assert esperado in falado
    assert "euentendo" not in falado
    assert "oque" not in falado


def test_push_serializa_evaluate_js_entre_threads():
    """WebKitGTK não pode receber dois scripts Python -> JS simultaneamente."""
    import interface_web

    class JanelaFalsa:
        def __init__(self):
            self._trava = threading.Lock()
            self.ativos = 0
            self.max_ativos = 0
            self.scripts = []

        def evaluate_js(self, script):
            with self._trava:
                self.ativos += 1
                self.max_ativos = max(self.max_ativos, self.ativos)
            time.sleep(0.01)
            with self._trava:
                self.scripts.append(script)
                self.ativos -= 1

    ponte = interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    ponte._pronta = threading.Event()
    ponte._pronta.set()
    ponte._lock = threading.Lock()
    ponte._lock_js = threading.RLock()
    ponte._fila_inicial = []
    ponte._janela = JanelaFalsa()

    threads = [
        threading.Thread(target=ponte._push, args=(
            "status", {"estado": "falando", "texto": f"frase {indice}"}))
        for indice in range(12)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert ponte._janela.max_ativos == 1
    assert len(ponte._janela.scripts) == len(threads)
    assert all("window.Emily.on" in script for script in ponte._janela.scripts)

# As 30 formas que vazavam na tela antes do filtro cobrir tags compostas. Cada
# uma veio do histórico real do Vitor (12,7% das ocorrências de colchete
# escapavam do sanitizador e apareciam dentro das respostas dela).
_TAGS_REAIS_QUE_VAZAVAM = (
    "pause, speaking seriously", "pause, speaking with emphasis",
    "pause, speaking gently", "pause, speaking carefully",
    "pause, speaking more gently", "pause, speaking with concern",
    "pause, speaking thoughtfully", "pause, speaking with sadness",
    "pause, speaking sadly", "pause, speaking with gentle concern",
    "pause, speaking gently but firmly", "pause, speaking more seriously",
    "pause, speaking softly", "pause, speaking excited",
    "pause, speaking firmly", "pause, speaking more directly",
    "pause, speaking with a hint of teasing", "pause, speaking with frustration",
    "pause, speaking with realization", "pause, speaking with warmth",
    "laughs wickedly", "laughs awkwardly", "laughs maniacally",
    "laughs maniacally and prolonged", "sobbing quietly",
    "angry and intense", "cheerful", "curious and concerned",
    "curious but concerned", "shouting angrily", "speaking firmly but warmly",
    "speaking carefully but honestly",
)


def test_sanitizador_cobre_as_tags_compostas_reais():
    """Tags Fish compostas do histórico real não podem mais vazar pra tela."""
    import interface_web

    for tag in _TAGS_REAIS_QUE_VAZAVAM:
        visivel = interface_web._texto_visual_sem_tags_de_voz(f"[{tag}] Oi Vitor.")
        assert visivel.strip() == "Oi Vitor.", f"tag vazou: [{tag}] -> {visivel!r}"

    # E o caminho de streaming, com a tag fatiada no meio dos deltas, não pode
    # exibir nem meia tag nem fragmento dela.
    filtro = interface_web._FiltroStreamingTagsDeVoz()
    pedacos = ("Oi Vitor [pause, spea", "king with gentle concern] e cê? [1]")
    saida = "".join(filtro.alimentar(p) for p in pedacos)
    assert "pause" not in saida and "concern" not in saida, saida
    assert "[1]" in saida, saida   # referência legítima permanece


def test_sanitizador_python_e_js_tem_a_mesma_whitelist():
    """
    As duas barreiras precisam concordar. O backend filtra o stream/status;
    o app.js filtra o histórico reaberto e eventos de integrações. Se a lista
    divergir, a dedup de frase (ditoNoCartao vs textoStream) desalinha e a
    bolha sai duplicada — o "embaralhado" que o Vitor viu.
    """
    import re as _re
    from pathlib import Path

    RAIZ = Path(__file__).resolve().parent.parent
    py = (RAIZ / "interface_web.py").read_text(encoding="utf-8")
    js = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

    # Captura o literal COMPLETO da whitelist. No Python ele é uma string
    # concatenada em várias linhas, então o teto é a linha do flag
    # (re.IGNORECASE), que é removida antes da comparação — senão a palavra
    # "ignorecase" entraria na contagem só de um lado.
    from fish_voz_texto import LIVRE
    py_literal = LIVRE.pattern
    js_literal = _re.search(
        r"const PADRAO_TAG_VOZ_LIVRE = (.*?);\n", js, _re.S).group(1)
    # Palavras de 3+ letras do alternation. Menores ("um", "a", "an", "\s",
    # "\b", o flag "/i") são sintaxe de regex e não dizem nada sobre a lista.
    termos_py = sorted(set(_re.findall(r"[a-z]{3,}", py_literal.replace("re.IGNORECASE", ""))))
    termos_js = sorted(set(_re.findall(r"[a-z]{3,}", js_literal)))
    assert termos_py == termos_js, (
        f"whitelist Python e JS divergem: "
        f"só no Python: {sorted(set(termos_py) - set(termos_js))}, "
        f"só no JS: {sorted(set(termos_js) - set(termos_py))}")


def test_canal_de_voz_guarda_stream_e_revela_prefixo_com_a_fala(monkeypatch):
    """Voz não inunda a WebView; revela o stream fiel quando o áudio começa."""
    import ferramentas
    import interface_web
    import llm
    import modelo

    partes = ["[speaking thoughtfully]", "É, eu imagino... ",
              "quando você tá com tudo isso na cabeça."]

    def stream_falso():
        for indice, texto in enumerate(partes):
            yield _delta(texto, finish="stop" if indice == len(partes) - 1 else None)

    monkeypatch.setattr(
        llm, "chamar_com_ferramentas",
        lambda *_a, **_k: llm.FluxoComFerramentas(iter(stream_falso())))
    monkeypatch.setattr(ferramentas, "esquemas_com_dominios", lambda *_a, **_k: [])
    monkeypatch.setattr(modelo, "_parece_pedido_de_acao", lambda _texto: False)
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda _extra="": [])
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "_envelhecer_dominios", lambda: None)
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: "")

    eventos = []
    ponte = interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    ponte._sprite = None
    ponte._ultimo_status = ("aguardando", "")
    ponte._falando = False
    ponte._resposta_emily = ""
    ponte._falas_processo = []
    ponte._resposta_crua = ""
    ponte._filtro_tags_stream = interface_web._FiltroStreamingTagsDeVoz()
    ponte._push = lambda evento, dados: eventos.append((evento, dict(dados)))

    historico_original = list(modelo.historico)
    fila = queue.Queue()
    try:
        modelo.historico.clear()
        ponte.progresso_evento("inicio", {})
        resposta = modelo.conversar_com_ferramentas(
            "como eu lido com isso?", fila_frases=fila,
            on_progresso=ponte.progresso_evento, canal="voz")
    finally:
        modelo.historico[:] = historico_original

    # Nenhum token individual atravessa a ponte no canal de voz: isso evitou a
    # corrida de evaluate_js que perdia chunks de espaço e desenhava
    # "euimagino/quandovocê". O texto fiel fica em memória Python.
    assert not [dados for evento, dados in eventos if evento == "delta"]
    assert ponte._stream_visual_voz == (
        "É, eu imagino... quando você tá com tudo isso na cabeça.")

    # Ao iniciar a reprodução, o status leva a fotografia cumulativa fiel até o
    # fim da unidade (sem tags Fish, com todos os espaços originais).
    ponte.atualizar_status("falando", "[speaking thoughtfully] É, eu imagino... ")
    status = [dados for evento, dados in eventos if evento == "status"][-1]
    assert status["texto"].strip() == "É, eu imagino..."
    assert status["texto_prefixo"] == "É, eu imagino..."
    assert resposta.startswith("[speaking thoughtfully]")


def test_resposta_final_de_voz_nao_reabre_bolha_com_delta_tardio():
    """A fonte final formatada deve ser o último evento visual do turno."""
    import interface_web

    resposta = (
        "#### Preço na API\n\n"
        "| Uso | Até 272k | Passou de 272k |\n"
        "|---|---:|---:|\n"
        "| Entrada | US$ 10 / 1M | US$ 20 / 1M |"
    )
    eventos = []
    ponte = interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    ponte._falas_processo = []
    ponte._resposta_crua = ""
    ponte._filtro_tags_stream = interface_web._FiltroStreamingTagsDeVoz()
    ponte._lock_stream_visual_voz = threading.Lock()
    ponte._stream_visual_voz = ""
    ponte._stream_visual_voz_indice = 0
    ponte._stream_visual_voz_ativo = False
    ponte._push = lambda evento, dados: eventos.append((evento, dict(dados)))

    ponte.progresso_evento("inicio", {})
    ponte.progresso_evento("delta", {
        "texto": resposta,
        "acompanhar_fala": True,
    })
    assert ponte._stream_visual_voz == resposta

    eventos.clear()
    ponte.progresso_evento("resposta", {"texto": resposta})

    assert eventos == [("resposta", {"texto": resposta})]
    assert ponte._stream_visual_voz == ""
    assert ponte._stream_visual_voz_indice == 0
    assert ponte._stream_visual_voz_ativo is False


def test_push_unicode_nao_trunca_javascript_no_webkitgtk():
    import json
    import interface_web
    scripts=[]
    ponte=interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    ponte._pronta=threading.Event(); ponte._pronta.set()
    ponte._janela=type('Janela',(),{'evaluate_js':lambda _,script:scripts.append(script)})()
    text='Não consegui fechar: ação 🧡 \\ caminho "teste" \u2028 fim'
    ponte._push('status',{'texto':text})
    assert len(scripts)==1 and scripts[0].isascii()
    payload=scripts[0].split('))(',1)[1][:-1]
    assert json.loads(payload)['d']['texto']==text

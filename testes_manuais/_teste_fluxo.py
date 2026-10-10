"""
Teste determinístico do FluxoComFerramentas, sem rede.

Simula os deltas que o endpoint manda em várias ordens diferentes e checa se a
camada percebe que existe chamada de ferramenta. Roda com: python _teste_fluxo.py

Dois formatos de fio são cobertos, porque a Emily já viu os dois:

  NIM (cenários A-E):     tool_call chega FATIADO em vários deltas — o id vem
                          num, os argumentos vêm em pedaços nos seguintes.

  Proxy (cenários F-K):   tool_call chega num ÚNICO chunk no FIM do stream,
                          com os argumentos completos, e várias ferramentas
                          na MESMA lista em vez de em deltas separados. É o
                          que faz proxy que traduz Anthropic -> OpenAI: ele
                          só monta o chunk depois de fechar o conteúdo.

A consequência desse formato é que a decisão antecipada da janela de
80 chars NUNCA dispara quando existe preâmbulo: a ferramenta só aparece na
releitura de .chamadas depois de esgotar .texto(). Isso deixou de ser exceção
e virou o caminho principal, então tem que estar testado.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
from types import SimpleNamespace
import queue

import llm
import modelo


def _testar_stream_de_texto_e_frases():
    """Delta visual é imediato; TTS recebe texto cru só em unidades faláveis."""
    fila = queue.Queue()
    deltas = []
    acumulador = modelo._AcumuladorDeFrases(fila, on_delta=deltas.append)
    partes = ["[exci", "ted] Agora eu consigo mostrar ",
              "o texto antes do áudio ficar pronto, ", "sem trocar a ordem."]
    for parte in partes:
        acumulador.adicionar(parte)
    acumulador.finalizar()
    frases = []
    while not fila.empty():
        frases.append(fila.get_nowait())
    assert deltas == partes, "cada delta do modelo deve ser publicado imediatamente"
    fala = " ".join(frases)
    assert "[excited]" in fala, "tags Fish devem permanecer no TTS"
    assert "Agora eu consigo mostrar" in fala and "sem trocar a ordem." in fala
    # Vírgula não deve mais abrir outra requisição Fish: microáudios faziam o
    # player alcançar a síntese seguinte e a voz freiava entre orações. Resposta
    # curta termina no ponto e continua saindo assim que o stream fecha.
    assert len(frases) == 1, "vírgula não deve fragmentar a resposta em microáudios"


_testar_stream_de_texto_e_frases()


def delta(texto=None, tool=None, finish=None):
    """Chunk no formato do NIM: tool_call fatiado entre deltas."""
    tool_calls = None
    if tool is not None:
        idx, tid, nome, args = tool
        tool_calls = [SimpleNamespace(
            index=idx, id=tid,
            function=SimpleNamespace(name=nome, arguments=args),
        )]
    d = SimpleNamespace(content=texto, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=d, finish_reason=finish)])


def delta_gateway(tools):
    """
    Chunk no formato de proxy: UM delta com a lista completa.

    tools: lista de (id, nome, argumentos_json_completo)
    """
    tool_calls = [
        SimpleNamespace(
            index=i, id=tid, type="function",
            function=SimpleNamespace(name=nome, arguments=args),
        )
        for i, (tid, nome, args) in enumerate(tools)
    ]
    d = SimpleNamespace(content=None, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=d, finish_reason=None)])


CENARIOS = {
    "A) tool_call puro (sem texto antes)": [
        delta(tool=(0, "c1", "ver_tela", "")),
        delta(tool=(0, None, None, "{}")),
        delta(finish="tool_calls"),
    ],
    "B) UM \\n antes do tool_call": [
        delta(texto="\n"),
        delta(tool=(0, "c1", "ver_tela", "")),
        delta(tool=(0, None, None, "{}")),
        delta(finish="tool_calls"),
    ],
    "C) preambulo falado antes do tool_call": [
        delta(texto="Peraí, "),
        delta(texto="vou olhar sua tela."),
        delta(tool=(0, "c1", "ver_tela", "")),
        delta(tool=(0, None, None, "{}")),
        delta(finish="tool_calls"),
    ],
    "D) texto puro, nenhuma ferramenta": [
        delta(texto="kkkk "),
        delta(texto="verdade mesmo."),
        delta(finish="stop"),
    ],
    "E) duas ferramentas em paralelo": [
        delta(tool=(0, "c1", "abrir_pasta", '{"nome":"downloads"}')),
        delta(tool=(1, "c2", "abrir_site", '{"site":"youtube"}')),
        delta(finish="tool_calls"),
    ],

    # ── Formato de proxy: chunk único no fim ───────────────────────
    "F) GATEWAY: ferramenta sem preambulo": [
        delta_gateway([("c1", "ver_tela", "{}")]),
        delta(finish="tool_calls"),
    ],
    "G) GATEWAY: so whitespace antes": [
        delta(texto="\n"),
        delta(texto="  "),
        delta_gateway([("c1", "ver_tela", "{}")]),
        delta(finish="tool_calls"),
    ],
    "H) GATEWAY: preambulo curto antes": [
        delta(texto="Peraí, "),
        delta(texto="vou olhar."),
        delta_gateway([("c1", "ver_tela", "{}")]),
        delta(finish="tool_calls"),
    ],
    # Este é o caso que o formato de proxy torna comum: preâmbulo maior que
    # a janela de 80 chars, então quer_ferramenta() devolve False e a
    # ferramenta só aparece na releitura de .chamadas.
    "I) GATEWAY: preambulo LONGO (>80 chars)": [
        delta(texto="Deixa eu dar uma olhada com calma na sua tela pra ver o que "
                    "exatamente está acontecendo nesse erro, "),
        delta(texto="porque pode ser várias coisas diferentes."),
        delta_gateway([("c1", "ver_tela", "{}")]),
        delta(finish="tool_calls"),
    ],
    "J) GATEWAY: duas ferramentas no MESMO chunk": [
        delta_gateway([
            ("c1", "abrir_pasta", '{"nome":"downloads"}'),
            ("c2", "abrir_site", '{"site":"youtube"}'),
        ]),
        delta(finish="tool_calls"),
    ],
    "K) GATEWAY: texto puro, nenhuma ferramenta": [
        delta(texto="Tô de boa aqui, "),
        delta(texto="por que a pergunta?"),
        delta(finish="stop"),
    ],
}

ESPERADO_FERRAMENTA = {
    "A) tool_call puro (sem texto antes)": 1,
    "B) UM \\n antes do tool_call": 1,
    "C) preambulo falado antes do tool_call": 1,
    "D) texto puro, nenhuma ferramenta": 0,
    "E) duas ferramentas em paralelo": 2,
    "F) GATEWAY: ferramenta sem preambulo": 1,
    "G) GATEWAY: so whitespace antes": 1,
    "H) GATEWAY: preambulo curto antes": 1,
    "I) GATEWAY: preambulo LONGO (>80 chars)": 1,
    "J) GATEWAY: duas ferramentas no MESMO chunk": 2,
    "K) GATEWAY: texto puro, nenhuma ferramenta": 0,
}

_PREAMBULO_LONGO = ("Deixa eu dar uma olhada com calma na sua tela pra ver o que "
                    "exatamente está acontecendo nesse erro, porque pode ser "
                    "várias coisas diferentes.")

ESPERADO_TEXTO = {
    "A) tool_call puro (sem texto antes)": "",
    "B) UM \\n antes do tool_call": "",
    "C) preambulo falado antes do tool_call": "Peraí, vou olhar sua tela.",
    "D) texto puro, nenhuma ferramenta": "kkkk verdade mesmo.",
    "E) duas ferramentas em paralelo": "",
    "F) GATEWAY: ferramenta sem preambulo": "",
    "G) GATEWAY: so whitespace antes": "",
    "H) GATEWAY: preambulo curto antes": "Peraí, vou olhar.",
    "I) GATEWAY: preambulo LONGO (>80 chars)": _PREAMBULO_LONGO,
    "J) GATEWAY: duas ferramentas no MESMO chunk": "",
    "K) GATEWAY: texto puro, nenhuma ferramenta": "Tô de boa aqui, por que a pergunta?",
}

falhas = 0
for nome, chunks in CENARIOS.items():
    fluxo = llm.FluxoComFerramentas(iter(chunks))

    # Consome exatamente como o laço de modelo.py passa a fazer.
    falado = ""
    if fluxo.quer_ferramenta():
        falado = fluxo.preambulo          # preâmbulo vai pro TTS
        executadas = fluxo.chamadas
    else:
        falado = "".join(fluxo.texto())   # streamou o texto pro TTS
        executadas = fluxo.chamadas       # releitura obrigatória

    esperado = ESPERADO_FERRAMENTA[nome]
    esperado_txt = ESPERADO_TEXTO[nome]
    ok = len(executadas) == esperado and falado.strip() == esperado_txt
    if not ok:
        falhas += 1
    print(f"{'OK   ' if ok else 'FALHA'} {nome}")
    print(f"       executadas={len(executadas)} (esperado {esperado})  "
          f"nomes={[c.nome for c in executadas]}")
    print(f"       falado={falado.strip()!r} (esperado {esperado_txt!r})")

print()
print(f"{falhas} cenário(s) com falha.")
raise SystemExit(1 if falhas else 0)

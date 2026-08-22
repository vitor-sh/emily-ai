"""
Teste ponta a ponta do laço conversar_com_ferramentas, sem rede e sem TTS.

Substitui llm.chamar_com_ferramentas por um roteiro de streams falsos e checa
se a ferramenta realmente EXECUTA nos casos que antes falhavam.

Roda com: python _teste_laco.py
"""
import os
import queue
from types import SimpleNamespace

os.environ.setdefault("EMILY_EXTRACT_FACTS", "0")

import ferramentas
import llm
import modelo


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
    Chunk no formato do kiro-gateway: UM delta com a lista completa de
    ferramentas, emitido no FIM do stream.

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


# ── Ferramenta de teste ───────────────────────────────────────────
executadas = []

ferramentas.registrar(ferramentas.Ferramenta(
    nome="ver_tela_teste",
    descricao="Ferramenta falsa de teste.",
    propriedades={},
    executar=lambda: (executadas.append("ver_tela_teste"),
                      "A tela mostra um erro de compilação na linha 12.")[1],
))


def rodar(nome_do_caso, roteiro, pedido):
    """Roda um turno com o roteiro de streams e devolve (falas, ferramentas)."""
    executadas.clear()
    modelo.historico.clear()
    restos = list(roteiro)

    def falso_chamar(mensagens, ferramentas=None, rota_nome=None, max_tokens=None,
                     stream=False, obrigar_ferramenta=False):
        chunks = restos.pop(0) if restos else [delta(texto="Sem mais nada.", finish="stop")]
        return llm.FluxoComFerramentas(iter(chunks))

    original = llm.chamar_com_ferramentas
    llm.chamar_com_ferramentas = falso_chamar
    fila = queue.Queue()
    try:
        resposta = modelo.conversar_com_ferramentas(pedido, fila_frases=fila)
    finally:
        llm.chamar_com_ferramentas = original

    falas = []
    while not fila.empty():
        item = fila.get()
        if item is not None:
            falas.append(item)
    return resposta, list(executadas), falas


CASOS = []

# 1. O caso que estava quebrado: preâmbulo falado + tool_call na mesma resposta.
CASOS.append((
    "preambulo + tool_call (era o bug)",
    "olha minha tela e me diz o que ta errado",
    [
        [delta(texto="Peraí, "), delta(texto="deixa eu ver."),
         delta(tool=(0, "c1", "ver_tela_teste", "{}")), delta(finish="tool_calls")],
        [delta(texto="Tem um erro de compilação na linha 12."), delta(finish="stop")],
    ],
    ["ver_tela_teste"],
))

# 2. GLM abrindo a resposta com um "\n" antes do tool_call.
CASOS.append((
    "newline solto antes do tool_call",
    "olha minha tela",
    [
        [delta(texto="\n"), delta(tool=(0, "c1", "ver_tela_teste", "{}")),
         delta(finish="tool_calls")],
        [delta(texto="Tá tudo normal aí."), delta(finish="stop")],
    ],
    ["ver_tela_teste"],
))

# 3. Conversa pura: não deve chamar ferramenta nenhuma.
CASOS.append((
    "conversa pura, nenhuma ferramenta",
    "kkkk voce e muito engracada",
    [
        [delta(texto="Eu sei, "), delta(texto="né kkkk."), delta(finish="stop")],
    ],
    [],
))

# 4. tool_call puro, sem preâmbulo (caminho que já funcionava).
CASOS.append((
    "tool_call puro",
    "olha minha tela agora",
    [
        [delta(tool=(0, "c1", "ver_tela_teste", "{}")), delta(finish="tool_calls")],
        [delta(texto="Vi sim, tem um erro ali."), delta(finish="stop")],
    ],
    ["ver_tela_teste"],
))

# 5. Preâmbulo LONGO (passa dos 80 chars da janela de decisão) e só então o
#    tool_call. Aqui a decisão inicial é "texto", e a ferramenta só aparece na
#    releitura de .chamadas — exatamente o ramo que antes perdia a chamada.
_LONGO = ("Deixa eu dar uma olhada aqui com calma na sua tela pra ver o que "
          "exatamente está acontecendo nesse erro, porque pode ser várias coisas. ")
CASOS.append((
    "preambulo LONGO + tool_call tardio (pedido de acao)",
    "olha minha tela e me diz o que ta errado",
    [
        [delta(texto=_LONGO), delta(tool=(0, "c1", "ver_tela_teste", "{}")),
         delta(finish="tool_calls")],
        [delta(texto="Achei: erro na linha 12."), delta(finish="stop")],
    ],
    ["ver_tela_teste"],
))

# 6. Frase SEM cara de pedido de ação, e o modelo decide usar ferramenta depois
#    de escrever bastante texto. O texto é falado na hora (streaming) e a
#    ferramenta roda mesmo assim.
CASOS.append((
    "conversa que virou ferramenta tardia",
    "sei la, ta estranho isso aqui",
    [
        [delta(texto=_LONGO), delta(tool=(0, "c1", "ver_tela_teste", "{}")),
         delta(finish="tool_calls")],
        [delta(texto="É erro de compilação."), delta(finish="stop")],
    ],
    ["ver_tela_teste"],
))

# ═════════════════════════════════════════════════════════════════
# FORMATO DO KIRO-GATEWAY
#
# O gateway emite os tool_calls num ÚNICO chunk no FIM do stream, com os
# argumentos já completos. Isso muda qual RAMO do laço é exercitado: com
# qualquer preâmbulo maior que a janela de 80 chars, quer_ferramenta()
# devolve False e a ferramenta só aparece na releitura de .chamadas.
#
# No NIM esse ramo era exceção. Com o gateway virou o caminho principal, e
# por isso ganhou cobertura própria aqui.
# ═════════════════════════════════════════════════════════════════

# 7. Gateway, ferramenta pura sem nenhum texto antes.
CASOS.append((
    "GATEWAY: ferramenta sem preambulo",
    "olha minha tela agora",
    [
        [delta_gateway([("c1", "ver_tela_teste", "{}")]), delta(finish="tool_calls")],
        [delta(texto="Erro na linha 12."), delta(finish="stop")],
    ],
    ["ver_tela_teste"],
))

# 8. Gateway, só whitespace antes do chunk de ferramenta.
CASOS.append((
    "GATEWAY: so whitespace antes da ferramenta",
    "olha minha tela",
    [
        [delta(texto="\n"), delta(texto="  "),
         delta_gateway([("c1", "ver_tela_teste", "{}")]), delta(finish="tool_calls")],
        [delta(texto="Tá tudo normal."), delta(finish="stop")],
    ],
    ["ver_tela_teste"],
))

# 9. Gateway, preâmbulo curto: cabe na janela de decisão.
CASOS.append((
    "GATEWAY: preambulo curto",
    "olha minha tela e me diz o que ta errado",
    [
        [delta(texto="Peraí, "), delta(texto="deixa eu ver."),
         delta_gateway([("c1", "ver_tela_teste", "{}")]), delta(finish="tool_calls")],
        [delta(texto="Erro de compilação na linha 12."), delta(finish="stop")],
    ],
    ["ver_tela_teste"],
))

# 10. Gateway, preâmbulo LONGO: estoura a janela, decisão vira "texto", e a
#     ferramenta só é encontrada na releitura. É o caminho principal agora.
CASOS.append((
    "GATEWAY: preambulo LONGO, ferramenta na releitura",
    "olha minha tela e me diz o que ta errado",
    [
        [delta(texto=_LONGO),
         delta_gateway([("c1", "ver_tela_teste", "{}")]), delta(finish="tool_calls")],
        [delta(texto="Achei: erro na linha 12."), delta(finish="stop")],
    ],
    ["ver_tela_teste"],
))

# 11. Gateway, texto puro: zero ferramentas.
CASOS.append((
    "GATEWAY: texto puro, nenhuma ferramenta",
    "kkkk voce e muito engracada",
    [
        [delta(texto="Eu sei, "), delta(texto="né kkkk."), delta(finish="stop")],
    ],
    [],
))

falhas = 0
for nome, pedido, roteiro, esperado in CASOS:
    resposta, rodaram, falas = rodar(nome, roteiro, pedido)
    ok = rodaram == esperado
    if not ok:
        falhas += 1
    print(f"{'OK   ' if ok else 'FALHA'} {nome}")
    print(f"       ferramentas executadas={rodaram} (esperado {esperado})")
    print(f"       resposta final={resposta!r}")
    print(f"       falas no TTS={falas}")
    print()

print(f"{falhas} caso(s) com falha.")
raise SystemExit(1 if falhas else 0)

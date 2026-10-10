"""
Teste do catálogo em camadas e do registro de ações, sem rede e sem TTS.

O que ele prova, e por que cada coisa importa
─────────────────────────────────────────────
1. O catálogo padrão do caminho de voz NÃO tem as 106 ferramentas de Discord e
   de Minecraft. Era isso que custava ~23.500 tokens em toda chamada.
2. Quando o modelo chama abrir_ferramentas('discord'), a chamada SEGUINTE recebe
   as ferramentas de Discord de verdade — não basta o laço dizer que abriu.
3. Escalonar não conta como AGIR. Se contasse, um turno que abriu o domínio e
   depois não chamou nada passaria pela guarda de promessa vazia.
4. O que ela executou aparece no system prompt com nome, argumentos e resultado
   inteiro — e NÃO entra na conversa como nota de texto.
5. Domínio inventado devolve erro útil em vez de quebrar o turno.

Roda com: python _teste_escalonamento.py
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import json
import os
import queue
from types import SimpleNamespace

os.environ.setdefault("EMILY_EXTRACT_FACTS", "0")

import ferramentas
import llm
import modelo


falhas = []


def ok(condicao, rotulo, detalhe=""):
    print(f"{'OK   ' if condicao else 'FALHA'} {rotulo}")
    if detalhe:
        print(f"       {detalhe}")
    if not condicao:
        falhas.append(rotulo)


def delta(texto=None, tool=None, finish=None):
    tool_calls = None
    if tool is not None:
        idx, tid, nome, args = tool
        tool_calls = [SimpleNamespace(
            index=idx, id=tid,
            function=SimpleNamespace(name=nome, arguments=args),
        )]
    d = SimpleNamespace(content=texto, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=d, finish_reason=finish)])


# ── Ferramenta falsa DENTRO do grupo 'discord' ────────────────────
# Precisa ser do grupo sob demanda pra provar que ela só aparece depois do
# escalonamento. Usar uma ferramenta real de Discord aqui tentaria falar com o
# discord.py de verdade.
executadas = []

ferramentas.registrar(ferramentas.Ferramenta(
    nome="teste_discord_falsa",
    grupo="discord",
    descricao="Ferramenta falsa de teste, do grupo discord.",
    propriedades={"canal": {"type": "string", "description": "canal"}},
    obrigatorios=["canal"],
    executar=lambda canal: (executadas.append(("teste_discord_falsa", canal)),
                            f"Mensagem enviada em #{canal}.")[1],
))


def rodar(roteiro, pedido):
    """
    Roda um turno com streams falsos e devolve o que o laço mandou ao modelo.

    Guarda os catálogos de CADA chamada: é assim que se prova que o escalonamento
    mudou a mesa, e não só o log.
    """
    executadas.clear()
    modelo.historico.clear()
    modelo.limpar_ferramentas_executadas()
    modelo._dominios_abertos.clear()

    restos = list(roteiro)
    catalogos = []
    sistemas = []

    def falso_chamar(mensagens, ferramentas=None, rota_nome=None, max_tokens=None,
                     stream=False, obrigar_ferramenta=False, proibir_ferramenta=False,
                     **_extra):
        catalogos.append([f["function"]["name"] for f in (ferramentas or [])])
        sistemas.append(next((m["content"] for m in mensagens
                              if m.get("role") == "system"), ""))
        chunks = restos.pop(0) if restos else [delta(texto="Acabou.", finish="stop")]
        return llm.FluxoComFerramentas(iter(chunks))

    original = llm.chamar_com_ferramentas
    llm.chamar_com_ferramentas = falso_chamar
    fila = queue.Queue()
    try:
        resposta = modelo.conversar_com_ferramentas(pedido, fila_frases=fila)
    finally:
        llm.chamar_com_ferramentas = original

    return SimpleNamespace(resposta=resposta, catalogos=catalogos,
                           sistemas=sistemas, executadas=list(executadas))


print("=" * 70)
print("1. O CATÁLOGO PADRÃO É PEQUENO")
print("=" * 70)

padrao = {f["function"]["name"] for f in ferramentas.esquemas_padrao()}
todas = {f["function"]["name"] for f in ferramentas.esquemas()}

ok("abrir_app" in padrao, "ferramenta do dia a dia está na mesa",
   "abrir_app presente")
ok("banir_membro_discord" not in padrao,
   "ferramenta de Discord NÃO está na mesa por padrão")
ok("status_servidor_mc" not in padrao,
   "ferramenta de Minecraft NÃO está na mesa por padrão")
ok("abrir_ferramentas" in padrao, "a ferramenta de escalonamento está na mesa")

tam_padrao = len(json.dumps(ferramentas.esquemas_padrao(), ensure_ascii=False))
tam_tudo = len(json.dumps(ferramentas.esquemas(), ensure_ascii=False))
reducao = 100 - tam_padrao * 100 // tam_tudo
ok(reducao >= 70, f"redução de tamanho do catálogo é relevante",
   f"{len(padrao)} de {len(todas)} ferramentas, {reducao}% menos caracteres")


print()
print("=" * 70)
print("2. ESCALONAMENTO COLOCA AS FERRAMENTAS NA MESA DE VERDADE")
print("=" * 70)

r = rodar(
    [
        # volta 1: pede o domínio
        [delta(texto="Peraí."),
         delta(tool=(0, "c1", "abrir_ferramentas", '{"dominio": "discord"}')),
         delta(finish="tool_calls")],
        # volta 2: agora usa a ferramenta que só existe depois de abrir
        [delta(tool=(0, "c2", "teste_discord_falsa", '{"canal": "geral"}')),
         delta(finish="tool_calls")],
        # volta 3: responde
        [delta(texto="Mandei lá no geral."), delta(finish="stop")],
    ],
    "manda um oi no canal geral do discord",
)

ok(len(r.catalogos) >= 2, "houve mais de uma ida ao modelo",
   f"{len(r.catalogos)} chamada(s)")
ok("teste_discord_falsa" not in r.catalogos[0],
   "na 1a chamada a ferramenta de Discord NÃO estava na mesa")
ok("teste_discord_falsa" in r.catalogos[1],
   "na 2a chamada ela ESTAVA na mesa")
ok(("teste_discord_falsa", "geral") in r.executadas,
   "a ferramenta de Discord realmente EXECUTOU",
   f"executadas={r.executadas}")
ok("Mandei lá no geral." in r.resposta,
   "a resposta final chegou", f"resposta={r.resposta!r}")


print()
print("=" * 70)
print("3. ESCALONAR NÃO É AGIR")
print("=" * 70)
print("Se abrir_ferramentas contasse como ação, um turno que abriu o domínio e")
print("depois só falou passaria pela guarda de promessa vazia como se tivesse")
print("feito a coisa. O teste força exatamente esse caminho.\n")

modelo._promessa_pendente = None
r3 = rodar(
    [
        [delta(tool=(0, "c1", "abrir_ferramentas", '{"dominio": "discord"}')),
         delta(finish="tool_calls")],
        # a partir daqui só texto: nunca chama a ferramenta de verdade
        [delta(texto="Beleza, vou mandar a mensagem lá."), delta(finish="stop")],
        [delta(texto="Vou mandar sim."), delta(finish="stop")],
        [delta(texto="Vou mandar sim."), delta(finish="stop")],
    ],
    "manda um oi no canal geral do discord",
)

ok(not r3.executadas,
   "nenhuma ferramenta de verdade executou", f"executadas={r3.executadas}")
ok(modelo._promessa_pendente is not None,
   "a guarda de promessa vazia DISPAROU (escalonar não passou por ação)",
   f"promessa pendente = {str(modelo._promessa_pendente)[:60]!r}")
ok("vou mandar" not in (r3.resposta or "").lower(),
   "a promessa não foi falada nem gravada como fala dela",
   f"resposta={r3.resposta!r}")
modelo._promessa_pendente = None


print()
print("=" * 70)
print("4. O QUE ELA FEZ SOBREVIVE AO TURNO — COM NOME, ARGUMENTOS E INTEIRO")
print("=" * 70)
print("A nota antiga era '[registro do sistema] resultado da última ação: <200")
print("chars>': sem nome de ferramenta, sem argumentos, e cortada. Além disso")
print("entrava na conversa como se fosse fala do Vitor.\n")

_LONGO = ("A tela mostra o VS Code aberto no arquivo main.py, com um erro de "
          "importação na linha 12 dizendo que o módulo 'ferramentas' não foi "
          "encontrado. No terminal de baixo tem um traceback de três níveis, e "
          "na aba do lado tem um segundo arquivo chamado modelo.py com "
          "alterações não salvas, marcado com um ponto branco no título. "
          "A barra de status embaixo diz que o interpretador selecionado é o "
          "Python 3.11 de sistema, e não o do ambiente virtual do projeto.")

ferramentas.registrar(ferramentas.Ferramenta(
    nome="teste_resultado_longo",
    grupo="geral",
    descricao="Ferramenta falsa que devolve um resultado grande.",
    propriedades={"pergunta": {"type": "string", "description": "o que olhar"}},
    obrigatorios=["pergunta"],
    executar=lambda pergunta: _LONGO,
))

r4 = rodar(
    [
        [delta(tool=(0, "c1", "teste_resultado_longo",
                     '{"pergunta": "o que ta errado na tela"}')),
         delta(finish="tool_calls")],
        [delta(texto="Falta ativar o ambiente virtual."), delta(finish="stop")],
    ],
    "olha minha tela e me diz o que ta errado",
)

bloco = modelo._bloco_ferramentas_executadas()
ok("teste_resultado_longo" in bloco, "o bloco cita o NOME da ferramenta")
ok("o que ta errado na tela" in bloco, "o bloco cita os ARGUMENTOS usados")
ok("ambiente virtual do projeto" in bloco,
   "o resultado NÃO foi cortado em 200 chars",
   f"o resultado tem {len(_LONGO)} chars e o fim dele está no bloco")
ok("Tool:" not in bloco,
   "o bloco não tem formato com cara de sintaxe pra ela imitar")

notas = [m for m in modelo.historico
         if str(m.get("content", "")).startswith("[registro do sistema]")]
ok(not notas, "a conversa NÃO ganhou nota de sistema por causa da ferramenta",
   f"{len(notas)} nota(s) no histórico")

modelo.limpar_ferramentas_executadas()
modelo.registrar_ferramenta_executada("ver_tela", {"pergunta": "o que tem ai"}, _LONGO)
sistema_com_bloco = modelo._mensagens_para_turno("")[0]["content"]
ok("ver_tela" in sistema_com_bloco and "JÁ EXECUTOU" in sistema_com_bloco,
   "no turno seguinte o bloco entra no SYSTEM PROMPT",
   f"system prompt tem {len(sistema_com_bloco):,} chars")


print()
print("=" * 70)
print("5. DOMÍNIO INVENTADO NÃO QUEBRA O TURNO")
print("=" * 70)

r5 = rodar(
    [
        [delta(tool=(0, "c1", "abrir_ferramentas", '{"dominio": "spotify"}')),
         delta(finish="tool_calls")],
        [delta(texto="Isso eu não sei fazer."), delta(finish="stop")],
    ],
    "abre as ferramentas do spotify",
)
ok(bool(r5.resposta), "o turno terminou com resposta em vez de estourar",
   f"resposta={r5.resposta!r}")
ok(modelo._dominios_na_mesa() == [],
   "nenhum domínio foi aberto por engano",
   f"na mesa: {modelo._dominios_na_mesa()}")


print()
print("=" * 70)
print("6. COMENTÁRIO QUE PARECE AÇÃO NÃO VIRA 'TRAVEI NESSA'")
print("=" * 70)
print("O Vitor comentou algo com cara de ação ('o windows engole espaço, era")
print("melhor mudar pro linux'). Nenhuma ferramenta cabe e obrigar falha. A")
print("resposta de CONVERSA dela tem que ser FALADA — antes virava a mensagem")
print("de falha genérica e a resposta boa só saía no terminal.\n")

modelo._promessa_pendente = None
_CONVERSA = "É, o Windows come espaço que é uma beleza. O WinSxS enche tudo."
r6 = rodar(
    [
        # A classificação compartilhada reconhece conversa antes do request e
        # envia tool_choice=none; não existe mais retry de contexto mínimo.
        [delta(texto=_CONVERSA), delta(finish="stop")],
    ],
    "só que o windows parece que engole mais espaço sozinho, era melhor o linux",
)
ok(_CONVERSA in (r6.resposta or ""),
   "a resposta de conversa foi FALADA (não trocada por 'travei nessa')",
   f"resposta={r6.resposta!r}")
ok(modelo._promessa_pendente is None,
   "conversa NÃO deixou promessa pendente pra cobrar",
   f"pendente={modelo._promessa_pendente!r}")
modelo._promessa_pendente = None


print()
print("=" * 70)
print(f"{len(falhas)} falha(s)" + (f": {falhas}" if falhas else ""))
print("=" * 70)
raise SystemExit(1 if falhas else 0)




"""
Teste do motor de ferramentas (laco_ferramentas.py), sem rede e sem modelo.

O que ele prova
───────────────
1. "Ela agiu?" é FATO, não palpite sobre o português do resultado. Antes,
   ferramenta que explodia, que faltava argumento ou que nem existia contavam
   TODAS como ação cumprida — e é esse booleano que a máquina de promessa lê.
2. O freio de repetição barra a chamada idêntica e deixa passar a legítima,
   inclusive quando o modelo manda o mesmo JSON com as chaves em outra ordem.
3. Ferramenta paralelizável roda de verdade em paralelo, e a ORDEM do resultado
   é a que o Vitor pediu, não a ordem em que terminou.
4. Ferramenta que mexe no computador NUNCA é paralelizada.

Roda com: python _teste_motor.py
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import time
from pathlib import Path
from types import SimpleNamespace

import ferramentas as F
import laco_ferramentas as L


falhas = []


def ok(condicao, rotulo, detalhe=""):
    print(f"{'OK   ' if condicao else 'FALHA'} {rotulo}")
    if detalhe:
        print(f"       {detalhe}")
    if not condicao:
        falhas.append(rotulo)


def chamada(nome, args_json="{}", cid=None):
    """Um llm.ChamadaFerramenta de mentira, só com o que o motor usa."""
    import json as _json
    return SimpleNamespace(
        nome=nome, id=cid or f"c_{nome}", argumentos=args_json,
        thought_signature=None,
        args=lambda: (_json.loads(args_json) if args_json else {}),
    )


# ── Ferramentas de teste ──────────────────────────────────────────
ordem_de_execucao = []


def _registrar(nome, **kw):
    F.registrar(F.Ferramenta(nome=nome, descricao="teste", **kw))


_registrar("t_ok", propriedades={}, obrigatorios=[],
           executar=lambda: (ordem_de_execucao.append("t_ok"), "feito")[1])

_registrar("t_explode", destrutiva=True, propriedades={}, obrigatorios=[],
           executar=lambda: (_ for _ in ()).throw(RuntimeError("disco cheio")))

_registrar("t_falta_arg", destrutiva=True,
           propriedades={"alvo": {"type": "string"}}, obrigatorios=["alvo"],
           executar=lambda alvo: f"apaguei {alvo}")

_registrar("t_recusa", destrutiva=True, propriedades={}, obrigatorios=[],
           executar=lambda: F.recusa("não montei o pack: falta kotlinforforge"))

_registrar("t_consulta", somente_leitura=True, propriedades={}, obrigatorios=[],
           executar=lambda: F.consulta("tem 4 jogadores online"))

_registrar("t_com_arg", propriedades={"a": {"type": "string"},
                                     "b": {"type": "string"}},
           obrigatorios=[],
           executar=lambda a=None, b=None: f"rodei com {a},{b}")


def _lento(marca):
    def executar():
        time.sleep(0.4)
        ordem_de_execucao.append(marca)
        return f"pronto {marca}"
    return executar


for _m in ("A", "B", "C"):
    _registrar(f"t_lenta_{_m}", paralelizavel=True, somente_leitura=True,
               propriedades={}, obrigatorios=[], executar=_lento(_m))
    _registrar(f"t_lenta_serial_{_m}", propriedades={}, obrigatorios=[],
               executar=_lento(f"S{_m}"))


print("=" * 72)
print("1. 'ELA AGIU?' É FATO")
print("=" * 72)
print("Cada linha destas contava como AÇÃO CUMPRIDA na versão anterior, porque")
print("a decisão saía de reconhecer o português do resultado.\n")

esperado = {
    "t_explode":   (False, False),   # (ok, agiu)
    "t_falta_arg": (False, False),
    "t_inexistente": (False, False),
    "t_recusa":    (False, False),
    "t_consulta":  (True,  False),   # deu certo, mas não mudou o mundo
    "t_ok":        (True,  True),
}

print(f"{'ferramenta':<16} {'ok':>6} {'agiu':>6}   esperado")
print("-" * 60)
for nome, (ok_esp, agiu_esp) in esperado.items():
    motor = L.Motor(catalogo=[], rotulo="TESTE")
    execucoes = motor.executar([chamada(nome)])
    e = execucoes[0]
    acertou = (e.resultado.ok == ok_esp) and (e.agiu == agiu_esp)
    print(f"{nome:<16} {str(e.resultado.ok):>6} {str(e.agiu):>6}   "
          f"ok={ok_esp} agiu={agiu_esp} {'✓' if acertou else '✗'}")
    if not acertou:
        falhas.append(f"classificação de {nome}")

ok(not [f for f in falhas if f.startswith("classificação")],
   "as seis classificações estão certas")

motor = L.Motor(catalogo=[], rotulo="TESTE")
motor.executar([chamada("t_explode"), chamada("t_ok")])
ok(motor.agiu, "um sucesso no meio de falhas ainda marca 'agiu'")
ok(len(motor.falhas) == 1, "o motor sabe listar o que falhou",
   f"falhas: {[f.nome for f in motor.falhas]}")


print()
print("=" * 72)
print("2. FREIO DE REPETIÇÃO")
print("=" * 72)

motor = L.Motor(catalogo=[], rotulo="TESTE")
execucoes = motor.executar([
    chamada("t_com_arg", '{"a": "1", "b": "2"}', cid="x1"),
    chamada("t_com_arg", '{"a": "1", "b": "2"}', cid="x2"),   # idêntica: barra
    chamada("t_com_arg", '{"b": "2", "a": "1"}', cid="x3"),   # mesma, outra ordem
    chamada("t_com_arg", '{"a": "9", "b": "2"}', cid="x4"),   # diferente: passa
])
ok(not execucoes[0].repetida, "a 1a chamada passa")
ok(execucoes[1].repetida, "a 2a, idêntica, é barrada")
ok(execucoes[2].repetida,
   "o mesmo JSON com as chaves em outra ORDEM também é barrado",
   "sem normalizar, o modelo furava o freio só mudando a ordem")
ok(not execucoes[3].repetida,
   "argumento diferente passa (é 'abre o site A e o site B')")
ok(all(not e.agiu for e in execucoes if e.repetida),
   "chamada barrada não conta como ação")


print()
print("=" * 72)
print("3. PARALELISMO — SÓ ONDE É SEGURO")
print("=" * 72)

ordem_de_execucao.clear()
motor = L.Motor(catalogo=[], rotulo="TESTE")
inicio = time.monotonic()
execucoes = motor.executar([chamada("t_lenta_A"), chamada("t_lenta_B"),
                            chamada("t_lenta_C")])
gasto_paralelo = time.monotonic() - inicio
ok(gasto_paralelo < 0.9,
   "três ferramentas de 0,4s paralelizáveis levaram bem menos que 1,2s",
   f"{gasto_paralelo:.2f}s em vez de ~1,20s em série")
ok([e.nome for e in execucoes] == ["t_lenta_A", "t_lenta_B", "t_lenta_C"],
   "o resultado volta na ORDEM PEDIDA, não na ordem em que terminou")

ordem_de_execucao.clear()
motor = L.Motor(catalogo=[], rotulo="TESTE")
inicio = time.monotonic()
motor.executar([chamada("t_lenta_serial_A"), chamada("t_lenta_serial_B"),
                chamada("t_lenta_serial_C")])
gasto_serial = time.monotonic() - inicio
ok(gasto_serial >= 1.1,
   "ferramenta NÃO marcada como paralelizável continua em série",
   f"{gasto_serial:.2f}s — é o comportamento certo pra quem mexe no PC")
ok(ordem_de_execucao == ["SA", "SB", "SC"],
   "e roda na ordem exata em que foi pedida",
   f"ordem observada: {ordem_de_execucao}")

ordem_de_execucao.clear()
motor = L.Motor(catalogo=[], rotulo="TESTE")
inicio = time.monotonic()
motor.executar([chamada("t_lenta_A")])
gasto_uma = time.monotonic() - inicio
ok(gasto_uma < 0.9, "uma paralelizável sozinha não paga overhead de thread",
   f"{gasto_uma:.2f}s")


print()
print("=" * 72)
print("4. OS TRÊS LAÇOS USAM O MESMO MOTOR")
print("=" * 72)
print("Antes cada laço tinha sua própria cópia da mecânica, e as cópias tinham")
print("consertos DIFERENTES: o de voz registrava as ações e não decidia 'agiu';")
print("o do Discord decidia 'agiu' (errado) e não registrava nada.\n")

import os
os.environ.setdefault("EMILY_EXTRACT_FACTS", "0")
import llm
import modelo

_registrar("t_dc", grupo="discord",
           propriedades={"canal": {"type": "string"}}, obrigatorios=["canal"],
           executar=lambda canal: f"mandei em #{canal}")
_registrar("t_dc_ruim", grupo="discord", propriedades={}, obrigatorios=[],
           executar=lambda: (_ for _ in ()).throw(RuntimeError("caiu")))
_registrar("t_mc", grupo="servidor", somente_leitura=True,
           propriedades={}, obrigatorios=[],
           executar=lambda: "servidor de pé")


def _bloco(tools):
    tcs = [SimpleNamespace(index=i, id=t[0], type="function",
                           function=SimpleNamespace(name=t[1], arguments=t[2]))
           for i, t in enumerate(tools)]
    return SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=None, tool_calls=tcs), finish_reason=None)])


def _delta(texto=None, finish=None):
    return SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=texto, tool_calls=None), finish_reason=finish)])


_roteiro = []


def _falso_chamar(mensagens, ferramentas=None, stream=False, **kw):
    chunks = _roteiro.pop(0) if _roteiro else [_delta(texto="fim", finish="stop")]
    fluxo = llm.FluxoComFerramentas(iter(chunks))
    if stream:
        return fluxo
    quer = fluxo.quer_ferramenta()
    texto = fluxo.preambulo if quer else "".join(fluxo.texto())
    return llm.Resposta(texto=texto, chamadas=fluxo.chamadas)


llm.chamar_com_ferramentas = _falso_chamar

_roteiro[:] = [
    [_bloco([("c1", "t_dc", '{"canal": "geral"}')]), _delta(finish="tool_calls")],
    [_delta(texto="mandei la"), _delta(finish="stop")],
]
r = modelo.responder_discord_com_ferramentas(
    mensagem="manda um oi no geral", nome_autor="Vitor",
    nome_servidor="S", nome_canal="geral", nivel="total", eh_dono=True)
ok(r.agiu is True, "Discord: ferramenta que funcionou marca agiu=True",
   f"texto={r.texto[:40]!r}")

_roteiro[:] = [
    [_bloco([("c9", "t_dc_ruim", "{}")]), _delta(finish="tool_calls")],
    [_delta(texto="deu ruim"), _delta(finish="stop")],
]
r2 = modelo.responder_discord_com_ferramentas(
    mensagem="faz aquilo la", nome_autor="Vitor", nivel="total", eh_dono=True)
ok(r2.agiu is False,
   "Discord: ferramenta que EXPLODIU não marca agiu (era True antes)",
   "esse booleano alimenta a máquina de promessa do Discord")

_roteiro[:] = [
    [_bloco([("c2", "t_mc", "{}")]), _delta(finish="tool_calls")],
    [_delta(texto="ta de pe sim"), _delta(finish="stop")],
]
r_mc = modelo.responder_discord_com_ferramentas(
    mensagem="o servidor ta on?", nome_autor="amigo", nivel="nenhum")
ok(r_mc.agiu is False, "Minecraft pelo Discord: o laço responde com o motor",
   f"resposta={str(r_mc)[:40]!r}")


print()
print("=" * 72)
print("5. ARGUMENTO OBRIGATÓRIO 'false' NÃO É ARGUMENTO FALTANDO")
print("=" * 72)
print("A checagem era `not argumentos.get(p)`, então ligar=False contava como")
print("faltando e a metade 'desligar' de TODOS os modos ficava morta — com a")
print("Emily pedindo ao Vitor um valor que o modelo já tinha mandado certo.\n")

_registrar("t_bool", propriedades={"ligar": {"type": "boolean"},
                                  "n": {"type": "integer"}},
           obrigatorios=["ligar", "n"],
           executar=lambda ligar, n: f"recebi ligar={ligar} n={n}")

r_false = F.executar_estruturado("t_bool", {"ligar": False, "n": 0})
ok(r_false.ok, "ligar=False e n=0 passam pela validação",
   f"resultado: {r_false.texto[:50]!r}")

r_ausente = F.executar_estruturado("t_bool", {"ligar": False})
ok(r_ausente.erro == "argumento_faltando",
   "argumento realmente AUSENTE continua sendo cobrado")

r_vazio = F.executar_estruturado("t_bool", {"ligar": False, "n": "   "})
ok(r_vazio.erro == "argumento_faltando",
   "string só com espaço continua contando como faltando")

chamados_modo = []
for _h in ("ativar_modo_escrito", "desativar_modo_escrito",
           "ativar_monitoramento_jogo", "desativar_escuta_discord"):
    F.registrar_handler(_h, (lambda nome=_h: (chamados_modo.append(nome),
                                              f"ok {nome}")[1]))
for _modo, _ligar in [("modo_escrito", True), ("modo_escrito", False),
                      ("monitoramento_jogo", True), ("escuta_discord", False)]:
    F.executar_estruturado("definir_modo", {"modo": _modo, "ligar": _ligar})
ok(chamados_modo == ["ativar_modo_escrito", "desativar_modo_escrito",
                     "ativar_monitoramento_jogo", "desativar_escuta_discord"],
   "definir_modo despacha pros 8 handlers antigos que o main.py registra",
   f"chamados: {chamados_modo}")
ok(F.aviso_de("definir_modo", {"modo": "modo_escrito", "ligar": False})
   == "modo_escrito_off",
   "o aviso falado varia com ligar/desligar (era um por ferramenta)")
ok("inventado" in F.executar_estruturado(
       "definir_modo", {"modo": "inventado", "ligar": True}).texto,
   "modo inventado devolve a lista do que existe em vez de falhar calado")

# A geração e a reprodução são workers separados ligados por FIFO: o primeiro
# áudio começa antes de a resposta completa existir e a ordem é preservada.
# Verificação estática evita importar os drivers globais de teclado/ALSA.
_voz_fonte = Path(__file__).resolve().parent.parent.joinpath("voz.py").read_text(encoding="utf-8")
ok("fila_audio = queue.Queue()" in _voz_fonte
   and "t_gerador.start()" in _voz_fonte
   and "t_tocador.start()" in _voz_fonte,
   "TTS mantém geração e reprodução em background por fila ordenada")


print()
print("=" * 72)
print(f"{len(falhas)} falha(s)" + (f": {falhas}" if falhas else ""))
print("=" * 72)
raise SystemExit(1 if falhas else 0)



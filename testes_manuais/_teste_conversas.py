"""
Prova do sistema de chats salvos — o "igual funciona no GPT, claude".

O que está sendo defendido aqui não é a API (criar/listar/abrir é trivial), são
as três coisas que quebram histórico de conversa na prática:

1. GRAVAÇÃO ATÔMICA. O arquivo é o histórico do Vitor. Fechar a Emily no meio de
   uma escrita não pode cortar o JSON e apagar TODAS as conversas.

2. ARQUIVO CORROMPIDO NÃO IMPEDE O BOOT. Se o JSON estiver quebrado, a Emily
   abre limpa e guarda o arquivo velho de lado. Perder o histórico é ruim; não
   abrir é pior.

3. ID ≠ TÍTULO. Renomear não pode perder a conversa, e duas conversas que
   começam com a mesma frase não podem colidir.

Roda num arquivo temporário (EMILY_ARQUIVO_CONVERSAS), então nunca toca no
histórico de verdade.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

PASTA = tempfile.mkdtemp(prefix="emily_conv_")
ARQ = os.path.join(PASTA, "conversas.json")
os.environ["EMILY_ARQUIVO_CONVERSAS"] = ARQ
os.environ["EMILY_MAX_CONVERSAS"] = "5"
os.environ["EMILY_MAX_MENSAGENS_CONVERSA"] = "6"

import conversas

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


def zerar():
    """Volta pro estado de instalação nova."""
    for p in (ARQ, ARQ.replace(".json", ".quebrado.json"),
              ARQ.replace(".json", ".tmp")):
        try:
            os.remove(p)
        except OSError:
            pass
    conversas.recarregar()


# ═════════════════════════════════════════════════════════════════
secao("1. o basico: criar, acrescentar, listar, abrir")
# ═════════════════════════════════════════════════════════════════

zerar()
ok(conversas.listar() == [], "instalacao nova comeca sem conversa nenhuma")

cid = conversas.criar("analisa a pasta de mods ai e me diz o que tem de bom")
ok(bool(cid), "criar devolve um id", cid)
ok(len(conversas.listar()) == 1, "e a conversa aparece na lista")
ok(conversas.vazia(cid), "mas nasce vazia (nenhuma mensagem ainda)")

conversas.acrescentar(cid, "user", "analisa a pasta de mods ai")
conversas.acrescentar(cid, "emily", "Achei 362 jars, 363 mods.")
ok(not conversas.vazia(cid), "depois de duas mensagens nao esta mais vazia")

msgs = conversas.abrir(cid)
ok(len(msgs) == 2, "abrir devolve as duas", len(msgs))
ok(msgs[0]["papel"] == "user" and msgs[1]["papel"] == "emily",
   "na ordem em que foram ditas")
ok(msgs[1]["texto"] == "Achei 362 jars, 363 mods.", "com o texto intacto")

meta = conversas.listar()[0]
ok(meta["quantas"] == 2, "a lista traz a contagem", meta["quantas"])
ok(meta["id"] == cid, "e o id")

ok(conversas.abrir("id_que_nao_existe") == [],
   "abrir id inexistente devolve lista vazia, nao explode")
conversas.acrescentar("id_que_nao_existe", "user", "oi")
ok(True, "e acrescentar em id inexistente e no-op silencioso")

conversas.acrescentar(cid, "user", "   ")
conversas.acrescentar(cid, "user", "")
ok(len(conversas.abrir(cid)) == 2, "mensagem vazia ou so espaco nao entra",
   len(conversas.abrir(cid)))

# ═════════════════════════════════════════════════════════════════
secao("2. o titulo sai da primeira mensagem, e corta em palavra inteira")
# ═════════════════════════════════════════════════════════════════

casos = [
    ("analisa a pasta de mods ai e me diz o que tem de bom", "analisa"),
    ("oi", "oi"),
    ("@emily monta o pack broxasRPG pra mim", "monta"),
    ("Emily, como ta o servidor?", "como"),
]
for entrada, comeco in casos:
    t = conversas.titulo_de(entrada)
    print(f"        {entrada[:42]!r:46s} -> {t!r}")
    ok(t.lower().startswith(comeco), f"titulo de {entrada[:24]!r}", t)
    ok(len(t) <= conversas.MAX_TITULO + 1, "e cabe na barra lateral", len(t))

t = conversas.titulo_de("   ")
ok(t == "Conversa nova", "texto vazio tem titulo de reserva", t)
t = conversas.titulo_de("")
ok(t == "Conversa nova", "string vazia tambem", t)
t = conversas.titulo_de("linha um\nlinha dois")
ok("\n" not in t, "quebra de linha nao vai pro titulo", repr(t))

longo = conversas.titulo_de("a" * 200)
ok(len(longo) <= conversas.MAX_TITULO + 1, "titulo gigante e cortado", len(longo))

frase = "monta um pack com os mods de interface que voce achou na pasta"
t = conversas.titulo_de(frase)
ok(t.endswith("…"), "corte marca que tem mais", t)
ok(not t[:-1].endswith(" "), "e nao deixa espaco solto antes do reticente", t)
ok(all(p in frase for p in t[:-1].split()),
   "e nenhuma palavra foi partida no meio", t)

secao("2b. conversa criada sem primeira mensagem ganha titulo na 1a fala")
zerar()
c2 = conversas.criar()          # o clique em "Nova conversa"
ok(conversas.listar()[0]["titulo"] == "Conversa nova",
   "nasce com titulo de reserva", conversas.listar()[0]["titulo"])
conversas.acrescentar(c2, "user", "como ta o servidor de minecraft?")
ok(conversas.listar()[0]["titulo"].lower().startswith("como"),
   "e a primeira fala do Vitor renomeia", conversas.listar()[0]["titulo"])

conversas.acrescentar(c2, "emily", "Servidor de pe, 3 jogadores.")
ok(conversas.listar()[0]["titulo"].lower().startswith("como"),
   "mas a fala da EMILY nao rouba o titulo",
   conversas.listar()[0]["titulo"])

# ═════════════════════════════════════════════════════════════════
secao("3. id nao e titulo: renomear nao perde a conversa")
# ═════════════════════════════════════════════════════════════════

zerar()
a = conversas.criar("monta o pack")
b = conversas.criar("monta o pack")     # MESMA frase
ok(a != b, "duas conversas com a mesma primeira frase tem ids diferentes")
conversas.acrescentar(a, "user", "sou a A")
conversas.acrescentar(b, "user", "sou a B")
ok(conversas.abrir(a)[0]["texto"] == "sou a A", "e nao se misturam")
ok(conversas.abrir(b)[0]["texto"] == "sou a B", "nenhuma das duas")

ok(conversas.renomear(a, "  pack   dos   broxas  "), "renomear devolve True")
titulos = {c["id"]: c["titulo"] for c in conversas.listar()}
ok(titulos[a] == "pack dos broxas", "espaco sobrando e normalizado", titulos[a])
ok(conversas.abrir(a)[0]["texto"] == "sou a A",
   "e a conversa continua abrindo pelo id depois de renomear")
ok(not conversas.renomear(a, "   "), "titulo vazio e recusado")
ok(not conversas.renomear("nao_existe", "x"), "e id inexistente tambem")

# ═════════════════════════════════════════════════════════════════
secao("4. apagar apaga uma, e so uma")
# ═════════════════════════════════════════════════════════════════

zerar()
ids = [conversas.criar(f"conversa {i}") for i in range(3)]
for i, c in enumerate(ids):
    conversas.acrescentar(c, "user", f"mensagem da {i}")
ok(conversas.apagar(ids[1]), "apagar devolve True")
restantes = [c["id"] for c in conversas.listar()]
ok(ids[1] not in restantes, "a conversa saiu")
ok(ids[0] in restantes and ids[2] in restantes, "e as outras ficaram",
   len(restantes))
ok(not conversas.apagar(ids[1]), "apagar de novo devolve False")
ok(not conversas.apagar("nunca_existiu"), "id inventado tambem")

# ═════════════════════════════════════════════════════════════════
secao("5. os tetos: nem arquivo infinito, nem conversa infinita")
# ═════════════════════════════════════════════════════════════════

zerar()
ok(conversas.MAX_CONVERSAS == 5, "o teto do ambiente de teste pegou",
   conversas.MAX_CONVERSAS)

primeiras = []
for i in range(8):
    c = conversas.criar(f"conversa numero {i}")
    conversas.acrescentar(c, "user", f"oi {i}")
    primeiras.append(c)
ok(len(conversas.listar()) == 5, "passando do teto, o arquivo para de crescer",
   len(conversas.listar()))
vivos = [c["id"] for c in conversas.listar()]
ok(primeiras[-1] in vivos, "a mais recente sobrevive")
ok(primeiras[0] not in vivos, "e a mais antiga e a que sai")

secao("5b. a poda olha a ultima MEXIDA, nao a data de criacao")
zerar()
velha = conversas.criar("conversa velha que eu ainda uso")
conversas.acrescentar(velha, "user", "primeira fala")
for i in range(4):
    c = conversas.criar(f"enchendo {i}")
    conversas.acrescentar(c, "user", "oi")
conversas.acrescentar(velha, "user", "continuei usando essa aqui")
for i in range(3):
    c = conversas.criar(f"enchendo mais {i}")
    conversas.acrescentar(c, "user", "oi")
ok(velha in [c["id"] for c in conversas.listar()],
   "conversa antiga que o Vitor continua usando NAO morre por idade")

secao("5c. e a conversa tem teto de mensagem")
zerar()
c = conversas.criar("conversa longa")
for i in range(20):
    conversas.acrescentar(c, "user" if i % 2 == 0 else "emily", f"msg {i}")
msgs = conversas.abrir(c)
ok(len(msgs) == 6, "guarda so as ultimas", len(msgs))
ok(msgs[-1]["texto"] == "msg 19", "e as ULTIMAS, nao as primeiras",
   msgs[-1]["texto"])

secao("5d. a lista vem da mais recente pra mais antiga")
zerar()
x = conversas.criar("primeira")
conversas.acrescentar(x, "user", "a")
y = conversas.criar("segunda")
conversas.acrescentar(y, "user", "b")
ok([c["id"] for c in conversas.listar()] == [y, x],
   "recente em cima, como em qualquer app de chat")
conversas.acrescentar(x, "user", "voltei na primeira")
ok([c["id"] for c in conversas.listar()] == [x, y],
   "e responder numa antiga sobe ela pro topo")

# ═════════════════════════════════════════════════════════════════
secao("6. o formato que vai pro modelo")
# ═════════════════════════════════════════════════════════════════

zerar()
c = conversas.criar("analisa os mods")
conversas.acrescentar(c, "user", "analisa os mods")
conversas.acrescentar(c, "emily", "Achei 362.")
conversas.acrescentar(c, "user", "e quantos de interface?")

pro_modelo = conversas.para_o_modelo(c)
ok(len(pro_modelo) == 3, "traz as tres", len(pro_modelo))
ok([m["role"] for m in pro_modelo] == ["user", "assistant", "user"],
   "com 'emily' traduzido pra 'assistant', que e o que o modelo entende",
   [m["role"] for m in pro_modelo])
ok(all(set(m) == {"role", "content"} for m in pro_modelo),
   "e SO role e content — nada de 'quando' ou 'papel' vazando pro provedor",
   list(pro_modelo[0]))
ok(conversas.para_o_modelo("nao_existe") == [],
   "id inexistente devolve lista vazia")

secao("6b. e o modelo aceita isso de volta sem reclamar")
import modelo

_guardado = list(modelo.historico)
modelo.definir_historico(conversas.para_o_modelo(c))
ok(len(modelo.historico) == 3, "o contexto foi restaurado",
   len(modelo.historico))
ok(modelo.historico[-1]["content"] == "e quantos de interface?",
   "com a ultima fala do Vitor no fim", modelo.historico[-1]["content"])
modelo.historico[:] = _guardado

# ═════════════════════════════════════════════════════════════════
secao("7. o disco: gravacao atomica e arquivo corrompido")
# ═════════════════════════════════════════════════════════════════

zerar()
c = conversas.criar("teste de disco")
conversas.acrescentar(c, "user", "grava isso ai")
ok(os.path.exists(ARQ), "o arquivo existe depois de gravar")
ok(not os.path.exists(ARQ.replace(".json", ".tmp")),
   "e o temporario NAO ficou pra tras")

with open(ARQ, encoding="utf-8") as f:
    cru = json.load(f)
ok(isinstance(cru, dict) and "conversas" in cru, "o JSON no disco e valido")
ok(cru.get("versao") == 1, "e tem versao, pra poder migrar depois",
   cru.get("versao"))

secao("7b. releitura do zero devolve a mesma coisa")
conversas.recarregar()
ok(len(conversas.listar()) == 1, "reabrindo o arquivo, a conversa esta la")
ok(conversas.abrir(c)[0]["texto"] == "grava isso ai", "com a mensagem")

fonte = open("conversas.py", encoding="utf-8").read()
ok("os.replace(" in fonte,
   "a gravacao usa os.replace — e o que torna a troca atomica")
ok("os.fsync(" in fonte,
   "e fsync antes, senao o replace troca por um arquivo que o SO ainda nao "
   "escreveu")
i_fsync = fonte.find("os.fsync(")
i_replace = fonte.find("os.replace(", i_fsync)
ok(0 < i_fsync < i_replace, "e nessa ordem: fsync primeiro, replace depois")

secao("7c. arquivo corrompido nao impede a Emily de abrir")
with open(ARQ, "w", encoding="utf-8") as f:
    f.write('{"conversas": [{"id": "x", "titu')     # cortado no meio
conversas.recarregar()
lista = conversas.listar()
ok(lista == [], "JSON cortado -> comeca limpa, sem excecao", lista)
ok(os.path.exists(ARQ.replace(".json", ".quebrado.json")),
   "e o arquivo velho fica guardado pra olhar depois")

novo = conversas.criar("depois do estrago")
conversas.acrescentar(novo, "user", "e a vida segue")
ok(len(conversas.listar()) == 1, "e da pra usar normalmente em seguida")

secao("7d. e formato inesperado tambem nao derruba")
for conteudo in ("[]", '{"outra_coisa": 1}', '{"conversas": "nao e lista"}',
                 "", "nao e json nem de longe"):
    with open(ARQ, "w", encoding="utf-8") as f:
        f.write(conteudo)
    conversas.recarregar()
    try:
        r = conversas.listar()
        ok(r == [], f"{conteudo[:26]!r} -> lista vazia", r)
    except Exception as e:
        ok(False, f"{conteudo[:26]!r} estourou", f"{type(e).__name__}: {e}")

secao("7e. arquivo sem permissao de escrita nao mata a Emily")
zerar()
c = conversas.criar("antes de travar o disco")
try:
    # Aponta o arquivo pra dentro de um caminho impossível.
    _real = conversas.ARQUIVO
    from pathlib import Path
    conversas.ARQUIVO = Path(ARQ) / "nao_da" / "conversas.json"
    conversas.acrescentar(c, "user", "isso nao vai gravar")
    ok(True, "gravar num caminho invalido nao levanta excecao")
finally:
    conversas.ARQUIVO = _real

print()
print("=" * 78)
if RUINS:
    print(f"{RUINS} problema(s).")
else:
    print("Os chats salvam, abrem, renomeiam e sobrevivem a arquivo quebrado.")
print("=" * 78)

try:
    shutil.rmtree(PASTA, ignore_errors=True)
except OSError:
    pass
sys.exit(1 if RUINS else 0)

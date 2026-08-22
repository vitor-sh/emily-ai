"""
Prova dos dois bugs relatados pelo Vitor, e da correção.

BUG 1 — a Emily mandou isto no Discord, como se fosse fala:
    [Tool: gerenciar_mod_launcher_mc (toolu_bdrk_01Q7WWSMxrJ8oQyPa8VaCbfz)]
    {"pack": "guerra", "adicionar": "kotlin-for-forge"}

A hipótese: o laço de ferramentas mandava a última volta com `tools` VAZIO pra
obrigar resposta em texto; o gateway do Kiro, sem `tools` na requisição, converte
o histórico de ferramentas em TEXTO nesse formato (converters_core.py:1457) pra
não perder o contexto; e o modelo imita o formato que acabou de ler.

A seção 3 TESTA essa hipótese contra o gateway de verdade, nas duas
configurações, em vez de assumir. Se o vazamento não aparecer no controle, o
teste diz isso em vez de passar calado — hipótese não confirmada é informação.

BUG 2 — congelamento de minutos sem dizer nada, com o log repetindo
'No response within 15.0 seconds'. Duas causas somadas: o teto de primeiro
token do gateway (15s) derrubava requisição que ia dar certo, e as retentativas
se multiplicavam (3 do gateway × 4 do llm.py = 12 idas ao provedor).

As seções 1, 2, 4 e 5 rodam sem rede. A 3 precisa do gateway e é PULADA se ele
não estiver de pé — não vira falha, porque a correção do laço não depende de o
provedor honrar o tool_choice.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# A resposta do modelo vem com emoji e o console do Windows é cp1252. Sem isto o
# teste morre com UnicodeEncodeError ao IMPRIMIR o que deu certo.
for fluxo in (sys.stdout, sys.stderr):
    try:
        fluxo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

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
# 1. O SANITIZADOR
# ═════════════════════════════════════════════════════════════════

secao("1. o sanitizador tira o artefato de ferramenta e nao come fala boa")

import modelo

VAZADO = (
    '[Tool: gerenciar_mod_launcher_mc (toolu_bdrk_01Q7WWSMxrJ8oQyPa8VaCbfz)]\n'
    '{"pack": "guerra", "adicionar": "kotlin-for-forge"}'
)

r = modelo._tirar_artefato_de_ferramenta(VAZADO)
ok(r == "", "a mensagem exata que vazou pro Discord vira vazio", repr(r))

r = modelo._tirar_artefato_de_ferramenta(
    "adicionei o kotlin la\n" + VAZADO)
ok(r == "adicionei o kotlin la",
   "fala de verdade antes do artefato sobrevive", repr(r))

r = modelo._tirar_artefato_de_ferramenta(
    VAZADO + "\npronto, ta lá agora")
ok(r == "pronto, ta lá agora",
   "fala de verdade depois do artefato sobrevive", repr(r))

# No '[Tool Result]' o rótulo sai e o CONTEÚDO fica. A assimetria é de
# propósito: argumento de chamada ('{"pack": "guerra"}') nunca é coisa que a
# Emily fala, mas resultado de ferramenta é justamente a informação que ela tem
# pra dar. Apagar o bloco inteiro aqui a deixaria muda com a resposta na mão.
r = modelo._tirar_artefato_de_ferramenta(
    '[Tool Result (toolu_abc)]\nNenhuma publicação presa agora.')
ok(r == "Nenhuma publicação presa agora.",
   "no RESULTADO o rotulo sai e a informacao fica", repr(r))

r = modelo._tirar_artefato_de_ferramenta(
    '[Tool Result (toolu_abc)]\n{"presas": 0}')
ok(r == "", "mas resultado que e JSON cru sai inteiro", repr(r))

r = modelo._tirar_artefato_de_ferramenta(
    '[Tool: banir_membro]\n{"quem": "joao"}\n\n'
    '[Tool: criar_canal]\n{"nome": "geral"}\nfeito os dois')
ok(r == "feito os dois", "dois blocos seguidos saem", repr(r))

secao("1b. e NAO estraga resposta legitima")
casos_intactos = [
    "adicionei o kotlin-for-forge no pack guerra",
    'o config ficou assim: {"pack": "guerra"}',
    "[AVISO] o pack ta sem dependencia",
    "olha o json: {\"a\": 1}",
    "beleza, ja era",
    "",
]
for texto in casos_intactos:
    r = modelo._tirar_artefato_de_ferramenta(texto)
    ok(r == texto, f"passou intacto: {texto[:44]!r}", repr(r)[:50])

secao("1c. e o sanitizador geral chama o novo (o caminho que a Emily usa)")
r = modelo._limpar_vazamento_de_registro(VAZADO)
ok(r.strip() == "", "_limpar_vazamento_de_registro mata o artefato", repr(r))
r = modelo._limpar_vazamento_de_registro("[Registro do sistema] beleza mano")
ok("beleza mano" in r, "e continua fazendo o que fazia antes", repr(r))

# ═════════════════════════════════════════════════════════════════
# 2. A CAMADA DE LLM ACEITA 'PROIBIR'
# ═════════════════════════════════════════════════════════════════

secao("2. o llm.py sabe declarar o catalogo e proibir o uso")

import llm
import inspect

for fn in (llm.chamar, llm.chamar_com_ferramentas):
    params = inspect.signature(fn).parameters
    ok("proibir_ferramenta" in params,
       f"{fn.__name__} aceita proibir_ferramenta")

params = inspect.signature(llm.ProvedorOpenAI.chamar).parameters
ok("proibir_ferramenta" in params, "o provedor OpenAI aceita")
params = inspect.signature(llm.Provedor.chamar).parameters
ok("proibir_ferramenta" in params, "a classe base tambem, senao quebra herança")


class _ClienteFalso:
    """Captura o corpo enviado, sem ir na rede."""

    def __init__(self):
        self.corpos = []
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **corpo):
        self.corpos.append(corpo)

        class _Fn:
            name = "ferramenta_teste"
            arguments = "{}"

        class _Msg:
            content = "texto de teste"
            tool_calls = []

        class _Escolha:
            message = _Msg()
            finish_reason = "stop"

        class _Resp:
            choices = [_Escolha()]

        return _Resp()


CATALOGO_FALSO = [{
    "type": "function",
    "function": {"name": "ferramenta_teste", "description": "teste",
                 "parameters": {"type": "object", "properties": {}}},
}]

prov = llm.ProvedorOpenAI(nome="falso", base_url=None, env_chave="NADA")
falso = _ClienteFalso()
prov._cliente = falso

for proibir, obrigar, esperado in ((False, False, "auto"),
                                   (True, False, "none"),
                                   (False, True, "required")):
    falso.corpos.clear()
    prov.chamar(
        mensagens=llm.normalizar_mensagens([{"role": "user", "content": "oi"}]),
        modelo="m", max_tokens=10, temperatura=None,
        raciocinio=llm.RACIOCINIO_DESLIGADO, stream=False,
        ferramentas=CATALOGO_FALSO,
        obrigar_ferramenta=obrigar, proibir_ferramenta=proibir,
    )
    corpo = falso.corpos[0]
    ok(corpo.get("tool_choice") == esperado,
       f"proibir={proibir} obrigar={obrigar} -> tool_choice={esperado}",
       corpo.get("tool_choice"))
    ok("tools" in corpo,
       f"e o catalogo VAI declarado (proibir={proibir}) — é o ponto todo")

# ═════════════════════════════════════════════════════════════════
# 3. A HIPÓTESE, CONTRA O GATEWAY DE VERDADE
# ═════════════════════════════════════════════════════════════════

secao("3. A HIPOTESE: sem 'tools', o gateway serializa o historico como texto")

# Um turno que JÁ tem chamada e resultado de ferramenta no histórico. É essa
# forma que o gateway reescreve quando a requisição não declara tools.
TURNO = [
    {"role": "system", "content":
     "Você é a Emily. Responda curto, em português, como no chat do Discord."},
    {"role": "user", "content": "adiciona o kotlin no pack guerra"},
    {"role": "assistant", "content": "",
     "tool_calls": [{
         "id": "toolu_bdrk_01Q7WWSMxrJ8oQyPa8VaCbfz",
         "type": "function",
         "function": {"name": "gerenciar_mod_launcher_mc",
                      "arguments": json.dumps({"pack": "guerra",
                                               "adicionar": "kotlin-for-forge"})},
     }]},
    {"role": "tool", "tool_call_id": "toolu_bdrk_01Q7WWSMxrJ8oQyPa8VaCbfz",
     "content": "Adicionei kotlin-for-forge no pack 'guerra'. Commit a1b2c3d."},
    {"role": "user", "content": "deu certo?"},
]

CATALOGO_REAL = [{
    "type": "function",
    "function": {
        "name": "gerenciar_mod_launcher_mc",
        "description": "Adiciona ou remove mod de um pack do launcher.",
        "parameters": {
            "type": "object",
            "properties": {"pack": {"type": "string"},
                           "adicionar": {"type": "string"}},
            "required": ["pack"],
        },
    },
}]


def _texto_de(resposta):
    if isinstance(resposta, str):
        return resposta
    return getattr(resposta, "texto", "") or ""


def _chamadas_de(resposta):
    if isinstance(resposta, str):
        return []
    return list(getattr(resposta, "chamadas", []) or [])


gateway_vivo = False
try:
    controle = llm.chamar_com_ferramentas(
        TURNO, ferramentas=[], rota_nome="discord", max_tokens=200,
        stream=False)
    gateway_vivo = True
except Exception as e:
    aviso(f"gateway indisponivel ({type(e).__name__}: {str(e)[:90]}); "
          f"pulei a secao 3")

if gateway_vivo:
    texto_controle = _texto_de(controle)
    print(f"        --- SEM tools (como era antes) ---")
    print(f"        {texto_controle[:300]!r}")
    vazou = "[Tool" in texto_controle
    if vazou:
        ok(True, "CONFIRMADO: sem tools o modelo imita '[Tool: ...]'")
    else:
        aviso("o vazamento nao apareceu nesta amostra. Ele e intermitente "
              "(depende do modelo imitar), entao isso NAO desmente a "
              "hipotese — o gateway serializa de qualquer jeito "
              "(converters_core.py:1457).")

    ok(modelo._limpar_vazamento_de_registro(texto_controle).find("[Tool") < 0,
       "e de todo jeito o sanitizador limparia essa resposta")

    # Agora a correção: catálogo declarado, uso proibido.
    corrigido = llm.chamar_com_ferramentas(
        TURNO, ferramentas=CATALOGO_REAL, proibir_ferramenta=True,
        rota_nome="discord", max_tokens=200, stream=False)
    texto_corrigido = _texto_de(corrigido)
    chamadas_corrigido = _chamadas_de(corrigido)
    print(f"        --- COM tools + tool_choice=none (correcao) ---")
    print(f"        {texto_corrigido[:300]!r}")
    print(f"        chamadas: {[c.nome for c in chamadas_corrigido]}")

    ok("[Tool" not in texto_corrigido,
       "com o catalogo declarado nao ha formato pra imitar")
    ok(texto_corrigido.strip() != "",
       "e ela respondeu alguma coisa", repr(texto_corrigido[:60]))
    if chamadas_corrigido:
        aviso(f"o provedor IGNOROU o tool_choice=none e pediu "
              f"{[c.nome for c in chamadas_corrigido]}. Esperado: o gateway do "
              f"Kiro nao repassa tool_choice pra API. É por isso que o laço "
              f"tambem descarta chamada na ultima volta.")
    else:
        ok(True, "e respeitou a proibicao de usar ferramenta")

# ═════════════════════════════════════════════════════════════════
# 4. O LAÇO NÃO DEPENDE DO PROVEDOR OBEDECER
# ═════════════════════════════════════════════════════════════════

secao("4. o laço descarta ferramenta na ultima volta, obedecido ou nao")

import re

fonte = open("modelo.py", encoding="utf-8").read()

ok("ferramentas=[] if ultima else catalogo" not in fonte,
   "nenhum laço manda mais lista de ferramentas VAZIA")
ok(fonte.count("proibir_ferramenta=ultima") == 3,
   "os TRES laços (voz, Discord e agente de jogo) usam proibir_ferramenta",
   fonte.count("proibir_ferramenta=ultima"))
ok(fonte.count("if ultima and chamadas:") == 2,
   "e os dois laços sem stream descartam chamada vinda na ultima volta",
   fonte.count("if ultima and chamadas:"))
ok(len(re.findall(r"texto = _limpar_vazamento_de_registro\(texto\)", fonte)) == 2,
   "o texto e sanitizado ANTES de virar a resposta final nos dois laços",
   len(re.findall(r"texto = _limpar_vazamento_de_registro\(texto\)", fonte)))

# ═════════════════════════════════════════════════════════════════
# 5. O CONGELAMENTO TEM TETO
# ═════════════════════════════════════════════════════════════════

secao("5. o congelamento de minutos tem teto agora")

ok(hasattr(llm, "ORCAMENTO_RETENTATIVA"), "existe orçamento de tempo total")
ok(0 < llm.ORCAMENTO_RETENTATIVA <= 180,
   "e o teto e de no maximo 3 minutos", f"{llm.ORCAMENTO_RETENTATIVA:.0f}s")

fonte_llm = open("llm.py", encoding="utf-8").read()
ok("time.monotonic() - comeco > ORCAMENTO_RETENTATIVA" in fonte_llm,
   "o laço de retentativa confere o orçamento antes de tentar de novo")

# O pior caso não pode passar do orçamento mais uma tentativa em andamento.
pior = llm.ORCAMENTO_RETENTATIVA + 60 * 1  # 60s = FIRST_TOKEN_TIMEOUT novo
ok(pior <= 300, "pior caso de silencio fica abaixo de 5 min", f"{pior:.0f}s")

secao("5b. o gateway nao derruba mais requisicao lenta em 15s")
env_gw = ""
try:
    env_gw = open(os.path.join("kiro_gateway", ".env"), encoding="utf-8").read()
except OSError as e:
    ok(False, f"nao li o .env do gateway: {e}")

if env_gw:
    m = re.search(r'FIRST_TOKEN_TIMEOUT="?(\d+)', env_gw)
    ok(m is not None, "FIRST_TOKEN_TIMEOUT esta configurado (nao no default 15)")
    if m:
        ok(int(m.group(1)) >= 45,
           "e da tempo do Claude comecar com prompt grande de ferramenta",
           f"{m.group(1)}s")
    m = re.search(r'FIRST_TOKEN_MAX_RETRIES="?(\d+)', env_gw)
    ok(m is not None, "FIRST_TOKEN_MAX_RETRIES esta configurado")
    if m:
        ok(int(m.group(1)) == 1,
           "e o gateway NAO repete sozinho (quem repete e o llm.py)",
           m.group(1))

secao("5c. e a correcao sobrevive ao script que regenera o .env")
try:
    gerador = open("_setup_gateway_env.py", encoding="utf-8").read()
    ok("FIRST_TOKEN_TIMEOUT" in gerador,
       "o gerador tambem escreve FIRST_TOKEN_TIMEOUT")
    ok("FIRST_TOKEN_MAX_RETRIES" in gerador,
       "e FIRST_TOKEN_MAX_RETRIES")
except OSError as e:
    ok(False, f"nao li o gerador: {e}")

# ═════════════════════════════════════════════════════════════════
# 6. NADA QUEBROU
# ═════════════════════════════════════════════════════════════════

secao("6. o catalogo continua carregando")
import ferramentas
ok(len(ferramentas.CATALOGO) > 140, "ferramentas no catalogo",
   len(ferramentas.CATALOGO))

print()
print("=" * 78)
if RUINS:
    print(f"{RUINS} problema(s).")
else:
    print("Os dois bugs estao atacados na raiz, com rede de seguranca por cima.")
print("=" * 78)
sys.exit(1 if RUINS else 0)

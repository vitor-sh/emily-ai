"""
_teste_code_projeto.py — a pasta de projeto do Emily Code.

Bug real, medido na máquina do Vitor: a conversa do code nasce com
"projeto": "" e o projeto_raiz() devolvia None SOMBREANDO a pasta padrão que
ele tinha definido. O terminal mostrava o caminho certo salvo nas preferências,
e a Emily dizia que não tinha projeto/pasta nenhum. Conserto: conversa sem
pasta própria (ou com pasta morta, ex.: caminho C:\\ da migração) cai na pasta
padrão; conversa com pasta própria válida continua vencendo a padrão.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import os
import sys
import tempfile
from pathlib import Path

# Os arquivos de estado são lidos no IMPORT: define os temporários antes.
_pasta_tmp = tempfile.mkdtemp(prefix="emily_code_teste_")
os.environ["EMILY_ARQUIVO_PREFERENCIAS"] = os.path.join(
    _pasta_tmp, "prefs.json")
os.environ["EMILY_ARQUIVO_CODE_CONVERSAS"] = os.path.join(
    _pasta_tmp, "conversas.json")

import preferencias  # noqa: E402
import emily_code    # noqa: E402

falhas = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    resultado = "OK" if condicao else "FALHOU"
    print(f"[{resultado}] {nome}" + (f" -> {detalhe}" if not condicao else ""))
    if not condicao:
        falhas.append(nome)


# Pastas de teste no disco (a pasta "padrão" e um projeto próprio).
raiz_padrao = Path(_pasta_tmp) / "projeto_padrao"
raiz_padrao.mkdir()
raiz_outro = Path(_pasta_tmp) / "outro_projeto"
raiz_outro.mkdir()

# 1) Sem conversa ativa nenhuma: vale a pasta padrão (comportamento de sempre).
preferencias.definir(emily_code_projeto=str(raiz_padrao))
checar("sem conversa ativa: usa a pasta padrão",
       emily_code.projeto_raiz() == raiz_padrao)

# 2) Conversa NOVA (nasce com projeto=""): a pasta padrão vale.
#    Era AQUI que a Emily dizia "não tem projeto nenhum" com a pasta certa
#    definida — o caso do bug.
cid = emily_code.code_criar_conversa("teste de pasta")
checar("conversa nova nasce sem pasta própria",
       emily_code._achar_conversa(cid).get("projeto") == "")
checar("conversa nova com pasta padrão definida: usa a padrão",
       emily_code.projeto_raiz() == raiz_padrao)

# 3) O sintoma que o Vitor viu: ver_projeto() tem que listar a pasta, não
#    dizer que não existe projeto.
resposta = emily_code.ver_projeto()
checar("ver_projeto não diz mais 'nenhuma pasta definida'",
       "Nenhuma pasta de projeto" not in resposta, resposta[:80])

# 4) Conversa com pasta PRÓPRIA: ela vence a padrão.
emily_code.definir_projeto(str(raiz_outro))
checar("definir_projeto grava na conversa ativa",
       emily_code._achar_conversa(cid).get("projeto") == str(raiz_outro))
checar("pasta própria vence a padrão",
       emily_code.projeto_raiz() == raiz_outro)

# 5) Pasta própria que MORREU (caminho da migração): cai na padrão, com aviso
#    no terminal em vez de "nenhum projeto definido".
preferencias.definir(emily_code_projeto=str(raiz_padrao))
emily_code._atualizar_conversa(cid, projeto="C:\\Users\\conti\\projeto")
checar("caminho morto da conversa cai na pasta padrão",
       emily_code.projeto_raiz() == raiz_padrao)

# 6) Sem pasta padrão e conversa vazia: aí sim None (a Emily pergunta).
emily_code._atualizar_conversa(cid, projeto="")
preferencias.definir(emily_code_projeto="")
checar("sem padrão e sem pasta própria: None (ela vai perguntar)",
       emily_code.projeto_raiz() is None)

# 7) Pasta padrão apontando pra caminho morto: None também.
preferencias.definir(emily_code_projeto="C:\\Users\\conti\\sumiu")
checar("padrão apontando pra caminho morto: None",
       emily_code.projeto_raiz() is None)

# 8) Conversa antiga (pré-migração, SEM a chave "projeto"): cai na global,
#    comportamento histórico mantido.
with emily_code._lock_conversas:
    dados = emily_code._carregar_conversas()
    for c in dados["conversas"]:
        if c.get("id") == cid:
            c.pop("projeto", None)
    emily_code._guardar_conversas(dados)
preferencias.definir(emily_code_projeto=str(raiz_padrao))
checar("conversa antiga sem a chave: usa a pasta padrão",
       emily_code.projeto_raiz() == raiz_padrao)

# 9) O fluxo inteiro de ferramenta funciona na pasta padrão: resolver um
#    caminho relativo dentro dela.
caminho = emily_code._resolver("arquivo.py")
checar("_resolver resolve relativo dentro da pasta padrão",
       caminho == raiz_padrao / "arquivo.py", str(caminho))

print()
if falhas:
    print(f"FALHOU: {len(falhas)} teste(s): {falhas}")
    sys.exit(1)
print("Tudo certo.")

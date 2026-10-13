"""Animação de ferramentas: toda ferramenta do catálogo precisa de rótulo e ícone próprios.

O PC traduz o nome da ferramenta em rótulo/ícone no web/app.js (_nomeBonito) e o celular
em EmilyAgent.descricaoPasso. Ferramenta nova sem entrada caía num cubo genérico (PC) ou em
"Trabalhando nisso" (celular), e a animação parecia não cobrir a ação.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import ferramentas

RAIZ = Path(__file__).resolve().parents[1]
# Genéricas de propósito: não há um ícone melhor que o cubo para elas.
GENERICAS_PC = {"abrir_ferramentas", "hora_atual"}


@pytest.mark.skipif(shutil.which("node") is None, reason="node não instalado")
def test_pc_toda_ferramenta_tem_icone_proprio():
    nomes = sorted(ferramentas.CATALOGO)
    js = (RAIZ / "web/app.js").read_text(encoding="utf-8")
    trecho = js[js.index("const _NOME_BONITO"):js.index("function _detalheArgumentos")]
    prog = ("const ICO = new Proxy({}, {get:(t,k)=>String(k)}); const ICO_GITHUB='github';\n" + trecho +
            "\nconst nomes = " + json.dumps(nomes) + ";\n"
            "console.log(JSON.stringify(nomes.map(n => { const r = _nomeBonito(n); return [n, r.rotulo, r.ico]; })));")
    saida = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=30)
    assert saida.returncode == 0, saida.stderr[-400:]
    linhas = json.loads(saida.stdout)
    sem_icone = sorted(n for n, _r, ico in linhas if ico == "cubo" and n not in GENERICAS_PC)
    assert not sem_icone, f"ferramentas sem ícone próprio no PC: {sem_icone}"
    # Rótulo com cara de nome de função ("Controlar luz", "Programacao previa") é rótulo que faltou.
    cru = [n for n, r, _i in linhas if r.lower().replace(" ", "_") == n and n not in GENERICAS_PC]
    assert not cru, f"ferramentas com rótulo cru no PC: {cru}"


def test_celular_toda_ferramenta_registrada_tem_rotulo():
    fonte = (RAIZ / "EmilyAPP2/app/src/main/java/com/example/emilyapp/EmilyAgent.kt").read_text(encoding="utf-8")
    registradas = set(re.findall(r'ferramenta\("([a-z0-9_]+)"', fonte))
    ini = fonte.index("internal fun descricaoPasso")
    bloco = fonte[ini:ini + 20000]
    rotulos = set()
    for grupo in re.findall(r'((?:"[a-z0-9_]+"\s*,\s*)*"[a-z0-9_]+")\s*->', bloco):
        rotulos |= set(re.findall(r'"([a-z0-9_]+)"', grupo))
    # pc_programacao_* e as do Emily Cloud têm rótulo próprio fora deste when.
    faltam = sorted(n for n in registradas - rotulos
                    if not n.startswith("pc_programacao_") and not n.startswith("nuvem_"))
    assert not faltam, f"ferramentas do celular sem rótulo: {faltam}"
    # O gancho que abre o passo tem de rodar ANTES do juiz de autorização.
    cliente = (RAIZ / "EmilyAPP2/app/src/main/java/com/example/emilyapp/OpenRouterClient.kt").read_text(encoding="utf-8")
    assert cliente.index("onToolStart(nome, args)") < cliente.index("authorizedAction(userText")
    assert "onToolResult(nome, args, resultado)" in cliente

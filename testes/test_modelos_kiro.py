"""Migração GPT-6 (Codex) -> Claude no Kiro, em 10/10/2026.

A assinatura do Codex acabou: nenhum caminho de produção pode ter um modelo
cx/gpt-6 como padrão, e as escolhas automáticas têm que cair no Kiro.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RAIZ = Path(__file__).resolve().parents[1]

# Código que roda na Emily do PC. Testes, benchmarks e backups ficam de fora:
# eles registram medições antigas e não escolhem modelo nenhum.
FONTES = [
    *RAIZ.glob("*.py"),
    *(RAIZ / "web").glob("*.js"),
    *(RAIZ / "web").glob("*.html"),
    RAIZ / "emily-gateway-service" / "emily_gateway.py",
    RAIZ / "emily-relay" / "relay.py",
]


def test_nenhum_padrao_de_producao_usa_gpt6():
    achados = []
    for arquivo in FONTES:
        if arquivo.name.startswith("_index_compilado"):
            continue  # cópia compilada antiga, não é carregada
        texto = arquivo.read_text(encoding="utf-8", errors="replace")
        for n, linha in enumerate(texto.splitlines(), 1):
            if re.search(r"[\"']cx/gpt-6", linha):
                achados.append(f"{arquivo.name}:{n}")
    assert not achados, "modelo cx/gpt-6 ainda escolhido em: " + ", ".join(achados)


def test_voz_rapida_e_forte_no_kiro():
    import orquestrador_voz
    assert orquestrador_voz.MODELO_LUNA.startswith("kr/claude-")
    assert orquestrador_voz.MODELO_FORTE.startswith("kr/claude-")
    assert orquestrador_voz.PROVEDOR_VOZ == "omniroute"


def test_agente_visual_sem_preferencia_cai_no_kiro(monkeypatch):
    import config_agente_visual
    import preferencias
    monkeypatch.setattr(preferencias, "obter", lambda chave, padrao=None: None)
    cfg = config_agente_visual.configuracao()
    assert cfg["provedor"] == "omniroute"
    assert cfg["modelo"].startswith("kr/claude-")


def test_rotas_fixas_dos_editores_e_xadrez(monkeypatch):
    import llm
    import editor_assistant
    import xadrez_emily
    chamadas = []
    monkeypatch.setattr(llm, "chamar_com_ferramentas", lambda *a, **kw: chamadas.append(kw))
    monkeypatch.setattr(llm, "chamar", lambda *a, **kw: chamadas.append(kw))
    editor_assistant.call_model([{"role": "user", "content": "oi"}])
    xadrez_emily.chamar_modelo([])
    assert {(c["provedor"], c["modelo"]) for c in chamadas} == {("omniroute", "kr/claude-opus-5")}


def test_provedor_oculto_fica_fora_do_seletor_mas_vale_de_fallback(monkeypatch):
    import llm
    cfg = llm.PROVEDORES_CONFIG.get("claude")
    if cfg is None:
        return  # instalação sem o provedor externo
    monkeypatch.setattr(cfg, "oculto", True)
    assert "claude" not in {p["id"] for p in llm.listar_provedores()}
    assert "claude" in llm.PROVEDORES


def test_provedor_sem_modelos_nao_aparece_no_seletor(monkeypatch):
    import llm
    cfg = llm.PROVEDORES_CONFIG.get("openai")
    if cfg is None:
        return
    monkeypatch.setattr(cfg, "modelos_csv", [])
    monkeypatch.setattr(cfg, "modelo_padrao", "")
    assert "openai" not in {p["id"] for p in llm.listar_provedores()}


def test_preferencia_salva_no_codex_vazio_cai_no_provedor_ativo(monkeypatch):
    import llm
    import preferencias
    cfg = llm.PROVEDORES_CONFIG.get("openai")
    if cfg is None:
        return
    monkeypatch.setattr(cfg, "modelos_csv", [])
    monkeypatch.setattr(cfg, "modelo_padrao", "")
    pid, _ = preferencias._validar_provedor_e_modelo("openai", "cx/gpt-6-sol")
    assert pid == llm.TABELA_ATIVA != "openai"


# ── Seletor, raciocínio e medidor (11/10/2026) ─────────────────────

def test_claude_do_kiro_oferece_os_seis_niveis_de_raciocinio():
    import llm
    ids = [n["id"] for n in llm.niveis_raciocinio("kr/claude-sonnet-5.5")]
    assert ids == ["desligado", "baixo", "medio", "alto", "extra_alto", "maximo"]
    assert [n["id"] for n in llm.niveis_raciocinio("kiro/claude-opus-5.5")] == ids
    # Claude de relay não medido continua com os três da interface.
    assert [n["id"] for n in llm.niveis_raciocinio("claude-sonnet-5")] == ["baixo", "medio", "alto"]
    assert llm.PARAMS_RACIOCINIO["extra_alto"]["reasoning_effort"] == "xhigh"


def test_seletor_mostra_janela_de_contexto_do_catalogo(monkeypatch):
    import llm
    import limites_modelos
    monkeypatch.setattr(limites_modelos, "catalogo_em_cache", lambda pid: {
        "kr/claude-sonnet-5.5": 1000000, "kr/claude-haiku-4.5": 200000})
    modelos = {m["id"]: m["sobre"] for m in llm._modelos_provedor("omniroute")}
    assert modelos["kr/claude-sonnet-5.5"] == "1M de contexto"
    assert modelos["kr/claude-haiku-4.5"] == "200k de contexto"


def test_lista_de_modelos_da_secao_vem_do_arquivo_e_nao_do_ambiente(monkeypatch):
    import llm
    # Um reinício por exec herda variáveis velhas; a seção lida do arquivo manda.
    monkeypatch.setenv("EMILY_PROVEDOR_OMNIROUTE_MODELOS", "cx/gpt-6-sol")
    monkeypatch.setenv("EMILY_PROVEDOR_OMNIROUTE_MODELO", "cx/gpt-6-sol")
    assert "cx/gpt-6-sol" not in llm._modelos_de_secao("omniroute")


def test_reinicio_com_ambiente_velho_nao_deixa_o_seletor_vazio():
    import subprocess
    codigo = (
        "import llm;"
        "print(llm.TABELA_ATIVA, llm.ROTAS['conversa'].modelo, len(llm.listar_provedores()))"
    )
    env = {**__import__("os").environ,
           "EMILY_PROVEDOR_LLM": "openai",
           "EMILY_PROVEDOR_OPENAI_MODELOS": "cx/gpt-6-sol, cx/gpt-6-luna",
           "EMILY_PROVEDOR_OPENAI_MODELO": "cx/gpt-6-luna"}
    saida = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, env=env,
                           capture_output=True, text=True, timeout=120).stdout.strip().splitlines()[-1]
    tabela, modelo, grupos = saida.split()
    assert tabela == "omniroute" and modelo.startswith("kr/claude-") and int(grupos) >= 1


def test_atualizador_limpa_provedores_do_ambiente_antes_de_reiniciar(monkeypatch):
    import os
    import atualizador_emily
    monkeypatch.setenv("EMILY_PROVEDOR_LLM", "openai")
    monkeypatch.setenv("EMILY_PROVEDOR_OPENAI_MODELOS", "cx/gpt-6-sol")
    monkeypatch.setattr(os, "execv", lambda *a, **k: None)
    atualizador_emily._reiniciar()
    assert not [n for n in os.environ if n.startswith("EMILY_PROVEDOR_")]


def test_medidor_de_contexto_nao_espera_pelo_uso_do_codex(monkeypatch):
    from types import SimpleNamespace
    import interface_web
    import uso_codex

    def nao_deve_chamar():
        raise AssertionError("uso_codex.desktop_usage() não pode atrasar o medidor")

    monkeypatch.setattr(uso_codex, "desktop_usage", nao_deve_chamar)
    api = object.__new__(interface_web.Api)
    api._j = SimpleNamespace(_cid="teste-medidor")
    resposta = api.uso_contexto()
    assert set(resposta) == {"context"}
    assert resposta["context"]["limit"] > 0


def test_medidor_acompanha_a_janela_de_cada_modelo(monkeypatch):
    import contexto_chat
    import limites_modelos
    monkeypatch.setattr(limites_modelos, "provedor", lambda m: "omniroute")
    monkeypatch.setattr(limites_modelos, "catalogo", lambda pid: {
        "kr/claude-sonnet-5.5": 1000000, "kr/claude-haiku-4.5": 200000})
    mensagens = [{"role": "user", "content": "oi " * 100}]
    grande = contexto_chat.display("chave-medidor", "kr/claude-sonnet-5.5", mensagens)
    pequeno = contexto_chat.display("chave-medidor", "kr/claude-haiku-4.5", mensagens)
    assert grande["limit"] == 1000000 and pequeno["limit"] == 200000
    assert pequeno["percent"] > grande["percent"]


def test_pagina_de_uso_do_codex_saiu_das_configuracoes():
    texto = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
    for resto in ("cfg-modelos-uso", "Assinatura Codex", "data-cfg-abrir=\"modelos\"",
                  "id: 'modelos', titulo: 'Modelos'"):
        assert resto not in texto, resto


def test_seletor_do_chat_ordena_do_mais_novo_para_o_mais_antigo():
    import json
    import shutil
    import subprocess
    if not shutil.which("node"):
        return
    texto = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
    ini = texto.index("const ordemModeloChat")
    fim = texto.index("function provedoresChat")
    ids = ["kr/claude-haiku-4.5", "kr/claude-sonnet-4.5", "kr/claude-opus-5", "kr/claude-sonnet-5.5",
           "kr/claude-opus-5.5", "kr/claude-sonnet-5", "kr/claude-opus-4.8", "kr/claude-sonnet-4.6"]
    script = (texto[ini:fim] + f"const ids={json.dumps(ids)};"
              "console.log(JSON.stringify(ids.map(id=>({id})).sort((a,b)=>ordemModeloChat(a)-ordemModeloChat(b)).map(m=>m.id)));")
    saida = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30).stdout
    assert json.loads(saida) == [
        "kr/claude-opus-5.5", "kr/claude-sonnet-5.5", "kr/claude-opus-5", "kr/claude-sonnet-5",
        "kr/claude-opus-4.8", "kr/claude-sonnet-4.6", "kr/claude-sonnet-4.5", "kr/claude-haiku-4.5"]

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

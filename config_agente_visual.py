"""Preferências próprias do agente visual; não muda as rotas de conversa."""
import os
import llm
import preferencias


def configuracao():
    return {
        "provedor": preferencias.obter("visual_provedor") or os.getenv("EMILY_AGENTE_UI_PROVEDOR", "omniroute"),
        "modelo": preferencias.obter("visual_modelo") or os.getenv("EMILY_AGENTE_UI_MODELO", "kr/claude-opus-5"),
        "raciocinio": preferencias.obter("visual_raciocinio") or os.getenv("EMILY_AGENTE_UI_RACIOCINIO", "medio"),
    }


def estado():
    atual = configuracao()
    return {**atual, "provedores": llm.listar_provedores(),
            "niveis": llm.niveis_raciocinio(atual["modelo"])}


def definir(provedor, modelo, raciocinio):
    provedores = {p["id"]: p for p in llm.listar_provedores()}
    p = provedores.get(provedor)
    if not p or modelo not in {m["id"] for m in p["modelos"]}:
        return False
    if raciocinio not in {n["id"] for n in llm.niveis_raciocinio(modelo)}:
        return False
    return preferencias.definir(visual_provedor=provedor, visual_modelo=modelo,
                                visual_raciocinio=raciocinio)

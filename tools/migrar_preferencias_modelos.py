"""Migra as preferências de modelo salvas dos GPT-6 (Codex) para o Kiro.

Só altera chaves que ainda apontam para um modelo cx/ ou para o provedor
openai; escolhas que já estão no Kiro ficam como estão. Usa o módulo
preferencias, que grava de forma atômica e respeita a sincronização.
Uso: python3 tools/migrar_preferencias_modelos.py [--aplicar]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import preferencias  # noqa: E402

ALVO = {
    ("provedor", "modelo"): ("omniroute", "kr/claude-sonnet-5.5"),
    ("visual_provedor", "visual_modelo"): ("omniroute", "kr/claude-opus-5"),
}


def _obsoleto(provedor: str, modelo: str) -> bool:
    return (provedor or "").strip().lower() == "openai" or (modelo or "").startswith("cx/")


def main():
    aplicar = "--aplicar" in sys.argv
    mudancas = {}
    for (chave_prov, chave_mod), (prov, mod) in ALVO.items():
        if _obsoleto(preferencias.obter(chave_prov) or "", preferencias.obter(chave_mod) or ""):
            mudancas[chave_prov], mudancas[chave_mod] = prov, mod
    discord = preferencias.obter("modelo_discord") or ""
    if discord.startswith("cx/"):
        mudancas["modelo_discord"] = ""  # vazio = padrão da rota (o Sonnet 5.5)
    # Raciocínios só do GPT-6 não existem nos Claude: cai pro equivalente.
    for chave in ("raciocinio", "visual_raciocinio"):
        if (preferencias.obter(chave) or "") in {"desligado", "extra_alto", "maximo"}:
            mudancas[chave] = "alto" if preferencias.obter(chave) != "desligado" else "baixo"
    if not mudancas:
        print("nada a migrar")
        return
    for k, v in mudancas.items():
        print(f"{k}: {preferencias.obter(k)!r} -> {v!r}")
    if aplicar:
        print("aplicado" if preferencias.definir(**mudancas) else "FALHOU ao gravar")
    else:
        print("(simulação; rode com --aplicar)")


if __name__ == "__main__":
    main()

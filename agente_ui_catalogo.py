"""Catálogo real de ferramentas compartilhado pelo agente visual e pela Emily."""
from __future__ import annotations

# Não iniciar outro controlador do desktop dentro da sessão que já o controla.
EXCLUIDAS = frozenset({"executar_na_tela", "assistir_tela", "parar_assistir_tela",
                      "definir_modo", "modo_bastidor"})


def catalogo(dominios=()):
    import ferramentas
    esquemas = ferramentas.esquemas(grupos=["geral", *dominios])
    return [e for e in esquemas if e["function"]["name"] not in EXCLUIDAS]


def texto_catalogo(esquemas):
    import json
    # Parâmetros inteiros; descrições compactas evitam pagar o catálogo inteiro
    # de conversa a cada captura e a cada verificação de clique.
    itens = []
    for e in esquemas:
        f = e["function"]
        itens.append({"nome": f["name"], "descricao": f["description"][:650],
                      "parametros": f["parameters"]})
    return json.dumps(itens, ensure_ascii=False, separators=(",", ":"))

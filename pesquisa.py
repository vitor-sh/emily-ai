import re
import urllib.parse
import webbrowser


def _extrair_query(mensagem: str) -> str:
    texto = mensagem.strip()

    # Remove "Emily" no início (com ou sem vírgula/ponto de exclamação)
    texto = re.sub(r"^emily\s*[,!]?\s*", "", texto, flags=re.IGNORECASE).strip()

    # Remove verbos de pesquisa + complementos como "para mim", "pra mim", "na internet"
    texto = re.sub(
        r"^(me\s+)?(pesquisa|pesquise|pesquisar|procure|procurar|procura|busque|buscar|busca)"
        r"(\s+(para\s+mim|pra\s+mim|na\s+internet|isso))*\s*",
        "",
        texto,
        flags=re.IGNORECASE,
    ).strip()

    # Se sobrou nada, usa a mensagem original pra não pesquisar vazio
    return texto if texto else mensagem


def pesquisar(query: str) -> str:
    query_limpa = _extrair_query(query)
    url = f"https://www.google.com/search?q={urllib.parse.quote(query_limpa)}"
    webbrowser.open(url)
    return f"Abrindo a pesquisa por '{query_limpa}' no navegador!"
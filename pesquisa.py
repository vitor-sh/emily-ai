import re
import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

# Headers de navegador realistas para scraping de páginas
_HEADERS_SCRAPING = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def _extrair_query(mensagem: str) -> str:
    texto = mensagem.strip()

    # Se for uma URL do Google (ex: https://www.google.com/search?q=...), extrai só o q=
    match_google = re.search(r"[?&]q=([^&]+)", texto)
    if match_google:
        import urllib.parse
        return urllib.parse.unquote_plus(match_google.group(1))

    # Se for qualquer outra URL, descarta e usa a mensagem original
    if re.match(r"https?://", texto):
        return mensagem

    # Remove "Emily" no início
    texto = re.sub(r"^emily\s*[,!]?\s*", "", texto, flags=re.IGNORECASE).strip()

    # Remove verbos de pesquisa e complementos
    texto = re.sub(
        r"^(me\s+)?(pesquisa|pesquise|pesquisar|procure|procurar|procura|busque|buscar|busca)"
        r"(\s+(para\s+mim|pra\s+mim|na\s+internet|isso))*\s*",
        "",
        texto,
        flags=re.IGNORECASE,
    ).strip()

    return texto if texto else mensagem


def _extrair_conteudo_pagina(url: str) -> str:
    """Acessa uma URL e extrai o texto principal da página."""
    try:
        resp = requests.get(
            url,
            timeout=4,  # timeout reduzido pra não travar a resposta
            headers=_HEADERS_SCRAPING,
            allow_redirects=True,
        )

        # Não lança exceção em 4xx/5xx — só ignora silenciosamente
        if not resp.ok:
            return None

        # Garante que a resposta é HTML antes de tentar parsear
        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove partes inúteis
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        texto = soup.get_text(separator=" ", strip=True)
        texto = re.sub(r"\s+", " ", texto).strip()

        # Retorna None se o conteúdo for muito curto (página bloqueou ou veio vazia)
        if len(texto) < 200:
            return None

        # Limita a 1500 chars — suficiente pra LLM resumir, sem engordar o contexto
        return texto[:1500]

    except Exception:
        return None


def pesquisar(query: str) -> str:
    query_limpa = _extrair_query(query)

    # Valida que a query não está vazia ou é só espaços
    query_limpa = query_limpa.strip()
    if not query_limpa:
        return "Não entendi o que você quer pesquisar."

    # Limita o tamanho da query (Brave rejeita queries muito longas com 422)
    if len(query_limpa) > 400:
        query_limpa = query_limpa[:400]

    print(f"[PESQUISA] Query enviada para Brave: '{query_limpa}'")

    if not BRAVE_API_KEY:
        return "Erro: chave da API do Brave não encontrada no .env"

    # IMPORTANTE: NÃO setar Accept-Encoding manualmente — o requests gerencia a
    # descompressão gzip automaticamente. Setar manualmente desativa esse comportamento.
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": BRAVE_API_KEY,
    }

    params = {
        "q": query_limpa,
        "count": 5,
        "country": "BR",
    }

    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers=headers,
            params=params,
            timeout=10,
        )

        if response.status_code == 401:
            return "Erro: chave da API do Brave inválida ou expirada."
        elif response.status_code == 422:
            print(f"[PESQUISA] Erro 422 — query rejeitada pela API: '{query_limpa}'")
            print(f"[PESQUISA] Resposta da API: {response.text[:300]}")
            return f"Não consegui pesquisar isso. Tenta reformular a pergunta."
        elif response.status_code == 429:
            return "Limite de requisições da API do Brave atingido. Tente novamente em alguns segundos."
        elif not response.ok:
            print(f"[PESQUISA] Erro {response.status_code}: {response.text[:300]}")
            return f"A API do Brave retornou erro {response.status_code}."

        dados = response.json()

        resultados = dados.get("web", {}).get("results", [])

        if not resultados:
            return f"Não encontrei nada sobre '{query_limpa}'."

        # --- Passo 1: snippets dos 5 resultados ---
        linhas = [f"Resultados da pesquisa sobre '{query_limpa}':\n"]
        for i, r in enumerate(resultados, 1):
            titulo = r.get("title", "Sem título")
            descricao = r.get("description", "Sem descrição")
            url = r.get("url", "")
            linhas.append(f"{i}. {titulo}\n   {descricao}\n   {url}\n")

        resumo_snippets = "\n".join(linhas)

        # --- Passo 2: conteúdo completo da 1ª página, com fallback pra 2ª e 3ª ---
        conteudo = None
        fonte_usada = None

        for r in resultados[:3]:
            url = r.get("url", "")
            titulo = r.get("title", "")
            if not url:
                continue

            conteudo = _extrair_conteudo_pagina(url)
            if conteudo:
                fonte_usada = titulo
                break  # Achou conteúdo útil, não precisa tentar a próxima

        if conteudo:
            resumo_snippets += f"\n\nConteúdo detalhado de '{fonte_usada}':\n\n{conteudo}"
        else:
            # Nenhuma página funcionou, usa só os snippets
            resumo_snippets += "\n\n(Não foi possível acessar o conteúdo completo das páginas. Use os snippets acima para responder.)"

        return resumo_snippets

    except requests.exceptions.Timeout:
        return "A pesquisa demorou demais e deu timeout."
    except requests.exceptions.ConnectionError:
        return "Sem conexão com a internet para pesquisar."
    except requests.exceptions.RequestException as e:
        return f"Erro ao pesquisar: {e}"
    except Exception as e:
        return f"Erro inesperado na pesquisa: {e}"

"""Regressões da pesquisa multi-site invisível (tudo simulado, sem rede real)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import pesquisa  # noqa: E402


def _fonte(indice: int, tamanho: int = 900) -> dict:
    return {
        "url": f"https://site{indice}.example/artigo?utm_source=teste",
        "titulo": f"Fonte {indice}",
        "conteudo": (f"Informação verificável da fonte {indice}. " * 80)[:tamanho],
        "origens": ["teste"],
    }


def test_url_canonica_remove_rastreadores_e_fragmento():
    assert pesquisa._url_canonica(
        "HTTPS://WWW.Example.COM/noticia/?utm_source=x&id=7#trecho"
    ) == "https://www.example.com/noticia?id=7"


def test_contexto_suficiente_nao_abre_extensao_nem_faz_busca_extra(monkeypatch):
    monkeypatch.setattr(pesquisa, "BRAVE_API_KEY", "teste")

    def contexto(_query, _perfil, fontes):
        for indice in range(1, 6):
            fonte = _fonte(indice)
            fonte["conteudo"] = ("Energia solar: dados verificáveis. " * 35)[:900]
            fontes[fonte["url"]] = fonte
        return True, ""

    monkeypatch.setattr(pesquisa, "_consultar_contexto_brave", contexto)
    monkeypatch.setattr(
        pesquisa, "_consultar_web_brave",
        lambda *_a, **_k: pytest.fail("Web Search não deveria ser chamada"),
    )
    monkeypatch.setattr(
        pesquisa, "pesquisa_via_extensao",
        lambda *_a, **_k: pytest.fail("A extensão nunca deve participar"),
    )
    monkeypatch.setattr(pesquisa, "_enriquecer_via_http", lambda *_a: None)
    monkeypatch.setattr(pesquisa, "_complementar_headless", lambda *_a: None)

    resultado = pesquisa.pesquisar("pesquise energia solar", "rapida")

    assert "PESQUISA WEB INVISÍVEL" in resultado
    assert "2 fontes de 2 sites" in resultado
    assert "site1.example" in resultado


def test_busca_profunda_expande_consultas_ate_obter_cobertura(monkeypatch):
    monkeypatch.setattr(pesquisa, "BRAVE_API_KEY", "teste")
    chamadas = []

    monkeypatch.setattr(
        pesquisa, "_consultar_contexto_brave", lambda *_a, **_k: (False, ""))

    def web(query, offset, fontes):
        chamadas.append((query, offset))
        indice = len(chamadas)
        fonte = _fonte(indice, tamanho=1000)
        fonte["conteudo"] = ("Baterias residenciais: comparação verificável. " * 25)[:1000]
        fontes[fonte["url"]] = fonte
        return True, True, ""

    monkeypatch.setattr(pesquisa, "_consultar_web_brave", web)
    monkeypatch.setattr(pesquisa, "_enriquecer_via_http", lambda *_a: None)
    monkeypatch.setattr(pesquisa, "_complementar_headless", lambda *_a: None)

    resultado = pesquisa.pesquisar("comparar baterias residenciais", "profunda")

    assert len(chamadas) == 5
    assert len({query for query, _ in chamadas}) == 2
    assert any(offset == 2 for _, offset in chamadas)
    assert "5 fontes de 5 sites" in resultado
    assert "detalhes fontes dados" in resultado
    assert "comparação análise" not in resultado


def test_pesquisa_profunda_para_com_cinco_fontes_relevantes(monkeypatch):
    monkeypatch.setattr(pesquisa, "BRAVE_API_KEY", "teste")

    def contexto(_query, perfil, fontes):
        assert perfil["inicio"] == 6
        for indice in range(1, 7):
            fonte = _fonte(indice, tamanho=1000)
            fonte["conteudo"] = ("Benchmarks de chips gráficos e desempenho. " * 30)[:1000]
            fontes[fonte["url"]] = fonte
        return True, ""

    monkeypatch.setattr(pesquisa, "_consultar_contexto_brave", contexto)
    monkeypatch.setattr(
        pesquisa, "_consultar_web_brave",
        lambda *_a, **_k: pytest.fail("Já havia evidência suficiente"))
    monkeypatch.setattr(
        pesquisa, "_enriquecer_via_http",
        lambda *_a: pytest.fail("Não precisa ler páginas extras"))
    monkeypatch.setattr(
        pesquisa, "_complementar_headless",
        lambda *_a: pytest.fail("Não precisa abrir navegador"))

    resultado = pesquisa.pesquisar("benchmarks de chips gráficos", "profunda")

    assert "5 fontes de 5 sites" in resultado
    assert "--- Fonte 6:" not in resultado


def test_muitos_snippets_rasos_nao_contam_como_base_suficiente(monkeypatch):
    monkeypatch.setattr(pesquisa, "BRAVE_API_KEY", "teste")
    enriquecer = []

    def contexto(_query, _perfil, fontes):
        for indice in range(1, 21):
            fonte = _fonte(indice, tamanho=300)
            fonte["conteudo"] = ("Benchmark de chips gráficos. " * 12)[:300]
            fontes[fonte["url"]] = fonte
        return True, ""

    monkeypatch.setattr(pesquisa, "_consultar_contexto_brave", contexto)
    monkeypatch.setattr(pesquisa, "_consultar_web_brave", lambda *_a, **_k: (False, False, ""))
    monkeypatch.setattr(
        pesquisa, "_enriquecer_via_http",
        lambda *_a: enriquecer.append(True))
    monkeypatch.setattr(pesquisa, "_complementar_headless", lambda *_a: None)

    pesquisa.pesquisar("benchmark de chips gráficos", "profunda")

    assert enriquecer


def test_modelos_openai_conferem_catalogo_oficial_mesmo_com_cobertura_suficiente(monkeypatch):
    monkeypatch.setattr(pesquisa, "BRAVE_API_KEY", "teste")

    def contexto(_query, _perfil, fontes):
        for indice in range(1, 6):
            fonte = _fonte(indice, tamanho=1300)
            fonte["conteudo"] = "Catálogo antigo de modelos OpenAI. " * 60
            fontes[fonte["url"]] = fonte
        return True, ""

    monkeypatch.setattr(pesquisa, "_consultar_contexto_brave", contexto)
    monkeypatch.setattr(
        pesquisa, "_extrair_conteudo_pagina",
        lambda url, limite=5000: (
            "Informações gerais do catálogo oficial. " * 50
            + "Modelos disponíveis: GPT-6 Astra, GPT-6 Sol e GPT-6 Luna. " * 20
            if url == pesquisa._CATALOGO_MODELOS_OPENAI else None
        ),
    )
    monkeypatch.setattr(
        pesquisa, "_consultar_web_brave",
        lambda *_a, **_k: pytest.fail("Catálogo oficial já respondeu"),
    )
    monkeypatch.setattr(pesquisa, "_enriquecer_via_http", lambda *_a: None)
    monkeypatch.setattr(pesquisa, "_complementar_headless", lambda *_a: None)

    resultado = pesquisa.pesquisar(
        "modelos mais recentes da OpenAI lançamentos oficiais API ChatGPT 2026")

    assert "Fonte 1: Catálogo oficial de modelos da OpenAI" in resultado
    assert "GPT-6 Astra" in resultado
    assert resultado.index("developers.openai.com/api/docs/models") < resultado.index("site1.example")


def test_catalogo_oficial_indisponivel_usa_busca_em_ingles(monkeypatch):
    monkeypatch.setattr(pesquisa, "BRAVE_API_KEY", "teste")
    monkeypatch.setattr(pesquisa, "_consultar_contexto_brave", lambda *_a: (False, ""))
    monkeypatch.setattr(pesquisa, "_extrair_conteudo_pagina", lambda *_a, **_k: None)
    monkeypatch.setattr(pesquisa, "_enriquecer_via_http", lambda *_a: None)
    monkeypatch.setattr(pesquisa, "_complementar_headless", lambda *_a: None)
    chamadas = []

    def web(query, offset, fontes, **kwargs):
        chamadas.append((query, kwargs))
        for indice in range(1, 6):
            fonte = _fonte(indice)
            fontes[fonte["url"]] = fonte
        return True, False, ""

    monkeypatch.setattr(pesquisa, "_consultar_web_brave", web)

    pesquisa.pesquisar("modelos da OpenAI")

    assert chamadas[0] == (
        "OpenAI latest models site:developers.openai.com", {"idioma": "en"})


def test_consulta_atual_faz_busca_recente_mesmo_com_muitos_trechos(monkeypatch):
    monkeypatch.setattr(pesquisa, "BRAVE_API_KEY", "teste")

    def contexto(_query, _perfil, fontes):
        for indice in range(1, 6):
            fonte = _fonte(indice, tamanho=1300)
            fonte["conteudo"] = ("Versão atual do Python: informação verificável. " * 30)[:1300]
            fontes[fonte["url"]] = fonte
        return True, ""

    chamadas = []
    monkeypatch.setattr(pesquisa, "_consultar_contexto_brave", contexto)
    monkeypatch.setattr(
        pesquisa, "_consultar_web_brave",
        lambda query, offset, fontes, **kwargs: (
            chamadas.append((query, offset, kwargs)) or False, False, ""),
    )
    monkeypatch.setattr(pesquisa, "_enriquecer_via_http", lambda *_a: None)
    monkeypatch.setattr(pesquisa, "_complementar_headless", lambda *_a: None)

    pesquisa.pesquisar("qual é a versão atual do Python?")

    assert chamadas == [
        ("a versão atual do Python?", 0, {"freshness": "py"})]


def test_busca_brave_recebe_filtro_de_recencia_e_idioma(monkeypatch):
    class Resposta:
        status_code = 200
        ok = True

        def json(self):
            return {"web": {"results": []}}

    requisicoes = []
    monkeypatch.setattr(
        pesquisa, "_brave_get",
        lambda _url, *, params, timeout: (
            requisicoes.append((params, timeout)) or Resposta()),
    )

    pesquisa._consultar_web_brave(
        "latest software version", 0, {}, freshness="py", idioma="en")

    assert requisicoes[0][0]["freshness"] == "py"
    assert requisicoes[0][0]["search_lang"] == "en"
    assert requisicoes[0][0]["country"] == "US"


def test_ferramenta_informa_falha_quando_pesquisa_nao_tem_fontes(monkeypatch):
    import ferramentas

    monkeypatch.setattr(
        pesquisa, "pesquisar", lambda *_a, **_k: "Não encontrei fontes úteis.")
    resultado = ferramentas._pesquisar("versão atual do Python")

    assert resultado.ok is False
    assert resultado.mudou is False
    assert "não conseguiu verificar" in resultado.texto


def test_parser_do_llm_context_aceita_grounding_generic():
    fontes = {}
    adicionadas = pesquisa._fontes_do_contexto({
        "grounding": {
            "generic": [{
                "url": "https://example.com/fato",
                "title": "Título",
                "snippets": [
                    {"text": "Primeiro trecho suficientemente detalhado para teste."},
                    {"text": "Segundo trecho suficientemente detalhado para teste."},
                ],
            }],
        },
    }, fontes)

    assert adicionadas == 1
    fonte = next(iter(fontes.values()))
    assert "Primeiro trecho" in fonte["conteudo"]
    assert "Segundo trecho" in fonte["conteudo"]
    assert fonte["origens"] == ["Brave LLM Context"]


def test_extracao_http_recusa_rede_privada_antes_do_download(monkeypatch):
    monkeypatch.setattr(
        pesquisa.socket, "getaddrinfo",
        lambda *_a, **_k: [(2, 1, 6, "", ("192.168.0.10", 80))],
    )
    monkeypatch.setattr(
        pesquisa.requests, "get",
        lambda *_a, **_k: pytest.fail("HTTP não pode rodar para endereço privado"),
    )

    assert pesquisa._extrair_conteudo_pagina("http://painel.example/segredo") is None


def test_catalogo_e_prompt_explicam_pesquisa_invisivel():
    import ferramentas
    import modelo

    ferramenta = ferramentas.CATALOGO["pesquisar_internet"]
    assert ferramenta.somente_leitura is True
    assert "não abre Brave" in ferramenta.descricao
    assert "não precisa da extensão" in ferramenta.descricao

    bloco_web = modelo._bloco_web()
    assert "pesquisa informacional comum usa diretamente pesquisar_internet" in bloco_web
    assert "NUNCA ligue modo_bastidor" in bloco_web
    assert "NUNCA use a extensão" in bloco_web

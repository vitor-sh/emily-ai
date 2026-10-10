"""Contratos do prompt adaptativo e da camada visual de respostas ricas."""

from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]


def test_prompt_formata_resposta_complexa_sem_documentar_conversa_casual():
    import modelo

    prompt = modelo.EMILY_PERSONALIDADE
    assert "CONVERSA CASUAL" in prompt
    assert "PESQUISA, comparação, explicação técnica" in prompt
    assert "tabela Markdown" in prompt
    assert "Cada título" in prompt and "própria linha" in prompt
    assert "nunca devolva um paredão de texto" in prompt
    assert "Continue\ncoloquial, direta e tsundere" in prompt


def test_frontend_tem_componentes_visuais_para_markdown_rico():
    js = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
    css = (RAIZ / "web" / "estilo.css").read_text(encoding="utf-8")
    html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

    assert "_separadorTabela" in js
    assert 'class="md-tabela-wrap"' in js
    assert "_marcarMensagemEstruturada" in js
    assert ".msg-corpo h1" in css
    assert ".md-tabela" in css
    assert "overflow-x: auto" in css
    assert '<link rel="stylesheet" href="estilo.css?v=' in html
    assert '<script src="app.js?v=' in html


def test_tts_converte_tabela_e_titulos_em_fala_natural():
    import modelo

    texto = (
        "## Comparação\n\n"
        "| Modelo | Velocidade | Preço |\n"
        "|---|---:|:---:|\n"
        "| GLM | 90 tokens/s | barato |\n"
        "| Claude | 70 tokens/s | caro |\n\n"
        "> O preço ainda pesa.\n\n---\n\n**Veredito:** GLM."
    )
    fala = modelo.limpar_para_tts(texto)

    assert "Comparação" in fala
    assert "Modelo, Velocidade, Preço." in fala
    assert "GLM, 90 tokens/s, barato." in fala
    assert "O preço ainda pesa." in fala
    assert "Veredito: GLM." in fala
    assert "|" not in fala and "---" not in fala and "#" not in fala

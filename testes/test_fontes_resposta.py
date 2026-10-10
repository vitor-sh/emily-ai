"""Fontes reais da pesquisa acompanham a resposta até o histórico."""

from __future__ import annotations


def test_extracao_de_fontes_usa_apenas_links_de_resultados():
    import pesquisa

    resultado = (
        "--- Fonte 1: Página oficial ---\nSite: example.org\n"
        "URL: https://example.org/noticia?utm_source=busca\nTexto.\n\n"
        "--- Fonte 2: Outra fonte ---\nSite: outro.org\n"
        "URL: https://outro.org/analise\nTexto.\n\n"
        "--- Fonte 3: Repetida ---\nSite: example.org\n"
        "URL: https://example.org/noticia\nTexto.\n\n"
        "--- Fonte 4: URL insegura ---\nSite: example.org\n"
        "URL: https://usuario:senha@example.org/segredo\nTexto."
    )
    assert pesquisa.extrair_fontes_do_resultado(resultado) == [
        {"titulo": "Página oficial", "url": "https://example.org/noticia"},
        {"titulo": "Outra fonte", "url": "https://outro.org/analise"},
    ]


def test_fontes_aparecem_ao_responder_e_reabrir_conversa(tmp_path, monkeypatch):
    import conversas
    import interface_web

    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "conversas.json")
    monkeypatch.setattr(conversas, "_cache", None)
    ponte = interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    ponte._cid = conversas.criar("Compare os modelos")
    ponte._resposta_emily = ""
    ponte._resposta_crua = ""
    ponte._falas_processo = []
    ponte._filtro_tags_stream = interface_web._FiltroStreamingTagsDeVoz()
    eventos = []
    ponte._push = lambda evento, dados: eventos.append((evento, dados))

    ponte.progresso_evento("inicio", {})
    ponte.progresso_evento("resultado", {
        "nome": "pesquisar_internet", "ok": True,
        "resultado": "--- Fonte 1: Fonte real ---\nSite: example.org\n"
                     "URL: https://example.org/benchmark\nConteúdo.",
    })
    ponte.progresso_evento("resposta", {"texto": "Veja a comparação."})
    ponte._salvar_resposta_emily()

    assert next(d for evento, d in eventos if evento == "resposta")["fontes"] == [
        {"titulo": "Fonte real", "url": "https://example.org/benchmark"}]
    monkeypatch.setattr(conversas, "_cache", None)
    assert conversas.abrir(ponte._cid)[-1]["fontes"] == [
        {"titulo": "Fonte real", "url": "https://example.org/benchmark"}]

    ponte.progresso_evento("inicio", {})
    ponte.progresso_evento("resposta", {"texto": "Resposta sem pesquisa."})
    ponte._salvar_resposta_emily()
    assert "fontes" not in conversas.abrir(ponte._cid)[-1]


def test_sincronizacao_nao_apaga_fontes_de_mensagem_igual(tmp_path, monkeypatch):
    import conversas

    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "conversas.json")
    monkeypatch.setattr(conversas, "_cache", None)
    cid = conversas.criar("Pesquisa")
    conversas.acrescentar(cid, "emily", "Resposta", fontes=[
        {"titulo": "Fonte", "url": "https://example.org/fonte"}])
    anterior = conversas.abrir(cid)[-1]
    assert conversas.gravar_externa(
        cid, "Pesquisa", 1, 9999999999, [
            {"papel": "assistant", "texto": "Resposta", "quando": anterior["quando"]}])
    assert conversas.abrir(cid)[-1]["fontes"] == anterior["fontes"]


def test_resposta_sem_pesquisa_descarta_fontes_do_turno_anterior():
    import interface_web

    ponte = interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    ponte._falas_processo = []
    ponte._resposta_crua = ""
    ponte._filtro_tags_stream = interface_web._FiltroStreamingTagsDeVoz()
    ponte._fontes_pesquisa_turno = [
        {"titulo": "Antiga", "url": "https://example.org/antiga"}]
    eventos = []
    ponte._push = lambda evento, dados: eventos.append((evento, dados))

    ponte.progresso_evento("resposta", {"texto": "Outra resposta.", "fontes": []})

    assert ponte._resposta_fontes == []
    assert eventos[-1] == ("resposta", {"texto": "Outra resposta."})

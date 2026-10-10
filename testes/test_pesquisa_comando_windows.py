"""Pesquisa de instalação respeita o sistema em que a Emily está rodando."""

from types import SimpleNamespace


def test_pesquisa_de_comando_no_windows_nao_recomenda_linux(monkeypatch):
    import pesquisa

    consultas = []

    class Resposta:
        status_code = 200
        ok = True

        def json(self):
            return {"web": {"results": [{"title": "Instalação oficial", "url": "https://example.com"}]}}

    monkeypatch.setattr(pesquisa, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(pesquisa, "BRAVE_API_KEY", "chave-de-teste")
    monkeypatch.setattr(pesquisa.requests, "get", lambda *args, **kwargs:
                        consultas.append(kwargs["params"]["q"]) or Resposta())

    resposta = pesquisa.pesquisar_comando("exemplo")

    assert "Windows 11" in consultas[0]
    assert "linux" not in consultas[0].lower()
    assert "Windows 11" in resposta
    assert "distro" not in resposta.lower()

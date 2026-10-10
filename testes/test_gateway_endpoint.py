import pytest

import gateway_endpoint


@pytest.mark.parametrize("valor", [
    "http://teste.ngrok-free.dev", "https://teste.ngrok-free.dev:5000",
    "https://teste.ngrok-free.dev/caminho", "https://teste.ngrok-free.dev@outro.ngrok-free.dev",
    "https://teste.ngrok-free.dev:porta", "https://example.com",
])
def test_endpoint_rejeita_enderecos_inseguros(valor):
    with pytest.raises(ValueError):
        gateway_endpoint.validar_url(valor)


def test_endpoint_aceita_dominio_ngrok():
    assert gateway_endpoint.validar_url(" https://teste.ngrok-free.dev/ ") == \
        "https://teste.ngrok-free.dev"

"""Contrato dos quadros e da ponte de estados do pet do Fedora."""

from types import SimpleNamespace

from PIL import Image, ImageChops

import pet_desktop_fedora
import preferencias


def test_quadros_sao_distintos_transparentes_e_completos():
    dados = pet_desktop_fedora.validar_assets()
    assert len(dados["states"]) == 10
    assert {"idle_sit", "idle_ram", "idle_star"}.issubset(
        pet_desktop_fedora.IDLES_OCASIONAIS)
    assert all(len(dados["states"][nome]["frames"]) == 9
               for nome in ("idle_sit", "idle_ram", "idle_star"))
    assert dados["states"]["idle_sit"]["loop_segment"] == [3, 6, 2]
    assert "pet_desktop_ativo" not in preferencias.SINCRONIZAVEIS
    assert "pet_desktop_tamanho" not in preferencias.SINCRONIZAVEIS
    for estado, item in dados["states"].items():
        quadros = [Image.open(pet_desktop_fedora.BASE / rel).convert("RGBA")
                   for rel in item["frames"]]
        assert all(q.size == (240, 260) for q in quadros), estado
        assert all(q.getchannel("A").getbbox() for q in quadros), estado
        assert all(q.getpixel((0, 0))[3] == 0 for q in quadros), estado
        assert any(ImageChops.difference(quadros[0], q).getbbox()
                   for q in quadros[1:]), estado


def test_tamanho_limita_intervalo_e_usa_padrao_para_entrada_invalida():
    assert pet_desktop_fedora.tamanho_valido(25) == 50
    assert pet_desktop_fedora.tamanho_valido("75") == 75
    assert pet_desktop_fedora.tamanho_valido(200) == 130
    assert pet_desktop_fedora.tamanho_valido("inválido") == 100


def test_tamanho_salva_no_fedora_e_ajusta_pet_aberto(monkeypatch):
    import interface_web

    monkeypatch.setattr(interface_web, "ambiente_fedora", lambda: True)
    salvos = []
    monkeypatch.setattr(preferencias, "definir",
                        lambda **campos: salvos.append(campos) or True)
    enviados = []
    processo = SimpleNamespace(poll=lambda: None,
                              stdin=SimpleNamespace(write=enviados.append,
                                                    flush=lambda: None))
    api = SimpleNamespace(_j=SimpleNamespace(_sprite=processo))
    assert interface_web.Api.pet_tamanho_definir(api, 65)
    assert salvos == [{"pet_desktop_tamanho": 65}]
    assert enviados == ["size 65\n"]
    assert not interface_web.Api.pet_tamanho_definir(api, 20)
    assert len(salvos) == 1


def test_launcher_compilado_usa_backend_sem_moldura(monkeypatch):
    import interface_web
    import platform_compat
    import subprocess
    import sys

    monkeypatch.setattr(platform_compat, "is_linux", lambda: True)
    monkeypatch.setattr(preferencias, "obter",
                        lambda chave, padrao=None: padrao)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("GDK_BACKEND", raising=False)
    monkeypatch.setenv("EMILY_SPRITE", "1")
    chamadas = []
    processo = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(subprocess, "Popen",
                        lambda comando, **opcoes: chamadas.append((comando, opcoes)) or processo)

    class ThreadImediata:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(interface_web.threading, "Thread", ThreadImediata)
    janela = SimpleNamespace(_sprite=None, _ultimo_status=("aguardando",),
                            _ouvir_sprite=lambda _processo: janela._sprite_pronto.set(),
                            _sprite_reage=lambda _status: None)
    interface_web.JanelaEmily._iniciar_sprite(janela)
    assert chamadas[0][1]["env"]["GDK_BACKEND"] == "x11"
    assert chamadas[0][0][-2:] == ["--size", "100"]


def test_estados_reais_enviados_ao_pet(monkeypatch):
    import interface_web
    import platform_compat

    monkeypatch.setattr(platform_compat, "is_linux", lambda: True)
    enviados = []
    processo = SimpleNamespace(poll=lambda: None,
                              stdin=SimpleNamespace(write=enviados.append,
                                                    flush=lambda: None))
    janela = SimpleNamespace(_sprite=processo)
    for estado in ("aguardando", "ouvindo", "gravando", "pensando",
                   "ocupada", "monitorando", "falando"):
        interface_web.JanelaEmily._sprite_reage(janela, estado)
    assert enviados == ["state idle\n", "state listening\n", "state listening\n",
                       "state thinking\n", "state working\n", "state working\n",
                       "state speaking\n"]

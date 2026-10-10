"""O .env privado precisa estar disponível antes dos imports do desktop."""

from __future__ import annotations

import os
import sys

import pytest

import emily_bootstrap


def test_carrega_env_do_pacote_congelado(monkeypatch, tmp_path):
    pasta_exe = tmp_path / "Emily"
    pasta_pacote = pasta_exe / "_internal"
    pasta_pacote.mkdir(parents=True)
    (pasta_pacote / ".env").write_text(
        "GROQ_API_KEY=groq-teste\nFISH_AUDIO_KEY=fish-teste\n"
        "EMILY_PONTE_TOKEN=ponte-teste\n", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(pasta_exe / "Emily.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(pasta_pacote), raising=False)
    for nome in ("GROQ_API_KEY", "FISH_AUDIO_KEY", "EMILY_PONTE_TOKEN"):
        monkeypatch.delenv(nome, raising=False)

    emily_bootstrap._carregar_ambiente()
    emily_bootstrap._validar_configuracao_privada()
    assert os.environ["GROQ_API_KEY"] == "groq-teste"


def test_env_externo_prevalece_e_pacote_completa(monkeypatch, tmp_path):
    pasta_exe = tmp_path / "Emily"
    pasta_pacote = pasta_exe / "_internal"
    pasta_pacote.mkdir(parents=True)
    (pasta_exe / ".env").write_text("GROQ_API_KEY=groq-externo\n", encoding="utf-8")
    (pasta_pacote / ".env").write_text(
        "GROQ_API_KEY=groq-pacote\nFISH_AUDIO_KEY=fish-teste\n"
        "EMILY_PONTE_TOKEN=ponte-teste\n", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(pasta_exe / "Emily.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(pasta_pacote), raising=False)
    for nome in ("GROQ_API_KEY", "FISH_AUDIO_KEY", "EMILY_PONTE_TOKEN"):
        monkeypatch.delenv(nome, raising=False)

    emily_bootstrap._carregar_ambiente()
    assert os.environ["GROQ_API_KEY"] == "groq-externo"
    emily_bootstrap._validar_configuracao_privada()


def test_preflight_reprova_chaves_ausentes(monkeypatch):
    for nome in ("GROQ_API_KEY", "FISH_AUDIO_KEY", "EMILY_PONTE_TOKEN"):
        monkeypatch.delenv(nome, raising=False)
    with pytest.raises(SystemExit, match="GROQ_API_KEY"):
        emily_bootstrap._validar_configuracao_privada()

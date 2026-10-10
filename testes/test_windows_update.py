"""Publicação privada: versão nova só executa após SHA-256 e tamanho conferirem."""

from __future__ import annotations

import hashlib

import windows_update


class Resposta:
    def __init__(self, dados=None, blocos=()):
        self._dados = dados
        self._blocos = blocos

    def raise_for_status(self):
        pass

    def json(self):
        return self._dados

    def iter_content(self, _tamanho):
        yield from self._blocos

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


class Sessao:
    def __init__(self, dados, conteudo):
        self.dados = dados
        self.conteudo = conteudo

    def get(self, url, **_kw):
        return Resposta(blocos=[self.conteudo]) if url.endswith("/installer") else Resposta(self.dados)


def test_instalador_so_inicia_apos_integridade(monkeypatch, tmp_path):
    pacote = b"MZ" + b"instalador privado" * 5
    metadados = {"ok": True, "version": "1.1.0", "size": len(pacote),
                 "sha256": hashlib.sha256(pacote).hexdigest()}
    monkeypatch.setattr(windows_update, "_windows_empacotado", lambda: True)
    monkeypatch.setattr(windows_update, "_config", lambda: {"version": "1.0.0",
                                                             "update_url": "https://gateway.exemplo/windows/update"})
    monkeypatch.setattr(windows_update, "_token", lambda: "segredo")
    monkeypatch.setattr(windows_update, "arquivo_dados", lambda _nome: tmp_path / "updates")
    comandos = []
    monkeypatch.setattr(windows_update.subprocess, "Popen", lambda cmd, **_kw: comandos.append(cmd))
    assert windows_update.verificar_e_instalar(Sessao(metadados, pacote)) is True
    assert (tmp_path / "updates" / "Emily-Setup-1.1.0.exe").read_bytes() == pacote
    assert comandos[0][0].endswith("Emily-Setup-1.1.0.exe")

    metadados["sha256"] = "0" * 64
    comandos.clear()
    assert windows_update.verificar_e_instalar(Sessao(metadados, pacote)) is False
    assert comandos == []
    assert not (tmp_path / "updates" / "Emily-Setup-1.1.0.download").exists()


def test_sem_instalador_novo_consulta_codigo(monkeypatch):
    monkeypatch.setattr(windows_update, "_windows_empacotado", lambda: True)
    monkeypatch.setattr(windows_update, "_config", lambda: {
        "version": "1.0.2", "update_url": "https://gateway.exemplo/windows/update"})
    monkeypatch.setattr(windows_update, "_token", lambda: "segredo")
    chamado = []
    monkeypatch.setattr(windows_update, "_verificar_codigo", lambda sessao: chamado.append(sessao) or True)
    sessao = Sessao({"ok": False}, b"")
    assert windows_update.verificar_e_instalar(sessao) is True
    assert chamado == [sessao]

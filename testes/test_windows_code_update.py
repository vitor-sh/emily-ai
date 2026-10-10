"""O patch Windows só é aplicado após autenticação, hashes e ensaio."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

import publicar_windows_codigo as publicador
import windows_code_update as codigo
import windows_update


def _publicar_teste(tmp_path):
    fonte = tmp_path / "fonte"
    fonte.mkdir()
    (fonte / "main.py").write_text("print('novo')\n", encoding="utf-8")
    (fonte / "windows_update.py").write_text("VERSAO = 1\n", encoding="utf-8")
    (fonte / "windows_code_update.py").write_text("VERSAO = 1\n", encoding="utf-8")
    (fonte / "emily_bootstrap.py").write_text("SEGREDO = 1\n", encoding="utf-8")
    (fonte / ".env").write_text("API_KEY=privada", encoding="utf-8")
    (fonte / "web").mkdir()
    (fonte / "web" / "app.js").write_text("const atualizado = true;", encoding="utf-8")
    destino = tmp_path / "publicado"
    arquivo = publicador.publicar(1, "1.0.2", destino, fonte)
    dados = json.loads((destino / "latest.json").read_text(encoding="utf-8"))
    return arquivo, dados


def test_publicacao_nao_inclui_chaves_nem_bootstrap_congelado(tmp_path):
    arquivo, dados = _publicar_teste(tmp_path)
    with ZipFile(arquivo) as pacote:
        assert set(pacote.namelist()) == set(dados["files"])
        assert "main.py" in pacote.namelist()
        assert "web/app.js" in pacote.namelist()
        assert ".env" not in pacote.namelist()
        assert "emily_bootstrap.py" not in pacote.namelist()
    assert hashlib.sha256(arquivo.read_bytes()).hexdigest() == dados["sha256"]
    with pytest.raises(ValueError):
        publicador.publicar(1, "1.0.2", tmp_path / "publicado", tmp_path / "fonte")


def test_publicacao_seletiva_valida_os_arquivos(tmp_path):
    _publicar_teste(tmp_path)
    fonte = tmp_path / "fonte"
    destino = tmp_path / "so_codigo"
    arquivo = publicador.publicar(2, "1.0.2", destino, fonte,
                                 selecionar=["main.py", "windows_update.py"])
    with ZipFile(arquivo) as pacote:
        assert pacote.namelist() == ["main.py", "windows_update.py"]
    with pytest.raises(ValueError, match="não publicáveis"):
        publicador.publicar(3, "1.0.2", destino, fonte,
                            selecionar=[".env"])


def test_publicacao_seletiva_acumula_patches_para_quem_pulou_versao(tmp_path):
    arquivo1, manifesto1 = _publicar_teste(tmp_path)
    fonte = tmp_path / "fonte"
    (fonte / "main.py").write_text("print('versão 2')\n", encoding="utf-8")
    (fonte / "web" / "app.js").write_text("mudança ainda não aprovada", encoding="utf-8")
    arquivo2 = publicador.publicar(2, "1.0.2", tmp_path / "publicado", fonte,
                                   selecionar=["main.py"])
    with ZipFile(arquivo1) as pacote1, ZipFile(arquivo2) as pacote2:
        assert set(pacote2.namelist()) == set(manifesto1["files"])
        assert pacote2.read("main.py") == b"print('vers\xc3\xa3o 2')\n"
        assert pacote2.read("web/app.js") == pacote1.read("web/app.js")


def test_publicacao_pode_retirar_modulo_legado_do_pacote_cumulativo(tmp_path):
    fonte = tmp_path / "fonte"
    fonte.mkdir()
    (fonte / "main.py").write_text("VERSAO = 1\n", encoding="utf-8")
    (fonte / "interface.py").write_text("import PyQt6\n", encoding="utf-8")
    destino = tmp_path / "publicado"
    publicador.publicar(1, "1.0.2", destino, fonte)
    arquivo = publicador.publicar(2, "1.0.2", destino, fonte,
                                 selecionar=["main.py"], retirar=["interface.py"])
    with ZipFile(arquivo) as pacote:
        assert pacote.namelist() == ["main.py"]


class Resposta:
    def __init__(self, dados=None, body=b""):
        self._dados, self.body = dados, body

    def raise_for_status(self):
        pass

    def json(self):
        return self._dados

    def iter_content(self, _tamanho):
        yield self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


class Sessao:
    def __init__(self, dados, body):
        self.dados, self.body = dados, body

    def get(self, url, **_kwargs):
        return Resposta(body=self.body) if url.endswith("/archive") else Resposta(self.dados)


def test_patch_so_aplica_apos_validacao_e_ensaio(tmp_path, monkeypatch):
    arquivo, dados = _publicar_teste(tmp_path)
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "main.py").write_text("antigo", encoding="utf-8")
    monkeypatch.setattr(codigo, "_internal", lambda: internal)
    monkeypatch.setattr(codigo, "_preflight", lambda _stage: None)
    monkeypatch.setattr(windows_update, "_windows_empacotado", lambda: True)
    monkeypatch.setattr(windows_update, "_config", lambda: {
        "version": "1.0.2", "update_url": "https://gateway.exemplo/windows/update"})
    monkeypatch.setattr(windows_update, "_token", lambda: "segredo")
    lancamentos = []
    monkeypatch.setattr(codigo.subprocess, "Popen", lambda *args, **kw: lancamentos.append(args))
    dados["ok"] = True
    sessao = Sessao(dados, arquivo.read_bytes())
    assert codigo.verificar_e_aplicar(sessao)
    assert (internal / "main.py").read_text(encoding="utf-8") == "print('novo')\n"
    assert (internal / "_windows_code_backup_1" / "main.py").read_text() == "antigo"
    assert codigo._versao_local() == 1
    assert len(lancamentos) == 1
    assert codigo.verificar_e_aplicar(sessao) is False


def test_hash_errado_ou_instalador_diferente_nao_mexe_no_app(tmp_path, monkeypatch):
    arquivo, dados = _publicar_teste(tmp_path)
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "main.py").write_text("antigo", encoding="utf-8")
    monkeypatch.setattr(codigo, "_internal", lambda: internal)
    monkeypatch.setattr(codigo, "_preflight", lambda _stage: pytest.fail("ensaio indevido"))
    monkeypatch.setattr(windows_update, "_windows_empacotado", lambda: True)
    monkeypatch.setattr(windows_update, "_config", lambda: {
        "version": "1.0.2", "update_url": "https://gateway.exemplo/windows/update"})
    monkeypatch.setattr(windows_update, "_token", lambda: "segredo")
    dados["ok"] = True
    dados["sha256"] = "0" * 64
    assert codigo.verificar_e_aplicar(Sessao(dados, arquivo.read_bytes())) is False
    assert (internal / "main.py").read_text() == "antigo"
    dados["sha256"] = hashlib.sha256(arquivo.read_bytes()).hexdigest()
    dados["installer"] = "1.0.1"
    assert codigo.verificar_e_aplicar(Sessao(dados, arquivo.read_bytes())) is False
    assert (internal / "main.py").read_text() == "antigo"


def test_zip_com_traversal_recusado(tmp_path):
    arquivo = tmp_path / "mau.zip"
    with ZipFile(arquivo, "w") as pacote:
        pacote.writestr("../fora.py", "x = 1")
    dados = {"files": {"../fora.py": hashlib.sha256(b"x = 1").hexdigest()}}
    with pytest.raises(ValueError):
        codigo._extrair_validado(arquivo, tmp_path / "stage", dados)
    assert not (tmp_path.parent / "fora.py").exists()


def test_ensaio_falho_preserva_instalacao(tmp_path, monkeypatch):
    arquivo, dados = _publicar_teste(tmp_path)
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "main.py").write_text("antigo", encoding="utf-8")
    monkeypatch.setattr(codigo, "_internal", lambda: internal)
    monkeypatch.setattr(codigo, "_preflight", lambda _stage: (_ for _ in ()).throw(
        RuntimeError("ensaio recusou o patch")))
    monkeypatch.setattr(windows_update, "_windows_empacotado", lambda: True)
    monkeypatch.setattr(windows_update, "_config", lambda: {
        "version": "1.0.2", "update_url": "https://gateway.exemplo/windows/update"})
    monkeypatch.setattr(windows_update, "_token", lambda: "segredo")
    dados["ok"] = True
    assert codigo.verificar_e_aplicar(Sessao(dados, arquivo.read_bytes())) is False
    assert (internal / "main.py").read_text() == "antigo"
    assert not (internal / ".windows-code-version.json").exists()
    assert not (internal / "_windows_code_backup_1").exists()


def test_falha_durante_copia_restaura_arquivos(tmp_path, monkeypatch):
    internal = tmp_path / "_internal"
    staging = tmp_path / "stage"
    internal.mkdir()
    staging.mkdir()
    (internal / "a.py").write_text("antigo a", encoding="utf-8")
    (internal / "b.py").write_text("antigo b", encoding="utf-8")
    (staging / "a.py").write_text("novo a", encoding="utf-8")
    (staging / "b.py").write_text("novo b", encoding="utf-8")
    monkeypatch.setattr(codigo, "_internal", lambda: internal)
    copiar = codigo.shutil.copy2

    def falhar_no_segundo(origem, destino, *args, **kwargs):
        if Path(origem) == staging / "b.py":
            raise OSError("falha simulada no disco")
        return copiar(origem, destino, *args, **kwargs)

    monkeypatch.setattr(codigo.shutil, "copy2", falhar_no_segundo)
    with pytest.raises(OSError, match="falha simulada"):
        codigo._aplicar(staging, {"version": 1, "installer": "1.0.2",
                                 "files": {"a.py": "hash", "b.py": "hash"}})
    assert (internal / "a.py").read_text() == "antigo a"
    assert (internal / "b.py").read_text() == "antigo b"
    assert not (internal / ".windows-code-version.json").exists()


def test_ensaio_combina_modulos_ja_instalados_com_o_patch(tmp_path, monkeypatch):
    internal = tmp_path / "_internal"
    staging = tmp_path / "stage"
    internal.mkdir()
    staging.mkdir()
    (internal / "antigo.py").write_text("VERSAO = 1", encoding="utf-8")
    (staging / "novo.py").write_text("VERSAO = 2", encoding="utf-8")
    monkeypatch.setattr(codigo, "_internal", lambda: internal)

    def ensaio(_cmd, **kwargs):
        combinado = Path(kwargs["env"]["EMILY_OVERRIDE_DIR"])
        assert (combinado / "antigo.py").read_text() == "VERSAO = 1"
        assert (combinado / "novo.py").read_text() == "VERSAO = 2"
        Path(kwargs["env"]["EMILY_PREFLIGHT_OUT"]).write_text('{"rc": 0}')
        return type("Resultado", (), {"returncode": 0})()

    monkeypatch.setattr(codigo.subprocess, "run", ensaio)
    codigo._preflight(staging)

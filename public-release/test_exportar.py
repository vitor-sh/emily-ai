"""Verifica barreiras de publicação usando perfis temporários, sem iniciar a Emily."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

import pytest

SPEC = importlib.util.spec_from_file_location("exportar_publico", Path(__file__).with_name("exportar.py"))
exportar = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exportar)


@pytest.fixture
def projeto(tmp_path):
    raiz = tmp_path / "pessoal"
    kit = tmp_path / "kit"
    raiz.mkdir()
    (kit / "modelo").mkdir(parents=True)
    (raiz / "main.py").write_text('NOME = "Emily"\n')
    (kit / "modelo" / "README.md").write_text("Rascunho\n")
    (kit / "manifesto.json").write_text(json.dumps({"fontes": ["main.py"], "documentos": ["README.md"]}))
    return raiz, kit, tmp_path / "fontes.zip"


def test_lista_positiva_nao_leva_dados_nem_segredos(projeto):
    raiz, kit, destino = projeto
    for nome in (".env", "config.yaml", "memoria.json", "novo.py"):
        (raiz / nome).write_text("DADO_PRIVADO_NAO_EXPORTAR")
    relatorio = exportar.montar(destino, raiz, kit)
    with ZipFile(destino) as z:
        assert set(z.namelist()) == {"emily/main.py", "emily/README.md", "emily/EXPORTACAO.json"}
        assert all(b"DADO_PRIVADO_NAO_EXPORTAR" not in z.read(n) for n in z.namelist())
        for nome, item in relatorio["arquivos"].items():
            assert hashlib.sha256(z.read("emily/" + nome)).hexdigest() == item["sha256"]


@pytest.mark.parametrize("nome", ["../.env", "/tmp/main.py", "sub/../../main.py", "C:\\main.py",
                                 "config.yaml", "sub/.env.local", "runtime/arquivo.py"])
def test_recusa_inclusao_perigosa(projeto, nome):
    raiz, kit, destino = projeto
    (kit / "manifesto.json").write_text(json.dumps({"fontes": [nome], "documentos": []}))
    with pytest.raises(exportar.ExportacaoInsegura):
        exportar.montar(destino, raiz, kit)
    assert not destino.exists()


def test_segredo_nao_vaza_na_mensagem_nem_gera_zip(projeto):
    raiz, kit, destino = projeto
    canario = "ghp_" + "x" * 35
    (raiz / "main.py").write_text('CHAVE = "' + canario + '"\n')
    with pytest.raises(exportar.ExportacaoInsegura) as erro:
        exportar.montar(destino, raiz, kit)
    assert canario not in str(erro.value)
    assert not destino.exists()


def test_link_direto_e_pasta_linkada_sao_recusados(projeto, tmp_path):
    raiz, kit, destino = projeto
    original = tmp_path / "fora.py"
    original.write_text("TOKEN = 'segredo fora do projeto'\n")
    (raiz / "main.py").unlink()
    (raiz / "main.py").symlink_to(original)
    with pytest.raises(exportar.ExportacaoInsegura):
        exportar.montar(destino, raiz, kit)
    (raiz / "sub").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(exportar.ExportacaoInsegura):
        exportar.ler_seguro(raiz, "sub/fora.py")
    assert not destino.exists()


def test_preserva_destino_existente(projeto):
    raiz, kit, destino = projeto
    destino.write_bytes(b"PACOTE_ANTERIOR")
    with pytest.raises(FileExistsError):
        exportar.montar(destino, raiz, kit)
    assert destino.read_bytes() == b"PACOTE_ANTERIOR"


def test_falha_de_validacao_nao_deixa_pacote_parcial(projeto):
    raiz, kit, destino = projeto
    (kit / "modelo" / "README.md").write_text("-----BEGIN PRIVATE KEY-----")
    with pytest.raises(exportar.ExportacaoInsegura):
        exportar.montar(destino, raiz, kit)
    assert not destino.exists()
    assert not list(destino.parent.glob(".public-source-*"))


def test_publico_neutraliza_discord_sem_mudar_pessoal(projeto):
    raiz, _, _ = projeto
    pessoal = 'APELIDOS_MEMBROS = {123456789012345678: "Privado"}\n_CONFIG_PADRAO = {"coadmins_id": [123456789012345678], "nomes_do_dono": ["Pessoal"], "ouvir_call": True}\n'
    arquivo = raiz / "discord_bot.py"
    arquivo.write_text(pessoal)
    publico, mudancas = exportar.preparar_texto("discord_bot.py", arquivo.read_bytes())
    no = ast.parse(publico)
    valores = {n.targets[0].id: ast.literal_eval(n.value) for n in no.body}
    assert valores["APELIDOS_MEMBROS"] == {}
    config = valores["_CONFIG_PADRAO"]
    assert config["coadmins_id"] == [] and config["nomes_do_dono"] == []
    assert not config["ouvir_call"] and not config["permitir_admin"]
    assert arquivo.read_text() == pessoal and mudancas


def test_transformacao_aborta_se_codigo_mudou():
    with pytest.raises(exportar.ExportacaoInsegura):
        exportar.preparar_texto("voz.py", b"OUTRA_CONFIG = 1\n")


def test_referencia_de_variavel_nao_e_chave_mas_literal_e_bloqueado():
    exportar.verificar("llm.py", b'env_chave = "OPENAI_API_KEY"\n')
    with pytest.raises(exportar.ExportacaoInsegura):
        exportar.verificar("outro.py", b'TOKEN = "VALOR_PRIVADO_LONGO"\n')


@pytest.mark.parametrize("nome,conteudo", [
    ("outro.py", b'CONFIG = {"token": "VALOR_PRIVADO_LONGO"}\n'),
    (".env.example", b'OPENAI_API_KEY=valor-privado-sem-prefixo\n'),
    ("outro.py", b'URL = "https://worker.conta.workers.dev"\n'),
])
def test_recusa_segredos_sem_prefixo_e_endpoint_cloud(nome, conteudo):
    with pytest.raises(exportar.ExportacaoInsegura):
        exportar.verificar(nome, conteudo)


def test_caminho_do_mod_parametrizado_sem_alterar_referencias():
    bruto = b'<Project><HollowKnightRefs>/home/Hiucksam/jogo</HollowKnightRefs><HintPath>$(HollowKnightRefs)/game.dll</HintPath></Project>'
    publico, _ = exportar.preparar_texto("hollow_knight_emily/mod/EmilyCompanion.csproj", bruto)
    assert b"/home/" not in publico
    assert b"$(HollowKnightRefs)/game.dll" in publico
    import xml.etree.ElementTree as xml
    xml.fromstring(publico)


def test_zip_real_compila_fontes_e_preserva_hashes_pessoais(tmp_path):
    manifesto = json.loads((exportar.KIT / "manifesto.json").read_text())
    antes = {n: hashlib.sha256((exportar.RAIZ / n).read_bytes()).hexdigest() for n in manifesto["fontes"]}
    destino = tmp_path / "real.zip"
    relatorio = exportar.montar(destino)
    with ZipFile(destino) as z:
        assert z.testzip() is None
        assert b"GNU GENERAL PUBLIC LICENSE" in z.read("emily/LICENSE")
        for nome, item in relatorio["arquivos"].items():
            bruto = z.read("emily/" + nome)
            assert hashlib.sha256(bruto).hexdigest() == item["sha256"]
            if nome.endswith(".py"):
                compile(bruto, nome, "exec")
    assert antes == {n: hashlib.sha256((exportar.RAIZ / n).read_bytes()).hexdigest() for n in manifesto["fontes"]}


def test_gitignore_libera_so_exemplo_publico_e_preserva_segredos(tmp_path):
    (tmp_path / ".gitignore").write_bytes((exportar.RAIZ / ".gitignore").read_bytes())
    (tmp_path / "public-release" / "modelo").mkdir(parents=True)
    (tmp_path / "public-release" / ".gitignore").write_bytes((exportar.KIT / ".gitignore").read_bytes())
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    for nome, ignorado in [(".env", True), (".env.local", True),
                           ("perfil/configuracao.json", True), ("perfil/provedor.env", True),
                           ("public-release/modelo/.env.example", False),
                           ("public-release/modelo/.env.local", True),
                           ("public-release/output/fontes.zip", True)]:
        retorno = subprocess.run(["git", "check-ignore", "--no-index", nome], cwd=tmp_path, capture_output=True)
        assert retorno.returncode == (0 if ignorado else 1), nome

"""Fase 1: persistência e isolamento da memória unificada (sem rede/modelo)."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from memoria_unificada import (
    ArmazenamentoMemoria,
    ConfigMemoria,
    ErroEmbeddings,
    ErroEsquemaMemoria,
    EventoMemoria,
    FatoMemoria,
)
from memoria_unificada.embeddings import ProvedorOllama, validar_embeddings


class EmbeddingsFake:
    """Vetores semânticos pequenos e determinísticos para testes offline."""

    identificador = "fake:pt-v1"

    def gerar(self, textos):
        vetores = []
        for texto in textos:
            t = texto.lower()
            vetor = [0.05, 0.05, 0.05, 0.05]
            if any(p in t for p in ("python", "código", "codigo", "program")):
                vetor[0] += 1.0
            if any(p in t for p in ("música", "musica", "spotify")):
                vetor[1] += 1.0
            if any(p in t for p in ("curso", "faculdade", "estuda")):
                vetor[2] += 1.0
            if any(p in t for p in ("jogo", "elden", "steam")):
                vetor[3] += 1.0
            norma = math.sqrt(sum(x * x for x in vetor))
            vetores.append([x / norma for x in vetor])
        return vetores


class EmbeddingsOutro(EmbeddingsFake):
    identificador = "fake:pt-v2"


def _config(tmp_path: Path, nome: str = "emily_teste") -> ConfigMemoria:
    return ConfigMemoria(
        pasta_dados=tmp_path / "dados",
        nome_colecao=nome,
        provedor_embeddings="ollama",
        modelo_embeddings="ignorado-pelo-fake",
    )


def _storage(tmp_path: Path) -> ArmazenamentoMemoria:
    return ArmazenamentoMemoria(_config(tmp_path), EmbeddingsFake())


def _fato(
    texto: str,
    dono: str = "vitor",
    *,
    fato_id: str = "",
    privacidade: str = "owner_private",
    pool: str = "general",
    entidades=(),
) -> FatoMemoria:
    kwargs = {"id": fato_id} if fato_id else {}
    return FatoMemoria(
        owner_user_id=dono,
        texto=texto,
        importancia=8,
        canal_origem="web",
        entidades=tuple(entidades),
        conversa_origem_id="chat-1",
        eventos_origem_ids=("evento-1", "evento-2"),
        sujeito="Vitor",
        topico="preferencia",
        confianca=0.9,
        evidence_role="mixed",
        privacy_scope=privacidade,
        memory_pool=pool,
        **kwargs,
    )


def test_import_e_config_nao_criam_diretorio(tmp_path):
    pasta = tmp_path / "ainda-nao-existe"
    cfg = ConfigMemoria(
        pasta_dados=pasta,
        provedor_embeddings="ollama",
        modelo_embeddings="embeddinggemma",
    )

    assert cfg.habilitada is False
    assert cfg.pasta_chroma == pasta / "chroma"
    assert not pasta.exists()


def test_modelos_validam_identidade_e_classificacoes():
    with pytest.raises(ValueError, match="owner_user_id"):
        _fato("Vitor gosta de Python", dono="")
    with pytest.raises(ValueError, match="entre 1 e 10"):
        FatoMemoria("vitor", "fato", 11, "web")
    with pytest.raises(ValueError, match="papel"):
        EventoMemoria("vitor", "invasor", "oi", "discord")

    evento = EventoMemoria("vitor", "assistant", "Vou lembrar disso", "voz")
    assert evento.privacy_scope == "owner_private"
    assert evento.memory_pool == "general"


def test_roundtrip_preserva_metadados(tmp_path):
    storage = _storage(tmp_path)
    original = _fato(
        "Vitor prefere programar em Python",
        fato_id="fato-python",
        entidades=("Vitor", "Python", "Python"),
    )

    storage.salvar(original)
    carregado = storage.obter("vitor", original.id)

    assert carregado is not None
    assert carregado.id == original.id
    assert carregado.owner_user_id == original.owner_user_id
    assert carregado.texto == original.texto
    assert carregado.importancia == original.importancia
    assert carregado.canal_origem == original.canal_origem
    # Metadata numérica atravessa a serialização interna do Chroma e pode voltar
    # com diferença inferior a um microssegundo no Python 3.14.
    assert carregado.criado_em == pytest.approx(original.criado_em, abs=1e-6)
    assert carregado.atualizado_em == pytest.approx(original.atualizado_em, abs=1e-6)
    assert carregado.confianca == pytest.approx(original.confianca)
    assert carregado.evidence_role == original.evidence_role
    assert carregado.privacy_scope == original.privacy_scope
    assert carregado.memory_pool == original.memory_pool
    assert carregado.entidades == ("Vitor", "Python")
    assert carregado.eventos_origem_ids == ("evento-1", "evento-2")


def test_busca_isola_usuario_privacidade_e_pool(tmp_path):
    storage = _storage(tmp_path)
    storage.salvar(_fato("Vitor programa em Python", fato_id="vitor-geral"))
    storage.salvar(_fato(
        "Decisão Python do Emily Code", fato_id="vitor-code", pool="code"))
    storage.salvar(_fato(
        "Segredo privado sobre Python", dono="discord:22", fato_id="terceiro"))
    storage.salvar(_fato(
        "Post público sobre Python", fato_id="publico", privacidade="public"))

    so_geral_privado = storage.buscar(
        "vitor",
        "Qual linguagem de programação?",
        privacy_scopes=("owner_private",),
        pools=("general",),
    )
    ids = {r.fato.id for r in so_geral_privado}
    assert ids == {"vitor-geral"}
    assert "terceiro" not in ids

    todos_do_vitor = storage.buscar("vitor", "Python", limite=10)
    ids = {r.fato.id for r in todos_do_vitor}
    assert ids == {"vitor-geral", "vitor-code", "publico"}
    assert all(r.fato.owner_user_id == "vitor" for r in todos_do_vitor)

    do_terceiro = storage.buscar("discord:22", "Python", limite=10)
    assert [r.fato.id for r in do_terceiro] == ["terceiro"]
    assert storage.obter("vitor", "terceiro") is None


def test_owner_e_obrigatorio_em_toda_leitura(tmp_path):
    storage = _storage(tmp_path)
    with pytest.raises(ValueError, match="owner_user_id"):
        storage.buscar("", "Python")
    with pytest.raises(ValueError, match="owner_user_id"):
        storage.listar("")
    with pytest.raises(ValueError, match="owner_user_id"):
        storage.obter("", "qualquer")


def test_id_colidente_nao_sobrescreve_memoria_de_outro_usuario(tmp_path):
    storage = _storage(tmp_path)
    original = _fato("Segredo de uma pessoa", dono="discord:7", fato_id="mesmo-id")
    storage.salvar(original)

    with pytest.raises(ValueError, match="outro usuário"):
        storage.salvar(_fato("Tentativa do Vitor", dono="vitor", fato_id="mesmo-id"))

    preservado = storage.obter("discord:7", "mesmo-id")
    assert preservado is not None
    assert preservado.id == original.id
    assert preservado.owner_user_id == original.owner_user_id
    assert preservado.texto == original.texto
    assert storage.obter("vitor", "mesmo-id") is None


def test_esquecer_remove_da_busca_sem_apagar(tmp_path):
    storage = _storage(tmp_path)
    fato = storage.salvar(_fato("Vitor estuda um curso antigo", fato_id="curso-antigo"))

    esquecido = storage.esquecer("vitor", fato.id)

    assert esquecido.status == "forgotten"
    assert storage.buscar("vitor", "curso antigo") == []
    preservado = storage.obter("vitor", fato.id)
    assert preservado is not None
    assert preservado.status == "forgotten"
    assert [f.id for f in storage.listar("vitor", status=("forgotten",))] == [fato.id]


def test_superseder_mantem_historico_e_ativa_o_novo(tmp_path):
    storage = _storage(tmp_path)
    antigo = storage.salvar(_fato("Vitor cursa História", fato_id="curso-1"))
    novo = _fato("Vitor mudou para Ciência da Computação", fato_id="curso-2")

    storage.superseder("vitor", antigo.id, novo)

    velho_salvo = storage.obter("vitor", antigo.id)
    assert velho_salvo.status == "superseded"
    assert velho_salvo.superseded_by == novo.id
    assert storage.obter("vitor", novo.id).status == "active"
    assert {r.fato.id for r in storage.buscar("vitor", "qual curso?", limite=10)} == {
        novo.id
    }


def test_nao_permite_superseder_fato_de_outro_usuario(tmp_path):
    storage = _storage(tmp_path)
    storage.salvar(_fato("Pessoa gosta de jogos", dono="discord:7", fato_id="pessoa"))

    with pytest.raises(KeyError):
        storage.superseder("vitor", "pessoa", _fato("Vitor gosta de jogos"))
    with pytest.raises(ValueError, match="outro usuário"):
        storage.superseder(
            "discord:7",
            "pessoa",
            _fato("Atualização", dono="discord:8"),
        )


def test_persiste_apos_reabrir_cliente(tmp_path):
    cfg = _config(tmp_path)
    primeiro = ArmazenamentoMemoria(cfg, EmbeddingsFake())
    primeiro.salvar(_fato("Vitor ouve música no Spotify", fato_id="musica"))

    reaberto = ArmazenamentoMemoria(cfg, EmbeddingsFake())

    assert reaberto.obter("vitor", "musica").texto == "Vitor ouve música no Spotify"
    assert reaberto.contar("vitor") == 1


def test_persiste_apos_reabrir_em_outro_processo(tmp_path):
    cfg = _config(tmp_path)
    storage = ArmazenamentoMemoria(cfg, EmbeddingsFake())
    storage.salvar(_fato("Vitor programa em Python", fato_id="entre-processos"))
    raiz_projeto = Path(__file__).resolve().parent.parent
    script = textwrap.dedent(f"""
        import sys
        from pathlib import Path
        sys.path.insert(0, {str(raiz_projeto)!r})
        from memoria_unificada import ArmazenamentoMemoria, ConfigMemoria

        class Fake:
            identificador = "fake:pt-v1"
            def gerar(self, textos):
                return [[1.0, 0.0, 0.0, 0.0] for _ in textos]

        cfg = ConfigMemoria(
            pasta_dados=Path({str(cfg.pasta_dados)!r}),
            nome_colecao={cfg.nome_colecao!r},
            provedor_embeddings="ollama",
            modelo_embeddings="ignorado-pelo-fake",
        )
        fato = ArmazenamentoMemoria(cfg, Fake()).obter("vitor", "entre-processos")
        print(fato.texto if fato else "NAO_ENCONTROU")
    """)

    resultado = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=raiz_projeto,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == "Vitor programa em Python"


def test_escritas_concorrentes_nao_perdem_fatos(tmp_path):
    storage = _storage(tmp_path)

    def salvar(indice):
        return storage.salvar(_fato(
            f"Vitor programa em Python no projeto {indice}",
            fato_id=f"concorrente-{indice}",
        )).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = set(executor.map(salvar, range(24)))

    assert len(ids) == 24
    assert storage.contar("vitor") == 24
    assert {f.id for f in storage.listar("vitor", limite=30)} == ids


def test_recusa_reabrir_com_modelo_de_embedding_diferente(tmp_path):
    cfg = _config(tmp_path)
    ArmazenamentoMemoria(cfg, EmbeddingsFake())

    with pytest.raises(ErroEsquemaMemoria, match="não.*mistur|misturar"):
        ArmazenamentoMemoria(cfg, EmbeddingsOutro())


@pytest.mark.parametrize("vetores,quantidade", [
    ([], 1),
    ([[0.0, 0.0]], 1),
    ([[1.0], [1.0, 2.0]], 2),
    ([[float("nan"), 1.0]], 1),
])
def test_validador_rejeita_embeddings_invalidos(vetores, quantidade):
    with pytest.raises(ErroEmbeddings):
        validar_embeddings(vetores, quantidade)


def test_ollama_envia_lote_e_le_resposta(monkeypatch):
    visto = {}

    class RespostaFake:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"embeddings": [[1, 0], [0, 1]]}).encode()

    def urlopen_fake(requisicao, timeout):
        visto["url"] = requisicao.full_url
        visto["corpo"] = json.loads(requisicao.data.decode())
        visto["timeout"] = timeout
        return RespostaFake()

    monkeypatch.setattr("urllib.request.urlopen", urlopen_fake)
    provedor = ProvedorOllama("embeddinggemma", "http://127.0.0.1:11434", 7)

    assert provedor.gerar(["um", "dois"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert visto == {
        "url": "http://127.0.0.1:11434/api/embed",
        "corpo": {
            "model": "embeddinggemma",
            "input": ["um", "dois"],
            "truncate": True,
            # keep_alive pro Ollama NÃO descarregar o modelo após ~5min de
            # inatividade — o cold-load da próxima consulta custou 10,4s medidos.
            "keep_alive": "30m",
        },
        "timeout": 7.0,
    }
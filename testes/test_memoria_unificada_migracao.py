"""Fase 6: migração das memórias antigas (offline).

As fontes legadas são substituídas por JSONs falsos em tmp_path via monkeypatch
nos caminhos do módulo. Nada toca nos arquivos reais; os testes provam leitura
read-only, idempotência, namespaces e limites.
"""

import hashlib
import json
from pathlib import Path

import pytest

from memoria_unificada import ConfigMemoria
from memoria_unificada.armazenamento import ArmazenamentoMemoria
from memoria_unificada.embeddings import ProvedorEmbeddings
from memoria_unificada.journal import JournalMemoria
from memoria_unificada.migracao import FONTES_VALIDAS, MigradorMemoria


class EmbeddingsFake(ProvedorEmbeddings):
    identificador = "fake:fase6"

    def gerar(self, textos):
        return [[1.0, 0.0, 0.0] for _ in textos]


def _config(tmp_path: Path) -> ConfigMemoria:
    return ConfigMemoria(
        habilitada=True,
        pasta_dados=tmp_path / "dados",
        nome_colecao="emily_fase6",
        provedor_embeddings="ollama",
        modelo_embeddings="fake",
    )


def _extracao_fake_para(fato_por_pool):
    """LLM falso ancorado nos ids de evento que aparecem no prompt."""
    import re

    def chamar(prompt, **_extra):
        ids = list(dict.fromkeys(re.findall(r"(?:evt_)?[0-9a-f]{28,32}", prompt)))
        if not ids:
            return '{"facts": []}'
        pool = ("code" if "SQLite" in prompt or "refator" in prompt.lower()
                else "general")
        spec = fato_por_pool.get(pool)
        if not spec:
            return '{"facts": []}'
        texto, topico = spec
        return json.dumps({"facts": [{
            "text": texto, "importance": 8, "entities": ["Vitor"],
            "subject": "Vitor", "topic": topico, "confidence": 0.9,
            "source_event_ids": ids,
        }]}, ensure_ascii=False)
    return chamar


def _armazenamento(config, tmp_path):
    return ArmazenamentoMemoria(config, EmbeddingsFake())


@pytest.fixture()
def fontes_falsas(tmp_path, monkeypatch):
    """Cria fontes legadas falsas e aponta o módulo pra elas."""
    import memoria_unificada.migracao as migracao

    pasta = tmp_path / "fontes"
    pasta.mkdir()

    def escrever(nome, conteudo):
        caminho = pasta / nome
        caminho.write_text(json.dumps(conteudo, ensure_ascii=False),
                           encoding="utf-8")
        return caminho

    memoria = escrever("memoria.json", {
        "nome_usuario": "Vitor",
        "fatos": [
            "Vitor gosta de Hollow Knight.",
            "Vitor tem 19 anos e mora em Belo Horizonte.",
        ],
    })
    discord = escrever("memoria_discord.json", {
        "membros": {
            "111": {"nome": "Amigo Um", "fatos": ["Ama jogar no PC"],
                    "visto_em": 1000.0, "extraido_em": 1100.0},
            "222": {"nome": "Mah", "fatos": [], "visto_em": 1000.0},
        },
        "estilo": {},
    })
    conversas = escrever("conversas.json", {"conversas": [
        {"id": "conv-1", "titulo": "t", "criada": 5000.0,
         "mensagens": [
             {"papel": "user", "texto": "Minha cor favorita é azul",
              "quando": 5000.0},
             {"papel": "emily", "texto": "Anotado!", "quando": 5001.0},
         ]},
    ]})
    code = escrever("code.json", {"conversas": [
        {"id": "code-1", "titulo": "t", "criada": 6000.0,
         "mensagens": [
             {"papel": "user", "texto": "Vamos usar SQLite WAL no journal?",
              "quando": 6000.0},
             {"papel": "emily", "texto": "Implementado.", "quando": 6001.0},
         ]},
    ]})
    dms = escrever("dms.json", {"usuarios": {
        "999": {"nome": "Desconhecido", "mensagens": [
            {"quem": "pessoa", "texto": "oi emily", "quando": 7000.0},
            {"quem": "emily", "texto": "oi!", "quando": 7001.0},
        ]},
        "1195765414400106626": {"nome": "Vitor", "mensagens": [
            {"quem": "pessoa", "texto": "lembra do meu jogo favorito?",
             "quando": 8000.0},
        ]},
    }})
    config_bot = escrever("bot.json", {"usuario_id": "1195765414400106626"})

    monkeypatch.setattr(migracao, "CAMINHO_MEMORIA", memoria)
    monkeypatch.setattr(migracao, "CAMINHO_MEMORIA_DISCORD", discord)
    monkeypatch.setattr(migracao, "CAMINHO_CONVERSAS", conversas)
    monkeypatch.setattr(migracao, "CAMINHO_CODE", code)
    monkeypatch.setattr(migracao, "CAMINHO_DMS", dms)
    monkeypatch.setattr(migracao, "CAMINHO_CONFIG_DISCORD", config_bot)
    return migracao


def _hash_fontes(fontes_falsas):
    return {
        str(caminho): hashlib.sha256(caminho.read_bytes()).hexdigest()
        for caminho in (
            fontes_falsas.CAMINHO_MEMORIA, fontes_falsas.CAMINHO_MEMORIA_DISCORD,
            fontes_falsas.CAMINHO_CONVERSAS, fontes_falsas.CAMINHO_CODE,
            fontes_falsas.CAMINHO_DMS, fontes_falsas.CAMINHO_CONFIG_DISCORD)
    }


def test_planejar_le_tudo_e_nao_grava_nada(tmp_path, fontes_falsas):
    antes = _hash_fontes(fontes_falsas)
    migrador = MigradorMemoria(config=_config(tmp_path), dono="vitor")

    plano = migrador.planejar()

    assert plano["dono_discord_id"] == "1195765414400106626"
    assert plano["fontes"]["memoria"] == {"fatos": 2}
    assert plano["fontes"]["discord"] == {"fatos": 1}  # Mah não tem fatos
    assert plano["fontes"]["conversas"] == {"conversas": 1, "eventos": 2,
                                            "ignoradas": 0}
    assert plano["fontes"]["code"] == {"conversas": 1, "eventos": 2,
                                       "ignoradas": 0}
    assert plano["fontes"]["dms"] == {"pessoas": 2, "eventos": 3}
    assert len(plano["fatos_diretos"]) == 3
    assert len(plano["eventos"]) == 7
    # Dry-run não cria banco, coleção nem pasta de dados.
    assert not (tmp_path / "dados").exists()
    # E as fontes continuam byte a byte iguais.
    assert _hash_fontes(fontes_falsas) == antes


def test_executar_e_idempotente(tmp_path, fontes_falsas):
    config = _config(tmp_path)
    migrador = MigradorMemoria(
        config=config, dono="vitor", provedor_embeddings=EmbeddingsFake(),
        chamar_extracao=_extracao_fake_para({
            "general": ("Vitor prefere a cor azul", "strong_preference"),
            "code": ("Decidimos usar SQLite WAL no journal",
                     "architecture_decision"),
        }))
    antes = _hash_fontes(fontes_falsas)

    primeiro = migrador.executar()

    assert primeiro["fatos_gravados"] == 3
    assert primeiro["eventos"] == 7
    assert primeiro["erros"] == []
    assert _hash_fontes(fontes_falsas) == antes

    donos = {f.owner_user_id for f in _armazenamento(config, tmp_path).listar(
        "discord:111", status=("active", "superseded", "forgotten"))}
    assert donos == {"discord:111"}  # fato curado do membro no namespace dele

    segundo = migrador.executar()

    assert segundo["fatos_gravados"] == 0
    assert segundo["fatos_ja_existiam"] == 3
    assert segundo["erros"] == []
    journal = JournalMemoria(config)
    # Idempotência de eventos: nada duplicou no journal.
    # dono: 2 (conversas) + 2 (code) + 1 (DM do próprio dono) = 5
    assert journal.contar_eventos("vitor") == 5
    assert journal.contar_eventos("discord:999") == 2


def test_namespaces_e_isolamento(tmp_path, fontes_falsas):
    config = _config(tmp_path)
    migrador = MigradorMemoria(
        config=config, dono="vitor", provedor_embeddings=EmbeddingsFake(),
        chamar_extracao=_extracao_fake_para({
            "general": ("Vitor gosta de algo", "strong_preference"),
        }))
    migrador.executar()
    armazenamento = _armazenamento(config, tmp_path)

    # A memória do dono não vê fato curado de terceiro.
    do_dono = armazenamento.listar("vitor")
    assert do_dono
    assert all(not f.texto.startswith("Ama jogar") for f in do_dono)

    # O namespace da pessoa vê o fato dela.
    da_pessoa = armazenamento.listar("discord:111")
    assert any("Ama jogar no PC" in f.texto for f in da_pessoa)


def test_limite_eventos_mantem_recentes(tmp_path, fontes_falsas):
    migrador = MigradorMemoria(config=_config(tmp_path), dono="vitor")

    plano = migrador.planejar(fontes=["conversas"], limite_eventos=1)

    assert len(plano["eventos"]) == 1
    assert plano["eventos"][0].texto == "Anotado!"  # o mais recente da conversa


def test_fonte_invalida(tmp_path):
    migrador = MigradorMemoria(config=_config(tmp_path), dono="vitor")
    with pytest.raises(ValueError):
        migrador.planejar(fontes=["roubada"])
    assert set(FONTES_VALIDAS) == {"memoria", "conversas", "code", "discord",
                                   "dms"}


def test_executar_com_extracao_real(tmp_path, fontes_falsas):
    """Ponta a ponta com extração: eventos viram fatos nos pools certos."""
    config = _config(tmp_path)
    migrador = MigradorMemoria(
        config=config, dono="vitor", provedor_embeddings=EmbeddingsFake(),
        chamar_extracao=_extracao_fake_para({
            "general": ("Vitor prefere a cor azul", "strong_preference"),
            "code": ("Decidimos usar SQLite WAL no journal",
                     "architecture_decision"),
        }))
    migrador.executar(fontes=["conversas", "code"])
    armazenamento = _armazenamento(config, tmp_path)

    geral = armazenamento.listar("vitor", pools=("general",))
    code = armazenamento.listar("vitor", pools=("code",))
    assert any("cor azul" in f.texto for f in geral)
    assert all(f.memory_pool == "code" for f in code)
    assert any("SQLite WAL" in f.texto for f in code)


def test_dm_do_dono_vai_pro_namespace_dele(tmp_path, fontes_falsas):
    config = _config(tmp_path)
    migrador = MigradorMemoria(
        config=config, dono="vitor",
        provedor_embeddings=EmbeddingsFake(),
        chamar_extracao=lambda **_k: '{"facts": []}')
    migrador.executar(fontes=["dms"])
    journal = JournalMemoria(config)

    eventos_dono = journal.listar_recentes("vitor", limite=50)
    eventos_pessoa = journal.listar_recentes("discord:999", limite=50)

    assert any("jogo favorito" in e.texto for e in eventos_dono)
    assert all("jogo favorito" not in e.texto for e in eventos_pessoa)
    assert all(e.canal == "discord_dm" for e in eventos_dono + eventos_pessoa)

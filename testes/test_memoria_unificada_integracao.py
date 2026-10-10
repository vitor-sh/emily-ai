"""Fase 4: integração da memória unificada no fluxo real (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

import modelo
import memoria_unificada as mu
from memoria_unificada import PonteMemoria, dono_id
from memoria_unificada.integracao import _reset_para_testes, id_discord
from memoria_unificada.armazenamento import ErroArmazenamentoMemoria


class EmbeddingsFake:
    identificador = "fake:fase4"

    def gerar(self, textos):
        return [[1.0, 0.0, 0.0] for _ in textos]


def _config(tmp_path: Path, habilitada: bool = True):
    from memoria_unificada import ConfigMemoria

    return ConfigMemoria(
        habilitada=habilitada,
        pasta_dados=tmp_path / "dados",
        nome_colecao="emily_fase4",
        provedor_embeddings="ollama",
        modelo_embeddings="fake",
    )


def _ponte_ligada(tmp_path: Path, chamar_extracao=None) -> PonteMemoria:
    ponte = PonteMemoria(
        config=_config(tmp_path),
        provedor_embeddings=EmbeddingsFake(),
        chamar_extracao=chamar_extracao or (lambda **_: '{"facts": []}'),
    )
    _reset_para_testes(ponte)
    return ponte


def _ponte_desligada(tmp_path: Path) -> PonteMemoria:
    ponte = PonteMemoria(config=_config(tmp_path, habilitada=False))
    _reset_para_testes(ponte)
    return ponte


@pytest.fixture(autouse=True)
def _limpar_estado():
    yield
    _reset_para_testes()
    modelo._turno_pool_memoria = "general"


# ═════════════════════════════════════════════════════════════════
# FLAG E CIRCUIT BREAKER
# ═════════════════════════════════════════════════════════════════

def test_config_carrega_env_do_projeto_sem_depender_do_cwd(tmp_path, monkeypatch):
    from memoria_unificada import config as config_mod

    arquivo = tmp_path / ".env"
    arquivo.write_text("EMILY_MEMORIA_UNIFICADA=1\n", encoding="utf-8")
    monkeypatch.delenv("EMILY_MEMORIA_UNIFICADA", raising=False)
    monkeypatch.setattr(config_mod, "_candidatos_env", lambda: (arquivo,))
    monkeypatch.chdir(tmp_path.parent)

    assert config_mod.carregar_config().habilitada is True


def test_variavel_exportada_tem_precedencia_sobre_env(tmp_path, monkeypatch):
    from memoria_unificada import config as config_mod

    arquivo = tmp_path / ".env"
    arquivo.write_text("EMILY_MEMORIA_UNIFICADA=1\n", encoding="utf-8")
    monkeypatch.setenv("EMILY_MEMORIA_UNIFICADA", "0")
    monkeypatch.setattr(config_mod, "_candidatos_env", lambda: (arquivo,))

    assert config_mod.carregar_config().habilitada is False


def test_config_nao_exporta_outras_chaves_do_env(tmp_path, monkeypatch):
    from memoria_unificada import config as config_mod

    arquivo = tmp_path / ".env"
    arquivo.write_text(
        "EMILY_MEMORIA_UNIFICADA=1\nCHAVE_ALHEIA_A_MEMORIA=segredo\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("EMILY_MEMORIA_UNIFICADA", raising=False)
    monkeypatch.delenv("CHAVE_ALHEIA_A_MEMORIA", raising=False)
    monkeypatch.setattr(config_mod, "_candidatos_env", lambda: (arquivo,))

    assert config_mod.carregar_config().habilitada is True
    assert "CHAVE_ALHEIA_A_MEMORIA" not in __import__("os").environ


def test_singleton_atualiza_config_criada_antes_do_env(monkeypatch):
    import memoria_unificada.integracao as integracao

    desligada = _config(Path("/tmp/memu-config-cedo"), habilitada=False)
    ligada = _config(Path("/tmp/memu-config-cedo"), habilitada=True)
    monkeypatch.setattr(integracao, "carregar_config", lambda: desligada)
    criada_cedo = PonteMemoria()
    _reset_para_testes(criada_cedo)
    monkeypatch.setattr(integracao, "carregar_config", lambda: ligada)

    assert mu.ponte() is criada_cedo
    assert criada_cedo.estado()["flag"] is True


def test_flag_desligada_ponte_inativa(tmp_path):
    ponte = _ponte_desligada(tmp_path)

    assert ponte.ativa is False
    assert modelo._memoria_unificada_ativa() is False
    assert modelo._bloco_memoria_unificada("qualquer coisa") == ""
    # Registrar com flag desligada é no-op silencioso (sem banco criado).
    ponte.registrar_troca(dono_id(), "web", "oi", "olá")
    assert not (tmp_path / "dados" / "journal.sqlite3").exists()


def test_circuit_breaker_pausa_e_reativa_sem_restart(tmp_path, monkeypatch):
    import memoria_unificada.integracao as integracao

    relogio = {"agora": 100.0}
    monkeypatch.setattr(integracao.time, "monotonic", lambda: relogio["agora"])
    ponte = PonteMemoria(
        config=_config(tmp_path),
        provedor_embeddings=EmbeddingsFake(),
        chamar_extracao=lambda **_: '{"facts": []}',
    )
    _reset_para_testes(ponte)
    # Pasta de dados dentro de /proc: toda operação falha na frente do breaker.
    ponte.config.__dict__["pasta_dados"] = Path("/proc/nao_da/emily")

    for _ in range(3):
        ponte.registrar_troca(dono_id(), "web", "oi", "olá")

    assert ponte.estado()["desativada_por_erro"] is True
    assert ponte.ativa is False
    assert modelo._memoria_unificada_ativa() is False

    relogio["agora"] += integracao._PAUSA_APOS_FALHAS_SEGUNDOS + 1
    assert ponte.ativa is True
    assert ponte.estado()["desativada_por_erro"] is False
    assert ponte.estado()["falhas_consecutivas"] == 0


def test_sem_chromadb_mantem_journal_contexto_e_nao_abre_circuito(
    tmp_path, monkeypatch,
):
    import memoria_unificada.integracao as integracao

    def sem_vetor(*_args, **_kwargs):
        raise ErroArmazenamentoMemoria("dependência vetorial ausente no runtime")

    monkeypatch.setattr(integracao, "ArmazenamentoMemoria", sem_vetor)
    ponte = PonteMemoria(
        config=_config(tmp_path), provedor_embeddings=EmbeddingsFake(),
        chamar_extracao=lambda **_: '{"facts": []}',
    )
    _reset_para_testes(ponte)

    ponte.registrar_troca(
        dono_id(), "web", "isto é importante para lembrar", "vou lembrar")
    for _ in range(5):
        bloco = ponte.bloco_contexto(dono_id(), "importante")

    estado = ponte.estado()
    eventos = ponte._servico.journal.listar_recentes(dono_id(), limite=10)
    assert estado["ativa"] is True
    assert estado["modo_degradado"] is True
    assert estado["desativada_por_erro"] is False
    assert estado["falhas_consecutivas"] == 0
    assert "dependência vetorial ausente" in estado["ultimo_erro"]
    assert [(e.papel, e.texto) for e in eventos] == [
        ("user", "isto é importante para lembrar"),
        ("assistant", "vou lembrar"),
    ]
    assert "CONVERSA RECENTE" in bloco
    assert "isto é importante" in bloco
    assert mu.ponte_completa() is False


def test_modo_degradado_tenta_restaurar_camada_vetorial(tmp_path, monkeypatch):
    import memoria_unificada.integracao as integracao

    armazenamento_real = integracao.ArmazenamentoMemoria
    monkeypatch.setattr(
        integracao, "ArmazenamentoMemoria",
        lambda *_a, **_k: (_ for _ in ()).throw(
            ErroArmazenamentoMemoria("vetor temporariamente fora")),
    )
    ponte = PonteMemoria(
        config=_config(tmp_path), provedor_embeddings=EmbeddingsFake(),
        chamar_extracao=lambda **_: '{"facts": []}',
    )
    _reset_para_testes(ponte)
    ponte.registrar_troca(dono_id(), "web", "oi", "olá")
    assert ponte.estado()["modo_degradado"] is True

    monkeypatch.setattr(integracao, "ArmazenamentoMemoria", armazenamento_real)
    ponte._retry_vetorial_em = 0.0
    assert ponte._pronta() is not None
    assert ponte.estado()["modo_degradado"] is False
    assert ponte.estado()["ultimo_erro"] == ""


def test_api_explica_modo_degradado_sem_mandar_reiniciar(tmp_path, monkeypatch):
    import memoria_unificada.integracao as integracao

    monkeypatch.setattr(
        integracao, "ArmazenamentoMemoria",
        lambda *_a, **_k: (_ for _ in ()).throw(
            ErroArmazenamentoMemoria("dependência chromadb ausente")),
    )
    ponte = PonteMemoria(
        config=_config(tmp_path), provedor_embeddings=EmbeddingsFake(),
        chamar_extracao=lambda **_: '{"facts": []}',
    )
    _reset_para_testes(ponte)
    ponte.registrar_troca(dono_id(), "web", "lembre disso", "anotado")

    from interface_web import Api
    estado = Api(None).memoria_unificada_estado()

    assert estado["ativa"] is True
    assert estado["modo_degradado"] is True
    assert estado["eventos_total"] == 2
    assert estado["lotes_pendentes"] == 0
    assert "chromadb" in estado["erro"]


def test_dono_e_discord_ids():
    assert dono_id() == "vitor"
    assert id_discord(12345) == "discord:12345"


def test_terceiro_nao_ve_memoria_do_dono(tmp_path):
    ponte = _ponte_ligada(tmp_path)
    ponte.registrar_troca(
        dono_id(), "web", "Vitor contou um segredo importante", "boa!")
    ponte.bloco_contexto(dono_id(), "segredo")  # força o serviço a subir

    bloco_terceiro = ponte.bloco_contexto(
        id_discord(999), "segredo importante")

    assert bloco_terceiro == ""


def test_pool_code_isolado_do_geral(tmp_path):
    ponte = _ponte_ligada(tmp_path)
    ponte.registrar_troca(
        dono_id(), "emily_code",
        "decidimos usar SQLite WAL no journal", "implementado.",
        memory_pool="code")
    ponte.bloco_contexto(dono_id(), "SQLite WAL", memory_pool="code")

    no_geral = ponte.bloco_contexto(dono_id(), "SQLite WAL journal")
    no_code = ponte.bloco_contexto(dono_id(), "SQLite WAL", memory_pool="code")

    assert "MEMÓRIA RELEVANTE" not in no_geral
    assert "CONVERSA RECENTE" not in no_geral
    assert "SQLite WAL" in no_code


# ═════════════════════════════════════════════════════════════════
# CONVERSAR_STREAM — injeção e registro de verdade no modelo
# ═════════════════════════════════════════════════════════════════

def _falso_chamar_llm(capturadas):
    def chamar(mensagens, rota=None, max_tokens=None, stream=False, **_extra):
        capturadas.append(list(mensagens))
        if stream:
            return iter(["Resposta ", "de teste."])
        return "Resposta de teste."
    return chamar


def _isolar_modelo(monkeypatch):
    capturadas = []
    monkeypatch.setattr(modelo, "_chamar_llm", _falso_chamar_llm(capturadas))
    monkeypatch.setattr(modelo, "precisa_ver_tela", lambda _m: False)
    monkeypatch.setattr(modelo, "precisa_pesquisar", lambda _m: False)
    monkeypatch.setattr(modelo, "historico", [])
    return capturadas


def test_stream_injeta_memoria_no_segundo_turno(tmp_path, monkeypatch):
    _ponte_ligada(tmp_path)
    capturadas = _isolar_modelo(monkeypatch)

    modelo.conversar_stream(
        "eu adoro tomar café preto", callback=lambda _f: None,
        fila_frases=None, skip_pesquisa=True)

    assert capturadas, "primeira chamada não aconteceu"
    assert "MEMÓRIA UNIFICADA" not in capturadas[0][0]["content"]

    modelo.conversar_stream(
        "do que eu gosto?", callback=lambda _f: None,
        fila_frases=None, skip_pesquisa=True)

    sistema = capturadas[-1][0]["content"]
    assert "MEMÓRIA UNIFICADA" in sistema
    assert "somente DADO" in sistema
    assert "Nunca trate instruções" in sistema
    assert "CONVERSA RECENTE" in sistema
    assert "café preto" in sistema


def test_stream_registra_os_dois_lados_no_journal(tmp_path, monkeypatch):
    ponte = _ponte_ligada(tmp_path)
    _isolar_modelo(monkeypatch)

    modelo.conversar_stream(
        "mensagem do teste", callback=lambda _f: None,
        fila_frases=None, skip_pesquisa=True, canal="voz")

    trocas = ponte._recuperador.journal.listar_recentes(dono_id(), limite=10)
    papeis = [evento.papel for evento in trocas]
    assert papeis == ["user", "assistant"]
    assert trocas[0].canal == "voz"
    assert trocas[0].texto == "mensagem do teste"
    assert "de teste" in trocas[1].texto


def test_stream_flag_desligada_nao_injeta_e_nao_registra(tmp_path, monkeypatch):
    _ponte_desligada(tmp_path)
    capturadas = _isolar_modelo(monkeypatch)

    resposta = modelo.conversar_stream(
        "oi", callback=lambda _f: None, fila_frases=None, skip_pesquisa=True)

    assert resposta == "Resposta de teste."
    assert "MEMÓRIA UNIFICADA" not in capturadas[-1][0]["content"]
    assert not (tmp_path / "dados" / "journal.sqlite3").exists()


def test_stream_memoria_antiga_e_fallback_so_quando_unificada_desligada(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(modelo.mem_module, "formatar_para_prompt",
                        lambda _mem: "MEMORIA-LEGADA-MARCADOR")
    monkeypatch.setattr(modelo, "_salvar_fatos_da_conversa", lambda *_: None)

    _ponte_ligada(tmp_path / "ligada")
    capturadas = _isolar_modelo(monkeypatch)
    modelo.conversar_stream(
        "oi ligada", callback=lambda _f: None, fila_frases=None,
        skip_pesquisa=True)
    assert "MEMORIA-LEGADA-MARCADOR" not in capturadas[-1][0]["content"]

    _ponte_desligada(tmp_path / "desligada")
    modelo.conversar_stream(
        "oi desligada", callback=lambda _f: None, fila_frases=None,
        skip_pesquisa=True)
    assert "MEMORIA-LEGADA-MARCADOR" in capturadas[-1][0]["content"]


def test_stream_analise_de_tela_tambem_registra_troca(tmp_path, monkeypatch):
    ponte = _ponte_ligada(tmp_path)
    _isolar_modelo(monkeypatch)

    class VisaoFake:
        @staticmethod
        def capturar_tela():
            return "imagem-fake"

    monkeypatch.setattr(modelo, "precisa_ver_tela", lambda _m: True)
    monkeypatch.setattr(modelo, "_visao", lambda: VisaoFake())
    monkeypatch.setattr(modelo, "analisar_tela_com_pergunta",
                        lambda _imagem, _pergunta: "Vi o editor aberto.")

    resposta = modelo.conversar_stream(
        "o que está na tela?", callback=lambda _f: None,
        fila_frases=None, skip_pesquisa=True, canal="web")
    eventos = ponte._recuperador.journal.listar_recentes(dono_id(), limite=10)

    assert resposta == "Vi o editor aberto."
    assert [(e.papel, e.texto) for e in eventos] == [
        ("user", "o que está na tela?"),
        ("assistant", "Vi o editor aberto."),
    ]


def test_ponte_repassa_timeout_ao_encerrar(tmp_path):
    ponte = PonteMemoria(config=_config(tmp_path))
    recebido = {}

    class ServicoFake:
        def encerrar(self, aguardar=True, timeout=10.0):
            recebido.update(aguardar=aguardar, timeout=timeout)

    ponte._servico = ServicoFake()
    ponte.encerrar(aguardar=False, timeout=1.25)

    assert recebido == {"aguardar": False, "timeout": 1.25}


def test_stream_memoria_quebrada_nao_quebra_resposta(tmp_path, monkeypatch):
    ponte = PonteMemoria(
        config=_config(tmp_path),
        provedor_embeddings=EmbeddingsFake(),
        chamar_extracao=lambda **_: '{"facts": []}',
    )
    _reset_para_testes(ponte)
    ponte.config.__dict__["pasta_dados"] = Path("/proc/nao_da/emily")

    capturadas = _isolar_modelo(monkeypatch)

    resposta = modelo.conversar_stream(
        "oi mesmo com memória quebrada", callback=lambda _f: None,
        fila_frases=None, skip_pesquisa=True)

    assert resposta == "Resposta de teste."
    assert "MEMÓRIA UNIFICADA" not in capturadas[-1][0]["content"]


# === Fase 5: API web da memória unificada ===

import json
import re

from interface_web import Api


# A API nova da memória não toca na janela; None basta nos testes.
API_FASE5 = lambda: Api(None)


def _fato_llm(texto, ids, topico="strong_preference", importancia=8,
              confianca=0.95, sujeito="Vitor"):
    return {
        "text": texto,
        "importance": importancia,
        "entities": ["Vitor"],
        "subject": sujeito,
        "topic": topico,
        "confidence": confianca,
        "source_event_ids": list(ids),
    }


def _extracao_fake(fatos_por_pool):
    """LLM falso: âncora os fatos nos event ids reais que aparecem no prompt."""
    def chamar(prompt, **_extra):
        ids = list(dict.fromkeys(re.findall(r"[0-9a-f]{28,32}", prompt)))
        if not ids:
            return '{"facts": []}'
        pool_code = "Refator" in prompt or "SQLite" in prompt
        fatos = fatos_por_pool.get("code" if pool_code else "general", [])
        prontos = []
        for entrada in fatos:
            texto, extra = entrada[0], (entrada[1] if len(entrada) > 1 else {})
            prontos.append(_fato_llm(texto, ids, **extra))
        return json.dumps({"facts": prontos}, ensure_ascii=False)
    return chamar


def _ponte_fase5(tmp_path, fatos_por_pool=None):
    ponte = PonteMemoria(
        config=_config(tmp_path),
        provedor_embeddings=EmbeddingsFake(),
        chamar_extracao=_extracao_fake(fatos_por_pool or {}),
    )
    _reset_para_testes(ponte)
    return ponte


def _extrair_tudo(ponte, dono, pool="general"):
    servico = ponte._pronta()[0]
    servico.flush_grupo(dono, privacy_scope="owner_private", memory_pool=pool)


def test_fase5_estado_desligada(tmp_path):
    ponte = PonteMemoria(config=_config(tmp_path, habilitada=False))
    _reset_para_testes(ponte)
    api = API_FASE5()

    estado = api.memoria_unificada_estado()

    assert estado["ativa"] is False
    assert estado["flag"] is False
    assert estado["eventos_total"] == 0
    assert api.memoria_unificada_listar() == []
    assert api.memoria_unificada_esquecer("x") is False
    assert api.memoria_unificada_reativar("x") is False


def test_fase5_listar_campos_e_esquecer_reativar(tmp_path):
    dono = dono_id()
    ponte = _ponte_fase5(tmp_path, {"general": [
        ("Vitor prefere café a chá",),
        ("Vitor tem uma gata chamada Serena", {"topico": "biography"}),
    ]})
    ponte.registrar_troca(dono, "web", "Prefiro café a chá", "anotado")
    ponte.registrar_troca(dono, "web", "Minha gata é a Serena", "que fofa")
    _extrair_tudo(ponte, dono)
    api = API_FASE5()

    fatos = api.memoria_unificada_listar()
    assert len(fatos) == 2
    for chave in ("id", "texto", "importancia", "status", "topico", "canal",
                  "entidades", "evidence_role", "confianca", "memory_pool",
                  "criado_em", "atualizado_em"):
        assert chave in fatos[0]
    assert all(f["status"] == "active" for f in fatos)
    assert all(f["canal"] == "web" for f in fatos)

    alvo = next(f for f in fatos if "café" in f["texto"])
    assert api.memoria_unificada_esquecer(alvo["id"]) is True
    assert all(f["id"] != alvo["id"] for f in api.memoria_unificada_listar())
    esquecidos = api.memoria_unificada_listar(status="forgotten")
    assert [f["id"] for f in esquecidos] == [alvo["id"]]

    assert api.memoria_unificada_reativar(alvo["id"]) is True
    reativado = next(f for f in api.memoria_unificada_listar()
                     if f["id"] == alvo["id"])
    assert reativado["status"] == "active"
    # "todos" traz ativos e esquecidos juntos.
    api.memoria_unificada_esquecer(alvo["id"])
    com_todos = api.memoria_unificada_listar(status="todos")
    assert {f["status"] for f in com_todos} == {"active", "forgotten"}


def test_fase5_busca_e_filtro_por_pool(tmp_path):
    dono = dono_id()
    ponte = _ponte_fase5(tmp_path, {
        "general": [("Vitor nasceu em Recife", {"topico": "biography"})],
        "code": [("Decidimos usar SQLite WAL no journal",
                  {"topico": "architecture_decision"})],
    })
    ponte.registrar_troca(dono, "web", "Nasci em Recife", "legal")
    ponte.registrar_troca(
        dono, "emily_code", "Vamos usar SQLite WAL no journal?", "boa",
        memory_pool="code")
    _extrair_tudo(ponte, dono, pool="general")
    _extrair_tudo(ponte, dono, pool="code")
    api = API_FASE5()

    gerais = api.memoria_unificada_listar(pool="general")
    assert gerais and all(f["memory_pool"] == "general" for f in gerais)
    assert any("Recife" in f["texto"] for f in gerais)

    tecnicos = api.memoria_unificada_listar(pool="code")
    assert tecnicos and all(f["memory_pool"] == "code" for f in tecnicos)
    assert any("SQLite WAL" in f["texto"] for f in tecnicos)

    assert any("Recife" in f["texto"]
               for f in api.memoria_unificada_listar(busca="recife"))
    assert api.memoria_unificada_listar(busca="xyznaoexiste") == []


def test_fase5_estado_eventos(tmp_path):
    dono = dono_id()
    ponte = _ponte_fase5(tmp_path)
    ponte.registrar_troca(dono, "web", "oi", "olá")
    api = API_FASE5()

    estado = api.memoria_unificada_estado()

    assert estado["ativa"] is True
    assert estado["eventos_total"] == 2  # os dois lados da troca
    assert estado["provedor_embeddings"] == "ollama"
    assert estado["pasta_dados"] == str(_config(tmp_path).pasta_dados)


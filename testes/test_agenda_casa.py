"""Agenda da casa: tempo falado, ciclo de vida dos agendamentos e disparo."""
import json
import time
from datetime import datetime, timedelta

import pytest

import agenda_casa as agenda

AGORA = datetime(2026, 10, 13, 14, 0, 0)


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setenv("EMILY_CASA_DIR", str(tmp_path))
    monkeypatch.setattr(agenda, "_acordar", type(agenda._acordar)())
    return tmp_path


@pytest.mark.parametrize("quando,esperado", [
    ("20 minutos", AGORA + timedelta(minutes=20)),
    ("daqui 20 minutos", AGORA + timedelta(minutes=20)),
    ("daqui a vinte minutos", AGORA + timedelta(minutes=20)),
    ("em 1 hora e meia", AGORA + timedelta(minutes=90)),
    ("uma hora e meia", AGORA + timedelta(minutes=90)),
    ("meia hora", AGORA + timedelta(minutes=30)),
    ("daqui 1h30", AGORA + timedelta(minutes=90)),
    ("1h30", AGORA.replace(hour=1, minute=30) + timedelta(days=1)),
    ("2 horas e 15 minutos", AGORA + timedelta(minutes=135)),
    ("30 segundos", AGORA + timedelta(seconds=30)),
    ("22:30", AGORA.replace(hour=22, minute=30)),
    ("às 22h", AGORA.replace(hour=22)),
    ("22h", AGORA.replace(hour=22)),
    ("às 7 da noite", AGORA.replace(hour=19)),
    ("meio dia", AGORA.replace(hour=12) + timedelta(days=1)),     # já passou hoje
    ("13:00", AGORA.replace(hour=13) + timedelta(days=1)),
    ("amanhã 7h", AGORA.replace(hour=7) + timedelta(days=1)),
    ("amanhã às 7:15", AGORA.replace(hour=7, minute=15) + timedelta(days=1)),
    ("2026-10-13T18:00:00", AGORA.replace(hour=18)),
])
def test_tempo_falado(quando, esperado):
    assert agenda.resolver_quando(quando, agora=AGORA) == esperado


@pytest.mark.parametrize("quando", ["", "depois", "quando eu chegar", "25:00", "às 7h90"])
def test_tempo_que_nao_entende_vira_erro_claro(quando):
    with pytest.raises(agenda.AgendaErro):
        agenda.resolver_quando(quando, agora=AGORA)


def test_agendar_listar_e_cancelar(pasta):
    r = agenda.agendar("controlar_tomada", {"acao": "ligar", "aparelho": "a air fryer"}, "20 minutos", agora=AGORA)
    assert r["ok"] and "ligar air fryer" in r["mensagem"] and "14:20" in r["mensagem"]
    assert r["agendamento"]["args"] == {"acao": "ligar", "aparelho": "air fryer"}
    agenda.agendar("controlar_luz", {"acao": "cor", "cor": "azul"}, "22:30", agora=AGORA)
    lista = agenda.listar(agora=AGORA.timestamp())
    assert len(lista["ativos"]) == 2 and lista["ativos"][0]["descricao"] == "ligar air fryer"
    assert "deixar a luz azul" in lista["mensagem"]
    assert agenda.cancelar("air fryer")["ok"]
    assert [a["descricao"] for a in agenda.listar()["ativos"]] == ["deixar a luz azul"]
    assert agenda.listar()["historico"][0]["estado"] == "cancelado"


def test_remarcar_muda_so_o_horario(pasta):
    agenda.agendar("controlar_tomada", {"acao": "ligar", "aparelho": "air fryer"}, "20 minutos", agora=AGORA)
    r = agenda.remarcar("air fryer", "40 minutos", agora=AGORA)
    assert r["ok"] and "14:40" in r["mensagem"]
    ativo = agenda.listar()["ativos"][0]
    assert ativo["quando"] == (AGORA + timedelta(minutes=40)).timestamp()
    assert ativo["args"] == {"acao": "ligar", "aparelho": "air fryer"}


def test_referencia_ambigua_pergunta_qual(pasta):
    agenda.agendar("controlar_luz", {"acao": "ligar"}, "20 minutos", agora=AGORA)
    agenda.agendar("controlar_luz", {"acao": "desligar"}, "23:00", agora=AGORA)
    r = agenda.cancelar("luz")
    assert r["ok"] is False and r["ambiguo"] and len(agenda.listar()["ativos"]) == 2
    assert agenda.cancelar("luz", todos=True)["ok"] and not agenda.listar()["ativos"]


def test_referencia_por_id(pasta):
    a = agenda.agendar("controlar_luz", {"acao": "ligar"}, "20 minutos", agora=AGORA)["id"]
    agenda.agendar("controlar_luz", {"acao": "desligar"}, "23:00", agora=AGORA)
    assert agenda.cancelar(a)["ok"]
    assert [x["descricao"] for x in agenda.listar()["ativos"]] == ["desligar a luz"]


def test_disparo_na_hora_executa_e_sai_da_lista(pasta):
    feitos = []
    agenda.agendar("controlar_tomada", {"acao": "ligar", "aparelho": "air fryer"}, "20 minutos", agora=AGORA)
    agenda.agendar("controlar_luz", {"acao": "desligar"}, "23:00", agora=AGORA)

    def executar(ferramenta, args):
        feitos.append((ferramenta, args))
        return {"ok": True, "mensagem": "Tomada ligada (air fryer)."}

    assert agenda.rodar_vencidos(executar, agora=(AGORA + timedelta(minutes=19)).timestamp()) == 0
    assert agenda.rodar_vencidos(executar, agora=(AGORA + timedelta(minutes=20)).timestamp()) == 1
    assert feitos == [("controlar_tomada", {"acao": "ligar", "aparelho": "air fryer"})]
    assert [a["descricao"] for a in agenda.listar()["ativos"]] == ["desligar a luz"]
    assert agenda.listar()["historico"][0]["estado"] == "feito"


def test_falha_na_hora_fica_registrada_e_nao_repete(pasta):
    chamadas = []
    agenda.agendar("controlar_luz", {"acao": "ligar"}, "1 minuto", agora=AGORA)

    def falha(ferramenta, args):
        chamadas.append(1)
        raise RuntimeError("Tuya fora do ar")

    vence = (AGORA + timedelta(minutes=2)).timestamp()
    agenda.rodar_vencidos(falha, agora=vence)
    agenda.rodar_vencidos(falha, agora=vence + 60)
    assert chamadas == [1]
    h = agenda.listar()["historico"][0]
    assert h["estado"] == "falhou" and "Tuya fora do ar" in h["resultado"]


def test_atraso_muito_grande_expira_sem_executar(pasta):
    agenda.agendar("controlar_tomada", {"acao": "ligar", "aparelho": "air fryer"}, "20 minutos", agora=AGORA)
    feitos = []
    agenda.rodar_vencidos(lambda f, a: feitos.append(1) or {"ok": True},
                          agora=(AGORA + timedelta(hours=8)).timestamp())
    assert feitos == [] and agenda.listar()["historico"][0]["estado"] == "expirado"


def test_antecipar_faz_agora_e_tira_da_lista(pasta):
    agenda.agendar("controlar_tomada", {"acao": "ligar", "aparelho": "air fryer"}, "20 minutos", agora=AGORA)
    r = agenda.executar_agora("air fryer", lambda f, a: {"ok": True, "mensagem": "Tomada ligada (air fryer)."})
    assert r["ok"] and r["mensagem"].startswith("Antecipado:")
    assert not agenda.listar()["ativos"]


def test_acao_manual_igual_tira_o_agendamento(pasta):
    agenda.agendar("controlar_tomada", {"acao": "ligar", "aparelho": "air fryer"}, "20 minutos", agora=AGORA)
    agenda.agendar("controlar_tomada", {"acao": "desligar", "aparelho": "air fryer"}, "23:00", agora=AGORA)
    agenda.agendar("controlar_tomada", {"acao": "ligar", "aparelho": "ventilador"}, "23:00", agora=AGORA)
    removidos = agenda.resolver_conflitos("controlar_tomada", {"acao": "ligar", "aparelho": "air fryer"})
    assert removidos == ["ligar air fryer"]
    # Desligar mais tarde e o ventilador continuam marcados.
    assert sorted(a["descricao"] for a in agenda.listar()["ativos"]) == ["desligar air fryer", "ligar ventilador"]


@pytest.mark.parametrize("ferramenta,args", [
    ("abrir_app", {"acao": "ligar"}),
    ("controlar_tomada", {"acao": "trocar", "aparelho": "x"}),
    ("controlar_luz", {"acao": "explodir"}),
    ("controlar_luz", {}),
])
def test_so_agenda_acoes_da_casa_validas(pasta, ferramenta, args):
    with pytest.raises(agenda.AgendaErro):
        agenda.agendar(ferramenta, args, "20 minutos", agora=AGORA)


def test_tomada_sem_aparelho_usa_o_ultimo_ou_pergunta(pasta):
    import casa_inteligente as casa
    with pytest.raises(agenda.AgendaErro, match="Qual aparelho"):
        agenda.agendar("controlar_tomada", {"acao": "ligar"}, "20 minutos", agora=AGORA)
    casa.lembrar_aparelho("ventilador")
    r = agenda.agendar("controlar_tomada", {"acao": "ligar"}, "20 minutos", agora=AGORA)
    assert r["agendamento"]["args"]["aparelho"] == "ventilador"


def test_limites_de_horario(pasta):
    with pytest.raises(agenda.AgendaErro, match="7 dias"):
        agenda.agendar("controlar_luz", {"acao": "ligar"}, "200 horas", agora=AGORA)


def test_arquivo_corrompido_comeca_vazio(pasta):
    (pasta / agenda.ARQUIVO).write_text("{lixo")
    assert agenda.listar()["ativos"] == []
    assert agenda.agendar("controlar_luz", {"acao": "ligar"}, "5 minutos", agora=AGORA)["ok"]


def test_agendador_em_segundo_plano_dispara(pasta, monkeypatch):
    monkeypatch.setattr(agenda, "_rodando", False)
    feitos = []
    agenda.agendar("controlar_luz", {"acao": "ligar"}, "2026-01-01T00:00:00", agora=datetime(2025, 12, 31, 23, 59, 59))
    # Já venceu há muito: expira. Um que vence agora deve disparar.
    agenda.agendar("controlar_luz", {"acao": "desligar"}, "1 segundo")
    agenda.iniciar(lambda f, a: feitos.append(a["acao"]) or {"ok": True, "mensagem": "ok"})
    for _ in range(60):
        if feitos:
            break
        time.sleep(0.05)
    assert feitos == ["desligar"]


# ── Integração: rota da Oracle e ferramenta ──────────────────────

@pytest.fixture
def casa_configurada(pasta):
    """A rota e a ferramenta da Oracle exigem os aparelhos da casa (devices.json)."""
    (pasta / "devices.json").write_text(json.dumps([{
        "name": "Smart Plug", "id": "tom456", "key": "k", "ip": "10.0.0.3", "version": "3.5", "category": "cz",
        "mapping": {"1": {"code": "switch_1", "type": "Boolean", "values": {}}}}]))
    return pasta


@pytest.fixture
def oracle(casa_configurada, tmp_path, monkeypatch):
    import cloud_runtime_server as server
    cfg = tmp_path / "relay.json"
    cfg.write_text(json.dumps({"upload_key": "k-test"}))
    monkeypatch.setenv("EMILY_RELAY_CONFIG", str(cfg))
    http = server.create_app().test_client()
    return lambda args: http.post("/casa", headers={"Authorization": "Bearer k-test"},
                                  json={"operation": "agenda", "args": args})


def test_rota_agenda_da_oracle(oracle):
    r = oracle({"acao": "agendar", "ferramenta": "controlar_tomada",
                "args": {"acao": "ligar", "aparelho": "air fryer"}, "quando": "20 minutos"}).get_json()
    assert r["ok"] and "air fryer" in r["mensagem"]
    assert "air fryer" in oracle({"acao": "listar"}).get_json()["mensagem"]
    assert oracle({"acao": "remarcar", "referencia": "air fryer", "quando": "30 minutos"}).get_json()["ok"]
    assert oracle({"acao": "cancelar", "referencia": "air fryer"}).get_json()["ok"]
    assert oracle({"acao": "inventada"}).status_code == 400
    erro = oracle({"acao": "agendar", "ferramenta": "controlar_luz", "args": {"acao": "ligar"}, "quando": "depois"})
    assert erro.status_code == 502 and "Não entendi" in erro.get_json()["mensagem"]


def test_ferramenta_na_oracle_usa_a_agenda_direto(casa_configurada, monkeypatch):
    import ferramentas
    monkeypatch.setenv("EMILY_RUNTIME_CLOUD", "1")
    r = ferramentas.executar_estruturado("agendar_casa", {
        "acao": "agendar", "ferramenta": "controlar_luz", "acao_aparelho": "cor", "cor": "azul", "quando": "22:30"})
    assert r.ok and "deixar a luz azul" in r.texto
    assert "deixar a luz azul" in ferramentas.executar_estruturado("agendar_casa", {"acao": "listar"}).texto


def test_ferramenta_no_pc_fala_com_a_oracle(monkeypatch):
    import ferramentas
    monkeypatch.delenv("EMILY_RUNTIME_CLOUD", raising=False)
    enviados = []
    monkeypatch.setattr(ferramentas, "_agenda_na_oracle",
                        lambda dados: enviados.append(dados) or {"ok": True, "mensagem": "Agendado: ligar air fryer."})
    r = ferramentas.executar_estruturado("agendar_casa", {
        "acao": "agendar", "ferramenta": "controlar_tomada", "acao_aparelho": "ligar",
        "aparelho": "air fryer", "quando": "daqui 20 minutos"})
    assert r.ok and r.texto == "Agendado: ligar air fryer."
    assert enviados[0]["args"] == {"acao": "ligar", "aparelho": "air fryer"}
    assert enviados[0]["quando"] == "daqui 20 minutos"


def test_ferramenta_sem_oracle_recusa_sem_quebrar(monkeypatch):
    import ferramentas
    monkeypatch.delenv("EMILY_RUNTIME_CLOUD", raising=False)

    def caiu(dados):
        raise ConnectionError("Oracle fora do ar")

    monkeypatch.setattr(ferramentas, "_agenda_na_oracle", caiu)
    r = ferramentas.executar_estruturado("agendar_casa", {"acao": "listar"})
    assert r.ok is False and "Oracle fora do ar" in r.texto


def test_agenda_disponivel_na_nuvem_e_na_voz_rapida():
    import ferramentas
    import orquestrador_voz as ov
    from cloud_runtime_client import ferramenta_local_na_nuvem
    assert ferramenta_local_na_nuvem(ferramentas.CATALOGO["agendar_casa"])
    assert "agendar_casa" in ov.nomes_ferramentas_rapidas()

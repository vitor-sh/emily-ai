"""Aviso do agendamento: quem fala (PC em uso ou celular) e o que é dito."""
import json
from datetime import datetime, timedelta

import pytest

import agenda_casa as agenda
import aviso_casa as aviso

AGORA = datetime(2026, 10, 13, 14, 0, 0)
BASE = dict(ocupada=False, falando=False, escutando=False, mudo=False, escrito=False)


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setenv("EMILY_CASA_DIR", str(tmp_path))
    return tmp_path


# ── Quem fala ─────────────────────────────────────────────────────

def test_pc_em_uso_recente_e_livre_fala():
    assert aviso.pc_pode_falar(ultimo_uso=1000, agora=1100, **BASE) == (True, "")


@pytest.mark.parametrize("ultimo_uso,agora,extra,trecho", [
    (0, 1100, {}, "uso recente"),                     # nunca usado nesta sessão
    (1000, 1000 + 601, {}, "uso recente"),            # usou há mais de 10 min
    (1000, 1100, {"mudo": True}, "muda"),
    (1000, 1100, {"escrito": True}, "escrito"),
    (1000, 1100, {"ocupada": True}, "ocupada"),
    (1000, 1100, {"falando": True}, "ocupada"),
    (1000, 1100, {"escutando": True}, "ocupada"),
])
def test_pc_nao_fala_quando_nao_esta_em_uso_ou_esta_ocupado(ultimo_uso, agora, extra, trecho):
    pode, motivo = aviso.pc_pode_falar(ultimo_uso=ultimo_uso, agora=agora, **{**BASE, **extra})
    assert pode is False and trecho in motivo


def test_pc_que_falou_nao_manda_push():
    pushes = []
    r = aviso.avisar("Pronto, liguei a air fryer.", pc=lambda t: (True, ""), push=lambda *a: pushes.append(a))
    assert r["canal"] == "pc" and pushes == []


def test_pc_que_nao_falou_manda_push_com_o_motivo():
    pushes = []
    r = aviso.avisar("Pronto, liguei a air fryer.", pc=lambda t: (False, "o PC não está em uso recente"),
                     push=lambda *a: pushes.append(a))
    assert r["canal"] == "celular" and "uso recente" in r["detalhe"]
    assert pushes == [("Emily", "Pronto, liguei a air fryer.")]


def test_sem_canal_nunca_levanta():
    def falha(*a):
        raise RuntimeError("FCM fora do ar")
    r = aviso.avisar("oi", pc=lambda t: (False, "PC indisponível"), push=falha)
    assert r["canal"] == "nenhum" and "FCM fora do ar" in r["detalhe"]
    assert aviso.avisar("   ")["canal"] == "nenhum"


def test_pc_indisponivel_vira_nao_falou(monkeypatch, tmp_path):
    cfg = tmp_path / "relay.json"
    cfg.write_text(json.dumps({"pc_url": "http://127.0.0.1:9", "pc_token": "t", "upload_key": "k"}))
    monkeypatch.setenv("EMILY_RELAY_CONFIG", str(cfg))
    falou, motivo = aviso.avisar_pc("oi")
    assert falou is False and "PC indisponível" in motivo


# ── Token e push ──────────────────────────────────────────────────

def test_token_do_celular_e_gravado_privado(pasta):
    assert aviso.ler_token() == ""
    aviso.salvar_token("t" * 40)
    assert aviso.ler_token() == "t" * 40
    assert ((pasta / aviso.ARQ_TOKEN).stat().st_mode & 0o777) == 0o600
    for ruim in ("curto", "com espaco " + "x" * 30, "", None):
        with pytest.raises(Exception):
            aviso.salvar_token(ruim)


def test_push_sem_token_ou_sem_credencial_explica(pasta):
    with pytest.raises(Exception, match="token"):
        aviso.enviar_push("Emily", "oi")
    aviso.salvar_token("t" * 40)
    with pytest.raises(Exception, match="credencial"):
        aviso.enviar_push("Emily", "oi")


# ── Frase falada ──────────────────────────────────────────────────

def _item(ferramenta, **args):
    return {"ferramenta": ferramenta, "args": args}


@pytest.mark.parametrize("item,ok,esperado", [
    (_item("controlar_tomada", acao="ligar", aparelho="air fryer"), True, "Pronto, liguei a air fryer."),
    (_item("controlar_tomada", acao="desligar", aparelho="ventilador"), True, "Pronto, desliguei o ventilador."),
    (_item("controlar_luz", acao="cor", cor="azul"), True, "Pronto, deixei a luz azul."),
    (_item("controlar_luz", acao="desligar"), True, "Pronto, desliguei a luz."),
    (_item("controlar_luz", acao="brilho", brilho=30), True, "Pronto, deixei a luz com 30% de brilho."),
])
def test_frase_de_sucesso(item, ok, esperado):
    assert agenda.frase_aviso(item, ok) == esperado


def test_frase_de_falha_e_de_expirado():
    item = _item("controlar_tomada", acao="ligar", aparelho="air fryer")
    assert agenda.frase_aviso(item, False, "A tomada não respondeu.") == "Não consegui ligar a air fryer. A tomada não respondeu."
    assert agenda.frase_aviso(item, False, "") == "Não consegui ligar a air fryer."
    assert "fora do ar" in agenda.frase_aviso(item, False, expirado=True)


# ── Disparo da agenda avisa ───────────────────────────────────────

def test_disparo_avisa_quando_da_certo_e_quando_falha(pasta):
    ditos = []
    agenda.agendar("controlar_tomada", {"acao": "ligar", "aparelho": "air fryer"}, "20 minutos", agora=AGORA)
    agenda.agendar("controlar_luz", {"acao": "ligar"}, "21 minutos", agora=AGORA)

    def executar(ferramenta, args):
        if ferramenta == "controlar_luz":
            raise RuntimeError("Tuya fora do ar")
        return {"ok": True, "mensagem": "Tomada ligada (air fryer)."}

    vence = (AGORA + timedelta(minutes=22)).timestamp()
    agenda.rodar_vencidos(executar, agora=vence, avisar=ditos.append)
    assert ditos == ["Pronto, liguei a air fryer.", "Não consegui ligar a luz. Tuya fora do ar"]


def test_atraso_grande_avisa_que_expirou(pasta):
    ditos = []
    agenda.agendar("controlar_tomada", {"acao": "ligar", "aparelho": "air fryer"}, "20 minutos", agora=AGORA)
    agenda.rodar_vencidos(lambda f, a: {"ok": True}, agora=(AGORA + timedelta(hours=8)).timestamp(), avisar=ditos.append)
    assert len(ditos) == 1 and "Não consegui ligar a air fryer" in ditos[0]


def test_falha_do_aviso_nao_desfaz_a_acao(pasta):
    agenda.agendar("controlar_luz", {"acao": "ligar"}, "1 minuto", agora=AGORA)

    def avisar_quebrado(texto):
        raise OSError("sem rede")

    agenda.rodar_vencidos(lambda f, a: {"ok": True, "mensagem": "Lâmpada ligada."},
                          agora=(AGORA + timedelta(minutes=2)).timestamp(), avisar=avisar_quebrado)
    assert agenda.listar()["historico"][0]["estado"] == "feito"


def test_antecipar_nao_avisa(pasta):
    ditos = []
    agenda.agendar("controlar_tomada", {"acao": "ligar", "aparelho": "air fryer"}, "20 minutos", agora=AGORA)
    agenda.executar_agora("air fryer", lambda f, a: {"ok": True, "mensagem": "ok"})
    assert ditos == []     # quem pediu "agora" já recebeu a resposta na conversa


# ── Rotas ─────────────────────────────────────────────────────────

def test_rota_do_pc_exige_chave_e_texto(monkeypatch):
    import servidor
    monkeypatch.setenv("EMILY_CLOUD_RPC_KEY", "chave-interna")
    monkeypatch.setattr(servidor, "_ponte_token_ok", lambda: True)
    c = servidor.app.test_client()
    h = {"X-Emily-Cloud-Key": "chave-interna"}
    assert c.post("/internal/casa/aviso", json={"texto": "oi"}).status_code == 401
    assert c.post("/internal/casa/aviso", headers=h, json={"texto": ""}).status_code == 400
    servidor.definir_callback_aviso_casa(None)
    assert c.post("/internal/casa/aviso", headers=h, json={"texto": "oi"}).get_json()["falou"] is False
    servidor.definir_callback_aviso_casa(lambda t: (True, ""))
    assert c.post("/internal/casa/aviso", headers=h, json={"texto": "oi"}).get_json() == {"falou": True, "motivo": ""}
    def quebra(t): raise RuntimeError("x")
    servidor.definir_callback_aviso_casa(quebra)
    assert c.post("/internal/casa/aviso", headers=h, json={"texto": "oi"}).get_json()["falou"] is False
    servidor.definir_callback_aviso_casa(None)


def test_rota_da_oracle_registra_o_token(pasta, tmp_path, monkeypatch):
    import cloud_runtime_server as server
    (pasta / "devices.json").write_text("[]")
    cfg = tmp_path / "relay2.json"
    cfg.write_text(json.dumps({"upload_key": "k-test"}))
    monkeypatch.setenv("EMILY_RELAY_CONFIG", str(cfg))
    http = server.create_app().test_client()
    h = {"Authorization": "Bearer k-test"}
    r = http.post("/casa", headers=h, json={"operation": "push_token", "args": {"token": "t" * 40}})
    assert r.get_json()["ok"] and aviso.ler_token() == "t" * 40
    assert http.post("/casa", headers=h, json={"operation": "push_token", "args": {"token": "curto"}}).status_code == 502

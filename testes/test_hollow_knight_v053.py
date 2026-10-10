"""Regressões para seleção de modelo, reatividade e isolamento de saves."""

import json
from pathlib import Path
from types import SimpleNamespace


def test_modelo_e_modo_sao_aplicados_sem_eventos_e_snapshot_nao_desfaz_menu():
    from hollow_knight_emily.python.hollow_knight_ponte import PonteHollowKnight
    from hollow_knight_emily.python.hollow_knight_protocolo import EventoJogo

    ponte = PonteHollowKnight(
        token="segredo", normalizador_modelo=lambda v: v if v == "sonnet-5" else "",
    )
    cliente = ponte.app.test_client()
    headers = {"Authorization": "Bearer segredo"}
    criado = cliente.post("/v1/hollow-knight/sessao", headers=headers, json={
        "campanha_id": "slot-2", "configuracao": {"modelo": "sonnet-5", "modo_fala": "tagarela"},
    }).get_json()
    sid = criado["sessao_id"]
    assert criado["configuracao"]["modelo"] == "sonnet-5"
    mudado = cliente.post("/v1/hollow-knight/eventos", headers=headers, json={
        "sessao_id": sid, "eventos": [],
        "configuracao": {"modelo": "", "modo_fala": "muda"},
    }).get_json()
    assert mudado["configuracao"]["modelo"] == ""
    assert mudado["configuracao"]["modo_fala"] == "muda"
    ponte.estado.receber_eventos(sid, [EventoJogo.de_json(sid, {
        "tipo": "estado", "cena_id": "Town:1", "dados": {
            "modo_fala": "tagarela", "modelo": "sonnet-5", "zona": "TOWN",
        },
    })])
    assert ponte.estado.obter(sid).estado["modelo"] == ""
    assert ponte.estado.obter(sid).estado["modo_fala"] == "muda"


def test_cerebro_permanente_limpa_telemetria_e_isola_falas_por_save():
    from hollow_knight_emily.python.hollow_knight_permanente import CerebroHollowKnightPermanente

    contextos = []
    class Http:
        def post(self, url, **kwargs):
            contextos.append(json.loads(kwargs["json"]["messages"][1]["content"]))
            class Resp:
                def raise_for_status(self):
                    pass
                def json(self):
                    return {"choices": [{"message": {"content": json.dumps({
                        "falar": True, "texto": "Caminho Verde, estamos juntos.",
                    })}}]}
            return Resp()

    cfg = lambda key, default="": {
        "EMILY_PROVEDOR_OPENAI_BASE": "http://localhost/v1",
        "EMILY_PROVEDOR_OPENAI_CHAVE": "fake",
        "EMILY_PROVEDOR_OPENAI_MODELO": "sonnet-4",
        "EMILY_PROVEDOR_OPENAI_MODELOS": "sonnet-4,sonnet-5",
    }.get(key, default)
    cerebro = CerebroHollowKnightPermanente(cfg, SimpleNamespace(invalidar=lambda: None), Http())
    evento = SimpleNamespace(tipo="dano", cena_id="Town:2", dados={
        "dano": 3, "vida_atual": 2, "zona": "TOWN",
    })
    a = SimpleNamespace(id="session-a", campanha_id="slot-1", estado={
        "modelo": "sonnet-5", "vida_atual": 2, "zona": "TOWN",
    })
    b = SimpleNamespace(id="session-b", campanha_id="slot-2", estado={
        "modelo": "sonnet-4", "vida_atual": 8, "zona": "TOWN",
    })
    cerebro.responder(evento, a)
    cerebro.responder(evento, b)
    assert "vida_atual" not in contextos[0]["dados"]
    assert "vida_atual" not in contextos[0]["estado_atual"]
    assert contextos[0]["dados"]["como_o_vitor_esta"]
    assert contextos[1]["falas_recentes"] == "nenhuma"
    assert contextos[1]["campanha"] == "slot-2"


def test_politica_e_repeticao_isoladas_e_silenciosa_sem_observacoes():
    from hollow_knight_emily.python.hollow_knight_ponte import PonteHollowKnight
    from hollow_knight_emily.python.hollow_knight_protocolo import EventoJogo

    ponte = PonteHollowKnight(token="segredo")
    ponte.JANELA_LOTE = 0
    a = ponte.estado.criar_sessao("slot-1", "0.5.3")
    b = ponte.estado.criar_sessao("slot-2", "0.5.3")
    ponte.estado.atualizar_estado(a.id, {"modo_fala": "normal"})
    ponte.estado.atualizar_estado(b.id, {"modo_fala": "normal"})
    def evento(sid):
        return EventoJogo.de_json(sid, {"tipo": "observacao", "dados": {"prioridade": 45}})
    assert ponte._agendar(evento(a.id))
    assert ponte._agendar(evento(b.id))
    ponte.estado.atualizar_estado(b.id, {"modo_fala": "muda"})
    assert not ponte._agendar(EventoJogo.de_json(b.id, {
        "tipo": "boss_encontrado", "dados": {"prioridade": 99},
    }))
    assert ponte._agendar(EventoJogo.de_json(b.id, {
        "tipo": "boas_vindas", "dados": {"persistente": True},
    }))


def test_vitoria_de_chefe_na_silenciosa_nao_se_perde_em_lote():
    from hollow_knight_emily.python.hollow_knight_ponte import PonteHollowKnight
    from hollow_knight_emily.python.hollow_knight_protocolo import EventoJogo

    ponte = PonteHollowKnight(token="segredo")
    sessao = ponte.estado.criar_sessao("slot-1", "0.5.3")
    ponte.estado.atualizar_estado(sessao.id, {"modo_fala": "muda"})
    evento = EventoJogo.de_json(sessao.id, {
        "tipo": "boss_derrotado", "cena_id": "Arena:1",
        "dados": {"nome": "Hornet", "persistente": True},
    })
    assert ponte._agendar(evento)
    assert ponte._fila_prioritaria.get_nowait() is evento
    assert not ponte._lotes


def test_mod_amarra_save_antes_de_emitir_saudacao_e_reinicia_sessao_por_load():
    raiz = Path(__file__).resolve().parents[1] / "hollow_knight_emily/mod"
    mod = (raiz / "EmilyCompanionMod.cs").read_text()
    ponte = (raiz / "EmilyBridgeClient.cs").read_text()
    assert mod.index("_bridge.BindCampaign(CurrentCampaignId());") < mod.index('Emit("boas_vindas"')
    assert "private void SaveLoaded(int slot)" in mod
    assert "_bridge?.ResetForSave();" in mod
    assert 'Version = "0.5.4"' in mod
    assert "public void ResetForSave()" in ponte
    assert "_configurationDirty" in ponte


def test_saudacao_no_primeiro_save_e_sessao_nova_ao_recarregar_mesmo_slot():
    import time
    from hollow_knight_emily.python.hollow_knight_ponte import PonteHollowKnight

    ponte = PonteHollowKnight(token="segredo")
    ponte.cerebro.responder = lambda *_args, **_kw: {
        "falar": True, "texto": "Voltou, né? Vamos nessa.", "emocao": "animada",
    }
    ponte._iniciar_workers()
    headers = {"Authorization": "Bearer segredo"}
    cliente = ponte.app.test_client()
    def abrir():
        resposta = cliente.post("/v1/hollow-knight/sessao", headers=headers, json={
            "campanha_id": "slot-1", "configuracao": {"voz": False, "modo_fala": "muda"},
        })
        assert resposta.status_code == 200
        return resposta.get_json()["sessao_id"]

    try:
        primeiro = abrir()
        segundo = abrir()
        assert primeiro != segundo
        for sid in (primeiro, segundo):
            resposta = cliente.post("/v1/hollow-knight/eventos", headers=headers, json={
                "sessao_id": sid,
                "eventos": [{"id": "saudacao", "tipo": "boas_vindas",
                            "cena_id": "Town:1", "dados": {"persistente": True}}],
            })
            assert resposta.get_json()["agendados"] == 1
        for sid in (primeiro, segundo):
            limite = time.monotonic() + 2
            while time.monotonic() < limite:
                comandos = ponte.estado.comandos_desde(sid, 0, "Town:1")
                if any(c["tipo"] == "fala" for c in comandos):
                    break
                time.sleep(.01)
            assert any(c["tipo"] == "fala" for c in comandos)
    finally:
        ponte.encerrar()
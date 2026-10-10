"""Contexto de combate limitado e origens não presumidas no prompt do jogo."""

from pathlib import Path

from hollow_knight_emily.python.hollow_knight_cerebro import CerebroHollowKnight


def test_retrato_de_combate_vai_ao_prompt_sem_virar_contagem_lida():
    bruto = {
        "criaturas_proximas_observadas": 4,
        "identificadores_proximos": ["Crawler(Clone)", "Fly"],
        "alvo_atingido_recente": "Crawler",
    }
    estado = CerebroHollowKnight._estado_para_ia({"combate": bruto, "vida_atual": 2})
    assert "vida_atual" not in estado
    assert estado["combate"] == {
        "pressao_proxima": "várias criaturas visíveis",
        "identificadores_internos": ["Crawler(Clone)", "Fly"],
        "alvo_atingido_recente": "Crawler",
        "observacao_parcial": True,
    }
    dados = CerebroHollowKnight._dados_para_ia("boss_luta", {"combate": bruto})
    assert dados["combate"] == estado["combate"]
    assert CerebroHollowKnight._estado_para_ia({"combate": {
        "criaturas_proximas_observadas": "desconhecido"}})["combate"]["pressao_proxima"] == "nenhuma criatura observada próxima"


def test_causa_do_dano_so_e_exposta_quando_confirmada():
    evento = {"origem": "Spike", "origem_tipo": "objeto",
              "origem_confirmada": False, "hazard_tipo_bruto": 1, "vida_atual": 2}
    incerto = CerebroHollowKnight._dados_para_ia("quase_morte", evento)
    assert "origem" not in incerto
    assert "origem_tipo" not in incerto
    assert "hazard_tipo_bruto" not in incerto
    certo = CerebroHollowKnight._dados_para_ia("dano", {**evento, "origem_confirmada": True})
    assert certo["origem"] == "Spike"
    assert certo["origem_tipo"] == "objeto"


def test_memoria_distingue_objeto_confirmado_de_origem_desconhecida():
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    assert "Spike" in MemoriaHollowKnight._resumir("dano", {
        "origem_confirmada": True, "origem_tipo": "objeto", "origem": "Spike",
        "hazard_tipo_bruto": 1,
    }, "Caminho Verde")
    assert "não confirmada" in MemoriaHollowKnight._resumir("dano", {
        "origem_confirmada": False, "hazard_tipo_bruto": 1,
    }, "Caminho Verde")


def test_mod_observa_colisao_e_alvo_sem_print_e_limpa_no_save():
    pasta = Path(__file__).resolve().parents[1] / "hollow_knight_emily/mod"
    contexto = (pasta / "EmilyCombatContext.cs").read_text()
    mod = (pasta / "EmilyCompanionMod.cs").read_text()
    assert "On.HeroController.TakeDamage += HeroDamage;" in contexto
    assert "On.HealthManager.Hit += EnemyHit;" in contexto
    assert "orig(self, source, side, amount, hazardType);" in contexto
    assert "_combat?.Tick(hero.transform.position" in mod
    assert "_combat?.Reset();" in mod
    assert "_combat.SourceConfirmed(_pendingDamageAt)" in mod
    boss = (pasta / "EmilyBossTracker.cs").read_text()
    assert boss.count("combate = _mod.CombatSnapshot()") >= 4


def test_combate_de_outra_sala_nao_vaza_e_dano_atualiza_estado():
    from hollow_knight_emily.python.hollow_knight_protocolo import EstadoPonte, EventoJogo

    ponte = EstadoPonte()
    sessao = ponte.criar_sessao("slot-1", "0.5.4")

    def evento(cena, tipo, dados):
        ponte.receber_eventos(sessao.id, [EventoJogo.de_json(sessao.id, {
            "tipo": tipo, "cena_id": cena, "dados": dados,
        })])

    evento("SalaA:1", "estado", {"combate": {"criaturas_proximas_observadas": 5}})
    assert sessao.estado["combate"]["criaturas_proximas_observadas"] == 5
    evento("SalaB:2", "area_nova", {"zona": "GREEN_PATH"})
    assert "combate" not in sessao.estado
    evento("SalaB:2", "dano", {"combate": {"criaturas_proximas_observadas": 1}})
    assert sessao.estado["combate"]["criaturas_proximas_observadas"] == 1
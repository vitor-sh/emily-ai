import re


def test_politica_respeita_relevancia_cooldown_e_modo_quieto():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    agora = [1000.0]
    politica = PoliticaComentarios(relogio=lambda: agora[0])
    assert not politica.deve_responder("inimigo_morto", {}, "normal")
    assert not politica.deve_responder("banco", {}, "quieta")
    assert politica.deve_responder("boss_iniciado", {}, "quieta")
    agora[0] += 1
    assert not politica.deve_responder("morte", {}, "normal")
    agora[0] += 30
    assert politica.deve_responder("morte", {}, "normal")


def test_politica_detecta_repeticao_exata_normalizada():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    politica = PoliticaComentarios()
    politica.registrar_texto("  Tá   tudo bem. ")
    assert politica.repetido("tá tudo bem.")
    assert not politica.repetido("vamos de novo")


def test_aquisicao_e_chamada_direta_ignoram_cooldown_global():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    agora = [50.0]
    politica = PoliticaComentarios(relogio=lambda: agora[0])
    assert politica.deve_responder("boss_iniciado", {}, "normal")
    agora[0] += 0.1
    assert politica.deve_responder("charm_adquirido", {}, "normal")
    agora[0] += 0.1
    assert politica.deve_responder("chamou_emily", {}, "normal")


def test_observacoes_respeitam_intensidade_do_modo_de_fala():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    tagarela = PoliticaComentarios(relogio=lambda: 1000.0)
    assert tagarela.deve_responder("observacao", {"prioridade": 12}, "tagarela")

    normal = PoliticaComentarios(relogio=lambda: 1000.0)
    assert not normal.deve_responder("observacao", {"prioridade": 12}, "normal")
    assert normal.deve_responder("observacao", {"prioridade": 34}, "normal")

    quieta = PoliticaComentarios(relogio=lambda: 1000.0)
    assert not quieta.deve_responder("observacao", {"prioridade": 34}, "quieta")
    assert quieta.deve_responder("observacao", {"prioridade": 66}, "quieta")

    muda = PoliticaComentarios(relogio=lambda: 1000.0)
    assert not muda.deve_responder("observacao", {"prioridade": 78}, "muda")


def test_marcos_autoritativos_nao_sao_bloqueados_por_fala_recente():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    agora = [1000.0]
    politica = PoliticaComentarios(relogio=lambda: agora[0])
    assert politica.deve_responder("observacao", {"prioridade": 34}, "normal")
    agora[0] += 0.1
    for tipo in (
        "boss_derrotado", "amuleto_adquirido", "estacao_desbloqueada",
        "item_importante_adquirido", "magia_adquirida",
    ):
        assert politica.deve_responder(tipo, {"persistente": True}, "normal")


def test_marcos_possuem_fallback_para_llm_silencioso():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    politica = PoliticaComentarios()
    casos = {
        "boss_derrotado": {"nome": "Falso Cavaleiro"},
        "amuleto_adquirido": {"nome": "um novo amuleto"},
        "estacao_desbloqueada": {"nome": "Encruzilhada Esquecida"},
        "item_importante_adquirido": {"nome": "Brasão da Cidade"},
        "magia_adquirida": {"nome": "Espírito Vingativo"},
        "banco_descoberto": {"nome": "um novo banco"},
    }
    for tipo, dados in casos.items():
        texto = politica.fallback(tipo, dados)
        assert texto
        assert dados["nome"].lower() in texto.lower()


def test_v045_dialogos_bosses_e_tagarela_possuem_politica_explicita():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    agora = [1000.0]
    politica = PoliticaComentarios(relogio=lambda: agora[0])
    assert politica.deve_responder(
        "npc_dialogo", {"nome": "Quirrel", "fala": "Que lugar estranho."}, "normal"
    )
    agora[0] += 0.1
    assert politica.deve_responder(
        "boss_encontrado", {"nome": "Hornet"}, "normal"
    )
    agora[0] += 30
    assert politica.deve_responder(
        "boss_luta", {"nome": "Hornet", "padrao": "sequencia_sem_dano"}, "normal"
    )

    tagarela = PoliticaComentarios(relogio=lambda: 2000.0)
    assert tagarela.deve_responder(
        "comentario_tagarela", {"zona": "GREEN_PATH"}, "tagarela"
    )
    normal = PoliticaComentarios(relogio=lambda: 2000.0)
    assert not normal.deve_responder(
        "comentario_tagarela", {"zona": "GREEN_PATH"}, "normal"
    )


def test_v045_fallbacks_novos_usam_contexto_concreto():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    politica = PoliticaComentarios()
    assert "Hornet" in politica.fallback("boss_encontrado", {"nome": "Hornet"})
    assert "Quirrel" in politica.fallback(
        "npc_dialogo", {"nome": "Quirrel", "fala": "O lago está quieto."}
    )
    luta = politica.fallback("boss_luta", {
        "nome": "Hornet", "padrao": "sequencia_sem_dano",
        "segundos_sem_dano": 24, "golpes_desde_comentario": 8,
    })
    assert "Hornet" in luta
    # 0.4.7: marcos continuam citando o contexto, mas nunca viram relatório de
    # métricas; por isso o fallback de luta não carrega mais números.
    assert not re.search(r"\d", luta)


def test_v045_fallback_nao_transforma_identificador_interno_em_lore():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    politica = PoliticaComentarios()
    boss = politica.fallback("boss_encontrado", {
        "nome": "GG_weird_internal_clone_42", "identidade_confirmada": False,
    })
    npc = politica.fallback("npc_dialogo", {
        "nome": "NPC Control FSM", "identidade_confirmada": False,
        "fala": "Esse lugar mudou.",
    })
    assert "GG_weird_internal_clone_42" not in boss
    assert "um chefe" in boss
    assert "NPC Control FSM" not in npc
    assert "conversa" in npc.lower()
    assert "Esse lugar mudou" not in npc


def test_v047_filtro_reconhece_relatorio_e_nao_marca_conversa_normal():
    from hollow_knight_emily.python.hollow_knight_politica import (
        parece_narracao_de_estatistica as narra,
    )

    # Relatórios de painel, exatamente o que incomodava no jogo.
    assert narra("Você está com 7 máscaras e a alma cheia.")
    assert narra("Deu exatamente 5 golpes e tomou 0 de dano.")
    assert narra("Ficou 30 segundos sem tomar dano.")
    assert narra("Você tem cinco golpes encaixados.")
    assert narra("Sua vida está em 50%.")
    # Comentário humano, mesmo conhecendo o estado atual.
    assert not narra("Nossa, já tá a maior tempão sem tomar dano.")
    assert not narra("Que isso, vai matar de primeira?")
    assert not narra("Esse chefe é chato demais, olha a cara dele.")
    assert not narra("")


def test_v047_orcamento_de_ambiente_segura_o_modo_tagarela():
    from hollow_knight_emily.python.hollow_knight_politica import (
        LIMITE_AMBIENTE,
        PoliticaComentarios,
    )

    agora = [1000.0]
    politica = PoliticaComentarios(relogio=lambda: agora[0])
    tipos = ("dano", "observacao", "area_nova", "quase_morte", "inimigo_morto", "banco")
    dados = {"vida_atual": 1, "prioridade": 40}
    for tipo in tipos:
        assert politica.deve_responder(tipo, dict(dados), "tagarela")
        agora[0] += 25
    # Todos os cooldowns por tipo já passaram para "area_nova"; o que barra a
    # sétima fala é o orçamento de ambiente da janela.
    assert LIMITE_AMBIENTE["tagarela"] == len(tipos)
    assert not politica.deve_responder("area_nova", dict(dados), "tagarela")


def test_v047_cooldowns_de_luta_e_conversa_ficaram_mais_rigidos():
    from hollow_knight_emily.python.hollow_knight_politica import COOLDOWN_TIPO

    # 0.5.0: boss_luta baixou para 50s (era 90s) porque o usuário reportou
    # silêncio demais durante lutas longas. Ainda é restritivo o suficiente
    # para não virar narração contínua.
    assert COOLDOWN_TIPO["boss_luta"] >= 40
    assert COOLDOWN_TIPO["comentario_tagarela"] >= 120
    assert COOLDOWN_TIPO["dano"] >= 60
    assert COOLDOWN_TIPO["inimigo_morto"] >= 120


def test_v048_banco_e_dano_isolado_nao_geram_fala_em_modo_nenhum():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    for modo in ("muda", "quieta", "normal", "tagarela"):
        politica = PoliticaComentarios(relogio=lambda: 5000.0)
        assert not politica.deve_responder("banco", {}, modo), modo
        assert not politica.deve_responder("dano", {"vida_atual": 8, "dano": 1}, modo), modo
    # Descobrir banco novo continua sendo marco; quase morte continua falando.
    marco = PoliticaComentarios(relogio=lambda: 5000.0)
    assert marco.deve_responder("banco_descoberto", {"nome": "um novo banco"}, "normal")
    risco = PoliticaComentarios(relogio=lambda: 5000.0)
    assert risco.deve_responder("quase_morte", {"vida_atual": 1}, "normal")


def test_v048_saudacao_fala_em_todos_os_modos():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    for modo in ("muda", "quieta", "normal", "tagarela"):
        politica = PoliticaComentarios(relogio=lambda: 6000.0)
        assert politica.deve_responder(
            "boas_vindas", {"persistente": True}, modo
        ), modo
    texto = PoliticaComentarios().fallback("boas_vindas", {})
def test_v049_dano_besta_nao_e_assunto():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    # Machucado pequeno e isolado passa em branco em todos os modos.
    for modo in ("muda", "quieta", "normal", "tagarela"):
        politica = PoliticaComentarios(relogio=lambda: 7000.0)
        assert not politica.deve_responder(
            "dano", {"dano": 1, "vida_atual": 8}, modo
        ), modo
    # Repetição não é anormalidade sozinha: o mod continua marcando dano comum.
    politica = PoliticaComentarios(relogio=lambda: 7000.0)
    assert not politica.deve_responder("dano", {"dano": 2, "vida_atual": 6}, "tagarela")


def test_v049_dano_anormal_pode_falar_em_todos_os_modos():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    # Golpe pesado de uma vez e vida no fio entram como assunto anormal.
    for dados in ({"dano": 3, "vida_atual": 6}, {"dano": 1, "vida_atual": 2}):
        for modo in ("normal", "tagarela"):
            politica = PoliticaComentarios(relogio=lambda: 8000.0)
            assert politica.deve_responder("dano", dict(dados), modo), (dados, modo)
    # O modo quieta é para falar pouco: só vida no fio (coberto por quase_morte)
    # rompe o silêncio; dano anormal mas não crítico continua calado.
    silenciosa = PoliticaComentarios(relogio=lambda: 8000.0)
    assert not silenciosa.deve_responder("dano", {"dano": 3, "vida_atual": 6}, "quieta")
    # No modo muda só quase_morte e marcos entram, então dano anormal é barrado.
    muda = PoliticaComentarios(relogio=lambda: 8000.0)
    assert not muda.deve_responder("dano", {"dano": 3, "vida_atual": 6}, "muda")


def test_v049_fallback_de_dano_anormal_e_curto():
    import re
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    politica = PoliticaComentarios()
    texto = politica.fallback("dano", {"dano": 3, "vida_atual": 4})
    assert texto
    assert len(texto) <= 90
    assert not re.search(r"\d", texto)
    assert not politica.parece_narracao_de_estatistica(texto)



def test_v048_dano_besta_passa_em_branco_mas_anormal_fala():
    import re as _re
    from hollow_knight_emily.python.hollow_knight_politica import (
        PoliticaComentarios, dano_anormal,
    )

    # Um arranhão de rotina nunca vira fala, em nenhum modo.
    for modo in ("muda", "quieta", "normal", "tagarela"):
        politica = PoliticaComentarios(relogio=lambda: 7000.0)
        assert not politica.deve_responder(
            "dano", {"dano": 1, "vida_atual": 8}, modo
        ), modo
    assert not dano_anormal({"dano": 1, "vida_atual": 8})

    # Perder várias máscaras de uma vez ou ficar no fio da vida merece reação.
    assert dano_anormal({"dano": 3, "vida_atual": 7})
    assert dano_anormal({"dano": 1, "vida_atual": 2})
    politica = PoliticaComentarios(relogio=lambda: 7000.0)
    assert politica.deve_responder("dano", {"dano": 3, "vida_atual": 7}, "normal")
    risco = PoliticaComentarios(relogio=lambda: 7100.0)
    assert risco.deve_responder("dano", {"dano": 1, "vida_atual": 2}, "tagarela")

    # E quando fala, o comentário é curto e sem números.
    for _ in range(12):
        texto = PoliticaComentarios().fallback("dano", {"dano": 4, "vida_atual": 5})
        assert texto and len(texto) <= 90
        assert not _re.search(r"\d", texto)


def test_v048_prompt_pede_reacao_curta_a_dano_anormal():
    from hollow_knight_emily.python.hollow_knight_cerebro import SYSTEM_HOLLOW_KNIGHT

    assert "Dano anormal é uma reação, não uma análise" in SYSTEM_HOLLOW_KNIGHT
    assert "diário do que vocês viveram" in SYSTEM_HOLLOW_KNIGHT


def test_v048_dano_comum_nao_vira_fala():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    for modo in ("muda", "quieta", "normal", "tagarela"):
        politica = PoliticaComentarios(relogio=lambda: 7000.0)
        # Um machucado de uma máscara com vida cheia não merece comentário.
        assert not politica.deve_responder(
            "dano", {"vida_atual": 8, "vida_maxima": 9, "dano": 1}, modo
        ), modo


def test_v048_dano_anormal_pode_falar_mas_curto():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    # Perder várias máscaras de uma vez é anormal em qualquer modo que fale.
    for modo in ("normal", "tagarela"):
        politica = PoliticaComentarios(relogio=lambda: 7100.0)
        assert politica.deve_responder(
            "dano", {"vida_atual": 5, "vida_maxima": 9, "dano": 4}, modo
        ), modo
    # Vida no fio da vida também conta como anormal.
    politica = PoliticaComentarios(relogio=lambda: 7200.0)
    assert politica.deve_responder(
        "dano", {"vida_atual": 2, "vida_maxima": 9, "dano": 1}, "normal"
    )
    # E o comentário de dano é uma reação curta, nunca um painel.
    texto = PoliticaComentarios().fallback("dano", {"dano": 4, "vida_atual": 5})
    assert texto and not __import__("re").search(r"\d", texto)
    assert len(texto) <= 120

    assert texto and not __import__("re").search(r"\d", texto)


def test_v048_dano_besta_nao_vira_fala_em_nenhum_modo():
    """Machucado pequeno e isolado é silêncio, inclusive no tagarela."""
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    for modo in ("muda", "quieta", "normal", "tagarela"):
        politica = PoliticaComentarios(relogio=lambda: 7000.0)
        assert not politica.deve_responder(
            "dano", {"dano": 1, "vida_atual": 7, "prioridade": 6}, modo
        ), modo
        politica = PoliticaComentarios(relogio=lambda: 7000.0)
        assert not politica.deve_responder(
            "dano", {"dano": 2, "vida_atual": 6}, modo
        ), modo


def test_v048_dano_anormal_tem_reacao_curta():
    from hollow_knight_emily.python.hollow_knight_politica import (
        PoliticaComentarios, dano_anormal,
    )

    assert dano_anormal({"dano": 3, "vida_atual": 6})
    assert dano_anormal({"dano": 1, "vida_atual": 2})
    assert not dano_anormal({"dano": 1, "vida_atual": 9})
    assert not dano_anormal({})
    # Dano anormal ganha prioridade suficiente para vencer o corte de "normal"
    # (mínimo 25) e de "tagarela" (8), mas não os de "quieta" (60) e "muda" (90).
    for modo in ("normal", "tagarela"):
        politica = PoliticaComentarios(relogio=lambda: 8000.0)
        assert politica.deve_responder(
            "dano", {"dano": 3, "vida_atual": 6, "prioridade": 6}, modo
        ), modo
    for modo in ("muda", "quieta"):
        politica = PoliticaComentarios(relogio=lambda: 8000.0)
        assert not politica.deve_responder(
            "dano", {"dano": 4, "vida_atual": 5, "prioridade": 6}, modo
        ), modo
    texto = PoliticaComentarios().fallback("dano", {"dano": 4, "vida_atual": 5})
    assert texto and not __import__("re").search(r"\d", texto)
    assert len(texto) < 120


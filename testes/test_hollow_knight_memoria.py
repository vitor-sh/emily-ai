import sqlite3
import types


class Relogio:
    def __init__(self, valor=1_000_000.0):
        self.valor = float(valor)

    def __call__(self):
        return self.valor

    def avancar(self, segundos):
        self.valor += segundos


def sessao(campanha="slot-1", sid="sessao-1"):
    return types.SimpleNamespace(
        id=sid,
        campanha_id=campanha,
        versao_mod="0.4.5",
        estado={"modo_fala": "normal", "voz": False},
    )


def evento(relogio, numero, tipo, dados=None, cena="Town:1"):
    from hollow_knight_emily.python.hollow_knight_protocolo import EventoJogo

    return EventoJogo(
        id=f"run-a-{numero}",
        sessao_id="sessao-1",
        cena_id=cena,
        tipo=tipo,
        dados=dados or {},
        criado_em=relogio(),
    )


def estado_base(**extra):
    dados = {
        "vida_atual": 5,
        "vida_maxima": 5,
        "dano_ferrao": 5,
        "geo": 0,
        "zona": "TOWN",
        "tempo_sessao": 4,
        "segundos_ativos_delta": 4,
        "parado_segundos": 0,
        "em_gameplay": True,
        "no_banco": False,
        "habilidades": {"dash": False, "garra": False},
    }
    dados.update(extra)
    return dados


def test_memoria_persiste_linha_do_tempo_e_separa_slots(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    arquivo = tmp_path / "memoria.sqlite3"
    memoria = MemoriaHollowKnight(arquivo, relogio)
    s1 = sessao("slot-1", "s1")
    memoria.registrar_sessao(s1)
    memoria.registrar_eventos(s1, [
        evento(relogio, 1, "jogo_iniciado", {"vida_maxima": 5, "dano_ferrao": 5}),
        evento(relogio, 2, "area_nova", {"cena": "Town", "zona": "TOWN"}),
        evento(relogio, 3, "estado", estado_base()),
    ])
    relogio.avancar(30)
    memoria.registrar_eventos(s1, [evento(relogio, 4, "morte", {}, "Town:2")])

    s2 = sessao("slot-2", "s2")
    memoria.registrar_sessao(s2)
    memoria.registrar_eventos(s2, [
        evento(relogio, 5, "jogo_iniciado", {"vida_maxima": 7}, "Crossroads:1")
    ])

    reaberta = MemoriaHollowKnight(arquivo, relogio)
    c1 = reaberta.contexto("slot-1")
    c2 = reaberta.contexto("slot-2")
    assert c1["campanha"]["mortes"] == 1
    assert c1["campanha"]["ultima_area"] == "TOWN"
    assert c2["campanha"]["mortes"] == 0
    assert c2["campanha"]["sessoes"] == 1
    assert arquivo.stat().st_mode & 0o077 == 0


def test_evento_reenviado_apos_reconexao_nao_duplica(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    primeira = sessao("slot-1", "ponte-a")
    segunda = sessao("slot-1", "ponte-b")
    memoria.registrar_sessao(primeira)
    morte = evento(relogio, 1, "morte")
    memoria.registrar_eventos(primeira, [morte])
    memoria.registrar_sessao(segunda)
    memoria.registrar_eventos(segunda, [morte])
    assert memoria.contexto("slot-1")["campanha"]["mortes"] == 1


def test_sessoes_reais_contam_jogo_iniciado_nao_reconexao(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    memoria.registrar_sessao(sessao("slot-1", "ponte-a"))
    memoria.registrar_sessao(sessao("slot-1", "ponte-b"))
    assert memoria.contexto("slot-1")["campanha"]["sessoes"] == 0
    memoria.registrar_eventos(
        sessao("slot-1", "ponte-b"),
        [evento(relogio, 1, "jogo_iniciado")],
    )
    assert memoria.contexto("slot-1")["campanha"]["sessoes"] == 1


def test_detecta_dano_repetido_e_perigo_ambiental_com_escalonamento(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    observacoes = []
    # 0.4.8: dano pequeno e isolado deixou de gerar observação; o escalonamento
    # agora é testado com impacto grave e repetido.
    for i in range(1, 7):
        observacoes += memoria.registrar_eventos(s, [
            evento(relogio, i, "dano", {
                "dano": 2, "vida_atual": 4, "perigo": 1,
                "origem_confirmada": True,
            })
        ])
        relogio.avancar(12)
    prioridades = [o.dados["prioridade"] for o in observacoes]
    padroes = [o.dados["padrao"] for o in observacoes]
    assert "danos_repetidos" in padroes
    assert "perigo_repetido_1" in padroes
    assert max(prioridades) >= 65


def test_detecta_ociosidade_conforme_prioridade_e_ignora_banco(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    memoria.registrar_eventos(s, [evento(relogio, 1, "estado", estado_base())])
    relogio.avancar(50)
    tagarela = memoria.registrar_eventos(s, [
        evento(relogio, 2, "estado", estado_base(parado_segundos=50, tempo_sessao=54))
    ])
    assert any(o.dados["prioridade"] == 12 for o in tagarela)
    relogio.avancar(50)
    normal = memoria.registrar_eventos(s, [
        evento(relogio, 3, "estado", estado_base(parado_segundos=100, tempo_sessao=104))
    ])
    assert any(o.dados["prioridade"] == 34 for o in normal)
    relogio.avancar(100)
    discreta = memoria.registrar_eventos(s, [
        evento(relogio, 4, "estado", estado_base(parado_segundos=200, tempo_sessao=204))
    ])
    assert any(o.dados["prioridade"] == 66 for o in discreta)
    relogio.avancar(700)
    banco = memoria.registrar_eventos(s, [
        evento(relogio, 5, "estado", estado_base(
            parado_segundos=1000, tempo_sessao=904, no_banco=True
        ))
    ])
    assert not banco
    relogio.avancar(700)
    pausado = memoria.registrar_eventos(s, [
        evento(relogio, 6, "estado", estado_base(
            parado_segundos=1000, tempo_sessao=1604, pausado=True
        ))
    ])
    assert not pausado


def test_detecta_dificuldade_prolongada_sem_progresso_no_nivel_normal(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    memoria.registrar_eventos(s, [evento(relogio, 1, "estado", estado_base())])
    relogio.avancar(1100)
    memoria.registrar_eventos(s, [evento(relogio, 2, "dano", {"dano": 1, "perigo": 0})])
    relogio.avancar(100)
    memoria.registrar_eventos(s, [evento(relogio, 3, "morte")])
    relogio.avancar(100)
    memoria.registrar_eventos(s, [evento(relogio, 4, "dano", {"dano": 1, "perigo": 0})])
    relogio.avancar(600)
    observacoes = memoria.registrar_eventos(s, [
        evento(relogio, 5, "estado", estado_base(tempo_sessao=1904))
    ])
    dificuldade = next(
        o for o in observacoes if o.dados["padrao"] == "dificuldade_sem_progresso"
    )
    assert dificuldade.dados["prioridade"] == 42


def test_snapshot_detecta_progresso_silencioso_sem_duplicar_area(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    memoria.registrar_eventos(s, [evento(relogio, 1, "estado", estado_base())])
    relogio.avancar(40)
    progresso = memoria.registrar_eventos(s, [
        evento(relogio, 2, "estado", estado_base(
            vida_maxima=6,
            dano_ferrao=9,
            habilidades={"dash": True, "garra": False},
            tempo_sessao=44,
        ))
    ])
    assert len(progresso) == 1
    assert progresso[0].dados["padrao"] == "progresso_percebido"
    assert len(progresso[0].dados["evidencias"]["motivos"]) == 3
    relogio.avancar(40)
    area = memoria.registrar_eventos(s, [
        evento(relogio, 3, "area_nova", {"cena": "Crossroads", "zona": "CROSSROADS"})
    ])
    assert area == []


def test_contexto_e_compacto_e_nao_carrega_memoria_unificada(tmp_path):
    from hollow_knight_emily.python import hollow_knight_memoria as modulo

    fonte = open(modulo.__file__, encoding="utf-8").read()
    assert "import memoria_unificada" not in fonte
    assert "import chromadb" not in fonte
    relogio = Relogio()
    memoria = modulo.MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    memoria.registrar_eventos(s, [evento(relogio, 1, "jogo_iniciado")])
    for i in range(2, 35):
        relogio.avancar(31)
        memoria.registrar_eventos(s, [
            evento(relogio, i, "estado", estado_base(tempo_sessao=i * 31))
        ])
    assert len(memoria.contexto("slot-1", modo="normal")["recentes"]) <= 12
    assert len(memoria.contexto("slot-1", modo="tagarela")["recentes"]) <= 18


def test_endpoint_memoria_e_autenticado(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight
    from hollow_knight_emily.python.hollow_knight_ponte import PonteHollowKnight

    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3")
    ponte = PonteHollowKnight(token="segredo", memoria=memoria)
    cliente = ponte.app.test_client()
    assert cliente.get("/v1/hollow-knight/memoria?campanha_id=slot-1").status_code == 401
    resposta = cliente.get(
        "/v1/hollow-knight/memoria?campanha_id=slot-1",
        headers={"Authorization": "Bearer segredo"},
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["ok"] is True


def test_ponte_registra_eventos_na_memoria_e_devolve_observacao(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight
    from hollow_knight_emily.python.hollow_knight_ponte import PonteHollowKnight

    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3")
    ponte = PonteHollowKnight(token="segredo", memoria=memoria)
    cliente = ponte.app.test_client()
    sid = cliente.post(
        "/v1/hollow-knight/sessao",
        headers={"Authorization": "Bearer segredo"},
        json={"campanha_id": "slot-1", "versao_mod": "0.4.5",
              "configuracao": {"modo_fala": "tagarela", "voz": False}},
    ).get_json()["sessao_id"]
    eventos = []
    # 0.4.8: a observação só aparece com dano grave/repetido.
    for numero in range(1, 5):
        eventos.append({
            "id": f"run-x-{numero}", "cena_id": "Town:1", "tipo": "dano",
            "criado_em": 2_000_000 + numero,
            "dados": {"dano": 2, "vida_atual": 4, "perigo": 0},
        })
    resposta = cliente.post(
        "/v1/hollow-knight/eventos",
        headers={"Authorization": "Bearer segredo"},
        json={"sessao_id": sid, "eventos": eventos},
    )
    assert resposta.status_code == 200
    assert resposta.get_json()["aceitos"] == 4
    assert resposta.get_json()["observacoes"] >= 1
    resumo = cliente.get(
        f"/v1/hollow-knight/memoria?sessao_id={sid}",
        headers={"Authorization": "Bearer segredo"},
    ).get_json()
    assert resumo["campanha"]["danos"] == 4


def test_sqlite_tem_tabelas_esperadas(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    arquivo = tmp_path / "memoria.sqlite3"
    MemoriaHollowKnight(arquivo)
    with sqlite3.connect(arquivo) as con:
        tabelas = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert {"campanhas", "sessoes", "eventos", "eventos_processados", "areas", "padroes"} <= tabelas


def test_dano_sem_origem_confirmada_nao_inventa_espinhos(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    memoria.registrar_eventos(s, [
        evento(relogio, 1, "dano", {
            "dano": 1, "vida_atual": 4, "hazard_tipo_bruto": 1,
            "origem_confirmada": False,
        })
    ])
    with sqlite3.connect(memoria.arquivo) as con:
        resumo = con.execute(
            "SELECT resumo FROM eventos WHERE tipo='dano'"
        ).fetchone()[0]
    assert "espinho" not in resumo.lower()
    assert "origem não confirmada" in resumo.lower()


def test_marcos_novos_contam_como_progresso_e_entram_na_linha_do_tempo(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    tipos = (
        "amuleto_adquirido", "estacao_desbloqueada",
        "item_importante_adquirido", "magia_adquirida", "boss_derrotado",
    )
    for numero, tipo in enumerate(tipos, 1):
        memoria.registrar_eventos(s, [
            evento(relogio, numero, tipo, {"nome": f"marco {numero}"})
        ])
        relogio.avancar(1)
    contexto = memoria.contexto("slot-1", modo="tagarela")
    recentes = {item["tipo"] for item in contexto["recentes"]}
    assert set(tipos) <= recentes


def test_poderes_automaticos_nao_dominam_contexto_recente(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    for numero in range(1, 30):
        memoria.registrar_eventos(s, [
            evento(relogio, numero, "poder_usado", {
                "poder": "faisca_teimosa", "automatico": True,
            })
        ])
        relogio.avancar(1)
    memoria.registrar_eventos(s, [
        evento(relogio, 31, "magia_adquirida", {"nome": "Espírito Vingativo"})
    ])
    recentes = memoria.contexto("slot-1", modo="normal")["recentes"]
    assert recentes[0]["tipo"] == "magia_adquirida"
    assert sum(item["tipo"] == "poder_usado" for item in recentes) <= 1


def test_primeiro_snapshot_v044_reconcilia_estado_sem_inventar_aquisicoes(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    progresso = {
        "amuletos_total": 3,
        "estacoes_total": 1,
        "bosses_derrotados": ["killedFalseKnight"],
        "magias": {"fireballLevel": 1, "quakeLevel": 0, "screamLevel": 0},
    }
    derivados = memoria.registrar_eventos(s, [
        evento(relogio, 1, "estado", estado_base(progresso=progresso))
    ])
    assert derivados == []
    with sqlite3.connect(memoria.arquivo) as con:
        tipos = [r[0] for r in con.execute("SELECT tipo FROM eventos ORDER BY numero")]
        dados = con.execute(
            "SELECT dados_json FROM eventos WHERE tipo='progresso_reconciliado'"
        ).fetchone()[0]
    assert tipos.count("progresso_reconciliado") == 1
    assert '"nao_retroativo":true' in dados


def test_migracao_oculta_poderes_automaticos_antigos_sem_apagar_eventos(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    arquivo = tmp_path / "memoria.sqlite3"
    memoria = MemoriaHollowKnight(arquivo, relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    memoria.registrar_eventos(s, [
        evento(relogio, 1, "poder_usado", {"poder": "faisca_teimosa"}),
        evento(relogio, 2, "poder_usado", {"poder": "pulso_do_vinculo"}),
    ])
    MemoriaHollowKnight(arquivo, relogio)
    with sqlite3.connect(arquivo) as con:
        linhas = con.execute(
            "SELECT dados_json FROM eventos WHERE tipo='poder_usado' ORDER BY numero"
        ).fetchall()
    assert len(linhas) == 2
    assert '\"automatico\":true' in linhas[0][0]
    assert 'automatico' not in linhas[1][0]


def test_v045_memoria_resume_dialogo_encontro_e_observacao_de_boss(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    memoria.registrar_eventos(s, [
        evento(relogio, 1, "npc_dialogo", {
            "nome": "Quirrel", "fala": "O lago está quieto.",
        }),
        evento(relogio, 2, "boss_encontrado", {"nome": "Hornet"}),
        evento(relogio, 3, "boss_luta", {
            "nome": "Hornet", "padrao": "sequencia_sem_dano",
            "golpes_desde_comentario": 7, "segundos_sem_dano": 22,
        }),
        evento(relogio, 4, "comentario_tagarela", {
            "zona": "GREEN_PATH", "progresso": {"amuletos_total": 3},
        }),
    ])
    contexto = memoria.contexto("slot-1", modo="tagarela")
    resumos = "\n".join(item["resumo"] for item in contexto["recentes"])
    assert "Quirrel" in resumos and "O lago está quieto" in resumos
    assert "Hornet" in resumos
    # 0.4.7: o resumo guardado para o modelo não carrega mais métricas cruas,
    # então o padrão aparece descrito e não como "7 golpes / 22s".
    assert "sem tomar dano" in resumos
    assert "GREEN_PATH" in resumos


def test_v045_memoria_nao_promove_nome_interno_nao_confirmado(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    memoria.registrar_eventos(s, [
        evento(relogio, 1, "boss_encontrado", {
            "nome": "Boss Internal Clone", "identidade_confirmada": False,
        }),
        evento(relogio, 2, "npc_dialogo", {
            "nome": "NPC Control", "identidade_confirmada": False,
            "fala": "O caminho fechou.",
        }),
    ])
    resumos = "\n".join(
        item["resumo"] for item in memoria.contexto("slot-1", modo="tagarela")["recentes"]
    )
    assert "Boss Internal Clone" not in resumos
    assert "NPC Control" not in resumos
    assert "um chefe" in resumos
    assert "O caminho fechou" in resumos


def test_v048_dano_trivial_nao_vira_assunto_da_emily(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    derivados = []
    for numero in range(1, 8):
        derivados += memoria.registrar_eventos(s, [
            evento(relogio, numero, "dano", {"dano": 1, "vida_atual": 8}),
        ])
        relogio.avancar(5)
    # Machucado pequeno e isolado não merece comentário, mesmo repetido.
    assert [item.tipo for item in derivados] == []


def test_v048_dano_grave_e_repetido_vira_observacao(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    derivados = []
    for numero in range(1, 7):
        derivados += memoria.registrar_eventos(s, [
            evento(relogio, numero, "dano", {"dano": 2, "vida_atual": 4}),
        ])
        relogio.avancar(5)
    padroes = [item.dados.get("padrao") for item in derivados if item.tipo == "observacao"]
    assert "danos_repetidos" in padroes


def test_v048_saudacao_entra_na_memoria_da_campanha(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    memoria.registrar_eventos(s, [
        evento(relogio, 1, "boas_vindas", {"zona": "TOWN", "persistente": True}),
    ])
    resumos = "\n".join(
        item["resumo"] for item in memoria.contexto("slot-1", modo="normal")["recentes"]
    )
    assert "entrou no jogo" in resumos
def test_v049_diario_de_historia_sobrevive_a_sessao_de_luta(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    memoria.registrar_eventos(s, [
        evento(relogio, 1, "npc_dialogo", {
            "nome": "Elderbug", "identidade_confirmada": True,
            "fala": "Bem-vindo a Dirtmouth.",
        }),
        evento(relogio, 2, "magia_adquirida", {"nome": "Espírito Vingativo"}),
    ])
    # Enche o histórico recente de combate: sem o diário, essas linhas empurram
    # as conversas com NPC para fora da janela do modo normal.
    for numero in range(3, 40):
        relogio.avancar(6)
        memoria.registrar_eventos(s, [
            evento(relogio, numero, "inimigo_morto", {"inimigo": "Vengefly"}),
        ])
    contexto = memoria.contexto("slot-1", modo="normal")
    assert contexto["historia"], "o diário da história não pode esvaziar"
    resumos = "\n".join(item["resumo"] for item in contexto["historia"])
    assert "Elderbug" in resumos
    assert "Espírito Vingativo" in resumos
    assert all("ha" in item for item in contexto["historia"])


def test_v049_historia_fica_ausente_em_campanha_desconhecida(tmp_path):
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", Relogio())
    contexto = memoria.contexto("slot-inexistente")
    assert contexto["historia"] == []
def test_v048_historia_sobrevive_a_sessao_cheia_de_combate(tmp_path):
    """O diário da história não pode ser empurrado para fora pelos "recentes"."""
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    memoria.registrar_eventos(s, [
        evento(relogio, 1, "npc_dialogo",
               {"nome": "Ancião", "fala": "Hallownest caiu faz tempo.", "identidade_confirmada": True}),
        evento(relogio, 2, "boss_derrotado", {"nome": "Falso Cavaleiro"}),
    ])
    # Muita luta depois: a sessão enche de eventos de rotina.
    for numero in range(3, 60):
        relogio.avancar(40)
        memoria.registrar_eventos(s, [
            evento(relogio, numero, "inimigo_morto", {"inimigo": "Vingefly"}),
        ])
    contexto = memoria.contexto("slot-1", modo="normal")
    historia = "\n".join(item["resumo"] for item in contexto["historia"])
    assert "Ancião" in historia
    assert "Falso Cavaleiro" in historia
    # O diário é separado dos recentes: não é só uma cópia da mesma janela.
    assert len(contexto["historia"]) <= 30
    assert all("ha" in item and "resumo" in item for item in contexto["historia"])


def test_v048_diario_de_historia_sobrevive_ao_limite_do_modo(tmp_path):
    """O diário guarda o que ela descobriu do mundo mesmo em modo silencioso."""
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    memoria.registrar_eventos(s, [
        evento(relogio, 1, "npc_dialogo", {
            "nome": "Elderbug", "fala": "Bem-vindo à vila.",
        }),
        evento(relogio, 2, "boss_derrotado", {"nome": "Falso Cavaleiro"}),
        evento(relogio, 3, "magia_adquirida", {"nome": "Ataque Vingativo"}),
    ])
    # Muita luta depois: em "quieta" só cabem 8 eventos recentes.
    for numero in range(4, 30):
        relogio.avancar(20)
        memoria.registrar_eventos(s, [
            evento(relogio, numero, "inimigo_morto", {"inimigo": "Bicho"}),
        ])
    contexto = memoria.contexto("slot-1", modo="quieta")
    tipos_historia = {item["tipo"] for item in contexto["historia"]}
    assert {"npc_dialogo", "boss_derrotado", "magia_adquirida"} <= tipos_historia
    assert all("ha" in item and "resumo" in item for item in contexto["historia"])
    recentes = {item["tipo"] for item in contexto["recentes"]}
    assert "npc_dialogo" not in recentes


def test_v048_area_repetida_nao_vira_progresso_de_novo(tmp_path):
    """Andar entre salas da mesma região não conta como região nova."""
    from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight

    relogio = Relogio()
    memoria = MemoriaHollowKnight(tmp_path / "memoria.sqlite3", relogio)
    s = sessao()
    memoria.registrar_sessao(s)
    primeira = memoria.registrar_eventos(s, [
        evento(relogio, 1, "area_nova", {"cena": "Town", "zona": "TOWN"}),
    ])
    # Área nova já é comentável por conta própria: a memória não cria uma
    # observação derivada em cima dela, para não falar duas vezes do mesmo fato.
    assert [item.tipo for item in primeira] == []
    assert memoria.contexto("slot-1")["campanha"]["areas_conhecidas"] == 1

    relogio.avancar(60)
    repetida = memoria.registrar_eventos(s, [
        evento(relogio, 2, "area_nova", {"cena": "Town", "zona": "TOWN"}),
    ])
    assert [item.tipo for item in repetida] == []
    assert memoria.contexto("slot-1")["campanha"]["areas_conhecidas"] == 1

    relogio.avancar(60)
    outra = memoria.registrar_eventos(s, [
        evento(relogio, 3, "area_nova", {"cena": "Fungus1_01", "zona": "GREEN_PATH"}),
    ])
    assert [item.tipo for item in outra] == []
    assert memoria.contexto("slot-1")["campanha"]["areas_conhecidas"] == 2

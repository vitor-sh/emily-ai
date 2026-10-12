"""Lâmpada e tomada Tuya: vocabulário, conversões e a trava da energia do PC.

Nada aqui toca a rede: os aparelhos são um devices.json de mentira e o
transporte é substituído por um registro em memória.
"""
import json

import pytest

import casa_inteligente as casa


LUZ = {"name": "Smart Lamp", "id": "luz123", "key": "k", "ip": "10.0.0.2", "version": "3.5",
       "category": "dj", "mapping": {
           "20": {"code": "switch_led", "type": "Boolean", "values": {}},
           "21": {"code": "work_mode", "type": "Enum", "values": {}},
           "22": {"code": "bright_value_v2", "type": "Integer", "values": {"min": 10, "max": 1000}},
           "23": {"code": "temp_value_v2", "type": "Integer", "values": {"min": 0, "max": 1000}},
           "24": {"code": "colour_data_v2", "type": "Json", "values": {}}}}
TOMADA = {"name": "Smart Plug", "id": "tom456", "key": "k", "ip": "10.0.0.3", "version": "3.5",
          "category": "cz", "mapping": {
              "1": {"code": "switch_1", "type": "Boolean", "values": {}},
              "19": {"code": "cur_power", "type": "Integer", "values": {"scale": 1}},
              "20": {"code": "cur_voltage", "type": "Integer", "values": {"scale": 1}},
              "38": {"code": "relay_status", "type": "Enum", "values": {}}}}


@pytest.fixture
def casa_falsa(tmp_path, monkeypatch):
    (tmp_path / "devices.json").write_text(json.dumps([LUZ, TOMADA]))
    monkeypatch.setenv("EMILY_CASA_DIR", str(tmp_path))
    estados = {
        "luz123": {"switch_led": False, "work_mode": "white", "bright_value_v2": 1000,
                   "temp_value_v2": 1000, "colour_data_v2": {"h": 30, "s": 1000, "v": 500}},
        "tom456": {"switch_1": True, "cur_power": 1500, "cur_voltage": 1270, "relay_status": "memory"},
    }
    enviados = []

    def ler(d, transporte=""):
        return dict(estados[d["id"]])

    def enviar(d, comandos, transporte=""):
        enviados.append((d["id"], dict(comandos)))
        estados[d["id"]].update(comandos)
        return "local"

    monkeypatch.setattr(casa, "ler", ler)
    monkeypatch.setattr(casa, "enviar", enviar)
    casa._pendente.clear()
    casa._espera.clear()
    return estados, enviados


def test_dispositivos_ganham_tipo_e_nome_amigavel(casa_falsa):
    nomes = {d["id"]: (d["tipo"], d["nome"]) for d in casa.dispositivos()}
    assert nomes == {"luz123": ("luz", "Lâmpada"), "tom456": ("tomada", "Tomada")}
    assert casa.tomada_pc()["id"] == "tom456"


@pytest.mark.parametrize("acao,esperado", [("ligar", True), ("desligar", False)])
def test_ligar_e_desligar_sao_absolutos(casa_falsa, acao, esperado):
    _, enviados = casa_falsa
    r = casa.controlar_luz(acao)
    assert r["ok"] and enviados == [("luz123", {"switch_led": esperado})]


def test_alternar_le_o_estado_antes(casa_falsa):
    estados, enviados = casa_falsa
    casa.controlar_luz("alternar")
    assert enviados[-1][1] == {"switch_led": True}


def test_cor_por_nome_vira_hsv_com_brilho(casa_falsa):
    _, enviados = casa_falsa
    r = casa.controlar_luz("cor", cor="Azul", brilho=50)
    comandos = enviados[-1][1]
    assert comandos["work_mode"] == "colour" and comandos["switch_led"] is True
    assert comandos["colour_data_v2"]["h"] == 240 and comandos["colour_data_v2"]["s"] == 1000
    assert comandos["colour_data_v2"]["v"] == casa._pct_para(50, 10, 1000)
    assert "azul" in r["mensagem"]


def test_cor_hex_e_cor_desconhecida(casa_falsa):
    _, enviados = casa_falsa
    casa.controlar_luz("cor", cor="#ff0000")
    assert enviados[-1][1]["colour_data_v2"]["h"] == 0
    with pytest.raises(casa.CasaErro, match="Não conheço a cor"):
        casa.controlar_luz("cor", cor="cor de burro quando foge")


@pytest.mark.parametrize("cor,temp", [("quente", 0), ("fria", 1000)])
def test_luz_quente_e_fria_vao_para_o_branco(casa_falsa, cor, temp):
    _, enviados = casa_falsa
    casa.controlar_luz("cor", cor=cor)
    assert enviados[-1][1] == {"switch_led": True, "work_mode": "white", "temp_value_v2": temp}


def test_brilho_respeita_o_modo_atual(casa_falsa):
    estados, enviados = casa_falsa
    casa.controlar_luz("brilho", brilho=100)
    assert enviados[-1][1] == {"switch_led": True, "bright_value_v2": 1000}
    estados["luz123"]["work_mode"] = "colour"
    casa.controlar_luz("brilho", brilho=1)
    assert enviados[-1][1]["colour_data_v2"] == {"h": 30, "s": 1000, "v": casa._pct_para(1, 10, 1000)}


def test_acao_invalida_e_temperatura_sem_valor(casa_falsa):
    with pytest.raises(casa.CasaErro):
        casa.controlar_luz("piscar")
    with pytest.raises(casa.CasaErro):
        casa.controlar_luz("temperatura")


def test_resumo_da_tomada_aplica_escala(casa_falsa):
    estados, _ = casa_falsa
    d = casa.tomada_pc()
    info = casa.resumo_tomada(d, estados["tom456"])
    assert info["potencia_w"] == 150.0 and info["tensao_v"] == 127.0
    assert info["ao_voltar_energia"] == "volta como estava"


def test_estado_descreve_tudo_e_marca_a_energia_do_pc(casa_falsa):
    dados = casa.estado()
    texto = casa.descrever_estado(dados)
    assert "Lâmpada: desligada" in texto
    assert "Tomada (energia do PC): ligada, consumindo 150 W" in texto


# ── A trava: a tomada alimenta o PC ───────────────────────────────

def test_nao_corta_energia_com_pc_ligado(casa_falsa):
    _, enviados = casa_falsa
    r = casa.energia_pc("desligar", pc_online=lambda: True)
    assert r["ok"] is False and r["requer_confirmacao"] and enviados == []


def test_consumo_alto_conta_como_ligado_mesmo_sem_gateway(casa_falsa):
    _, enviados = casa_falsa
    r = casa.energia_pc("desligar", pc_online=lambda: False)
    assert r["requer_confirmacao"] and "150 W" in r["mensagem"] and enviados == []


def test_sem_leitura_de_consumo_nao_arrisca(casa_falsa):
    estados, enviados = casa_falsa
    estados["tom456"]["cur_power"] = None
    r = casa.energia_pc("desligar", pc_online=lambda: None)
    assert r["requer_confirmacao"] and enviados == []


def test_corta_quando_pc_esta_desligado(casa_falsa):
    estados, enviados = casa_falsa
    estados["tom456"]["cur_power"] = 20  # 2 W: só o estabilizador
    r = casa.energia_pc("desligar", pc_online=lambda: False)
    assert r["ok"] and enviados == [("tom456", {"switch_1": False})]


def test_confirmacao_exige_id_certo_e_expira(casa_falsa):
    _, enviados = casa_falsa
    relogio = [1000.0]
    pedido = casa.energia_pc("desligar", pc_online=lambda: True, agora=lambda: relogio[0])
    errado = casa.energia_pc("confirmar_desligar", pc_online=lambda: True,
                             confirmation_id="outro", agora=lambda: relogio[0])
    assert errado["ok"] is False and enviados == []
    relogio[0] += casa.CONFIRMACAO_TTL + 1
    expirado = casa.energia_pc("confirmar_desligar", pc_online=lambda: True,
                               confirmation_id=pedido["confirmation_id"], agora=lambda: relogio[0])
    assert expirado["ok"] is False and enviados == []


def test_confirmacao_valida_corta_uma_vez(casa_falsa):
    _, enviados = casa_falsa
    pedido = casa.energia_pc("desligar", pc_online=lambda: True)
    ok = casa.energia_pc("confirmar_desligar", pc_online=lambda: True,
                         confirmation_id=pedido["confirmation_id"])
    de_novo = casa.energia_pc("confirmar_desligar", pc_online=lambda: True,
                              confirmation_id=pedido["confirmation_id"])
    assert ok["ok"] and de_novo["ok"] is False
    assert enviados == [("tom456", {"switch_1": False})]


def test_aguardar_corta_depois_de_duas_leituras_desligado(casa_falsa, monkeypatch):
    estados, enviados = casa_falsa
    monkeypatch.setattr(casa, "INTERVALO_ESPERA_S", 0.01)
    online = [True]
    r = casa.energia_pc("desligar", pc_online=lambda: online[0], aguardar_pc=True)
    assert r["aguardando"] and enviados == []
    online[0] = False
    estados["tom456"]["cur_power"] = 20
    for _ in range(300):
        if not casa._espera.get("ativa"):
            break
        import time; time.sleep(0.01)
    assert enviados == [("tom456", {"switch_1": False})]
    assert casa._espera["resultado"] == "energia cortada depois que o PC desligou"


def test_cancelar_espera_nao_corta(casa_falsa, monkeypatch):
    _, enviados = casa_falsa
    monkeypatch.setattr(casa, "INTERVALO_ESPERA_S", 0.05)
    casa.energia_pc("desligar", pc_online=lambda: True, aguardar_pc=True)
    assert casa.energia_pc("cancelar", pc_online=lambda: True)["ok"]
    import time; time.sleep(0.2)
    assert enviados == [] and not casa._espera.get("ativa")


def test_ligar_energia_cancela_espera(casa_falsa, monkeypatch):
    _, enviados = casa_falsa
    monkeypatch.setattr(casa, "INTERVALO_ESPERA_S", 0.05)
    casa.energia_pc("desligar", pc_online=lambda: True, aguardar_pc=True)
    r = casa.energia_pc("ligar", pc_online=lambda: True)
    assert r["ok"] and enviados == [("tom456", {"switch_1": True})] and "BIOS" in r["mensagem"]


# ── Transporte ────────────────────────────────────────────────────

def test_auto_cai_para_a_nuvem_quando_local_falha(tmp_path, monkeypatch):
    (tmp_path / "devices.json").write_text(json.dumps([LUZ]))
    monkeypatch.setenv("EMILY_CASA_DIR", str(tmp_path))
    d = casa.luzes()[0]

    def local_falha():
        raise OSError("timeout")

    assert casa._via(d, local_falha, lambda: "ok", "auto") == ("ok", "nuvem")
    with pytest.raises(casa.CasaErro):
        casa._via(d, local_falha, lambda: "ok", "local")


def test_nuvem_sem_chave_local_vai_direto(tmp_path, monkeypatch):
    sem_chave = {**LUZ, "key": "", "ip": ""}
    (tmp_path / "devices.json").write_text(json.dumps([sem_chave]))
    monkeypatch.setenv("EMILY_CASA_DIR", str(tmp_path))
    chamado = []
    d = casa.luzes()[0]
    assert casa._via(d, lambda: chamado.append(1), lambda: "n", "auto") == ("n", "nuvem")
    assert chamado == []


def test_cor_local_ida_e_volta_no_formato_hex(casa_falsa):
    d = casa.luzes()[0]
    codigo, valor = casa._converter_dp(d, "24", "00f003e80064")
    assert codigo == "colour_data_v2" and valor == {"h": 240, "s": 1000, "v": 100}


def test_erro_de_permissao_explica_renovacao():
    assert "IoT Core" in casa._erro_tuya({"Payload": "permission deny"})


def test_ferramentas_registradas_e_energia_so_na_nuvem(monkeypatch):
    import ferramentas
    assert {"casa_estado", "controlar_luz"} <= set(ferramentas.CATALOGO)
    assert ferramentas.CATALOGO["casa_estado"].somente_leitura is True
    assert "energia_pc" not in ferramentas.CATALOGO
    from cloud_runtime_client import ferramenta_local_na_nuvem
    for nome in ("casa_estado", "controlar_luz"):
        assert ferramenta_local_na_nuvem(ferramentas.CATALOGO[nome])


@pytest.mark.parametrize("texto,acao", [("Emily, acende a luz!", "ligar"), ("apaga a lâmpada do quarto", "desligar"),
                                        ("desliga a luz pra mim", "desligar")])
def test_atalho_literal_da_luz(texto, acao):
    import comandos_rapidos
    assert comandos_rapidos.parse(texto) == ("controlar_luz", {"acao": acao})


@pytest.mark.parametrize("texto", ["não apaga a luz", "apaga a luz depois", "como liga a luz?",
                                   "apaga a luz e desliga o pc", "desliga a energia do pc", "desliga a tomada"])
def test_atalho_nao_pega_pedido_incerto_nem_energia(texto):
    import comandos_rapidos
    assert comandos_rapidos.parse(texto) is None


def test_rota_casa_da_oracle(casa_falsa, tmp_path, monkeypatch):
    import cloud_runtime_server as server
    import ferramentas
    config = tmp_path / "relay.json"
    config.write_text(json.dumps({"upload_key": "k-test"}))
    monkeypatch.setenv("EMILY_RELAY_CONFIG", str(config))
    monkeypatch.setattr(ferramentas, "_pc_responde", lambda: True)
    http = server.create_app().test_client()
    h = {"Authorization": "Bearer k-test"}
    assert http.post("/casa", json={"operation": "estado"}).status_code == 401
    estado = http.post("/casa", headers=h, json={"operation": "estado", "args": {}}).get_json()
    assert estado["ok"] and "Lâmpada" in estado["mensagem"] and "hsv" not in json.dumps(estado)
    luz = http.post("/casa", headers=h, json={"operation": "luz", "args": {"acao": "cor", "cor": "verde"}}).get_json()
    assert luz["ok"] and "verde" in luz["mensagem"]
    assert http.post("/casa", headers=h, json={"operation": "luz", "args": {"acao": "ligar", "x": 1}}).status_code == 400
    corte = http.post("/casa", headers=h, json={"operation": "energia_pc", "args": {"acao": "desligar"}}).get_json()
    assert corte["requer_confirmacao"] and casa_falsa[1][-1][0] == "luz123"


def test_ferramenta_sem_casa_recusa_sem_quebrar(tmp_path, monkeypatch):
    import ferramentas
    monkeypatch.setenv("EMILY_CASA_DIR", str(tmp_path))
    r = ferramentas.executar_estruturado("controlar_luz", {"acao": "ligar"})
    assert r.ok is False and "não está configurada" in r.texto

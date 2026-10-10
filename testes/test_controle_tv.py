"""Testes do controle de TV da Emily do PC (sem rede e sem TV real).

Cobre o catálogo de dispositivos (tvs_salvas.json), os mapas de teclas/apps/
canais espelhados do celular, os erros amigáveis sem conexão e as 7 ferramentas
tv_* registradas no catálogo da Emily.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import controle_tv as tv  # noqa: E402
import ferramentas  # noqa: E402


@pytest.fixture()
def tv_isolada(tmp_path, monkeypatch):
    """Catalogo e legado apontando pra pasta temporária; nenhum estado de rede."""
    monkeypatch.setattr(tv, "ARQUIVO", tmp_path / "tvs_salvas.json")
    monkeypatch.setattr(tv, "LEGADO_TV_IP", tmp_path / "tv_ip.txt")
    monkeypatch.setattr(tv, "_dispositivo_ativo", {})
    monkeypatch.setattr(tv, "_remotes", {})
    return tmp_path


# ─── Catálogo de dispositivos ────────────────────────────────────────────

def test_salvar_e_listar_dispositivo(tv_isolada):
    d = tv.salvar_dispositivo("TV da Sala", "192.168.0.15", "TCL")
    assert d["nome"] == "TV da Sala"
    assert d["pareada"] is False
    lista = tv.listar_dispositivos()
    assert len(lista) == 1 and lista[0]["ip"] == "192.168.0.15"
    # persistiu no json
    dados = json.loads((tv_isolada / "tvs_salvas.json").read_text(encoding="utf-8"))
    assert dados[0]["tipo"] == "TCL"


def test_salvar_mesmo_ip_atualiza_em_vez_de_duplicar(tv_isolada):
    tv.salvar_dispositivo("TV da Sala", "192.168.0.15")
    d = tv.salvar_dispositivo("Quarto", "192.168.0.15", "Samsung")
    assert len(tv.listar_dispositivos()) == 1
    assert d["nome"] == "Quarto" and d["tipo"] == "Samsung"


@pytest.mark.parametrize("ip", ["", "abc", "192.168.1", "192.168.0.999.1"])
def test_salvar_ip_invalido_levanta(tv_isolada, ip):
    with pytest.raises(ValueError):
        tv.salvar_dispositivo("X", ip)


def test_editar_dispositivo(tv_isolada):
    d = tv.salvar_dispositivo("TV da Sala", "192.168.0.15")
    editado = tv.editar_dispositivo(d["id"], nome="Sala 4K", ip="192.168.0.20", tipo="LG")
    assert editado["nome"] == "Sala 4K"
    assert editado["ip"] == "192.168.0.20"
    assert editado["tipo"] == "LG"
    with pytest.raises(ValueError):
        tv.editar_dispositivo("id-fantasma")


def test_remover_dispositivo(tv_isolada):
    d = tv.salvar_dispositivo("TV da Sala", "192.168.0.15")
    assert tv.remover_dispositivo(d["id"]) == "OK"
    assert tv.listar_dispositivos() == []
    assert tv.remover_dispositivo(d["id"]) == "ERRO: dispositivo não encontrado"


def test_migracao_do_ip_legado(tmp_path, monkeypatch):
    (tmp_path / "tv_ip.txt").write_text("10.0.0.5\n", encoding="utf-8")
    monkeypatch.setattr(tv, "ARQUIVO", tmp_path / "tvs_salvas.json")
    monkeypatch.setattr(tv, "LEGADO_TV_IP", tmp_path / "tv_ip.txt")
    monkeypatch.setattr(tv, "_dispositivo_ativo", {})
    monkeypatch.setattr(tv, "_remotes", {})
    lista = tv.listar_dispositivos()
    assert len(lista) == 1
    assert lista[0]["ip"] == "10.0.0.5"
    # a migração fica em memória até o primeiro salvamento (sem escrever à toa)
    assert not (tmp_path / "tvs_salvas.json").exists()


def test_restaura_tv_ativa_persistida_sem_conectar(tv_isolada):
    dispositivo = tv.salvar_dispositivo("TV Sala", "192.168.0.20")
    dispositivo["ativa"] = True
    dispositivo["companion_token"] = "a" * 48
    tv._escrever_catalogo([dispositivo])

    ativo = tv.dispositivo_ativo()

    assert ativo is not None
    assert ativo["id"] == dispositivo["id"]
    assert ativo["companion_token"] == "a" * 48
    assert tv._remotes == {}


def test_conectar_persiste_uma_unica_tv_ativa(tv_isolada, monkeypatch):
    sala = tv.salvar_dispositivo("TV Sala", "192.168.0.20")
    quarto = tv.salvar_dispositivo("TV Quarto", "192.168.0.21")
    monkeypatch.setattr(tv, "_garantir_conectado", lambda dispositivo: object())

    resultado = tv.conectar_dispositivo(quarto["id"])
    salvas = json.loads((tv_isolada / "tvs_salvas.json").read_text(encoding="utf-8"))

    assert resultado["ok"] is True
    assert [d["id"] for d in salvas if d.get("ativa")] == [quarto["id"]]
    assert not next(d for d in salvas if d["id"] == sala["id"])["ativa"]


# ─── Mapas espelhados do celular ─────────────────────────────────────────

def test_mapa_de_teclas_tem_os_comandos_do_celular():
    for tecla in ("power", "volume_up", "volume_down", "volume_mute", "home",
                  "back", "settings", "playpause", "up", "down", "left",
                  "right", "ok", "tv_input"):
        assert tecla in tv.TECLAS
        assert tv.TECLAS[tecla].startswith("KEYCODE_")


def test_mapa_de_apps_e_igual_ao_do_celular():
    assert set(tv.APPS_TV) >= {"youtube", "netflix", "prime video", "disney",
                               "max", "spotify", "globoplay"}
    assert tv.APPS_TV["youtube"] == "https://www.youtube.com"


def test_link_de_busca_somente_youtube_e_netflix():
    assert tv._link_busca("youtube", "chaves").startswith(
        "https://www.youtube.com/results?search_query=chaves")
    assert "q=dark" in tv._link_busca("netflix", "dark")
    assert tv._link_busca("spotify", "x") is None


def test_canais_mapeados_globo_e_record():
    assert tv.CANAIS == {"globo": "12", "record": "27"}


# ─── Comandos sem conexão (erros amigáveis, sem rede) ────────────────────

def test_tecla_sem_tv_conectada_da_erro_amigavel(tv_isolada):
    resultado = tv.enviar_tecla("power")
    assert resultado.startswith("ERRO")
    assert "nenhuma TV conectada" in resultado


def test_tecla_desconhecida_sem_conexao_reporta_antes(tv_isolada):
    assert tv.enviar_tecla("chaveta_marciana").startswith("ERRO")


def test_canal_sem_tv_conectada_da_erro_amigavel(tv_isolada):
    assert tv.sintonizar_canal("12").startswith("ERRO")


def test_status_sem_nada_salvo(tv_isolada):
    texto = tv.status_tv()
    assert "Nenhuma TV salva" in texto


def test_salvar_token_do_companion_na_tv_ativa(tv_isolada, monkeypatch):
    dispositivo = tv.salvar_dispositivo("TV Sala", "192.168.0.20")
    tv._dispositivo_ativo.update(dispositivo)
    token = "a" * 48
    chamadas = []

    def validar(dispositivo_recebido, token_recebido, method, path, body=None):
        chamadas.append((dispositivo_recebido["id"], token_recebido, method, path, body))
        return {"ok": True, "service": "Emily TV Companion", "version": 10}, "192.168.0.20"

    monkeypatch.setattr(tv, "_companion_request_para", validar)
    resultado = tv.salvar_token_companion(token)
    assert resultado["ok"] is True
    assert tv.listar_dispositivos()[0]["companion_token"] == token
    assert chamadas == [(dispositivo["id"], token, "GET", "/v1/health", None)]


def test_salvar_token_normaliza_espacos_e_maiusculas(tv_isolada, monkeypatch):
    dispositivo = tv.salvar_dispositivo("TV Sala", "192.168.0.20")
    tv._dispositivo_ativo.update(dispositivo)
    token = "ABCDEF12" * 6
    recebido = {}

    def validar(_dispositivo, token_recebido, _method, _path, _body=None):
        recebido["token"] = token_recebido
        return {"ok": True, "service": "Emily TV Companion"}, "192.168.0.20"

    monkeypatch.setattr(tv, "_companion_request_para", validar)
    resultado = tv.salvar_token_companion("  ".join(
        token[i:i + 8] for i in range(0, len(token), 8)))

    assert resultado["ok"] is True
    assert recebido["token"] == token.lower()
    assert tv.listar_dispositivos()[0]["companion_token"] == token.lower()


def test_token_com_caractere_nao_hexadecimal_e_recusado_sem_rede(tv_isolada, monkeypatch):
    dispositivo = tv.salvar_dispositivo("TV Sala", "192.168.0.20")
    dispositivo["companion_token"] = "b" * 48
    tv._escrever_catalogo([dispositivo])
    tv._dispositivo_ativo.update(dispositivo)
    chamado = False

    def nao_deveria_chamar(*_args, **_kwargs):
        nonlocal chamado
        chamado = True
        raise AssertionError("token malformado não deve chegar à rede")

    monkeypatch.setattr(tv, "_companion_request_para", nao_deveria_chamar)
    resultado = tv.salvar_token_companion("a" * 20 + "t" + "a" * 27)

    assert resultado["ok"] is False
    assert "48 caracteres hexadecimais" in resultado["mensagem"]
    assert chamado is False
    assert tv.listar_dispositivos()[0]["companion_token"] == "b" * 48


def test_token_recusado_na_tv_nao_substitui_credencial_anterior(tv_isolada, monkeypatch):
    dispositivo = tv.salvar_dispositivo("TV Sala", "192.168.0.20")
    dispositivo["companion_token"] = "b" * 48
    tv._escrever_catalogo([dispositivo])
    tv._dispositivo_ativo.update(dispositivo)

    def recusar(*_args, **_kwargs):
        raise tv.CompanionAuthError("unauthorized")

    monkeypatch.setattr(tv, "_companion_request_para", recusar)
    resultado = tv.salvar_token_companion("a" * 48)

    assert resultado["ok"] is False
    assert "recusou esse token" in resultado["mensagem"]
    assert tv.listar_dispositivos()[0]["companion_token"] == "b" * 48


def test_token_so_e_salvo_depois_de_autenticar_em_ip_descoberto(tv_isolada, monkeypatch):
    dispositivo = tv.salvar_dispositivo("TV Sala", "192.168.0.20")
    tv._dispositivo_ativo.update(dispositivo)
    monkeypatch.setattr(
        tv, "_companion_request_para",
        lambda *_args, **_kwargs: (
            {"ok": True, "service": "Emily TV Companion"}, "192.168.0.99"),
    )

    resultado = tv.salvar_token_companion("c" * 48)
    salvo = tv.listar_dispositivos()[0]

    assert resultado["ok"] is True
    assert salvo["companion_token"] == "c" * 48
    assert salvo["ip"] == "192.168.0.99"


def test_listar_apps_companion_sem_token_da_erro_amigavel(tv_isolada):
    dispositivo = tv.salvar_dispositivo("TV Sala", "192.168.0.20")
    tv._dispositivo_ativo.update(dispositivo)
    resultado = tv.listar_apps_instalados()
    assert resultado["ok"] is False
    assert "token" in resultado["mensagem"].lower()


def test_abrir_app_instalado_codifica_nome(monkeypatch):
    recebido = {}

    def fake_request(method, path):
        recebido.update(method=method, path=path)
        return {"ok": True, "app": {"name": "Prime Video"}}

    monkeypatch.setattr(tv, "_companion_request", fake_request)
    resultado = tv.abrir_app_instalado("Prime Video")
    assert resultado["ok"] is True
    assert recebido == {"method": "POST", "path": "/v1/apps/Prime%20Video/launch"}


def test_status_com_dispositivo_salvo(tv_isolada):
    tv.salvar_dispositivo("TV da Sala", "192.168.0.15")
    texto = tv.status_tv()
    assert "TV da Sala" in texto and "192.168.0.15" in texto


def test_parear_iniciar_com_id_fantasma_nao_abre_socket(tv_isolada):
    r = tv.iniciar_pareamento("id-fantasma")
    assert r["ok"] is False
    assert "não encontrado" in r["mensagem"]


def test_concluir_pareamento_sem_sessao(tv_isolada):
    r = tv.concluir_pareamento("123456")
    assert r["ok"] is False and "nenhum pareamento" in r["mensagem"].lower()


# ─── Ferramentas registradas na Emily ────────────────────────────────────

FERRAMENTAS_TV = {
    "ver_tvs",
    "salvar_tv",
    "conectar_tv",
    "comando_tv",
    "abrir_app_tv",
    "buscar_na_tv",
    "status_da_tv",
    "compartilhar_tela_pc_tv",
    "parar_compartilhamento_tv",
    "configurar_emily_tv",
}


def test_ferramentas_tv_no_catalogo():
    assert FERRAMENTAS_TV <= set(ferramentas.CATALOGO)
    # comandos de TV são ações: não marcados como somente leitura
    for nome in ("comando_tv", "abrir_app_tv", "buscar_na_tv", "conectar_tv",
                 "compartilhar_tela_pc_tv", "parar_compartilhamento_tv",
                 "configurar_emily_tv"):
        assert ferramentas.CATALOGO[nome].somente_leitura is False
    # leituras são marcadas
    assert ferramentas.CATALOGO["ver_tvs"].somente_leitura is True
    assert ferramentas.CATALOGO["status_da_tv"].somente_leitura is True


def test_esquemas_das_ferramentas_tv_validos():
    esquemas = {e["function"]["name"]: e for e in ferramentas.esquemas(["geral"])}
    for nome in FERRAMENTAS_TV:
        fn = esquemas[nome]["function"]
        assert fn["description"].strip()
        assert fn["parameters"]["type"] == "object"
    assert esquemas["salvar_tv"]["function"]["parameters"]["required"] == ["nome", "ip"]
    assert esquemas["comando_tv"]["function"]["parameters"]["required"] == ["acao"]


def test_ver_tvs_sem_dispositivos(tv_isolada, monkeypatch):
    monkeypatch.setattr("ferramentas._importar_tv", lambda: tv)
    r = ferramentas.executar("ver_tvs", {})
    assert "Nenhuma TV salva" in r


def test_salvar_tv_via_ferramenta(tv_isolada, monkeypatch):
    monkeypatch.setattr("ferramentas._importar_tv", lambda: tv)
    r = ferramentas.executar("salvar_tv", {"nome": "Quarto", "ip": "10.1.1.9"})
    assert "Quarto" in r and "10.1.1.9" in r


def test_configurar_emily_tv_registra_mudanca_real(tv_isolada, monkeypatch):
    dispositivo = tv.salvar_dispositivo("TV Sala", "192.168.0.20")
    tv._dispositivo_ativo.update(dispositivo)
    monkeypatch.setattr("ferramentas._importar_tv", lambda: tv)
    monkeypatch.setattr(
        tv, "_companion_request_para",
        lambda *_args, **_kwargs: (
            {"ok": True, "service": "Emily TV Companion"}, "192.168.0.20"),
    )
    token = "a" * 48

    resultado = ferramentas.executar_estruturado(
        "configurar_emily_tv", {"token": token},
        contexto={"pedido_explicito": True, "dono_confirmado": True},
    )

    assert resultado.ok is True
    assert resultado.mudou is True
    assert tv.listar_dispositivos()[0]["companion_token"] == token


def test_configurar_emily_tv_nao_marca_mudanca_quando_tv_recusa_token(
        tv_isolada, monkeypatch):
    dispositivo = tv.salvar_dispositivo("TV Sala", "192.168.0.20")
    tv._dispositivo_ativo.update(dispositivo)
    monkeypatch.setattr("ferramentas._importar_tv", lambda: tv)
    monkeypatch.setattr(
        tv, "_companion_request_para",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            tv.CompanionAuthError("unauthorized")),
    )

    resultado = ferramentas.executar_estruturado(
        "configurar_emily_tv", {"token": "a" * 48},
        contexto={"pedido_explicito": True, "dono_confirmado": True},
    )

    assert resultado.ok is False
    assert resultado.mudou is False
    assert "recusou esse token" in resultado.texto


def test_salvar_tv_ip_invalido_recusa(tv_isolada, monkeypatch):
    monkeypatch.setattr("ferramentas._importar_tv", lambda: tv)
    r = ferramentas.executar_estruturado("salvar_tv", {"nome": "X", "ip": "999.1.1"})
    assert r.ok is False


def test_comando_tv_sem_conexao_recusa_com_instrucao(tv_isolada, monkeypatch):
    tv.salvar_dispositivo("TV da Sala", "192.168.0.15")
    monkeypatch.setattr("ferramentas._importar_tv", lambda: tv)
    r = ferramentas.executar_estruturado("comando_tv", {"acao": "power"})
    assert r.ok is False
    assert "nenhuma TV conectada" in r.texto


def test_status_da_tv_via_ferramenta(tv_isolada, monkeypatch):
    tv.salvar_dispositivo("TV da Sala", "192.168.0.15")
    monkeypatch.setattr("ferramentas._importar_tv", lambda: tv)
    r = ferramentas.executar_estruturado("status_da_tv", {})
    assert "TV da Sala" in r.texto
    assert ferramentas.CATALOGO["status_da_tv"].somente_leitura is True


def test_compartilhar_tela_pc_exige_tv_ativa(tv_isolada):
    resultado = tv.compartilhar_tela_pc()
    assert resultado["ok"] is False
    assert "nenhuma TV ativa" in resultado["mensagem"]


def test_compartilhar_tela_pc_negocia_capacidades_e_servico_local(tv_isolada, monkeypatch):
    dispositivo = tv.salvar_dispositivo("TV Sala", "192.168.0.20")
    dispositivo["companion_token"] = "a" * 48
    tv._dispositivo_ativo.update(dispositivo)
    chamadas = []

    def companion(method, path, body=None):
        chamadas.append(("tv", method, path, body))
        return {"ok": True, "protocol_version": 1}

    def tela(method, path, body=None):
        chamadas.append(("pc", method, path, body))
        return {"ok": True, "preset": "720p60", "encoder": "openh264enc"}

    monkeypatch.setattr(tv, "_companion_request", companion)
    monkeypatch.setattr(tv, "_tela_pc_request", tela)
    resultado = tv.compartilhar_tela_pc("720p60", monitor=2, audio=False)
    assert resultado["ok"] is True
    assert "openh264enc" in resultado["mensagem"]
    assert chamadas[0] == ("tv", "GET", "/v1/screen/capabilities", None)
    assert chamadas[1][0:3] == ("pc", "POST", "/tela/webrtc/start")
    assert chamadas[1][3] == {
        "tv_ip": "192.168.0.20", "tv_token": "a" * 48,
        "preset": "720p60", "monitor": 2, "audio": False,
    }


def test_parar_compartilhamento_chama_servico_local(monkeypatch):
    recebido = {}
    monkeypatch.setattr(tv, "_tela_pc_request", lambda method, path, body=None: (
        recebido.update(method=method, path=path, body=body) or {"ok": True}))
    resultado = tv.parar_compartilhamento_tela()
    assert resultado["ok"] is True
    assert recebido == {"method": "POST", "path": "/tela/webrtc/stop", "body": None}


def test_ferramenta_compartilhar_tela_pc(monkeypatch):
    class FakeTv:
        @staticmethod
        def compartilhar_tela_pc(preset, monitor, audio):
            assert (preset, monitor, audio) == ("1080p30", 1, True)
            return {"ok": True, "mensagem": "Tela compartilhada."}

    monkeypatch.setattr("ferramentas._importar_tv", lambda: FakeTv)
    r = ferramentas.executar_estruturado("compartilhar_tela_pc_tv", {
        "preset": "1080p30", "monitor": 1, "audio": True,
    })
    assert r.ok is True



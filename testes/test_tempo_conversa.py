"""Horário de cada fala e aviso de pausa longa, no PC, na memória e no Discord."""
import time
from datetime import datetime, timedelta, timezone

import pytest

import tempo_conversa as tc

BH = timezone(timedelta(hours=-3))


def ts(dia, hora, minuto, mes=10):
    return datetime(2026, mes, dia, hora, minuto, tzinfo=BH).timestamp()


def test_rotulos_hoje_ontem_e_antigo():
    agora = ts(13, 15, 0)
    assert tc.rotulo(ts(13, 14, 5), agora) == "14:05"
    assert tc.rotulo(ts(12, 22, 40), agora) == "ontem 22:40"
    assert tc.rotulo(ts(7, 9, 10), agora) == "qua 07/10 09:10"


def test_virada_do_dia_usa_o_fuso_de_bh_e_nao_o_da_maquina():
    agora = ts(13, 0, 30)                 # 00:30 em BH = 03:30 UTC
    assert tc.rotulo(ts(12, 23, 50), agora) == "ontem 23:50"


@pytest.mark.parametrize("seg,texto", [(60, "menos de 2 min"), (25 * 60, "25 min"), (3 * 3600, "3 h"),
                                       (90 * 60, "1,5 h"), (12 * 3600, "12 h"), (2 * 86400, "2 dias"),
                                       (86400, "1 dia")])
def test_duracao(seg, texto):
    assert tc.duracao(seg) == texto


def test_conversa_em_andamento_nao_gera_aviso():
    agora = ts(13, 15, 0)
    assert tc.bloco_continuidade(ts(13, 14, 40), agora) == ""
    assert tc.bloco_continuidade(0, agora) == ""


def test_pausa_longa_gera_aviso_discreto():
    agora = ts(13, 15, 0)
    bloco = tc.bloco_continuidade(ts(13, 9, 0), agora)
    assert "09:00" in bloco and "faz 6 h" in bloco
    assert "NÃO trate a mensagem de agora como continuação direta" in bloco
    assert "não cite o horário" in bloco       # contexto interno, sem comentar à toa


def test_limite_e_de_30_minutos():
    agora = ts(13, 15, 0)
    assert tc.bloco_continuidade(agora - 29 * 60, agora) == ""
    assert tc.bloco_continuidade(agora - 31 * 60, agora) != ""


# ── Memória unificada ─────────────────────────────────────────────

def _contexto(eventos):
    from memoria_unificada.recuperacao import ContextoMemoria
    return ContextoMemoria(trocas=tuple(eventos))


def _evento(papel, texto, quando):
    from memoria_unificada.modelos import EventoMemoria
    return EventoMemoria(owner_user_id="vitor", papel=papel, texto=texto, canal="pc", timestamp=quando)


def test_memoria_mostra_horario_nas_trocas_e_avisa_a_pausa():
    velho = time.time() - 6 * 3600
    prompt = _contexto([_evento("user", "me lembra de ligar pra Maria", velho),
                        _evento("assistant", "lembro sim", velho + 5)]).para_prompt()
    assert "CONVERSA RECENTE" in prompt and "Usuário: me lembra de ligar pra Maria" in prompt
    assert prompt.count("[") >= 2                         # horário em cada troca
    assert "NÃO trate a mensagem de agora como continuação direta" in prompt


def test_memoria_recente_nao_avisa_pausa():
    agora = time.time()
    prompt = _contexto([_evento("user", "oi", agora - 60)]).para_prompt()
    assert "ÚLTIMA CONVERSA" not in prompt and "NÃO trate" not in prompt


def test_memoria_vazia_continua_vazia():
    assert _contexto([]).para_prompt() == ""


# ── Discord ───────────────────────────────────────────────────────

def test_janela_do_discord_mostra_horario_e_marca_pausa(monkeypatch):
    import discord_bot as d
    base = ts(13, 9, 0)
    monkeypatch.setattr(d, "_historico_janela", {7: [
        {"nome": "Ana", "texto": "bom dia", "quando": base},
        {"nome": "Emily", "texto": "bom dia!", "eh_emily": True, "quando": base + 30},
        {"nome": "Ana", "texto": "voltei", "quando": base + 5 * 3600},
    ]})
    texto = d._formatar_janela(7)
    linhas = texto.splitlines()
    assert linhas[0].startswith("[") and "Ana: bom dia" in linhas[0]
    assert "--- 5 h depois ---" in texto
    assert linhas[-1].endswith("Ana: voltei")


def test_janela_sem_horario_continua_igual(monkeypatch):
    import discord_bot as d
    monkeypatch.setattr(d, "_historico_janela", {8: [{"nome": "Ana", "texto": "oi"}]})
    assert d._formatar_janela(8) == "Ana: oi"


def test_quando_da_mensagem_usa_o_instante_do_envio():
    import discord_bot as d
    msg = type("M", (), {"created_at": datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)})()
    assert d._quando_da_mensagem(msg) == datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc).timestamp()
    assert abs(d._quando_da_mensagem(object()) - time.time()) < 5


def test_dm_mostra_horario_e_pausa(tmp_path, monkeypatch):
    import historico_dm as h
    monkeypatch.setattr(h, "ARQUIVO", tmp_path / "dm.json")
    monkeypatch.setattr(h, "_cache", None, raising=False)
    h.adicionar(42, "Ana", "pessoa", "oi")
    dados = h.carregar()
    dados["usuarios"]["42"]["mensagens"][0]["quando"] = time.time() - 4 * 3600
    h._salvar()
    texto = h.formatar(42)
    assert texto.startswith("[") and "Ana: oi" in texto
    assert "depois (agora) ---" in texto


def test_discord_na_oracle_nao_depende_do_callback_do_desktop():
    """O desktop registra _callback_texto; a Oracle nunca. A trava no on_message calava a
    nuvem inteira (menção, reply e conversa espontânea), que não dependem dele."""
    import inspect
    import discord_bot as d
    fonte = inspect.getsource(d.on_message)
    antes_do_comando = fonte.split("COMANDO DIRETO")[0]
    assert "if not _callback_texto" not in antes_do_comando
    assert "if not _callback_texto" in fonte.split("COMANDO DIRETO")[1]   # só o prefixo exige o desktop

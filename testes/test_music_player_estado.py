"""Estado persistido do player nunca deve quebrar o boot da interface."""

import json

import music_player


def _usar_arquivo(tmp_path, monkeypatch):
    arquivo = tmp_path / "playlist.json"
    monkeypatch.setattr(music_player, "ARQUIVO", arquivo)
    monkeypatch.setattr(music_player, "_cache", None)
    return arquivo


def test_estado_invalido_e_normalizado(tmp_path, monkeypatch):
    arquivo = _usar_arquivo(tmp_path, monkeypatch)
    arquivo.write_text(json.dumps({
        "playlists": {"default": [{"video_id": "aaaaaaaaaaa"}]},
        "playlist_ativa": "default",
        "player_estado": {
            "volume": 999, "loop": 17, "shuffle": "sim",
            "playlist": "inexistente", "indice": 90,
            "video_id": "id ruim", "posicao": -40,
        },
    }), encoding="utf-8")

    assert music_player.estado() == {
        "volume": 100, "loop": 1, "shuffle": False,
        "playlist": "default", "indice": -1,
        "video_id": None, "posicao": 0.0,
    }


def test_salvar_estado_ignora_campos_desconhecidos(tmp_path, monkeypatch):
    arquivo = _usar_arquivo(tmp_path, monkeypatch)

    assert music_player.salvar_estado(
        volume=-5, loop=2, shuffle=False, posicao=12.5,
        video_id="bbbbbbbbbbb", campo_perigoso="não persiste",
    )

    salvo = json.loads(arquivo.read_text(encoding="utf-8"))["player_estado"]
    assert salvo["volume"] == 0
    assert salvo["loop"] == 2
    assert salvo["posicao"] == 12.5
    assert salvo["video_id"] == "bbbbbbbbbbb"
    assert "campo_perigoso" not in salvo


def test_playlist_corrompida_nao_quebra_normalizacao(tmp_path, monkeypatch):
    arquivo = _usar_arquivo(tmp_path, monkeypatch)
    arquivo.write_text(json.dumps({
        "playlists": {"default": 42},
        "player_estado": {"playlist": "default", "indice": 8},
    }), encoding="utf-8")

    assert music_player.estado()["indice"] == -1
    assert music_player.listar() == []
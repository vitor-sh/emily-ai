from pathlib import Path


def _modulo():
    import importlib.util

    caminho = (
        Path(__file__).resolve().parents[1]
        / "hollow_knight_emily/scripts/instalar_modding_api.py"
    )
    spec = importlib.util.spec_from_file_location("instalador_hk", caminho)
    modulo = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(modulo)
    return modulo


def test_detector_nao_confunde_o_proprio_script_com_o_jogo(monkeypatch, tmp_path):
    modulo = _modulo()
    proc = tmp_path / "proc"
    (proc / "123").mkdir(parents=True)
    (proc / "123/cmdline").write_bytes(
        b"python\0hollow_knight_emily/scripts/instalar_modding_api.py\0instalar\0"
    )
    monkeypatch.setattr(modulo, "Path", lambda valor: proc if valor == "/proc" else Path(valor))
    assert modulo._processos_hollow_knight() == []


def test_detector_reconhece_executavel_do_jogo(monkeypatch, tmp_path):
    modulo = _modulo()
    proc = tmp_path / "proc"
    (proc / "456").mkdir(parents=True)
    (proc / "456/cmdline").write_bytes(
        b"wine64\0/home/vitor/Hollow Knight/hollow_knight.exe\0"
    )
    monkeypatch.setattr(modulo, "Path", lambda valor: proc if valor == "/proc" else Path(valor))
    encontrados = modulo._processos_hollow_knight()
    assert encontrados and encontrados[0]["pid"] == 456
"""O catálogo Cloud é realmente carregado sob demanda."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_dominio_nuvem_e_lazy_e_nao_polui_catalogo_padrao(tmp_path):
    raiz = Path(__file__).resolve().parents[1]
    codigo = """
import sys
import ferramentas
assert 'emily_cloud' not in sys.modules
assert not any(e['function']['name'].startswith('nuvem_') for e in ferramentas.esquemas_padrao())
schemas = ferramentas.esquemas_com_dominios(['nuvem'])
assert 'emily_cloud' in sys.modules
assert sum(e['function']['name'].startswith('nuvem_') for e in schemas) == 19
assert len(ferramentas.esquemas(grupos=['nuvem'])) == 19
assert len(ferramentas.esquemas(grupos=['nuvem'])) == 19
"""
    env = os.environ.copy()
    env["EMILY_CLOUD_DIR"] = str(tmp_path / "catalogo")
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=raiz, env=env,
        text=True, capture_output=True, timeout=30,
    )
    assert resultado.returncode == 0, resultado.stderr or resultado.stdout


def test_interface_cloud_tem_migracao_preview_de_video_e_polling_sem_piscada():
    raiz = Path(__file__).resolve().parents[1]
    js = (raiz / "web" / "cloud.js").read_text(encoding="utf-8")
    css = (raiz / "web" / "cloud.css").read_text(encoding="utf-8")
    ponte = (raiz / "interface_web.py").read_text(encoding="utf-8")
    core = (raiz / "emily_cloud" / "core.py").read_text(encoding="utf-8")

    assert "id=\"cloud-storage\"" in js
    assert "cloud_escolher_armazenamento" in ponte
    assert "cloud_migrar_armazenamento" in ponte
    assert "cloudAssinatura" in js and "cloudCarregar(true)" in js
    assert "if (silencioso) return;" in js
    assert ".cloud-conteudo.carregando{pointer-events:none}" in css
    assert ".cloud-conteudo.carregando{opacity:" not in css
    assert "mime.startswith(\"video/\")" in core
    assert "agendar_previews_pendentes" in core
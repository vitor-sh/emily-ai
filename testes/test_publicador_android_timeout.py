"""Uma queda de rede não pode deixar o publicador esperando SSH indefinidamente."""
import importlib.util
import json
from pathlib import Path
import subprocess
import pytest


def test_publicador_limita_ssh_e_nao_inicia_upload_apos_desconexao(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('publicador_android_probe', Path(__file__).parents[1]/'EmilyAPP2/publicar_oracle.py')
    p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
    apk=tmp_path/'app.apk';apk.write_bytes(b'APK de teste')
    (tmp_path/'output-metadata.json').write_text(json.dumps({'elements':[{'versionCode':55}]}))
    private=tmp_path/'.config/emily-cloud-oracle';private.mkdir(parents=True)
    (private/'relay-upload-key.json').write_text('{"key":"test-only"}')
    monkeypatch.setattr(p.Path,'home',lambda:tmp_path)
    def disconnect(args, **kw):
        assert 'ConnectTimeout=10' in args
        assert 'ServerAliveInterval=10' in args
        assert 'ServerAliveCountMax=3' in args
        assert kw['timeout']==120
        raise subprocess.TimeoutExpired(args,120)
    monkeypatch.setattr(p.subprocess,'run',disconnect)
    monkeypatch.setattr(p.requests,'post',lambda *a,**k:pytest.fail('Upload não pode começar após falha do SSH'))
    with pytest.raises(subprocess.TimeoutExpired):p.publicar_apk(apk)

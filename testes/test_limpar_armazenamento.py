import hashlib
import json
import os
from pathlib import Path
import pytest
import limpar_armazenamento as c


def test_retention_keeps_current_previous_future_and_symlinks(tmp_path):
    for v in [1,2,3,4,5]: (tmp_path/f'emily-{v}.apk').touch()
    (tmp_path/'emily-0.apk').symlink_to(tmp_path/'emily-1.apk')
    assert {p.name for p in c.retention(tmp_path,r'emily-(\d+)\.apk',4)}=={'emily-1.apk','emily-2.apk'}


def test_manifest_validation_refuses_invalid_current(tmp_path):
    folder=tmp_path/'.local/share/emily/android-updates';folder.mkdir(parents=True)
    (folder/'latest.json').write_text(json.dumps({'version_code':3,'size':3,'sha256':'wrong'}))
    (folder/'emily-3.apk').write_bytes(b'abc')
    (folder/'emily-1.apk').touch()
    with pytest.raises(ValueError):c.build_candidates(tmp_path,tmp_path)
    assert (folder/'emily-1.apk').exists()


def test_valid_manifest_only_plans_old_releases(tmp_path):
    folder=tmp_path/'.local/share/emily/android-updates';folder.mkdir(parents=True)
    for v in [1,2,3]: (folder/f'emily-{v}.apk').write_bytes(b'abc')
    (folder/'latest.json').write_text(json.dumps({'version_code':3,'size':3,'sha256':hashlib.sha256(b'abc').hexdigest()}))
    assert c.build_candidates(tmp_path,tmp_path)==[folder/'emily-1.apk']


def test_runtime_cleanup_preserves_active_recent_and_primary(tmp_path):
    folder=tmp_path/'.cache/codex-runtimes';folder.mkdir(parents=True)
    for name in ['codex-runtime-install-old','codex-runtime-install-active','codex-runtime-install-new','codex-primary-runtime']:
        p=folder/name;p.mkdir();os.utime(p,(0,0))
    now=10*86400;os.utime(folder/'codex-runtime-install-new',(now,now))
    result=c.runtime_candidates(tmp_path,now=now,usage=str(folder/'codex-runtime-install-active/bin/node'))
    assert result==[folder/'codex-runtime-install-old']


def test_dry_run_keeps_files_and_apply_removes_only_candidates(tmp_path,monkeypatch):
    old=tmp_path/'old.apk';old.touch();current=tmp_path/'current.apk';current.touch()
    monkeypatch.setattr(c,'build_candidates',lambda:[old])
    assert c.clean()==[str(old)] and old.exists()
    c.clean(apply=True)
    assert not old.exists() and current.exists()


def test_unknown_process_never_removes_extracted_runtime(tmp_path,monkeypatch):
    folder=tmp_path/'.cache/codex-runtimes';folder.mkdir(parents=True)
    empty=folder/'codex-runtime-install-empty';extracted=folder/'codex-runtime-install-extracted'
    for p in [empty,extracted]:
        (p/'payload').mkdir(parents=True);(p/'node-runtime.tar.xz').touch()
    (extracted/'payload/node').touch()
    for p in [empty,extracted]:
        for item in [p,*p.iterdir()]:os.utime(item,(0,0))
    monkeypatch.setattr(c,'active_paths',lambda:(_ for _ in ()).throw(RuntimeError('inacessível')))
    assert c.runtime_candidates(tmp_path,now=10*86400)==[empty]

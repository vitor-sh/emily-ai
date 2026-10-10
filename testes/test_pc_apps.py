import subprocess
import threading
from pathlib import Path

from pc_apps import PCApps
import pc_apps_admin as admin
import pytest


def appimage(tmp_path, name='Teste', suffix='one'):
    image=tmp_path/(suffix+'.AppImage'); image.write_text('aplicativo temporário')
    desktop=tmp_path/(suffix+'.desktop'); desktop.write_text('atalho temporário')
    return dict(id='appimage:'+str(image),tipo='appimage',alvo=str(image),nome=name,lancador=str(desktop))


def client(tmp_path, apps):
    pc=PCApps(tmp_path)
    pc.inventory=lambda refresh=False:[a for a in apps if Path(a['alvo']).exists()]
    return pc


def request(name, key='request-123456', **kwargs):
    return dict(nome=name,request_id=key,**kwargs)


def test_exact_removal_unrestricted_is_verified_and_idempotent(tmp_path):
    app=appimage(tmp_path)
    data=tmp_path/'dados-pessoais'; data.write_text('save')
    pc=client(tmp_path,[app])
    args=request('Teste')
    first=pc.remove(args,'turno',True)
    done=pc.status(first['job_id'],wait=2)
    assert done['ok'] and done['concluido'] and done['estado']=='concluido'
    assert not Path(app['alvo']).exists() and data.read_text()=='save'
    assert pc.remove(args,'turno',True)['job_id']==first['job_id']
    assert not pc.remove(request('outro'),'turno',True)['ok']


def test_typo_and_duplicate_require_choice_never_delete(tmp_path):
    a=appimage(tmp_path,'Claude','one');b=appimage(tmp_path,'Claude','two')
    pc=client(tmp_path,[a,b])
    typo=pc.remove(request('Claudee'),'t',True)
    assert typo['precisa_escolha'] and len(typo['candidatos'])==2
    same=pc.remove(request('Claude'),'t',True)
    assert same['precisa_escolha'] and not pc.jobs
    assert Path(a['alvo']).exists() and Path(b['alvo']).exists()
    selected=pc.remove(request('',id=b['id']),'next-turn',True)
    assert pc.status(selected['job_id'],wait=2)['ok']
    assert Path(a['alvo']).exists() and not Path(b['alvo']).exists()


def test_restricted_mode_confirmation_new_turn_and_retry(tmp_path):
    a=appimage(tmp_path);pc=client(tmp_path,[a])
    result=pc.remove(request('Teste'),'t1',False)
    assert result['requer_confirmacao'] and Path(a['alvo']).exists()
    args=dict(confirmation_id=result['confirmation_id'],confirmar=True)
    assert not pc.confirm(args,'t1')['ok']
    first=pc.confirm(args,'t2');done=pc.status(first['job_id'],wait=2)
    assert done['ok'] and not Path(a['alvo']).exists()
    assert pc.confirm(args,'t2')['job_id']==first['job_id']
    assert not pc.confirm(args,'t3')['ok']


def test_long_job_returns_immediately_and_status_waits_without_new_execution(tmp_path):
    a=dict(id='rpm:test',tipo='rpm',alvo='test',nome='Teste')
    started=threading.Event();release=threading.Event();calls=[]
    def runner(command,**kwargs):
        calls.append(command);started.set();assert release.wait(2)
        return '{"ok":true}'
    pc=PCApps(tmp_path,runner)
    pc.inventory=lambda refresh=False:[] if release.is_set() else [a]
    initial=pc.remove(request('Teste'),'t',True)
    assert initial['estado']=='executando' and started.wait(1)
    release.set()
    assert pc.status(initial['job_id'],wait=2)['concluido']
    assert len(calls)==1


def test_helper_failure_never_claims_success(tmp_path):
    a=dict(id='rpm:test',tipo='rpm',alvo='test',nome='Teste')
    def runner(*a,**kw):raise RuntimeError('Permissão recusada')
    pc=PCApps(tmp_path,runner);pc.inventory=lambda refresh=False:[a]
    r=pc.remove(request('Teste'),'t',True)
    done=pc.status(r['job_id'],wait=2)
    assert done['concluido'] and not done['ok'] and 'Permissão recusada' in done['mensagem']


def test_steam_removes_only_game_and_manifest_preserves_saves_and_runtimes(tmp_path, monkeypatch):
    steamapps=tmp_path/'steamapps';game=steamapps/'common'/'Jogo';game.mkdir(parents=True)
    (game/'game.exe').write_text('jogo')
    manifest=steamapps/'appmanifest_123.acf';manifest.write_text('"appid" "123"\n"installdir" "Jogo"')
    save=steamapps/'compatdata'/'123';save.mkdir(parents=True);(save/'save').write_text('save')
    runtime=steamapps/'common'/'Proton';runtime.mkdir()
    pc=PCApps(tmp_path);monkeypatch.setattr(pc,'_stop_steam',lambda:None)
    pc._remove_steam(dict(pasta=str(game),manifesto=str(manifest),appid='123'))
    assert not game.exists() and not manifest.exists()
    assert (save/'save').exists() and runtime.exists()


def test_steam_rejects_symlink_outside_library(tmp_path,monkeypatch):
    outside=tmp_path/'personal';outside.mkdir();(outside/'data').write_text('keep')
    steamapps=tmp_path/'steamapps';(steamapps/'common').mkdir(parents=True)
    game=steamapps/'common'/'Jogo';game.symlink_to(outside,target_is_directory=True)
    manifest=steamapps/'appmanifest_123.acf';manifest.write_text('"appid" "123"\n"installdir" "Jogo"')
    pc=PCApps(tmp_path);monkeypatch.setattr(pc,'_stop_steam',lambda:None)
    with pytest.raises(RuntimeError):pc._remove_steam(dict(pasta=str(game),manifesto=str(manifest),appid='123'))
    assert (outside/'data').exists()


@pytest.mark.parametrize('package',['systemd','kernel-core','sudo','polkit','plasma-desktop','python3','dnf5','../etc','x;id','--all'])
def test_admin_rejects_core_packages_and_command_injection(package):
    with pytest.raises(ValueError):admin.rpm_transaction(package)


def test_admin_flatpak_rejects_runtime_and_keeps_user_data(monkeypatch):
    calls=[]
    def run(command):
        calls.append(command)
        return subprocess.CompletedProcess(command,0,'org.example.App\n','')
    monkeypatch.setattr(admin,'run',run)
    with pytest.raises(ValueError):admin.execute('flatpak-system','org.example.Platform')
    admin.execute('flatpak-system','org.example.App')
    assert calls[-1]==['/usr/bin/flatpak','uninstall','--system','--noninteractive','--','org.example.App']
    assert not any('--delete-data' in c for c in calls)


def test_dnf_refuses_transaction_that_removes_any_other_package(monkeypatch):
    import sys
    from types import SimpleNamespace as S
    called=[]
    package=lambda name:S(get_package=lambda:S(get_name=lambda:name),get_action=lambda:5)
    transaction=S(get_problems=lambda:0,get_transaction_packages=lambda:[package('testapp'),package('systemd')],run=lambda:called.append('run'))
    base=S(load_config=lambda:None,setup=lambda:None,
           get_config=lambda:S(get_clean_requirements_on_remove_option=lambda:S(set=lambda value:None)),
           get_repo_sack=lambda:S(load_repos=lambda kind:None))
    dnf=S(base=S(Base=lambda:base,Goal=lambda b:S(add_remove=lambda p:None,resolve=lambda:transaction)),
          repo=S(Repo=S(Type_SYSTEM=1)),transaction=S(TransactionItemAction_REMOVE=5))
    monkeypatch.setitem(sys.modules,'libdnf5',dnf)
    monkeypatch.setattr(admin,'run',lambda command:subprocess.CompletedProcess(command,0,'/usr/share/applications/testapp.desktop\n',''))
    with pytest.raises(ValueError,match='outros pacotes'):admin.rpm_transaction('testapp')
    assert called==[]


def test_steam_refuses_shared_installation_directory(tmp_path,monkeypatch):
    steamapps=tmp_path/'steamapps';game=steamapps/'common'/'Jogo';game.mkdir(parents=True)
    a=steamapps/'appmanifest_123.acf';a.write_text('"appid" "123"\n"installdir" "Jogo"')
    b=steamapps/'appmanifest_456.acf';b.write_text('"appid" "456"\n"installdir" "Jogo"')
    pc=PCApps(tmp_path);monkeypatch.setattr(pc,'_stop_steam',lambda:None)
    with pytest.raises(RuntimeError,match='compartilhada'):pc._remove_steam(dict(pasta=str(game),manifesto=str(a),appid='123'))
    assert game.exists() and a.exists() and b.exists()


def test_admin_execution_uses_isolated_worker_and_fixed_helper():
    from pc_apps import admin_command, ADMIN_HELPER
    command=admin_command('rpm','testapp',preview=True)
    assert command[:2]==['/usr/bin/systemd-run','--user']
    assert '--property=NoNewPrivileges=false' in command
    assert '--property=RuntimeMaxSec=600' in command
    assert command[-5:]==['--disable-internal-agent',ADMIN_HELPER,'rpm','testapp','--preview']
    assert not any(c in command for c in ['/bin/sh','/bin/bash','/usr/bin/python3'])


def test_duplicate_active_target_shares_job_even_across_turns(tmp_path):
    a=dict(id='rpm:test',tipo='rpm',alvo='test',nome='Teste')
    release=threading.Event();calls=[]
    def runner(command,**kwargs):
        calls.append(command);assert release.wait(3);return '{"ok":true}'
    pc=PCApps(tmp_path,runner);pc.inventory=lambda refresh=False:[] if release.is_set() else [a]
    try:
        first=pc.remove(request('Teste'),'turn1',True)
        second=pc.remove(request('Teste',key='request-another'),'turn2',True)
        assert first['job_id']==second['job_id']
    finally:release.set()
    assert pc.status(first['job_id'],wait=2)['ok']
    assert len(calls)==1


def test_invalid_confirmation_does_not_cancel_pending_request(tmp_path):
    a=appimage(tmp_path);pc=client(tmp_path,[a])
    pending=pc.remove(request('Teste'),'t1',False);cid=pending['confirmation_id']
    assert not pc.confirm(dict(confirmation_id=cid,confirmar='sim'),'t2')['ok']
    assert cid in pc.confirmations and Path(a['alvo']).exists()
    result=pc.confirm(dict(confirmation_id=cid,confirmar=True),'t3')
    assert pc.status(result['job_id'],wait=2)['ok']


def test_structured_helper_error_beats_unrelated_stderr(monkeypatch):
    import pc_apps
    monkeypatch.setattr(pc_apps.subprocess,'run',lambda *a,**kw:subprocess.CompletedProcess(a[0],1,
        '{"ok":false,"mensagem":"A remoção afetaria outros pacotes."}','Aviso do DNF'))
    with pytest.raises(pc_apps.RemovalError,match='outros pacotes'):
        pc_apps.output(['test'])


def test_failed_permission_keeps_machine_readable_diagnostic(tmp_path):
    import pc_apps
    a=dict(id='rpm:test',tipo='rpm',alvo='test',nome='Teste')
    def runner(*a,**kw):raise pc_apps.RemovalError('Not authorized','permissao_administrativa')
    pc=PCApps(tmp_path,runner);pc.inventory=lambda refresh=False:[a]
    r=pc.remove(request('Teste'),'t',True);done=pc.status(r['job_id'],wait=2)
    assert done['codigo_erro']=='permissao_administrativa' and not done['ok']


def test_package_manager_jobs_do_not_overlap(tmp_path):
    apps=[dict(id='rpm:'+n,tipo='rpm',alvo=n,nome=n) for n in ('first','second')]
    started=threading.Event();second=threading.Event();release=threading.Event();removed=set()
    def runner(command,**kwargs):
        target=command[-1]
        if target=='first':
            started.set();assert release.wait(3)
        else:second.set()
        removed.add(target)
        return '{"ok":true}'
    pc=PCApps(tmp_path,runner);pc.inventory=lambda refresh=False:[a for a in apps if a['alvo'] not in removed]
    a=pc.remove(request('first'),'one',True);assert started.wait(1)
    try:
        b=pc.remove(request('second',key='request-second'),'two',True)
        assert b['estado']=='executando' and not second.wait(.1)
    finally:release.set()
    assert pc.status(a['job_id'],wait=2)['ok']
    assert pc.status(b['job_id'],wait=2)['ok'] and second.is_set()

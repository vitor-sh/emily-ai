import json
from pathlib import Path
import hashlib
import pytest
import programacao_ambiente as a

@pytest.mark.parametrize('purpose,command',[('teste','node tests/ui.js'),('comando','node -e "require(\'jsdom\')"'),('comando','python -c "import subprocess; subprocess.run([\'node\',\'test.js\'])"')])
def test_node_is_ready_for_commands_and_nested_python(tmp_path,monkeypatch,purpose,command):
    workspace=tmp_path/'workspace';(workspace/'testes').mkdir(parents=True);(workspace/'testes/test_waiting_indicator.js').touch()
    path=tmp_path/'sessions/session/job.json';path.parent.mkdir(parents=True)
    calls=[]
    def npm(argv,cwd,**kwargs):
        calls.append(argv)
        (cwd/'node_modules/jsdom').mkdir(parents=True)
        (cwd/'node_modules/jsdom/package.json').write_text('{}')
    monkeypatch.setattr(a.subprocess,'run',npm)
    monkeypatch.setattr(a.shutil,'which',lambda name:'/bin/npm')
    with (tmp_path/'log').open('wb') as out:
        env={};a.preparar_node({'pasta':str(workspace),'comando':command,'finalidade':purpose},path,env,out)
        assert Path(env['NODE_PATH']).joinpath('jsdom/package.json').exists()
        a.preparar_node({'pasta':str(workspace),'comando':command,'finalidade':purpose},path,env,out)
    assert len(calls)==1

@pytest.mark.parametrize('text,category',[
    ("KeyError: 'EMILY_PREVIEW_URL'",'previa_ausente'),
    ("ModuleNotFoundError: No module named 'pytest'",'dependencia_ausente'),
    ('ReferenceError: missing_helper is not defined','referencia_javascript'),
    ('Page.wait_for_selector: Timeout 30000ms exceeded.','espera_da_interface'),
    ('AssertionError: expected 2, got 1','teste_falhou')])
def test_diagnosis_preserves_real_failure(text,category):
    result=a.diagnosticar(text,{'codigo_saida':1,'finalidade':'teste'})
    assert result['categoria']==category and result['codigo_saida']==1
    assert not result['precisa_confirmacao']

def test_empty_search_is_not_test_success():
    result=a.diagnosticar('',{'comando':'rg absent file.py','codigo_saida':1,'finalidade':'comando'})
    assert result['categoria']=='busca_sem_correspondencias'
    assert result['codigo_saida']==1


def test_inspection_finds_playwright_browser_without_system_install(tmp_path,monkeypatch):
    browser=tmp_path/'chromium-123/chrome-linux64/chrome'
    browser.parent.mkdir(parents=True);browser.touch()
    monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH',str(tmp_path))
    monkeypatch.setattr(a.shutil,'which',lambda name:None)
    import sys
    result=a.inspecionar(tmp_path,sys.executable)
    assert result['navegador']==str(browser)

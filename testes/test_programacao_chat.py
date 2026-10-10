import json
import time
from pathlib import Path
import pytest
import programacao as p


@pytest.fixture
def project(tmp_path, monkeypatch):
    source=tmp_path/'source';source.mkdir()
    (source/'sample.py').write_text('value = 1\n')
    (source/'tests').mkdir()
    (source/'tests/test_sample.py').write_text('import unittest\nfrom sample import value\nclass Check(unittest.TestCase):\n def test_value(self): self.assertEqual(value, 2)\n')
    (source/'.env').write_text('PRIVATE_TOKEN=not-copied')
    (source/'memoria.json').write_text('{"private":true}')
    monkeypatch.setattr(p,'STORE',tmp_path/'sessions')
    monkeypatch.setattr(p,'root_source',lambda:source)
    return source


def session(project):
    result=p.execute('iniciar',{'objetivo':'Corrigir value e testar o resultado'})
    assert result['ok'],result
    folder,data=p.load(result['sessao']);data['publicar_automaticamente']=False;p.save(folder/'session.json',data)
    return result['sessao'],Path(result['pasta'])


def call(op,sid,**args): return p.execute(op,dict(sessao=sid,**args))


def run(sid,command='python3 -m unittest discover -s tests -v',purpose='teste'):
    result=call('executar',sid,comando=command,finalidade=purpose)
    assert result['ok'],result
    for _ in range(100):
        result=call('status',sid,trabalho=result['trabalho'],aguardar_segundos=0)
        if result['estado'] not in ('iniciando','executando'):return result
        time.sleep(.05)
    raise AssertionError('worker did not complete')


def edit(sid,to='value = 2'):
    result=call('editar',sid,arquivo='sample.py',buscar='value = 1',substituir=to)
    assert result['ok'],result


def test_actual_worker_test_apply_targets_undo(project):
    runtime=project/'dist/Emily/_internal';(runtime/'web').mkdir(parents=True)
    (runtime/'web/index.html').write_text('hello');(runtime/'sample.py').write_text('value = 7\n')
    sid,work=session(project);edit(sid)
    assert project.joinpath('sample.py').read_text()=='value = 1\n'
    result=run(sid);assert result['estado']=='concluido' and 'OK' in result['saida']
    assert call('aplicar',sid)['ok']
    assert project.joinpath('sample.py').read_text()=='value = 2\n'
    assert runtime.joinpath('sample.py').read_text()=='value = 2\n'
    assert call('aplicar',sid)['ok'] # idempotent
    assert call('desfazer',sid)['ok']
    assert runtime.joinpath('sample.py').read_text()=='value = 7\n'
    assert project.joinpath('sample.py').read_text()=='value = 1\n'


def test_secret_and_symlink_exclusion(project):
    (project/'outside.py').symlink_to('/etc/passwd')
    sid,work=session(project)
    assert not (work/'.env').exists() and not (work/'memoria.json').exists() and not (work/'outside.py').exists()
    for name in ('../sample.py','/etc/passwd','.env','web/../../sample.py','programacao.py'):
        assert not call('criar',sid,arquivo=name,conteudo='bad')['ok']


def test_stale_tests_and_failed_tests_reject_apply(project):
    sid,work=session(project)
    assert run(sid)['estado']=='falhou'
    edit(sid)
    assert not call('aplicar',sid)['ok']
    assert run(sid)['estado']=='concluido'
    call('editar',sid,arquivo='sample.py',buscar='value = 2',substituir='value = 3')
    assert not call('aplicar',sid)['ok']


def test_source_conflict_and_undo_conflict(project):
    sid,work=session(project);edit(sid);run(sid)
    project.joinpath('sample.py').write_text('value = 99\n')
    assert not call('aplicar',sid)['ok']
    assert project.joinpath('sample.py').read_text()=='value = 99\n'
    project.joinpath('sample.py').write_text('value = 1\n');assert call('aplicar',sid)['ok']
    project.joinpath('sample.py').write_text('value = 100\n')
    assert not call('desfazer',sid)['ok']
    assert project.joinpath('sample.py').read_text()=='value = 100\n'


def test_bad_syntax_not_applied_even_with_success_command(project):
    sid,work=session(project);edit(sid,'def invalid(')
    assert run(sid,'python3 -c "print(123)"')['estado']=='concluido'
    assert not call('aplicar',sid)['ok']
    assert project.joinpath('sample.py').read_text()=='value = 1\n'


def test_process_survives_interface_and_duplicate_start(project):
    sid,work=session(project)
    command='python3 -c "import time; time.sleep(1); print(42)"'
    args=dict(sessao=sid,comando=command,finalidade='teste')
    a=p.execute('executar',args);b=p.execute('executar',args)
    assert a['trabalho']==b['trabalho']
    # No in-memory process table needed, just persistent session/job state.
    folder,data=p.load(sid)
    time.sleep(1.2)
    assert p.status(folder,data,a['trabalho'])['estado']=='concluido'
    assert p.execute('listar')['sessoes'][0]['id']==sid


def test_cancel_process_and_prevent_apply_while_preview_running(project):
    sid,work=session(project);edit(sid);run(sid)
    job=call('executar',sid,comando='python3 -c "import time; time.sleep(60)"',finalidade='previa')
    assert not call('aplicar',sid)['ok']
    assert call('cancelar',sid,trabalho=job['trabalho'])['ok']
    result=call('status',sid,trabalho=job['trabalho'],aguardar_segundos=3)
    assert result['estado']=='cancelado'
    assert call('aplicar',sid)['ok']


def test_read_search_diff_progress(project):
    sid,work=session(project);events=[]
    assert '1: value = 1' in call('ler',sid,arquivo='sample.py')['texto']
    assert call('buscar',sid,texto='value')['resultados']
    edit(sid);assert '+value = 2' in call('diff',sid)['diff']
    result=p.execute('comentar',dict(sessao=sid,texto='Encontrei a causa e vou conferir a correção.',categoria='testes'),progress=lambda *x:events.append(x))
    assert result['ok'] and events[0][0]=='fala' and events[0][1]['categoria']=='testes'


def test_worker_isolated_data_and_env(project,monkeypatch):
    monkeypatch.setenv('EXAMPLE_API_KEY','private-not-test')
    sid,work=session(project)
    result=run(sid,'python3 -c "import os; from pathlib import Path; assert not os.getenv(\'EXAMPLE_API_KEY\'); assert Path(os.environ[\'EMILY_DATA_DIR\']).name == \'dados-teste\'; print(\'isolated\')"')
    assert result['estado']=='concluido' and 'isolated' in result['saida']


def test_terminal_policy_not_bypassed(project):
    sid,work=session(project)
    assert not call('executar',sid,comando='mkfs.ext4 /dev/sda',finalidade='teste')['ok']
    assert not call('executar',sid,comando='sudo apt install something',finalidade='comando')['ok']


def test_automatic_publication_only_self_project_after_verified_apply(project,monkeypatch):
    sid,work=session(project);edit(sid);run(sid)
    folder,data=p.load(sid);data.pop('publicar_automaticamente');p.save(folder/'session.json',data)
    launches=[]
    def launch(folder,data,command,purpose):
        assert project.joinpath('sample.py').read_text()=='value = 2\n'
        assert json.loads((folder/'session.json').read_text())['aplicacao']['arquivos']==['sample.py']
        launches.append((command,purpose));return dict(ok=True,trabalho='publication-job',estado='executando')
    monkeypatch.setattr(p,'job_start',launch)
    result=call('aplicar',sid)
    assert result['ok'] and result['publicacao']['estado']=='executando'
    assert launches[0][1]=='publicacao' and 'programacao_deploy.py' in launches[0][0]
    assert p.load(sid)[1]['estado']=='publicando'


def test_external_project_never_updates_emily_or_publishes(project,tmp_path,monkeypatch):
    sid,work=session(project);edit(sid);run(sid)
    folder,data=p.load(sid);data.pop('publicar_automaticamente');p.save(folder/'session.json',data)
    monkeypatch.setattr(p,'root_source',lambda:tmp_path/'real-emily')
    result=call('aplicar',sid)
    assert result['ok'] and not result['reiniciar_pc'] and 'publicacao' not in result


def test_missing_worker_recovered_after_crash(project):
    sid,work=session(project);folder,data=p.load(sid)
    jid='test-crash';data['jobs'].append(jid);p.save(folder/'session.json',data)
    p.save(folder/f'{jid}.json',{'id':jid,'estado':'executando','worker_pid':99999999,'criado':time.time()-20})
    result=call('status',sid,trabalho=jid,aguardar_segundos=0)
    assert not result['ok'] and result['estado']=='interrompido'
    assert work.joinpath('sample.py').exists()


def test_android_schema_matches_pc_contract():
    text=Path('EmilyAPP2/app/src/main/java/com/example/emilyapp/ProgrammingTools.kt').read_text()
    raw=text.split('private const val SCHEMAS = """',1)[1].split('"""',1)[0]
    definitions={t['function']['name'].removeprefix('pc_programacao_'):t['function'] for t in json.loads(raw)}
    assert set(definitions)=={d[0] for d in p.DEFINITIONS}
    for op,desc,props,req in p.DEFINITIONS:
        assert definitions[op]['parameters']['properties']==props
        assert definitions[op]['parameters']['required']==req


def test_restart_metadata_survives_result_preview_truncation():
    import interface_web
    bridge=interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    bridge._cid='';events=[];bridge._push=lambda name,data:events.append((name,data))
    full=json.dumps(dict(sessao='a'*32,arquivos=['file.py']*150,reiniciar_pc=True,backup='/private/backup'))
    bridge.progresso_evento('resultado',dict(nome='programacao_aplicar',resultado=full,ok=True,mudou=True))
    payload=events[-1][1]['dados']
    assert len(payload['resultado'])<=500
    assert payload['programacao']==dict(reiniciar_pc=True,sessao='a'*32)


def test_refresh_three_versions_preserves_changes_and_requires_new_tests(project):
    (project/'sample.py').write_text('value = 1\nother = 1\n')
    sid,work=session(project)
    edit(sid)
    assert run(sid)['estado']=='concluido'
    previous=call('diff',sid)['revisao']
    (project/'sample.py').write_text('value = 1\nother = 9\n')
    result=call('atualizar',sid)
    assert result['ok'] and result['conflitos']==[]
    assert (work/'sample.py').read_text()=='value = 2\nother = 9\n'
    assert (project/'sample.py').read_text()=='value = 1\nother = 9\n'
    assert call('diff',sid)['revisao']!=previous
    assert not call('aplicar',sid)['ok']
    assert run(sid)['estado']=='concluido'
    assert call('aplicar',sid)['ok']
    assert (project/'sample.py').read_text()=='value = 2\nother = 9\n'


def test_overlapping_conflict_preserved_and_resolution_checks_both_versions(project):
    sid,work=session(project);edit(sid)
    (project/'sample.py').write_text('value = 99\n')
    result=call('atualizar',sid)
    assert result['ok'] and result['conflitos'][0]['arquivo']=='sample.py'
    assert (work/'sample.py').read_text()=='value = 2\n'
    comparison=call('comparar',sid,arquivo='sample.py')['arquivos'][0]
    assert comparison['base']=='value = 1\n' and comparison['conflito']
    (work/'sample.py').write_text('value = 3\n')
    args={k:comparison[k] for k in ('sha_original','sha_copia')}
    assert not call('resolver',sid,arquivo='sample.py',escolha='manter_copia',**args)['ok']
    comparison=call('comparar',sid,arquivo='sample.py')['arquivos'][0]
    args={k:comparison[k] for k in ('sha_original','sha_copia')}
    result=call('resolver',sid,arquivo='sample.py',escolha='mesclar',conteudo='value = 2\n',**args)
    assert result['ok']
    assert (project/'sample.py').read_text()=='value = 99\n'
    assert run(sid)['estado']=='concluido'
    assert call('aplicar',sid)['ok']
    assert (project/'sample.py').read_text()=='value = 2\n'


def test_refresh_creation_deletion_and_binary_conflict(project):
    (project/'assets').mkdir();(project/'assets/logo.png').write_bytes(b'\x89PNG\xffbase')
    sid,work=session(project)
    (project/'added.py').write_text('added = True\n')
    (project/'sample.py').unlink()
    (project/'assets/logo.png').write_bytes(b'\x89PNG\xffremote')
    (work/'assets/logo.png').write_bytes(b'\x89PNG\xffours')
    result=call('atualizar',sid)
    assert result['ok'] and len(result['conflitos'])==1
    assert (work/'added.py').read_text()=='added = True\n'
    assert not (work/'sample.py').exists()
    assert (work/'assets/logo.png').read_bytes()==b'\x89PNG\xffours'


def test_preview_capture_is_local_and_original_does_not_change(project):
    import urllib.request
    (project/'web').mkdir()
    html='<html><body><h1>Prévia da cópia</h1><button onclick="this.textContent=\'ok\'">Teste</button><script>window.pywebview={api:{}};function irPara(screen){document.querySelector("h1").textContent=screen;}</script></body></html>'
    (project/'web/index.html').write_text(html)
    sid,work=session(project)
    (work/'web/index.html').write_text(html.replace('Prévia da cópia','Minha alteração'))
    result=call('previa',sid,operacao='abrir');assert result['ok'],result
    try:
        assert 'Minha alteração' in urllib.request.urlopen(result['url']).read().decode()
        for path in ['sample.py','.env','%2e%2e/sample.py']:
            with pytest.raises(urllib.error.HTTPError): urllib.request.urlopen(result['url']+path)
        image=call('previa',sid,operacao='capturar',largura=390,altura=820,tela='Visualização móvel')
        assert image['ok'],image
        folder,_=p.load(sid)
        assert (folder/image['arquivo']).read_bytes().startswith(b'\x89PNG')
        assert image['erros_javascript']==[]
        assert (project/'web/index.html').read_text()==html
    finally:
        call('cancelar',sid,trabalho=result['trabalho'])
        for _ in range(30):
            if call('status',sid,trabalho=result['trabalho'],aguardar_segundos=0)['estado'] not in {'iniciando','executando'}:break
            time.sleep(.1)


def test_motor_reruns_same_test_command_after_fixing_copy(project):
    import ferramentas as f, laco_ferramentas as motor, llm
    sid,work=session(project)
    catalog=[schema for schema in f.esquemas() if schema['function']['name'] in {'programacao_executar','programacao_editar'}]
    runner=motor.Motor(catalogo=catalog,contexto_execucao={'pedido_explicito':True,'dono_confirmado':True})
    args={'sessao':sid,'comando':'python3 -m unittest discover -s tests -v','finalidade':'teste'}
    def attempt(ident):
        return runner.executar([llm.ChamadaFerramenta(id=ident,nome='programacao_executar',argumentos=json.dumps(args))])[0]
    first=attempt('first');assert first.resultado.ok
    job=json.loads(first.resultado.texto)['trabalho']
    for _ in range(60):
        state=call('status',sid,trabalho=job,aguardar_segundos=0)
        if state['estado'] not in {'iniciando','executando'}:break
        time.sleep(.05)
    assert state['estado']=='falhou'
    edit(sid)
    second=attempt('second')
    assert not second.repetida and second.resultado.ok
    assert attempt('duplicate').repetida


def test_binary_changes_never_use_text_merge_even_when_valid_utf8(project):
    (project/'assets').mkdir();(project/'assets/picture.gif').write_bytes(b'GIF89a\nbase\nend\n')
    sid,work=session(project)
    (project/'assets/picture.gif').write_bytes(b'GIF89a\nremote\nend\n')
    (work/'assets/picture.gif').write_bytes(b'GIF89a\nbase\nours\n')
    result=call('atualizar',sid)
    assert result['conflitos'][0]['arquivo']=='assets/picture.gif'
    assert (work/'assets/picture.gif').read_bytes()==b'GIF89a\nbase\nours\n'


def test_worker_prepara_jsdom_sem_node_path_manual(project):
    (project/'testes').mkdir()
    (project/'testes/test_waiting_indicator.js').write_text("const {JSDOM}=require('jsdom'); const d=new JSDOM('<p>Teste</p>'); if(d.window.document.querySelector('p').textContent !== 'Teste') process.exit(1); console.log('DOM verificado');")
    sid,work=session(project)
    job=call('executar',sid,comando='node testes/test_waiting_indicator.js',finalidade='teste')
    deadline=time.monotonic()+150
    while job['estado'] in {'iniciando','executando'} and time.monotonic()<deadline:
        job=call('status',sid,trabalho=job['trabalho'],aguardar_segundos=1)
    assert job['estado']=='concluido',job
    assert 'DOM verificado' in job['saida']
    assert not (work/'node_modules').exists()


def test_worker_diagnostica_dependencia_sem_inventar_falta_de_autorizacao(project):
    sid,work=session(project)
    job=call('executar',sid,comando='python -c "import modulo_inexistente_emily_987"',finalidade='teste')
    while job['estado'] in {'iniciando','executando'}:
        job=call('status',sid,trabalho=job['trabalho'],aguardar_segundos=1)
    assert job['estado']=='falhou'
    assert job['diagnostico']['categoria']=='dependencia_ausente'
    assert job['diagnostico']['precisa_confirmacao'] is False


def test_testes_recebem_endereco_da_previa_ativa(project):
    (project/'web').mkdir();(project/'web/index.html').write_text('<p>Prévia de teste</p>')
    sid,work=session(project)
    preview=call('previa',sid,operacao='abrir')
    assert preview['ok'],preview
    try:
        job=call('executar',sid,comando='python -c "import os,urllib.request; print(urllib.request.urlopen(os.environ[\'EMILY_PREVIEW_URL\']).read().decode())"',finalidade='teste')
        while job['estado'] in {'iniciando','executando'}:
            job=call('status',sid,trabalho=job['trabalho'],aguardar_segundos=1)
        assert job['estado']=='concluido',job
        assert 'Prévia de teste' in job['saida']
    finally:
        call('cancelar',sid,trabalho=preview['trabalho'])


def test_retomada_reutiliza_teste_aprovado_e_invalida_apos_editar(project):
    sid,work=session(project);edit(sid)
    command='python3 -c "from sample import value; assert value == 2"'
    first=run(sid,command)
    summary=call('status',sid)
    assert summary['testes_aprovados'][0]['trabalho']==first['trabalho']
    again=call('executar',sid,comando=command,finalidade='teste')
    assert again['reutilizado'] and again['trabalho']==first['trabalho']
    forced=call('executar',sid,comando=command,finalidade='teste',reexecutar=True)
    assert forced['trabalho']!=first['trabalho']
    while forced['estado'] in {'iniciando','executando'}: forced=call('status',sid,trabalho=forced['trabalho'],aguardar_segundos=1)
    call('editar',sid,arquivo='sample.py',buscar='value = 2',substituir='value = 3')
    assert not call('status',sid)['testes_aprovados']
    rerun=run(sid,command)
    assert rerun['estado']=='falhou' and rerun['trabalho']!=first['trabalho']


def test_conferencia_visual_persistida_reutiliza_analise_sem_chamar_modelo(project,monkeypatch):
    from PIL import Image
    import modelo
    sid,work=session(project);folder,data=p.load(sid)
    image=folder/'preview-test.png';Image.new('RGB',(2,2),'orange').save(image)
    data['capturas']={image.name:{'revisao':p.revision(folder,data),'sha256':p.digest(image.read_bytes())}}
    p.save(folder/'session.json',data)
    calls=[];monkeypatch.setattr(modelo,'analisar_tela_com_pergunta',lambda *a:calls.append(a) or ('Cor e posição conferidas.'+'x'*2500))
    assert call('ver_imagem',sid,arquivo=image.name,pergunta='Confira o botão')['ok']
    reused=call('ver_imagem',sid,arquivo=image.name,pergunta='Confira o botão')
    assert reused['reutilizado'] and len(reused['analise'])>2500
    assert call('status',sid)['conferencias_visuais'][0]['analise_resumida']
    assert len(calls)==1 and len(call('status',sid)['conferencias_visuais'])==1
    edit(sid)
    assert not call('status',sid)['conferencias_visuais']


def test_active_preview_is_available_to_commands_and_environment(project):
    (project/'web').mkdir();(project/'web/index.html').write_text('preview-test')
    sid,work=session(project)
    preview=call('previa',sid,operacao='abrir')
    assert preview['ok'],preview
    try:
        env=call('ambiente',sid)
        assert env['ok'] and env['pasta']==str(work) and env['python']['pacotes']['pytest']
        assert env['previa']['url']==preview['url']
        result=run(sid,'python3 -c "import os,urllib.request; print(urllib.request.urlopen(os.environ[\'EMILY_PREVIEW_URL\']).read().decode())"',purpose='comando')
        assert result['estado']=='concluido' and 'preview-test' in result['saida']
        assert result['ambiente']['previa_url']==preview['url']
        assert result['fase']=='encerrado'
        assert not call('status',sid)['testes_aprovados']
    finally:
        call('cancelar',sid,trabalho=preview['trabalho'])

import json
import logging
import types
from pathlib import Path

import pytest
import comandos_rapidos as fast
import diagnostico_execucao as diag


@pytest.mark.parametrize('text',[
    'Não abre o Discord','Se eu pedir, abre o Discord','Como abrir o Discord?',
    'Eu gosto de abrir o Discord','Ele disse "abre o Discord"','abre o Discord e apaga meus arquivos',
    'abre o Discord depois de salvar','abre o Discord amanhã','talvez abre o Discord',
    'abre o discord\n','abre o navegador e pesquisa','abre ele','abre /tmp/coisa',
    'O botão tem o nome abrir calculadora','abre o Steam; reinicia o PC',
    'abre o app desconhecido','abre o Discord ou o Spotify','não deixe de abrir o Discord',
])
def test_uncertain_is_left_to_agent(text):
    assert fast.parse(text) is None


@pytest.mark.parametrize('text', ['Emily, abre a calculadora!', 'abre o Discord',
    'Por favor abre o Firefox', 'abra o Spotify no meu PC', 'abre o terminal pra mim'])
def test_literal_complete_requests(text):
    assert fast.parse(text)[0] == 'abrir_app'


def test_failure_and_timeout_are_not_retried():
    calls=[];events=[]
    def execute(name,args):
        calls.append((name,args))
        return types.SimpleNamespace(texto='Não consegui abrir.',ok=False)
    assert fast.try_execute('abre o Discord',execute,lambda *e:events.append(e))=='Não consegui abrir.'
    assert len(calls)==1 and events[-1][1]['ok'] is False
    assert fast.try_execute('Não abre o Discord',execute) is None
    assert len(calls)==1


def test_label_or_example_answer_is_not_an_action():
    for history in [[{'role':'assistant','content':'Qual texto você quer no botão?'}],
                    [{'role':'user','content':'Vou dar um exemplo de comando.'}]]:
        assert fast.try_execute('abre o Discord',lambda *a:pytest.fail('executou'),history=history) is None


def test_rotating_private_metadata_captures_failure_without_content(tmp_path,monkeypatch):
    old=diag._logger;diag._logger=None
    monkeypatch.setenv('EMILY_DIAGNOSTICS_DIR',str(tmp_path))
    @diag.measured('tool','nome')
    def run(nome,arguments):
        return types.SimpleNamespace(ok=False,erro='negado',texto='segredo-na-saida')
    @diag.measured('turn')
    def turn(): return run('abrir_app',{'chave':'segredo-no-pedido'})
    try:
        turn()
        path=tmp_path/'performance.jsonl'
        text=path.read_text();rows=[json.loads(r) for r in text.splitlines()]
        assert len(rows)==2 and rows[0]['ok'] is False
        assert rows[0]['trace']==rows[1]['trace'] and rows[0]['trace']
        assert 'segredo' not in text and path.stat().st_mode & 0o777==0o600
        handler=diag._logger.handlers[0];handler.maxBytes=100
        for i in range(10): turn()
        assert len(list(tmp_path.glob('performance.jsonl*')))<=3
        assert any(p.name.endswith('.1') for p in tmp_path.iterdir())
    finally:
        for h in diag._logger.handlers: h.close()
        diag._logger=old


def test_metadata_failure_does_not_block_tool(monkeypatch):
    monkeypatch.setattr(diag,'event',lambda *a,**k:None)
    @diag.measured('tool','nome')
    def tool(nome): raise ValueError('private detail')
    with pytest.raises(ValueError): tool('teste')

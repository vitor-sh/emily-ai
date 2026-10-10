import time
from pathlib import Path

from pc_terminal import TerminalRemoto


def esperar(t, ident):
    for _ in range(100):
        result = t.status(ident)
        if result.get('concluido'):
            return result
        time.sleep(0.05)
    raise AssertionError('comando não terminou')


def test_execucao_real_idempotente_e_saida(tmp_path):
    t = TerminalRemoto(tmp_path)
    args = dict(comando='printf x >> teste; printf "ação 🧡"; printf erro >&2', request_id='teste-1234')
    a = t.iniciar(args, 'turno')
    b = t.iniciar(args, 'turno')
    assert a['job_id'] == b['job_id']
    r = esperar(t, a['job_id'])
    assert r['stdout'] == 'ação 🧡' and r['stderr'] == 'erro'
    assert r['codigo_saida'] == 0 and r['ok']
    assert (tmp_path/'teste').read_text() == 'x'
    assert not t.iniciar({**args, 'comando': 'printf outra'}, 'turno')['ok']


def test_falha_nao_e_sucesso_e_saida_limitada(tmp_path):
    t = TerminalRemoto(tmp_path)
    r = t.iniciar(dict(comando='head -c 100000 /dev/zero; exit 7', request_id='teste-1234'), 'turno')
    r = esperar(t, r['job_id'])
    assert not r['ok'] and r['codigo_saida'] == 7 and r['estado'] == 'falhou'
    assert len(r['stdout']) <= 16000 and r['saida_truncada']


def test_confirmacao_novo_turno_comando_exato_e_retransmissao(tmp_path):
    t = TerminalRemoto(tmp_path)
    f = tmp_path/'apagar'; f.write_text('temp')
    args = dict(comando='rm apagar', request_id='teste-1234')
    r = t.iniciar(args, 'turno1')
    assert r['requer_confirmacao'] and f.exists()
    ident = r['confirmation_id']
    assert t.iniciar(args,'turno1')['confirmation_id'] == ident
    assert not t.confirmar(dict(confirmation_id=ident, confirmar=True), 'turno1')['ok']
    r = t.confirmar(dict(confirmation_id=ident, confirmar=True, comando='rm outro'), 'turno2')
    assert esperar(t,r['job_id'])['ok'] and not f.exists()
    assert t.confirmar(dict(confirmation_id=ident, confirmar=True), 'turno2')['job_id'] == r['job_id']


def test_confirmacao_expirada_cancelada_e_bloqueio(tmp_path):
    t = TerminalRemoto(tmp_path)
    r = t.iniciar(dict(comando='rm arquivo', request_id='teste-1234'),'turno1')
    ident=r['confirmation_id']; t.confirmations[ident]['expires']=0
    assert not t.confirmar(dict(confirmation_id=ident, confirmar=True),'turno2')['ok']
    r=t.iniciar(dict(comando='rm arquivo',request_id='teste-5678'),'turno1')
    assert t.confirmar(dict(confirmation_id=r['confirmation_id'], confirmar=False),'turno2')['estado']=='cancelado'
    assert not t.iniciar(dict(comando='rm -rf /',request_id='teste-9999'),'turno')['ok']


def test_comando_longo_cancelavel_nao_anuncia_conclusao(tmp_path):
    t = TerminalRemoto(tmp_path)
    r=t.iniciar(dict(comando='sleep 20',request_id='teste-1234'),'turno')
    assert r['estado']=='executando' and not r['concluido']
    assert t.cancelar(r['job_id'])['ok']
    assert esperar(t,r['job_id'])['estado']=='cancelado'


def test_confirmacao_semantica_independe_de_palavra_chave(tmp_path):
    t=TerminalRemoto(tmp_path)
    r=t.iniciar(dict(comando="printf serio",sensivel=True,request_id='teste-1234'),'turno1')
    assert r['requer_confirmacao']
    r=t.confirmar(dict(confirmation_id=r['confirmation_id'],confirmar=True),'turno2')
    assert esperar(t,r['job_id'])['stdout']=='serio'


def test_irrestrito_exclui_arquivo_pessoal_uma_vez(tmp_path):
    t=TerminalRemoto(tmp_path)
    f=tmp_path/'arquivo pessoal.txt';f.write_text('teste')
    args=dict(comando="rm -- 'arquivo pessoal.txt'",sensivel=True,request_id='modo-12345')
    first=t.iniciar(args,'t1',irrestrito=True)
    assert esperar(t,first['job_id'])['ok'] and not f.exists()
    assert t.iniciar(args,'t1',irrestrito=True)['job_id']==first['job_id']


def test_irrestrito_preserva_credenciais_sistema_scripts_e_modo_padrao(tmp_path):
    t=TerminalRemoto(tmp_path)
    (tmp_path/'.ssh').mkdir();key=tmp_path/'.ssh/id_ed25519';key.write_text('teste')
    for i,command in enumerate(['rm .ssh/id_ed25519','unlink .ssh/id_ed25519','rm -r /etc','chmod 777 arquivo','python3 -c "print(1)"']):
        result=t.iniciar(dict(comando=command,sensivel=True,request_id=f'protegido-{i}'),'t1',irrestrito=True)
        assert result.get('requer_confirmacao') or not result['ok']
    assert key.exists()
    assert t.iniciar(dict(comando='rm arquivo',request_id='modo-normal',unrestricted_mode=True),'t1').get('requer_confirmacao')
    assert not t.iniciar(dict(comando='rm -rf /',request_id='modo-raiz'),'t1',irrestrito=True)['ok']


def test_irrestrito_nao_libera_symlink_para_fora_da_home(tmp_path):
    home=tmp_path/'home';home.mkdir()
    outside=tmp_path/'fora';outside.mkdir()
    (home/'atalho').symlink_to(outside,target_is_directory=True)
    t=TerminalRemoto(home)
    result=t.iniciar(dict(comando='rm -r atalho',request_id='modo-link'),'t1',irrestrito=True)
    assert result['requer_confirmacao'] and outside.exists()

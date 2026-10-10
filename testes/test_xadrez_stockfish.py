import sys
from pathlib import Path
import threading
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import xadrez_stockfish as sf
from xadrez_emily import Partida
FEN='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

def p0():return {'fen':FEN,'pgn':'','cor':'b','turno':'w','fim':False,'legais':[{'uci':'e2e4','san':'e4'},{'uci':'d2d4','san':'d4'}]}

def test_sol_so_escolhe_entre_candidatos_verificados_e_nivel_persiste(tmp_path):
    pedidos=[];respostas=iter(['{"uci":"e2e4"}','{"uci":"d2d4"}'])
    def modelo(msgs,**kw):pedidos.append(msgs[-1]['content']);return next(respostas)
    def apoio(pos,nivel,avisar,cancelado):
        assert nivel=='casual';avisar('Conferindo')
        return {'candidatos':['d2d4'],'descricao':'Verificado','avaliacao':None}
    p=Partida(tmp_path/'j.json',chamar=modelo,apoio=apoio)
    p.sincronizar(p0(),0,nova=True);p.escolher_lance(1);p.worker_lance.join(2)
    assert p.estado()['lance']['uci']=='d2d4'
    assert '"e2e4"' not in pedidos[0]
    p.dificuldade('equilibrado')
    assert Partida(p.caminho).estado()['dificuldade']=='equilibrado'
    with pytest.raises(ValueError):p.dificuldade('desconhecido')

def test_trocar_nivel_descarta_analise_pendente(tmp_path):
    inicio,liberar=threading.Event(),threading.Event()
    def apoio(pos,nivel,avisar,cancelado):
        inicio.set();assert liberar.wait(2);assert cancelado()
        raise ValueError('Cancelado')
    p=Partida(tmp_path/'j.json',chamar=lambda *a,**kw:pytest.fail('Não chamar Sol antigo'),apoio=apoio)
    p.sincronizar(p0(),0,nova=True);p.escolher_lance(1);assert inicio.wait(1)
    p.dificuldade('sol');liberar.set();p.worker_lance.join(2)
    assert p.estado()['lance']['estado']=='pronto'

def test_filtro_respeita_perfil_sem_escolher_lance_aleatorio(monkeypatch):
    monkeypatch.setattr(sf,'preparar',lambda *a:'exe')
    monkeypatch.setattr(sf,'analisar',lambda *a:('d2d4',[{'uci':'e2e4','cp':100},{'uci':'d2d4','cp':10}]))
    assert sf.consultar(p0(),'casual')['candidatos']==['d2d4']
    assert sf.consultar(p0(),'desafiador')['candidatos']==['e2e4']

def test_download_invalido_nao_instala_nem_executa(tmp_path,monkeypatch):
    import requests
    class Fake:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def raise_for_status(self):pass
        def iter_content(self,*a):yield b'arquivo alterado'
    monkeypatch.setattr(sf,'pasta',lambda:tmp_path)
    monkeypatch.setattr(sf.platform,'system',lambda:'Linux');monkeypatch.setattr(sf.platform,'machine',lambda:'x86_64')
    monkeypatch.setattr(requests,'get',lambda *a,**kw:Fake())
    with pytest.raises(ValueError,match='verificação'):sf.preparar()
    assert not (tmp_path/'stockfish').exists()

def test_motor_real_perfis_e_cancelamento():
    exe=sf.pasta()/'stockfish'
    if not exe.is_file():pytest.skip('Motor oficial ainda não está no cache local')
    legais={f'{f}2{f}{r}' for f in 'abcdefgh' for r in '34'}|{'b1a3','b1c3','g1f3','g1h3'}
    for skill,ms,_ in sf.PERFIS.values():
        escolhido,scores=sf.analisar(exe,FEN,skill,ms)
        assert escolhido in legais and scores and all(m['uci'] in legais for m in scores)
    with pytest.raises(ValueError,match='partida mudou'):sf.analisar(exe,FEN,0,150,cancelado=lambda:True)
    with pytest.raises(ValueError,match='inválida'):sf.analisar(exe,FEN+'\nquit',0,150)


def test_guia_so_usa_motor_instalado_cache_e_nao_altera_dificuldade(tmp_path,monkeypatch):
    sf._cache_conversa.clear()
    monkeypatch.setattr(sf,'pasta',lambda:tmp_path)
    monkeypatch.setattr(sf.platform,'system',lambda:'Linux')
    monkeypatch.setattr(sf,'preparar',lambda *a:pytest.fail('Conversa não deve baixar motor'))
    assert sf.contexto_conversa(p0()) is None
    (tmp_path/'stockfish').write_bytes(b'fixture')
    chamadas=[]
    def analisar(*args):
        chamadas.append(args)
        return 'e2e4',[{'uci':'e2e4','cp':20,'pv':['e2e4','e7e5']}]
    monkeypatch.setattr(sf,'analisar',analisar)
    niveis=dict(sf.PERFIS)
    guia=sf.contexto_conversa(p0());guia['linhas_uci'][0].append('a1a8')
    assert sf.contexto_conversa(p0())['linhas_uci']==[['e2e4','e7e5']]
    assert len(chamadas)==1 and sf.PERFIS==niveis
    assert sf.contexto_conversa({**p0(),'fim':True}) is None
    assert sf.contexto_conversa(p0(),cancelado=lambda:True) is None
    sf._cache_conversa.clear()

@pytest.mark.parametrize('ancora_presente',[True,False])
def test_captura_fora_top_seis_exige_referencia(tmp_path,monkeypatch,ancora_presente):
    sf._cache_conversa.clear();(tmp_path/'stockfish').write_bytes(b'fixture')
    monkeypatch.setattr(sf,'pasta',lambda:tmp_path);monkeypatch.setattr(sf.platform,'system',lambda:'Linux')
    pos=p0();pos['fatos']={'tatico':{'capturas_legais_agora':[{'uci':'d2d4'}]}}
    calls=[]
    def analisar(*a,**kw):
        calls.append(kw)
        if not kw:return 'e2e4',[{'uci':'e2e4','cp':50,'pv':['e2e4']}]
        assert kw['restritos']==['d2d4','e2e4']
        scores=[{'uci':'d2d4','cp':-600,'pv':['d2d4']}]
        if ancora_presente:scores.append({'uci':'e2e4','cp':30,'pv':['e2e4']})
        return 'e2e4',scores
    monkeypatch.setattr(sf,'analisar',analisar)
    guia=sf.contexto_conversa(pos)
    if ancora_presente:
        assert guia['avaliacoes_capturas'][0]['perda_estimada_cp']==630
        assert not guia['capturas_sem_avaliacao']
    else:
        assert not guia['avaliacoes_capturas']
        assert guia['capturas_sem_avaliacao']==['d2d4']
    sf._cache_conversa.clear()

def test_searchmoves_invalidos_rejeitados_antes_de_executar():
    for moves in ([],['e2e4\nquit'],['banana']):
        with pytest.raises(ValueError,match='restrita'):sf.analisar('nao-executar',FEN,20,200,restritos=moves)

def test_motor_real_avalia_captura_envenenada_fora_melhores_variantes():
    if not (sf.pasta()/'stockfish').is_file():pytest.skip('Motor não instalado')
    fen='r1b2rk1/pp2qppp/5p2/8/2P5/3QbP2/P3B1PP/R3K2R w KQ - 0 16'
    # A alternativa segura e as duas capturas relevantes; o frontend valida o conjunto completo.
    pos={'fen':fen,'turno':'w','legais':[{'uci':u} for u in ['d3e4','d3c2','a1b1','d3e3','d3h7']],
         'fatos':{'tatico':{'capturas_legais_agora':[{'uci':'d3e3'},{'uci':'d3h7'}]}}}
    sf._cache_conversa.clear();guia=sf.contexto_conversa(pos)
    captura=next(m for m in guia['avaliacoes_capturas'] if m['uci']=='d3e3')
    assert captura['perda_estimada_cp']>=150
    assert captura['linha_apos_captura'][:2]==['d3e3','e7e3']
    sf._cache_conversa.clear()

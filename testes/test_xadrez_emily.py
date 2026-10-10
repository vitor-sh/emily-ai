import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xadrez_emily import Partida, chamar_modelo

FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


def posicao(**extra):
    return dict(fen=FEN, pgn='', cor='b', turno='w', fim=False,
                legais=[{'uci':'e2e4','san':'e4'},{'uci':'d2d4','san':'d4'}], **extra)


def partida(tmp_path, fn):
    p = Partida(tmp_path / 'partida.json', chamar=fn)
    assert p.sincronizar(posicao(), 0, nova=True)['ok']
    return p


def test_lance_invalido_corrigido_sem_aplicar_no_tabuleiro(tmp_path):
    respostas = iter(['{"uci":"e2e5"}', '{"uci":"e2e4"}'])
    p = partida(tmp_path, lambda *a, **k: next(respostas))
    p.escolher_lance(1); p.worker_lance.join(3)
    assert p.estado()['lance']['uci'] == 'e2e4'
    assert p.estado()['posicao']['fen'] == FEN
    assert p.estado()['revisao'] == 1


def test_nao_escolhe_lance_aleatorio_quando_resposta_invalida(tmp_path):
    p = partida(tmp_path, lambda *a, **k: 'e2e5')
    p.escolher_lance(1); p.worker_lance.join(3)
    assert p.estado()['lance']['estado'] == 'erro'
    assert p.estado()['posicao']['fen'] == FEN


def test_desfaz_descarta_calculo_antigo_e_nao_dispara_duplicados(tmp_path):
    inicio, liberar = threading.Event(), threading.Event()
    def lento(*a, **k):
        inicio.set(); assert liberar.wait(3); return '{"uci":"e2e4"}'
    p = partida(tmp_path, lento)
    p.escolher_lance(1); assert inicio.wait(1)
    assert p.escolher_lance(1)['ocupado']
    p.sincronizar(posicao(), 1, nova=True)
    liberar.set(); p.worker_lance.join(3)
    assert p.estado()['lance']['estado'] == 'pronto'
    assert not p.sincronizar(posicao(), 1)['ok']


def test_conversa_e_lance_em_paralelo_sem_mudar_tabuleiro(tmp_path):
    inicio, liberar = threading.Event(), threading.Event()
    chamadas=[]
    def modelo(msgs, **kw):
        chamadas.append(kw)
        if kw.get('lance'):
            inicio.set(); assert liberar.wait(3); return '{"uci":"d2d4"}'
        return 'Bora jogar, Vitor.'
    p=partida(tmp_path, modelo)
    p.escolher_lance(1); assert inicio.wait(1)
    assert p.conversar('Como você tá?')['ok']
    p.worker_chat.join(2)
    assert p.estado()['mensagens'][-1]['content']=='Bora jogar, Vitor.'
    assert p.estado()['lance']['estado']=='pensando'
    liberar.set();p.worker_lance.join(3)
    assert p.estado()['lance']['uci']=='d2d4'
    assert chamadas[0]['lance'] is True


def test_salvamento_e_recuperacao_de_interrupcao(tmp_path):
    p=partida(tmp_path, lambda *a, **k: '')
    with p.lock:
        p.dados['lance']={'estado':'pensando'}
        p.dados['mensagens']=[{'role':'user','content':'Oi, Emily!'}]
        p._salvar()
    recuperada=Partida(p.caminho)
    assert recuperada.estado()['lance']['estado']=='erro'
    assert recuperada.estado()['mensagens'][0]['content']=='Oi, Emily!'
    assert recuperada.estado()['posicao']['fen']==FEN


def test_erro_rede_preserva_partida_e_permite_nova_tentativa(tmp_path):
    def erro(*a, **k):
        import llm
        raise llm.ErroTransporte('timeout')
    p=partida(tmp_path, erro)
    p.escolher_lance(1);p.worker_lance.join(3)
    assert 'conexão' in p.estado()['lance']['erro']
    p.chamar=lambda *a, **k:'{"uci":"d2d4"}'
    p.escolher_lance(1);p.worker_lance.join(3)
    assert p.estado()['lance']['uci']=='d2d4'


def test_rota_fixa_do_xadrez_sem_alterar_selecao_global(monkeypatch):
    import llm
    chamadas=[]
    monkeypatch.setattr(llm,'chamar',lambda msgs,**kw:chamadas.append(kw) or 'oi')
    chamar_modelo([],lance=True);chamar_modelo([])
    assert [(c['modelo'],c['raciocinio']) for c in chamadas]==[('kr/claude-opus-5','medio'),('kr/claude-opus-5','baixo')]
    assert all(c['provedor']=='omniroute' for c in chamadas)


def test_convite_abre_xadrez_mas_conversa_nao_e_obrigatoria():
    from classificacao_ferramentas import classificar, FERRAMENTA_OBRIGATORIA
    assert classificar('Emily, vamo jogar um xadrez?').politica==FERRAMENTA_OBRIGATORIA
    assert classificar('Não quero jogar xadrez agora').politica!=FERRAMENTA_OBRIGATORIA
    assert classificar('Como jogar xadrez?').politica!=FERRAMENTA_OBRIGATORIA
    assert classificar('Cria uma pasta chamada xadrez', acao_explicita=True).politica==FERRAMENTA_OBRIGATORIA


def test_ferramenta_abre_interface_preservando_partida(monkeypatch):
    import interface_web
    import ferramentas
    eventos=[]
    class ApiTeste:
        def xadrez_acao(self, acao):
            eventos.append(acao)
            return {'ok':True}
    monkeypatch.setattr(interface_web,'_api_registrada',ApiTeste())
    resultado=ferramentas.executar_estruturado('xadrez_abrir',{},contexto={'pedido_explicito':True,'dono_confirmado':True})
    assert resultado.ok and eventos==['abrir']
    assert 'xadrez_abrir' in {f['function']['name'] for f in ferramentas.esquemas_com_dominios([])}


def fatos_lance(ply=1, captura=None):
    return {'meios_lances':ply,'ultimos_lances':[{'ator':'Você','peca':'peão','origem':'e4','destino':'d5','captura':captura}]}


def test_comentarios_intervalo_eventos_sem_duplicar_e_persistir(tmp_path):
    chamadas=[]
    p=partida(tmp_path,lambda msgs,**kw:chamadas.append(msgs) or 'Meu peão foi passear, hein.')
    p.dados['comentarios']={'ultimo':0,'intervalo':8}
    p.sincronizar(posicao(fatos=fatos_lance(1)),1)
    p.comentar(2);assert not chamadas
    p.sincronizar(posicao(fatos=fatos_lance(2,{'peca':'peão','dono':'Emily'})),2)
    p.comentar(3);assert not chamadas
    p.sincronizar(posicao(fatos=fatos_lance(4,{'peca':'peão','dono':'Emily'})),3)
    p.comentar(4);p.worker_comentario.join(2)
    assert len(chamadas)==1
    p.comentar(4);assert len(chamadas)==1
    assert p.estado()['mensagens'][-1]['automatico']
    assert p.estado()['comentarios']['ultimo']==4
    assert 'Comente espontaneamente' in chamadas[0][-1]['content']
    assert 'Emily' in chamadas[0][-1]['content']
    loaded=Partida(p.caminho,chamar=lambda *a,**kw:pytest.fail('Não repetir comentário ao abrir'))
    loaded.comentar(4)
    assert loaded.estado()['comentarios']['ultimo']==4
    p.sincronizar(posicao(fatos=fatos_lance(1)),4)
    assert p.estado()['comentarios']['ultimo']==1


def test_comentario_antigo_descartado_quando_tabuleiro_muda(tmp_path):
    inicio,liberar=threading.Event(),threading.Event()
    def lento(*a,**kw):
        inicio.set();assert liberar.wait(3);return 'Comentário antigo.'
    p=partida(tmp_path,lento);p.dados['comentarios']['intervalo']=1
    p.sincronizar(posicao(fatos=fatos_lance()),1);p.comentar(2);assert inicio.wait(1)
    p.sincronizar(posicao(fatos=fatos_lance(2)),2)
    liberar.set();p.worker_comentario.join(2)
    assert p.estado()['mensagens']==[]


def test_mensagem_usuario_prioritaria_sobre_comentario_em_andamento(tmp_path):
    inicio,liberar=threading.Event(),threading.Event()
    def modelo(msgs,**kw):
        if 'Comente espontaneamente' in msgs[-1]['content']:
            inicio.set();assert liberar.wait(3);return 'Comentário dispensado.'
        return 'Tudo bem, Vitor.'
    p=partida(tmp_path,modelo);p.dados['comentarios']['intervalo']=1
    p.sincronizar(posicao(fatos=fatos_lance()),1);p.comentar(2);assert inicio.wait(1)
    assert p.conversar('Tudo bem?')['ok'];p.worker_chat.join(2)
    liberar.set();p.worker_comentario.join(2)
    assert [m['content'] for m in p.estado()['mensagens']]==['Tudo bem?','Tudo bem, Vitor.']


def test_comentario_falha_nao_trava_chat_nem_dispara_retry_infinito(tmp_path):
    calls=[]
    def falha(*a,**kw):calls.append(1);raise ValueError('Falhou')
    p=partida(tmp_path,falha);p.dados['comentarios']['intervalo']=1
    p.sincronizar(posicao(fatos=fatos_lance()),1);p.comentar(2);p.worker_comentario.join(2)
    for _ in range(5):p.comentar(2)
    assert len(calls)==1 and p.estado()['conversa']['estado']=='pronto'


def test_voz_na_partida_registra_ambos_e_volta_ao_chat_ao_fechar(tmp_path,monkeypatch):
    import interface_web
    import xadrez_emily
    from types import SimpleNamespace
    p=partida(tmp_path,lambda *a,**kw:'Peguei seu cavalo, hein!')
    narracoes=[];monkeypatch.setattr(p,'_narrar',lambda *args:narracoes.append(args))
    monkeypatch.setattr(xadrez_emily,'instancia',lambda:p)
    monkeypatch.setattr(interface_web,'_api_registrada',None)
    api=interface_web.Api(SimpleNamespace(_push=lambda *a:None))
    monkeypatch.setattr(api,'_demo_ativo',lambda:False)
    assert not interface_web.encaminhar_voz_xadrez('Oi')
    api.xadrez_acao('visibilidade',{'ativo':True,'serial':10})
    assert interface_web.encaminhar_voz_xadrez('Emily, o que aconteceu?')
    p.worker_chat.join(2)
    assert [m['role'] for m in p.estado()['mensagens']]==['user','assistant']
    assert all(m['origem']=='voz' for m in p.estado()['mensagens'])
    loaded=Partida(p.caminho)
    assert loaded.estado()['mensagens']==p.estado()['mensagens']
    assert narracoes
    api.xadrez_acao('visibilidade',{'ativo':False,'serial':12})
    api.xadrez_acao('visibilidade',{'ativo':True,'serial':11})
    assert not interface_web.encaminhar_voz_xadrez('Agora no chat normal')


def test_falas_em_sequencia_ficam_registradas_e_respondidas(tmp_path,monkeypatch):
    import time
    inicio,liberar=threading.Event(),threading.Event()
    pedidos=[]
    def modelo(msgs,**kw):
        pedido=msgs[-1]['content'].split('Responda a esta mensagem do usuário, considerando estes fatos atuais: ')[-1]
        pedidos.append(pedido)
        if len(pedidos)==1:inicio.set();assert liberar.wait(3)
        return 'Resposta: '+pedido
    p=partida(tmp_path,modelo);monkeypatch.setattr(p,'_narrar',lambda *a:None)
    p.conversar('Primeira fala',voz=True,origem='voz');assert inicio.wait(1)
    assert p.conversar('Segunda fala',voz=True,origem='voz')['enfileirada']
    assert p.estado()['mensagens'][-1]['content']=='Segunda fala'
    liberar.set();deadline=time.monotonic()+3
    while time.monotonic()<deadline and p.estado()['conversa']['estado']=='pensando':time.sleep(.01)
    assert pedidos==['Primeira fala','Segunda fala']
    assert [m['content'] for m in p.estado()['mensagens'] if m['role']=='assistant']==['Resposta: Primeira fala','Resposta: Segunda fala']
    assert len(p.fila_voz)==0


def test_comentario_revisa_coordenadas_e_fallback_sem_inventar(tmp_path):
    respostas=iter(['Capturei seu cavalo em f8.','Peguei em f8 em quatro jogadas.'])
    p=partida(tmp_path,lambda *a,**kw:next(respostas))
    p.dados['comentarios']['intervalo']=1
    fato=fatos_lance(1,{'peca':'cavalo','dono':'Você'});fato['ultimos_lances'][0]['ator']='Emily'
    p.sincronizar(posicao(fatos=fato),1)
    p.comentar(2);p.worker_comentario.join(2)
    resposta=p.estado()['mensagens'][-1]['content']
    assert resposta=='Peguei o cavalo! Vai me dar mais presente, é?'
    assert not p._comentario_tecnico(resposta)


def test_coordenadas_continuam_permitidas_quando_usuario_pergunta(tmp_path):
    p=partida(tmp_path,lambda *a,**kw:'Seu cavalo está em f3.')
    p.conversar('Onde está meu cavalo?');p.worker_chat.join(2)
    assert 'f3' in p.estado()['mensagens'][-1]['content']


def test_capturas_proximas_nao_geram_rajada_e_fim_tem_prioridade(tmp_path):
    import time
    chamadas=[]
    p=partida(tmp_path,lambda *a,**kw:chamadas.append(1) or 'Essa eu senti!')
    p.dados['comentarios']={'ultimo':4,'intervalo':8,'quando':time.time()}
    p.sincronizar(posicao(fatos=fatos_lance(8,{'peca':'dama','dono':'Emily'})),1)
    p.comentar(2);assert p.worker_comentario is None
    p.dados['comentarios']['quando']=time.time()-21
    p.comentar(2);p.worker_comentario.join(2)
    assert len(chamadas)==1
    p.sincronizar(posicao(fatos=fatos_lance(9,{'peca':'torre','dono':'Emily'})),2)
    p.comentar(3);assert len(chamadas)==1
    p.sincronizar({**posicao(fatos=fatos_lance(10)), 'fim':True},3)
    p.comentar(4);p.worker_comentario.join(2)
    assert len(chamadas)==2


def test_pergunta_na_janela_de_comentario_funde_sem_chamada_extra(tmp_path):
    chamadas=[]
    p=partida(tmp_path,lambda msgs,**kw:chamadas.append(msgs[-1]['content']) or 'Tô bem! E esse cavalo que você pegou, hein?')
    p.dados['comentarios']['intervalo']=1
    p.sincronizar(posicao(fatos=fatos_lance(1)),1)
    p.comentar(2)
    assert p.conversar('Tudo bem?')['ok']
    p.worker_chat.join(2);p.worker_comentario.join(2)
    assert len(chamadas)==1 and 'UMA resposta breve' in chamadas[0]
    assert [m['role'] for m in p.estado()['mensagens']]==['user','assistant']


def test_texto_e_voz_enfileirados_preservam_pedidos_e_contexto_atual(tmp_path):
    import time
    inicio,liberar=threading.Event(),threading.Event()
    chamadas=[]
    def modelo(msgs,**kw):
        pedido=msgs[-1]['content'].split('Responda a esta mensagem do usuário, considerando estes fatos atuais: ')[-1]
        chamadas.append((pedido,msgs))
        if len(chamadas)==1:inicio.set();assert liberar.wait(3)
        return 'Resposta: '+pedido
    p=partida(tmp_path,modelo)
    assert p.conversar('Primeira')['ok'];assert inicio.wait(1)
    assert p.conversar('Segunda')['enfileirada']
    assert p.conversar('Terceira',origem='voz')['enfileirada']
    p.sincronizar(posicao(fatos=fatos_lance(8)),1)
    liberar.set();deadline=time.monotonic()+3
    while time.monotonic()<deadline and p.chat_ocupado:time.sleep(.01)
    assert [c[0] for c in chamadas]==['Primeira','Segunda','Terceira']
    assert not any(m['content']=='Terceira' for m in chamadas[1][1])
    assert any(m['content']=='Resposta: Primeira' for m in chamadas[1][1])
    assert '"meios_lances": 8' in chamadas[1][1][-1]['content']
    assert len([m for m in p.estado()['mensagens'] if m['role']=='assistant'])==3
    assert not p.chat_ocupado and not p.fila_voz
    loaded=Partida(p.caminho)
    assert loaded.chat_serial==3


def test_nova_partida_descarta_fila_antiga_sem_responder_pergunta_errada(tmp_path):
    import time
    inicio,liberar=threading.Event(),threading.Event()
    def modelo(msgs,**kw):
        if 'Antiga' in msgs[-1]['content']:inicio.set();assert liberar.wait(3)
        return 'Resposta nova'
    p=partida(tmp_path,modelo)
    p.conversar('Antiga');assert inicio.wait(1)
    p.conversar('Pergunta da partida antiga')
    p.sincronizar(posicao(),1,nova=True)
    assert p.conversar('Nova')['enfileirada']
    liberar.set();deadline=time.monotonic()+3
    while time.monotonic()<deadline and p.chat_ocupado:time.sleep(.01)
    assert [m['content'] for m in p.estado()['mensagens']]==['Nova','Resposta nova']


def test_erro_de_uma_mensagem_nao_engole_a_proxima(tmp_path):
    import time
    inicio,liberar=threading.Event(),threading.Event()
    calls=[]
    def modelo(msgs,**kw):
        calls.append(msgs)
        if len(calls)==1:
            inicio.set();assert liberar.wait(3);raise ValueError('Falha temporária')
        return 'Resposta da segunda'
    p=partida(tmp_path,modelo)
    p.conversar('Primeira');assert inicio.wait(1)
    p.conversar('Segunda');liberar.set();deadline=time.monotonic()+3
    while time.monotonic()<deadline and p.chat_ocupado:time.sleep(.01)
    respostas=[m for m in p.estado()['mensagens'] if m['role']=='assistant']
    assert respostas[0]['erro'] and 'Falha temporária' in respostas[0]['content']
    assert respostas[1]['content']=='Resposta da segunda'
    assert p.estado()['conversa']['estado']=='pronto'


def test_narracoes_proximas_aguardam_sem_sumir(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import time
    inicio,liberar=threading.Event(),threading.Event()
    faladas=[]
    def falar(texto):
        faladas.append(texto)
        if texto=='Primeira':inicio.set();assert liberar.wait(3)
    monkeypatch.setitem(sys.modules,'voz',SimpleNamespace(falar=falar,mudo=threading.Event(),falar_ativo=threading.Event()))
    p=partida(tmp_path,lambda *a,**kw:'Oi');p.dados['voz']=True
    a=threading.Thread(target=p._narrar,args=(p.dados['id'],'Primeira'));a.start();assert inicio.wait(1)
    b=threading.Thread(target=p._narrar,args=(p.dados['id'],'Segunda'));b.start()
    time.sleep(.03);assert b.is_alive()
    liberar.set();a.join(2);b.join(2)
    assert faladas==['Primeira','Segunda']


def test_prompt_competitivo_preserva_palavroes_e_exige_base_para_critica(tmp_path):
    p=partida(tmp_path,lambda *a,**kw:'Peguei seu peão, porra!')
    p.conversar('Como tá a partida?');p.worker_chat.join(2)
    assert p.estado()['mensagens'][-1]['content']=='Peguei seu peão, porra!'
    ctx=p.estado();ctx['pedido']='Como tá?'
    sistema=Partida.mensagens_conversa(ctx)[0]['content']
    assert 'competitiva e provocadora' in sistema
    assert 'Palavrões naturais' in sistema
    assert 'perda_estimada_cp >= 150' in sistema
    assert 'valores menores não provam gafe' in sistema


def test_atualizar_contexto_de_partida_reaberta_sem_cancelar_calculo(tmp_path):
    p=partida(tmp_path,lambda *a,**kw:'Oi')
    p.dados['posicao']['fatos']={'avaliacao_ultimo_lance':{'perda_estimada_cp':200}}
    p.dados['lance']={'estado':'pensando'}
    novo=posicao(fatos={**fatos_lance(0),'tatico':{'vez':'Emily','capturas_legais_agora':[]}})
    assert p.atualizar_contexto(novo,1)['ok']
    assert p.estado()['revisao']==1 and p.estado()['lance']['estado']=='pensando'
    assert p.estado()['posicao']['fatos']['tatico']['vez']=='Emily'
    assert p.estado()['posicao']['fatos']['avaliacao_ultimo_lance']['perda_estimada_cp']==200
    assert not p.atualizar_contexto(novo,0)['ok']
    diferente={**novo,'pgn':'1. e4'}
    assert not p.atualizar_contexto(diferente,1)['ok']


def test_avaliacao_recente_preservada_no_lance_seguinte_e_removida_ao_desfazer(tmp_path):
    p=partida(tmp_path,lambda *a,**kw:'Oi')
    p.dados['posicao']['fatos']=fatos_lance(1)
    p.dados['posicao']['fatos']['avaliacao_ultimo_lance']={'ator':'Você','perda_estimada_cp':200}
    novo=posicao(fatos={**fatos_lance(2),'fen_antes_ultimo_lance':FEN})
    p.sincronizar(novo,1)
    registro=p.estado()['posicao']['fatos']['avaliacoes_recentes'][0]
    assert registro['ator']=='Você' and registro['meio_lance']==1
    assert 'avaliacao_ultimo_lance' not in p.estado()['posicao']['fatos']
    p.sincronizar(posicao(fatos={**fatos_lance(1),'fen_antes_ultimo_lance':FEN}),2)
    assert 'avaliacoes_recentes' not in p.estado()['posicao']['fatos']


def test_guia_de_conversa_usa_snapshot_sem_mudar_partida(tmp_path):
    chamadas=[]
    def guia(pos,cancelado):
        assert not cancelado()
        return {'fen_base':pos['fen'],'linhas_uci':[['e2e4','e7e5']]}
    p=Partida(tmp_path/'g.json',chamar=lambda msgs,**kw:chamadas.append(msgs) or 'Bora.',analise=guia)
    p.sincronizar(posicao(),0,nova=True)
    p.conversar('E depois desse lance?');p.worker_chat.join(2)
    assert 'analise_curta_verificada' in chamadas[0][-1]['content']
    assert 'analise_curta_verificada' not in p.estado()['posicao']['fatos']
    assert p.estado()['posicao']['fen']==FEN
    assert p.estado()['mensagens'][-1]['content']=='Bora.'


def test_falha_do_motor_da_conversa_nao_perde_pergunta(tmp_path):
    def falha(*a):raise TimeoutError('motor ocupado')
    p=Partida(tmp_path/'g.json',chamar=lambda *a,**kw:'Ouvi você.',analise=falha)
    p.sincronizar(posicao(),0,nova=True)
    p.conversar('Como você tá?');p.worker_chat.join(2)
    assert p.estado()['mensagens'][-1]['content']=='Ouvi você.'
    assert p.estado()['conversa']['estado']=='pronto'


def test_guia_de_outra_posicao_nao_vaza_para_resposta(tmp_path):
    chamadas=[]
    p=Partida(tmp_path/'g.json',chamar=lambda msgs,**kw:chamadas.append(msgs) or 'Tá.',
        analise=lambda *a:{'fen_base':'outra posição','linhas_uci':[['e2e4']]})
    p.sincronizar(posicao(),0,nova=True)
    p.conversar('E aí?');p.worker_chat.join(2)
    assert 'analise_curta_verificada' not in chamadas[0][-1]['content']

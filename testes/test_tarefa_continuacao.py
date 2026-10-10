"""Regressões da parada prematura e da retomada sem perder evidências."""
import json
import pytest

@pytest.fixture
def agent(monkeypatch, tmp_path):
    import modelo as m, llm, ferramentas as f, politica_agente as p, tarefa_pendente as t, contexto_chat
    tool = f.Ferramenta(nome='teste_etapa_continuacao', descricao='Leitura local de teste',
        propriedades={'indice': {'type': 'integer'}}, obrigatorios=[], somente_leitura=True,
        executar=lambda indice=0: 'etapa verificada '+str(indice))
    monkeypatch.setitem(f.CATALOGO, tool.nome, tool)
    monkeypatch.setattr(f, 'esquemas_com_dominios', lambda *a, **k: [{'type':'function','function':{
        'name':tool.nome,'parameters':{'type':'object','properties':{'indice':{'type':'integer'}}}}}])
    for name in ['_registrar_memoria_unificada','_envelhecer_dominios','registrar_ferramenta_executada']:
        monkeypatch.setattr(m, name, lambda *a, **k: None)
    monkeypatch.setattr(m, '_mensagens_para_turno', lambda extra='': [])
    monkeypatch.setattr(m, '_memoria_unificada_ativa', lambda: True)
    monkeypatch.setattr(m, 'web_turno_cid', lambda: 'conversa-teste')
    monkeypatch.setattr(t, 'ROOT', tmp_path/'pending')
    monkeypatch.setattr(contexto_chat, 'ROOT', tmp_path/'archives')
    old = m.historico.copy()
    m.historico.clear()
    requests=[]
    real_review = p.revisar_apos_ferramentas
    def run(sequence, reviews, pedido='Corrija, teste e aplique a mudança.', structured=False):
        seq=iter(sequence); rev=iter(reviews)
        class Flow:
            def __init__(self, step):
                self.step=step;self.preambulo='';self.chamadas=[]
                if isinstance(step,int):
                    self.chamadas=[llm.ChamadaFerramenta(id=str(len(requests)),nome=tool.nome,argumentos=json.dumps({'indice':step}))]
            def quer_ferramenta(self): return isinstance(self.step,int)
            def texto(self): return iter([self.step if isinstance(self.step,str) else ''])
        def request(messages, **kw):
            requests.append(messages.copy());return Flow(next(seq))
        monkeypatch.setattr(llm,'chamar_com_ferramentas',request)
        if structured:
            monkeypatch.setattr(p,'revisar_apos_ferramentas',real_review)
            monkeypatch.setattr(llm,'chamar',lambda *a,**kw:json.dumps(next(rev)))
        else:
            monkeypatch.setattr(p,'revisar_apos_ferramentas',lambda pedido,texto,*a:dict(next(rev),texto=texto))
        return m.conversar_com_ferramentas(pedido,canal='web')
    yield run,m,t,requests
    m.historico[:]=old


def test_muitas_correcoes_com_progresso_nao_encerram_tarefa(agent):
    run,m,t,requests=agent
    sequence=[];reviews=[]
    for i in range(5):
        sequence += [i, 'Corrigi o teste; falta verificar e aplicar.']
        reviews += [{'continuar':True}]
    sequence += [5,'Tudo testado e aplicado.']
    reviews += [{'continuar':False,'tarefa_encerrada':True}]
    assert run(sequence,reviews)=='Tudo testado e aplicado.'
    assert len(requests)==12
    assert t.restore(':conversa-teste',m.historico) is None


def test_repetir_resposta_sem_avanco_interrompe_com_estado_pendente(agent):
    run,m,t,requests=agent
    result=run([0]+['Vou continuar.']*4,[{'continuar':True}]*4)
    assert 'continua pendente' in result
    assert t.restore(':conversa-teste',m.historico) is not None
    assert len(requests)==5
    # Um turno novo recebe a evidência de ferramentas mesmo antes de usar outra.
    assert run([1,'Agora testei e apliquei.'],[{'continuar':False,'tarefa_encerrada':True}],
               'Ué, por que parou antes de terminar?')=='Agora testei e apliquei.'
    assert any(msg.get('content','').startswith(t.MARKER) for msg in requests[-2]
               if isinstance(msg.get('content'),str))
    assert t.restore(':conversa-teste',m.historico) is None


def test_registro_nao_vaza_conversas_nem_ramos(monkeypatch,tmp_path):
    import tarefa_pendente as t, contexto_chat
    monkeypatch.setattr(t,'ROOT',tmp_path/'pending')
    monkeypatch.setattr(contexto_chat,'ROOT',tmp_path/'archive')
    history=[{'role':'user','content':'Corrija o botão'}]
    messages=history+[{'role':'tool','content':'teste passou; falta aplicar'}]
    t.save('a',history,messages)
    assert t.restore('a',history+[{'role':'assistant','content':'interrupção'}])
    assert t.restore('b',history) is None
    assert t.restore('a',[{'role':'user','content':'Não faça nada'}]) is None
    record=json.loads(t._path('a').read_text())
    assert contexto_chat.recover(record['archive'])


def test_revisao_retomada_usa_objetivo_antigo_e_evidencia(monkeypatch):
    import politica_agente as p, llm, tarefa_pendente as t
    received=[]
    monkeypatch.setattr(llm,'chamar',lambda messages,**kw:received.append(json.loads(messages[-1]['content'])) or
                        '{"continuar":true,"texto":"Ainda falta aplicar.","tarefa_encerrada":false}')
    messages=[{'role':'user','content':'Corrija, teste e aplique.'}]+[
        {'role':'assistant','content':'etapa '+str(i)} for i in range(30)]+[
        {'role':'system','content':t.MARKER+'Teste aprovado; falta aplicar.'},
        {'role':'user','content':'Por que você parou?'}]
    result=p.revisar_apos_ferramentas('Por que você parou?','Vou continuar.',messages,'conversa')
    assert result['continuar'] and not result['tarefa_encerrada']
    assert received[0]['registro'][0]==messages[0]


def test_explica_sem_executar_e_preserva_pendencia_ate_cancelamento(agent):
    run,m,t,requests=agent
    run([0]+['Falta aplicar.']*4,[{'continuar':True}]*4)
    result=run(['Vou explicar o motivo.'],[{'continuar':False,'tarefa_encerrada':False}],
               'Só explique, não continue agora.')
    assert result=='Vou explicar o motivo.'
    assert t.restore(':conversa-teste',m.historico)
    result=run(['Cancelei a tarefa.'],[{'continuar':False,'tarefa_encerrada':True}],
               'Cancele essa tarefa.')
    assert result=='Cancelei a tarefa.'
    assert t.restore(':conversa-teste',m.historico) is None


def test_revisao_invalida_tem_recuperacao_e_nao_encerra_pendencia(monkeypatch):
    import llm, politica_agente as p
    replies=iter(['inválido','{"continuar":true,"texto":"Falta aplicar.","tarefa_encerrada":false}'])
    monkeypatch.setattr(llm,'chamar',lambda *a,**kw:next(replies))
    messages=[{'role':'tool','content':'testes passaram; não aplicado'}]
    assert p.revisar_apos_ferramentas('Teste e aplique.','Falta aplicar.',messages,'conversa')['continuar']
    monkeypatch.setattr(llm,'chamar',lambda *a,**kw:'inválido')
    result=p.revisar_apos_ferramentas('Teste e aplique.','Pronto.',messages,'conversa')
    assert not result['tarefa_encerrada'] and result['revisao_indisponivel']
    assert 'pendente' in result['texto']


def test_tarefa_real_continua_apos_mais_de_180_rodadas(agent):
    run,m,t,requests=agent
    assert run(list(range(200))+['Testado e aplicado.'],[{'continuar':False,'tarefa_encerrada':True}]) == 'Testado e aplicado.'
    assert len(requests)==201
    assert t.restore(':conversa-teste',m.historico) is None


def test_consultas_iguais_ao_teste_ativo_nao_impedem_aplicacao(agent, monkeypatch):
    run,m,t,requests=agent
    import ferramentas as f
    tool=f.CATALOGO['teste_etapa_continuacao']
    monkeypatch.setattr(tool,'nome','programacao_status')
    monkeypatch.setitem(f.CATALOGO,'programacao_status',tool)
    monkeypatch.setattr(tool,'executar',lambda indice=0: json.dumps(dict(ok=True,trabalho='job',estado='executando' if indice==0 else 'concluido')))
    assert run([0]*40+[1, 'Teste terminou e mudança aplicada.'],[{'continuar':False,'tarefa_encerrada':True}]) == 'Teste terminou e mudança aplicada.'
    assert len(requests)==42


def test_incomplete_draft_does_not_end_real_loop_or_require_confirmation(agent):
    run,m,t,requests=agent
    answer=run([0,'Preparei a cópia. Quer que eu aplique?',1,'Mudança testada e aplicada.'],[
        {'desfecho':'concluido','continuar':False,'texto':'Preparei a cópia. Quer que eu aplique?',
         'pendencias':['aplicar a mudança autorizada'],'evidencia_conclusao':'cópia preparada'},
        {'desfecho':'concluido','texto':'Mudança testada e aplicada.','pendencias':[],
         'evidencia_conclusao':'ferramentas confirmaram a aplicação'}],structured=True)
    assert answer=='Mudança testada e aplicada.'
    assert len(requests)==4
    assert t.restore(':conversa-teste',m.historico) is None


def test_optional_confirmation_does_not_stop_but_indispensable_decision_does(agent):
    run,m,t,requests=agent
    answer=run([0,'Posso continuar?',1,'Preciso da decisão sobre excluir os dados.'],[
        {'desfecho':'aguardando_usuario','texto':'Posso continuar?',
         'dependencia_humana':False,'motivo_parada':'reconfirmar aplicação já autorizada'},
        {'desfecho':'aguardando_usuario','texto':'Preciso da decisão sobre excluir os dados.',
         'dependencia_humana':True,'motivo_parada':'Exclusão irreversível não autorizada; não há etapa independente.'}],structured=True)
    assert answer=='Preciso da decisão sobre excluir os dados.'
    assert len(requests)==4
    assert t.restore(':conversa-teste',m.historico)


@pytest.mark.parametrize('value,continues',[
    ({'desfecho':'bloqueado','motivo_parada':'primeiro teste falhou','alternativas_esgotadas':False},True),
    ({'desfecho':'bloqueado','motivo_parada':'serviço inacessível após alternativas','alternativas_esgotadas':True},False),
    ({'desfecho':'concluido','evidencia_conclusao':''},True),
    ({'desfecho':'cancelado'},False),
    ({'desfecho':'conversa'},False)])
def test_stopping_condition_is_required(value,continues):
    import politica_agente as p
    assert p.normalizar_revisao(value)['continuar']==continues


def test_bare_false_is_not_valid_completion():
    import politica_agente as p
    with pytest.raises(ValueError):p.normalizar_revisao({'continuar':False,'texto':'Parei.'})

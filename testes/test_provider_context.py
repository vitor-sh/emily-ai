from types import SimpleNamespace as N
import json
import llm
import contexto_chat as c
import limites_modelos as limits


def test_native_tools_preserve_parallel_results_and_multimodal():
    p=llm.ProvedorAnthropic('teste',None,'unused')
    messages=llm.normalizar_mensagens([
        {'role':'system','content':'policy'},
        {'role':'user','content':'go'},
        {'role':'assistant','content':'vou olhar','tool_calls':[{'id':'a','function':{'name':'ler','arguments':'{"x":1}'}},{'id':'b','function':{'name':'buscar','arguments':'{}'}}]},
        {'role':'tool','tool_call_id':'a','content':'A'},
        {'role':'tool','tool_call_id':'b','content':'B'},
        {'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,abcd'}}]}])
    system,rows=p._montar(messages)
    assert system=='policy'
    assert rows[1]['content'][1]['input']=={'x':1}
    assert [b['tool_use_id'] for b in rows[2]['content'][:2]]==['a','b']
    assert rows[2]['content'][2]['type']=='image'


def test_native_stream_retains_preamble_json_fragments_and_ids():
    events=iter([
        N(type='content_block_delta',index=0,delta=N(type='text_delta',text='Vou olhar.')),
        N(type='content_block_start',index=1,content_block=N(type='tool_use',id='tool-a',name='ler')),
        N(type='content_block_delta',index=1,delta=N(type='input_json_delta',partial_json='{"x":')),
        N(type='content_block_delta',index=1,delta=N(type='input_json_delta',partial_json='1}')),
        N(type='message_delta',delta=N(stop_reason='tool_use'))])
    stream=llm.FluxoComFerramentas(llm.ProvedorAnthropic._eventos_ferramentas(events))
    assert stream.quer_ferramenta()
    calls=stream.chamadas
    assert len(calls)==1 and calls[0].id=='tool-a' and calls[0].args()=={'x':1}
    assert ''.join(stream.texto())=='Vou olhar.'


def test_native_tool_payload_and_model_specific_forcing(monkeypatch):
    body={}
    client=N(messages=N(create=lambda **kwargs:(body.update(kwargs) or N(content=[N(type='tool_use',id='a',name='ler',input={'x':1})]))))
    p=llm.ProvedorAnthropic('teste',None,'unused')
    monkeypatch.setattr(p,'_obter_cliente',lambda:client)
    tools=[{'type':'function','function':{'name':'ler','parameters':{'type':'object','properties':{'x':{'type':'integer'}}}}}]
    result=p.chamar(llm.normalizar_mensagens([{'role':'user','content':'go'}]),'claude-sonnet-5.5',512,None,'medio',False,tools,True)
    assert body['tool_choice']=={'type':'auto'}
    assert body['tools'][0]['input_schema']==tools[0]['function']['parameters']
    assert result.chamadas[0].args()=={'x':1}
    assert p.suporta_ferramentas


def test_display_cannot_overwrite_real_request_with_partial_history(monkeypatch):
    monkeypatch.setattr(c,'profile',lambda m:{'model':m,'limit':100000,'effective_limit':95000,'threshold':68000})
    key='test-display';messages=[{'role':'user','content':'long '*500}];tools=[{'schema':'large '*1000}]
    first=c.meter(messages,tools,'first',key=key)
    assert c.display(key,'first',[])==first
    second=c.display(key,'second',[])
    assert second['used']==first['used']
    assert second['model']=='second'
    assert c.state(key)['used']==first['used']


def test_models_use_route_catalog_and_codex_only_on_codex_route(monkeypatch):
    monkeypatch.setattr(limits,'provedor',lambda m:'test')
    monkeypatch.setattr(limits,'catalogo',lambda pid:{'claude-sonnet-5':1000000,'claude-haiku-4.5':200000,'other':64000})
    assert c.profile('claude-sonnet-5')['limit']==1000000
    assert c.profile('claude-haiku-4.5')['limit']==200000
    assert c.profile('other')['limit']==64000
    assert c.profile('cx/gpt-6-sol')['limit']==272000
    assert c.profile('gpt-6-sol')['limit']!=272000

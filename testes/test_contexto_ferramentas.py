import json
from contexto_ferramentas import mensagens_economicas


def test_repeticao_preserva_primeiro_log_e_estado_atual_sem_reenvio():
    cache={}
    def message(state,output,id):return {'role':'tool','tool_call_id':id,'content':json.dumps(dict(trabalho='j',estado=state,saida=output,ok=True))}
    first=message('executando','log longo'*1000,'1')
    assert mensagens_economicas([first],cache)==[first]
    second=json.loads(mensagens_economicas([message('concluido','log longo'*1000,'2')],cache)[0]['content'])
    assert second['estado']=='concluido' and second['saida']=='' and second['saida_referencia_tool_call_id']=='1'
    third=message('concluido','log novo','3')
    assert mensagens_economicas([third],cache)==[third]
    assert mensagens_economicas([{'content':'texto normal'}],cache)==[{'content':'texto normal'}]

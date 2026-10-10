"""Evita retransmitir logs idênticos sem cortar evidência nova ou estado atual."""
import json


def mensagens_economicas(mensagens, cache):
    result=[]
    for msg in mensagens:
        try:
            data=json.loads(msg.get('content',''))
        except (ValueError,TypeError):
            result.append(msg);continue
        job=data.get('publicacao') or data if isinstance(data,dict) else None
        if isinstance(job,dict) and job.get('trabalho') and isinstance(job.get('saida'),str) and job['saida']:
            key=job['trabalho'];output=job['saida']
            prior=cache.get(key)
            if prior and prior[0]==output:
                job['saida']=''
                job['saida_inalterada']=True
                job['saida_referencia_tool_call_id']=prior[1]
                msg=dict(msg,content=json.dumps(data,ensure_ascii=False))
            else: cache[key]=(output,msg.get('tool_call_id',''))
        result.append(msg)
    return result

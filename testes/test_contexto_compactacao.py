import copy
import json
from pathlib import Path
import pytest
import contexto_chat as c
import uso_codex as u

@pytest.fixture
def compact(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'ROOT',tmp_path)
    monkeypatch.setattr(c,'profile',lambda model:{'model':model,'limit':60000,'effective_limit':57000,'threshold':35000,'source':'test'})
    return [{'role':'user' if i%2==0 else 'assistant','content':f'item-{i} preservado\n'+('fala abcdefg '*110)} for i in range(90)]

def summary(messages,model):
    result={key:[] for key in c.KEYS}
    result['detalhes_exatos']=[m['content'].split('\n')[0] for m in messages]
    return result

def test_compaction_preserves_recent_original_and_resume_cache(compact):
    original=copy.deepcopy(compact);events=[];calls=[]
    def summarizer(msgs,model):calls.append(msgs);return summary(msgs,model)
    result,state=c.prepare(compact,[], 'cx/gpt-6-sol',summarize=summarizer,progress=lambda phase,data:events.append(data))
    assert compact==original
    assert state['used']<state['before'] and state['compacted']
    assert result[-24:]==original[-24:]
    assert events[0]['estado']=='inicio' and events[-1]['estado']=='concluido'
    recovered=c.recover(state['archive'],consulta='item-0')
    assert recovered['trechos'][0]['mensagem']==original[0]
    previous_calls=len(calls)
    # An unchanged prefix must reuse summaries instead of calling the model again.
    second,_=c.prepare(compact,[],'cx/gpt-6-sol',summarize=summarizer)
    assert len(calls)==previous_calls
    assert second[-24:]==original[-24:]

def test_invalid_summary_never_drops_original(compact):
    original=copy.deepcopy(compact)
    with pytest.raises(c.ContextoCheio):c.prepare(compact,[],'cx/gpt-6-sol',summarize=lambda *_:'not json')
    assert compact==original
    assert list(c.ROOT.glob('*.json'))
    assert not (c.ROOT/'index.json').exists()

def test_tool_groups_are_atomic_and_pending_rejected():
    messages=[{'role':'user','content':'faça'}, {'role':'assistant','tool_calls':[{'id':'a'},{'id':'b'}]},
              {'role':'tool','tool_call_id':'a','content':'ok'},{'role':'tool','tool_call_id':'b','content':'ok'},
              {'role':'assistant','content':'done'}]
    assert c._boundaries(messages)==[0,1,4]
    with pytest.raises(c.ContextoCheio):c._boundaries(messages[:3])

def test_large_original_can_be_read_to_end(compact):
    message={'role':'tool','content':'Á'*60000+'ENDING'};ident=c.archive([message]);chunks=[];start=0
    while True:
        part=c.read_message(ident,0,start,12000);chunks.append(part['texto'])
        if part['proximo'] is None:break
        start=part['proximo']
    assert json.loads(''.join(chunks))==message
    assert c.recover(ident)['trechos'][0]['truncado']
    with pytest.raises(ValueError):c.recover('../../private')

def test_estimate_images_does_not_count_base64_as_text():
    image=[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+'a'*3000000}}]}]
    assert 4096 <= c.estimate(image)<5000

def test_real_codex_profile_is_not_api_million_context():
    for model in ['cx/gpt-6-sol','cx/gpt-6-luna','cx/gpt-6-astra']:
        assert c.profile(model)['limit']==272000
        assert c.profile(model)['effective_limit']==258400

def test_usage_zero_and_missing_not_fabricated():
    normalized=u.normalize({'quotas':{'session':{'used':0,'total':100,'resetAt':'2026-10-08T00:00:00Z'},'weekly':{'used':49,'total':100}}})
    assert normalized[0]['used_percent']==0 and normalized[0]['remaining_percent']==100
    assert normalized[1]['used_percent']==49
    assert u.normalize({'quotas':{}})==[]
    assert u.normalize({'quotas':{'session':{'used':0,'total':None}}})==[]

def test_fork_edit_does_not_reuse_unrelated_summary(compact):
    c.prepare(compact,[],'cx/gpt-6-sol',summarize=summary)
    branch=copy.deepcopy(compact);branch[0]['content']='corrigido '+branch[0]['content'];calls=[]
    c.prepare(branch,[],'cx/gpt-6-sol',summarize=lambda m,n:(calls.append(m) or summary(m,n)))
    assert calls

def test_no_single_turn_silent_truncation(compact):
    original=[{'role':'user','content':'z'*180000}]
    events=[]
    with pytest.raises(c.ContextoCheio):c.prepare(original,[],'cx/gpt-6-sol',summarize=summary,progress=lambda _,data:events.append(data))
    assert events[-1]['estado']=='erro'
    assert len(original[0]['content'])==180000

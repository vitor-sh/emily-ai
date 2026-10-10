import pytest
from types import SimpleNamespace

@pytest.mark.parametrize('late',[False,True])
def test_preambulos_em_ordem_nao_viram_resposta_final(monkeypatch,late):
    import modelo as m
    import llm, ferramentas as f, politica_agente as p
    events=[];requests=[]
    tool=f.Ferramenta(nome='teste_leitura_progresso',descricao='Leitura de teste',propriedades={'indice':{'type':'integer'}},obrigatorios=[],somente_leitura=True,executar=lambda indice=0:'ok')
    monkeypatch.setitem(f.CATALOGO,tool.nome,tool)
    monkeypatch.setattr(f,'esquemas_com_dominios',lambda *a,**kw:[{'type':'function','function':{'name':tool.nome,'description':tool.descricao,'parameters':{'type':'object','properties':{}}}}])
    for name in ['_registrar_memoria_unificada','_envelhecer_dominios','registrar_ferramenta_executada']:
        monkeypatch.setattr(m,name,lambda *a,**kw:None)
    monkeypatch.setattr(m,'_mensagens_para_turno',lambda extra='':[])
    monkeypatch.setattr(m,'_memoria_unificada_ativa',lambda:True)
    monkeypatch.setattr(p,'revisar_apos_ferramentas',lambda pedido,texto,*a:{'texto':texto,'continuar':False})
    phrases=['Vou começar conferindo o recurso compartilhado.','Encontrei a causa; vou verificar o segundo seletor.']
    class Flow:
        def __init__(self,index):self.index=index;self.preambulo=phrases[index] if index<2 else '';self.chamadas=[] if late or index>=2 else [llm.ChamadaFerramenta(id=str(index),nome=tool.nome,argumentos='{"indice":'+str(self.index)+'}')]
        def quer_ferramenta(self):return self.index<2 and not late
        def texto(self):
            if self.index<2:
                self.chamadas=[llm.ChamadaFerramenta(id=str(self.index),nome=tool.nome,argumentos='{"indice":'+str(self.index)+'}')]
                return iter([phrases[self.index]])
            return iter(['Resultado verificado.'])
    def request(messages,**kw):requests.append(messages.copy());return Flow(len(requests)-1)
    monkeypatch.setattr(llm,'chamar_com_ferramentas',request)
    before=m.historico.copy()
    try:
        m.historico.clear()
        result=m.conversar_com_ferramentas('Confira os dois seletores.',on_progresso=lambda phase,data:events.append((phase,data)),canal='web')
        assert result=='Resultado verificado.'
        assert [data['texto'] for phase,data in events if phase=='fala']==phrases
        phases=[phase for phase,data in events if phase in {'fala','ferramenta','resultado'}]
        assert phases==['fala','ferramenta','resultado','fala','ferramenta','resultado']
        assert requests[1][-2]['content']==phrases[0]
    finally:m.historico[:]=before


def test_comentario_embutido_nao_vaza_para_ferramenta():
    import modelo as m, llm
    original=[{'type':'function','function':{'name':'ler','parameters':{'type':'object','properties':{'arquivo':{'type':'string'}},'required':['arquivo']}}}]
    catalog=m._catalogo_com_comentario(original,inicial=True)
    assert 'comentario_progresso' in catalog[0]['function']['parameters']['required']
    assert 'comentario_progresso' not in original[0]['function']['parameters']['properties']
    calls=[llm.ChamadaFerramenta(id='a',nome='ler',argumentos='{"arquivo":"web/app.js","comentario_progresso":"Vou conferir a interface."}')]
    assert m._extrair_comentarios(calls)==['Vou conferir a interface.']
    assert calls[0].args()=={'arquivo':'web/app.js'}

import json
from orcamento_agente import OrcamentoAgente, trabalho_ativo


def test_progresso_nao_tem_teto_total_de_etapas_ou_tempo():
    now = [0]
    budget = OrcamentoAgente(clock=lambda: now[0])
    for step in range(250):
        now[0] += 60
        budget.registrar([str(step)])
        assert not budget.interromper()


def test_espera_confirmada_nao_vira_estagnacao():
    now = [0]
    budget = OrcamentoAgente(clock=lambda: now[0])
    for _ in range(200):
        now[0] += 10
        budget.registrar(['mesmo status'], aguardando=True)
        assert not budget.interromper()
    for _ in range(8):
        budget.registrar(['mesmo status'])
    assert budget.interromper()


def test_janela_de_inatividade_recomeca_apos_atividade():
    now = [0]
    budget = OrcamentoAgente(clock=lambda: now[0])
    now[0] = 590
    budget.registrar(['resultado novo'])
    now[0] = 610
    assert not budget.interromper()
    now[0] = 1190
    assert budget.interromper()


def test_apenas_status_estruturado_confirma_espera():
    data = dict(ok=True, trabalho='job', estado='executando')
    assert trabalho_ativo('programacao_status', json.dumps(data))
    assert trabalho_ativo('programacao_status', json.dumps(dict(ok=True, publicacao=data)))
    assert not trabalho_ativo('programacao_previa', json.dumps(data))
    assert not trabalho_ativo('programacao_status', 'O teste está executando')
    assert not trabalho_ativo('programacao_status', json.dumps(dict(data, estado='falhou')))
    assert not trabalho_ativo('programacao_status', json.dumps(dict(data, ok=False)))

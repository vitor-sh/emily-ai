"""Pedidos curtos de retry retomam apenas a tarefa pendente do mesmo chat."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.mark.parametrize("frase", ["continue", "tenta de novo", "ver se agora vai",
                                     "Continue de onde parou", "tente novamente",
                                     "Tenta de novo emily", "Emily, tenta de novo",
                                     "Tenta de novo, Emilyy!"])
def test_retry_reencontra_pedido_de_navegador_apos_reabrir_chat(frase):
    import modelo

    pedido = "Use o seu navegador para ver o preço do ingresso no cinema Estação BH"
    historico_salvo = [
        {"role": "user", "content": pedido},
        {"role": "assistant", "content": "Não consegui consultar o preço: o navegador não está acessível."},
    ]
    assert modelo._pedido_pendente_para_retentativa(frase, historico_salvo) == pedido


def test_retry_reabre_pedido_apos_confirmacao_e_duas_falhas_salvas():
    import modelo

    pedido = ("Oi emilyy, tu pode usar o seu navegador pra ver o preço pra min "
              "do ingresso do filme do Resident evil no shopping estação cinema?")
    historico_salvo = [
        {"role": "user", "content": pedido},
        {"role": "assistant", "content": "É pra sexta-feira, 2 de outubro?"},
        {"role": "user", "content": "Sim sim, isso mesmo"},
        {"role": "assistant", "content": "Meu navegador não está acessível nesta tentativa."},
        {"role": "user", "content": "Tenta de novo emily"},
        {"role": "assistant", "content": "Tentei de novo, mas ainda tô sem acesso ao navegador."},
    ]
    assert modelo._pedido_pendente_para_retentativa("Tenta de novo emily", historico_salvo) == pedido
    assert modelo._pedido_pendente_para_retentativa("ver se agora vai", historico_salvo) == pedido


def test_retry_de_arquivo_pula_confirmacoes_curtas_mas_nao_outro_assunto(monkeypatch):
    import modelo

    monkeypatch.setattr(modelo, "chamar_llm_simples", lambda *_a, **_kw: "NOVA")

    pedido = "Crie a pasta Relatorios e um arquivo de texto dentro dela"
    historico = [
        {"role": "user", "content": pedido},
        {"role": "assistant", "content": "Qual nome você quer dar ao arquivo?"},
        {"role": "user", "content": "Sim, isso mesmo"},
        {"role": "assistant", "content": "Não consegui criar o arquivo."},
        {"role": "user", "content": "tenta de novo"},
        {"role": "assistant", "content": "Deu erro novamente."},
    ]
    assert modelo._pedido_pendente_para_retentativa("continue", historico) == pedido
    assert not modelo._pedido_pendente_para_retentativa(
        "continue", [{"role": "user", "content": pedido},
                     {"role": "assistant", "content": "Criei e conferi o arquivo."}])
    assert modelo._pedido_pendente_para_retentativa(
        "tenta de novo", [{"role": "user", "content": pedido},
                          {"role": "assistant", "content": "Criei e conferi o arquivo."}]) == pedido
    assert not modelo._pedido_pendente_para_retentativa(
        "continue escrevendo a carta", historico)
    outro_assunto = historico[:2] + [
        {"role": "user", "content": "Como está o tempo hoje?"},
        {"role": "assistant", "content": "Não consigo confirmar a previsão."},
    ]
    assert modelo._pedido_pendente_para_retentativa("continue", outro_assunto) == "Como está o tempo hoje?"


def test_retomada_ambigua_usa_contexto_e_nao_reaproveita_tarefa_em_outro_assunto(monkeypatch):
    import modelo

    pedido = "Use seu navegador para encontrar os ingressos no cinema Estação BH"
    historico = [
        {"role": "user", "content": pedido},
        {"role": "assistant", "content": "Ainda não consegui ver os preços, fiquei sem acesso."},
    ]
    decisoes = iter(["RETOMAR", "NOVA", "CONVERSAR"])
    chamadas = []

    def classificar(prompt, **_kw):
        chamadas.append(prompt)
        return next(decisoes)

    monkeypatch.setattr(modelo, "chamar_llm_simples", classificar)
    assert modelo._pedido_pendente_para_retentativa(
        "Vamos por outro site então", historico) == pedido
    assert not modelo._pedido_pendente_para_retentativa(
        "Agora cria um documento novo", historico)
    assert not modelo._pedido_pendente_para_retentativa(
        "Que pena, obrigado pelo esforço", historico)
    assert len(chamadas) == 3

    monkeypatch.setattr(modelo, "chamar_llm_simples", lambda *_a, **_kw:
                        pytest.fail("frase clara não deveria chamar a LLM auxiliar"))
    assert modelo._pedido_pendente_para_retentativa("Tenta de novo emily", historico) == pedido


def test_nova_conversa_pessoal_nao_herda_retentativa_contextual(monkeypatch):
    import ferramentas
    import llm
    import modelo

    pedido_antigo = "Abra o navegador e veja os ingressos do cinema"
    mensagem = "Lembra que eu falei que ia conversar com uma amiga? Aconteceu."

    class FluxoTexto:
        chamadas = []

        def quer_ferramenta(self):
            return False

        def texto(self):
            return iter(["Entendi. Como ela reagiu?"])

    monkeypatch.setattr(modelo, "_pedido_pendente_para_retentativa",
                        lambda *_a: pedido_antigo)
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda _extra="": [])
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: None)
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "_envelhecer_dominios", lambda: None)
    monkeypatch.setattr(ferramentas, "esquemas_com_dominios", lambda *_a, **_k: [])
    monkeypatch.setattr(llm, "chamar_com_ferramentas", lambda *_a, **_k: FluxoTexto())
    anterior = list(modelo.historico)
    try:
        modelo.historico.clear()
        resposta = modelo.conversar_com_ferramentas(mensagem, canal="web")
    finally:
        modelo.historico[:] = anterior
    assert resposta == "Entendi. Como ela reagiu?"


def test_condicional_social_nao_vira_falha_de_ferramenta(monkeypatch):
    import classificacao_ferramentas as cf
    import modelo

    pergunta = ("Obrigado por conversar comigo. Vou esperar uma oportunidade "
                "para falar com ela. O que você acha?")
    resposta = ("Se ela não conseguir te ouvir depois de você falar, "
                "aí você já sabe a resposta. Desabafa aqui de novo.")
    historico = [{"role": "user", "content": pergunta},
                 {"role": "assistant", "content": resposta}]
    monkeypatch.setattr(modelo, "chamar_llm_simples", lambda *_a, **_k:
                        pytest.fail("desabafo não precisa classificar retomada"))

    assert not cf.parece_pergunta_factual(pergunta)
    assert not modelo._resposta_indica_tarefa_pendente(resposta)
    assert not modelo._pedido_pendente_para_retentativa(
        "Consegui falar com ela sobre aquele assunto", historico)
    assert modelo._resposta_indica_tarefa_pendente(
        "Não consegui abrir o site; preciso de ajuda.")


def test_continue_apos_passo_parcial_pede_decisao_semantica(monkeypatch):
    import modelo

    pedido = "Veja o preço do ingresso no site do cinema"
    historico = [
        {"role": "user", "content": pedido},
        {"role": "assistant", "content": "Abri a página do cinema."},
    ]
    monkeypatch.setattr(modelo, "chamar_llm_simples", lambda *_a, **_kw: "RETOMAR")
    assert modelo._pedido_pendente_para_retentativa("Continue", historico) == pedido
    monkeypatch.setattr(modelo, "chamar_llm_simples", lambda *_a, **_kw: "CONVERSAR")
    assert not modelo._pedido_pendente_para_retentativa("Continue", historico)


def test_continue_reabre_ferramenta_autorizada_sem_repetir_por_inferencia(monkeypatch):
    import ferramentas
    import llm
    import modelo

    class Fluxo:
        def __init__(self, chamadas=(), texto=""):
            self.chamadas = list(chamadas)
            self.preambulo = ""
            self._texto = texto

        def quer_ferramenta(self):
            return bool(self.chamadas)

        def texto(self):
            return iter([self._texto])

    fluxos = iter([
        Fluxo([llm.ChamadaFerramenta("1", "criar_pasta", '{"nome":"Relatorios"}')]),
        Fluxo(texto="Conferi a pasta Relatorios: ela foi criada."),
    ])
    contextos = []
    monkeypatch.setattr(llm, "chamar_com_ferramentas", lambda *_a, **_kw: next(fluxos))
    monkeypatch.setattr(ferramentas, "executar_estruturado", lambda _n, _a, contexto=None:
                        contextos.append(contexto) or ferramentas.ResultadoFerramenta(
                            "Pasta criada", ok=True, mudou=True))
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda *_a: [
        {"role": "system", "content": "Teste"}])
    monkeypatch.setattr(modelo, "_emitir_fala", lambda *_a, **_kw: None)
    monkeypatch.setattr(modelo, "_falar_aviso", lambda *_a, **_kw: None)
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_kw: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "registrar_ferramenta_executada", lambda *_a: None)
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: None)
    anterior = list(modelo.historico)
    modelo.definir_historico([
        {"role": "user", "content": "Crie a pasta Relatorios"},
        {"role": "assistant", "content": "Não consegui criar a pasta."},
    ])
    try:
        resposta = modelo.conversar_com_ferramentas("continue", canal="web")
        assert resposta == "Conferi a pasta Relatorios: ela foi criada."
        assert contextos and contextos[0]["pedido_explicito"] is True
    finally:
        modelo.definir_historico(anterior)


@pytest.mark.parametrize("frase", ["Tenta de novo emily", "Vamos por outro site então"])
def test_retry_com_vocativo_forca_navegador_se_modelo_repete_negativa(monkeypatch, frase):
    import ferramentas
    import llm
    import modelo

    class Fluxo:
        def __init__(self, chamadas=(), texto=""):
            self.chamadas = list(chamadas)
            self.preambulo = ""
            self._texto = texto

        def quer_ferramenta(self):
            return bool(self.chamadas)

        def texto(self):
            return iter([self._texto])

    chamadas_llm = []
    fluxos = iter([
        Fluxo(texto="Ainda não tenho acesso ao navegador."),
        Fluxo([llm.ChamadaFerramenta(
            "abrir_1", "navegador_interno_abrir",
            '{"endereco":"https://www.google.com/search?q=shopping+esta%C3%A7%C3%A3o+cinema"}')]),
        Fluxo(texto="Abri o navegador e confirmei que ele está acessível."),
    ])

    def chamar(*_a, **kw):
        chamadas_llm.append(kw)
        return next(fluxos)

    execucoes = []
    monkeypatch.setattr(llm, "chamar_com_ferramentas", chamar)
    monkeypatch.setattr(ferramentas, "executar_estruturado", lambda nome, _args, contexto=None:
                        execucoes.append((nome, contexto)) or ferramentas.ResultadoFerramenta(
                            "Navegador aberto, página carregada", ok=True, mudou=True))
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda *_a: [
        {"role": "system", "content": "Teste"}])
    monkeypatch.setattr(modelo, "_emitir_fala", lambda *_a, **_kw: None)
    monkeypatch.setattr(modelo, "_falar_aviso", lambda *_a, **_kw: None)
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_kw: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "registrar_ferramenta_executada", lambda *_a: None)
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: None)
    monkeypatch.setattr(modelo, "chamar_llm_simples", lambda *_a, **_kw: "RETOMAR")

    pedido = "Oi emilyy, tu pode usar o seu navegador pra ver o preço do ingresso?"
    anterior = list(modelo.historico)
    modelo.definir_historico([
        {"role": "user", "content": pedido},
        {"role": "assistant", "content": "É pra sexta-feira, 2 de outubro?"},
        {"role": "user", "content": "Sim sim, isso mesmo"},
        {"role": "assistant", "content": "Meu navegador não está acessível."},
    ])
    try:
        resposta = modelo.conversar_com_ferramentas(frase, canal="web")
        assert resposta == "Abri o navegador e confirmei que ele está acessível."
        assert execucoes[0][0] == "navegador_interno_abrir"
        assert execucoes[0][1]["pedido_explicito"] is True
        assert any(kw.get("obrigar_ferramenta") for kw in chamadas_llm)
    finally:
        modelo.definir_historico(anterior)

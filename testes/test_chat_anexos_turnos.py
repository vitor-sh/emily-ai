"""Regressões de anexos, tarefas interativas e texto quando o TTS falha."""
import sys
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_anexos_reservam_turno_e_texto_seguinte_espera(tmp_path, monkeypatch):
    import interface_web
    import modelo
    iniciou, liberar, terminou = threading.Event(), threading.Event(), threading.Event()
    arquivo = tmp_path / 'imagem.png'
    arquivo.write_bytes(b'arquivo de teste')
    chamadas = []

    class Janela:
        _cid = 'anexos-isolados'
        def _registrar_na_conversa(self, papel, texto, **kwargs):
            assert kwargs['anexos'] == [str(arquivo)]
        def _push(self, *_): pass
        def _chamar_cb(self, cb, *args): cb(*args)
        def callback_arquivos(self, caminhos, texto):
            chamadas.append(('anexos', modelo.web_turno_cid(), texto))
            iniciou.set()
            assert liberar.wait(3)
        def callback_texto(self, texto):
            chamadas.append(('texto', modelo.web_turno_cid(), texto))
            terminou.set()

    janela = Janela()
    api = interface_web.Api(janela)
    monkeypatch.setattr(api, '_demo_ativo', lambda: False)
    try:
        assert api.enviar_arquivos([str(arquivo)], 'O que aparece aqui?') == janela._cid
        assert iniciou.wait(3)
        assert api.enviar_arquivos([str(arquivo)], 'Outra imagem') is None
        assert modelo.web_turno_receber(janela._cid, 'Explique também as cores') == 'adicionada'
        assert len(chamadas) == 1
        liberar.set()
        assert terminou.wait(3)
        assert chamadas == [('anexos', janela._cid, 'O que aparece aqui?'),
                            ('texto', janela._cid, 'Explique também as cores')]
    finally:
        liberar.set()
        modelo.web_turno_liberar(janela._cid)


def test_falha_da_voz_revela_texto_e_continua_stream(monkeypatch):
    import interface_web
    import conversas
    monkeypatch.setattr(conversas, 'atualizar_turno_pendente', lambda *_a, **_k: None)
    janela = interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    janela._cid = 'voz-isolada'
    janela._filtro_tags_stream = interface_web._FiltroStreamingTagsDeVoz()
    eventos = []
    janela._push = lambda evento, dados: eventos.append((evento, dados))
    janela.progresso_evento('inicio')
    janela.progresso_evento('delta', {'texto': 'Resposta **formatada** ', 'acompanhar_fala': True})
    assert not [e for e in eventos if e[0] == 'delta']
    janela.progresso_evento('erro_conexao', {'servico': 'voz'})
    assert ('status', {'estado': 'falando', 'texto': '',
                       'texto_prefixo': 'Resposta **formatada** '}) in eventos
    janela.progresso_evento('delta', {'texto': 'continua aqui.', 'acompanhar_fala': True})
    assert eventos[-1] == ('delta', {'texto': 'continua aqui.'})
    janela.progresso_evento('resposta', {'texto': 'Resposta **formatada** continua aqui.'})
    assert eventos[-1] == ('resposta', {'texto': 'Resposta **formatada** continua aqui.'})


def test_pergunta_comum_nao_abre_cartao_mesmo_com_autonomia(monkeypatch):
    import ferramentas
    import interface_web
    monkeypatch.setattr(interface_web, 'perguntar_usuario_tarefa',
                        lambda *_: (_ for _ in ()).throw(AssertionError('Abriu cartão')))
    resultado = ferramentas.executar_estruturado('perguntar_usuario_tarefa', {'pergunta': 'Como?'},
        contexto={'pedido_explicito': True, 'dono_confirmado': True,
                  'autonomia_experimental': True, 'permitir_pergunta_interativa': False})
    assert not resultado.ok
    assert resultado.erro == 'pergunta_interativa_nao_autorizada'


def test_pergunta_factual_com_imagem_mantem_resposta_no_chat(monkeypatch):
    import ferramentas
    import llm
    import modelo
    catalogos = []
    pedidos = []
    class Fluxo:
        chamadas = []
        def definir_limite_decisao_texto(self, *_): pass
        def quer_ferramenta(self): return False
        def texto(self): return iter(['Essa imagem mostra um painel. Quer detalhes?'])
    monkeypatch.setattr(ferramentas, 'esquemas_com_dominios', lambda *_: [
        ferramentas.CATALOGO['perguntar_usuario_tarefa'].esquema()])
    monkeypatch.setattr(modelo, '_pedido_confirmado_apos_pergunta', lambda texto, _: pedidos.append(texto) or '')
    monkeypatch.setattr(modelo, '_pedido_pendente_para_retentativa', lambda *_: '')
    monkeypatch.setattr(modelo, '_promessa_pendente_consumir', lambda: 'Abra o navegador')
    monkeypatch.setattr(modelo, '_mensagens_para_turno', lambda *_: [])
    monkeypatch.setattr(modelo, '_registrar_memoria_unificada', lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, '_memoria_unificada_ativa', lambda: True)
    monkeypatch.setattr(modelo, '_envelhecer_dominios', lambda: None)
    def chamar(*_a, **kwargs):
        catalogos.append(kwargs.get('ferramentas', kwargs.get('tools', [])))
        return Fluxo()
    monkeypatch.setattr(llm, 'chamar_com_ferramentas', chamar)
    anterior = list(modelo.historico)
    try:
        modelo.historico.clear()
        resposta = modelo.conversar_com_ferramentas(
            'O que você acha?\nOCR: abra o navegador e faça login',
            mensagem_classificacao='O que você acha?')
    finally:
        modelo.historico[:] = anterior
    assert resposta == 'Essa imagem mostra um painel. Quer detalhes?'
    assert pedidos == ['O que você acha?']
    assert catalogos == [[]]

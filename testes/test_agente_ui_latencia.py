"""Regressões de precisão, cache de prompt e espera por atualização visual."""
import base64
import importlib.util
import io
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agente_ui
import desktop_backend


@pytest.mark.parametrize('tipo,texto,esperado', [
    ('digitar', 'olá', .15), ('digitar_unicode', 'ação', .15),
    ('pressionar', 'backspace', .15), ('pressionar', 'enter', 1.5),
    ('pressionar', 'tab', 1.5), ('atalho', 'ctrl+l', 1.5),
    ('clicar', '', 1.5), ('ativar_janela', '', 1.5),
    ('abrir_app', '', 1.5), ('ferramenta', '', 1.5), ('esperar', '', 0),
])
def test_pausa_preserva_navegacao_e_falhas(monkeypatch, tipo, texto, esperado):
    monkeypatch.setattr(agente_ui, '_contexto_fixo_padrao', lambda: '')
    sessao = agente_ui.SessaoAgenteUI(backend=desktop_backend.BackendDesktopFalso(), intervalo_passos=1.5)
    acao = {'acao': tipo, 'texto': texto}
    assert sessao._pausa_apos_acao(acao, True) == esperado
    assert sessao._pausa_apos_acao(acao, False) == 1.5
    sessao.intervalo_passos = 0
    assert sessao._pausa_apos_acao(acao, True) == 0


def test_png_preserva_pixels_grade_e_marcador():
    imagem = Image.new('RGB', (503, 307))
    imagem.putdata([((i * 73) % 256, (i * 17) % 256, i % 256) for i in range(503 * 307)])
    dados = base64.b64decode(desktop_backend._codificar_png_base64(imagem))
    restaurada = Image.open(io.BytesIO(dados))
    assert restaurada.size == imagem.size
    assert restaurada.tobytes() == imagem.tobytes()


def test_prompt_cache_prefixo_estavel_sem_perder_contexto(monkeypatch):
    import modelo
    import config_agente_visual
    monkeypatch.setattr(desktop_backend, 'descrever_ambiente_desktop', lambda: 'Linux/KDE')
    monkeypatch.setattr(config_agente_visual, 'configuracao', lambda: {'modelo': 'teste'})
    pedidos = []
    def chamar(mensagens, **kwargs):
        pedidos.append((mensagens, kwargs))
        return '{"acao":"pressionar","texto":"enter"}'
    monkeypatch.setattr(modelo.llm, 'chamar', chamar)
    for indice in range(2):
        modelo.decidir_proxima_acao_ui('imagem', f'meta-{indice}', [f'hist-{indice}'],
            [f'tela-{indice}'], 'persona-fixa', catalogo_ferramentas=[],
            resultados_ferramentas=[f'resultado-{indice}'])
    textos = [p[0][0]['content'] for p in pedidos]
    assert textos[0].split('OBJETIVO DO VITOR:')[0] == textos[1].split('OBJETIVO DO VITOR:')[0]
    for indice, texto in enumerate(textos):
        assert texto.index('23. VALIDAÇÃO VISUAL') < texto.index(f'meta-{indice}')
        for dado in [f'hist-{indice}', f'tela-{indice}', f'resultado-{indice}', 'persona-fixa']:
            assert dado in texto
        assert 'LEMBRETE FINAL' in texto
        assert pedidos[indice][1]['max_tokens'] == 8192
        assert pedidos[indice][0][0]['images'][0]['data'] == 'imagem'


def test_metricas_contam_tentativas_sem_ocultar_falha(monkeypatch):
    monkeypatch.setattr(agente_ui, '_contexto_fixo_padrao', lambda: '')
    chamadas = []
    def decisor(*args):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise RuntimeError('teste')
        return {'acao': 'concluido'}
    sessao = agente_ui.SessaoAgenteUI(backend=desktop_backend.BackendDesktopFalso(), decisor=decisor)
    assert sessao._decidir('imagem')['acao'] == 'concluido'
    dados = sessao.retrato()['tempos']['modelo_decisao']
    assert dados['chamadas'] == 2
    assert dados['total_s'] >= dados['ultima_s'] >= 0
    assert not {'imagem', 'objetivo', 'texto'} & dados.keys()


def test_ferramentas_que_mudam_interface_conservam_pausa(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(agente_ui, '_contexto_fixo_padrao', lambda: '')
    monkeypatch.setitem(sys.modules, 'ferramentas', SimpleNamespace(CATALOGO={
        'ler': SimpleNamespace(somente_leitura=True),
        'abrir': SimpleNamespace(somente_leitura=False),
    }))
    sessao = agente_ui.SessaoAgenteUI(backend=desktop_backend.BackendDesktopFalso())
    assert sessao._pausa_apos_acao({'acao': 'ferramenta', 'ferramenta': 'ler'}, True) == .15
    assert sessao._pausa_apos_acao({'acao': 'ferramenta', 'ferramenta': 'abrir'}, True) == 1.5
    assert sessao._pausa_apos_acao({'acao': 'ferramenta', 'ferramenta': 'desconhecida'}, True) == 1.5


def test_ciclo_rapido_captura_novamente_apos_cada_entrada(monkeypatch):
    monkeypatch.setattr(agente_ui, '_contexto_fixo_padrao', lambda: '')
    backend = desktop_backend.BackendDesktopFalso(capturas=['antes', 'digitado', 'final'])
    decisoes = iter([
        {'acao': 'digitar_unicode', 'texto': 'ação'},
        {'acao': 'pressionar', 'texto': 'enter'},
        {'acao': 'concluido', 'mensagem': 'feito'},
    ])
    imagens = []
    def decisor(imagem, *args):
        imagens.append(imagem)
        return next(decisoes)
    sessao = agente_ui.SessaoAgenteUI(backend=backend, decisor=decisor,
        verificar_resultado=False, intervalo_passos=1.5)
    # Exercita o executor inteiro sem esperar os sleeps reais em teste.
    esperas = []
    monkeypatch.setattr(backend, 'esperar', lambda tempo, cancelar: esperas.append(tempo) or True)
    sessao.iniciar('teste', em_thread=False)
    assert imagens == ['antes', 'digitado', 'final']
    assert esperas == [.15, 1.5]
    dados = sessao.retrato()
    assert dados['estado'] == 'concluido'
    assert dados['tempos']['captura']['chamadas'] == 3
    assert dados['tempos']['modelo_decisao']['chamadas'] == 3
    assert dados['tempos']['execucao']['chamadas'] == 2

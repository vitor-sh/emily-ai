import subprocess
from types import SimpleNamespace
import pytest
import desktop_backend
import config_agente_visual as config
import preferencias


def test_texto_longo_unicode_nao_usa_keymap_ou_timeout_por_letra(monkeypatch):
    backend = desktop_backend.BackendKDEWayland(ydotool='ydotool')
    monkeypatch.setattr(backend, '_exigir_entrada', lambda: 'ydotool')
    monkeypatch.setattr(desktop_backend.shutil, 'which', lambda x: x if x == 'wl-copy' else None)
    monkeypatch.setattr(desktop_backend.time, 'sleep', lambda _: None)
    chamadas = []
    monkeypatch.setattr(desktop_backend.subprocess, 'run', lambda args, **kw: chamadas.append((args,kw)))
    atalhos = []
    monkeypatch.setattr(backend, 'atalho', atalhos.append)
    texto = 'Olá, Vitor! çã 🙂\nAspas " e símbolos @{}[]<>?\\\n' * 400
    backend.digitar(texto, .04)
    assert len(chamadas) == 1
    assert chamadas[0][1]['input'] == texto
    assert chamadas[0][1]['timeout'] == 5
    assert atalhos == [('shift', 'insert')]


def test_falha_preparacao_nao_cola_texto_antigo(monkeypatch):
    backend = desktop_backend.BackendKDEWayland(ydotool='ydotool')
    monkeypatch.setattr(backend, '_exigir_entrada', lambda: 'ydotool')
    monkeypatch.setattr(desktop_backend.shutil, 'which', lambda x: x if x == 'wl-copy' else None)
    def falhar(*args, **kw):
        raise subprocess.TimeoutExpired('wl-copy', 5)
    monkeypatch.setattr(desktop_backend.subprocess, 'run', falhar)
    monkeypatch.setattr(backend, 'atalho', lambda _: pytest.fail('não pode colar'))
    with pytest.raises(desktop_backend.ErroBackendDesktop):
        backend.digitar('não repetir texto antigo')


def test_teclas_liberadas_mesmo_apos_timeout(monkeypatch):
    backend = desktop_backend.BackendKDEWayland(ydotool='ydotool')
    monkeypatch.setattr(backend, '_exigir_entrada', lambda: 'ydotool')
    calls=[]
    def rodar(args):
        calls.append(list(args))
        if len(calls)==1:
            raise desktop_backend.ErroBackendDesktop('falha durante envio')
    monkeypatch.setattr(backend, '_rodar', rodar)
    with pytest.raises(desktop_backend.ErroBackendDesktop):
        backend.atalho(('shift','insert'))
    assert calls[1] == ['ydotool','key','110:0','42:0']


def test_preferencia_visual_persistida_separada_do_chat(monkeypatch,tmp_path):
    monkeypatch.setattr(preferencias,'ARQUIVO',tmp_path/'prefs.json')
    preferencias.recarregar()
    monkeypatch.setattr(config.llm,'listar_provedores',lambda: [{'id':'teste','modelos':[{'id':'outro'}]}])
    monkeypatch.setattr(config.llm,'niveis_raciocinio',lambda _: [{'id':'maximo'}])
    try:
        preferencias.definir(modelo='cx/gpt-6-luna',raciocinio='baixo')
        assert not config.definir('teste','inexistente','maximo')
        assert not config.definir('teste','outro','medio')
        assert config.definir('teste','outro','maximo')
        preferencias.recarregar()
        assert config.configuracao() == {'provedor':'teste','modelo':'outro','raciocinio':'maximo'}
        assert preferencias.obter('modelo') == 'cx/gpt-6-luna'
        assert preferencias.obter('raciocinio') == 'baixo'
    finally:
        preferencias.recarregar()


def test_decisao_e_auditoria_usam_modelo_visual_escolhido(monkeypatch):
    import modelo
    escolhido = {'provedor':'openai','modelo':'cx/gpt-6-astra','raciocinio':'maximo'}
    monkeypatch.setattr(config, 'configuracao', lambda: escolhido.copy())
    calls=[]
    def chamar(*args,**kw):
        calls.append(kw)
        return '{"acao":"aguardar","concluido":false,"evidencia":"ainda falta"}'
    monkeypatch.setattr(config.llm, 'chamar', chamar)
    assert modelo.decidir_proxima_acao_ui('imagem','pedido',[]) is not None
    assert modelo.verificar_resultado_ui('imagem','pedido',[]) is not None
    assert len(calls)==2
    for call in calls:
        assert {k:call[k] for k in escolhido} == escolhido

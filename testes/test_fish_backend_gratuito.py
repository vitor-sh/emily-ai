"""Carrega apenas funções de TTS: sem microfone, interface ou clientes pessoais."""
import ast
import os
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest

RAIZ = Path(__file__).resolve().parents[1]


def funcoes(arquivo='voz.py'):
    nomes = {'_backend_fish','_abrir_tts_http','_erro_tts_permanente','_aviso_tts_permanente','_gerar_audio_pacote','gerar_audio_stream'}
    arvore = ast.parse((RAIZ / arquivo).read_text())
    ns = {'os':os,'TTSRequest':object,'Session':object,'Iterator':list,'time':__import__('time')}
    exec(compile(ast.Module(body=[n for n in arvore.body if isinstance(n,ast.FunctionDef) and n.name in nomes],type_ignores=[]),arquivo,'exec'),ns)
    return ns


@pytest.mark.parametrize('arquivo',['voz.py','dist/Emily/_internal/voz.py'])
@pytest.mark.parametrize('valor',[None,'','   ','s2.1-pro-free'])
def test_padrao_instalado_e_fonte_selecionam_free(monkeypatch, arquivo, valor):
    if valor is None:monkeypatch.delenv('EMILY_FISH_BACKEND',raising=False)
    else:monkeypatch.setenv('EMILY_FISH_BACKEND',valor)
    ns = funcoes(arquivo)
    chamadas=[]
    def tts(req, backend): chamadas.append(backend);return iter([b'audio'])
    assert list(ns['_abrir_tts_http'](SimpleNamespace(tts=tts),object())) == [b'audio']
    assert chamadas == ['s2.1-pro-free']


@pytest.mark.parametrize('arquivo',['voz.py','dist/Emily/_internal/voz.py'])
def test_sdk_sem_backend_nao_chama_default_pago(monkeypatch,arquivo):
    monkeypatch.delenv('EMILY_FISH_BACKEND',raising=False)
    chamadas=[]
    def tts(req): chamadas.append(req)
    with pytest.raises(RuntimeError):funcoes(arquivo)['_abrir_tts_http'](SimpleNamespace(tts=tts),object())
    assert not chamadas


@pytest.mark.parametrize('stream',[False,True])
@pytest.mark.parametrize('status',[401,402,403])
def test_erros_permanentes_nao_repetem_sintese(monkeypatch,stream,status):
    import modelo
    monkeypatch.setattr(modelo,'limpar_para_tts',lambda t:t)
    ns=funcoes();chamadas=[];eventos=[]
    class Recusado(Exception):pass
    erro=Recusado('recusado');erro.status=status
    def falhar(*args):chamadas.append(args);raise erro
    ns.update(_tentativas_tts=lambda:2,_pausa_retry_tts=lambda:0,_requisicao_fish=lambda *a,**k:object(),_formato_fish=lambda:'pcm',_abrir_tts_http=falhar,_session_fish=object(),_sessao_fish_da_thread=lambda:object(),_audio_sample_rate=44100,_audio_channels=1,_audio_sample_width=2,parar_fala=threading.Event(),FormatoDaFala=lambda:object())
    if stream:
        assert list(ns['gerar_audio_stream']('oi',on_conexao=lambda *args:eventos.append(args)))==[]
        assert eventos[0][0]=='erro_conexao'
    else:assert ns['_gerar_audio_pacote']('oi')[0]==b''
    assert len(chamadas)==1


def test_timeout_continua_permitindo_retry():
    ns=funcoes()
    assert not ns['_erro_tts_permanente'](TimeoutError())
    assert not ns['_erro_tts_permanente'](SimpleNamespace(status=429))
    assert not ns['_erro_tts_permanente'](SimpleNamespace(status=503))


def test_aviso_de_400_aponta_para_a_voz():
    ns = funcoes()
    for status in (400, 404):
        erro = SimpleNamespace(status=status)
        assert 'FISH_VOICE_ID' in ns['_aviso_tts_permanente'](erro)
    assert 'FISH_VOICE_ID' not in ns['_aviso_tts_permanente'](SimpleNamespace(status=401))


def test_voz_padrao_e_a_mesma_no_pc_no_hollow_knight_e_no_android():
    """O padrão do pacote público (1d5c6866) não existe na conta do Vitor: o Fish
    responde 400. Os três lugares precisam apontar para a mesma voz da conta."""
    import re
    voz = re.search(r"FISH_VOICE_ID = os\.getenv\('FISH_VOICE_ID', '([0-9a-f]{32})'\)",
                    (RAIZ / 'voz.py').read_text()).group(1)
    hk = set(re.findall(r'"EMILY_FISH_VOICE_ID",\s*"([0-9a-f]{32})"',
                        (RAIZ / 'hollow_knight_emily/python/hollow_knight_permanente.py').read_text()))
    android = RAIZ / 'EmilyAPP2/app/src/main/java/com/example/emilyapp/FishAudioTTS.kt'
    assert hk == {voz}
    if android.exists():
        assert re.search(r'FISH_VOICE_ID = "([0-9a-f]{32})"', android.read_text()).group(1) == voz

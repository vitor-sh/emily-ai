import io
import struct
import wave
from unittest.mock import Mock

import pytest
from flask import Flask
import music_identify as mi
import music_gateway


def sample(seconds=12):
    output=io.BytesIO()
    with wave.open(output,'wb') as w:
        w.setparams((1,2,16000,0,'NONE','not compressed'))
        w.writeframes(struct.pack('<h',1200)*16000*seconds)
    return output.getvalue()


def test_two_windows_preserve_original_audio():
    clips=mi.windows(sample(24))
    assert len(clips)==2
    for clip in clips:
        with wave.open(io.BytesIO(clip),'rb') as w:
            assert w.getnframes()==16000*12
            assert w.readframes(1)==struct.pack('<h',1200)


@pytest.mark.parametrize('raw',[b'',b'fake',b'x'*(mi.MAX_BYTES+1),sample(1),sample(26)])
def test_invalid_audio_rejected(raw):
    with pytest.raises((ValueError,wave.Error,EOFError)):
        mi.windows(raw)


def test_silence_is_not_sent_to_provider():
    audio=io.BytesIO()
    with wave.open(audio,'wb') as w:
        w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(bytes(16000*2*3))
    with pytest.raises(ValueError,match='Não recebi som'):mi.windows(audio.getvalue())


def test_no_match_never_invents_song():
    assert mi.normalize({'matches':[]},'shazam') is None
    assert mi.normalize({'track':{'title':'Missing artist'}},'shazam') is None
    assert mi.normalize({'result':None},'audd') is None


def test_unsafe_art_removed_and_query_encoded():
    result=mi.normalize({'track':{'title':'A & B','subtitle':'Artist','images':{'coverart':'javascript:alert(1)'}}},'shazam')
    assert result['capa']==''
    assert result['youtube'].endswith('Artist%20A%20%26%20B')


def test_audd_requires_explicit_request_and_token(monkeypatch):
    import requests
    monkeypatch.setenv('EMILY_MUSIC_WORKER','1')
    monkeypatch.setenv('EMILY_AUDD_TOKEN','test')
    async def no_match(_clips):return None
    monkeypatch.setattr(mi,'_shazam',no_match)
    send=Mock(side_effect=AssertionError('Must not use paid provider'))
    monkeypatch.setattr(requests,'post',send)
    assert mi.recognize(sample())['estado']=='nao_encontrada'
    send.assert_not_called()
    monkeypatch.delenv('EMILY_AUDD_TOKEN')
    assert mi.recognize(sample(),True)['estado']=='nao_encontrada'
    send.assert_not_called()


def test_authenticated_route_and_body_limits(monkeypatch):
    app=Flask(__name__)
    music_gateway.register(app,lambda: ('denied',401) if __import__('flask').request.headers.get('Authorization')!='test' else None)
    client=app.test_client()
    recognize=Mock(return_value={'ok':True,'musica':{'titulo':'Test'}})
    monkeypatch.setattr(mi,'recognize',recognize)
    assert client.post('/music/identify',data=sample()).status_code==401
    recognize.assert_not_called()
    assert client.post('/music/identify',headers={'Authorization':'test'},data=sample()).json['ok']
    assert client.post('/music/identify',headers={'Authorization':'test'},data=b'x'*(mi.MAX_BYTES+1)).status_code==413


def test_worker_crash_does_not_crash_gateway(monkeypatch):
    monkeypatch.delenv('EMILY_MUSIC_WORKER',raising=False)
    monkeypatch.setattr(mi.subprocess,'run',Mock(return_value=Mock(returncode=-11)))
    result=mi.recognize(sample())
    assert not result['ok'] and result['estado']=='erro'

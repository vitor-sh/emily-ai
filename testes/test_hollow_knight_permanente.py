import json
import io
import types
import wave


def _cfg(valores):
    return lambda nome, padrao="": valores.get(nome, padrao)


class _Resposta:
    def __init__(self, *, corpo=None, conteudo=b"", ok=True, status=200):
        self._corpo = corpo or {}
        self.content = conteudo
        self.ok = ok
        self.status_code = status

    def json(self):
        return self._corpo

    def raise_for_status(self):
        if not self.ok:
            import requests

            raise requests.HTTPError(str(self.status_code))


def test_fish_audio_direto_usa_rest_oficial_e_retorna_wav():
    from hollow_knight_emily.python.hollow_knight_permanente import FishAudioDireto

    chamadas = []
    bruto = io.BytesIO()
    with wave.open(bruto, "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(44100)
        arquivo.writeframes(b"\x00\x00" * 100)
    wav = bruto.getvalue()

    class Sessao:
        def post(self, url, **kwargs):
            chamadas.append((url, kwargs))
            return _Resposta(conteudo=wav)

    tts = FishAudioDireto(
        _cfg({
            "FISH_AUDIO_KEY": "segredo-fish",
            "EMILY_FISH_VOICE_ID": "voz-emily",
            "EMILY_FISH_MODELO_TTS": "s2.1-pro-free",
        }),
        Sessao(),
    )
    normalizado = tts.gerar_wav("[excited] Oi!")
    with wave.open(io.BytesIO(normalizado), "rb") as arquivo:
        assert arquivo.getnframes() == 100
        assert arquivo.getframerate() == 44100
    url, pedido = chamadas[0]
    assert url == "https://api.fish.audio/v1/tts"
    assert pedido["headers"]["Authorization"] == "Bearer segredo-fish"
    assert pedido["headers"]["model"] == "s2.1-pro-free"
    assert pedido["json"]["reference_id"] == "voz-emily"
    assert pedido["json"]["format"] == "wav"


def test_fish_audio_direto_entrega_pcm_incremental():
    from hollow_knight_emily.python.hollow_knight_permanente import FishAudioDireto

    chamadas = []

    class RespostaStream(_Resposta):
        def iter_content(self, chunk_size=1):
            assert chunk_size == 8192
            yield b"\x01\x00" * 20
            yield b"\x02\x00" * 20

        def close(self):
            pass

    class Sessao:
        def post(self, url, **kwargs):
            chamadas.append((url, kwargs))
            return RespostaStream()

    tts = FishAudioDireto(
        _cfg({
            "FISH_AUDIO_KEY": "segredo-fish",
            "EMILY_FISH_VOICE_ID": "voz-emily",
            "EMILY_FISH_MODELO_TTS": "s2.1-pro-free",
        }),
        Sessao(),
    )

    partes = list(tts.gerar_pcm_stream("[excited] Oi em streaming!"))

    assert partes == [b"\x01\x00" * 20, b"\x02\x00" * 20]
    url, pedido = chamadas[0]
    assert url == "https://api.fish.audio/v1/tts"
    assert pedido["stream"] is True
    assert pedido["json"]["format"] == "pcm"
    assert pedido["json"]["chunk_length"] == 100


def test_cerebro_permanente_chama_omniroute_com_contexto():
    from hollow_knight_emily.python.hollow_knight_permanente import (
        CerebroHollowKnightPermanente,
    )

    chamadas = []

    class Sessao:
        def post(self, url, **kwargs):
            chamadas.append((url, kwargs))
            return _Resposta(corpo={"choices": [{"message": {"content": json.dumps({
                "falar": True, "texto": "Tô aqui.", "emocao": "curiosa",
                "acao": "nenhuma",
            })}}]})

    cfg = _cfg({
        "EMILY_PROVEDOR_OPENAI_BASE": "http://127.0.0.1:20128/v1",
        "EMILY_PROVEDOR_OPENAI_CHAVE": "segredo-omni",
        "EMILY_PROVEDOR_OPENAI_MODELO": "cx/gpt-5.6-terra",
        "EMILY_PROVEDOR_OPENAI_MODELOS": "cx/gpt-5.6-terra,cx/gpt-5.6-luna,cx/gpt-5.6-sol",
    })
    saude = types.SimpleNamespace(invalidar=lambda: None)
    cerebro = CerebroHollowKnightPermanente(cfg, saude, Sessao())
    evento = types.SimpleNamespace(
        tipo="area_nova", dados={"zona": "TOWN"}, cena_id="Town:2"
    )
    sessao = types.SimpleNamespace(
        campanha_id="slot-3", estado={"modelo": "cx/gpt-5.6-sol"}
    )
    resposta = cerebro.responder(evento, sessao)
    assert resposta["texto"] == "Tô aqui."
    url, pedido = chamadas[0]
    assert url == "http://127.0.0.1:20128/v1/chat/completions"
    assert pedido["headers"]["Authorization"] == "Bearer segredo-omni"
    assert pedido["json"]["model"] == "cx/gpt-5.6-sol"
    assert pedido["json"]["reasoning_effort"] == "low"
    assert "temperature" not in pedido["json"]
    contexto = json.loads(pedido["json"]["messages"][1]["content"])
    assert contexto["evento"] == "area_nova"
    assert contexto["campanha"] == "slot-3"


def test_cerebro_permanente_envia_resumo_da_memoria_ao_omniroute():
    from hollow_knight_emily.python.hollow_knight_permanente import (
        CerebroHollowKnightPermanente,
    )

    chamadas = []

    class SessaoHttp:
        def post(self, url, **kwargs):
            chamadas.append(kwargs["json"])
            return _Resposta(corpo={"choices": [{"message": {"content": json.dumps({
                "falar": True, "texto": "Eu lembro.", "emocao": "neutra",
                "acao": "nenhuma",
            })}}]})

    memoria = types.SimpleNamespace(
        contexto=lambda campanha, evento, modo: {
            "campanha": {"mortes": 7, "ultima_area": "CROSSROADS"},
            "recentes": [{"tipo": "morte", "resumo": "Morreu novamente."}],
        }
    )
    cfg = _cfg({
        "EMILY_PROVEDOR_OPENAI_BASE": "http://127.0.0.1:20128/v1",
        "EMILY_PROVEDOR_OPENAI_CHAVE": "segredo",
        "EMILY_PROVEDOR_OPENAI_MODELO": "cx/gpt-5.6-luna",
        "EMILY_PROVEDOR_OPENAI_MODELOS": "cx/gpt-5.6-luna",
    })
    cerebro = CerebroHollowKnightPermanente(
        cfg,
        types.SimpleNamespace(invalidar=lambda: None),
        SessaoHttp(),
        memoria=memoria,
    )
    cerebro.responder(
        types.SimpleNamespace(tipo="morte", dados={}, cena_id="Crossroads:4"),
        types.SimpleNamespace(
            campanha_id="slot-1", estado={"modo_fala": "normal", "modelo": ""}
        ),
    )
    contexto = json.loads(chamadas[0]["messages"][1]["content"])
    assert contexto["memoria_da_campanha"]["campanha"]["mortes"] == 7
    assert contexto["memoria_da_campanha"]["recentes"][0]["tipo"] == "morte"


def test_catalogo_permanente_nao_serializa_segredos(tmp_path):
    from hollow_knight_emily.python.hollow_knight_permanente import (
        gravador_catalogo, normalizador_modelo,
    )

    destino = tmp_path / "modelos.json"
    gravador_catalogo(_cfg({
        "EMILY_PROVEDOR_OPENAI_NOME": "OpenAI",
        "EMILY_PROVEDOR_OPENAI_MODELO": "cx/gpt-5.6-terra",
        "EMILY_PROVEDOR_OPENAI_MODELOS": "cx/gpt-5.6-terra,cx/gpt-5.6-luna,cx/gpt-5.6-sol",
        "EMILY_PROVEDOR_OPENAI_CHAVE": "nao-pode-aparecer",
        "FISH_AUDIO_KEY": "tambem-nao-pode-aparecer",
    }))(destino)
    texto = destino.read_text(encoding="utf-8")
    catalogo = json.loads(texto)
    assert catalogo["provedor"] == "openai"
    assert catalogo["padrao"] == "cx/gpt-5.6-luna"
    assert [m["id"] for m in catalogo["modelos"]] == [
        "cx/gpt-5.6-terra", "cx/gpt-5.6-luna", "cx/gpt-5.6-sol",
    ]
    assert "nao-pode-aparecer" not in texto
    assert "tambem-nao-pode-aparecer" not in texto
    normalizar = normalizador_modelo(_cfg({
        "EMILY_PROVEDOR_OPENAI_MODELO": "cx/gpt-5.6-terra",
        "EMILY_PROVEDOR_OPENAI_MODELOS": "cx/gpt-5.6-terra,cx/gpt-5.6-luna,cx/gpt-5.6-sol",
    }))
    assert normalizar("cx/gpt-5.6-sol") == "cx/gpt-5.6-sol"
    assert normalizar("claude-sonnet-5") == ""


def test_luna_padrao_mesmo_com_terra_como_padrao_do_pc():
    from hollow_knight_emily.python.hollow_knight_permanente import (
        CerebroHollowKnightPermanente,
    )

    chamadas = []

    class Http:
        def post(self, url, **kwargs):
            chamadas.append(kwargs["json"])
            return _Resposta(corpo={"choices": [{"message": {"content": json.dumps({
                "falar": True, "texto": "Que lugar estranho.", "emocao": "curiosa",
            })}}]})

    cfg = _cfg({
        "EMILY_PROVEDOR_OPENAI_BASE": "http://localhost/v1",
        "EMILY_PROVEDOR_OPENAI_CHAVE": "segredo",
        "EMILY_PROVEDOR_OPENAI_MODELO": "cx/gpt-5.6-terra",
        "EMILY_PROVEDOR_OPENAI_MODELOS": "cx/gpt-5.6-terra,cx/gpt-5.6-luna",
    })
    cerebro = CerebroHollowKnightPermanente(
        cfg, types.SimpleNamespace(invalidar=lambda: None), Http(),
    )
    evento = types.SimpleNamespace(tipo="area_nova", dados={"zona": "TOWN"}, cena_id="Town:1")
    sessao = types.SimpleNamespace(campanha_id="slot-1", estado={"modelo": ""})
    cerebro.responder(evento, sessao)
    sessao.estado["modelo"] = "claude-sonnet-5"
    cerebro.responder(evento, sessao)
    assert [item["model"] for item in chamadas] == ["cx/gpt-5.6-luna"] * 2
    assert all(item["reasoning_effort"] == "low" for item in chamadas)
    assert all("temperature" not in item for item in chamadas)


def test_status_da_ponte_reflete_saude_do_upstream():
    from hollow_knight_emily.python.hollow_knight_ponte import PonteHollowKnight

    ponte = PonteHollowKnight(
        token="segredo", pronto=lambda: False, origem="gateway-permanente"
    )
    resposta = ponte.app.test_client().get(
        "/v1/hollow-knight/status",
        headers={"Authorization": "Bearer segredo"},
    )
    assert resposta.status_code == 503
    assert resposta.get_json()["online"] is False
    assert resposta.get_json()["origem"] == "gateway-permanente"


def test_saude_omniroute_cabe_no_timeout_do_cliente_do_mod():
    from hollow_knight_emily.python.hollow_knight_permanente import SaudeOmniRoute

    chamadas = []

    class Sessao:
        def get(self, url, **kwargs):
            chamadas.append((url, kwargs))
            return _Resposta(ok=True)

    saude = SaudeOmniRoute(_cfg({
        "EMILY_PROVEDOR_OPENAI_BASE": "http://127.0.0.1:20128/v1",
        "EMILY_PROVEDOR_OPENAI_CHAVE": "segredo",
    }), Sessao())
    assert saude.pronto(forcar=True)
    assert sum(chamadas[0][1]["timeout"]) < 8.0


def test_saude_aceita_upstream_sem_catalogo_models_mas_rejeita_credencial_invalida():
    from hollow_knight_emily.python.hollow_knight_permanente import SaudeOmniRoute

    cfg = _cfg({
        "EMILY_PROVEDOR_OPENAI_BASE": "http://localhost/v1",
        "EMILY_PROVEDOR_OPENAI_CHAVE": "teste",
    })
    class Sessao:
        status = 404
        def get(self, url, **kwargs):
            return _Resposta(ok=False, status=self.status)

    http = Sessao()
    saude = SaudeOmniRoute(cfg, http)
    assert saude.pronto(forcar=True)
    http.status = 401
    assert not saude.pronto(forcar=True)


def test_v045_cerebro_permanente_da_liberdade_proporcional_sem_corte_curto():
    from hollow_knight_emily.python import hollow_knight_permanente as modulo

    texto = "Uma observação concreta e natural. " * 20

    class Sessao:
        def post(self, _url, **kwargs):
            assert kwargs["json"]["max_tokens"] >= 400
            return _Resposta(corpo={"choices": [{"message": {"content": json.dumps({
                "falar": True, "texto": texto, "emocao": "curiosa", "acao": "nenhuma",
            })}}]})

    cfg = _cfg({
        "EMILY_PROVEDOR_OPENAI_BASE": "http://127.0.0.1:20128/v1",
        "EMILY_PROVEDOR_OPENAI_CHAVE": "segredo",
        "EMILY_PROVEDOR_OPENAI_MODELO": "cx/gpt-5.6-luna",
        "EMILY_PROVEDOR_OPENAI_MODELOS": "cx/gpt-5.6-luna",
    })
    cerebro = modulo.CerebroHollowKnightPermanente(
        cfg, types.SimpleNamespace(invalidar=lambda: None), Sessao()
    )
    resposta = cerebro.responder(
        types.SimpleNamespace(tipo="npc_dialogo", dados={}, cena_id="Town:1"),
        types.SimpleNamespace(campanha_id="slot-1", estado={"modelo": ""}),
    )
    assert len(resposta["texto"]) > 420

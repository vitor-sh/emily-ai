"""Regressões de conversa confundida com pedido obrigatório de ferramenta."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

@pytest.fixture(autouse=True)
def revisor_sem_rede(monkeypatch):
    import politica_agente
    sem_evidencia = {"já vou criar", "criei o canal", "bora, crio um cargo staff pra vocês", "Pronto, configurei o token da TV."}
    def revisar(pedido, texto, mensagens, rota):
        precisa = texto in sem_evidencia or texto.startswith("Pronto, configurei")
        return {"continuar": precisa, "texto": "Ainda não confirmei essa alteração." if precisa else texto}
    monkeypatch.setattr(politica_agente, "revisar_resposta", revisar)
    monkeypatch.setattr(politica_agente, "explicar_falha", lambda *a: "Ainda não confirmei essa alteração.")


RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


FALA_COMPORTAMENTAL = (
    "Ai, você tem razão, Emily. Eu vou tentar ficar mais tranquilo com isso. "
    "Mas, ó, Emily, se a Maria ou outra pessoa entrar na call, é pra você "
    "lembrar, perceber essa informação e não ficar falando das coisas nossas, "
    "tá? Quando entrar outra pessoa na call aqui, fica de boa."
)


def _preparar_call(monkeypatch, dono_id: int = 111) -> None:
    import discord_bot
    import perfil_discord

    membro = SimpleNamespace(id=dono_id, bot=False)
    guild = SimpleNamespace(
        id=10,
        name="Servidor",
        get_member=lambda uid: membro if uid == dono_id else None,
    )
    canal = SimpleNamespace(id=20, name="call", guild=guild, members=[membro])
    monkeypatch.setattr(
        discord_bot,
        "_voice_client",
        SimpleNamespace(is_connected=lambda: True, channel=canal),
    )
    monkeypatch.setattr(discord_bot, "_config", {"usuario_id": dono_id})
    monkeypatch.setattr(discord_bot, "_memoria_dono", lambda *_a: "vitor")
    monkeypatch.setattr(
        perfil_discord, "contexto_de_membros", lambda *_a, **_k: "")


def _esquema_teste() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "acao_teste",
            "description": "teste",
            "parameters": {
                "type": "object", "properties": {}, "required": [],
            },
        },
    }


def test_instrucao_comportamental_nao_e_acao_nem_admin():
    import classificacao_ferramentas as cf
    import discord_admin
    import modelo

    classificacao = cf.classificar(
        FALA_COMPORTAMENTAL,
        acao_explicita=modelo._parece_pedido_de_acao(FALA_COMPORTAMENTAL),
        permitir_iniciativa=True,
    )

    assert classificacao.proibe_ferramenta
    assert classificacao.motivo == "instrucao_comportamental_conversacional"
    assert modelo._parece_pedido_de_acao(FALA_COMPORTAMENTAL) is False
    assert modelo.fala_pede_ferramenta_na_call(
        FALA_COMPORTAMENTAL, eh_dono=True) is False
    assert discord_admin.parece_ordem_de_admin(
        FALA_COMPORTAMENTAL, dirigido_a_ela=True) is False
    assert discord_admin.parece_pedido_de_admin(
        FALA_COMPORTAMENTAL, dirigido_a_ela=True) is False
    assert cf.parece_instrucao_comportamental(
        "quando alguém entrar, não fala da criança") is True
    assert cf.parece_instrucao_comportamental(
        "quando alguém entrar, apaga o canal e não fala nada") is False


def test_pedido_de_memoria_sem_ferramenta_de_escrita_nao_e_acao():
    import classificacao_ferramentas as cf
    import modelo

    texto = "lembra que meu aniversário é 14 de maio"
    classificacao = cf.classificar(
        texto, acao_explicita=modelo._parece_pedido_de_acao(texto))

    assert classificacao.proibe_ferramenta
    assert classificacao.motivo == "pedido_de_memoria_sem_ferramenta_de_escrita"
    assert modelo._parece_pedido_de_acao(texto) is False


def test_pedido_conversado_para_navegador_interno_exige_ferramenta():
    import classificacao_ferramentas as cf
    import modelo

    pedido = ('Oii Emily! Tu pode entrar no seu navegador e ir no site do cinema '
              'do Shopping Estação, checa pra mim o preço do filme na sexta?')
    casual = 'Eu entrei no seu navegador ontem e achei legal.'
    assert modelo._pediu_navegador_interno(pedido)
    assert cf.classificar(pedido, acao_explicita=modelo._parece_pedido_de_acao(pedido)).exige_ferramenta
    assert not modelo._pediu_navegador_interno(casual)
    assert cf.classificar(casual, acao_explicita=modelo._parece_pedido_de_acao(casual)).proibe_ferramenta


def test_usar_seu_navegador_para_ver_preco_e_confirmacao_seguinte():
    import classificacao_ferramentas as cf
    import modelo

    pedido = ("Oi Emily, tu pode usar o seu navegador pra ver o preço pra mim "
              "do ingresso do filme Resident Evil no shopping Estação BH? Isso "
              "é para sexta-feira, 2 de outubro.")
    assert not modelo._parece_pedido_de_acao(pedido)
    assert modelo._pediu_navegador_interno(pedido)
    politica = cf.classificar(
        pedido, acao_explicita=(modelo._parece_pedido_de_acao(pedido)
                                 or modelo._pediu_navegador_interno(pedido)))
    assert politica.exige_ferramenta

    historico = [
        {"role": "user", "content": pedido},
        {"role": "assistant", "content": "É pra sexta-feira, 2 de outubro?"},
    ]
    assert modelo._pedido_confirmado_apos_pergunta("Sim sim, isso mesmo", historico) == pedido
    assert not modelo._pedido_confirmado_apos_pergunta("Não, deixa pra lá", historico)


def test_call_com_autonomia_ligada_mantem_instrucao_no_caminho_rapido(monkeypatch):
    import discord_bot
    import modelo

    _preparar_call(monkeypatch)
    chamadas = {"rapido": 0, "ferramentas": 0}
    monkeypatch.setattr(modelo, "autonomia_experimental_ativa", lambda: True)

    def rapido(**_kwargs):
        chamadas["rapido"] += 1
        return {
            "responder": True,
            "resposta": "Tá, fica entre a gente.",
            "detalhe_texto": "",
        }

    def pesado(**_kwargs):
        chamadas["ferramentas"] += 1
        raise AssertionError("conversa não deveria abrir o laço de ferramentas")

    monkeypatch.setattr(modelo, "responder_na_call", rapido)
    monkeypatch.setattr(modelo, "responder_discord_com_ferramentas", pesado)

    resultado = discord_bot._pensar_na_call(
        111, "Vitor", FALA_COMPORTAMENTAL, "", quem_na_call="Vitor")

    assert resultado["resposta"] == "Tá, fica entre a gente."
    assert chamadas == {"rapido": 1, "ferramentas": 0}


def test_call_nao_abre_ferramenta_so_por_desabafo_com_autonomia(monkeypatch):
    import discord_bot
    import modelo

    _preparar_call(monkeypatch)
    chamadas = {"rapido": 0, "ferramentas": 0}
    monkeypatch.setattr(modelo, "autonomia_experimental_ativa", lambda: True)

    def rapido(**_kwargs):
        chamadas["rapido"] += 1
        return {
            "responder": True,
            "resposta": "Poxa, vem cá, me conta o que pegou.",
            "detalhe_texto": "",
        }

    monkeypatch.setattr(modelo, "responder_na_call", rapido)
    monkeypatch.setattr(
        modelo,
        "responder_discord_com_ferramentas",
        lambda **_k: chamadas.__setitem__("ferramentas", 1),
    )

    resultado = discord_bot._pensar_na_call(
        111, "Vitor", "Emily, eu tô triste hoje", "", quem_na_call="Vitor")

    assert resultado["resposta"].startswith("Poxa")
    assert chamadas == {"rapido": 1, "ferramentas": 0}


def test_mencao_conversacional_no_discord_nao_abre_laco_admin(monkeypatch):
    import discord_admin
    import discord_bot
    import modelo

    autor = SimpleNamespace(id=711)
    mensagem = SimpleNamespace(
        guild=SimpleNamespace(id=812),
        author=autor,
    )
    monkeypatch.setattr(discord_bot, "_config", {"permitir_admin": True})
    monkeypatch.setattr(
        discord_admin, "consumir_promessa", lambda *_a, **_k: None)

    def nao_chamar_modelo(**_kwargs):
        raise AssertionError("menção conversacional não deve abrir laço admin")

    monkeypatch.setattr(
        modelo, "responder_discord_com_ferramentas", nao_chamar_modelo)

    tratado = discord_bot._tentar_pedido_de_admin(
        913,
        FALA_COMPORTAMENTAL,
        "Vitor",
        mensagem,
    )

    assert tratado is False


def test_resposta_textual_valida_e_preservada_sem_retry(monkeypatch):
    import ferramentas
    import llm
    import modelo

    chamadas = []
    monkeypatch.setattr(
        ferramentas, "esquemas", lambda grupos=None: [_esquema_teste()])

    def responder(*_args, **kwargs):
        chamadas.append(dict(kwargs))
        return SimpleNamespace(
            texto="Tá tranquilo, quando entrar alguém eu não exponho nada nosso.",
            chamadas=[],
        )

    monkeypatch.setattr(llm, "chamar_com_ferramentas", responder)

    resultado = modelo.responder_discord_com_ferramentas(
        mensagem=FALA_COMPORTAMENTAL,
        nome_autor="Vitor",
        eh_dono=True,
        parece_acao=True,  # simula um roteador antigo errando para o lado forte
    )

    assert resultado.texto == (
        "Tá tranquilo, quando entrar alguém eu não exponho nada nosso.")
    assert resultado.agiu is False
    assert resultado.politica_ferramenta == "ferramenta_opcional"
    assert len(chamadas) == 1
    assert chamadas[0]["proibir_ferramenta"] is False


def test_recusa_explicada_e_preservada_sem_retry(monkeypatch):
    import ferramentas
    import llm
    import modelo

    chamadas = []
    monkeypatch.setattr(
        ferramentas, "esquemas", lambda grupos=None: [_esquema_teste()])

    def responder(*_args, **kwargs):
        chamadas.append(dict(kwargs))
        return SimpleNamespace(
            texto="não consigo criar sem o nome do canal", chamadas=[])

    monkeypatch.setattr(llm, "chamar_com_ferramentas", responder)

    resultado = modelo.responder_discord_com_ferramentas(
        mensagem="cria o canal",
        nome_autor="Vitor",
        eh_dono=True,
        parece_acao=True,
    )

    assert len(chamadas) == 1
    assert resultado.texto == "não consigo criar sem o nome do canal"


def test_explicacao_valida_e_preservada_apos_unico_retry(monkeypatch):
    import ferramentas
    import llm
    import modelo

    chamadas = []
    monkeypatch.setattr(
        ferramentas, "esquemas", lambda grupos=None: [_esquema_teste()])

    def responder(*_args, **kwargs):
        chamadas.append(dict(kwargs))
        return SimpleNamespace(
            texto="Essa alteração precisa ser feita no painel externo do serviço.",
            chamadas=[],
        )

    monkeypatch.setattr(llm, "chamar_com_ferramentas", responder)

    resultado = modelo.responder_discord_com_ferramentas(
        mensagem="altera essa configuração externa",
        nome_autor="Vitor",
        eh_dono=True,
        parece_acao=True,
    )

    assert len(chamadas) == 1
    assert resultado.texto == (
        "Essa alteração precisa ser feita no painel externo do serviço.")


def test_politica_opcional_nao_forca_nem_chama_classificador_extra(monkeypatch):
    import classificacao_ferramentas as cf
    import ferramentas
    import llm
    import modelo

    chamadas = []
    monkeypatch.setattr(
        ferramentas, "esquemas", lambda grupos=None: [_esquema_teste()])

    def responder(*_args, **kwargs):
        chamadas.append(dict(kwargs))
        return SimpleNamespace(
            texto="consigo sim, mas você só perguntou", chamadas=[])

    monkeypatch.setattr(llm, "chamar_com_ferramentas", responder)

    resultado = modelo.responder_discord_com_ferramentas(
        mensagem="você consegue banir pessoas?",
        nome_autor="Vitor",
        eh_dono=True,
        parece_acao=False,
        politica_ferramenta=cf.FERRAMENTA_OPCIONAL,
        motivo_classificacao="pergunta_de_capacidade_administrativa",
    )

    assert len(chamadas) == 1
    assert resultado.texto == "consigo sim, mas você só perguntou"


def test_conversa_local_proibe_ferramenta_no_primeiro_request(monkeypatch):
    import ferramentas
    import llm
    import modelo

    vistos = []

    class FluxoTexto:
        chamadas = []

        def definir_limite_decisao_texto(self, _limite):
            return None

        def quer_ferramenta(self):
            return False

        def texto(self):
            return iter(["Fechado, isso fica só entre a gente."])

    monkeypatch.setattr(
        ferramentas, "esquemas_com_dominios", lambda *_a, **_k: [_esquema_teste()])
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda _extra="": [])
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: None)
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "_envelhecer_dominios", lambda: None)

    def chamar(*_args, **kwargs):
        vistos.append(dict(kwargs))
        return FluxoTexto()

    monkeypatch.setattr(llm, "chamar_com_ferramentas", chamar)
    historico_original = list(modelo.historico)
    try:
        modelo.historico.clear()
        resposta = modelo.conversar_com_ferramentas(FALA_COMPORTAMENTAL)
    finally:
        modelo.historico[:] = historico_original

    assert resposta == "Fechado, isso fica só entre a gente."
    assert len(vistos) == 1
    assert vistos[0]["proibir_ferramenta"] is False


def test_consulta_atual_local_mantem_ferramenta_disponivel(monkeypatch):
    import ferramentas
    import llm
    import modelo

    vistos = []

    class FluxoTexto:
        chamadas = []

        def quer_ferramenta(self):
            return False

        def texto(self):
            return iter(["Preciso consultar isso."])

    monkeypatch.setattr(
        ferramentas, "esquemas_com_dominios", lambda *_a, **_k: [_esquema_teste()])
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda _extra="": [])
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: None)
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "_envelhecer_dominios", lambda: None)

    def chamar(*_args, **kwargs):
        vistos.append(dict(kwargs))
        return FluxoTexto()

    monkeypatch.setattr(llm, "chamar_com_ferramentas", chamar)
    historico_original = list(modelo.historico)
    try:
        modelo.historico.clear()
        modelo.conversar_com_ferramentas("quem é o presidente?")
    finally:
        modelo.historico[:] = historico_original

    assert vistos
    assert vistos[0]["proibir_ferramenta"] is False


def test_pergunta_social_nao_abre_cartao_mesmo_com_promessa_antiga(monkeypatch):
    import ferramentas
    import interface_web
    import llm
    import modelo

    requisicoes = []

    class FluxoTexto:
        chamadas = []

        def quer_ferramenta(self):
            return False

        def texto(self):
            return iter(["Imagino que isso tenha pesado. Como você está agora?"])

    monkeypatch.setattr(ferramentas, "esquemas_com_dominios", lambda *_a, **_k: [])
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda _extra="": [])
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: "Abra o navegador")
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "_envelhecer_dominios", lambda: None)
    monkeypatch.setattr(modelo, "_emitir_fala", lambda *_a, **_k: None)
    def chamar(*_a, **kwargs):
        requisicoes.append(kwargs)
        return FluxoTexto()

    monkeypatch.setattr(llm, "chamar_com_ferramentas", chamar)
    monkeypatch.setattr(interface_web, "perguntar_usuario_tarefa", lambda *_a, **_k:
                        __import__("pytest").fail("conversa abriu cartão de tarefa"))

    anterior = list(modelo.historico)
    try:
        modelo.historico.clear()
        resposta = modelo.conversar_com_ferramentas(
            "Queria desabafar sobre uma conversa com uma amiga.", canal="web")
    finally:
        modelo.historico[:] = anterior

    assert resposta == "Imagino que isso tenha pesado. Como você está agora?"
    assert requisicoes[0]["proibir_ferramenta"] is False


def test_abrir_outro_chat_descarta_promessa_da_conversa_anterior():
    import modelo

    anterior_historico = list(modelo.historico)
    anterior_promessa = modelo._promessa_pendente
    try:
        modelo._promessa_pendente = "Abra o navegador da tarefa antiga"
        modelo.definir_historico([{"role": "user", "content": "Oi, Emily"}])
        assert modelo._promessa_pendente_consumir() is None
    finally:
        modelo.definir_historico(anterior_historico)
        modelo._promessa_pendente = anterior_promessa


def test_acoes_externas_continuam_obrigatorias():
    import classificacao_ferramentas as cf
    import modelo

    for texto in (
        "abre o Brave pra mim",
        "pesquisa as notícias desse jogo",
        "desfaz isso",
        "configura esse token na TV",
        "salva o token do app da televisão",
    ):
        classificacao = cf.classificar(
            texto, acao_explicita=modelo._parece_pedido_de_acao(texto))
        assert classificacao.exige_ferramenta, texto


def test_promessa_tem_so_uma_reentrada_mas_pergunta_continua_pendente():
    import discord_admin

    canal_id, autor_id = 9981, 9982
    discord_admin.limpar_promessa(canal_id, autor_id)
    try:
        discord_admin.registrar_promessa(
            canal_id, autor_id, "cria um canal",
            tipo=discord_admin.TIPO_PROMESSA,
        )
        assert discord_admin.tem_promessa(canal_id, autor_id)

        # Mesma promessa após a reentrada frustrada: descarta em vez de abrir
        # novas tentativas em mensagens futuras.
        discord_admin.registrar_promessa(
            canal_id, autor_id, "cria um canal",
            tipo=discord_admin.TIPO_PROMESSA,
        )
        assert not discord_admin.tem_promessa(canal_id, autor_id)

        # Pergunta de esclarecimento é outra categoria: não é falha e continua
        # esperando a resposta curta do usuário.
        discord_admin.registrar_promessa(
            canal_id, autor_id, "cria um canal",
            tipo=discord_admin.TIPO_PERGUNTA,
        )
        discord_admin.registrar_promessa(
            canal_id, autor_id, "cria um canal",
            tipo=discord_admin.TIPO_PERGUNTA,
        )
        pendente = discord_admin.consumir_promessa(canal_id, autor_id)
        assert pendente and pendente["tipo"] == discord_admin.TIPO_PERGUNTA
    finally:
        discord_admin.limpar_promessa(canal_id, autor_id)


def test_classificador_entra_nos_builds_e_no_atualizador():
    import atualizador_emily

    build_windows = (RAIZ / "build_emily.py").read_text(encoding="utf-8")
    build_linux = (RAIZ / "build_emily_linux.py").read_text(encoding="utf-8")

    assert '"classificacao_ferramentas"' in build_windows
    assert "_e_modulo_interno" in build_linux
    assert atualizador_emily._modulo_interno("classificacao_ferramentas.py")

"""
Properties 5, 6, 7 e 12 do design — tabelas de rotas e plano B.

Nenhum teste aqui toca a rede. São propriedades ESTRUTURAIS: o tipo de bug
que elas pegam é o que só apareceria na primeira chamada real da rota errada,
possivelmente semanas depois, com a Emily muda no meio de uma conversa.

Property 5:  paridade entre as tabelas, provedor registrado, max_tokens > 0
Property 6:  seleção de tabela por EMILY_PROVEDOR_LLM
Property 7:  modelo de cada grupo de rota sobrescritível por ambiente
Property 12: diagnosticar() cobre a tabela ativa inteira sem parar na falha

Rodar:
    python -m pytest testes/test_rotas_propriedades.py -v
"""

from __future__ import annotations

import importlib
import io
import os
import sys
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import llm  # noqa: E402


ROTAS_ESPERADAS = {
    "conversa", "classificador", "comando", "extracao",
    "visao", "triagem_visual", "agente_ui", "agente_jogo", "discord",
}


# ═════════════════════════════════════════════════════════════════
# Property 5: Paridade das tabelas de rotas
#
# "Para qualquer estado do código, as tabelas ROTAS_CLAUDE e ROTAS_NVIDIA têm
# exatamente o mesmo conjunto de nomes de rota, e toda rota das duas aponta
# para um provedor registrado em PROVEDORES e tem max_tokens positivo."
# ═════════════════════════════════════════════════════════════════

def test_property5_paridade_de_nomes():
    """
    A paridade é o que impede as rotas centrais de sumirem: uma rota que
    existe no caminho de ferramentas e não na tabela ativa só quebraria na
    primeira chamada real, no pior momento possível.

    Aqui só existe UMA tabela afinada (ROTAS_CLAUDE) — as tabelas de
    nvidia/openrouter saíram junto com os provedores. Então o que se exige é:
    as nove rotas centrais existem, e as rotas EXTRAS (dedicadas) apontam
    para um provedor registrado.
    """
    faltando = ROTAS_ESPERADAS - set(llm.ROTAS_CLAUDE)
    assert not faltando, f"rota(s) central ausente da tabela claude: {sorted(faltando)}"

    # Rotas EXTRAS são as dedicadas (titulo, memoria_extracao,
    # comando_interpreta, visao_gmi, code_*): continuam resolvendo com
    # qualquer EMILY_PROVEDOR_LLM porque o rota() cai na tabela padrão quando
    # a rota não existe na ativa. Cada uma tem que apontar pra provedor
    # REGISTRADO, senão a rota morre só quando for usada.
    extras = set(llm.ROTAS_CLAUDE) - ROTAS_ESPERADAS
    extraviadas = {
        n: c.provedor for n, c in llm.ROTAS_CLAUDE.items()
        if n in extras and c.provedor not in llm.PROVEDORES
    }
    assert not extraviadas, (
        f"rota(s) dedicada(s) apontando pra provedor fora de PROVEDORES: "
        f"{extraviadas}"
    )


def test_property5_todas_as_rotas_esperadas_existem():
    """
    A tabela afinada (claude) tem as 9 rotas centrais — foi afinada por
    tarefa e é a que o rota() usa como padrão. Tabelas de provedores novos
    (criadas sob demanda via seções do .env) podem ter só 'conversa' e
    'discord': é o caso do openai/omniroute, que entram no cérebro de
    voz/texto e caem aqui pro resto.
    """
    tabela_claude = llm.TABELAS[llm.TABELA_PADRAO]
    faltando = ROTAS_ESPERADAS - set(tabela_claude)
    assert not faltando, (
        f"tabela padrão '{llm.TABELA_PADRAO}' não tem: {sorted(faltando)}"
    )


@pytest.mark.parametrize("tabela_nome", sorted(llm.TABELAS))
def test_property5_provedor_registrado_e_max_tokens_positivo(tabela_nome):
    tabela = llm.TABELAS[tabela_nome]
    for nome, cfg in tabela.items():
        assert cfg.provedor in llm.PROVEDORES, (
            f"{tabela_nome}/{nome} aponta para provedor '{cfg.provedor}' "
            f"que não está em PROVEDORES"
        )
        assert cfg.max_tokens is None or cfg.max_tokens > 0, (
            f"{tabela_nome}/{nome} tem max_tokens={cfg.max_tokens}"
        )
        assert cfg.modelo, f"{tabela_nome}/{nome} tem modelo vazio"
        assert cfg.rpm > 0, f"{tabela_nome}/{nome} tem rpm={cfg.rpm}"
        assert cfg.tentativas >= 1, f"{tabela_nome}/{nome} tem tentativas={cfg.tentativas}"


@pytest.mark.parametrize("tabela_nome", sorted(llm.TABELAS))
def test_property5_raciocinio_e_valor_conhecido(tabela_nome):
    """
    Nível de raciocínio fora da tabela PARAMS_RACIOCINIO seria ignorado em
    silêncio — a rota rodaria com o comportamento default do endpoint sem
    ninguém notar.
    """
    for nome, cfg in llm.TABELAS[tabela_nome].items():
        assert cfg.raciocinio in llm.PARAMS_RACIOCINIO, (
            f"{tabela_nome}/{nome} usa raciocinio='{cfg.raciocinio}', "
            f"que não existe em PARAMS_RACIOCINIO"
        )


@pytest.mark.parametrize("tabela_nome,provedor_esperado", sorted(
    # A tabela padrão ("claude") serve o provedor das rotas internas
    # (PROVEDOR_ROTAS: o Kiro desde 10/10/2026); as demais, o próprio nome.
    (nome, llm.PROVEDOR_ROTAS if nome == llm.TABELA_PADRAO else nome)
    for nome in llm.TABELAS
))
def test_property5_tabela_toda_no_proprio_provedor(tabela_nome, provedor_esperado):
    """
    Cada tabela é de UM provedor. Rota sobrando com o provedor de outra tabela
    é o bug que sobrevive à troca de .env sem ninguém ver.
    """
    tabela = llm.TABELAS[tabela_nome]
    # Só as rotas CENTRAIS têm que ser do provedor da tabela. Rotas dedicadas
    # (extras) apontam de propósito pra outro provedor — ver a paridade acima.
    fora = {
        n: c.provedor for n, c in tabela.items()
        if n in ROTAS_ESPERADAS and c.provedor != provedor_esperado
    }
    assert not fora, f"rotas centrais da tabela {tabela_nome} fora do provedor {provedor_esperado}: {fora}"


def test_property5_nao_sobrou_tabela_de_provedor_removido():
    """
    O projeto ficou com TRÊS provedores (Anthropic, OpenAI, OmniRoute) e as
    tabelas de nvidia/openrouter/kiro/vertex saíram junto. Se alguém
    reintroduzir uma tabela sem registrar o provedor, o Property 5 acima já
    pega; este teste garante que os nomes antigos não voltaram calados.

    Tabelas de provedores NOVOS via .env podem ser ADICIONADAS em TABELAS
    (criadas sob demanda em _resolver_tabela) — o que não pode é tabela
    órfã apontando pra provedor inexistente.
    """
    assert llm.TABELA_PADRAO == "claude"
    for removido in ("nvidia", "openrouter", "kiro", "vertex", "gmi",
                     "qwen", "ollama", "deepseek", "puter"):
        assert removido not in llm.TABELAS, (
            f"tabela '{removido}' voltou — o provedor foi removido do .env"
        )
    assert not hasattr(llm, "ROTAS_NVIDIA")
    assert not hasattr(llm, "ROTAS_OPENROUTER")
    assert not hasattr(llm, "ROTAS_KIRO")
    assert not hasattr(llm, "ROTAS_VERTEX")
    # Nenhuma tabela pode apontar pra provedor que não existe.
    for nome_tabela, tabela in llm.TABELAS.items():
        for nome_rota, cfg in tabela.items():
            assert cfg.provedor in llm.PROVEDORES, (
                f"{nome_tabela}/{nome_rota} aponta para '{cfg.provedor}', "
                f"que não está em PROVEDORES"
            )


# ═════════════════════════════════════════════════════════════════
# Property 6: Seleção de tabela por variável de ambiente
#
# "Para qualquer valor de EMILY_PROVEDOR_LLM, a tabela ativa é a
# correspondente quando o valor (normalizado) é conhecido, e é levantado
# ErroConfiguracao citando os valores aceitos quando não é; com a variável
# ausente, a tabela ativa é a padrão."
# ═════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("valor,esperado", [
    ("claude", "claude"),
    ("openai", "openai"),
    ("omniroute", "omniroute"),
    ("CLAUDE", "claude"),
    ("OPENAI", "openai"),
    ("  claude  ", "claude"),
    ("\tomniroute\n", "omniroute"),
    ("ClAuDe", "claude"),
])
def test_property6_normalizacao_do_valor(valor, esperado):
    """Espaço nas pontas e caixa não decidem nada — .env copiado à mão vem sujo."""
    nome, tabela = llm._resolver_tabela(valor)
    assert nome == esperado
    assert tabela is llm.TABELAS[esperado]


@pytest.mark.parametrize("ausente", [None, "", "   ", "\n", "\t  "])
def test_property6_ausente_cai_no_default(ausente):
    nome, tabela = llm._resolver_tabela(ausente)
    assert nome == llm.TABELA_PADRAO == "claude"
    assert tabela is llm.ROTAS_CLAUDE


@settings(max_examples=200)
@given(valor=st.text(min_size=1, max_size=30))
def test_property6_valor_desconhecido_levanta_com_os_aceitos(valor):
    """
    Nunca cair no default em silêncio.

    Se o Vitor digitar 'nvida' por engano, ele precisa saber na hora — e não
    descobrir três dias depois que nunca tinha saído da tabela padrão.
    """
    limpo = valor.strip().lower()
    if limpo in llm.TABELAS or not limpo:
        return  # esses casos têm testes próprios acima

    with pytest.raises(llm.ErroConfiguracao) as capturado:
        llm._resolver_tabela(valor)

    mensagem = str(capturado.value)
    for aceito in llm.TABELAS:
        assert aceito in mensagem, "a mensagem tem que citar os valores aceitos"


def test_property6_erro_de_digitacao_comum():
    with pytest.raises(llm.ErroConfiguracao) as capturado:
        llm._resolver_tabela("claudee")
    mensagem = str(capturado.value)
    assert "claude" in mensagem
    assert "omniroute" in mensagem


def test_property6_provedores_removidos_nao_sao_mais_aceitos():
    """
    Qwen, GMI, NVIDIA, OpenRouter, Ollama e DeepSeek saíram do .env. Um
    EMILY_PROVEDOR_LLM apontando pra eles tem que falhar ALTO, não cair no
    default em silêncio: senão o Vitor acha que está num provedor e está em
    outro.
    """
    for removido in ("qwen", "gmi", "nvidia", "openrouter", "ollama",
                     "deepseek", "puter"):
        with pytest.raises(llm.ErroConfiguracao):
            llm._resolver_tabela(removido)


def test_property6_nome_de_provedor_removido_nao_e_aceito():
    """
    'kiro' e 'vertex' eram valores válidos. Depois da remoção têm que falhar
    ALTO: .env antigo com EMILY_PROVEDOR_LLM=kiro não pode cair no default em
    silêncio, senão o Vitor acha que está num provedor e está em outro.
    """
    for antigo in ("kiro", "vertex"):
        with pytest.raises(llm.ErroConfiguracao):
            llm._resolver_tabela(antigo)


def test_property6_tabela_ativa_confere_com_o_ambiente():
    """O estado do módulo tem que refletir a variável que estava no ambiente."""
    esperado, _ = llm._resolver_tabela(os.getenv("EMILY_PROVEDOR_LLM"))
    assert llm.TABELA_ATIVA == esperado
    assert llm.ROTAS is llm.TABELAS[esperado]


# ═════════════════════════════════════════════════════════════════
# Property 7: Modelo de cada rota é sobrescritível por ambiente
#
# "Para qualquer nome de modelo não vazio colocado na variável de ambiente de
# um grupo de rotas, todas as rotas daquele grupo passam a usar esse modelo, e
# nenhuma outra rota é afetada."
#
# Precisa recarregar o módulo porque as constantes são lidas no import — que
# é o comportamento certo (ler .env em toda chamada seria desperdício), mas
# obriga o teste a simular o boot.
# ═════════════════════════════════════════════════════════════════

# A tabela do provedor atual usa UM modelo em todas as rotas CENTRAIS
# (EMILY_CLAUDE_MODELO / EMILY_PROVEDOR_CLAUDE_MODELO) e o Haiku nas rotas
# baratas (titulo, memoria_extracao). O grupo por variável de ambiente
# (EMILY_MODELO_TEXTO/VISAO...) era do NIM e saiu com ele.


@contextmanager
def recarregado_com(env: dict):
    """
    Recarrega o llm.py com um ambiente ajustado, e desfaz na saída.

    TEM que ser gerenciador de contexto, não função que devolve o módulo.
    O importlib.reload muta o objeto de módulo NO LUGAR, então o módulo
    "novo" e o `llm` importado no topo são o MESMO objeto. Uma versão
    anterior deste helper fazia `return importlib.reload(llm)` dentro de um
    try/finally que recarregava de volta — e o finally rodava ANTES de o
    valor chegar ao corpo do teste, que então media sempre o estado
    original. Sete testes falharam apontando para um bug no llm.py que não
    existia; o log capturado ('tabela ATIVA: nvidia') foi o que denunciou o
    teste.
    """
    antigos = {}
    for chave, valor in env.items():
        antigos[chave] = os.environ.get(chave)
        if valor is None:
            os.environ.pop(chave, None)
        else:
            os.environ[chave] = valor

    importlib.reload(llm)
    try:
        yield llm
    finally:
        for chave, valor in antigos.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor
        importlib.reload(llm)   # devolve o módulo ao estado do .env real


def test_property7_modelo_do_provedor_atual_vale_pra_tabela_toda():
    """
    A tabela do provedor atual usa um modelo só nas rotas CENTRAIS. Trocar
    EMILY_CLAUDE_MODELO tem que mover as NOVE rotas juntas — é o que faz
    "trocar de modelo" ser edição de uma linha de .env em vez de nove.
    """
    marcador = "modelo-de-teste-xyz"
    with recarregado_com({
        # Valor vazio impede load_dotenv() de repor o valor real do .env e
        # exercita deliberadamente a variável legada abaixo.
        "EMILY_ROTAS_PROVEDOR": "claude",
        "EMILY_PROVEDOR_CLAUDE_MODELO": "",
        "EMILY_CLAUDE_MODELO": marcador,
    }) as novo:
        usando = {n for n, c in novo.ROTAS_CLAUDE.items() if c.modelo == marcador}
        faltando = ROTAS_ESPERADAS - usando
        assert not faltando, (
            f"EMILY_CLAUDE_MODELO não alcançou as rotas centrais: "
            f"{sorted(faltando)}"
        )
        # As dedicadas ao Haiku mantêm o modelo próprio delas.
        for nome in ("titulo", "memoria_extracao"):
            if nome in novo.ROTAS_CLAUDE:
                assert novo.ROTAS_CLAUDE[nome].modelo != marcador, (
                    f"rota dedicada '{nome}' não deveria mudar de modelo"
                )


@settings(max_examples=25, deadline=None)
@given(modelo=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-.",
                      min_size=1, max_size=30))
def test_property7_qualquer_nome_de_modelo_e_aceito(modelo):
    """
    Nome de modelo é repassado literalmente, sem validação nossa.

    É deliberado: quem decide se o modelo existe é o endpoint, não a Emily.
    Validar aqui significaria bloquear modelo novo que a conta já tem — e
    esse caso já aconteceu neste projeto.
    """
    with recarregado_com({
        "EMILY_ROTAS_PROVEDOR": "claude",
        "EMILY_PROVEDOR_CLAUDE_MODELO": "",
        "EMILY_CLAUDE_MODELO": modelo,
    }) as novo:
        assert novo.ROTAS_CLAUDE["agente_ui"].modelo == modelo


def test_property7_sem_variavel_usa_o_default_documentado():
    with recarregado_com({
        "EMILY_ROTAS_PROVEDOR": "claude",
        "EMILY_PROVEDOR_CLAUDE_MODELO": "",
        "EMILY_CLAUDE_MODELO": "",
    }) as novo:
        assert novo.ROTAS_CLAUDE["conversa"].modelo == "claude-sonnet-5"


def test_property7_plano_b_por_uma_linha_de_env():
    """
    Uma variável troca o cérebro. Desde 10/10/2026 o OmniRoute (Kiro na
    Oracle) é o provedor principal, e o Claude externo virou a reserva.
    """
    with recarregado_com({"EMILY_PROVEDOR_LLM": "omniroute"}) as novo:
        assert novo.TABELA_ATIVA == "omniroute"
        # Tabela sob demanda de provedor novo: cérebro e Discord.
        assert set(novo.ROTAS) == {"conversa", "discord"}
        provedores = {c.provedor for c in novo.ROTAS.values()}
        assert provedores == {"omniroute"}
        # As rotas centrais continuam resolvendo (caem na tabela padrão).
        for nome_rota in ("visao", "agente_ui", "classificador", "titulo"):
            assert novo.rota(nome_rota).modelo, (
                f"rota '{nome_rota}' ficou sem modelo com o OmniRoute ativo"
            )


# ═════════════════════════════════════════════════════════════════
# Property 12: Diagnóstico cobre a tabela ativa por inteiro
#
# "Para qualquer tabela de rotas ativa, o diagnóstico exercita todas as rotas
# dessa tabela e relata, para cada uma, sucesso ou o motivo da falha, sem
# interromper as rotas seguintes quando uma falha."
# ═════════════════════════════════════════════════════════════════

def test_property12_diagnostico_cobre_todas_as_rotas(monkeypatch):
    exercitadas = []

    def chamar_falso(mensagens, rota_nome=llm.ROTA_PADRAO, **kwargs):
        exercitadas.append(rota_nome)
        return "OK"

    monkeypatch.setattr(llm, "chamar", chamar_falso)
    # Sem captura de tela: o diagnóstico tem que se sair bem sem visão.
    monkeypatch.setitem(sys.modules, "visao", None)

    saida = io.StringIO()
    with redirect_stdout(saida):
        relatorio = llm.diagnosticar()

    for nome in llm.ROTAS:
        assert nome in relatorio["rotas"], f"rota '{nome}' não foi relatada"
        assert nome in exercitadas or relatorio["rotas"][nome].get("erro"), (
            f"rota '{nome}' não foi exercitada nem teve erro registrado"
        )


def test_property12_uma_falha_nao_interrompe_as_seguintes(monkeypatch):
    """
    O diagnóstico serve para dizer O QUE está quebrado. Se parasse na primeira
    falha, diria apenas "algo está quebrado".

    Quebrar a rota "comando" pressupõe tabela legada (9 rotas). Se a tabela
    ativa for de um provedor novo (só 'conversa' existe), caímos pra
    'conversa' — ainda exercita o caminho, ainda é a primeira rota da tabela.
    """
    quebrada = "comando" if "comando" in llm.ROTAS else "conversa"

    def chamar_falso(mensagens, rota_nome=llm.ROTA_PADRAO, **kwargs):
        if rota_nome == quebrada:
            raise llm.ErroTransporte("falha proposital do teste")
        return "OK"

    monkeypatch.setattr(llm, "chamar", chamar_falso)
    monkeypatch.setitem(sys.modules, "visao", None)

    saida = io.StringIO()
    with redirect_stdout(saida):
        relatorio = llm.diagnosticar()

    assert relatorio["rotas"][quebrada]["ok"] is False
    assert "erro" in relatorio["rotas"][quebrada]

    # Todas as outras foram testadas apesar da falha.
    outras = [n for n in llm.ROTAS if n != quebrada]
    for nome in outras:
        assert nome in relatorio["rotas"]
    # Se a tabela ativa tem só a rota quebrada (caso provedor novo via .env
    # com 1 única rota), 'outras' é vazia e a asserção abaixo é pulada — o
    # teste ainda prova que o diagnóstico NÃO parou na primeira falha.
    if outras:
        assert any(relatorio["rotas"][n].get("ok") for n in outras)


def test_property12_relatorio_diz_qual_tabela_esta_ativa(monkeypatch):
    monkeypatch.setattr(llm, "chamar", lambda *a, **k: "OK")
    monkeypatch.setitem(sys.modules, "visao", None)

    saida = io.StringIO()
    with redirect_stdout(saida):
        relatorio = llm.diagnosticar()

    assert relatorio["tabela_ativa"] == llm.TABELA_ATIVA
    assert llm.TABELA_ATIVA in saida.getvalue()


def test_property12_relatorio_traz_rotas_por_provedor(monkeypatch):
    monkeypatch.setattr(llm, "chamar", lambda *a, **k: "OK")
    monkeypatch.setitem(sys.modules, "visao", None)

    with redirect_stdout(io.StringIO()):
        relatorio = llm.diagnosticar()

    assert relatorio["rotas_orfas"] == []
    total = sum(len(v) for v in relatorio["rotas_por_provedor"].values())
    assert total == len(llm.ROTAS)


def test_property12_diagnostico_nao_fala_mais_de_gateway(monkeypatch):
    """
    O diagnóstico tinha uma seção [0] só pro gateway do Kiro. Ela saiu; se
    voltar a aparecer no relatório é porque alguém reintroduziu o subprocesso.
    """
    monkeypatch.setattr(llm, "chamar", lambda *a, **k: "OK")
    monkeypatch.setitem(sys.modules, "visao", None)

    saida = io.StringIO()
    with redirect_stdout(saida):
        relatorio = llm.diagnosticar()

    assert "gateway" not in relatorio
    texto = saida.getvalue().lower()
    assert "gateway" not in texto
    assert "kiro" not in texto


# ═════════════════════════════════════════════════════════════════
# Property 13: Sistema unificado de provedores (seções do .env)
#
# "Para qualquer .env com seções [PROVEDOR:*] válidas, PROVEDORES contém
# todos os provedores descobertos; PROVEDORES_CONFIG tem as configs; e
# listar_provedores() devolve um item por provedor com seus modelos."
# ═════════════════════════════════════════════════════════════════


def test_property13_provedores_e_config_alinhados():
    """O dict de instâncias e o dict de configs têm as mesmas chaves."""
    assert set(llm.PROVEDORES) == set(llm.PROVEDORES_CONFIG), (
        f"PROVEDORES={sorted(llm.PROVEDORES)} != "
        f"PROVEDORES_CONFIG={sorted(llm.PROVEDORES_CONFIG)}"
    )


def test_property13_listar_provedores_tem_um_item_por_provedor():
    """Um item por provedor registrado, menos os ocultos e os sem modelo.

    Ocultos (EMILY_PROVEDOR_<X>_OCULTO=1) e seções sem modelos ficam fora do
    seletor de propósito, mas continuam em PROVEDORES (servem de fallback).
    """
    saida = llm.listar_provedores()
    ids = {p["id"] for p in saida}
    esperados = {
        pid for pid in llm.PROVEDORES
        if not (llm.PROVEDORES_CONFIG.get(pid) and (
            llm.PROVEDORES_CONFIG[pid].oculto or not llm._modelos_provedor(pid)))
    }
    assert ids == esperados, (
        f"listar_provedores()={ids} != esperados={esperados}"
    )
    assert len(saida) == len(ids), "provedor repetido no seletor"
    for p in saida:
        assert isinstance(p.get("modelos"), list)
        assert p.get("nome")


def test_property13_modelos_disponiveis_so_do_provedor_ativo():
    """modelos_disponiveis() é só a lista do provedor ativo (compat antiga)."""
    modelos = llm.modelos_disponiveis()
    pid = llm.TABELA_ATIVA
    cfg = llm.PROVEDORES_CONFIG.get(pid)
    if cfg is not None:
        # Modo dinâmico: a lista do ativo vem de _modelos_provedor.
        esperado = {m["id"] for m in llm._modelos_provedor(pid)}
    else:
        esperado = {m["id"] for m in llm._MODELOS_POR_TABELA.get(pid, [])}
    assert {m["id"] for m in modelos} == esperado


def test_property13_definir_provedor_e_modelo_aceita_provedor_valido():
    """Mudar provedor em runtime atualiza TABELA_ATIVA e o modelo da conversa."""
    # Pega qualquer provedor diferente do ativo.
    candidatos = [p for p in llm.PROVEDORES if p != llm.TABELA_ATIVA]
    if not candidatos:
        pytest.skip("só há um provedor no ambiente; troca impossível")
    novo_pid = candidatos[0]
    novo_modelo = llm.PROVEDORES_CONFIG.get(novo_pid)
    if novo_modelo and novo_modelo.modelos_csv:
        modelo_alvo = novo_modelo.modelos_csv[0]
    else:
        modelo_alvo = llm.PROVEDORES_CONFIG[novo_pid].modelo_padrao or "x"

    with recarregado_com({}):
        assert llm.definir_provedor_e_modelo(novo_pid, modelo_alvo) is True
        assert llm.TABELA_ATIVA == novo_pid
        assert llm.ROTAS["conversa"].modelo == modelo_alvo


def test_property13_definir_provedor_e_modelo_rejeita_provedor_invalido():
    """Provedor que não está em PROVEDORES é rejeitado sem efeito colateral."""
    ativo_antes = llm.TABELA_ATIVA
    modelo_antes = llm.ROTAS["conversa"].modelo
    assert llm.definir_provedor_e_modelo("inventado", "qualquer") is False
    assert llm.TABELA_ATIVA == ativo_antes
    assert llm.ROTAS["conversa"].modelo == modelo_antes


def test_property13_secoes_do_env_povoam_provedores_config(tmp_path, monkeypatch):
    """
    Com um .env sintético de seções, o loader popula PROVEDORES_CONFIG com
    a config correspondente (nome, base, tipo, modelos_csv).
    """
    env_falso = tmp_path / ".env"
    env_falso.write_text(
        "# >>> provedor: teste_a\n"
        "EMILY_PROVEDOR_TESTE_A_NOME=Teste A\n"
        "EMILY_PROVEDOR_TESTE_A_BASE=https://a.example/v1\n"
        "EMILY_PROVEDOR_TESTE_A_CHAVE=CHAVE_A\n"
        "EMILY_PROVEDOR_TESTE_A_MODELO=modelo-a-1\n"
        "EMILY_PROVEDOR_TESTE_A_MODELOS=modelo-a-1,modelo-a-2\n"
        "EMILY_PROVEDOR_TESTE_A_TIMEOUT=60\n"
        "# <<< provedor: teste_a\n"
        "# >>> provedor: teste_b\n"
        "EMILY_PROVEDOR_TESTE_B_BASE=http://localhost:11434/v1\n"
        "EMILY_PROVEDOR_TESTE_B_MODELO=local-model\n"
        "EMILY_PROVEDOR_TESTE_B_SEM_CHAVE=1\n"
        "EMILY_PROVEDOR_TESTE_B_TIPO=ollama\n"
        "# <<< provedor: teste_b\n",
        encoding="utf-8",
    )
    # Redireciona DIR_PROJETO pro tmp_path via patch.
    import importlib
    monkeypatch.setattr(llm, "DIR_PROJETO", str(tmp_path))
    secos = llm._parsear_secoes_provedor(str(env_falso))
    assert "teste_a" in secos
    assert "teste_b" in secos
    a = secos["teste_a"]
    assert a.nome_exibicao == "Teste A"
    assert a.base_url == "https://a.example/v1"
    assert a.modelos_csv == ["modelo-a-1", "modelo-a-2"]
    assert a.timeout == 60.0
    b = secos["teste_b"]
    assert b.tipo == "ollama"
    assert b.env_chave_opcional is True


def test_property13_secoes_malformadas_sao_ignoradas(tmp_path, monkeypatch):
    """Se a marca de fechamento não bate com a de abertura, ignora a seção."""
    env_falso = tmp_path / ".env"
    env_falso.write_text(
        "# >>> provedor: z\n"
        "EMILY_PROVEDOR_Z_BASE=https://z.example/v1\n"
        "# <<< provedor: outro\n",   # fechamento com nome diferente
        encoding="utf-8",
    )
    monkeypatch.setattr(llm, "DIR_PROJETO", str(tmp_path))
    secos = llm._parsear_secoes_provedor(str(env_falso))
    # A seção "z" foi aberta mas não fechada; o estado interno do parser
    # volta a None, então variáveis da "z" não são coletadas.
    assert secos == {}


def test_provedor_openai_anthropic_cria_transporte_hibrido():
    """O relay usa Chat Completions em texto e Messages API em visão."""
    cfg = llm.ProvedorConfig(
        id="relay_hibrido", nome_exibicao="Relay híbrido",
        base_url="https://relay.example/v1", env_chave="CHAVE_RELAY",
        env_chave_opcional=False, modelo_padrao="claude-sonnet",
        modelos_csv=["claude-sonnet"], timeout=60.0, rpm=10,
        tipo="openai_anthropic",
    )

    provedor = llm._instanciar_provedor(cfg)

    assert isinstance(provedor, llm.ProvedorOpenAIComVisaoAnthropic)
    assert provedor.base_url == "https://relay.example/v1"
    assert provedor._visao_anthropic.base_url == "https://relay.example"


# ═════════════════════════════════════════════════════════════════
# Provedor novo (seção do .env) x rota do Discord
#
# O bug real: trocar o provedor na interface pra um provedor novo (Qwen,
# GMI, ...) construía tabela com SÓ a rota 'conversa'. O Discord chama por
# nome ("discord"), não achava na tabela ativa e caía no fallback da
# tabela do claude — que pode estar fora. A Emily ficava muda no Discord
# mesmo com o provedor escolhido funcionando.
# ═════════════════════════════════════════════════════════════════

def _provedor_novo(monkeypatch, pid="xyzteste", modelos=("xyz-1", "xyz-2")):
    """Registra um provedor sintético (seção .env) sem tocar os reais."""
    cfg = llm.ProvedorConfig(
        id=pid, nome_exibicao="XYZ", base_url="https://xyz.example/v1",
        env_chave="XYZ_API_KEY", env_chave_opcional=True,
        modelo_padrao=modelos[0], modelos_csv=list(modelos),
        timeout=30.0, rpm=10, tipo="openai",
    )
    monkeypatch.setitem(llm.PROVEDORES_CONFIG, pid, cfg)
    monkeypatch.setitem(llm.PROVEDORES, pid, object())
    # Cópia: se o teste resolver a tabela sob demanda, a inserção em
    # TABELAS vai pra cópia e é descartada junto com o monkeypatch.
    monkeypatch.setattr(llm, "TABELAS", dict(llm.TABELAS))
    return pid, cfg


def test_tabela_de_provedor_novo_inclui_rota_discord_do_proprio_provedor(monkeypatch):
    """A tabela sob demanda precisa nascer com rota 'discord' própria."""
    pid, _cfg = _provedor_novo(monkeypatch)
    tabela = llm._construir_tabela_provedor(pid)
    assert "discord" in tabela, (
        "tabela de provedor novo sem rota 'discord': o Discord cairia na "
        "tabela do claude"
    )
    assert tabela["discord"].provedor == pid
    assert tabela["discord"].modelo
    assert tabela["discord"].max_tokens > 0


def test_trocar_provedor_na_interface_alcanca_a_rota_discord(monkeypatch):
    """definir_provedor_e_modelo troca o modelo da rota discord também."""
    pid, _cfg = _provedor_novo(monkeypatch)
    monkeypatch.setattr(llm, "TABELA_ATIVA", "claude")
    monkeypatch.setattr(llm, "ROTAS", llm.TABELAS["claude"])

    assert llm.definir_provedor_e_modelo(pid, "xyz-2")

    assert llm.TABELA_ATIVA == pid
    assert llm.ROTAS["discord"].provedor == pid
    assert llm.ROTAS["discord"].modelo == "xyz-2"


def test_rota_discord_de_provedor_novo_nao_cai_na_tabela_do_claude(monkeypatch):
    """rota('discord') com provedor novo ativo devolve a rota DELE."""
    pid, _cfg = _provedor_novo(monkeypatch)
    tabela = llm._construir_tabela_provedor(pid)
    monkeypatch.setattr(llm, "TABELA_ATIVA", pid)
    monkeypatch.setattr(llm, "ROTAS", tabela)

    r = llm.rota("discord")

    assert r.provedor == pid, (
        f"rota 'discord' resolveu para o provedor '{r.provedor}' em vez do "
        f"ativo '{pid}'"
    )


def test_override_de_modelo_do_discord_de_outro_provedor_e_ignorado(monkeypatch):
    """Pref de modelo do Discord salva com outro provedor não pode virar 400.

    O override só vale quando o modelo pode ser servido pelo provedor da
    rota ativa; senão a rota usa o modelo que a troca de provedor aplicou.
    """
    pid, _cfg = _provedor_novo(monkeypatch)
    r_discord = llm.Rota(
        provedor=pid, modelo="xyz-1", max_tokens=200,
        raciocinio=llm.RACIOCINIO_DESLIGADO, temperatura=0.9, rpm=10,
    )

    # Modelo de OUTRO provedor (claude): ignorado, mantém o da rota.
    monkeypatch.setattr(llm, "_discord_modelo_override", "kr/claude-sonnet-4.5")
    assert llm._com_override("discord", r_discord).modelo == "xyz-1"

    # Modelo do PRÓPRIO provedor: continua aplicando (comportamento antigo).
    monkeypatch.setattr(llm, "_discord_modelo_override", "xyz-2")
    assert llm._com_override("discord", r_discord).modelo == "xyz-2"


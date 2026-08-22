"""
Properties 5, 6, 7 e 12 do design — tabelas de rotas e reversão.

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
# "Para qualquer estado do código, as tabelas ROTAS_KIRO e ROTAS_NVIDIA têm
# exatamente o mesmo conjunto de nomes de rota, e toda rota das duas aponta
# para um provedor registrado em PROVEDORES e tem max_tokens positivo."
#
# Validates: Requirements 5.1, 6.1, 9.2
# ═════════════════════════════════════════════════════════════════

def test_property5_paridade_de_nomes():
    """
    A paridade é o que impede a reversão de virar uma armadilha: uma rota
    que existe no Kiro e não no NIM só quebraria DEPOIS de reverter, no pior
    momento possível.
    """
    so_no_kiro = set(llm.ROTAS_KIRO) - set(llm.ROTAS_NVIDIA)
    so_no_nvidia = set(llm.ROTAS_NVIDIA) - set(llm.ROTAS_KIRO)

    assert not so_no_kiro, f"rota(s) só no Kiro: {sorted(so_no_kiro)}"
    assert not so_no_nvidia, f"rota(s) só no NIM: {sorted(so_no_nvidia)}"
    assert set(llm.ROTAS_KIRO) == set(llm.ROTAS_NVIDIA)


def test_property5_todas_as_rotas_esperadas_existem():
    for tabela_nome, tabela in llm.TABELAS.items():
        faltando = ROTAS_ESPERADAS - set(tabela)
        assert not faltando, f"tabela '{tabela_nome}' não tem: {sorted(faltando)}"


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


def test_property5_tabela_kiro_toda_no_provedor_kiro():
    """A migração está completa: nenhuma rota sobrou apontando pro NIM."""
    fora = {n: c.provedor for n, c in llm.ROTAS_KIRO.items() if c.provedor != "kiro"}
    assert not fora, f"rotas da tabela kiro fora do provedor kiro: {fora}"


def test_property5_tabela_nvidia_toda_no_provedor_nvidia():
    fora = {n: c.provedor for n, c in llm.ROTAS_NVIDIA.items() if c.provedor != "nvidia"}
    assert not fora, f"rotas da tabela nvidia fora do provedor nvidia: {fora}"


# ═════════════════════════════════════════════════════════════════
# Property 6: Seleção de tabela por variável de ambiente
#
# "Para qualquer valor de EMILY_PROVEDOR_LLM, a tabela ativa é a
# correspondente quando o valor (normalizado) é conhecido, e é levantado
# ErroConfiguracao citando os valores aceitos quando não é; com a variável
# ausente, a tabela ativa é a do Kiro."
#
# Validates: Requirements 9.1, 9.3
# ═════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("valor,esperado", [
    ("kiro", "kiro"),
    ("nvidia", "nvidia"),
    ("KIRO", "kiro"),
    ("NVIDIA", "nvidia"),
    ("  kiro  ", "kiro"),
    ("\tnvidia\n", "nvidia"),
    ("KiRo", "kiro"),
])
def test_property6_normalizacao_do_valor(valor, esperado):
    """Espaço nas pontas e caixa não decidem nada — .env copiado à mão vem sujo."""
    nome, tabela = llm._resolver_tabela(valor)
    assert nome == esperado
    assert tabela is llm.TABELAS[esperado]


@pytest.mark.parametrize("ausente", [None, "", "   ", "\n", "\t  "])
def test_property6_ausente_cai_no_default_kiro(ausente):
    nome, tabela = llm._resolver_tabela(ausente)
    assert nome == llm.TABELA_PADRAO == "kiro"
    assert tabela is llm.ROTAS_KIRO


@settings(max_examples=200)
@given(valor=st.text(min_size=1, max_size=30))
def test_property6_valor_desconhecido_levanta_com_os_aceitos(valor):
    """
    Nunca cair no default em silêncio.

    Se o Vitor digitar 'nvida' por engano, ele precisa saber na hora — e não
    descobrir três dias depois que estava no Kiro o tempo todo, achando que
    tinha revertido.
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
        llm._resolver_tabela("nvida")
    assert "nvidia" in str(capturado.value)
    assert "kiro" in str(capturado.value)


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
# Validates: Requirements 9.4
#
# Precisa recarregar o módulo porque as constantes são lidas no import — que
# é o comportamento certo (ler .env em toda chamada seria desperdício), mas
# obriga o teste a simular o boot.
# ═════════════════════════════════════════════════════════════════

# variável de ambiente -> rotas que ela deve afetar
GRUPOS = {
    "EMILY_KIRO_MODELO_CONVERSA": {"conversa", "comando", "extracao", "discord"},
    "EMILY_KIRO_MODELO_BARATO": {"classificador", "triagem_visual"},
    "EMILY_KIRO_MODELO_VISAO": {"visao"},
    "EMILY_KIRO_MODELO_AGENTE_UI": {"agente_ui"},
    "EMILY_KIRO_MODELO_AGENTE_JOGO": {"agente_jogo"},
}


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


@pytest.mark.parametrize("variavel,rotas_do_grupo", sorted(GRUPOS.items()))
def test_property7_variavel_afeta_apenas_seu_grupo(variavel, rotas_do_grupo):
    marcador = "modelo-de-teste-xyz"
    with recarregado_com({variavel: marcador}) as novo:
        usando = {n for n, c in novo.ROTAS_KIRO.items() if c.modelo == marcador}
        assert usando == rotas_do_grupo, (
            f"{variavel}={marcador} afetou {sorted(usando)}, "
            f"esperado {sorted(rotas_do_grupo)}"
        )


@settings(max_examples=25, deadline=None)
@given(modelo=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-.",
                      min_size=1, max_size=30))
def test_property7_qualquer_nome_de_modelo_e_aceito(modelo):
    """
    Nome de modelo é repassado literalmente, sem validação nossa.

    É deliberado e casa com o resolver do gateway, que é pass-through: quem
    decide se o modelo existe é a API do Kiro, não a Emily. Validar aqui
    significaria bloquear modelo novo que a conta já tem — foi exatamente o
    caso do claude-sonnet-5, que funciona sem aparecer no /v1/models.
    """
    with recarregado_com({"EMILY_KIRO_MODELO_AGENTE_UI": modelo}) as novo:
        assert novo.ROTAS_KIRO["agente_ui"].modelo == modelo


def test_property7_sem_variavel_usa_o_default_documentado():
    with recarregado_com({
        "EMILY_KIRO_MODELO_CONVERSA": None,
        "EMILY_KIRO_MODELO_AGENTE_UI": None,
        "EMILY_KIRO_MODELO_BARATO": None,
    }) as novo:
        assert novo.ROTAS_KIRO["conversa"].modelo == "claude-sonnet-5"
        assert novo.ROTAS_KIRO["agente_ui"].modelo == "claude-opus-5"
        assert novo.ROTAS_KIRO["classificador"].modelo == "claude-haiku-4.5"


def test_property7_reversao_por_uma_linha_de_env():
    """
    O ponto da Task 9: uma variável devolve a Emily inteira pro NIM.
    """
    with recarregado_com({"EMILY_PROVEDOR_LLM": "nvidia"}) as novo:
        assert novo.TABELA_ATIVA == "nvidia"
        assert set(novo.ROTAS) == ROTAS_ESPERADAS
        provedores = {c.provedor for c in novo.ROTAS.values()}
        assert provedores == {"nvidia"}


# ═════════════════════════════════════════════════════════════════
# Property 12: Diagnóstico cobre a tabela ativa por inteiro
#
# "Para qualquer tabela de rotas ativa, o diagnóstico exercita todas as rotas
# dessa tabela e relata, para cada uma, sucesso ou o motivo da falha, sem
# interromper as rotas seguintes quando uma falha."
#
# Validates: Requirements 11.1, 11.2, 11.3
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
    Requisito 11.2: o diagnóstico serve para dizer O QUE está quebrado. Se
    parasse na primeira falha, diria apenas "algo está quebrado".
    """
    quebrada = "comando"

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

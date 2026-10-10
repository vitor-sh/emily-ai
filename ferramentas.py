"""
ferramentas.py — Catálogo de ferramentas que a Emily pode invocar sozinha.

Por que esse arquivo existe
───────────────────────────
Antes, para a Emily fazer algo era preciso uma cascata: palavra-chave em
intencoes.py, depois um filtro de keywords em automacao.py, depois um prompt
estático de 8.178 tokens interpretando a frase, e por fim um classificador de
"confiança" que só executava se o resultado fosse 'alta'. Cada camada era
mais uma chance de a Emily não entender um pedido óbvio.

Com tool calling, o próprio modelo lê a conversa, decide que ferramenta usar
e já extrai os argumentos. Este módulo é a ponte: descreve as ferramentas em
JSON Schema para o modelo e liga cada uma ao código que já funciona.

O que ele NÃO faz
─────────────────
Não reimplementa nada. Toda ação de automação cai em
automacao._executar_acao_por_dict, que é o executor de 723 linhas que já
resolve busca fuzzy de app, catálogo da Steam, resolução de drive e pasta,
undo, etc. A ferramenta só monta o dicionário que ele espera.

Modos da Emily (modo escrito, controle de tela, monitoramento de jogo, escuta
do Discord) mexem em estado global do main.py — thread, evento, status da
janela. Esses não são chamados direto: o main.py registra um handler com
registrar_handler() e a ferramenta chama o que foi registrado.
"""

from __future__ import annotations

import datetime
import json
import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

# Ferramentas destrutivas só rodam sozinhas se isso estiver ligado.
# automacao.py tem sistema de desfazer para operações de arquivo, mas
# deletar por decisão autônoma de um modelo merece uma tranca.
PERMITIR_DESTRUTIVAS = os.getenv("EMILY_FERRAMENTAS_DESTRUTIVAS", "1").strip() == "1"


def _log(msg: str) -> None:
    print(f"[FERRAMENTAS] {msg}")


# ═════════════════════════════════════════════════════════════════
# ESTRUTURA
# ═════════════════════════════════════════════════════════════════

@dataclass
class Ferramenta:
    nome: str
    descricao: str
    executar: Callable[..., str]
    propriedades: dict = field(default_factory=dict)
    obrigatorios: List[str] = field(default_factory=list)
    # Frase que a Emily fala antes de executar, pra não ficar muda enquanto
    # a ferramenta roda. Vazio = não fala nada.
    aviso: str = ""
    # Quando o aviso depende dos ARGUMENTOS. Existe por causa do definir_modo:
    # ligar o modo escrito e desligar são a mesma ferramenta agora, e a frase
    # que ela fala tem que ser diferente. Recebe os argumentos, devolve a
    # categoria de aviso (ou "" pra ficar calada).
    aviso_dinamico: Optional[Callable[[dict], str]] = None
    # Ferramenta que apaga ou move coisas do Vitor.
    destrutiva: bool = False
    # Domínio da ferramenta. Existe pra poder mandar ao modelo um SUBCONJUNTO
    # do catálogo: um pedido que chegou pelo chat do Discord não precisa das
    # 33 ferramentas de automação do Windows na mesa, e o catálogo inteiro é
    # prompt pago em toda chamada. Ver esquemas(grupos=...).
    grupo: str = "geral"
    # Pode rodar ao mesmo tempo que outra paralelizável, quando o modelo pede
    # várias na mesma resposta. Só marque como True se a ferramenta:
    #   1. só LÊ — não mexe em arquivo, janela, mouse, teclado nem estado global
    #   2. gasta tempo esperando rede ou modelo, senão não há ganho
    # O default é False de propósito: duas ferramentas de automação em paralelo
    # disputam o mouse do Vitor e desrespeitam a ordem em que ele pediu.
    paralelizavel: bool = False
    # Só LÊ: não muda nada no mundo. Alimenta o 'mudou' do ResultadoFerramenta,
    # que alimenta o 'agiu' do motor, que alimenta a máquina de promessa.
    #
    # O default é False (= "muda o mundo") de propósito, e é o lado seguro:
    # errar pra "mudou" faz a Emily não repetir uma ação que já aconteceu.
    # Errar pra "não mudou" faria ela executar de novo.
    somente_leitura: bool = False

    def esquema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.nome,
                "description": self.descricao,
                "parameters": {
                    "type": "object",
                    "properties": self.propriedades,
                    "required": self.obrigatorios,
                },
            },
        }


CATALOGO: Dict[str, Ferramenta] = {}


# ═════════════════════════════════════════════════════════════════
# RESULTADO ESTRUTURADO
#
# O PROBLEMA, MEDIDO
# ──────────────────
# executar() devolvia só uma string, e quem chamava tinha que ADIVINHAR pelo
# português se a ferramenta fez, recusou ou explodiu. O modelo.py adivinhava com
# uma lista de 24 frases (_MARCAS_RECUSA). Medido contra os quatro casos que
# importam, a lista errava TODOS os mecânicos:
#
#   ferramenta que explodiu com RuntimeError  -> contava como FEITO
#   argumento obrigatório faltando            -> contava como FEITO
#   ferramenta que não existe no catálogo     -> contava como FEITO
#
# Isso não é detalhe de log. Esse booleano alimenta a máquina de promessa: com
# "feito", o pedido do Vitor é marcado como cumprido, a cobrança do turno
# seguinte não acontece, e o pedido morre calado — ou pior, ela diz "pronto,
# feito" sobre uma ferramenta que levantou exceção.
#
# A SOLUÇÃO
# ─────────
# Quem sabe se deu certo é quem executou, não quem lê o texto depois. As falhas
# MECÂNICAS (exceção, argumento faltando, ferramenta inexistente, destrutiva
# bloqueada) agora são fato, não palpite.
#
# Para a recusa de DOMÍNIO ("não montei o pack porque falta dependência") quem
# sabe é a própria ferramenta. Ela declara devolvendo ResultadoFerramenta em vez
# de str — ver recusa() e consulta() logo abaixo. As 148 que devolvem str
# continuam funcionando: caem na heurística de texto, que fica aqui, isolada e
# marcada como legado, em vez de espalhada pelo modelo.py.
# ═════════════════════════════════════════════════════════════════

@dataclass
class ResultadoFerramenta:
    """O que aconteceu quando a ferramenta rodou."""
    texto: str                      # o que volta pro modelo (e às vezes pro chat)
    ok: bool = True                 # fez o que foi pedido?
    mudou: bool = True              # mudou algo no mundo, ou só consultou/recusou?
    erro: Optional[str] = None      # tipo da exceção, quando houve

    def __str__(self) -> str:       # pra quem ainda trata como string
        return self.texto


def recusa(motivo: str) -> ResultadoFerramenta:
    """
    Para a ferramenta dizer 'rodei e NÃO fiz', com o motivo.

    Use isto em vez de devolver a frase seca: com str, quem chama volta a
    depender de reconhecer o português da recusa.
    """
    return ResultadoFerramenta(texto=motivo, ok=False, mudou=False)


def consulta(texto: str) -> ResultadoFerramenta:
    """Para ferramenta que só LÊ: deu certo, e não mudou nada no mundo."""
    return ResultadoFerramenta(texto=texto, ok=True, mudou=False)


# Sem pedido explícito, só estas ferramentas podem mudar alguma coisa. O prompt
# pode sugerir qualquer ação; esta lista é a garantia mecânica de que uma leitura
# emocional errada nunca vira terminal, arquivo, mensagem externa ou moderação.
INICIATIVAS_BAIXO_IMPACTO = frozenset({
    "abrir_app", "abrir_jogo", "abrir_site", "tocar_musica", "player_tocar",
})


def iniciativa_espontanea_permitida(nome: str) -> bool:
    return nome in INICIATIVAS_BAIXO_IMPACTO


_historico_iniciativas: List[dict] = []
_lock_iniciativas = threading.Lock()
_MAX_INICIATIVAS_DESFAZER = 20


def _registrar_iniciativa_desfazivel(nome: str, argumentos: dict) -> bool:
    """Guarda ação simples com inversa local e confiável. True se registrou."""
    args = dict(argumentos or {})
    entrada = None
    if nome in ("abrir_app", "abrir_jogo") and args.get("nome"):
        alvo = str(args["nome"])
        entrada = {
            "descricao": f"abertura de '{alvo}'",
            "desfazer": lambda alvo=alvo: _automacao("fechar_app", alvo=alvo),
        }
    elif nome in ("abrir_site", "tocar_musica"):
        entrada = {
            "descricao": "aba aberta pela Emily",
            "desfazer": lambda: _automacao("fechar_aba"),
        }
    elif nome == "player_tocar":
        entrada = {
            "descricao": "música iniciada pela Emily",
            "desfazer": lambda: _comando_player("pausar"),
        }
    if entrada is None:
        return False
    with _lock_iniciativas:
        _historico_iniciativas.append(entrada)
        del _historico_iniciativas[:-_MAX_INICIATIVAS_DESFAZER]
    return True


def _desfazer_iniciativa_recente() -> Optional[str]:
    with _lock_iniciativas:
        if not _historico_iniciativas:
            return None
        entrada = _historico_iniciativas.pop()
    try:
        resultado = entrada["desfazer"]()
    except Exception:
        with _lock_iniciativas:
            _historico_iniciativas.append(entrada)
        raise
    return f"Desfiz a {entrada['descricao']}. {resultado or ''}".strip()


def _invalidar_iniciativas_anteriores() -> None:
    """Uma mutação explícita posterior passa a ser a verdadeira 'última ação'."""
    with _lock_iniciativas:
        _historico_iniciativas.clear()


# Handlers que dependem do estado do main.py.
_handlers: Dict[str, Callable[..., str]] = {}
_lock_handlers = threading.Lock()


def registrar_handler(nome: str, funcao: Callable[..., str]) -> None:
    """
    O main.py usa isso pra ligar as ferramentas de modo, que precisam mexer
    em threads, eventos e status da janela.
    """
    with _lock_handlers:
        _handlers[nome] = funcao


def _chamar_handler(nome: str, **kwargs) -> str:
    with _lock_handlers:
        fn = _handlers.get(nome)
    if fn is None:
        return (f"A ferramenta '{nome}' não está ligada nesta sessão. "
                f"Avise que esse recurso não está disponível agora.")
    return fn(**kwargs) or "Feito."


def registrar(f: Ferramenta) -> Ferramenta:
    # Blindagem: descricao como tupla (vírgula sobrando no parêntese)
    # serializaria como array JSON e derrubaria gateways que chamam
    # .trim no campo — já derrubou uma vez. Junta tudo numa string.
    if isinstance(f.descricao, (tuple, list)):
        f.descricao = "".join(str(parte) for parte in f.descricao)
    CATALOGO[f.nome] = f
    return f


_cloud_carregada = False
_lock_cloud = threading.Lock()


def _carregar_cloud_se_preciso(grupos=None, nomes=None) -> None:
    """Registra o domínio nuvem somente quando ele for realmente solicitado."""
    global _cloud_carregada
    solicitado = "nuvem" in (grupos or ()) or any(
        str(nome).startswith("nuvem_") for nome in (nomes or ()))
    if not solicitado or _cloud_carregada:
        return
    with _lock_cloud:
        if _cloud_carregada:
            return
        import ferramentas_cloud
        ferramentas_cloud.registrar_catalogo(
            registrar, Ferramenta, consulta, ResultadoFerramenta, recusa)
        _cloud_carregada = True


def esquemas(grupos: Optional[List[str]] = None) -> List[dict]:
    """
    Catálogo no formato que o endpoint espera em 'tools'.

    grupos — se informado, só as ferramentas desses domínios entram. Sem
    argumento devolve tudo, que é o que o caminho de voz do Vitor usa.
    """
    try:
        import modo_demo
        em_demo = modo_demo.ativo()
    except Exception:
        em_demo = False
    # Durante a demo não carregamos sequer o catálogo Cloud real por efeito
    # colateral. A allowlist usa apenas ferramentas já registradas e seguras.
    if not em_demo:
        _carregar_cloud_se_preciso(grupos=grupos)
    if grupos is None:
        ferramentas = list(CATALOGO.values())
        if em_demo:
            ferramentas = [f for f in ferramentas if modo_demo.ferramenta_permitida(f.nome)]
        return [f.esquema() for f in ferramentas]
    permitidos = set(grupos)
    return [f.esquema() for f in CATALOGO.values()
            if f.grupo in permitidos and (not em_demo or modo_demo.ferramenta_permitida(f.nome))]


def nomes_do_grupo(grupo: str) -> List[str]:
    try:
        import modo_demo
        em_demo = modo_demo.ativo()
    except Exception:
        em_demo = False
    if not em_demo:
        _carregar_cloud_se_preciso(grupos=[grupo])
    return [nome for nome, f in CATALOGO.items()
            if f.grupo == grupo and (not em_demo or modo_demo.ferramenta_permitida(nome))]


def esquemas_por_nome(nomes: List[str]) -> List[dict]:
    """
    Catálogo com ferramentas escolhidas a dedo, na ordem pedida.

    Existe porque grupo é uma divisão grossa demais para o chat do Minecraft. Lá
    ela precisa de UMA ferramenta (mexer no próprio corpo) e não das 34 do
    servidor: o chat do jogo é movimentado, cada mensagem pagaria o catálogo
    inteiro, e ela não administra nada por ali de propósito — o servidor é
    offline-mode, então nome de jogador não prova identidade.

    Nome que não existe é ignorado em silêncio? Não: vai pro log. Errar o nome
    aqui faria a ferramenta desaparecer da mesa sem nenhum sinal, e "ela não faz
    o que eu pedi" é o sintoma mais difícil de rastrear que já tivemos.
    """
    try:
        import modo_demo
        em_demo = modo_demo.ativo()
    except Exception:
        em_demo = False
    nomes = [str(nome) for nome in (nomes or [])
             if not em_demo or modo_demo.ferramenta_permitida(nome)]
    if not em_demo:
        _carregar_cloud_se_preciso(nomes=nomes)
    saida = []
    for nome in nomes:
        f = CATALOGO.get(nome)
        if f is None:
            _log(f"esquemas_por_nome: '{nome}' não existe no catálogo")
            continue
        saida.append(f.esquema())
    return saida


def existe(nome: str) -> bool:
    _carregar_cloud_se_preciso(nomes=[nome])
    return nome in CATALOGO


def aviso_de(nome: str, argumentos: Optional[dict] = None) -> str:
    """
    Categoria de aviso falado antes de rodar a ferramenta.

    Aceita os argumentos porque uma ferramenta pode precisar de aviso diferente
    conforme o que foi pedido — ligar e desligar um modo são a mesma ferramenta
    e não são a mesma frase.
    """
    _carregar_cloud_se_preciso(nomes=[nome])
    f = CATALOGO.get(nome)
    if f is None:
        return ""
    if f.aviso_dinamico is not None:
        try:
            return f.aviso_dinamico(argumentos or {}) or ""
        except Exception as e:  # noqa: BLE001
            _log(f"aviso_dinamico de '{nome}' falhou: {e}")
            return f.aviso
    return f.aviso


def executar(nome: str, argumentos: dict) -> str:
    """
    Compatibilidade: roda a ferramenta e devolve só o texto.

    Quem precisa saber se DEU CERTO tem que usar executar_estruturado(). Esta
    função existe porque há call sites antigos que só querem a string.
    """
    return executar_estruturado(nome, argumentos).texto


# ─────────────────────────────────────────────
# LEGADO: como as ferramentas deste projeto recusam EM TEXTO
#
# Levantado lendo os returns reais das ferramentas deste arquivo — não é lista
# adivinhada. Morava no modelo.py e foi
# trazida pra cá porque o lugar certo de interpretar o retorno de uma ferramenta
# é ao lado de quem a executa, uma vez, e não em cada laço que a consome.
#
# Só se aplica a ferramenta que devolve str. Ferramenta que devolve
# ResultadoFerramenta não passa por aqui — ela DIZ o que aconteceu, e é pra lá
# que as ferramentas importantes devem migrar.
#
# Na dúvida o padrão é CONTAR COMO FEITO, de propósito. Errar pra "não fez" faz
# a máquina de promessa cobrar de novo uma ação que já aconteceu, e ela poderia
# executar duas vezes.
# ─────────────────────────────────────────────

_MARCAS_RECUSA = (
    "não montei", "não acrescentei", "não consegui", "não mudei nada",
    "não veio nada", "não sobrou nenhuma mudança", "nada foi alterado",
    "não foi alterado", "nada casou com isso", "não fui capaz", "bloqueado.",
    "recuse a ação", "e meu limite é", "e meu limite por vez é",
    "meu teto por vez é", "meu teto é", "já existe pack com id",
    "não tenho análise", "não analisei", "não achei nenhum",
    "não achei nenhuma", "preciso do nome", "me diz o que", "me diz qual",
    "me diz o nome", "todos esses",
)

# Só o COMEÇO do resultado é examinado. As recusas deste projeto abrem com o
# motivo; mensagem de sucesso pode mencionar "não achei 2 dependências" mais
# adiante e não é recusa nenhuma.
_JANELA_RECUSA = 220


def parece_recusa_em_texto(resultado: str) -> bool:
    """A ferramenta devolveu str e essa str tem cara de recusa?"""
    if not resultado or not resultado.strip():
        return True
    baixo = " ".join(resultado.lower().split())[:_JANELA_RECUSA]
    return any(m in baixo for m in _MARCAS_RECUSA)


from diagnostico_execucao import measured as _medir_execucao


@_medir_execucao("tool", "nome")
def executar_estruturado(nome: str, argumentos: dict,
                         contexto: Optional[dict] = None) -> ResultadoFerramenta:
    """
    Roda uma ferramenta e devolve o que aconteceu, com ok/mudou já decididos.

    Erro nunca sobe daqui: se subisse, derrubaria o laço de conversa e a Emily
    emudeceria. O modelo recebe a explicação e decide o que dizer.
    """
    try:
        import modo_demo
        if modo_demo.ativo() and not modo_demo.ferramenta_permitida(nome):
            _log(f"modo demo bloqueou ferramenta real: {nome}")
            return ResultadoFerramenta(
                texto=("Essa ação está bloqueada no Modo Demo porque poderia "
                       "acessar ou alterar o ambiente real. Use apenas recursos "
                       "demonstrativos ou consultas seguras."),
                ok=False, mudou=False, erro="bloqueada_modo_demo")
    except Exception:
        pass
    _carregar_cloud_se_preciso(nomes=[nome])
    f = CATALOGO.get(nome)
    if f is None:
        _log(f"modelo pediu ferramenta inexistente: {nome!r}")
        return ResultadoFerramenta(
            texto=f"A ferramenta '{nome}' não existe. Não invente ferramentas.",
            ok=False, mudou=False, erro="ferramenta_inexistente")

    # A quem a Emily deve perguntar quando falta informação.
    #
    # Isso era "o Vitor" fixo no texto, e passou a estar errado quando as
    # ferramentas de Discord entraram: um membro do servidor pede algo vago no
    # chat, a ferramenta reclama do argumento faltando, e a instrução mandava a
    # Emily perguntar ao Vitor — que não está na conversa.
    _GRUPOS_DE_CHAT = ("discord",)
    interlocutor = "quem pediu" if f.grupo in _GRUPOS_DE_CHAT else "o Vitor"

    contexto = dict(contexto or {})
    if (nome in {"perguntar_usuario_tarefa", "code_perguntar"}
            and contexto.get("permitir_pergunta_interativa") is False):
        return ResultadoFerramenta(
            texto="Responda no chat; este turno não é uma tarefa interativa.",
            ok=False, mudou=False, erro="pergunta_interativa_nao_autorizada")
    tem_politica_de_turno = bool(contexto)
    pedido_explicito = bool(contexto.get("pedido_explicito"))
    dono_confirmado = bool(contexto.get("dono_confirmado"))
    autonomia_ligada = bool(contexto.get("autonomia_experimental"))

    # Preparar código numa sessão existente não altera a instalação nem executa
    # comandos. A aplicação, publicação, USB e terminal continuam avaliados.
    preparacao_reversivel = False
    if nome in {'programacao_editar', 'programacao_criar', 'programacao_atualizar', 'programacao_resolver'}:
        try:
            import programacao
            programacao.load((argumentos or {}).get('sessao'))
            preparacao_reversivel = True
        except (ValueError, OSError, KeyError, TypeError): pass

    # Pedidos conversados não precisam caber numa lista de verbos. A avaliação
    # semântica recebe apenas o pedido humano e não substitui os portões abaixo.
    if tem_politica_de_turno and not pedido_explicito and not f.somente_leitura and not preparacao_reversivel:
        autorizar = contexto.get("autorizar_pedido")
        if callable(autorizar):
            try:
                pedido_explicito = autorizar(nome, argumentos or {}) is True
            except Exception:
                pedido_explicito = False
            if not pedido_explicito:
                if getattr(autorizar, 'ultima_falha', ''):
                    return ResultadoFerramenta(texto="A consulta de autorização não pôde ser validada pelo serviço de IA. Isso não é uma recusa do usuário nem uma limitação da ferramenta. Confira a conexão e tente validar novamente; nenhuma ação foi executada.", ok=False, mudou=False, erro="validacao_autorizacao_indisponivel")
                diagnostico = dict(getattr(autorizar, 'ultimo_diagnostico', {}) or {})
                diagnostico.update(acao=nome, arquivo=(argumentos or {}).get('arquivo'), sessao=(argumentos or {}).get('sessao'), executada=False)
                return ResultadoFerramenta(texto="A ação proposta não foi autorizada pelo sentido do pedido humano. Diagnóstico: " + json.dumps(diagnostico,ensure_ascii=False), ok=False, mudou=False, erro="pedido_nao_autorizado")
            contexto["pedido_explicito"] = True

    if tem_politica_de_turno and not pedido_explicito and not f.somente_leitura and not preparacao_reversivel:
        pode_iniciar = (
            autonomia_ligada
            and dono_confirmado
            and not f.destrutiva
            and iniciativa_espontanea_permitida(nome)
        )
        if not pode_iniciar:
            _log(f"iniciativa bloqueada sem pedido explícito: {nome}")
            return ResultadoFerramenta(
                texto=("Essa ação não pode ser iniciada só por inferência da "
                       "conversa. Responda sem executá-la; se for séria, espere "
                       "um pedido explícito do Vitor."),
                ok=False, mudou=False, erro="iniciativa_nao_autorizada")

    if f.destrutiva and not PERMITIR_DESTRUTIVAS:
        _log(f"bloqueada por ser destrutiva: {nome}")
        return ResultadoFerramenta(
            texto=(f"Essa operação apaga coisas e está desativada nesta sessão. "
                   f"Avise {interlocutor} que isso precisa ser feito à mão."),
            ok=False, mudou=False, erro="destrutiva_bloqueada")

    if os.getenv("EMILY_RUNTIME_CLOUD") == "1":
        from cloud_runtime_client import ferramenta_local_na_nuvem, executar_no_pc
        if not ferramenta_local_na_nuvem(f):
            return executar_no_pc(nome, argumentos, contexto)

    argumentos = argumentos if isinstance(argumentos, dict) else {}
    if (nome == "executar_terminal" and pedido_explicito and dono_confirmado
            and autonomia_ligada):
        # Argumento interno: não aparece no schema que o modelo recebe.
        argumentos = dict(argumentos)
        argumentos["autorizacao_direta"] = True

    # "Faltou" é AUSÊNCIA, não valor falsy.
    #
    # Antes o teste era `not argumentos.get(p)`, e isso tornava impossível passar
    # False ou 0 num argumento obrigatório: `not False` é True, então a camada
    # dizia que o argumento faltava e a ferramenta nunca rodava. Apareceu no
    # definir_modo, em que `ligar=False` é o caso de DESLIGAR o modo — ou seja, a
    # metade "desativar" de todos os modos ficaria morta, com a Emily pedindo ao
    # Vitor um valor que o modelo já tinha mandado certo.
    #
    # String vazia e só-espaço continuam contando como faltando: ali o modelo
    # realmente não preencheu nada.
    def _faltou(valor) -> bool:
        if valor is None:
            return True
        if isinstance(valor, str):
            return not valor.strip()
        return False

    faltando = [p for p in f.obrigatorios
                if p not in argumentos or _faltou(argumentos[p])]
    if faltando:
        return ResultadoFerramenta(
            texto=(f"Faltou o argumento obrigatório {', '.join(faltando)} para "
                   f"'{nome}'. NÃO chute o valor: pergunte a {interlocutor} o que "
                   f"falta, com uma pergunta curta."),
            ok=False, mudou=False, erro="argumento_faltando")

    if os.getenv("EMILY_RUNTIME_CLOUD") != "1":
        from cloud_runtime_client import hospedado_na_oracle, executar_na_oracle
        if hospedado_na_oracle() and f.grupo == "discord":
            return executar_na_oracle(nome, argumentos, contexto)

    argumentos_log = dict(argumentos)
    if nome == "criar_arquivo_txt" and "conteudo" in argumentos_log:
        argumentos_log["conteudo"] = f"<{len(str(argumentos_log['conteudo']))} caracteres>"
    _log(f"executando {nome}({json.dumps(argumentos_log, ensure_ascii=False)})")
    on_reconexao = contexto.get("on_reconexao")
    reconectou = False
    for tentativa in range(3):
        try:
            exec_args = dict(argumentos)
            if nome == "executar_terminal" and contexto.get("cancelar_terminal_evento") is not None:
                exec_args["cancelar_evento"] = contexto["cancelar_terminal_evento"]
            if nome == "programacao_comentar":
                exec_args["progress"] = contexto.get("on_progresso")
            bruto = f.executar(**exec_args)
            if reconectou and callable(on_reconexao):
                try:
                    on_reconexao(0, 3)
                except Exception:
                    pass
            break
        except TypeError as e:
            # Modelo mandou argumento que a função não aceita.
            _log(f"argumentos incompativeis em {nome}: {e}")
            return ResultadoFerramenta(
                texto=f"Argumentos inválidos para '{nome}': {e}",
                ok=False, mudou=False, erro="TypeError")
        except Exception as e:
            tipo = type(e).__name__.lower()
            transiente = isinstance(e, (TimeoutError, ConnectionError)) or any(
                parte in tipo for parte in ("timeout", "connection", "transport",
                                            "readerror", "remoteprotocol"))
            if f.somente_leitura and transiente and tentativa < 2:
                reconectou = True
                _log(f"consulta {nome} falhou por rede; reconectando "
                     f"({tentativa + 1}/3): {type(e).__name__}")
                if callable(on_reconexao):
                    try:
                        on_reconexao(tentativa + 1, 3)
                    except Exception:
                        pass
                time.sleep(min(2.0, 0.5 * (2 ** tentativa)))
                continue
            _log(f"erro em {nome}: {type(e).__name__}: {e}")
            _log(traceback.format_exc(limit=3))
            if f.somente_leitura and reconectou and callable(on_reconexao):
                try:
                    on_reconexao(-1, 3)
                except Exception:
                    pass
            if not f.somente_leitura:
                # O erro pode ter ocorrido depois do efeito externo (timeout ao
                # receber o ACK, por exemplo). Não repetir automaticamente.
                return ResultadoFerramenta(
                    texto=(f"Resultado incerto de '{nome}': a chamada falhou com "
                           f"{type(e).__name__}. A ação pode ter acontecido. "
                           "Confira o estado com uma ferramenta de leitura antes "
                           "de repetir; se não for possível conferir, pergunte ao usuário."),
                    ok=False, mudou=False, erro="resultado_incerto")
            return ResultadoFerramenta(
                texto=f"A ferramenta '{nome}' falhou: {type(e).__name__}: {e}",
                ok=False, mudou=False, erro=type(e).__name__)

    # A ferramenta já disse o que aconteceu: respeita.
    if isinstance(bruto, ResultadoFerramenta):
        if bruto.ok and bruto.mudou and nome != "desfazer_ultima_acao":
            registravel = iniciativa_espontanea_permitida(nome)
            if registravel:
                _registrar_iniciativa_desfazivel(nome, argumentos)
            elif pedido_explicito:
                _invalidar_iniciativas_anteriores()
        _log(f"{nome} -> ok={bruto.ok} mudou={bruto.mudou} {bruto.texto[:90]}")
        return bruto

    texto = str(bruto) if bruto is not None else "Feito."
    # Devolveu str: o 'mudou' sai da declaração da ferramenta, e a heurística de
    # texto só é consultada pra ferramenta destrutiva — que é onde um "rodei e
    # não fiz" custa caro.
    mudou = not f.somente_leitura
    if mudou and f.destrutiva and parece_recusa_em_texto(texto):
        mudou = False
    if mudou and nome != "desfazer_ultima_acao":
        registravel = iniciativa_espontanea_permitida(nome)
        if registravel:
            _registrar_iniciativa_desfazivel(nome, argumentos)
        elif pedido_explicito:
            _invalidar_iniciativas_anteriores()
    _log(f"{nome} -> {texto[:120]}")
    return ResultadoFerramenta(texto=texto, ok=True, mudou=mudou)


# ═════════════════════════════════════════════════════════════════
# PONTE COM A AUTOMAÇÃO
# ═════════════════════════════════════════════════════════════════

def _automacao(acao: str, **campos) -> str:
    """
    Chama o executor de automação com o dicionário já montado.

    Isso pula de propósito duas coisas: o filtro de palavra-chave e o
    _interpretar_com_llm, que é o prompt estático de 8.178 tokens. O modelo
    já decidiu a ação e extraiu os argumentos no tool call, então reinterpretar
    a frase seria pagar aquele prompt de novo sem ganho nenhum.
    """
    import automacao

    dados = {"acao": acao, "resposta": "Feito."}
    dados.update({k: v for k, v in campos.items() if v not in (None, "")})

    resultado = automacao._executar_acao_por_dict(dados, callback_falar=None)
    if resultado is None:
        return f"A ação '{acao}' não retornou resultado. Pode não ter funcionado."
    return resultado or "Feito."


def _criar_arquivo_local(acao: str, **campos):
    texto = _automacao(acao, **campos)
    if texto.startswith(("Não achei", "Não consegui", "Já existe", "Me diz", "Use só")):
        return recusa(texto)
    return texto


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — APLICATIVOS, JOGOS E JANELAS
# ═════════════════════════════════════════════════════════════════

registrar(Ferramenta(
    nome="abrir_app",
    descricao=(
        "Abre um aplicativo instalado no PC (funciona no Windows E no Linux). "
        "Use para programas comuns como "
        "Discord, Spotify, VS Code, navegador, calculadora. NÃO use se o Vitor "
        "quiser abrir o programa E fazer algo dentro dele: nesse caso use "
        "executar_na_tela. NÃO use se o pedido for sobre SITE/internet "
        "(entrar em site, baixar da web, mod, vídeo online): nesse caso use "
        "abrir_site e as ferramentas *_navegador."
    ),
    propriedades={"nome": {"type": "string", "description": "Nome do aplicativo"}},
    obrigatorios=["nome"],
    aviso="abrir_app",
    executar=lambda nome: _automacao("abrir_app", alvo=nome),
))

registrar(Ferramenta(
    nome="abrir_jogo",
    descricao=(
        "Abre um jogo. Procura na Steam, Epic, GOG e Program Files. Use quando "
        "o Vitor pedir para abrir ou jogar algo que é um jogo."
    ),
    propriedades={"nome": {"type": "string", "description": "Nome do jogo"}},
    obrigatorios=["nome"],
    aviso="abrir_app",
    executar=lambda nome: _automacao("abrir_jogo", alvo=nome),
))

registrar(Ferramenta(
    nome="fechar_app",
    descricao=(
        "Fecha um programa INTEIRO, pelo nome. Use quando o Vitor falar fecha o "
        "Discord, sai do Spotify, mata o Chrome. Pra fechar só a aba do navegador "
        "e deixar ele aberto, é fechar_aba."
    ),
    propriedades={"nome": {
        "type": "string",
        "description": ("Nome do programa como o Vitor falou. Ela resolve nome "
                        "parecido, não precisa ser exato."),
    }},
    obrigatorios=["nome"],
    executar=lambda nome: _automacao("fechar_app", alvo=nome),
))

registrar(Ferramenta(
    nome="minimizar_app",
    descricao=(
        "Manda a janela de um programa pra barra de tarefas, sem fechar nada. Use "
        "quando o Vitor falar minimiza, esconde ou tira da frente."
    ),
    propriedades={"nome": {
        "type": "string",
        "description": "Nome do programa como o Vitor falou",
    }},
    obrigatorios=["nome"],
    executar=lambda nome: _automacao("minimizar_app", alvo=nome),
))

registrar(Ferramenta(
    nome="maximizar_app",
    descricao=(
        "Põe a janela de um programa em tela cheia e traz pra frente. Use quando "
        "o Vitor falar maximiza, aumenta, traz pra frente ou 'deixa em tela "
        "cheia'. Se o programa não estiver aberto, é abrir_app."
    ),
    propriedades={"nome": {
        "type": "string",
        "description": "Nome do programa como o Vitor falou",
    }},
    obrigatorios=["nome"],
    executar=lambda nome: _automacao("maximizar_app", alvo=nome),
))

registrar(Ferramenta(
    nome="fechar_aba",
    descricao=(
        "Fecha SÓ a aba que está na frente no navegador, deixando o navegador "
        "aberto. Use quando o Vitor falar fecha essa aba, fecha isso aí, fecha "
        "essa página. Pra fechar o navegador todo, é fechar_app."
    ),
    propriedades={},
    executar=lambda: _automacao("fechar_aba"),
))

# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — SITES, PASTAS E ARQUIVOS
# ═════════════════════════════════════════════════════════════════

_SITES_CONHECIDOS = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "nexus mods": "https://www.nexusmods.com",
    "nexusmods": "https://www.nexusmods.com",
    "github": "https://github.com",
    "twitch": "https://www.twitch.tv",
    "netflix": "https://www.netflix.com",
    "steam": "https://store.steampowered.com",
    "reddit": "https://www.reddit.com",
    "wikipedia": "https://pt.wikipedia.org",
    "gmail": "https://mail.google.com",
    "whatsapp": "https://web.whatsapp.com",
}


def _abrir_site(site: str):
    """
    No modo bastidor, abre pela extensão na janela escondida (sem tomar a aba
    do Vitor). No modo normal — ou se a extensão não estiver conectada — cai
    no caminho de sempre (automacao, que abre no navegador padrão dele).
    """
    site = (site or "").strip()
    if not site:
        return recusa("Me diz qual site você quer abrir!")
    try:
        import navegador
        if navegador.esta_conectado() and navegador.modo_bastidor_ativo():
            alvo = site.lower().removeprefix("https://").removeprefix("http://").rstrip("/")
            url = _SITES_CONHECIDOS.get(alvo)
            if not url:
                url = next((v for k, v in _SITES_CONHECIDOS.items() if k in alvo), None)
            if not url and "." in site and " " not in site:
                url = site if site.startswith("http") else "https://" + site
            if url:
                r = navegador.enviar_comando_com_id(
                    "abrir_url", timeout=10.0, url=url, bastidor=True)
                if r and r.get("tipo") != "erro":
                    return (f"Abri {url} na janela de bastidor (escondida) do "
                            "navegador — sem tomar a aba dele.")
    except Exception as e:  # noqa: BLE001
        print(f"[FERRAMENTAS] abrir_site via extensão falhou ({e}); "
              "caindo pro caminho normal.")
    return _automacao("abrir_site", alvo=site)


registrar(Ferramenta(
    nome="abrir_site",
    descricao=(
        "Abre um site no navegador. É o PRIMEIRO passo de qualquer tarefa de "
        "web (ex.: 'entra no Nexus Mods e baixa um mod de Elden Ring'): "
        "abra a página aqui e depois encadeie as ferramentas do navegador "
        "(ler_pagina_navegador, extrair_links_da_pagina, "
        "executar_javascript_na_pagina, baixar_arquivo_navegador) até "
        "terminar o que ele pediu. Passe a URL completa quando souber "
        "(ex.: https://www.nexusmods.com/games/eldenring/mods); se o modo "
        "bastidor estiver ligado, a página abre na janela escondida, sem "
        "tomar a aba dele. NÃO use para pesquisar informação: para isso use "
        "pesquisar_internet. Nunca use abrir_pasta/abrir_arquivo/terminal "
        "pra coisa de site."
    ),
    propriedades={"site": {"type": "string", "description": "URL do site (ex.: https://www.nexusmods.com) ou nome conhecido (ex.: 'nexus mods')"}},
    obrigatorios=["site"],
    aviso="abrir_app",
    executar=lambda site: _abrir_site(site),
))

registrar(Ferramenta(
    nome="abrir_pasta",
    descricao=(
        "Abre uma pasta no gerenciador de arquivos (funciona no Windows E no "
        "Linux). Aceita pastas conhecidas "
        "(downloads, documentos, imagens, area de trabalho) ou nome de pasta. "
        "Ela mesma localiza a pasta nos drives, então não precisa saber o "
        "caminho antes. Se o Vitor só quer SABER onde algo está, sem abrir, "
        "use procurar_no_pc. NÃO use se o pedido for sobre SITE/internet "
        "(entrar em site, baixar da web, mod, vídeo online): nesse caso use "
        "abrir_site e as ferramentas *_navegador."
    ),
    propriedades={
        "nome": {"type": "string", "description": "Nome da pasta"},
        "dentro_de": {"type": "string", "description": "Pasta-pai onde procurar, se o Vitor disser"},
        "drive": {"type": "string", "description": "Letra do drive, se o Vitor disser"},
    },
    obrigatorios=["nome"],
    executar=lambda nome, dentro_de=None, drive=None: _automacao(
        "abrir_pasta", alvo=nome, pasta=dentro_de, drive=drive),
))

registrar(Ferramenta(
    nome="abrir_arquivo",
    descricao=(
        "Abre UM arquivo no programa padrão dele (funciona no Windows E no "
        "Linux): documento, PDF, imagem, vídeo, "
        "planilha. Use quando o Vitor nomear um arquivo LOCAL do PC dele pra "
        "abrir. Se ele pedir a "
        "PASTA e não o arquivo, é abrir_pasta; se for um programa, abrir_app; se "
        "ele quiser saber ONDE está sem abrir, é procurar_no_pc. NUNCA use pra "
        "coisa de SITE/internet (baixar da web, mod, vídeo online): use "
        "abrir_site e as ferramentas *_navegador."
    ),
    propriedades={
        "nome": {"type": "string",
                 "description": "Nome do arquivo, com extensão se ele disser"},
        "dentro_de": {
            "type": "string",
            "description": ("Pasta onde procurar. Aceita pasta conhecida "
                            "(downloads, documentos, imagens, area de trabalho) "
                            "ou caminho. Vazio = ela procura."),
        },
    },
    obrigatorios=["nome"],
    executar=lambda nome, dentro_de=None: _automacao(
        "abrir_arquivo", alvo=nome, pasta=dentro_de),
))

from busca_pc import (  # noqa: E402,F401 - movido para busca_pc.py
    _MAX_CANDIDATOS,
    _PROFUNDIDADE_VARREDURA,
    _NOTA_EXATA,
    _SEGUNDOS_MAX_VARREDURA,
    _PASTAS_IGNORADAS,
    _tokens_significativos,
    _pontuar_candidata,
    _todos_os_drives,
    _drives_para_procurar,
    _candidatas_nos_launchers,
    _candidatas_no_drive,
    _procurar_no_pc,
)


registrar(Ferramenta(
    nome="procurar_no_pc",
    descricao=(
        "Descobre ONDE está a pasta de um jogo, programa ou pasta qualquer, e "
        "devolve o caminho completo. Procura na Steam, Epic, GOG, registro do "
        "Windows, Program Files e, se preciso, varre os drives. "
        "Use SEMPRE que o Vitor perguntar onde algo está, disser que não acha "
        "uma pasta, ou pedir pra você achar/localizar/procurar algo no PC. "
        "Esta ferramenta só encontra e informa: não abre nada. Se ele quiser "
        "abrir, chame abrir_pasta depois. "
        "NUNCA use executar_na_tela nem comando_do_pc pra procurar arquivo ou "
        "pasta: eles ficam clicando na tela às cegas e não funcionam pra isso."
    ),
    propriedades={
        "nome": {
            "type": "string",
            "description": "Nome da pasta, jogo ou programa a procurar",
        },
        "drive": {
            "type": "string",
            "description": (
                "Só preencha se o Vitor disser explicitamente ONDE está "
                "(ex: 'h', 'nvme'). É apenas uma dica de onde começar; a busca "
                "continua nos outros drives se não achar. Não chute o drive a "
                "partir de onde ele disse que NÃO está — deixe vazio."
            ),
        },
    },
    obrigatorios=["nome"],
    aviso="abrir_app",
    executar=_procurar_no_pc,
))

registrar(Ferramenta(
    nome="criar_pasta",
    descricao=(
        "Cria uma pasta nova e vazia. Use quando o Vitor pedir pra criar, fazer "
        "ou abrir espaço pra uma pasta. O resultado traz o caminho completo "
        "da pasta criada; use esse caminho nas próximas ferramentas. "
        "NÃO use pra ABRIR pasta que já existe "
        "(abrir_pasta) nem pra descobrir onde uma pasta está (procurar_no_pc)."
    ),
    propriedades={
        "nome": {"type": "string", "description": "Nome da pasta nova, só o nome"},
        "dentro_de": {
            "type": "string",
            "description": ("Onde criar. Aceita pasta conhecida (downloads, "
                            "documentos, imagens, area de trabalho) ou caminho "
                            "completo. Vazio = área de trabalho, ou pasta pessoal se indisponível."),
        },
    },
    obrigatorios=["nome"],
    executar=lambda nome, dentro_de=None: _criar_arquivo_local(
        "criar_pasta", nome=nome, pasta=dentro_de),
))

registrar(Ferramenta(
    nome="criar_arquivo_txt",
    descricao=(
        "Cria um arquivo de texto (.txt) novo no PC do Vitor. Use "
        "quando ele pedir pra criar um txt, um arquivo de texto, um bloco de "
        "notas. Pode criar o arquivo já com o conteúdo pedido. Informe onde "
        "criar (área de trabalho, downloads, documentos, uma pasta existente) "
        "e o nome. Se também pediu uma pasta nova, use criar_pasta primeiro "
        "e passe o caminho completo devolvido em dentro_de. "
        "Não use o terminal para esta tarefa."
    ),
    propriedades={
        "nome": {"type": "string", "description": "Nome do arquivo, com ou sem .txt"},
        "dentro_de": {
            "type": "string",
            "description": ("Onde criar. Aceita pasta conhecida (downloads, "
                            "documentos, imagens, area de trabalho) ou caminho "
                            "completo. Vazio = área de trabalho, ou pasta pessoal se indisponível."),
        },
        "conteudo": {
            "type": "string",
            "description": "Texto completo a colocar no arquivo. Vazio cria um TXT vazio.",
        },
    },
    obrigatorios=["nome"],
    executar=lambda nome, dentro_de=None, conteudo="": _criar_arquivo_local(
        "criar_arquivo_txt", nome=nome, pasta=dentro_de, conteudo=conteudo),
))

registrar(Ferramenta(
    nome="mover_arquivo",
    descricao=(
        "Move um arquivo de uma pasta pra outra: ele SAI do lugar antigo. Use "
        "quando o Vitor falar mover, jogar pra, tirar daqui e pôr lá, ou "
        "organizar. Se ele quiser manter o original onde está, é copiar_arquivo."
    ),
    propriedades={
        "arquivo": {"type": "string",
                    "description": "Nome do arquivo, com extensão se souber"},
        "origem": {
            "type": "string",
            "description": ("Pasta de onde tirar. Deixe vazio se não souber: ela "
                            "procura o arquivo."),
        },
        "destino": {
            "type": "string",
            "description": ("Pasta pra onde levar. Aceita pasta conhecida "
                            "(downloads, documentos, imagens, area de trabalho) "
                            "ou caminho completo."),
        },
    },
    obrigatorios=["arquivo", "destino"],
    destrutiva=True,
    executar=lambda arquivo, destino, origem=None: _automacao(
        "mover_arquivo", alvo=arquivo, destino=destino, origem=origem),
))

registrar(Ferramenta(
    nome="copiar_arquivo",
    descricao=(
        "Copia um arquivo pra outra pasta, deixando o original onde está. Use "
        "quando o Vitor falar copiar, duplicar ou 'faz uma cópia'. Se ele falar "
        "mover, tirar de um lugar e pôr no outro, é mover_arquivo — o original "
        "deixa de existir no lugar antigo, e a diferença importa pra ele."
    ),
    propriedades={
        "arquivo": {"type": "string",
                    "description": "Nome do arquivo, com extensão se souber"},
        "origem": {
            "type": "string",
            "description": ("Pasta de onde copiar. Deixe vazio se não souber: "
                            "ela procura o arquivo."),
        },
        "destino": {
            "type": "string",
            "description": ("Pasta pra onde copiar. Aceita pasta conhecida "
                            "(downloads, documentos, imagens, area de trabalho) "
                            "ou caminho completo."),
        },
    },
    obrigatorios=["arquivo", "destino"],
    executar=lambda arquivo, destino, origem=None: _automacao(
        "copiar_arquivo", alvo=arquivo, destino=destino, origem=origem),
))

registrar(Ferramenta(
    nome="renomear_arquivo",
    descricao=(
        "Troca o nome de um arquivo, deixando ele na mesma pasta. Use quando o "
        "Vitor pedir pra renomear ou trocar o nome. NÃO use pra mover de pasta "
        "(mover_arquivo)."
    ),
    propriedades={
        "arquivo": {"type": "string",
                    "description": "Nome atual do arquivo, com extensão se souber"},
        "novo_nome": {"type": "string",
                      "description": "Nome novo. Mantenha a extensão original"},
        "dentro_de": {
            "type": "string",
            "description": ("Pasta onde o arquivo está. Aceita pasta conhecida "
                            "(downloads, documentos, area de trabalho) ou caminho. "
                            "Deixe vazio se não souber: ela procura."),
        },
    },
    obrigatorios=["arquivo", "novo_nome"],
    destrutiva=True,
    executar=lambda arquivo, novo_nome, dentro_de=None: _automacao(
        "renomear_arquivo", alvo=arquivo, novo_nome=novo_nome, pasta=dentro_de),
))

registrar(Ferramenta(
    nome="deletar_arquivo",
    descricao=(
        "Apaga um arquivo. Use somente quando o Vitor pedir claramente para "
        "deletar. Existe desfazer, mas não use por conta própria."
    ),
    propriedades={
        "arquivo": {"type": "string",
                    "description": ("Nome do arquivo a apagar, com extensão. "
                                    "Nunca chute: se ele não disse qual, "
                                    "pergunte.")},
        "dentro_de": {
            "type": "string",
            "description": ("Pasta onde o arquivo está. Aceita pasta conhecida "
                            "(downloads, documentos, area de trabalho) ou "
                            "caminho. Vazio = ela procura."),
        },
    },
    obrigatorios=["arquivo"],
    destrutiva=True,
    executar=lambda arquivo, dentro_de=None: _automacao(
        "deletar_arquivo", alvo=arquivo, pasta=dentro_de),
))

registrar(Ferramenta(
    nome="extrair_arquivo",
    descricao=(
        "Descompacta um zip, rar ou 7z, criando uma pasta com o conteúdo. Use "
        "quando o Vitor falar extrair, descompactar, abrir o zip ou 'tira isso "
        "de dentro do rar'."
    ),
    propriedades={
        "arquivo": {"type": "string",
                    "description": "Nome do compactado, ex: 'modpack.zip'"},
        "dentro_de": {
            "type": "string",
            "description": ("Pasta onde o compactado está. Vazio = ela procura, "
                            "começando pelos downloads."),
        },
    },
    obrigatorios=["arquivo"],
    executar=lambda arquivo, dentro_de=None: _automacao(
        "extrair_arquivo", alvo=arquivo, pasta=dentro_de),
))

def _desfazer() -> str:
    iniciativa = _desfazer_iniciativa_recente()
    if iniciativa:
        return iniciativa
    import automacao
    r = automacao.desfazer_ultima_acao()
    return r or "Não tinha nada pra desfazer."


registrar(Ferramenta(
    nome="desfazer_ultima_acao",
    descricao=(
        "Desfaz a última ação reversível registrada: uma ação simples sua "
        "(como abrir app/jogo ou iniciar música) ou uma operação de arquivo/pasta "
        "(mover, copiar, renomear, deletar, extrair). Use quando o Vitor disser "
        "que foi errado, pedir pra desfazer, ou reclamar do último resultado."
    ),
    propriedades={},
    executar=_desfazer,
))


def _comando_legado(pedido: str) -> str:
    """
    Escotilha de escape para tudo que a Emily já sabia fazer e que ainda não
    tem ferramenta própria.

    Isso existe por um motivo concreto: o main.py agora desvia pro tool calling
    ANTES de chegar no automacao.executar_comando. Sem esta ferramenta, tudo
    que só existia no caminho de palavra-chave — speedruns, modos
    configuráveis, operações em arquivos selecionados no explorador, instalar
    jogo da Steam, entrar em call do Discord — ficaria inacessível.

    Aqui vale pagar o _interpretar_com_llm (o prompt grande), porque é o preço
    de reusar 38 ações já testadas em vez de reescrever cada uma como
    ferramenta separada.
    """
    import automacao
    import voz

    # Freio: a escotilha NÃO pode virar porta de entrada do agente visual.
    #
    # O prompt de interpretação do automacao manda usar agente_ui quando ouve
    # "acha", "procura", "navega", "resolve isso". Então comando_do_pc("Procurar
    # a pasta do Elden Ring") escalava pro agente visual, que abria a busca do
    # Windows e ficava clicando às cegas por até 50 passos, enquanto esta
    # ferramenta devolvia "Vou lá resolver" — ou seja, o modelo recebia um
    # resultado que não dizia nada e a tarefa nunca terminava.
    #
    # Agora interpreta primeiro, e se o destino for o agente visual, recusa e
    # diz qual ferramenta usar. O agente visual continua acessível, mas só
    # quando o modelo pedir explicitamente por executar_na_tela.
    try:
        interpretado = automacao._interpretar_com_llm(pedido)
    except Exception as e:
        _log(f"interpretação do comando legado falhou: {e}")
        interpretado = None

    if interpretado and interpretado.get("acao") == "agente_ui":
        _log(f"recusando escalada pro agente visual: {pedido!r}")
        return (
            "Esse pedido caiu no controle visual da tela, que é lento e pouco "
            "confiável. Escolha uma ferramenta específica: para achar onde algo "
            "está no PC use procurar_no_pc; para abrir pasta, arquivo, app, jogo "
            "ou site use a ferramenta de abrir correspondente; para mexer em "
            "arquivo use mover/copiar/renomear/extrair. Só use executar_na_tela "
            "se realmente for preciso clicar e digitar numa interface."
        )

    if interpretado and interpretado.get("acao") not in (None, "nenhuma"):
        resultado = automacao._executar_acao_por_dict(
            interpretado, callback_falar=voz.falar)
        if resultado is None:
            return ("A ação não retornou resultado. Pode não ter funcionado; "
                    "não afirme ao Vitor que deu certo.")
        return resultado or "Feito."

    # Interpretação não reconheceu nada: tenta o caminho completo, que ainda
    # cobre o filtro de palavra-chave.
    resultado = automacao.executar_comando(pedido, callback_falar=voz.falar)
    if resultado is None:
        return ("Não reconheci esse comando no sistema de automação. "
                "Diga ao Vitor que não entendeu o que ele quis.")
    return resultado or "Feito."


registrar(Ferramenta(
    nome="comando_do_pc",
    descricao=(
        "Executa um comando no PC que não tem ferramenta específica na sua "
        "lista. Passe a frase do Vitor quase como ele falou. Use para: "
        "speedruns e macros gravadas (listar, iniciar, pausar, parar), modos "
        "configuráveis (criar, listar, ativar, deletar um modo como 'modo "
        "gameplay'), operações em arquivos SELECIONADOS no explorador (mover, "
        "copiar, deletar, renomear, extrair os selecionados), operações em "
        "pastas inteiras, criar arquivo de texto, instalar ou desinstalar jogo "
        "da Steam, entrar ou sair de call do Discord, controlar o navegador, "
        "extrair um download recém-baixado. "
        "Só use se nenhuma ferramenta específica servir."
    ),
    propriedades={
        "pedido": {
            "type": "string",
            "description": "A frase do Vitor descrevendo o que fazer, em português",
        }
    },
    obrigatorios=["pedido"],
    aviso="abrir_app",
    executar=_comando_legado,
))


registrar(Ferramenta(
    nome="organizar_downloads",
    descricao=(
        "Arruma a pasta de downloads movendo cada arquivo pra uma subpasta por "
        "tipo (imagens, documentos, instaladores, compactados). Use quando o "
        "Vitor pedir pra organizar ou arrumar os downloads. Mexe em VÁRIOS "
        "arquivos de uma vez: não chame por conta própria."
    ),
    propriedades={},
    destrutiva=True,
    executar=lambda: _automacao("organizar_downloads"),
))


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — ESPAÇO EM DISCO
#
# Varredura de disco e limpeza. A análise é só leitura e devolve o mapa do que
# está pesando, inclusive o espaço que o Windows esconde. A limpeza é
# destrutiva e, por padrão, só faz PRÉVIA (ver disco.py).
# ═════════════════════════════════════════════════════════════════

def _analisar_disco(drive: str = "C") -> str:
    import disco
    return disco.analisar(drive)


def _limpar_disco(confirmar: bool = False) -> str:
    import disco
    r = disco.limpar(confirmar=bool(confirmar))
    # Prévia é consulta (não mudou nada); limpeza de verdade mudou o mundo.
    return consulta(r) if not confirmar else r


registrar(Ferramenta(
    nome="analisar_disco",
    grupo="geral",
    somente_leitura=True,
    descricao=(
        "Varre um drive inteiro e diz PRECISAMENTE o que está enchendo o "
        "espaço: o panorama por pasta de cima, as pastas que concentram espaço "
        "(o ponto exato, fundo na árvore), os maiores arquivos, e os arquivos "
        "de sistema (hibernação, memória virtual). Não pula arquivo oculto e "
        "fecha a conta contra o espaço usado real, apontando o que o Windows "
        "reserva e esconde (pontos de restauração, cópias de sombra). "
        "Use quando o Vitor perguntar o que está ocupando o disco, disser que "
        "está cheio/sem espaço, ou pedir pra analisar o armazenamento. É só "
        "leitura: não apaga nada. Pode demorar em disco grande."
    ),
    propriedades={
        "drive": {
            "type": "string",
            "description": ("Letra do drive a analisar (C, D, ...). Vazio = C, "
                            "que é o disco do sistema."),
        },
    },
    obrigatorios=[],
    aviso="analisando_disco",
    executar=_analisar_disco,
))

registrar(Ferramenta(
    nome="limpar_disco",
    grupo="geral",
    destrutiva=True,
    descricao=(
        "Libera espaço apagando o que é SEGURO: os temporários (do usuário e do "
        "Windows) e a lixeira. Com confirmar=false (padrão) só faz a PRÉVIA — "
        "diz quanto dá pra liberar sem apagar nada. Com confirmar=true, apaga "
        "de verdade. Use depois do analisar_disco, e sempre faça a prévia "
        "primeiro pra o Vitor decidir. NÃO mexe em pontos de restauração, "
        "WinSxS nem arquivo de sistema — isso exige admin e ela não faz sozinha."
    ),
    propriedades={
        "confirmar": {
            "type": "boolean",
            "description": ("false (ou vazio) = só a prévia do quanto dá pra "
                            "liberar. true = apaga de verdade. Só mande true "
                            "depois que o Vitor confirmar que quer limpar."),
        },
    },
    obrigatorios=[],
    aviso_dinamico=lambda a: "limpando_disco" if a.get("confirmar") else "",
    executar=_limpar_disco,
))


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — TERMINAL
#
# A ferramenta universal: quando nenhum catálogo específico cobre o pedido,
# a Emily resolve por PowerShell. A segurança NÃO é julgamento do modelo — é
# classificação local por regex em terminal.py, com três destinos (livre /
# confirmar / bloqueado). Ver o cabeçalho de terminal.py.
# ═════════════════════════════════════════════════════════════════

def _executar_terminal(comando: str, confirmado: bool = False, entrada: str = "",
                       autorizacao_direta: bool = False, cancelar_evento=None):
    import terminal
    texto, ok = terminal.executar(
        comando, confirmado=confirmado, entrada=entrada,
        autorizacao_direta=autorizacao_direta,
        **({"cancelar_evento": cancelar_evento} if cancelar_evento is not None else {}))
    # Recusa ou falha NÃO mudou o mundo e precisa voltar como não-feito —
    # se fosse consulta(), a máquina de promessa contaria bloqueio como
    # tarefa cumprida.
    return recusa(texto) if not ok else texto


registrar(Ferramenta(
    nome="executar_terminal",
    # Literal e não GRUPO_PADRAO: a constante é definida no fim do arquivo,
    # depois deste ponto do módulo.
    grupo="geral",
    descricao=(
        "A FERRAMENTA MAIS PODEROSA: executa qualquer comando no terminal do "
        "PC do Vitor, invisível, e devolve a saída. FUNCIONA EM QUALQUER "
        "SISTEMA OPERACIONAL — no Windows usa PowerShell, no Linux usa Bash, "
        "e a Emily detecta sozinha: consulte o bloco <ambiente> do seu prompt "
        "pra saber em qual sistema está AGORA e use a sintaxe certa. No Linux "
        "nada de PowerShell nem C:/D: — use ls, xdg-open, dnf, systemctl etc. "
        "Não tem limite de tempo: roda até terminar. Use quando o pedido não "
        "tiver ferramenta específica e puder ser concluído INTEIRO por comando: "
        "instalar pacote sem assistente gráfico, configurar serviço, consultar "
        "informação do "
        "sistema (processos, serviços, rede, bateria, versões), "
        "converter/renomear arquivos em lote, rodar scripts, abrir algo, checar "
        "algo técnico, tarefas demoradas. Para configurar opções dentro de um "
        "programa, atravessar instalador gráfico, clicar, preencher e validar na "
        "interface, prefira executar_na_tela. Se o programa DENTRO do "
        "comando fizer pergunta "
        "(continuar? [S/N]), prefira flags oficiais que evitem a pergunta "
        "(ex.: dnf -y no Linux, winget --accept-source-agreements no Windows); "
        "sem flag disponível, forneça a resposta em 'entrada' na execução "
        "autorizada, nunca senha. COMANDOS QUE INSTALAM, "
        "DESINSTALAM, MATAM PROCESSO, MEXEM EM SERVIÇO OU APAGAM ARQUIVO são "
        "confirmáveis. Normalmente a primeira chamada é barrada: explique ao "
        "Vitor e só repita com o MESMO comando e confirmado=true depois do sim. "
        "EXCEÇÃO: com <autonomia_experimental estado='ligada'>, se o Vitor pediu "
        "esse comando explicitamente na mensagem atual, a própria ordem já autoriza "
        "e o executor libera sem segunda pergunta — não invente confirmado=true. "
        "No Linux, desligar, reiniciar ou suspender o PC exige pedido explícito "
        "ou confirmação específica da ação. Comandos administrativos "
        "simples abrem a janela padrão de autenticação do sistema; nunca "
        "coloque senha em comando ou no argumento entrada. Comandos "
        "irreversíveis (formatar, registro, boot) são sempre bloqueados — "
        "não tente variações. Se um comando travar e o "
        "Vitor quiser parar, use cancelar_terminal. REGRA DE OURO: NUNCA "
        "invente comando, nome de pacote ou flag. Se você não tem CERTEZA "
        "absoluta do comando certo (principalmente pra instalar/desinstalar "
        "algo), use descobrir_comando ANTES e só execute o que a pesquisa "
        "confirmar."
    ),
    propriedades={
        "comando": {
            "type": "string",
            "description": ("O comando completo, pronto pra rodar, na sintaxe "
                            "do sistema (PowerShell no Windows, Bash no Linux). "
                            "Não use placeholder nem '...' — escreva tudo."),
        },
        "confirmado": {
            "type": "boolean",
            "description": ("Só mande true depois que o Vitor confirmar "
                            "explicitamente a segunda chamada do MESMO comando "
                            "que foi barrado. Nunca na primeira tentativa."),
        },
        "entrada": {
            "type": "string",
            "description": ("Resposta pra um programa que pergunta via stdin "
                            "(ex.: 'S', 'N'). Nunca coloque senha aqui. Deixe vazio na maioria "
                            "das vezes."),
        },
    },
    obrigatorios=["comando"],
    aviso="executando_terminal",
    executar=_executar_terminal,
))


registrar(Ferramenta(
    nome="cancelar_terminal",
    grupo="geral",
    somente_leitura=False,
    descricao=(
        "Interrompe à força o comando que está travado no terminal agora. Use "
        "quando o Vitor disser que cansou de esperar, que quer parar, que tá "
        "travado, ou quando você souber que o comando não vai terminar. Não faz "
        "nada se não tem comando rodando."
    ),
    propriedades={},
    aviso="cancelando_terminal",
    executar=lambda: _terminal_cancelar(),
))


def _terminal_cancelar() -> str:
    import terminal
    return terminal.cancelar()


def _descobrir_comando(software: str):
    import pesquisa
    return pesquisa.pesquisar_comando(software)


registrar(Ferramenta(
    nome="descobrir_comando",
    grupo="geral",
    descricao=(
        "PESQUISA LEVE de comando de terminal. Use ANTES de executar qualquer "
        "comando de instalar, desinstalar, atualizar ou configurar um programa "
        "SEMPRE que você não tiver certeza ABSOLUTA do comando exato e do nome "
        "do pacote no sistema atual. NUNCA invente comando, nome de pacote ou "
        "flag: se tem qualquer dúvida, pesquise AQUI primeiro, leia o comando "
        "que a pesquisa trouxe, confira se serve pra distro atual, e SÓ DEPOIS "
        "execute via executar_terminal (explicando ao Vitor e pedindo "
        "confirmação, porque instalar/desinstalar pede confirmação). Exemplo: "
        "'instala o alacritty' → descobrir_comando(software='alacritty') → "
        "pesquisa retorna 'sudo dnf install alacritty' → explica e executa. "
        "Também serve pra descobrir como rodar/executar algo desconhecido. "
        "É leve: uma busca rápida, não abre navegador."
    ),
    propriedades={
        "software": {
            "type": "string",
            "description": ("Nome do programa/coisa que se quer instalar ou "
                            "executar. Ex.: 'alacritty', 'steam', 'whatsapp'."),
        },
    },
    obrigatorios=["software"],
    aviso="pesquisando_comando",
    executar=lambda software: _descobrir_comando(software),
))


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — NAVEGADOR: FORMULÁRIOS E INTERAÇÃO COM PÁGINA
#
# Requer a extensão Emily Browser Bridge ativada no navegador do Vitor.
# Fluxo de formulário: ver_formularios → coletar o que falta COM O VITOR
# → preencher_formularios → CONFIRMAR → submeter_formulario.
# ═════════════════════════════════════════════════════════════════

def _ver_formularios():
    import navegador
    if not navegador.esta_conectado():
        return recusa("A extensão Emily do navegador não está conectada. "
                      "Peça ao Vitor pra conferir se a extensão está ativada "
                      "e o navegador aberto, e tente de novo.")
    dados = navegador.ler_formularios()
    if not dados or dados.get("tipo") == "erro":
        return recusa("Não consegui ler os formulários da página. Detalhe: "
                      + str((dados or {}).get("mensagem", "sem resposta da extensão")))
    partes = ["Página: " + str(dados.get("titulo", "")) + " — " + str(dados.get("url", ""))]
    for f in dados.get("formularios", []):
        nome_f = " (" + f["nome"] + ")" if f.get("nome") else ""
        partes.append("\nFORMULÁRIO " + str(f["indice"]) + nome_f + ":")
        for c in f.get("campos", []):
            linha = ("  - [" + c["tipo"] + "] rótulo: "
                     + (c.get("rotulo") or c.get("nome") or "(sem rótulo)")
                     + " | seletor: " + c["seletor"]
                     + " | obrigatório: " + str(c.get("obrigatorio", False)))
            if c.get("frame_id") not in (None, 0):
                linha += " | frame_id: " + str(c["frame_id"])
            if c.get("opcoes"):
                linha += " | opções: " + ", ".join(c["opcoes"])
            if c.get("valor_atual"):
                linha += " | já preenchido: " + str(c["valor_atual"])
            partes.append(linha)
        if f.get("botao_enviar"):
            partes.append("  - [botão de enviar] seletor: " + f["botao_enviar"])
    if dados.get("campos_soltos"):
        partes.append("\nCAMPOS FORA DE FORMULÁRIO:")
        for c in dados["campos_soltos"]:
            partes.append("  - [" + c["tipo"] + "] "
                          + (c.get("rotulo") or c.get("nome") or "(sem rótulo)")
                          + " | seletor: " + c["seletor"]
                          + ((" | frame_id: " + str(c["frame_id"]))
                             if c.get("frame_id") not in (None, 0) else ""))
    if len(partes) == 1 and not dados.get("campos_soltos"):
        partes.append("Nenhum formulário visível nesta página.")
    return "\n".join(partes)


registrar(Ferramenta(
    nome="ver_formularios_navegador",
    grupo="geral",
    descricao=(
        "REQUER a extensão Emily ativada no navegador. Lê TODOS os formulários "
        "e campos visíveis da aba atual do navegador do Vitor: rótulos, tipos, "
        "opções de select, o que já está preenchido e o que é obrigatório. "
        "Use quando o Vitor pedir pra preencher formulário, cadastro, login, "
        "pesquisa ou qualquer coisa na página dele. FLUXO OBRIGATÓRIO: (1) leia "
        "os campos; (2) identifique qual informação está faltando; (3) PERGUNTE "
        "ao Vitor no chat o que falta — NUNCA invente dados pessoais dele; (4) "
        "preencha com preencher_formularios_navegador; (5) confirme com ele "
        "ANTES de enviar com submeter_formulario_navegador. Campos tipo password "
        "só se ele pedir explicitamente."
    ),
    propriedades={},
    aviso="lendo_pagina",
    executar=lambda: _ver_formularios(),
))


def _preencher_formularios(campos_json: str):
    import navegador
    import json as _json
    if not navegador.esta_conectado():
        return recusa("A extensão Emily do navegador não está conectada.")
    try:
        campos = _json.loads(campos_json)
    except Exception as e:
        return recusa("campos_json não é um JSON válido: " + str(e))
    if not isinstance(campos, list) or not campos:
        return recusa('campos_json tem que ser uma lista de {"seletor": ..., '
                      '"valor": ...} — use os seletores de ver_formularios_navegador.')
    resultado = navegador.preencher_formulario(campos)
    if not resultado or resultado.get("tipo") == "erro":
        return recusa("Falhou preenchendo: "
                      + str((resultado or {}).get("mensagem", "sem resposta")))
    resultados = resultado.get("resultados", [])
    ok = [r for r in resultados if r.get("ok")]
    falha = [r for r in resultados if not r.get("ok")]
    texto = "Preenchi " + str(len(ok)) + "/" + str(len(resultados)) + " campos."
    if falha:
        texto += " Não consegui: " + "; ".join(
            r["seletor"] + " (" + str(r.get("motivo", "valor não aceito")) + ")"
            for r in falha)
        texto += " Confira com o Vitor o que fazer com os campos que falharam."
    else:
        texto += " Antes de ENVIAR, confirme com o Vitor e use "
        texto += "submeter_formulario_navegador."
    return texto


registrar(Ferramenta(
    nome="preencher_formularios_navegador",
    grupo="geral",
    descricao=(
        "REQUER a extensão Emily ativada. Preenche uma LISTA de campos da página "
        "atual de uma vez. Use DEPOIS de ver_formularios_navegador: cada item é "
        '{"seletor": <seletor exato>, "valor": <texto>, "frame_id": <se mostrado>}. '
        "Sempre preserve frame_id quando ver_formularios_navegador mostrar um. Para select, "
        "valor tem que casar com uma das opções; checkbox aceita true/false; "
        "radio recebe o valor da opção. NUNCA invente dados do Vitor: o que "
        "faltar, pergunte no chat antes. Antes de ENVIAR o formulário, sempre "
        "confirme com ele."
    ),
    propriedades={
        "campos_json": {
            "type": "string",
            "description": ('JSON em texto: lista de {"seletor": ..., "valor": '
                            '..., "frame_id": opcional}. Preserve frame_id da leitura.'),
        },
    },
    obrigatorios=["campos_json"],
    aviso="preenchendo_formulario",
    executar=lambda campos_json: _preencher_formularios(campos_json),
))


registrar(Ferramenta(
    nome="submeter_formulario_navegador",
    grupo="geral",
    descricao=(
        "REQUER a extensão Emily ativada. ENVIA (submit) um formulário da página "
        "atual. Use SOMENTE depois de preencher com preencher_formularios_"
        "navegador e depois de o Vitor CONFIRMAR explicitamente que quer enviar — "
        "enviar formulário é a ação que vale, não tem desfazer. indice = número "
        "do formulário na lista de ver_formularios_navegador; vazio = o primeiro "
        "com botão de enviar."
    ),
    propriedades={
        "indice": {"type": "integer",
                   "description": "Índice do formulário (de ver_formularios_navegador). Vazio = o primeiro com botão de enviar."},
    },
    aviso="enviando_formulario",
    executar=lambda indice=None: (
        (lambda r: (
            "Formulário enviado."
            if (r or {}).get("ok")
            else recusa("Não consegui enviar: "
                        + str((r or {}).get("motivo", "sem resposta da extensão")))
        ))((
            (lambda nav: (
                {"ok": False, "motivo": "extensão do navegador não conectada"}
                if not nav.esta_conectado()
                else nav.submeter_formulario(indice if isinstance(indice, int) else None)
            ))(__import__("navegador"))
        ))
    ),
))


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — NAVEGADOR: MODO BASTIDOR
#
# O modo bastidor faz TODAS as ferramentas de navegador trabalharem numa
# janela própria minimizada (mesmo perfil, mesmos logins) em vez da aba
# ativa do Vitor. A injeção do flag é centralizada no navegador.py — aqui
# só existe a ferramenta que liga/desliga e o abrir_site que respeita o modo.
# ═════════════════════════════════════════════════════════════════

def _modo_bastidor(modo: str = "ligar"):
    import navegador
    if not navegador.esta_conectado():
        return recusa("A extensão Emily do navegador não está conectada. "
                      "Peça ao Vitor pra conferir se a extensão está ativada "
                      "e o navegador aberto, e tente de novo.")
    modo = (modo or "ligar").strip().lower()
    if modo in ("ligar", "ativar", "on", "1", "true"):
        ativo = navegador.definir_modo_bastidor(True)
    elif modo in ("desligar", "desativar", "off", "0", "false"):
        ativo = navegador.definir_modo_bastidor(False)
    else:
        ativo = navegador.modo_bastidor_ativo()
        return ("O modo bastidor está " + ("LIGADO" if ativo else "DESLIGADO") + ". "
                "Diga 'ligar' ou 'desligar' pra mudar.")
    if ativo:
        return ("Modo bastidor LIGADO: daqui pra frente eu trabalho numa janela "
                "escondida do seu navegador — você pode continuar usando ele "
                "tranquilo que eu não tomo a sua aba.")
    return "Modo bastidor DESLIGADO: volto a mexer na aba visível do navegador."


registrar(Ferramenta(
    nome="modo_bastidor",
    grupo="geral",
    descricao=(
        "Liga ou desliga o MODO BASTIDOR: você passa a mexer no navegador dele "
        "por baixo dos panos, numa janela escondida (mesmo perfil, mesmos "
        "logins), sem tomar a aba que ele está usando. LIGUE antes de tarefas "
        "de web que navegam por várias páginas (baixar arquivo, procurar coisa "
        "no site, cadastro) para não atrapalhar ele. NÃO ligue quando ele pedir "
        "pra mexer na página que ELE está olhando ('lê essa página', 'clica "
        "aí', 'preenche isso aqui') — nesse caso use o modo normal. Lembre de "
        "desligar no fim se ele quiser ver o que você fez na tela. Screenshot "
        "(ver_pagina_navegador) não funciona no bastidor: use ler_pagina_"
        "navegador."
    ),
    propriedades={
        "modo": {
            "type": "string",
            "enum": ["ligar", "desligar"],
            "description": "Ligar = janela escondida. Desligar = volta ao modo normal.",
        },
    },
    obrigatorios=[],
    aviso="abrir_app",
    executar=lambda modo="ligar": _modo_bastidor(modo),
))


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — NAVEGADOR: LIBERDADE GERAL (o "terminal" do navegador)
#
# A extensão Emily Browser Bridge precisa estar ativa. O executa de
# JavaScript é o escape hatch universal (como executar_terminal pro
# Linux); as outras ferramentas são os atalhos de alto nível.
# ═════════════════════════════════════════════════════════════════

def _exige_extensao():
    import navegador
    if not navegador.esta_conectado():
        return recusa("A extensão Emily do navegador não está conectada. "
                      "Peça ao Vitor pra conferir se a extensão está ativada "
                      "e o navegador aberto, e tente de novo.")
    import navegador
    return navegador


def _ler_pagina_navegador():
    nav = _exige_extensao()
    if isinstance(nav, ResultadoFerramenta):
        return nav
    r = nav.enviar_comando_com_id("ler_pagina", timeout=15)
    if not r or r.get("tipo") == "erro":
        return recusa("Não consegui ler a página: "
                      + str((r or {}).get("mensagem", "sem resposta da extensão")))
    texto = r.get("texto", "").strip()
    bloqueio = r.get("bloqueio") or {}
    if bloqueio:
        return consulta(
            "A página está bloqueada para automação neste momento: "
            + str(bloqueio.get("mensagem") or bloqueio.get("tipo") or "proteção do site")
            + " Não tente contornar CAPTCHA, Cloudflare ou acesso negado; peça ao Vitor "
              "para concluir a etapa manualmente e depois tente ler novamente."
        )
    if not texto:
        return recusa("A página não tem texto legível (deve ser algo dinâmico). "
                      "Tente ver_pagina_navegador pra VER a página.")
    nota_login = (
        "\n\n[LOGIN DETECTADO: use ver_formularios_navegador, nunca invente "
        "credenciais e peça ao Vitor para concluir CAPTCHA/OAuth manualmente.]"
        if r.get("parece_login") else ""
    )
    return ("Página: " + str(r.get("titulo", "")) + " — " + str(r.get("url", ""))
            + nota_login + "\n\n" + texto[:40000])


registrar(Ferramenta(
    nome="ler_pagina_navegador",
    grupo="geral",
    descricao=(
        "REQUER a extensão Emily ativada. Lê o TEXTO completo da aba ativa do "
        "navegador do Vitor. Use pra saber o que está escrito na página que ele "
        "está olhando: artigos, produtos, instruções, resultados. Para "
        "formulários use ver_formularios_navegador; pra VER o visual (imagens, "
        "layout) use ver_pagina_navegador; pra pegar LINKS use "
        "extrair_links_da_pagina."
    ),
    propriedades={},
    aviso="lendo_pagina",
    executar=lambda: _ler_pagina_navegador(),
))


def _extrair_links_da_pagina(filtro: str = ""):
    nav = _exige_extensao()
    if isinstance(nav, ResultadoFerramenta):
        return nav
    r = nav.extrair_links(limite=100)
    if not r or r.get("tipo") == "erro":
        return recusa("Não consegui extrair os links: "
                      + str((r or {}).get("mensagem", "sem resposta")))
    links = r.get("links", [])
    if not links:
        return recusa("Nenhum link visível nesta página.")

    # Ruído de navegação que nunca é o que o Vitor quer: âncoras da própria
    # página, javascript:, e os "skip to content" de acessibilidade.
    _RUIDO_TEXTO = ("skip to content", "pular para", "ir para o conteúdo",
                    "voltar ao topo", "sign in / join", "log in / sign up")

    def _limpo(l: dict) -> bool:
        href = (l.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            return False
        texto = (l.get("texto") or "").strip().lower()
        return not any(ruido in texto for ruido in _RUIDO_TEXTO)

    links = [l for l in links if _limpo(l)]

    # O filtro é o que evita a enxurrada: "baixa um mod de moveset" no Nexus
    # devolvia 81 links e a Emily se perdia dentro deles. Com filtro, só os
    # que casam com a palavra no texto ou na URL.
    termo = (filtro or "").strip().lower()
    if termo:
        termos = [t.strip() for t in termo.split() if t.strip()]
        def _casa(l: dict) -> bool:
            palhada = ((l.get("texto") or "") + " " + (l.get("href") or "")).lower()
            return any(t in palhada for t in termos)
        casados = [l for l in links if _casa(l)]
        if casados:
            links = casados
        else:
            # Nada casou: avisa em vez de devolver a página inteira de novo —
            # devolver tudo só ensina o modelo a ignorar o filtro.
            return (f"Nenhum dos {len(r.get('links', []))} links desta página "
                    f"casa com '{filtro}'. Dica: use ler_pagina_navegador pra "
                    "ver o texto da página e refinar o termo, ou ver_pagina_"
                    "navegador pra VER o que tem na tela.")

    downloads = [l for l in links if l.get("download")]
    comuns = [l for l in links if not l.get("download")]
    partes = [f"Links da página ({len(links)} relevantes"
              + (f" — filtro: '{filtro}'" if termo else "") + "):"]
    for l in downloads[:15]:
        partes.append("- " + (l.get("texto") or "(sem texto)") + " → "
                      + l["href"] + " [ARQUIVO PRA DOWNLOAD]")
    for l in comuns[:25]:
        partes.append("- " + (l.get("texto") or "(sem texto)") + " → " + l["href"])
    if downloads:
        partes.append("\nTem link(s) marcado(s) [ARQUIVO PRA DOWNLOAD]: pra "
                      "baixar, use baixar_arquivo_navegador com a URL.")
    total = len(downloads) + len(comuns)
    if total > 40:
        partes.append(f"(mostrando os 40 mais relevantes de {total})")
    return "\n".join(partes)


registrar(Ferramenta(
    nome="extrair_links_da_pagina",
    grupo="geral",
    descricao=(
        "REQUER a extensão Emily ativada. Extrai os links da aba ativa, "
        "marcando os que parecem ser download direto de arquivo (zip, pdf, "
        "exe, mp3...). SEMPRE passe 'filtro' com a palavra-chave do que você "
        "procura (ex.: 'moveset') — sem filtro ele devolve TODOS os links da "
        "página e você se perde. Use pra achar o link de download quando o "
        "Vitor quiser baixar algo, ou pra navegar pra uma seção específica."
    ),
    propriedades={
        "filtro": {
            "type": "string",
            "description": ("Palavra-chave pra filtrar os links (ex.: nome do "
                            "mod, tipo de arquivo). Vazio = todos os links."),
        },
    },
    aviso="lendo_pagina",
    executar=lambda filtro="": _extrair_links_da_pagina(filtro),
))


def _baixar_arquivo_navegador(url: str):
    nav = _exige_extensao()
    if isinstance(nav, ResultadoFerramenta):
        return nav
    url = (url or "").strip()
    if not url.startswith("http"):
        return recusa("URL inválida pra download: " + str(url))
    r = nav.baixar_arquivo_confirmado(url)
    if not r or r.get("tipo") == "erro":
        return recusa("Download não iniciou: "
                      + str((r or {}).get("mensagem", "sem resposta da extensão")))
    return ("Download iniciado pelo navegador do Vitor — o arquivo vai pra "
            "pasta Downloads dele. Avisando que iniciei o download de: " + url)


registrar(Ferramenta(
    nome="baixar_arquivo_navegador",
    grupo="geral",
    descricao=(
        "REQUER a extensão Emily ativada. Baixa um arquivo pelo navegador do "
        "Vitor (o arquivo vai pra pasta Downloads dele). Use com a URL de "
        "download — na dúvida, extraia primeiro com extrair_links_da_pagina. "
        "Diga ao Vitor que o download começou. Para downloads que precisam de "
        "login, o navegador dele já está com as contas logadas."
    ),
    propriedades={
        "url": {"type": "string", "description": "URL direta do arquivo pra baixar"},
    },
    obrigatorios=["url"],
    aviso="baixando_arquivo",
    executar=lambda url: _baixar_arquivo_navegador(url),
))


def _abrir_site_em_nova_aba(url: str, ativa: bool = True):
    nav = _exige_extensao()
    if isinstance(nav, ResultadoFerramenta):
        return nav
    r = nav.nova_aba(url=url, ativa=ativa)
    if not r or r.get("tipo") == "erro":
        return recusa("Não consegui abrir a nova aba: "
                      + str((r or {}).get("mensagem", "sem resposta")))
    return "Abri " + str(url) + " em uma nova aba do navegador."


registrar(Ferramenta(
    nome="abrir_site_em_nova_aba",
    grupo="geral",
    descricao=(
        "REQUER a extensão Emily ativada. Abre uma URL em uma NOVA aba do "
        "navegador, SEM mexer na aba que o Vitor está olhando. Use quando não "
        "quiser roubar o foco da aba atual (ex.: abrir um vídeo ou artigo "
        "enquanto ele faz outra coisa). Para substituir a página atual, use "
        "abrir_site normal."
    ),
    propriedades={
        "url": {"type": "string", "description": "URL completa pra abrir"},
        "ativa": {"type": "boolean", "description": "Se a nova aba ganha foco. Padrão: true."},
    },
    obrigatorios=["url"],
    aviso="abrir_app",
    executar=lambda url, ativa=True: _abrir_site_em_nova_aba(url, ativa),
))


def _listar_abas_navegador():
    nav = _exige_extensao()
    if isinstance(nav, ResultadoFerramenta):
        return nav
    r = nav.listar_abas()
    if not r or r.get("tipo") == "erro":
        return recusa("Não consegui listar as abas: "
                      + str((r or {}).get("mensagem", "sem resposta")))
    abas = r.get("abas", [])
    partes = ["Abas abertas do Vitor (" + str(len(abas)) + "):"]
    for t in abas:
        marca = " ← ATIVA" if t.get("ativa") else ""
        partes.append("- " + str(t.get("titulo", "")) + " | "
                      + str(t.get("url", "")) + marca)
    return "\n".join(partes)


registrar(Ferramenta(
    nome="listar_abas_navegador",
    grupo="geral",
    descricao=(
        "REQUER a extensão Emily ativada. Lista as abas que o Vitor tem abertas "
        "(título e URL). PRIVACIDADE: só use quando o Vitor PEDIR explicitamente "
        "algo sobre as abas dele (\'que abas eu tenho aberto?\', \'acha aquela "
        "aba do curso\'). Nunca liste por conta própria por curiosidade. Ações "
        "nas páginas sempre acontecem na ABA ATIVA, não nessa lista."
    ),
    propriedades={},
    aviso="lendo_pagina",
    executar=lambda: _listar_abas_navegador(),
))


def _ver_pagina_navegador(pergunta: str = ""):
    nav = _exige_extensao()
    if isinstance(nav, ResultadoFerramenta):
        return nav
    captura = nav.screenshot_aba(timeout=15)
    if not captura:
        return recusa("Não consegui capturar a aba (a aba pode ser uma página "
                      "interna do navegador, tipo chrome://settings).")
    import modelo
    pergunta = (pergunta or "").strip() or (
        "Descreva o que aparece nesta página do navegador do Vitor: layout "
        "principal, botões e links importantes, imagens, se tem formulário ou "
        "captcha, e qualquer elemento que pareça relevante pro que ele pediu.")
    return modelo.analisar_tela_com_pergunta(captura, pergunta)


registrar(Ferramenta(
    nome="ver_pagina_navegador",
    grupo="geral",
    descricao=(
        "REQUER a extensão Emily ativada. Tira um PRINT da aba ativa do "
        "navegador e ANALISA com a sua visão — é como você VÊ a página. NÃO "
        "funciona no modo bastidor (a janela escondida não dá print): se ele "
        "estiver ligado, use ler_pagina_navegador. Use "
        "quando o texto não basta: layout estranho, imagem, captcha visual, "
        "botão sem rótulo claro, canvas, ou quando o Vitor perguntar \'você tá "
        "vendo isso?\'. Você pode mandar uma pergunta específica sobre o que "
        "quer enxergar. Para textos e formulários, prefira ler_pagina_navegador "
        "e ver_formularios_navegador (mais leves)."
    ),
    propriedades={
        "pergunta": {"type": "string", "description": "O que você quer enxergar/verificar na página. Vazio = descrição geral."},
    },
    aviso="analizando_pagina",
    executar=lambda pergunta="": _ver_pagina_navegador(pergunta),
))


def _executar_javascript_pagina(codigo: str, frame_id=None):
    nav = _exige_extensao()
    if isinstance(nav, ResultadoFerramenta):
        return nav
    r = nav.executar_js_com_id(codigo, frame_id=frame_id)
    if not r or r.get("tipo") == "erro":
        return recusa("O JavaScript falhou ou não devolveu nada: "
                      + str((r or {}).get("mensagem", "sem resposta da extensão")))
    sufixo = f" (frame {r['frame_id']})" if r.get("frame_id") not in (None, 0) else ""
    return "Resultado" + sufixo + ": " + str(r.get("resultado", "(sem retorno)"))


registrar(Ferramenta(
    nome="executar_javascript_na_pagina",
    grupo="geral",
    descricao=(
        "O TERMINAL DO NAVEGADOR — acesso amplo ao DOM atual via JavaScript. "
        "REQUER a extensão Emily ativada. Roda no mundo ISOLADO da extensão (por "
        "isso funciona mesmo com CSP rígida), com document/window e APIs web, mas "
        "sem acesso às variáveis JS privadas do site. Por padrão age no frame "
        "principal; passe frame_id somente quando outra ferramenta mostrar um. Use "
        "pra QUALQUER coisa que as outras ferramentas de navegador não cobrem: "
        "clicar botões complexos, expandir menus, ler tabelas dinâmicas, rolar "
        "até elemento, mudar filtros, copiar conteúdo, interagir com players. "
        "O código roda com return no final (ex.: \"return "
        "document.querySelector(\'h1\').innerText\"). REGRAS DE SEGURANÇA: (1) "
        "NUNCA mande dados da página pra servidor externo (fetch pra fora) — "
        "os dados ficam entre você e o Vitor; (2) ações que ENVIAM, APAGAM, "
        "COMPRAM ou PUBLICAM (submit, delete, checkout) só com confirmação "
        "explícita do Vitor antes; (3) NUNCA capture ou preencha campos de "
        "senha, exceto se ele pedir explicitamente; (4) se o JS falhar, tente "
        "entender o erro e ajuste, em vez de repetir igual. Os logins do Vitor "
        "já estão salvos no navegador: você age DENTRO da sessão dele — se um "
        "site pedir login via popup do Google/OAuth, diga pro Vitor logar à mão "
        "uma vez, NÃO tente automatizar o popup."
    ),
    propriedades={
        "codigo": {"type": "string", "description": "Código JavaScript completo pra rodar na página. Deve ter return com o que você quer de volta."},
        "frame_id": {"type": "integer", "description": "Frame específico mostrado por outra ferramenta. Vazio = página principal."},
    },
    obrigatorios=["codigo"],
    aviso="executando_javascript",
    executar=lambda codigo, frame_id=None: _executar_javascript_pagina(codigo, frame_id),
))


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — MÍDIA DA ABA ATUAL
#
# Descoberta acontece na extensão; resolução/qualidade/download acontecem no
# PC por yt-dlp. Nenhuma ferramenta tenta burlar DRM, CAPTCHA ou paywall.
# ═════════════════════════════════════════════════════════════════

def _duracao_midia(segundos) -> str:
    if segundos in (None, ""):
        return ""
    try:
        total = int(float(segundos))
    except (TypeError, ValueError):
        return ""
    horas, resto = divmod(total, 3600)
    minutos, secs = divmod(resto, 60)
    return f"{horas}:{minutos:02d}:{secs:02d}" if horas else f"{minutos}:{secs:02d}"


def _listar_midias_aba():
    nav = _exige_extensao()
    if isinstance(nav, ResultadoFerramenta):
        return nav
    r = nav.descobrir_midias(timeout=18)
    if not r or r.get("tipo") == "erro":
        return recusa("Não consegui analisar as mídias da aba: "
                      + str((r or {}).get("mensagem", "sem resposta da extensão")))
    itens = r.get("itens") or []
    if not itens:
        return consulta(
            "Não encontrei vídeo ou áudio acessível nesta aba. Dê play e tente "
            "novamente; se houver DRM, CAPTCHA ou login, o Vitor precisa resolver "
            "isso manualmente. Não diga que iniciou download.")

    partes = [f"Mídias detectadas em '{r.get('titulo', '')}' ({len(itens)}):"]
    for indice, item in enumerate(itens[:20], 1):
        detalhes = [str(item.get("tipo") or "mídia")]
        if item.get("altura"):
            detalhes.append(f"{item['altura']}p")
        duracao = _duracao_midia(item.get("duracao"))
        if duracao:
            detalhes.append(duracao)
        if item.get("ativo"):
            detalhes.append("tocando agora")
        if item.get("drm"):
            detalhes.append("DRM — não baixável")
        titulo = str(item.get("titulo") or "Mídia sem título").replace("\n", " ")[:180]
        partes.append(f"{indice}. {titulo} [{', '.join(detalhes)}]\n   {item.get('url', '')}")
    if len(itens) > 20:
        partes.append(f"(mostrando 20 de {len(itens)}; peça para refinar a página se necessário)")
    if r.get("drm_detectado"):
        partes.append("AVISO: o player informou DRM. A Emily não contorna DRM; ofereça apenas opções sem essa marca.")
    partes.append(
        "FLUXO OBRIGATÓRIO: se houver mais de uma opção, PERGUNTE no chat qual "
        "número o Vitor quer. Também pergunte se quer VÍDEO ou só ÁUDIO e, para "
        "vídeo, a resolução; para áudio, pode perguntar o bitrate se ele se "
        "importar com isso. Caso ele ainda não tenha dito, não escolha sozinho. "
        "Depois use baixar_midia_da_aba com o índice exato deste catálogo.")
    return consulta("\n".join(partes))


registrar(Ferramenta(
    nome="listar_midias_da_aba",
    grupo="geral",
    descricao=(
        "REQUER a extensão Emily. Encontra vídeos e áudios na aba atual, inclusive "
        "YouTube e players em iframes, e devolve opções numeradas. É SEMPRE o "
        "primeiro passo quando o Vitor pedir para baixar 'esse vídeo', 'o vídeo "
        "da página', mídia da aba ou quando houver vários players. Se vier mais de "
        "uma opção, você DEVE mostrar/resumir as opções e perguntar qual número. "
        "Se ele não disse formato, pergunte vídeo ou só áudio; se escolheu vídeo "
        "mas não disse qualidade, pergunte a qualidade. Não tenta quebrar DRM, "
        "CAPTCHA, Cloudflare, login ou paywall."
    ),
    propriedades={},
    aviso="lendo_pagina",
    executar=lambda: _listar_midias_aba(),
    somente_leitura=True,
))


def _ver_qualidades_midia(indice: int):
    import midia_navegador
    import navegador
    item = navegador.midia_do_catalogo(indice)
    if not item:
        return recusa("Esse índice não existe no catálogo atual. Use listar_midias_da_aba novamente.")
    if item.get("drm"):
        return recusa("Essa mídia está marcada com DRM e não pode ser baixada pela Emily.")
    if item.get("blob"):
        return recusa("Essa é uma URL blob temporária. Use a opção da página ou uma fonte HTTP do catálogo.")
    dados = midia_navegador.inspecionar(
        item.get("url", ""),
        navegador.metadados_catalogo_midias().get("navegador", ""),
        item.get("referer") or navegador.metadados_catalogo_midias().get("url", ""))
    if not dados.get("ok"):
        return recusa(str(dados.get("mensagem") or "Não consegui inspecionar essa mídia."))
    duracao = _duracao_midia(dados.get("duracao")) or "não informada"
    qualidades = ", ".join(dados.get("qualidades") or []) or "qualidade automática"
    return consulta(
        f"Mídia {indice}: {dados.get('titulo')}\nAutor: {dados.get('autor') or 'não informado'}\n"
        f"Duração: {duracao}\nQualidades de vídeo disponíveis: {qualidades}\n"
        "Áudio pode ser extraído em MP3. Pergunte qual qualidade o Vitor quer se ele ainda não disse.")


registrar(Ferramenta(
    nome="ver_qualidades_da_midia",
    grupo="geral",
    descricao=(
        "Consulta título, duração e resoluções reais de uma opção retornada por "
        "listar_midias_da_aba, sem baixar. Use quando o Vitor perguntar quais "
        "qualidades existem ou antes de pedir que ele escolha a resolução."
    ),
    propriedades={
        "indice": {"type": "integer", "description": "Número mostrado por listar_midias_da_aba."},
    },
    obrigatorios=["indice"],
    aviso="lendo_pagina",
    executar=lambda indice: _ver_qualidades_midia(indice),
    somente_leitura=True,
))


def _baixar_midia_aba(indice: int, formato: str, qualidade: str = "melhor"):
    import midia_navegador
    import navegador
    item = navegador.midia_do_catalogo(indice)
    if not item:
        return recusa("Esse índice não existe mais. Use listar_midias_da_aba e mostre as opções novamente.")
    if item.get("drm"):
        return recusa("Não iniciei: essa mídia está marcada com DRM e eu não contorno essa proteção.")
    if item.get("blob"):
        return recusa("Não iniciei: essa URL blob é temporária. Escolha a opção da página ou uma fonte HTTP.")
    meta = navegador.metadados_catalogo_midias()
    referer = item.get("referer") or meta.get("url", "")
    job = midia_navegador.iniciar_download(
        item.get("url", ""), formato=formato, qualidade=qualidade,
        navegador=meta.get("navegador", ""), referer=referer,
        pagina=meta.get("url", ""))
    tipo = "áudio em MP3" if job["formato"] == "audio" else f"vídeo ({job['qualidade']})"
    return ResultadoFerramenta(
        texto=(f"Download iniciado como {tipo}. Job: {job['id']}. Destino: {job['pasta']}. "
               "Use status_download_midia com esse job para acompanhar; não diga que concluiu ainda."),
        ok=True,
        mudou=True,
    )


registrar(Ferramenta(
    nome="baixar_midia_da_aba",
    grupo="geral",
    descricao=(
        "Baixa UMA opção do último listar_midias_da_aba, em vídeo ou só áudio. "
        "NUNCA chame antes de listar as mídias. Se havia várias, só chame após o "
        "Vitor escolher o índice. O argumento formato precisa refletir o que ele "
        "disse; se não disse, pergunte antes. Para vídeo, se ele não escolheu "
        "qualidade, pergunte ou use 'melhor' apenas se ele disser que tanto faz. "
        "Vídeo aceita qualquer resolução de 144p a 8640p; áudio aceita melhor, "
        "64, 96, 128, 192, 256 ou 320kbps. "
        "Funciona em sites suportados pelo yt-dlp e streams públicos, mas recusa "
        "DRM e não burla login/CAPTCHA/paywall. O download roda em segundo plano."
    ),
    propriedades={
        "indice": {"type": "integer", "description": "Número exato mostrado no último catálogo."},
        "formato": {"type": "string", "enum": ["video", "audio"], "description": "video = imagem+som; audio = MP3."},
        "qualidade": {"type": "string", "description": "Vídeo: melhor ou resolução entre 144p e 8640p (ex.: 1080p). Áudio: melhor, 64kbps, 96kbps, 128kbps, 192kbps, 256kbps ou 320kbps."},
    },
    obrigatorios=["indice", "formato"],
    aviso="baixando_arquivo",
    executar=lambda indice, formato, qualidade="melhor": _baixar_midia_aba(indice, formato, qualidade),
))


def _status_download_midia(job: str = ""):
    import midia_navegador
    dados = midia_navegador.status(job)
    if dados.get("estado") == "nao_encontrado":
        return recusa("Não encontrei um download com o job " + str(job) + ".")
    jobs = dados.get("jobs") if "jobs" in dados else [dados]
    if not jobs:
        return consulta("Nenhum download de mídia foi iniciado nesta sessão.")
    linhas = []
    for item in jobs:
        linha = f"Job {item['id']}: {item.get('estado', 'desconhecido')}"
        if item.get("percentual") is not None:
            linha += f" — {item['percentual']}%"
        if item.get("titulo"):
            linha += " — " + str(item["titulo"])
        if item.get("arquivo"):
            linha += "\nArquivo: " + str(item["arquivo"])
        if item.get("aviso"):
            linha += "\nAviso: " + str(item["aviso"])
        if item.get("erro"):
            linha += "\nErro: " + str(item["erro"])
        linhas.append(linha)
    return consulta("\n\n".join(linhas))


registrar(Ferramenta(
    nome="status_download_midia",
    grupo="geral",
    descricao=(
        "Consulta progresso, conclusão ou erro de downloads iniciados por "
        "baixar_midia_da_aba. Passe o job retornado; vazio lista os recentes. "
        "Só diga que terminou quando o estado for 'concluido'."
    ),
    propriedades={
        "job": {"type": "string", "description": "ID retornado ao iniciar. Vazio = downloads recentes."},
    },
    aviso="",
    executar=lambda job="": _status_download_midia(job),
    somente_leitura=True,
))


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — TV: a Emily do PC controlando a Android TV do Vitor
#
# Espelho exato do que a Emily do celular já fazia (TvController.kt no app),
# agora INDEPENDENTE do celular: o PC tem certificado próprio e fala direto
# com a TV pelo mesmo protocolo (Android TV Remote v2). O pareamento, a lista
# de dispositivos e o código de TV vivem no controle_tv.py e na aba TV das
# Configurações. Todas grupo "geral": mexer na TV é conversa com a Emily dele.
# ═════════════════════════════════════════════════════════════════

def _importar_tv():
    import controle_tv
    return controle_tv


def _tv_tvs():
    tv = _importar_tv()
    dispositivos = tv.listar_dispositivos()
    if not dispositivos:
        return consulta(
            "Nenhuma TV salva ainda. O Vitor pode adicionar o IP dela na aba "
            "TV das Configurações, ou me dizer nome e IP pra eu salvar com "
            "salvar_tv. Depois é conectar e usar.")
    linhas = [f"{len(dispositivos)} TV(s) salva(s):"]
    for d in dispositivos:
        marca = " ← ativa agora" if d.get("ativa") else ""
        tipo = f" · {d['tipo']}" if d.get("tipo") else ""
        pareada = "pareada" if d.get("pareada") else "NÃO pareada"
        linhas.append(f"{d['id']} · {d['nome']} · {d['ip']}{tipo} · {pareada}{marca}")
    linhas.append("Pra usar: conectar_tv com o id (ou o IP); depois mande teclas, "
                  "canais, apps e buscas normalmente.")
    return consulta("\n".join(linhas))


registrar(Ferramenta(
    nome="ver_tvs",
    descricao=(
        "Lista as TVs salvas da Emily do PC (nome, IP, tipo, pareada e qual "
        "está ativa). Use antes de conectar quando houver mais de uma TV, ou "
        "quando o Vitor perguntar o que está configurado. O pareamento com "
        "código é feito na aba TV das Configurações."
    ),
    propriedades={},
    aviso="",
    executar=lambda: _tv_tvs(),
    somente_leitura=True,
))


def _tv_salvar(nome: str, ip: str, tipo: str = ""):
    tv = _importar_tv()
    try:
        d = tv.salvar_dispositivo(nome, ip, tipo)
    except ValueError as e:
        return recusa(str(e))
    return consulta(
        f"TV salva: {d['nome']} · {d['ip']}" + (f" · {d['tipo']}" if d.get("tipo") else "")
        + ". Se ela nunca pareou com a Emily do PC, o Vitor pareia na aba TV "
          "das Configurações (código aparece na tela da TV).")


registrar(Ferramenta(
    nome="salvar_tv",
    descricao=(
        "Salva (ou atualiza) uma TV na lista de dispositivos pelo nome e IP, "
        "ex.: 'salva a TV da sala com o IP 192.168.0.15'. Se o IP já existe, "
        "atualiza nome/tipo. O campo tipo é o que o Vitor disser (ex.: TCL, "
        "Samsung, Philips); se ele não souber, deixe vazio. Depois de salvar, "
        "use conectar_tv."
    ),
    propriedades={
        "nome": {"type": "string", "description": "Nome amigável (ex.: TV da Sala)."},
        "ip": {"type": "string", "description": "IP local da TV (ex.: 192.168.0.15)."},
        "tipo": {"type": "string", "description": "Marca/modelo que o Vitor disser. Vazio = sem tipo."},
    },
    obrigatorios=["nome", "ip"],
    aviso="",
    executar=lambda nome, ip, tipo="": _tv_salvar(nome, ip, tipo),
))


def _tv_conectar(alvo: str):
    tv = _importar_tv()
    dispositivos = tv.listar_dispositivos()
    if not dispositivos:
        return recusa("Nenhuma TV salva. Use salvar_tv ou a aba TV das Configurações.")
    alvo_limpo = (alvo or "").strip().lower()
    if not alvo_limpo:
        if len(dispositivos) == 1:
            alvo_limpo = dispositivos[0]["id"]
        else:
            return consulta("Tem mais de uma TV salva. Qual delas? Me diga o "
                            "nome (ou o IP) de:\n" + "\n".join(
                                f"- {d['nome']} ({d['ip']})" for d in dispositivos))
    d = next((x for x in dispositivos
              if alvo_limpo in (x["id"], x["ip"])
              or alvo_limpo in x["nome"].lower()), None)
    if not d:
        return recusa(f"Não achei a TV '{alvo}'. As salvas: "
                      + ", ".join(f"{x['nome']} ({x['ip']})" for x in dispositivos))
    resultado = tv.conectar_dispositivo(d["id"])
    if not resultado.get("ok"):
        msg = resultado.get("mensagem", "falhou")
        if resultado.get("precisa_parear"):
            return consulta(msg + " Não tente de novo nem invente código: o "
                            "pareamento é manual, na aba TV das Configurações.")
        return recusa(msg)
    return consulta(resultado["mensagem"])


registrar(Ferramenta(
    nome="conectar_tv",
    descricao=(
        "Conecta a Emily numa TV salva e a torna ativa. Passe o nome (ou IP) "
        "da TV; vazio conecta a única salva, e com várias ele pergunta qual. "
        "Se voltar que precisa parear, NÃO repita: diga pro Vitor usar o "
        "botão 'Parear na TV' da aba TV nas Configurações."
    ),
    propriedades={
        "alvo": {"type": "string", "description": "Nome ou IP da TV. Vazio = a única salva."},
    },
    aviso="mexendo_na_tv",
    executar=lambda alvo="": _tv_conectar(alvo),
))


def _tv_comando(acao: str, parametro: str = "", texto: str = ""):
    tv = _importar_tv()
    acao_limpa = (acao or "").strip().lower().replace(" ", "_").replace("-", "_")
    resultado: str
    if acao_limpa == "power":
        resultado = tv.enviar_tecla("power")
    elif acao_limpa == "volume":
        p = (parametro or "").strip().lower()
        resultado = {"aumentar": tv.enviar_tecla("volume_up"),
                     "diminuir": tv.enviar_tecla("volume_down"),
                     "mudo": tv.enviar_tecla("volume_mute")}.get(
            p, f"ERRO: para volume use aumentar, diminuir ou mudo (recebi '{parametro}')")
    elif acao_limpa == "canal":
        resultado = tv.sintonizar_canal(parametro)
    elif acao_limpa == "input":
        resultado = tv.enviar_tecla("tv_input")
    else:
        resultado = tv.enviar_tecla(acao_limpa, texto=texto)
    if resultado.startswith("ERRO"):
        return recusa(resultado)
    return consulta(resultado)


registrar(Ferramenta(
    nome="comando_tv",
    descricao=(
        "Comando direto na TV ATIVA: power (liga/desliga), volume (aumentar/"
        "diminuir/mudo), canal (número ou globo/record — abre a TV ao vivo e "
        "digita), input (troca HDMI/fonte), ou uma tecla avulsa: home, back, "
        "menu, settings, play, pause, playpause, stop, forward, rewind, next, "
        "previous, up, down, left, right, ok, channel_up, channel_down. Passe "
        "também texto pra digitar algo num campo da TV. Se nenhuma TV estiver "
        "conectada, use ver_tvs + conectar_tv primeiro."
    ),
    propriedades={
        "acao": {"type": "string",
                 "description": "power | volume | canal | input | nome de tecla (home, back, ok, play…)."},
        "parametro": {"type": "string",
                      "description": "Para volume: aumentar/diminuir/mudo. Para canal: número ou nome (globo, record)."},
        "texto": {"type": "string",
                  "description": "Texto pra digitar num campo da TV (busca, login). Opcional."},
    },
    obrigatorios=["acao"],
    aviso="mexendo_na_tv",
    executar=lambda acao, parametro="", texto="": _tv_comando(acao, parametro, texto),
))


def _tv_abrir_app(app: str):
    tv = _importar_tv()
    resultado = tv.abrir_app(app)
    if resultado.startswith("ERRO"):
        return recusa(resultado)
    return consulta(resultado)


registrar(Ferramenta(
    nome="abrir_app_tv",
    descricao=(
        "Abre um app na TV ATIVA pelo nome: youtube, netflix, prime (video), "
        "disney (plus), max (hbo max), spotify, globoplay. Se nenhum app foi "
        "citado ou o pedido é buscar algo DENTRO do app, use buscar_na_tv. Se "
        "nenhuma TV estiver conectada, use ver_tvs + conectar_tv primeiro."
    ),
    propriedades={
        "app": {"type": "string", "description": "Nome do app (ex.: youtube, netflix, spotify)."},
    },
    obrigatorios=["app"],
    aviso="mexendo_na_tv",
    executar=lambda app: _tv_abrir_app(app),
))


def _tv_buscar(app: str, query: str):
    tv = _importar_tv()
    resultado = tv.buscar_no_app(app, query)
    if resultado.startswith("ERRO"):
        return recusa(resultado)
    return consulta(resultado)


registrar(Ferramenta(
    nome="buscar_na_tv",
    descricao=(
        "Busca um conteúdo DENTRO de um app da TV ATIVA e abre os resultados: "
        "funciona no YouTube e na Netflix ('procura Chaves no YouTube da TV', "
        "'abre Dark na Netflix da TV'). Para só abrir o app sem buscar, use "
        "abrir_app_tv. Se nenhuma TV estiver conectada, use ver_tvs + "
        "conectar_tv primeiro."
    ),
    propriedades={
        "app": {"type": "string", "description": "youtube ou netflix."},
        "query": {"type": "string", "description": "O que buscar (filme, série, canal, vídeo)."},
    },
    obrigatorios=["app", "query"],
    aviso="mexendo_na_tv",
    executar=lambda app, query: _tv_buscar(app, query),
))


def _tv_status():
    tv = _importar_tv()
    return consulta(tv.status_tv())


registrar(Ferramenta(
    nome="status_da_tv",
    descricao=(
        "Mostra o estado da TV: dispositivos salvos, qual está ativa, ligada "
        "ou desligada, app em foco e volume. Use quando o Vitor perguntar "
        "'a TV tá ligada?', 'o que tá passando na TV?', 'qual TV tá ativa?' "
        "ou quando um comando de TV falhar e você precisar entender por quê."
    ),
    propriedades={},
    aviso="",
    executar=lambda: _tv_status(),
    somente_leitura=True,
))


def _tv_compartilhar_tela_pc(preset: str = "1080p60", monitor: int = 1, audio: bool = True):
    resultado = _importar_tv().compartilhar_tela_pc(preset, monitor, audio)
    return consulta(resultado.get("mensagem", "Tela compartilhada.")) if resultado.get("ok") else recusa(
        resultado.get("mensagem", "ERRO: não consegui compartilhar a tela."))


registrar(Ferramenta(
    nome="compartilhar_tela_pc_tv",
    descricao=(
        "Compartilha ao vivo a tela do PC na TV ativa pela rede local, com baixa latência, "
        "vídeo H.264 e áudio Opus. Use quando o Vitor pedir para espelhar, transmitir ou "
        "mostrar a tela do PC na TV. 1080p60 é alvo adaptativo; a TV e o PC podem reduzir."
    ),
    propriedades={
        "preset": {"type": "string", "enum": ["1080p60", "1080p30", "720p60", "720p30"],
                   "description": "Perfil desejado; padrão 1080p60."},
        "monitor": {"type": "integer", "description": "Monitor começando em 1."},
        "audio": {"type": "boolean", "description": "Inclui o som do PC; padrão true."},
    },
    aviso="mexendo_na_tv", executar=_tv_compartilhar_tela_pc,
))


def _tv_parar_compartilhamento():
    resultado = _importar_tv().parar_compartilhamento_tela()
    return consulta(resultado.get("mensagem", "Compartilhamento encerrado.")) if resultado.get("ok") else recusa(
        resultado.get("mensagem", "ERRO: não consegui encerrar o compartilhamento."))


registrar(Ferramenta(
    nome="parar_compartilhamento_tv",
    descricao="Encerra o compartilhamento ao vivo da tela do PC que está aberto na TV.",
    propriedades={}, aviso="mexendo_na_tv", executar=lambda: _tv_parar_compartilhamento(),
))


def _tv_configurar_companion(token: str, alvo: str = ""):
    resultado = _importar_tv().salvar_token_companion(token, alvo)
    return (ResultadoFerramenta(resultado["mensagem"], ok=True, mudou=True)
            if resultado.get("ok") else recusa(resultado["mensagem"]))


registrar(Ferramenta(
    nome="configurar_emily_tv",
    descricao=("Valida na TV e salva de verdade o token mostrado pelo app companheiro Emily TV. "
               "Use obrigatoriamente quando o Vitor pedir para configurar, salvar ou associar "
               "esse token à TV; não basta responder que configurou."),
    propriedades={"token": {"type": "string", "description": "Token exato mostrado na TV ou lido do anexo, sem alterar caracteres."},
                  "alvo": {"type": "string", "description": "Nome, id ou IP; vazio usa a TV ativa."}},
    obrigatorios=["token"], aviso="mexendo_na_tv", executar=_tv_configurar_companion,
))


def _tv_apps_instalados(incluir_sistema: bool = True):
    resultado = _importar_tv().listar_apps_instalados(incluir_sistema)
    if not resultado.get("ok"):
        return recusa(resultado.get("mensagem", "ERRO: falha ao listar apps da TV"))
    apps = resultado.get("apps", [])
    linhas = [f"{len(apps)} aplicativo(s) disponível(is) na TV:"]
    linhas += [f"- {a.get('name')} ({a.get('package')})" +
               (" [sistema]" if a.get("system") else "") for a in apps]
    return consulta("\n".join(linhas))


registrar(Ferramenta(
    nome="apps_instalados_tv",
    descricao="Lista os aplicativos realmente instalados e disponíveis na TV ativa, com nome e pacote.",
    propriedades={"incluir_sistema": {"type": "boolean", "description": "Inclui apps de sistema; padrão true."}},
    aviso="mexendo_na_tv", executar=_tv_apps_instalados,
))


def _tv_abrir_instalado(app: str):
    resultado = _importar_tv().abrir_app_instalado(app)
    if not resultado.get("ok"):
        return recusa(resultado.get("mensagem", "ERRO: app não encontrado"))
    aberto = resultado.get("app", {})
    return consulta(f"{aberto.get('name', app)} aberto na TV ({aberto.get('package', '')}).")


registrar(Ferramenta(
    nome="abrir_app_instalado_tv",
    descricao="Abre qualquer aplicativo instalado na TV pelo nome exibido ou pacote.",
    propriedades={"app": {"type": "string", "description": "Nome ou pacote do aplicativo."}},
    obrigatorios=["app"], aviso="mexendo_na_tv", executar=_tv_abrir_instalado,
))


def _tv_tocar_cloud(busca: str = "", item_id: str = "", posicao_segundos: int = 0,
                    velocidade: float = 1.0):
    from emily_cloud import core, service
    item = core.detalhes(item_id) if item_id else None
    if item is None:
        candidatos = [i for i in core.buscar(busca) if service.categoria(i) == "video"]
        if not candidatos:
            return recusa(f"Não achei vídeo chamado '{busca}' na Emily Cloud.")
        exato = (busca or "").strip().casefold()
        candidatos.sort(key=lambda i: (
            0 if i.get("nome", "").casefold() == exato else
            1 if exato in i.get("nome", "").casefold() else 2,
            -float(i.get("alterado_em", i.get("criado_em", 0)) or 0),
        ))
        item = candidatos[0]
    if service.categoria(item) != "video":
        return recusa(f"'{item.get('nome', 'Item')}' não é um vídeo da Emily Cloud.")

    # O endpoint /cloud/content implementa Range, essencial pra seek instantâneo.
    # Nunca passe localhost à TV: descubra o IP LAN do PC pela rota até a TV.
    import socket
    base = str(os.getenv("EMILY_GATEWAY_URL", "")).rstrip("/")
    if not base:
        tv_ativa = _importar_tv().dispositivo_ativo() or {}
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((tv_ativa.get("ip", "8.8.8.8"), 80))
                ip_pc = sock.getsockname()[0]
        except OSError:
            return recusa("Não consegui descobrir o endereço LAN do PC para a TV.")
        base = f"http://{ip_pc}:{int(os.getenv('EMILY_GATEWAY_PORTA', '5000'))}"
    token = str(os.getenv("EMILY_PONTE_TOKEN", ""))
    url = f"{base}/cloud/content/{item['id']}"
    resultado = _importar_tv().tocar_video_cloud(
        url, item.get("nome", "Emily Cloud"), token,
        posicao_segundos, velocidade)
    if not resultado.get("ok"):
        return recusa(resultado.get("mensagem", "ERRO: player da TV indisponível"))
    return consulta(f"Reproduzindo '{item['nome']}' da Emily Cloud na TV.")


registrar(Ferramenta(
    nome="tocar_video_cloud_tv",
    descricao=("Busca e reproduz um vídeo da Emily Cloud no player cinematográfico "
               "da TV em tela cheia e qualidade original. Aceita nome ou item_id. "
               "Depois de nuvem_guardar_arquivo, use o ID retornado para salvar e "
               "tocar na TV na mesma tarefa."),
    propriedades={
        "busca": {"type": "string", "description": "Nome do vídeo."},
        "item_id": {"type": "string", "description": "ID exato, se conhecido."},
        "posicao_segundos": {"type": "integer", "description": "Segundo inicial."},
        "velocidade": {"type": "number", "description": "0.25 a 2.0."},
    }, aviso="mexendo_na_tv", executar=_tv_tocar_cloud,
))


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — DISCORD: a Emily local mexendo no Discord a pedido do Vitor
#
# A ponte que executa vive no discord_bot.py (só lá existe o client vivo).
# São grupo "geral" de propósito: o Vitor pede isso FALANDO com a Emily dele,
# no PC — é ele comandando, não alguém no chat do servidor pedindo por conta
# própria. As ações de chat não são destrutivas, mas a Emily deve confirmar
# mensagem delicada antes de mandar, como sempre faz.
# ═════════════════════════════════════════════════════════════════


def _discord_bot():
    import discord_bot
    return discord_bot


registrar(Ferramenta(
    nome="ler_chat_discord",
    descricao=(
        "Lê as últimas mensagens de um canal do Discord do Vitor. Use quando "
        "ele pedir pra você olhar/resumir o chat ('olha o chat de tal', 'o "
        "que rolou no geral?', 'o que o Ryan disse?'). Depois de ler, resuma "
        "ou comente no seu jeito. Se não souber o canal, use "
        "ver_canais_discord primeiro."
    ),
    propriedades={
        "canal": {"type": "string",
                  "description": "Nome do canal (ex.: 'geral'). Pode ficar vazio se houver só um servidor."},
        "servidor": {"type": "string",
                     "description": "Nome do servidor, se ele disse qual. Vazio = procura em todos."},
        "quantidade": {"type": "integer",
                       "description": "Quantas mensagens ler (padrão 20, máximo 50)."},
    },
    aviso="lendo_pagina",
    executar=lambda canal="", servidor="", quantidade=20: _discord_bot(
    ).ler_chat_discord(canal=canal, servidor=servidor,
                       quantidade=int(quantidade or 20)),
))

registrar(Ferramenta(
    nome="ver_canais_discord",
    descricao=(
        "Lista os servidores e canais de texto do Discord onde você está. "
        "Use antes de ler ou mandar mensagem quando o Vitor não disse "
        "exatamente onde, ou quando ler_chat_discord não achou o canal."
    ),
    propriedades={
        "servidor": {"type": "string",
                     "description": "Nome de um servidor específico. Vazio = lista todos."},
    },
    aviso="lendo_pagina",
    executar=lambda servidor="": _discord_bot().ver_canais(servidor),
))

registrar(Ferramenta(
    nome="mandar_mensagem_discord",
    descricao=(
        "Manda uma mensagem SUA num canal do Discord, no seu estilo. Use "
        "quando o Vitor pedir pra você mandar/recado/anunciar algo num "
        "canal ('manda lá no geral que o servidor vai reiniciar'). Escreva "
        "a mensagem já no seu jeito — ele pediu PRA VOCÊ mandar. Mensagem "
        "delicada ou pública demais, confirme com ele antes. "
        "REGRA DE ESTILO: a mensagem vai PRO DISCORD, então escreva com a "
        "sua personalidade de Discord (curta, informal, abreviações tipo "
        "'vc'/'pq', sem pontuação formal, igual alguém do servidor) "
        "MESMO que esta conversa esteja acontecendo no chat local, fora "
        "do Discord. Só escreva palavra por palavra exatamente como o "
        "Vitor ditar se ele mandar isso explicitamente."
    ),
    propriedades={
        "mensagem": {"type": "string",
                     "description": "A mensagem, no estilo de Discord — curta e informal, mesmo vindo do chat local"},
        "canal": {"type": "string", "description": "Nome do canal (ex.: 'geral')"},
        "servidor": {"type": "string",
                     "description": "Nome do servidor, se ele disse qual"},
    },
    obrigatorios=["mensagem"],
    aviso="abrir_app",
    executar=lambda mensagem, canal="", servidor="": _discord_bot(
    ).mandar_mensagem_discord(canal=canal, mensagem=mensagem,
                              servidor=servidor),
))

registrar(Ferramenta(
    nome="responder_mensagem_discord",
    descricao=(
        "RESPONDE (reply) a última mensagem de uma pessoa num canal do "
        "Discord. Use quando o Vitor pedir pra responder alguém que falou "
        "lá ('responde o Ryan lá no geral', 'contesta aquele cara'). Se você "
        "não sabe o que a pessoa disse, use ler_chat_discord primeiro, "
        "depois responda aqui no seu estilo. "
        "REGRA DE ESTILO: a resposta vai PRO DISCORD, então escreva com a "
        "sua personalidade de Discord (curta, informal, abreviações, sem "
        "pontuação formal) MESMO que esta conversa esteja no chat local. "
        "Só escreva exatamente como o Vitor ditar se ele mandar isso "
        "explicitamente."
    ),
    propriedades={
        "autor": {"type": "string",
                  "description": "Nome da pessoa que você vai responder"},
        "resposta": {"type": "string",
                     "description": "O que você vai responder, no estilo de Discord"},
        "canal": {"type": "string", "description": "Nome do canal"},
        "servidor": {"type": "string",
                     "description": "Nome do servidor, se ele disse qual"},
    },
    obrigatorios=["autor", "resposta"],
    aviso="abrir_app",
    executar=lambda autor, resposta, canal="", servidor="": _discord_bot(
    ).responder_mensagem_discord(autor=autor, resposta=resposta,
                                 canal=canal, servidor=servidor),
))

registrar(Ferramenta(
    nome="mandar_dm_discord",
    descricao=(
        "Manda uma mensagem no DIRECT de uma pessoa do Discord. Você procura "
        "pelo nome entre os contatos que enxerga (quem compartilha servidor "
        "com você e quem já te mandou direct). ATENÇÃO: se achar mais de uma "
        "pessoa com o mesmo nome, a ferramenta DEVOLVE a lista de nicks — "
        "mostre pro Vitor, pergunte qual é a certa, e chame de novo "
        "passando nome_exato. NUNCA chute entre dois nomes iguais. "
        "REGRA DE ESTILO: a mensagem vai PRO DISCORD, então escreva com a "
        "sua personalidade de Discord (curta, informal, abreviações tipo "
        "'vc'/'pq', sem pontuação formal) MESMO que esta conversa esteja "
        "no chat local. Só escreva palavra por palavra exatamente como o "
        "Vitor ditar se ele mandar isso explicitamente."
    ),
    propriedades={
        "pessoa": {"type": "string",
                   "description": "Nome da pessoa, como o Vitor falou"},
        "mensagem": {"type": "string",
                     "description": "A mensagem, no estilo de Discord — curta e informal, mesmo vindo do chat local"},
        "nome_exato": {"type": "string",
                       "description": "O nick exato — só depois de o Vitor confirmar em caso de nomes repetidos"},
    },
    obrigatorios=["pessoa", "mensagem"],
    aviso="abrir_app",
    executar=lambda pessoa, mensagem, nome_exato="": _discord_bot(
    ).mandar_dm_discord(pessoa=pessoa, mensagem=mensagem,
                        nome_exato=nome_exato),
))


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — MÚSICA
# ═════════════════════════════════════════════════════════════════

registrar(Ferramenta(
    nome="tocar_musica",
    descricao=(
        "ABRE uma música, álbum ou artista no YouTube, no NAVEGADOR do Vitor "
        "(fora da interface). Use SOMENTE quando ele pedir explicitamente pra "
        "abrir no navegador, abrir no YouTube ou abrir em outra aba. Se ele só "
        "pedir pra tocar/colocar/ouvir uma música SEM mencionar navegador, use "
        "player_tocar (toca no Emily Music da interface). Pra pausar, pular ou "
        "mexer no volume do que JÁ está tocando, é controle_musica."
    ),
    propriedades={
        "musica": {"type": "string",
                   "description": ("Nome da música, álbum ou playlist. Se ele só "
                                   "disse o artista, repita o nome dele aqui.")},
        "artista": {"type": "string",
                    "description": "Artista, quando ele disser qual"},
    },
    obrigatorios=["musica"],
    executar=lambda musica, artista=None: _automacao(
        "tocar_musica", musica=musica, artista=artista),
))

registrar(Ferramenta(
    nome="controle_musica",
    descricao=(
        "Mexe no que JÁ está tocando FORA da interface (Spotify, YouTube no "
        "navegador, VLC...) usando as teclas de mídia do Windows. Use quando o "
        "Vitor pedir pra pausar, pular, voltar ou mexer no volume de um player "
        "externo. Pra controlar o Emily Music DA INTERFACE, use player_* "
        "(player_pausar_ou_tocar, player_proxima, player_anterior, player_volume)."
    ),
    propriedades={
        "controle": {
            "type": "string",
            "enum": ["pausar", "retomar", "proxima", "anterior", "volume"],
            "description": "Qual ação. 'volume' exige o campo valor.",
        },
        "valor": {"type": "string", "description": "Para volume: número de 0 a 100"},
    },
    obrigatorios=["controle"],
    executar=lambda controle, valor=None: _automacao(
        "controle_musica", controle=controle, valor=valor),
))

# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — MUSIC PLAYER DA INTERFACE (player_*)
#
# Estas controlam o Emily Music que vive na JANELA da Emily (o áudio roda
# no iframe do YouTube dentro da interface). Diferente de tocar_musica /
# controle_musica, que ABREM o YouTube no navegador. A ponte pro player é o
# handler 'comando_player', registrado pelo main.py.
# ═════════════════════════════════════════════════════════════════

def _music_player():
    import music_player
    return music_player


def _comando_player(acao: str, **dados) -> str:
    """Manda uma ação pro player da interface via handler do main.py."""
    return _chamar_handler("comando_player", acao=acao, **dados)


def _buscar_e_adicionar_musica(musica: str, artista: str = "",
                               playlist: str = "") -> dict:
    """Busca no YouTube, adiciona à playlist e devolve {ok, erro, item}."""
    mp = _music_player()
    query = f"{musica} {artista}".strip() if artista else musica
    previas = mp.buscar_preview(query, limite=1)
    if not previas:
        return {"ok": False, "erro": f"Não achei '{query}' no YouTube."}
    item = previas[0]
    try:
        import modo_demo
        if modo_demo.ativo():
            if playlist:
                modo_demo.playlist_selecionar(playlist)
            if not modo_demo.playlist_adicionar(item):
                return {"ok": False, "erro": "Não consegui adicionar na playlist demonstrativa."}
            return {"ok": True, "item": item}
    except Exception:
        pass
    if playlist:
        if not mp.adicionar(item, nome_playlist=playlist):
            return {"ok": False,
                    "erro": f"Não consegui adicionar na playlist '{playlist}'."}
    else:
        if not mp.adicionar(item):
            return {"ok": False, "erro": "Não consegui adicionar na playlist ativa."}
    return {"ok": True, "item": item}


registrar(Ferramenta(
    nome="player_tocar",
    descricao=(
        "Busca uma música no YouTube, adiciona à playlist ativa do Emily Music "
        "da interface e começa a tocar AQUI no player. Use quando o Vitor pedir "
        "pra tocar, colocar ou ouvir uma música. Pra abrir no navegador do "
        "YouTube (fora da interface), é tocar_musica."
    ),
    propriedades={
        "musica": {"type": "string",
                   "description": "Nome da música, artista ou o que ele quiser ouvir"},
        "artista": {"type": "string",
                    "description": "Artista, quando ele disser qual"},
    },
    obrigatorios=["musica"],
    aviso="player_tocar",
    executar=lambda musica, artista=None: _buscar_e_tocar(musica, artista),
))


def _buscar_e_tocar(musica: str, artista: str = "") -> str:
    r = _buscar_e_adicionar_musica(musica, artista or "")
    if not r["ok"]:
        return r["erro"]
    item = r["item"]
    _comando_player("tocar", video_id=item["video_id"])
    return f"Tocando '{item['titulo']}' no player, Vitor!"


registrar(Ferramenta(
    nome="player_pausar_ou_tocar",
    descricao=(
        "Alterna entre tocar e pausar o que está tocando no Emily Music da "
        "interface. Use pra 'pausa', 'para', 'continua', 'volta a tocar'. "
        "Não começa música nova — pra isso é player_tocar."
    ),
    propriedades={},
    aviso="player_tocar",
    executar=lambda: _comando_player("play_pause"),
))

registrar(Ferramenta(
    nome="player_proxima",
    descricao=(
        "Pula pra próxima música da playlist no Emily Music da interface. "
        "Use pra 'próxima', 'passa pra frente', 'skip'."
    ),
    propriedades={},
    aviso="player_tocar",
    executar=lambda: _comando_player("proxima"),
))

registrar(Ferramenta(
    nome="player_anterior",
    descricao=(
        "Volta pra música anterior no Emily Music da interface. "
        "Use pra 'volta', 'música anterior', 'toca a de trás'."
    ),
    propriedades={},
    aviso="player_tocar",
    executar=lambda: _comando_player("anterior"),
))

registrar(Ferramenta(
    nome="player_volume",
    descricao=(
        "Define o volume do Emily Music da interface (0 a 100). "
        "Use pra 'volume 50', 'aumenta o volume', 'diminui', 'muda'."
    ),
    propriedades={
        "valor": {"type": "number",
                  "description": "Volume de 0 a 100. Pra aumentar/diminuir, "
                                 "some/subtraia ~15 do atual."},
    },
    obrigatorios=["valor"],
    aviso="player_tocar",
    executar=lambda valor: _comando_player("volume", valor=valor),
))

registrar(Ferramenta(
    nome="player_loop",
    descricao=(
        "Alterna o modo de repetição do Emily Music: sem repetir → repete a "
        "playlist → repete a música atual. Cada uso avança um modo. "
        "Use pra 'deixa em loop', 'repete', 'repetir playlist'."
    ),
    propriedades={},
    aviso="player_tocar",
    executar=lambda: _comando_player("loop"),
))

registrar(Ferramenta(
    nome="player_aleatorio",
    descricao=(
        "Liga ou desliga o modo aleatório do Emily Music da interface. "
        "Use pra 'toca no aleatório', 'embaralha', 'desliga o aleatório'."
    ),
    propriedades={},
    aviso="player_tocar",
    executar=lambda: _comando_player("aleatorio"),
))

# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — PLAYLISTS DO MUSIC PLAYER
# Estas mexem nas playlists que ficam salvas (music_player.py), sem precisar
# de ponte pro JS — o player re-lê sozinho quando abrir o modal.
# ═════════════════════════════════════════════════════════════════

registrar(Ferramenta(
    nome="playlist_criar",
    descricao=(
        "Cria uma playlist nova no Emily Music da interface. "
        "Use pra 'cria uma playlist Favoritas', 'faz uma playlist de treino'."
    ),
    propriedades={
        "nome": {"type": "string", "description": "Nome da playlist nova"},
    },
    obrigatorios=["nome"],
    aviso="player_tocar",
    executar=lambda nome: _criar_playlist(nome),
))


def _criar_playlist(nome: str) -> str:
    mp = _music_player()
    if not nome or not nome.strip():
        return "Me diz o nome da playlist, Vitor!"
    if mp.criar_playlist(nome):
        return f"Playlist '{nome}' criada, Vitor!"
    return f"Não consegui criar a playlist '{nome}' (já existe ou chegou no limite)."


registrar(Ferramenta(
    nome="playlist_adicionar",
    descricao=(
        "Busca uma música no YouTube e adiciona a uma playlist do Emily Music "
        "da interface (a ativa, se não disser qual). NÃO começa a tocar — só "
        "guarda na playlist. Pra tocar já, é player_tocar."
    ),
    propriedades={
        "musica": {"type": "string", "description": "Nome da música"},
        "artista": {"type": "string", "description": "Artista, quando ele disser"},
        "playlist": {"type": "string",
                     "description": "Nome da playlist. Se não disser, vai na ativa"},
    },
    obrigatorios=["musica"],
    aviso="player_tocar",
    executar=lambda musica, artista=None, playlist=None: _adicionar_playlist(
        musica, artista, playlist),
))


def _adicionar_playlist(musica: str, artista: str = "", playlist: str = "") -> str:
    r = _buscar_e_adicionar_musica(musica, artista or "", playlist or "")
    if not r["ok"]:
        return r["erro"]
    item = r["item"]
    onde = f" na playlist '{playlist}'" if playlist else " na playlist ativa"
    return f"Adicionei '{item['titulo']}'{onde}, Vitor!"


registrar(Ferramenta(
    nome="playlist_remover",
    descricao=(
        "Remove uma música da playlist do Emily Music. O Vitor diz o nome da "
        "música (ou cola o link); a Emily acha e tira da playlist ativa. "
        "Use pra 'tira essa música da playlist', 'remove X'."
    ),
    propriedades={
        "musica": {"type": "string",
                   "description": "Nome da música ou link do YouTube pra remover"},
        "playlist": {"type": "string",
                     "description": "Playlist de onde remover. Se não disser, a ativa"},
    },
    obrigatorios=["musica"],
    aviso="player_tocar",
    executar=lambda musica, playlist=None: _remover_da_playlist(musica, playlist),
))


def _remover_da_playlist(musica: str, playlist: str = "") -> str:
    mp = _music_player()
    vid = mp.video_id_de(musica)
    nome = playlist or mp.playlist_ativa()
    musicas = mp.listar_playlists()["playlists"].get(nome, {}).get("musicas", [])
    if not vid:
        alvo = musica.strip().lower()
        achado = next((m for m in musicas
                       if alvo in (m.get("titulo") or "").lower()), None)
        if not achado:
            return f"Não achei '{musica}' na playlist '{nome}'."
        vid = achado["video_id"]
    if mp.remover(vid, nome_playlist=nome):
        return f"Removi '{musica}' da playlist '{nome}', Vitor!"
    return f"Não consegui remover '{musica}'."


registrar(Ferramenta(
    nome="playlist_favoritar",
    descricao=(
        "Favorita ou desfavorita uma música do Emily Music. Use pra 'favorita "
        "essa', 'curti essa música', 'tira dos favoritos'. O Vitor pode dar o "
        "nome da música ou o link."
    ),
    propriedades={
        "musica": {"type": "string", "description": "Nome ou link da música"},
        "favorito": {"type": "boolean",
                     "description": "True pra favoritar, False pra desfavoritar"},
    },
    obrigatorios=["musica"],
    aviso="player_tocar",
    executar=lambda musica, favorito=True: _favoritar(musica, bool(favorito)),
))


def _favoritar(musica: str, favorito: bool) -> str:
    mp = _music_player()
    vid = mp.video_id_de(musica)
    if not vid:
        # Procura em todas as playlists pelo nome
        dados = mp.listar_playlists()
        achado = None
        alvo = musica.strip().lower()
        for pl in dados["playlists"].values():
            for m in pl.get("musicas", []):
                if alvo in (m.get("titulo") or "").lower():
                    achado = m
                    break
            if achado:
                break
        if not achado:
            return f"Não achei '{musica}' nas playlists."
        vid = achado["video_id"]
    mp.favoritar(vid, favorito)
    return f"{'Favoritada' if favorito else 'Tirei dos favoritos'} '{musica}', Vitor!"


registrar(Ferramenta(
    nome="playlist_renomear",
    descricao=(
        "Renomeia uma playlist do Emily Music da interface. "
        "Use pra 'renomeia a playlist Treino pra Academia'."
    ),
    propriedades={
        "nome_atual": {"type": "string", "description": "Nome atual da playlist"},
        "nome_novo": {"type": "string", "description": "Nome novo"},
    },
    obrigatorios=["nome_atual", "nome_novo"],
    aviso="player_tocar",
    executar=lambda nome_atual, nome_novo: _renomear_playlist(nome_atual, nome_novo),
))


def _renomear_playlist(nome_atual: str, nome_novo: str) -> str:
    mp = _music_player()
    if mp.renomear_playlist(nome_atual, nome_novo):
        return f"Playlist renomeada de '{nome_atual}' pra '{nome_novo}', Vitor!"
    return f"Não consegui renomear '{nome_atual}' (existe uma com esse nome novo?)."


registrar(Ferramenta(
    nome="playlist_apagar",
    descricao=(
        "Apaga uma playlist do Emily Music da interface (a 'default' não se "
        "apaga). Use pra 'apaga a playlist X', 'remove essa playlist'."
    ),
    propriedades={
        "nome": {"type": "string", "description": "Nome da playlist a apagar"},
    },
    obrigatorios=["nome"],
    aviso="player_tocar",
    executar=lambda nome: _apagar_playlist(nome),
))


def _apagar_playlist(nome: str) -> str:
    mp = _music_player()
    if mp.apagar_playlist(nome):
        return f"Playlist '{nome}' apagada, Vitor!"
    return f"Não consegui apagar a playlist '{nome}' (a default não apaga, ou ela não existe)."


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — CONSULTA DO ACERVO DO USUÁRIO (player_* consulta)
# A Emily precisa SABER o que o Vitor tem salvo antes de tocar — se ele pedir
# "toca minha playlist de anime", tem que achar A playlist dele, não uma
# aleatória do YouTube. Estas duas dão o mapa do acervo.
# ═════════════════════════════════════════════════════════════════

registrar(Ferramenta(
    nome="player_minhas_playlists",
    descricao=(
        "Lista TODAS as playlists que o Vitor criou no Emily Music da "
        "interface, com quantas músicas cada uma tem, a playlist ativa e os "
        "favoritos. Use ANTES de player_tocar quando ele disser 'toca minha "
        "playlist X' ou 'toca meus favoritos' — pra achar a playlist DELE, não "
        "uma aleatória do YouTube. Não toca nada, só consulta."
    ),
    propriedades={},
    aviso="player_tocar",
    executar=lambda: _minhas_playlists(),
))


def _minhas_playlists() -> str:
    mp = _music_player()
    dados = mp.listar_playlists()
    playlists = dados.get("playlists", {})
    favoritos = dados.get("favoritos", {})
    ativa = dados.get("ativa", "default")

    if not playlists:
        return "Você ainda não tem playlists salvas, Vitor."

    linhas = []
    for nome, pl in playlists.items():
        qtd = pl.get("quantidade", 0)
        marcador = " (ativa)" if nome == ativa else ""
        linhas.append(f"- {nome}: {qtd} música{'s' if qtd != 1 else ''}{marcador}")
    parte_fav = ""
    if favoritos:
        n = len(favoritos)
        parte_fav = f"\nFavoritos: {n} música{'s' if n != 1 else ''} curtida{'s' if n != 1 else ''}."

    return ("Suas playlists:\n" + "\n".join(linhas) + parte_fav)


registrar(Ferramenta(
    nome="player_playlist_info",
    descricao=(
        "Mostra as músicas de UMA playlist específica do Vitor (ou as músicas "
        "favoritas). Use pra saber o que tem dentro da playlist antes de tocar, "
        "ou quando ele perguntar 'o que tem na minha playlist X'."
    ),
    propriedades={
        "nome": {"type": "string",
                 "description": "Nome da playlist. Use 'favoritos' (ou 'curtidas') "
                                "pra ver as músicas favoritas"},
    },
    obrigatorios=["nome"],
    aviso="player_tocar",
    executar=lambda nome: _playlist_info(nome),
))


def _playlist_info(nome: str) -> str:
    mp = _music_player()
    dados = mp.listar_playlists()
    nome = (nome or "").strip().lower()
    playlists = dados.get("playlists", {})

    # Favoritos/curtidas são tratados como uma "playlist" especial.
    if nome in ("favoritos", "favoritas", "curtidas", "curtidos"):
        fav_ids = set(dados.get("favoritos", {}).keys())
        musicas = []
        for pl in playlists.values():
            for m in pl.get("musicas", []):
                if m.get("video_id") in fav_ids:
                    musicas.append(m)
        if not musicas:
            return "Você ainda não tem músicas favoritas, Vitor."
        return "Suas favoritas:\n" + "\n".join(
            f"- {m.get('titulo', 'Sem título')}" for m in musicas)

    # Acha a playlist pelo nome (ignorando caixa).
    chave = None
    for cand in playlists:
        if cand.strip().lower() == nome:
            chave = cand
            break
    if chave is None:
        return (f"Não achei uma playlist chamada '{nome}'. Suas playlists: "
                + ", ".join(playlists.keys()) + ".")
    musicas = playlists[chave].get("musicas", [])
    if not musicas:
        return f"A playlist '{chave}' está vazia."
    return f"Playlist '{chave}':\n" + "\n".join(
        f"- {m.get('titulo', 'Sem título')}" for m in musicas)


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — INTERNET E TELA
# ═════════════════════════════════════════════════════════════════

def _pesquisar(consulta: str, profundidade: str = "normal") -> ResultadoFerramenta:
    import pesquisa
    resultado = pesquisa.pesquisar(consulta, profundidade=profundidade)
    if not resultado or not resultado.startswith("PESQUISA WEB INVISÍVEL"):
        return recusa(
            (resultado or "A pesquisa não retornou fontes.")
            + " Não afirme fatos atuais sem fontes; diga que não conseguiu verificar."
        )
    # Mantém espaço para várias fontes sem deixar uma pesquisa dominar todo o
    # contexto da conversa. O próprio pesquisa.py já limita cada página.
    return ResultadoFerramenta(texto=resultado[:26000], ok=True, mudou=False)


registrar(Ferramenta(
    nome="pesquisar_internet",
    descricao=(
        "Pesquisa na internet e devolve o conteúdo encontrado. Use quando "
        "precisar de informação atual que você não tem: preço, notícia, "
        "resultado de jogo, versão de software, qualquer coisa que mude com o "
        "tempo. Também use quando o Vitor pedir para pesquisar, buscar ou "
        "procurar algo. Escolha a profundidade conforme o pedido: 'rapida' "
        "pra algo simples (uma informação, preço, definição), 'normal' pro "
        "padrão, e 'profunda' quando ele pedir algo complexo, comparar várias "
        "coisas, ou quiser bastante detalhe (com teto maior de fontes, mas "
        "parando cedo se a evidência já for suficiente)."
        " A pesquisa comum roda totalmente em segundo plano: não abre Brave, "
        "Chrome, janela ou aba e não precisa da extensão. Compare as fontes "
        "coletadas, priorize fontes oficiais para versões atuais e sinalize "
        "divergências ou evidência insuficiente. Se não houver fontes úteis, "
        "diga que não conseguiu verificar; não responda de memória."
    ),
    propriedades={
        "consulta": {
            "type": "string",
            "description": "O que pesquisar. Escreva uma boa consulta de busca, não a frase do Vitor.",
        },
        "profundidade": {
            "type": "string",
            "enum": ["rapida", "normal", "profunda"],
            "description": "Teto, não meta fixa: rapida (até 5 fontes), normal (até 8), profunda (até 12 fontes e consultas extras só se faltar evidência).",
        },
    },
    obrigatorios=["consulta"],
    aviso="pesquisar",
    somente_leitura=True,
    executar=lambda consulta, profundidade="normal": _pesquisar(consulta, profundidade),
))


def _ver_tela(pergunta: Optional[str] = None) -> str:
    import modelo
    import visao

    imagem = visao.capturar_tela()
    if not imagem:
        return "Não consegui capturar a tela agora."
    if pergunta:
        resposta = modelo.analisar_tela_com_pergunta(imagem, pergunta)
    else:
        resposta = modelo.analisar_tela(imagem)
    return resposta or "Não consegui interpretar o que está na tela."


registrar(Ferramenta(
    nome="ver_tela",
    descricao=(
        "Captura a tela do Vitor AGORA e analisa o que está nela. Use quando "
        "ele pedir para você olhar a tela, ou quando falar de um erro, código, "
        "imagem ou janela sem explicar o conteúdo, indicando que você precisa "
        "ver. NÃO use para saber a hora nem para pesquisar na internet."
    ),
    propriedades={
        "pergunta": {
            "type": "string",
            "description": "O que olhar especificamente na tela. Opcional.",
        }
    },
    aviso="analisando_tela",
    somente_leitura=True,
    executar=_ver_tela,
))


def _tv_configurar_companion(token: str, alvo: str = ""):
    resultado = _importar_tv().salvar_token_companion(token, alvo)
    return (ResultadoFerramenta(resultado["mensagem"], ok=True, mudou=True)
            if resultado.get("ok") else recusa(resultado["mensagem"]))


registrar(Ferramenta(
    nome="configurar_emily_tv",
    descricao=("Valida na TV e salva de verdade o token mostrado pelo app companheiro Emily TV instalado na televisão. "
               "Use obrigatoriamente quando o Vitor pedir para configurar, salvar ou associar esse token; "
               "não responda que configurou sem chamar esta ferramenta. Faça uma vez por TV para liberar "
               "listagem e abertura de qualquer app instalado."),
    propriedades={
        "token": {"type": "string", "description": "Token exato mostrado na tela ou lido do anexo, sem alterar caracteres."},
        "alvo": {"type": "string", "description": "Nome, id ou IP da TV; vazio usa a ativa/única."},
    },
    obrigatorios=["token"], aviso="mexendo_na_tv", executar=_tv_configurar_companion,
))


def _tv_apps_instalados(incluir_sistema: bool = True):
    resultado = _importar_tv().listar_apps_instalados(incluir_sistema)
    if not resultado.get("ok"):
        return recusa(resultado.get("mensagem", "ERRO: falha ao listar apps da TV"))
    apps = resultado.get("apps", [])
    linhas = [f"{len(apps)} aplicativo(s) disponível(is) na TV:"]
    linhas += [f"- {a.get('name')} ({a.get('package')})" +
               (" [sistema]" if a.get("system") else "") for a in apps]
    return consulta("\n".join(linhas))


registrar(Ferramenta(
    nome="apps_instalados_tv",
    descricao=("Lista os aplicativos realmente instalados e disponíveis na TV ativa, com nome e pacote. "
               "Use antes de abrir quando o nome exato for desconhecido."),
    propriedades={"incluir_sistema": {"type": "boolean", "description": "Inclui apps do sistema; padrão true."}},
    aviso="mexendo_na_tv", executar=_tv_apps_instalados,
))


def _tv_abrir_instalado(app: str):
    resultado = _importar_tv().abrir_app_instalado(app)
    if not resultado.get("ok"):
        return recusa(resultado.get("mensagem", "ERRO: app não encontrado"))
    aberto = resultado.get("app", {})
    return consulta(f"{aberto.get('name', app)} aberto na TV ({aberto.get('package', '')}).")


registrar(Ferramenta(
    nome="abrir_app_instalado_tv",
    descricao=("Abre qualquer aplicativo instalado na TV pelo nome exibido ou pacote, usando o app "
               "companheiro. Prefira esta ferramenta para apps fora do catálogo fixo."),
    propriedades={"app": {"type": "string", "description": "Nome ou pacote do aplicativo."}},
    obrigatorios=["app"], aviso="mexendo_na_tv", executar=_tv_abrir_instalado,
))


def _traduzir_tela(instrucao: str = "traduz o que está na tela") -> str:
    import modelo
    return modelo.traduzir_tela(instrucao) or "Não achei texto pra traduzir."


registrar(Ferramenta(
    nome="traduzir_tela",
    descricao=(
        "Lê um texto que está na tela e devolve traduzido pro português. Use "
        "quando o Vitor pedir pra traduzir o que está aparecendo, ou reclamar que "
        "está em inglês. Se ele quiser saber o que a tela MOSTRA (sem traduzir), "
        "é ver_tela."
    ),
    propriedades={
        "instrucao": {
            "type": "string",
            "description": "Que texto traduzir, ex: 'o primeiro parágrafo', 'tudo'",
        }
    },
    aviso="traduzir",
    executar=_traduzir_tela,
))


def _executar_na_tela(objetivo: str) -> str:
    import agente_ui
    import voz
    antes = agente_ui.estado_agente_ui()
    resposta = agente_ui.iniciar_agente_ui(objetivo, callback_falar=voz.falar)
    depois = agente_ui.estado_agente_ui()
    iniciou = bool(
        depois.get("objetivo") == (objetivo or "").strip()
        and depois.get("iniciado_em")
        and depois.get("iniciado_em") != antes.get("iniciado_em")
    )
    if not iniciou:
        return recusa(resposta or depois.get("erro") or "Não consegui iniciar o agente visual.")
    return (resposta or "Comecei a fazer isso na tela.") + (
        " O agente está trabalhando em segundo plano; não repita a ação."
    )


registrar(Ferramenta(
    nome="executar_na_tela",
    descricao=(
        "Assume o controle do mouse e teclado para executar uma tarefa de "
        "vários passos na tela. Use quando o Vitor quiser que você FAÇA algo "
        "que envolve navegar pela interface, clicar, preencher campos, ou "
        "abrir um programa E fazer algo dentro dele. O objetivo tem que ser "
        "concreto e completo, nunca 'faça o que eu disse'. "
        "Para configurar algo dentro de um programa, atravessar instaladores e "
        "assistentes gráficos, ou concluir uma instalação que exige passos manuais, "
        "esta é normalmente a opção MAIS CONFIÁVEL porque valida visualmente cada "
        "etapa. Ainda assim, prefira ferramenta específica ou executar_terminal "
        "quando eles concluírem a tarefa inteira sem interface. "
        "NÃO use para procurar arquivo ou pasta (use procurar_no_pc), nem para "
        "só abrir algo (use as ferramentas de abrir)."
    ),
    propriedades={
        "objetivo": {
            "type": "string",
            "description": "A tarefa completa e concreta, passo a passo se necessário",
        }
    },
    obrigatorios=["objetivo"],
    aviso="agente_ui_iniciando",
    executar=_executar_na_tela,
))

# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — MEMÓRIA E CONTEXTO LOCAL
# ═════════════════════════════════════════════════════════════════

def _guardar_fato(fato: str) -> str:
    import memoria
    novo = memoria.adicionar_fato(fato)
    return "Fato guardado na memória." if novo else "Já sabia disso, não guardei de novo."


registrar(Ferramenta(
    nome="guardar_fato",
    descricao=(
        "Guarda na memória de longo prazo um fato sobre o Vitor. Use quando ele "
        "disser para lembrar de algo, ou quando revelar uma preferência ou "
        "hábito que vale lembrar em conversas futuras."
    ),
    propriedades={
        "fato": {"type": "string", "description": "O fato, escrito de forma curta e clara"}
    },
    obrigatorios=["fato"],
    aviso="guardar_fato",
    executar=_guardar_fato,
))


def _esquecer_fato(fato: str) -> str:
    import memoria
    if memoria.remover_fato(fato):
        return "Fato removido da memória."
    fatos = memoria.listar_fatos()
    parecidos = [f for f in fatos if fato.lower()[:15] in f.lower()]
    if parecidos:
        return ("Não achei esse fato exato. Parecidos guardados: "
                + "; ".join(parecidos[:3]) + ". Confirme qual remover.")
    return "Não tenho esse fato guardado."


registrar(Ferramenta(
    nome="esquecer_fato",
    descricao=(
        "Remove um fato da memória de longo prazo. Use quando o Vitor pedir "
        "pra esquecer algo ou disser que uma informação guardada está errada. "
        "O texto tem que bater com o fato guardado; se não souber, use "
        "lembrar_fatos primeiro."
    ),
    propriedades={"fato": {"type": "string", "description": "O fato exato a remover"}},
    obrigatorios=["fato"],
    executar=_esquecer_fato,
))


def _ler_instrucoes() -> str:
    import modelo
    texto = modelo.ler_instrucoes_da_tela()
    if not texto or "SEM_INSTRUCOES" in texto:
        return "Não achei passos ou instruções claras na tela."
    return f"Instruções que estão na tela:\n{texto}"


registrar(Ferramenta(
    nome="ler_instrucoes_da_tela",
    descricao=(
        "Extrai a lista de passos ou instruções que está visível na tela, como "
        "um tutorial. Use quando o Vitor pedir pra você seguir ou entender um "
        "tutorial que está aberto. Depois de ler, se ele quiser que você "
        "execute, use executar_na_tela com os passos."
    ),
    propriedades={},
    aviso="analisando_tela",
    executar=_ler_instrucoes,
))


def _trocar_monitor(numero: int) -> str:
    import visao
    r = visao.trocar_monitor(numero)
    if isinstance(r, str):
        return r          # mensagem de erro já explicada
    monitores = visao.listar_monitores()
    detalhe = next((m for m in monitores if m["numero"] == r), None)
    if detalhe:
        return (f"Agora eu capturo o monitor {r} "
                f"({detalhe['largura']}x{detalhe['altura']}). "
                f"Olhe a tela de novo pra ver o conteúdo novo.")
    return f"Agora eu capturo o monitor {r}. Olhe a tela de novo."


registrar(Ferramenta(
    nome="trocar_monitor",
    descricao=(
        "Muda qual monitor você captura quando olha a tela. Use se o Vitor "
        "disser que você está olhando a tela errada."
    ),
    propriedades={"numero": {"type": "integer", "description": "Número do monitor, começando em 1"}},
    obrigatorios=["numero"],
    executar=_trocar_monitor,
))


def _lembrar_fatos() -> str:
    import memoria
    fatos = memoria.listar_fatos()
    if not fatos:
        return "A memória está vazia."
    return "Fatos guardados:\n" + "\n".join(f"- {f}" for f in fatos)


registrar(Ferramenta(
    nome="lembrar_fatos",
    descricao=(
        "Lista o que você tem guardado na memória sobre o Vitor. Use se ele "
        "perguntar do que você lembra."
    ),
    propriedades={},
    executar=_lembrar_fatos,
))


_DIAS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
         "sexta-feira", "sábado", "domingo")
_MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
          "agosto", "setembro", "outubro", "novembro", "dezembro")


def _agora() -> str:
    a = datetime.datetime.now()
    return (f"{_DIAS[a.weekday()]}, {a.day} de {_MESES[a.month - 1]} de {a.year}, "
            f"{a.hour:02d}:{a.minute:02d}")


registrar(Ferramenta(
    nome="hora_atual",
    descricao=(
        "Devolve a data e a hora de agora, do relógio do PC. Use sempre que a "
        "conversa depender de que dia ou que horas são. Não olhe a tela pra isso."
    ),
    propriedades={},
    executar=_agora,
))

# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — MODOS DA EMILY
#
# Estes mexem em estado global do main.py (threads, eventos, status da
# janela), então vão pelo registro de handlers. Se o main.py não registrar,
# a ferramenta responde que o recurso não está disponível, em vez de
# estourar exceção.
# ═════════════════════════════════════════════════════════════════

# Eram OITO ferramentas: ativar_modo_escrito, desativar_modo_escrito,
# ativar_modo_controle_tela, desativar_modo_controle_tela, e o mesmo par pro
# monitoramento de jogo e pra escuta do Discord.
#
# Oito portas pra quatro interruptores. Cada par só se distinguia pelo prefixo
# do nome, e as versões "desativar_" tinham descrição de 24 caracteres ("Desativa
# o modo escrito.") — o modelo tinha que inferir o contrato inteiro do nome.
#
# Agora é UMA ferramenta com dois argumentos. O despacho continua caindo nos
# MESMOS handlers que o main.py registra ("ativar_modo_escrito", etc.), então
# nada do outro lado mudou: quem some é a escolha entre oito nomes parecidos.
_MODOS = {
    "modo_escrito": (
        "modo escrito: em vez de responder, ela DIGITA o que o Vitor falar, "
        "no lugar onde o cursor está"),
    "modo_controle_tela": (
        "controle de tela: ela assume mouse e teclado e opera a interface por "
        "conta própria, olhando a tela"),
    "monitoramento_jogo": (
        "monitoramento de jogo: ela observa a tela enquanto ele joga e comenta "
        "quando acontece algo marcante"),
    "escuta_discord": (
        "escuta do Discord: ela passa a acompanhar o chat do servidor e "
        "responder por lá"),
}

# Aviso falado antes de ligar/desligar, quando existe. Só os dois modos que
# mexem no controle do PC têm — os outros são silenciosos de propósito.
_AVISO_MODO = {
    ("modo_escrito", True): "modo_escrito_on",
    ("modo_escrito", False): "modo_escrito_off",
    ("modo_controle_tela", True): "ativar_ui",
    ("modo_controle_tela", False): "desativar_ui",
}


def _aviso_do_modo(argumentos: dict) -> str:
    """A frase depende de QUAL modo e de ligar ou desligar."""
    modo = str((argumentos or {}).get("modo") or "")
    ligar = bool((argumentos or {}).get("ligar", True))
    return _AVISO_MODO.get((modo, ligar), "")


def _definir_modo(modo: str, ligar: bool = True) -> str:
    """
    Liga ou desliga um modo, despachando pro handler que o main.py registrou.

    Modo desconhecido devolve a lista do que existe em vez de falhar calado: se
    o modelo inventar um nome, ela precisa poder se corrigir na volta seguinte.
    """
    if modo not in _MODOS:
        return (f"Não existe o modo '{modo}'. Os que existem: "
                f"{', '.join(sorted(_MODOS))}.")
    prefixo = "ativar" if ligar else "desativar"
    return _chamar_handler(f"{prefixo}_{modo}")


_QUEBRA = chr(10)

_DESCRICAO_MODOS = _QUEBRA.join(
    f"- {nome}: {oque}" for nome, oque in _MODOS.items()
)

registrar(Ferramenta(
    nome="definir_modo",
    descricao=(
        "Liga ou desliga um dos modos de operação dela. Os modos são:"
        + _QUEBRA + _DESCRICAO_MODOS + _QUEBRA + _QUEBRA
        + "Use quando o Vitor pedir pra entrar ou sair de um desses. "
          "NÃO use pra fazer UMA coisa pontual: pra olhar a tela uma vez é "
          "ver_tela, e pra executar uma tarefa na tela e acabar é "
          "executar_na_tela."
    ),
    propriedades={
        "modo": {
            "type": "string",
            "enum": sorted(_MODOS),
            "description": "Qual modo mexer.",
        },
        "ligar": {
            "type": "boolean",
            "description": ("true pra ligar, false pra desligar. Se o Vitor "
                            "falou 'para', 'desliga', 'sai do', é false."),
        },
    },
    obrigatorios=["modo", "ligar"],
    aviso_dinamico=_aviso_do_modo,
    executar=_definir_modo,
))

def _assistir_tela(duracao_segundos: int = 120) -> str:
    return _chamar_handler("assistir_tela", duracao_segundos=int(duracao_segundos))

registrar(Ferramenta(
    nome="assistir_tela",
    descricao=(
        "Fica olhando a tela por um tempo e comentando sozinha o que acontecer. "
        "Use quando o Vitor pedir pra você ACOMPANHAR, ficar de olho ou assistir "
        "junto por um tempo. Três coisas parecidas e diferentes: pra olhar UMA vez "
        "agora é ver_tela; se ele estiver jogando e quiser comentário de jogo é "
        "ativar_monitoramento_jogo; pra parar isso aqui é parar_assistir_tela."
    ),
    propriedades={
        "duracao_segundos": {
            "type": "integer",
            "description": "Por quanto tempo olhar a tela, em segundos. Padrão: 120.",
        }
    },
    aviso="",
    executar=_assistir_tela,
))

def _parar_assistir_tela() -> str:
    return _chamar_handler("parar_assistir_tela")

registrar(Ferramenta(
    nome="parar_assistir_tela",
    descricao=(
        "Para de acompanhar a tela e encerra o que o assistir_tela começou. Use "
        "quando o Vitor falar pode parar, chega, para de olhar. Se o que está "
        "ligado é o monitoramento de JOGO, o desligamento é pelo definir_modo."
    ),
    propriedades={},
    aviso="",
    executar=_parar_assistir_tela,
))


# 
# CATÁLOGO DE ADMINISTRAÇÃO DO DISCORD
#
# Vive em ferramentas_discord.py porque é outro domínio e são 30+ ferramentas.
# A fábrica é passada por parâmetro em vez de o outro módulo importar este:
# assim a dependência é de mão única e não existe ciclo de importação.
#
# Falha aqui não pode derrubar o catálogo inteiro. Se o discord.py não estiver
# instalado, ou o módulo tiver um erro, a Emily continua abrindo pasta e lendo
# tela — só perde as ferramentas de servidor.
# ═════════════════════════════════════════════════════════════════

def _registrar_catalogo_discord() -> None:
    try:
        import ferramentas_discord
        quantas = ferramentas_discord.registrar_tudo(registrar, Ferramenta)
        _log(f"{quantas} ferramentas de administração do Discord registradas")
    except Exception as e:
        _log(f"catálogo do Discord não carregou ({type(e).__name__}: {e}); "
             f"as ferramentas de servidor ficam indisponíveis nesta sessão")


_registrar_catalogo_discord()


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO DA AUTONOMIA DELA
#
# Lembretes, o que ela reparou sozinha no servidor, regras e suporte. Entra no
# grupo 'discord' porque é onde essas ferramentas fazem sentido — ver a explicação
# no topo do ferramentas_vida.py.
# ═════════════════════════════════════════════════════════════════

def _registrar_catalogo_vida() -> None:
    try:
        import ferramentas_vida
        quantas = ferramentas_vida.registrar_tudo(registrar, Ferramenta)
        _log(f"{quantas} ferramentas de autonomia registradas")
    except Exception as e:
        _log(f"catálogo de autonomia não carregou ({type(e).__name__}: {e}); "
             f"ela continua respondendo, mas sem lembrete nem agenda")


_registrar_catalogo_vida()


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO DE CRIAÇÃO DE IMAGEM (GPT Image)
#
# Vive em ferramentas_imagem.py porque é outro domínio (API de imagem própria,
# com credenciais próprias no .env). A ferramenta entra no grupo 'geral' —
# criar imagem é habilidade de conversa, não precisa de abrir_ferramentas.
# Falha aqui (sem requests, sem dotenv) não derruba o catálogo inteiro, pelo
# mesmo motivo do Discord e da autonomia.
# ═════════════════════════════════════════════════════════════════

def _registrar_catalogo_imagem() -> None:
    try:
        import ferramentas_imagem
        quantas = ferramentas_imagem.registrar_tudo(registrar, Ferramenta)
        _log(f"{quantas} ferramenta de criação de imagem registrada")
    except Exception as e:
        _log(f"catálogo de imagem não carregou ({type(e).__name__}: {e}); "
             f"a Emily continua tudo, só sem criar imagens nesta sessão")


_registrar_catalogo_imagem()


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — GITHUB (sob demanda via abrir_ferramentas("github"))
# ═════════════════════════════════════════════════════════════════

def _registrar_catalogo_github():
    import github_api

    def _precisa_token() -> bool:
        return github_api.configurado()

    # ── Repositórios ────────────────────────────────────────────

    registrar(Ferramenta(
        nome="github_listar_repos",
        # No grupo 'geral' (sempre na mesa) de propósito: é a ferramenta de
        # GitHub mais pedida e custa só ~85 tokens. Assim o modelo chama direto
        # na primeira volta, sem gastar uma ida extra abrindo o domínio github.
        grupo="geral",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Lista os repositórios do Vitor no GitHub, do mais recente ao mais "
            "antigo. Use quando ele perguntar 'quais repositórios eu tenho', "
            "'mostra meus repos', 'quais projetos eu tenho no GitHub'. "
            "Para as demais ações do GitHub (ler/escrever arquivo, PR, issue, "
            "commit), chame abrir_ferramentas('github') antes."
        ),
        propriedades={},
        executar=lambda: github_api.listar_repos(),
    ))

    registrar(Ferramenta(
        nome="github_ver_repo",
        grupo="github",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Mostra detalhes de um repositório do GitHub: descrição, linguagem, "
            "stars, forks, data de criação, branch padrão, se é privado, URL. "
            "Use quando o Vitor pedir info sobre um repo específico."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo do repo (dono/nome). Ex: Vitor123/meu-projeto"},
        },
        obrigatorios=["repo"],
        executar=lambda repo: github_api.ver_repo(repo),
    ))

    registrar(Ferramenta(
        nome="github_criar_repo",
        grupo="github",
        descricao=(
            "Cria um repositório novo no GitHub do Vitor. Pede o nome, descrição "
            "e se é público ou privado. Use quando ele pedir pra criar um repo, "
            "repositório, ou projeto novo no GitHub."
        ),
        propriedades={
            "nome": {"type": "string", "description": "Nome do repositório"},
            "descricao": {"type": "string",
                          "description": "Descrição do repositório (opcional)"},
            "privado": {"type": "boolean",
                        "description": "True pra privado, False pra público (padrão)"},
        },
        obrigatorios=["nome"],
        aviso="github",
        executar=lambda nome, descricao="", privado=False: github_api.criar_repo(
            nome, descricao, bool(privado)),
    ))

    registrar(Ferramenta(
        nome="github_apagar_repo",
        grupo="github",
        destrutiva=True,
        descricao=(
            "Apaga um repositório INTEIRO do GitHub do Vitor (com todo o código, "
            "issues, PRs — sem volta). Use SOMENTE se ele pedir explicitamente "
            "pra deletar, apagar ou remover um repositório."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repo a apagar"},
        },
        obrigatorios=["repo"],
        aviso="github",
        executar=lambda repo: github_api.apagar_repo(repo),
    ))

    # ── Arquivos ────────────────────────────────────────────────

    registrar(Ferramenta(
        nome="github_listar_arquivos",
        grupo="github",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Lista o conteúdo de uma pasta ou raiz de um repositório do GitHub. "
            "Mostra pastas e arquivos. Use quando o Vitor perguntar 'o que tem "
            "no repo X', 'mostra os arquivos', 'quais arquivos tem em Y'."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "caminho": {"type": "string",
                        "description": "Caminho da pasta. Vazio = raiz do repo"},
            "ref": {"type": "string",
                    "description": "Branch ou tag. Vazio = branch padrão"},
        },
        obrigatorios=["repo"],
        executar=lambda repo, caminho="", ref="": github_api.listar_arquivos(
            repo, caminho, ref),
    ))

    registrar(Ferramenta(
        nome="github_ler_arquivo",
        grupo="github",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Lê o conteúdo de um arquivo de um repositório do GitHub. Mostra o "
            "texto do arquivo. Use quando o Vitor pedir pra ver o que tem dentro "
            "de um arquivo no GitHub."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "caminho": {"type": "string",
                        "description": "Caminho completo do arquivo (ex: src/main.py)"},
            "ref": {"type": "string",
                    "description": "Branch ou tag. Vazio = branch padrão"},
        },
        obrigatorios=["repo", "caminho"],
        executar=lambda repo, caminho, ref="": github_api.ler_arquivo(
            repo, caminho, ref),
    ))

    registrar(Ferramenta(
        nome="github_escrever_arquivo",
        grupo="github",
        descricao=(
            "Cria ou atualiza um arquivo num repositório do GitHub, com commit "
            "automático. Se o arquivo já existe, substitui. Use quando o Vitor "
            "pedir pra criar, editar, salvar ou atualizar um arquivo no GitHub."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "caminho": {"type": "string",
                        "description": "Caminho completo do arquivo (ex: src/main.py)"},
            "conteudo": {"type": "string",
                         "description": "Conteúdo do arquivo"},
            "mensagem": {"type": "string",
                         "description": "Mensagem do commit. Opcional"},
            "branch": {"type": "string",
                       "description": "Branch. Vazio = main"},
        },
        obrigatorios=["repo", "caminho", "conteudo"],
        aviso="github",
        executar=lambda repo, caminho, conteudo, mensagem="", branch="main":
            github_api.escrever_arquivo(repo, caminho, conteudo, mensagem, branch),
    ))

    registrar(Ferramenta(
        nome="github_apagar_arquivo",
        grupo="github",
        destrutiva=True,
        descricao=(
            "Apaga um arquivo de um repositório do GitHub, com commit automático. "
            "Use SOMENTE se o Vitor pedir pra apagar, deletar ou remover um "
            "arquivo do GitHub."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "caminho": {"type": "string",
                        "description": "Caminho completo do arquivo a apagar"},
            "mensagem": {"type": "string",
                         "description": "Mensagem do commit. Opcional"},
            "branch": {"type": "string",
                       "description": "Branch. Vazio = main"},
        },
        obrigatorios=["repo", "caminho"],
        aviso="github",
        executar=lambda repo, caminho, mensagem="", branch="main":
            github_api.apagar_arquivo(repo, caminho, mensagem, branch),
    ))

    registrar(Ferramenta(
        nome="github_ver_readme",
        grupo="github",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Lê o README de um repositório do GitHub. Use quando o Vitor pedir "
            "pra ver o README, a documentação, ou 'o que diz o readme' de um repo."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
        },
        obrigatorios=["repo"],
        executar=lambda repo: github_api.ver_readme(repo),
    ))

    # ── Commits ─────────────────────────────────────────────────

    registrar(Ferramenta(
        nome="github_listar_commits",
        grupo="github",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Lista os commits recentes de um repositório do GitHub, com hash, "
            "data, autor e mensagem. Use quando o Vitor perguntar 'quais commits "
            "teve', 'o que foi alterado', 'mostra os commits'."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "branch": {"type": "string",
                       "description": "Branch. Vazio = branch padrão"},
        },
        obrigatorios=["repo"],
        executar=lambda repo, branch="": github_api.listar_commits(repo, branch),
    ))

    # ── Branches ────────────────────────────────────────────────

    registrar(Ferramenta(
        nome="github_listar_branches",
        grupo="github",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Lista as branches de um repositório do GitHub. Use quando o Vitor "
            "perguntar 'quais branches tem', 'mostra as branches'."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
        },
        obrigatorios=["repo"],
        executar=lambda repo: github_api.listar_branches(repo),
    ))

    registrar(Ferramenta(
        nome="github_criar_branch",
        grupo="github",
        descricao=(
            "Cria uma branch nova num repositório do GitHub, a partir de uma "
            "branch existente. Use quando o Vitor pedir pra criar uma branch."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "nome": {"type": "string", "description": "Nome da branch nova"},
            "de": {"type": "string",
                   "description": "Branch de origem. Vazio = main"},
        },
        obrigatorios=["repo", "nome"],
        aviso="github",
        executar=lambda repo, nome, de="main": github_api.criar_branch(repo, nome, de),
    ))

    # ── Pull Requests ───────────────────────────────────────────

    registrar(Ferramenta(
        nome="github_listar_prs",
        grupo="github",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Lista as pull requests de um repositório do GitHub. Use quando o "
            "Vitor perguntar 'quais PRs tem', 'mostra as pull requests', 'PRs "
            "abertas'."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "estado": {"type": "string",
                       "enum": ["open", "closed", "all"],
                       "description": "Filtro: open (abertas), closed (fechadas), all (todas)"},
        },
        obrigatorios=["repo"],
        executar=lambda repo, estado="open": github_api.listar_prs(repo, estado),
    ))

    registrar(Ferramenta(
        nome="github_ver_pr",
        grupo="github",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Mostra os detalhes de uma pull request específica: título, estado, "
            "branch de origem/destino, autor, descrição. Use quando o Vitor pedir "
            "pra ver uma PR específica."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "numero": {"type": "integer",
                       "description": "Número da PR (ex: 12)"},
        },
        obrigatorios=["repo", "numero"],
        executar=lambda repo, numero: github_api.ver_pr(repo, int(numero)),
    ))

    registrar(Ferramenta(
        nome="github_criar_pr",
        grupo="github",
        descricao=(
            "Abre uma pull request num repositório do GitHub. Pede título, branch "
            "de origem, branch de destino e descrição opcional. Use quando o "
            "Vitor pedir pra abrir uma PR, pull request, merge request."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "titulo": {"type": "string", "description": "Título da PR"},
            "head": {"type": "string",
                     "description": "Branch de origem (ex: feature/nova-func)"},
            "base": {"type": "string",
                     "description": "Branch de destino (ex: main)"},
            "corpo": {"type": "string",
                      "description": "Descrição/detalhes da PR. Opcional"},
        },
        obrigatorios=["repo", "titulo", "head", "base"],
        aviso="github",
        executar=lambda repo, titulo, head, base, corpo="":
            github_api.criar_pr(repo, titulo, head, base, corpo),
    ))

    registrar(Ferramenta(
        nome="github_mesclar_pr",
        grupo="github",
        descricao=(
            "Mescla (faz merge) de uma pull request no GitHub. Use quando o "
            "Vitor pedir pra mergear, mesclar, aprovar ou aplicar uma PR."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "numero": {"type": "integer",
                       "description": "Número da PR"},
        },
        obrigatorios=["repo", "numero"],
        aviso="github",
        executar=lambda repo, numero: github_api.mesclar_pr(repo, int(numero)),
    ))

    registrar(Ferramenta(
        nome="github_fechar_pr",
        grupo="github",
        descricao=(
            "Fecha uma pull request sem mesclar. Use quando o Vitor pedir pra "
            "fechar uma PR sem dar merge."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "numero": {"type": "integer",
                       "description": "Número da PR"},
        },
        obrigatorios=["repo", "numero"],
        aviso="github",
        executar=lambda repo, numero: github_api.fechar_pr(repo, int(numero)),
    ))

    # ── Issues ──────────────────────────────────────────────────

    registrar(Ferramenta(
        nome="github_listar_issues",
        grupo="github",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Lista as issues de um repositório do GitHub. Use quando o Vitor "
            "perguntar 'quais issues tem', 'mostra as issues', 'o que tá pendente'."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "estado": {"type": "string",
                       "enum": ["open", "closed", "all"],
                       "description": "Filtro: open (abertas), closed (fechadas), all (todas)"},
        },
        obrigatorios=["repo"],
        executar=lambda repo, estado="open": github_api.listar_issues(repo, estado),
    ))

    registrar(Ferramenta(
        nome="github_criar_issue",
        grupo="github",
        descricao=(
            "Abre uma issue nova num repositório do GitHub. Pede título e "
            "descrição opcional. Use quando o Vitor pedir pra abrir uma issue, "
            "reportar um problema, sugerir algo."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "titulo": {"type": "string", "description": "Título da issue"},
            "corpo": {"type": "string",
                      "description": "Descrição detalhada. Opcional"},
        },
        obrigatorios=["repo", "titulo"],
        aviso="github",
        executar=lambda repo, titulo, corpo="": github_api.criar_issue(repo, titulo, corpo),
    ))

    registrar(Ferramenta(
        nome="github_fechar_issue",
        grupo="github",
        descricao=(
            "Fecha uma issue de um repositório do GitHub. Use quando o Vitor "
            "pedir pra fechar uma issue específica."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "numero": {"type": "integer",
                       "description": "Número da issue"},
        },
        obrigatorios=["repo", "numero"],
        aviso="github",
        executar=lambda repo, numero: github_api.fechar_issue(repo, int(numero)),
    ))

    registrar(Ferramenta(
        nome="github_comentar_issue",
        grupo="github",
        descricao=(
            "Adiciona um comentário numa issue ou PR do GitHub. Use quando o "
            "Vitor pedir pra comentar, responder, ou escrever algo numa issue ou PR."
        ),
        propriedades={
            "repo": {"type": "string",
                     "description": "Nome completo (dono/nome) do repositório"},
            "numero": {"type": "integer",
                       "description": "Número da issue ou PR"},
            "comentario": {"type": "string", "description": "Texto do comentário"},
        },
        obrigatorios=["repo", "numero", "comentario"],
        aviso="github",
        executar=lambda repo, numero, comentario:
            github_api.comentar_issue(repo, int(numero), comentario),
    ))

    # ── Usuário ─────────────────────────────────────────────────

    registrar(Ferramenta(
        nome="github_ver_usuario",
        grupo="github",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Mostra informações do perfil do Vitor no GitHub: login, nome, "
            "quantos repositórios, seguidores. Use quando ele perguntar 'quem "
            "sou eu no GitHub', 'meu perfil', 'meus dados do GitHub'."
        ),
        propriedades={},
        executar=lambda: github_api.ver_usuario(),
    ))

    registrar(Ferramenta(
        nome="github_listar_repos_usuario",
        grupo="github",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Lista repositórios de QUALQUER usuário do GitHub (não só o Vitor). "
            "Use quando ele pedir pra ver os repositórios de outra pessoa, "
            "'mostra os repos do fulano', 'o que o ciclano tem no GitHub'."
        ),
        propriedades={
            "usuario": {"type": "string",
                        "description": "Nome de usuário do GitHub (ex: octocat)"},
        },
        obrigatorios=["usuario"],
        executar=lambda usuario: github_api.listar_repos_usuario(usuario),
    ))

    _log(f"{len(github_api.__dict__)} operações de GitHub registradas")


try:
    _registrar_catalogo_github()
except Exception as e:
    _log(f"catálogo de GitHub não carregou ({type(e).__name__}: {e}); "
         f"Emily continua sem ferramentas de GitHub")


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO — EMILY CODE (sob demanda via abrir_ferramentas("code"))
# ═════════════════════════════════════════════════════════════════

def _registrar_catalogo_code():
    import emily_code

    # ── Leitura / contexto (sem permissão) ────────────────────────

    registrar(Ferramenta(
        nome="code_ler_arquivo",
        grupo="code",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Lê o conteúdo de um arquivo da pasta de projeto do Vitor. Mostra "
            "o texto com linhas. Use quando precisar ver o que tem dentro de "
            "um arquivo do projeto."
        ),
        propriedades={
            "arquivo": {"type": "string",
                        "description": "Caminho relativo do arquivo (ex: src/main.py)"},
        },
        obrigatorios=["arquivo"],
        aviso="code",
        executar=lambda arquivo: emily_code.executar("ler_arquivo", arquivo=arquivo),
    ))

    registrar(Ferramenta(
        nome="code_listar_arquivos",
        grupo="code",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Lista os arquivos e pastas de um diretório da pasta de projeto do "
            "Vitor. Use quando ele perguntar 'o que tem nessa pasta', 'mostra "
            "os arquivos'."
        ),
        propriedades={
            "pasta": {"type": "string",
                      "description": "Pasta relativa (ex: src). Vazio = raiz"},
        },
        executar=lambda pasta="": emily_code.executar("listar_arquivos", pasta=pasta),
    ))

    registrar(Ferramenta(
        nome="code_ver_estrutura",
        grupo="code",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Mostra a árvore de pastas e arquivos do projeto do Vitor (até "
            "algumas pastas de profundidade). Use pra entender a organização "
            "geral do projeto."
        ),
        propriedades={
            "profundidade": {"type": "integer",
                             "description": "Quantas pastas de profundidade. Padrão 3"},
        },
        executar=lambda profundidade=3: emily_code.executar(
            "ver_estrutura", profundidade=profundidade),
    ))

    registrar(Ferramenta(
        nome="code_buscar",
        grupo="code",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Procura um texto (regex ou palavra) dentro dos arquivos do projeto "
            "do Vitor. Mostra arquivo:linha: trecho. Use quando ele pedir pra "
            "achar onde algo é usado, onde aparece tal função, variável, texto."
        ),
        propriedades={
            "padrao": {"type": "string", "description": "Texto ou regex pra procurar"},
            "em": {"type": "string",
                   "description": "Pasta de DENTRO do projeto pra restringir a busca "
                                  "(ex: 'src', 'web', 'testes'). NÃO é nome de arquivo — "
                                  "se o Vitor mencionar um arquivo específico, use o "
                                  "padrao pra procurar DENTRO dele e deixe em vazio. "
                                  "Vazio = projeto todo."},
        },
        obrigatorios=["padrao"],
        executar=lambda padrao, em="": emily_code.executar(
            "buscar_texto", padrao=padrao, em=em),
    ))

    registrar(Ferramenta(
        nome="code_achar_arquivo",
        grupo="code",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Acha arquivos pelo nome (ou parte do nome) dentro do projeto do "
            "Vitor. Mostra os caminhos completos."
        ),
        propriedades={
            "nome": {"type": "string", "description": "Nome (ou parte) do arquivo"},
        },
        obrigatorios=["nome"],
        executar=lambda nome: emily_code.executar("achar_arquivo", nome=nome),
    ))

    registrar(Ferramenta(
        nome="code_projeto",
        grupo="code",
        somente_leitura=True, paralelizavel=True,
        descricao=(
            "Mostra a pasta de projeto configurada e seu conteúdo na raiz. Use "
            "pra saber onde a Emily pode mexer e o que tem lá."
        ),
        propriedades={},
        executar=lambda: emily_code.executar("ver_projeto"),
    ))

    # ── Escrita (pede permissão) ──────────────────────────────────

    registrar(Ferramenta(
        nome="code_escrever_arquivo",
        grupo="code",
        descricao=(
            "Cria um arquivo novo ou substitui um existente INTEIRO na pasta de "
            "projeto, com o conteúdo fornecido. Pede permissão ao Vitor antes "
            "de escrever. Use quando ele pedir pra criar, salvar ou atualizar "
            "um arquivo."
        ),
        propriedades={
            "arquivo": {"type": "string",
                        "description": "Caminho relativo do arquivo (ex: src/main.py)"},
            "conteudo": {"type": "string", "description": "Conteúdo completo do arquivo"},
        },
        obrigatorios=["arquivo", "conteudo"],
        aviso="code",
        executar=lambda arquivo, conteudo: emily_code.executar(
            "escrever_arquivo", arquivo=arquivo, conteudo=conteudo),
    ))

    registrar(Ferramenta(
        nome="code_editar_arquivo",
        grupo="code",
        descricao=(
            "Edita um trecho específico de um arquivo do projeto: substitui "
            "uma parte exata por outra. Não reescreve o arquivo inteiro. Pede "
            "permissão antes. Use pra consertar um pedaço de código."
        ),
        propriedades={
            "arquivo": {"type": "string",
                        "description": "Caminho relativo do arquivo"},
            "buscar": {"type": "string",
                       "description": "Trecho exato que existe no arquivo e será substituído"},
            "substituir": {"type": "string",
                           "description": "Novo trecho que entra no lugar"},
            "ocorrencia": {"type": "integer",
                           "description": "Qual ocorrência (0 = primeira). Opcional"},
        },
        obrigatorios=["arquivo", "buscar", "substituir"],
        aviso="code",
        executar=lambda arquivo, buscar, substituir, ocorrencia=0: emily_code.executar(
            "editar_arquivo", arquivo=arquivo, buscar=buscar,
            substituir=substituir, ocorrencia=ocorrencia),
    ))

    registrar(Ferramenta(
        nome="code_editar_linhas",
        grupo="code",
        descricao=(
            "Edita um trecho de arquivo por NÚMERO DE LINHA: troca da linha "
            "linha_inicio até linha_fim (inclusive) pelo novo_conteudo. Mais "
            "confiável que buscar/substituir quando o texto é impreciso. "
            "Pede permissão. Use pra mexer num pedaço do código sabendo as linhas."
        ),
        propriedades={
            "arquivo": {"type": "string",
                        "description": "Caminho relativo do arquivo"},
            "linha_inicio": {"type": "integer",
                             "description": "Primeira linha a substituir (1-indexada)"},
            "linha_fim": {"type": "integer",
                          "description": "Última linha a substituir (inclusive)"},
            "novo_conteudo": {"type": "string",
                              "description": "O que entra no lugar da faixa de linhas"},
        },
        obrigatorios=["arquivo", "linha_inicio", "linha_fim", "novo_conteudo"],
        aviso="code",
        executar=lambda arquivo, linha_inicio, linha_fim, novo_conteudo: emily_code.executar(
            "editar_linhas", arquivo=arquivo, linha_inicio=linha_inicio,
            linha_fim=linha_fim, novo_conteudo=novo_conteudo),
    ))

    registrar(Ferramenta(
        nome="code_editar_multi",
        grupo="code",
        descricao=(
            "Aplica VÁRIAS edições no mesmo arquivo numa única chamada "
            "(lista de edições, aplicadas em ordem). Cada edição é um objeto "
            "com linha_inicio, linha_fim e novo_conteudo. TUDO-OU-NADA: se "
            "uma falhar, nenhuma é aplicada. Pede permissão uma vez."
        ),
        propriedades={
            "arquivo": {"type": "string",
                        "description": "Caminho relativo do arquivo"},
            "edicoes": {"type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "linha_inicio": {"type": "integer"},
                                "linha_fim": {"type": "integer"},
                                "novo_conteudo": {"type": "string"},
                            },
                        },
                        "description": "Lista de edições na ordem de aplicação"},
        },
        obrigatorios=["arquivo", "edicoes"],
        aviso="code",
        executar=lambda arquivo, edicoes: emily_code.executar(
            "editar_multi", arquivo=arquivo, edicoes=edicoes),
    ))

    registrar(Ferramenta(
        nome="code_apagar_arquivo",
        grupo="code",
        destrutiva=True,
        descricao=(
            "Apaga um arquivo ou pasta do projeto do Vitor. Pede permissão "
            "SEMPRE (é destrutivo). Use SOMENTE se ele pedir pra apagar, deletar "
            "ou remover."
        ),
        propriedades={
            "arquivo": {"type": "string",
                        "description": "Caminho relativo do arquivo ou pasta a apagar"},
        },
        obrigatorios=["arquivo"],
        aviso="code",
        executar=lambda arquivo: emily_code.executar("apagar_arquivo", arquivo=arquivo),
    ))

    registrar(Ferramenta(
        nome="code_desfazer_ultima_mudanca",
        grupo="code",
        descricao=(
            "Restaura o backup mais recente de um arquivo que a Emily modificou "
            "ou apagou (o Emily Code guarda uma cópia antes de cada escrita). "
            "Use quando o Vitor pedir pra desfazer/voltar atrás numa mudança de "
            "arquivo. Pede permissão (escreve no arquivo)."
        ),
        propriedades={
            "arquivo": {"type": "string",
                        "description": "Caminho relativo do arquivo a restaurar"},
        },
        obrigatorios=["arquivo"],
        aviso="code",
        executar=lambda arquivo: emily_code.executar(
            "desfazer_ultima_mudanca", arquivo=arquivo),
    ))

    registrar(Ferramenta(
        nome="code_renomear_arquivo",
        grupo="code",
        descricao=(
            "Renomeia um arquivo ou pasta do projeto do Vitor. Pede permissão. "
            "Use quando ele pedir pra renomear."
        ),
        propriedades={
            "arquivo": {"type": "string", "description": "Caminho atual"},
            "novo_nome": {"type": "string", "description": "Novo nome (só o nome)"},
        },
        obrigatorios=["arquivo", "novo_nome"],
        aviso="code",
        executar=lambda arquivo, novo_nome: emily_code.executar(
            "renomear_arquivo", arquivo=arquivo, novo_nome=novo_nome),
    ))

    registrar(Ferramenta(
        nome="code_mover_arquivo",
        grupo="code",
        descricao=(
            "Move um arquivo de lugar dentro do projeto do Vitor. Pede "
            "permissão. Use quando ele pedir pra mover, mudar de pasta."
        ),
        propriedades={
            "arquivo": {"type": "string", "description": "Caminho atual do arquivo"},
            "destino": {"type": "string",
                        "description": "Caminho relativo de destino (ex: src/novo.py)"},
        },
        obrigatorios=["arquivo", "destino"],
        aviso="code",
        executar=lambda arquivo, destino: emily_code.executar(
            "mover_arquivo", arquivo=arquivo, destino=destino),
    ))

    # ── Execução (pede permissão sempre) ──────────────────────────

    registrar(Ferramenta(
        nome="code_executar_comando",
        grupo="code",
        descricao=(
            "Executa um comando no terminal, dentro da pasta de projeto do "
            "Vitor. Pede permissão SEMPRE. Use pra rodar build, teste, npm, "
            "pip, git, python -m, etc. Devolve a saída do comando."
        ),
        propriedades={
            "comando": {"type": "string",
                        "description": "Comando completo pra rodar (ex: python -m pytest)"},
        },
        obrigatorios=["comando"],
        aviso="code",
        executar=lambda comando: emily_code.executar("executar_comando", comando=comando),
    ))

    registrar(Ferramenta(
        nome="code_executar_script",
        grupo="code",
        descricao=(
            "Executa um script do projeto do Vitor (Python, Node ou bash) com "
            "argumentos opcionais. Pede permissão SEMPRE. Use quando ele pedir "
            "pra rodar um script específico."
        ),
        propriedades={
            "arquivo": {"type": "string",
                        "description": "Caminho relativo do script (ex: scripts/build.py)"},
            "args": {"type": "string",
                     "description": "Argumentos pra passar pro script. Opcional"},
        },
        obrigatorios=["arquivo"],
        aviso="code",
        executar=lambda arquivo, args="": emily_code.executar(
            "executar_script", arquivo=arquivo, args=args),
    ))

    registrar(Ferramenta(
        nome="code_executar_comando_fundo",
        grupo="code",
        descricao=(
            "Inicia um comando em SEGUNDO PLANO na pasta de projeto, sem "
            "travar o Emily Code, e devolve um id. Depois usa "
            "ver_saida_processo pra consultar a saída e encerrar_processo "
            "pra matar. Pede permissão pra executar."
        ),
        propriedades={
            "comando": {"type": "string",
                        "description": "Comando pra rodar em segundo plano (ex: python -m http.server 8000)"},
        },
        obrigatorios=["comando"],
        aviso="code",
        executar=lambda comando: emily_code.executar(
            "executar_comando_fundo", comando=comando),
    ))

    registrar(Ferramenta(
        nome="code_ver_saida_processo",
        grupo="code",
        descricao=(
            "Consulta a saída acumulada de um processo iniciado com "
            "executar_comando_fundo. Diz se terminou e o código de saída. "
            "Leitura livre."
        ),
        propriedades={
            "id_processo": {"type": "string",
                            "description": "O id devolvido por executar_comando_fundo"},
        },
        obrigatorios=["id_processo"],
        aviso="code",
        executar=lambda id_processo: emily_code.executar(
            "ver_saida_processo", id_processo=id_processo),
    ))

    registrar(Ferramenta(
        nome="code_encerrar_processo",
        grupo="code",
        descricao=(
            "Encerra (mata) um processo que roda em segundo plano, pelo id "
            "devolvido por executar_comando_fundo. Pede permissão."
        ),
        propriedades={
            "id_processo": {"type": "string",
                            "description": "O id do processo a encerrar"},
        },
        obrigatorios=["id_processo"],
        aviso="code",
        executar=lambda id_processo: emily_code.executar(
            "encerrar_processo", id_processo=id_processo),
    ))

    # ── Workspace de teste (Fase 2.6) ───────────────────────────────
    # Área de rascunho fora do projeto: copiar/escrever/ler/lixar é livre.

    registrar(Ferramenta(
        nome="code_workspace_copiar",
        grupo="code",
        descricao=(
            "Copia um arquivo do projeto pra workspace de rascunho (fora do "
            "projeto real). Serve pra testar/alterar sem risco de estragar o "
            "projeto do Vitor. Não pede permissão de escrita."
        ),
        propriedades={
            "arquivo": {"type": "string",
                        "description": "Caminho relativo no projeto"},
            "para": {"type": "string",
                     "description": "Nome na workspace. Opcional (usa o mesmo nome)"},
        },
        obrigatorios=["arquivo"],
        aviso="code",
        executar=lambda arquivo, para="": emily_code.executar(
            "workspace_copiar", arquivo=arquivo, para=para),
    ))

    registrar(Ferramenta(
        nome="code_workspace_escrever",
        grupo="code",
        descricao=(
            "Escreve um arquivo de rascunho na workspace (fora do projeto real). "
            "Não pede permissão de escrita — é área segura."
        ),
        propriedades={
            "nome": {"type": "string", "description": "Nome do arquivo na workspace"},
            "conteudo": {"type": "string", "description": "Conteúdo do rascunho"},
        },
        obrigatorios=["nome", "conteudo"],
        aviso="code",
        executar=lambda nome, conteudo: emily_code.executar(
            "workspace_escrever", nome=nome, conteudo=conteudo),
    ))

    registrar(Ferramenta(
        nome="code_workspace_ler",
        grupo="code",
        descricao=(
            "Lê um arquivo da workspace de rascunho. Leitura livre."
        ),
        propriedades={
            "nome": {"type": "string", "description": "Nome do arquivo na workspace"},
        },
        obrigatorios=["nome"],
        aviso="code",
        executar=lambda nome: emily_code.executar("workspace_ler", nome=nome),
    ))

    registrar(Ferramenta(
        nome="code_workspace_listar",
        grupo="code",
        descricao=(
            "Lista os arquivos da workspace de rascunho. Leitura livre."
        ),
        propriedades={},
        aviso="code",
        executar=lambda: emily_code.executar("workspace_listar"),
    ))

    registrar(Ferramenta(
        nome="code_workspace_rodar",
        grupo="code",
        descricao=(
            "Roda um comando COM o diretório de trabalho na workspace (fora do "
            "projeto real), pra testar um rascunho sem risco. Pede permissão de "
            "execução."
        ),
        propriedades={
            "comando": {"type": "string",
                        "description": "Comando pra rodar na workspace"},
        },
        obrigatorios=["comando"],
        aviso="code",
        executar=lambda comando: emily_code.executar(
            "workspace_rodar", comando=comando),
    ))

    registrar(Ferramenta(
        nome="code_workspace_limpar",
        grupo="code",
        descricao=(
            "Apaga todos os arquivos da workspace de rascunho. Só mexe na "
            "workspace, nunca no projeto real. Não pede permissão."
        ),
        propriedades={},
        aviso="code",
        executar=lambda: emily_code.executar("workspace_limpar"),
    ))

    # ── Dependências (Fase 3.2) ─────────────────────────────────────

    registrar(Ferramenta(
        nome="code_listar_dependencias",
        grupo="code",
        descricao=(
            "Lista as dependências do projeto: lê requirements.txt (e variantes) "
            "e package.json (dependencies + devDependencies). Leitura livre."
        ),
        propriedades={},
        aviso="code",
        executar=lambda: emily_code.executar("listar_dependencias"),
    ))

    registrar(Ferramenta(
        nome="code_instalar_pacote",
        grupo="code",
        descricao=(
            "Instala um pacote no projeto com o gerenciador pedido (pip ou npm). "
            "Roda python -m pip install ou npm install na pasta de projeto. "
            "Pede permissão de execução."
        ),
        propriedades={
            "gerenciador": {"type": "string",
                            "description": "'pip' ou 'npm'"},
            "nome": {"type": "string",
                     "description": "Nome do pacote a instalar"},
        },
        obrigatorios=["gerenciador", "nome"],
        aviso="code",
        executar=lambda gerenciador, nome: emily_code.executar(
            "instalar_pacote", gerenciador=gerenciador, nome=nome),
    ))

    registrar(Ferramenta(
        nome="code_editar_transacao",
        grupo="code",
        descricao=(
            "Aplica edições em VÁRIOS ARQUIVOS como uma transação: se QUALQUER "
            "um falhar, reverte todos os outros da mesma leva (tudo-ou-nada). "
            "Cada edição é um objeto com 'arquivo' e ou 'conteudo' (escrita "
            "completa) ou 'linha_inicio'/'linha_fim'/'novo_conteudo' (edição por "
            "linha). Pede permissão uma vez, com preview de todos os diffs. Use "
            "pra mudanças que tocam arquivos relacionados (ex: renomear função "
            "usada em vários lugares)."
        ),
        propriedades={
            "edicoes": {"type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "arquivo": {"type": "string"},
                                "conteudo": {"type": "string"},
                                "linha_inicio": {"type": "integer"},
                                "linha_fim": {"type": "integer"},
                                "novo_conteudo": {"type": "string"},
                            },
                        },
                        "description": "Lista de edições (arquivos diferentes ou não)"},
        },
        obrigatorios=["edicoes"],
        aviso="code",
        executar=lambda edicoes: emily_code.executar(
            "editar_transacao", edicoes=edicoes),
    ))

    # ── Git local (Fase 2.1) ────────────────────────────────────────
    # Leitura (status/diff/log) é livre; commit pede permissão de execução.

    registrar(Ferramenta(
        nome="code_git_status",
        grupo="code",
        descricao=(
            "Mostra o status do repositório git na pasta de projeto: arquivos "
            "modificados, staged, untracked e branch atual. Não muda nada."
        ),
        propriedades={},
        aviso="code",
        executar=lambda: emily_code.executar("git_status"),
    ))

    registrar(Ferramenta(
        nome="code_git_diff",
        grupo="code",
        descricao=(
            "Mostra o diff do working tree (não staged) no formato unificado. "
            "Se passar um arquivo, mostra só o diff dele. Leitura livre."
        ),
        propriedades={
            "relativo": {"type": "string",
                         "description": "Arquivo específico (ex: src/main.py). Vazio = tudo"},
        },
        aviso="code",
        executar=lambda relativo="": emily_code.executar("git_diff", relativo=relativo),
    ))

    registrar(Ferramenta(
        nome="code_git_log",
        grupo="code",
        descricao=(
            "Mostra os últimos commits do repositório: hash, data, autor e "
            "mensagem. Leitura livre."
        ),
        propriedades={
            "quantos": {"type": "integer",
                        "description": "Quantos commits mostrar. Padrão 10, máx 50"},
        },
        aviso="code",
        executar=lambda quantos=10: emily_code.executar("git_log", quantos=quantos),
    ))

    registrar(Ferramenta(
        nome="code_git_commit",
        grupo="code",
        descricao=(
            "Faz git add -A + git commit na pasta de projeto com a mensagem "
            "fornecida. Pede permissão antes de executar (é escrita)."
        ),
        propriedades={
            "mensagem": {"type": "string",
                         "description": "Mensagem do commit"},
        },
        obrigatorios=["mensagem"],
        aviso="code",
        executar=lambda mensagem: emily_code.executar("git_commit", mensagem=mensagem),
    ))

    # ── Pergunta ──────────────────────────────────────────────────

    registrar(Ferramenta(
        nome="code_perguntar",
        grupo="code",
        descricao=(
            "Faz uma pergunta ao Vitor com opções, numa janela bonita. Use pra "
            "esclarecer o que ele quer antes de agir: qual abordagem, qual "
            "opção, qual arquivo. Passa a pergunta e até 4 opções. A resposta "
            "dele volta."
        ),
        propriedades={
            "pergunta": {"type": "string", "description": "A pergunta clara"},
            "opcoes": {"type": "array", "items": {"type": "string"},
                       "description": "Até 4 opções de resposta (opcional)"},
        },
        obrigatorios=["pergunta"],
        executar=lambda pergunta, opcoes=None: _code_perguntar(pergunta, opcoes),
    ))

    registrar(Ferramenta(
        nome="code_mudar_pasta",
        grupo="code",
        descricao=(
            "Acende o aviso de escolher pasta de projeto de novo, com campo e "
            "botão 'Escolher pasta…', e ESPERA o Vitor escolher. Use quando ele "
            "pedir pra mudar de pasta de projeto ou trocar o diretório onde as "
            "ferramentas de código rodam."
        ),
        propriedades={
            "mensagem": {"type": "string",
                         "description": "Aviso opcional a mostrar junto do campo"},
        },
        executar=lambda mensagem="": _code_mudar_pasta(mensagem),
    ))

    # Revisão multi-modelo: a Emily chama esta ferramenta QUANDO QUISER
    # uma segunda opinião do DeepSeek sobre o código que acabou de editar.
    # Não é automática — a Emily decide se precisa de revisão, como qualquer
    # outra ferramenta. O pipeline roda: MiniMax planeja, Qwen implementa,
    # DeepSeek revisa, com loop de até 3 rodadas.
    registrar(Ferramenta(
        nome="code_revisar",
        grupo="code",
        descricao=(
            "Chama o DeepSeek pra revisar a implementação que você acabou de "
            "fazer no Emily Code. O DeepSeek analisa as mudanças e aponta "
            "problemas. Use quando a tarefa for complexa, crítica ou de alto "
            "risco (múltiplos arquivos, lógica não-trivial, código que já "
            "existe e é importante pro funcionamento). NÃO use pra revisão "
            "simples ou ajuste pequeno — nesses casos confie no seu taco."
        ),
        aviso="code",
        executar=lambda: _code_revisar(),
    ))

    _log("catálogo do Emily Code registrado")


def _code_revisar() -> str:
    """Chama o pipeline multi-modelo de revisão (MiniMax → Qwen → DeepSeek)."""
    try:
        import emily_code_multi
        import emily_code
        cid = emily_code.code_conversa_atual()
        historico = emily_code.code_para_o_modelo(cid) if cid else []
        resultado = emily_code_multi.processar(
            "Revise a implementação que acabou de ser feita.",
            historico)
        return resultado or "Revisão concluída."
    except Exception as e:
        _log(f"code_revisar falhou: {e}")
        return "Não consegui chamar o revisor agora. O DeepSeek pode estar indisponível."


def _code_mudar_pasta(mensagem: str = "") -> str:
    """Acende o aviso de escolher pasta de projeto de novo, bloqueia até escolher."""
    try:
        import interface_web
        return interface_web._mudar_pasta_code(mensagem)
    except Exception as e:
        _log(f"code_mudar_pasta falhou: {e}")
        return "Não consegui acender o aviso de pasta agora."


def _code_perguntar(pergunta: str, opcoes: Optional[list] = None) -> str:
    """Pergunta via ponte do interface_web (modal bonito)."""
    try:
        import interface_web
        return interface_web._perguntar_ao_vitor(pergunta, opcoes or [])
    except Exception as e:
        _log(f"code_perguntar falhou: {e}")
        return "Não consegui fazer a pergunta agora."


try:
    _registrar_catalogo_code()
except Exception as e:
    _log(f"catálogo do Emily Code não carregou ({type(e).__name__}: {e}); "
         f"Emily continua sem ferramentas de código")

# Chromium exclusivo da Emily: funciona sem extensão, sem mover o ponteiro do PC.
# As mesmas ações aparecem no painel lateral do chat para o usuário acompanhar.
def _perguntar_usuario_tarefa(pergunta: str, tipo: str = "duvida"):
    import interface_web
    resposta = interface_web.perguntar_usuario_tarefa(pergunta, tipo)
    if resposta.startswith("Não consegui abrir a pergunta"):
        return recusa(resposta)
    return consulta("Resposta do Vitor: " + resposta)


registrar(Ferramenta(
    nome="perguntar_usuario_tarefa", grupo="geral", aviso="perguntar_usuario",
    descricao=("Pausa a tarefa e abre um cartão de pergunta no chat para o Vitor. "
               "Use quando faltar uma informação necessária, surgir login, CAPTCHA, "
               "permissão ou erro que só ele possa resolver. Depois da resposta, "
               "continue do passo em que parou; não presuma que ele resolveu."),
    propriedades={
        "pergunta": {"type": "string", "description": "O que o Vitor precisa responder ou fazer"},
        "tipo": {"type": "string", "enum": ["duvida", "login", "problema"]},
    },
    obrigatorios=["pergunta"], executar=_perguntar_usuario_tarefa,
))


def _navegador_interno_resultado(resultado: dict, leitura: bool = False):
    if not resultado.get("ok"):
        return recusa("Navegador interno: " + str(resultado.get("erro", "falha desconhecida")))
    texto = f"{resultado.get('titulo') or 'Página'} — {resultado.get('url') or 'em branco'}"
    if resultado.get("largura") and resultado.get("altura"):
        texto += f" (área {resultado['largura']}x{resultado['altura']})"
    if resultado.get("alvo"):
        texto += "\nElemento atingido: " + str(resultado["alvo"])
    if resultado.get("mudou") is False:
        texto += "\nSem mudança observável após o clique; confira a página antes de concluir."
    if leitura:
        texto += "\n\n" + str(resultado.get("texto", ""))
        return consulta(texto)
    return ResultadoFerramenta(texto, ok=True, mudou=bool(resultado.get("mudou", True)))


def _navegador_interno_abrir(endereco: str):
    import navegador_interno
    from urllib.parse import parse_qs, urlparse
    # O campo de endereço aceita busca textual; uma frase com data, produto,
    # preço e local de uma vez costuma esconder o site certo. A pesquisa do
    # navegador deve achar primeiro a fonte e refinar DENTRO dela. A busca
    # informacional via Brave API não passa por esta guarda.
    consulta = endereco
    try:
        partes = urlparse(endereco)
        if partes.hostname and any(
                partes.hostname == m or partes.hostname.endswith("." + m)
                for m in ("bing.com", "google.com", "brave.com", "duckduckgo.com")):
            consulta = (parse_qs(partes.query).get("q") or [endereco])[0]
    except ValueError:
        pass
    termos = consulta.split()
    if (len(termos) >= 8 and " " in consulta and
            any(termo.lower().strip(",.;:?!") in {
                "preço", "preco", "ingresso", "ingressos", "sessão", "sessao",
                "programação", "programacao", "horário", "horario", "data",
            } or any(ch.isdigit() for ch in termo) for termo in termos)):
        return recusa(
            "A busca do navegador juntou detalhes demais. Primeiro localize o "
            "site, empresa ou serviço com poucos termos (por exemplo, nome e "
            "cidade). Abra a fonte certa; depois procure produto, data, horário "
            "e preço dentro dela. URLs diretas continuam permitidas.")
    return _navegador_interno_resultado(navegador_interno.abrir(endereco))


def _navegador_interno_ler():
    import navegador_interno
    return _navegador_interno_resultado(navegador_interno.ler(), leitura=True)


def _navegador_interno_interagir(acao: str, alvo: str = "", valor: str = "",
                                 x: int = 0, y: int = 0, indice: int = 0):
    import navegador_interno
    if acao == "clicar_texto" and alvo:
        resultado = navegador_interno.comando("clicar_texto", alvo)
    elif acao == "preencher" and alvo:
        resultado = navegador_interno.comando("preencher", alvo, valor)
    elif acao == "clicar":
        resultado = navegador_interno.comando("clicar", x, y, "left")
    elif acao == "rolar":
        resultado = navegador_interno.comando("rolar", 0, int(y or 500))
    elif acao == "tecla" and valor:
        resultado = navegador_interno.comando("tecla", valor)
    elif acao in {"voltar", "avancar", "recarregar"}:
        resultado = navegador_interno.comando(acao)
    elif acao == "aguardar":
        try:
            segundos = float(valor or 2)
        except (TypeError, ValueError):
            return recusa("Informe quantos segundos aguardar (entre 0,5 e 5).")
        resultado = navegador_interno.comando("aguardar", segundos)
    elif acao in {"nova_aba", "abas"}:
        resultado = navegador_interno.comando(acao)
    elif acao in {"trocar_aba", "fechar_aba"}:
        resultado = navegador_interno.comando(acao, indice)
    else:
        return recusa("Ação inválida ou faltou alvo/valor no navegador interno.")
    if acao == "abas" and resultado.get("ok"):
        return consulta(json.dumps(resultado.get("abas", []), ensure_ascii=False))
    return _navegador_interno_resultado(resultado)


def _navegador_interno_ver(pergunta: str = ""):
    import navegador_interno
    captura = navegador_interno.comando("estado")
    if not captura.get("ok"):
        return recusa("Não consegui ver o navegador interno: " + str(captura.get("erro")))
    import modelo
    resposta = modelo.analisar_tela_com_pergunta(
        captura["imagem"], (pergunta or "Descreva a página e os controles relevantes.")
        + f" A captura mede {captura['largura']}x{captura['altura']} pixels."
    )
    return consulta(resposta) if resposta else recusa("Não consegui analisar a imagem da página.")


registrar(Ferramenta(
    nome="navegador_interno_abrir", grupo="geral", aviso="abrir_app",
    descricao=("Abre URL HTTP/HTTPS ou pesquisa no navegador INTERNO da Emily, "
               "separado do Brave e visível no painel lateral do chat. "
               "Use quando for útil interagir com um site sem mexer no mouse do usuário. "
               "Ao pesquisar, comece com 2 a 5 termos para achar o site/entidade "
               "correta; depois procure filme, produto, data e preço dentro do site. "
               "Não envie a pergunta inteira como termos de busca."),
    propriedades={"endereco": {"type": "string", "description": "URL ou termos da busca"}},
    obrigatorios=["endereco"], executar=_navegador_interno_abrir,
))
registrar(Ferramenta(
    nome="navegador_interno_ler", grupo="geral", aviso="lendo_pagina",
    descricao="Lê título, URL e texto da página atual do navegador interno da Emily.",
    propriedades={}, somente_leitura=True, executar=_navegador_interno_ler,
))
registrar(Ferramenta(
    nome="navegador_interno_interagir", grupo="geral", aviso="lendo_pagina",
    descricao=("Interage com a página do navegador interno. Prefira clicar_texto "
               "ou preencher por seletor CSS; clique por x/y só após VER a página. "
               "Use abas para listar as abas e o índice para trocar_aba ou "
               "fechar_aba. Se o conteúdo ainda estiver carregando, use aguardar "
               "com valor em segundos (máximo 5), depois leia de novo. "
               "Confirme o resultado após cada ação importante."),
    propriedades={
        "acao": {"type": "string", "enum": ["clicar_texto", "preencher", "clicar", "rolar", "tecla", "voltar", "avancar", "recarregar", "aguardar", "abas", "trocar_aba", "nova_aba", "fechar_aba"]},
        "alvo": {"type": "string", "description": "Texto visível a clicar ou seletor CSS para preencher"},
        "valor": {"type": "string", "description": "Texto do campo ou nome de tecla Playwright"},
        "x": {"type": "integer", "description": "Coordenada horizontal da área atual do navegador"},
        "y": {"type": "integer", "description": "Coordenada vertical para clique; distância de rolagem para rolar"},
        "indice": {"type": "integer", "description": "Número da aba informado pela ação abas"},
    },
    obrigatorios=["acao"], executar=_navegador_interno_interagir,
))
registrar(Ferramenta(
    nome="navegador_interno_ver", grupo="geral", aviso="analizando_pagina",
    descricao="Captura e analisa visualmente a página do navegador interno da Emily.",
    propriedades={"pergunta": {"type": "string"}}, somente_leitura=True,
    executar=_navegador_interno_ver,
))

# ═════════════════════════════════════════════════════════════════
# CATÁLOGO EM CAMADAS — o que entra na mesa por padrão
#
# O PROBLEMA, MEDIDO
# ──────────────────
# O caminho de voz mandava esquemas() sem filtro: 148 ferramentas, 94 mil
# caracteres, ~23.500 tokens. Junto com o system prompt e a memória isso dava
# ~25.800 tokens de ENTRADA por chamada, dos quais o catálogo era 91%. E o laço
# de ferramentas roda até MAX_VOLTAS_FERRAMENTA vezes por turno, então uma frase
# do Vitor podia custar ~155 mil tokens de entrada.
#
# Pior que o custo: das 148, um total de 106 são administração do Discord e
# operação do servidor de Minecraft. Falando por voz com o Vitor, ela quase
# nunca precisa delas — mas pagava por todas e, mais grave, tinha que ESCOLHER
# entre 148 opções. O próprio código já dizia isso em outro lugar: o
# _forcar_ferramenta do modelo.py existe porque "o que derruba a escolha da
# ferramenta é o ruído do histórico", e mesa cheia é a mesma doença.
#
# A SOLUÇÃO
# ─────────
# Duas camadas. Por padrão vai só o grupo 'geral' (42 ferramentas, ~3.700
# tokens) mais UMA ferramenta de escalonamento: abrir_ferramentas(dominio).
# Quando o pedido é de Discord ou de Minecraft, ela chama essa ferramenta e o
# laço acrescenta aquele grupo ao catálogo da volta seguinte.
#
# O custo disso é uma ida a mais ao modelo quando o pedido É de administração.
# O ganho é 85% menos entrada em todo o resto — que é a esmagadora maioria.
#
# A descrição da ferramenta é o ÍNDICE: é ela que faz o modelo saber que existe
# mais coisa e quando pedir. Índice errado é pior que catálogo grande, porque a
# ferramenta simplesmente nunca é encontrada. Por isso ela lista exemplos reais
# de cada domínio em vez de dizer "ferramentas de Discord".
# ═════════════════════════════════════════════════════════════════


# Programação no chat comum: mesmo catálogo e autorização semântica das demais ações.
def _registrar_programacao():
    import programacao
    def execute(op, progress=None, **args):
        data = programacao.execute(op, args, progress=progress)
        return ResultadoFerramenta(texto=json.dumps(data, ensure_ascii=False),
            ok=bool(data.get("ok")), mudou=bool(data.get("ok") and op in {"aplicar", "desfazer"}),
            erro="" if data.get("ok") else str(data.get("erro") or "programacao"))
    for op, desc, props, required in programacao.DEFINITIONS:
        registrar(Ferramenta(nome="programacao_"+op, grupo="programacao", descricao=desc,
            propriedades=props, obrigatorios=required, aviso="",
            somente_leitura=op in {"listar", "arquivos", "ler", "buscar", "status", "diff", "comentar", "comparar", "ambiente"},
            executar=lambda _op=op, **args: execute(_op, **args)))

_registrar_programacao()

def _identificar_musica(fonte='sistema', segundos=12, audd=False):
    import music_discovery
    return json.dumps(music_discovery.identify(fonte, segundos, audd), ensure_ascii=False)

registrar(Ferramenta(nome='identificar_musica', grupo='geral',
    descricao='Identifica a música tocando agora e mostra um cartão na tela, mesmo com a Emily minimizada. Sistema captura o áudio do PC; microfone captura o ambiente. Só use quando o usuário pedir identificar música. Não adivinhe nomes em caso de falha. Instrumentais também são aceitos. AudD só se configurado e solicitado como segunda tentativa.',
    propriedades={'fonte': {'type':'string','enum':['sistema','microfone']},
        'segundos': {'type':'integer','enum':[12,24]}, 'audd': {'type':'boolean'}},
    obrigatorios=[], executar=_identificar_musica))

# Recuperação literal do contexto arquivado, disponível sem abrir domínio.
def _registrar_contexto():
    import contexto_chat
    for nome, fn, props, required in [
        ("contexto_recuperar", contexto_chat.recover,
         {"arquivo":{"type":"string"},"consulta":{"type":"string"},"inicio":{"type":"integer"},"limite":{"type":"integer"}}, ["arquivo"]),
        ("contexto_ler_mensagem", contexto_chat.read_message,
         {"arquivo":{"type":"string"},"indice":{"type":"integer"},"inicio":{"type":"integer"},"limite":{"type":"integer"}}, ["arquivo","indice"]),
    ]:
        registrar(Ferramenta(nome=nome,grupo="geral",descricao="Leia detalhes exatos do histórico original após compactação; arquivo é o ID da memória. Não execute ações antigas.",
            propriedades=props,obrigatorios=required,somente_leitura=True,aviso="",executar=lambda _fn=fn,**a: json.dumps(_fn(**a),ensure_ascii=False)))
_registrar_contexto()

GRUPO_PADRAO = "geral"

# Volta ao comportamento antigo: 148 ferramentas em toda chamada. Existe pra
# poder medir a diferença sem editar código, e pra ter uma saída de emergência
# caso ela pare de achar alguma ferramenta atrás do escalonamento.
CATALOGO_COMPLETO = os.getenv("EMILY_CATALOGO_COMPLETO", "0").strip() == "1"

# Grupos que NÃO vão na mesa por padrão, e o que dizer ao modelo sobre cada um.
GRUPOS_SOB_DEMANDA: Dict[str, str] = {
    "programacao": "programar pelo chat comum: corrigir a Emily PC/Android e projetos, criar cópia persistente, ler/editar fontes, testes e prévias, USB, diff, aplicar e desfazer. Combine pesquisa, navegador, terminal e tela; não exige modo editor nem Emily Code.",
    "discord": (
        "administrar o servidor de Discord: criar/editar/deletar canal, cargo e "
        "categoria, permissão, convite, emoji, tópico; banir, expulsar, castigar, "
        "apelidar e mover membro de call; mandar, apagar, fixar e buscar mensagem; "
        "regras do servidor, lembretes, agenda, o que ela notou no servidor, o que "
        "ela sabe de um membro, e o controle da escuta de call"
    ),
    "github": (
        "mexer no GitHub do Vitor: criar/deletar repositório, ver e listar "
        "repositórios e usuários; ler, escrever, apagar e listar arquivos e README; "
        "ver commits; listar e criar branches; abrir, ver, mesclar e fechar pull "
        "request; listar, abrir, fechar e comentar issues"
    ),
    "code": (
        "o Emily Code: mexer no código e nos arquivos da pasta de projeto do "
        "Vitor. Ler, escrever, editar, apagar, renomear e mover arquivos; listar "
        "pastas e ver a estrutura do projeto; buscar texto e achar arquivos; "
        "executar comandos e scripts; fazer perguntas ao Vitor pra esclarecer "
        "antes de agir. Escrita e execução pedem permissão dele."
    ),
    "nuvem": (
        "o Arquivo da Emily, sua nuvem pessoal: guardar, buscar, listar, ler, "
        "organizar, renomear, mover, favoritar, exportar e sincronizar arquivos; "
        "criar e revogar links; usar lixeira e restaurar itens"
    ),
}


def _abrir_ferramentas(dominio: str) -> str:
    """
    Placeholder. Quem realmente executa é o laço de ferramentas, que é o único
    que pode trocar o catálogo da chamada seguinte.

    Se a execução chegar até aqui, é porque o laço em uso não implementa
    escalonamento. Nesse caso a resposta diz a verdade em vez de fingir que
    abriu — ferramenta que mente sobre o próprio efeito é o pior tipo de bug
    que este projeto já teve.
    """
    conhecido = dominio in GRUPOS_SOB_DEMANDA
    if not conhecido:
        return (f"Não existe o domínio '{dominio}'. Os que existem: "
                f"{', '.join(sorted(GRUPOS_SOB_DEMANDA))}.")
    return ("Neste caminho de conversa eu não consigo abrir mais ferramentas. "
            "Responda com o que já está na mesa, ou diga que isso precisa ser "
            "pedido pelo Discord.")


registrar(Ferramenta(
    nome="abrir_ferramentas",
    grupo=GRUPO_PADRAO,
    descricao=(
        "Traz para a mesa um conjunto de ferramentas que não está carregado agora. "
        "Chame ANTES de tentar fazer a coisa, quando o pedido for de um destes "
        "domínios:\n"
        + "\n".join(f"- {nome}: {oque}" for nome, oque in GRUPOS_SOB_DEMANDA.items())
        + "\n\nDepois de chamar, as ferramentas do domínio aparecem e você usa a "
          "que precisa na mesma conversa. Não chame para coisa que você já "
          "consegue fazer com o que está na mesa (abrir app, mexer em arquivo, "
          "ver a tela, pesquisar, música, memória, modos)."
    ),
    propriedades={
        "dominio": {
            "type": "string",
            "enum": sorted(GRUPOS_SOB_DEMANDA),
            "description": "Qual conjunto de ferramentas trazer.",
        },
    },
    obrigatorios=["dominio"],
    executar=_abrir_ferramentas,
))


def esquemas_padrao() -> List[dict]:
    """
    O que vai na mesa numa conversa comum: o grupo 'geral' e o escalonamento.

    É isto que o caminho de voz usa. Com EMILY_CATALOGO_COMPLETO=1 devolve as
    148 de novo, que é o comportamento antigo — serve pra medir a diferença.
    """
    if CATALOGO_COMPLETO:
        return esquemas()
    return esquemas(grupos=[GRUPO_PADRAO])


def esquemas_com_dominios(dominios: Optional[List[str]] = None) -> List[dict]:
    """O catálogo padrão mais os domínios que já foram abertos neste turno."""
    if CATALOGO_COMPLETO:
        return esquemas()
    grupos = [GRUPO_PADRAO] + [d for d in (dominios or []) if d in GRUPOS_SOB_DEMANDA]
    return esquemas(grupos=grupos)


# ═════════════════════════════════════════════════════════════════
# QUAIS FERRAMENTAS PODEM RODAR EM PARALELO
#
# Marcadas aqui, e não na declaração de cada uma, pra a lista ser LEGÍVEL de
# uma vez: quem for acrescentar uma tem que ver as outras e pensar se a dela é
# do mesmo tipo.
#
# O critério é estreito: só LÊ, e espera rede ou modelo. Nenhuma delas mexe em
# arquivo, janela, mouse ou teclado. As de tela usam `with mss.mss()` — instância
# nova por chamada, que é o jeito thread-safe de usar o mss (conferido no
# visao.py antes de marcar).
#
# Onde isso paga de verdade: "pesquisa o preço da 5090 e vê o que tem na minha
# tela" era 2s + 3s em série, agora é max(2s, 3s).
#
# O que NÃO está aqui e não deve estar: abrir_app, mover_arquivo, tocar_musica,
# executar_na_tela, qualquer coisa de modo, e as 106 de Discord/Minecraft — essas
# nunca foram auditadas pra concorrência e várias mexem em estado compartilhado.
# ═════════════════════════════════════════════════════════════════

PARALELIZAVEIS = (
    "pesquisar_internet",   # espera a Brave Search e o scraping
    "ver_tela",             # captura + chamada de visão
    "traduzir_tela",        # idem
    "ler_instrucoes_da_tela",
    "procurar_no_pc",       # varre disco, até 25s
    "lembrar_fatos",        # lê o memoria.json
    "hora_atual",           # instantânea, mas inofensiva e às vezes vem junto
)

for _nome in PARALELIZAVEIS:
    _f = CATALOGO.get(_nome)
    if _f is None:
        _log(f"PARALELIZAVEIS cita '{_nome}', que não existe no catálogo")
    else:
        _f.paralelizavel = True
        # A mesma lista serve pros dois: uma ferramenta entra em PARALELIZAVEIS
        # justamente porque só lê. Se algum dia entrar uma que muda coisa (não
        # deveria), esta linha é o lugar de separar as duas listas.
        _f.somente_leitura = True


def resumo() -> str:
    """Uma linha por ferramenta, pra inspeção rápida."""
    linhas = [f"{len(CATALOGO)} ferramentas registradas:"]
    for nome, f in CATALOGO.items():
        marca = " [destrutiva]" if f.destrutiva else ""
        args = ", ".join(f.propriedades) or "sem argumentos"
        ligada = "" if not f.executar.__name__.startswith("<lambda") else ""
        linhas.append(f"  {nome}({args}){marca}{ligada}")
    return "\n".join(linhas)


if __name__ == "__main__":
    print(resumo())
    print()
    print(f"handlers de modo registrados: {len(_handlers)} "
          f"(o main.py registra em tempo de execução)")
    print(f"destrutivas permitidas: {PERMITIR_DESTRUTIVAS}")
    print()
    print("--- amostra de esquema enviado ao modelo ---")
    print(json.dumps(esquemas()[0], indent=2, ensure_ascii=False))


# Xadrez integrado: a ferramenta abre uma partida existente sem apagar lances.
def _xadrez_abrir():
    import interface_web
    api = interface_web._api_ativa()
    if api is None:
        return ResultadoFerramenta("A interface desktop precisa estar aberta para jogar xadrez.", ok=False)
    resultado = api.xadrez_acao("abrir")
    if not resultado.get("ok"):
        return ResultadoFerramenta(resultado.get("erro", "Não consegui abrir o tabuleiro."), ok=False)
    return ResultadoFerramenta("Tabuleiro aberto dentro da Emily. A partida anterior, se existir, foi preservada. "
        "O jogador pode escolher a cor e começar uma nova partida pelos controles. "
        "A Emily escolhe os lances e também conversa no painel da partida, em chamadas independentes.", ok=True, mudou=True)

registrar(Ferramenta(
    nome="xadrez_abrir", grupo="geral", aviso="abrir_app",
    descricao="Abre o xadrez integrado da Emily para jogar com o usuário. Use quando ele convidar para jogar xadrez ou pedir o tabuleiro. Preserva a partida salva; não abre sites externos.",
    propriedades={}, executar=_xadrez_abrir,
))

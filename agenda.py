"""
agenda.py — o relógio da Emily.

O QUE FALTAVA
─────────────
Até aqui a Emily só existia quando alguém falava com ela. Toda capacidade dela
começava numa mensagem: sem mensagem, nada acontecia. Isso torna impossível
qualquer coisa com "depois", "amanhã" ou "toda semana" — e é justamente o que
separa alguém que frequenta o servidor de um programa que responde.

Este módulo é o batimento cardíaco. Uma thread que acorda, olha o que está na
hora, executa e volta a dormir.

TRÊS DECISÕES QUE MOLDAM O ARQUIVO
──────────────────────────────────
1. AÇÃO É CALLBACK REGISTRADO, NÃO UM if/elif AQUI.

   Quem sabe dar boas-vindas é o vida_discord. Quem sabe olhar o servidor de
   Minecraft é a ponte. Se este arquivo soubesse executar cada tipo de tarefa,
   ele importaria todos os outros e viraria o centro de tudo — e cada
   capacidade nova exigiria mexer nele.

   Aqui só existe: relógio, persistência e despacho. Os módulos chamam
   `registrar_acao("nome", funcao)` e a agenda nunca precisa saber o que a
   função faz.

2. NÃO DISPARA O QUE ACUMULOU DURANTE O DESLIGAMENTO.

   Esta é a armadilha clássica de agendador, e o efeito dela é grotesco: a
   Emily fica desligada três dias, volta, e manda três "bom dia" seguidos às
   quatro da tarde. Ou pior, num lembrete de dez minutos: volta e despeja
   quarenta avisos.

   A regra é: se a hora passou há mais que a tolerância, a ocorrência é
   ABANDONADA e a tarefa é reagendada pra próxima. Lembrete de uma vez tem
   tolerância maior (algumas horas), porque ali chegar atrasado ainda é melhor
   que nunca chegar — mas mesmo esse desiste depois de meio dia.

3. HORA LOCAL, NÃO UTC.

   O Vitor diz "me lembra às 8". Ele quer 8 da manhã dele. Guardar em UTC e
   converter na hora de mostrar seria mais "correto" e daria mais chance de
   errar por um fuso — e não existe nenhum caso aqui em que dois fusos
   coexistam.

TOLERÂNCIA A FALHA
──────────────────
Tarefa que estoura exceção não derruba o loop nem some: ela conta a falha e é
desativada depois de algumas seguidas. Uma tarefa quebrada tentando pra sempre a
cada 20 segundos é a melhor forma de encher o log e a cota de LLM sem ninguém
notar.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from typing import Callable, Dict, List, Optional

from emily_paths import arquivo_dados

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = str(arquivo_dados("agenda.json"))

# De quanto em quanto o relógio confere se tem coisa na hora. 20s é fino o
# suficiente pra um lembrete parecer pontual e grosso o suficiente pra não pesar.
PASSO = float(os.getenv("EMILY_AGENDA_PASSO", "20"))

# Quanto atraso ainda vale executar, por tipo. Ver a decisão 2 no topo.
TOLERANCIA_RECORRENTE = float(os.getenv("EMILY_AGENDA_TOLERANCIA", "3600"))
TOLERANCIA_UMA_VEZ = float(os.getenv("EMILY_AGENDA_TOLERANCIA_UNICA", "43200"))

# Falhas seguidas antes de desistir de uma tarefa.
MAX_FALHAS = 5

# Teto de tarefas. Não é limite técnico: é limite de estrago, do mesmo jeito que
# o MAX_MODS_POR_VEZ do broxas — o modelo errando num laço criaria mil.
MAX_TAREFAS = 200

TIPOS = ("uma_vez", "diario", "semanal", "intervalo")

_DIAS = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")


def _log(msg: str) -> None:
    print(f"[AGENDA] {msg}")


# ═════════════════════════════════════════════════════════════════
# AÇÕES REGISTRADAS
#
# Cada módulo pluga o que sabe fazer. A assinatura é `fn(tarefa: dict) -> str`,
# e o texto devolvido só vai pro log — a ação é responsável por si mesma.
# ═════════════════════════════════════════════════════════════════

_acoes: Dict[str, Callable[[dict], Optional[str]]] = {}


def registrar_acao(nome: str, funcao: Callable[[dict], Optional[str]]) -> None:
    """Ensina à agenda um tipo de tarefa que ela pode disparar."""
    _acoes[nome] = funcao
    _log(f"ação '{nome}' registrada")


def acoes_conhecidas() -> List[str]:
    return sorted(_acoes)


# ═════════════════════════════════════════════════════════════════
# ESTADO
# ═════════════════════════════════════════════════════════════════

_dados: Optional[dict] = None
_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_parar = threading.Event()


def _padrao() -> dict:
    return {"tarefas": [], "atualizado": ""}


def carregar() -> dict:
    global _dados
    if _dados is not None:
        return _dados
    if not os.path.exists(ARQUIVO):
        _dados = _padrao()
        return _dados
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            lidos = json.load(f)
        base = _padrao()
        base["tarefas"] = lidos.get("tarefas", []) or []
        _dados = base
    except (json.JSONDecodeError, OSError) as e:
        _log(f"arquivo ilegível ({e}); começando do zero")
        _dados = _padrao()
    return _dados


def salvar() -> None:
    dados = carregar()
    dados["atualizado"] = time.strftime("%d/%m/%Y %H:%M")
    try:
        os.makedirs(os.path.dirname(ARQUIVO), exist_ok=True)
        temporario = ARQUIVO + ".tmp"
        with open(temporario, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        os.replace(temporario, ARQUIVO)
    except OSError as e:
        _log(f"não consegui gravar: {e}")


# ═════════════════════════════════════════════════════════════════
# CONTAS DE TEMPO
#
# Tudo aqui é hora local e timestamp de época. As funções são pequenas de
# propósito: erro de fuso ou de "próximo dia" é o tipo de bug que só aparece
# numa quinta-feira às 23h59.
# ═════════════════════════════════════════════════════════════════

def _hoje_as(hora: int, minuto: int, base: Optional[float] = None) -> float:
    """Timestamp de hoje naquele horário, em hora local."""
    agora = time.localtime(base if base is not None else time.time())
    return time.mktime((agora.tm_year, agora.tm_mon, agora.tm_mday,
                        hora, minuto, 0, 0, 0, -1))


def ler_horario(texto: str) -> Optional[tuple]:
    """
    "8", "08:30", "8h", "20:00" -> (hora, minuto). None se não der.

    Aceita formato solto porque quem escreve é uma pessoa no chat, e a LLM
    repassa o que ouviu. Recusar "8h" por causa do 'h' faria a Emily responder
    erro de sintaxe pra um pedido perfeitamente claro.
    """
    if not texto:
        return None
    limpo = str(texto).strip().lower().replace("h", ":").replace(" ", "")
    limpo = limpo.rstrip(":")
    if not limpo:
        return None
    try:
        if ":" in limpo:
            h, m = limpo.split(":", 1)
            hora, minuto = int(h), int(m or 0)
        else:
            hora, minuto = int(limpo), 0
    except ValueError:
        return None
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        return None
    return hora, minuto


def ler_dia_da_semana(texto: str) -> Optional[int]:
    """Nome do dia -> 0 (segunda) a 6 (domingo)."""
    if not texto:
        return None
    alvo = (str(texto).strip().lower()
            .replace("á", "a").replace("ç", "c").replace("â", "a")
            .replace("ê", "e").replace("é", "e").replace("í", "i"))
    alvo = alvo.replace("-feira", "").replace("feira", "").strip()
    for i, dia in enumerate(_DIAS):
        if alvo.startswith(dia[:3]):
            return i
    return None


def _proxima_ocorrencia(tarefa: dict, depois_de: Optional[float] = None) -> float:
    """Quando esta tarefa deve rodar pela próxima vez."""
    agora = depois_de if depois_de is not None else time.time()
    tipo = tarefa.get("tipo")

    if tipo == "uma_vez":
        return float(tarefa.get("quando") or agora)

    if tipo == "intervalo":
        segundos = max(60.0, float(tarefa.get("intervalo") or 3600))
        return agora + segundos

    horario = ler_horario(tarefa.get("horario") or "9:00") or (9, 0)

    if tipo == "diario":
        alvo = _hoje_as(horario[0], horario[1], agora)
        if alvo <= agora:
            alvo = _hoje_as(horario[0], horario[1], agora + 86400)
        return alvo

    if tipo == "semanal":
        dia_alvo = int(tarefa.get("dia_semana") or 0)
        alvo = _hoje_as(horario[0], horario[1], agora)
        hoje = time.localtime(agora).tm_wday
        faltam = (dia_alvo - hoje) % 7
        if faltam == 0 and alvo <= agora:
            faltam = 7
        return alvo + faltam * 86400

    return agora + 3600


def descrever_quando(tarefa: dict) -> str:
    """Como a Emily fala do horário. Vai pro chat, então em português."""
    tipo = tarefa.get("tipo")
    if tipo == "uma_vez":
        quando = float(tarefa.get("quando") or 0)
        agora = time.time()
        if 0 < quando - agora < 86400:
            return time.strftime("hoje às %H:%M", time.localtime(quando))
        return time.strftime("%d/%m às %H:%M", time.localtime(quando))
    if tipo == "diario":
        return f"todo dia às {tarefa.get('horario')}"
    if tipo == "semanal":
        dia = _DIAS[int(tarefa.get("dia_semana") or 0)]
        return f"toda {dia} às {tarefa.get('horario')}"
    if tipo == "intervalo":
        minutos = int(float(tarefa.get("intervalo") or 3600) / 60)
        if minutos % 60 == 0:
            return f"a cada {minutos // 60}h"
        return f"a cada {minutos} min"
    return "sem horário"


# ═════════════════════════════════════════════════════════════════
# CRIAR E MEXER
# ═════════════════════════════════════════════════════════════════

def criar(*, acao: str, tipo: str = "uma_vez", quando: Optional[float] = None,
          horario: str = "", dia_semana: Optional[int] = None,
          intervalo: Optional[float] = None, dados: Optional[dict] = None,
          canal_id: int = 0, criado_por: str = "", visivel: bool = True,
          chave: str = "") -> dict:
    """
    Põe uma tarefa na agenda. Devolve a tarefa criada.

    `chave` é o mecanismo de idempotência: com ela preenchida, criar de novo
    SUBSTITUI a anterior em vez de duplicar. Existe porque as rotinas internas
    (varredura de ausência, painel de status) são registradas a cada boot — sem
    isso, cada reinício da Emily somaria mais uma cópia da mesma rotina, e em
    uma semana ela estaria varrendo o servidor vinte vezes por dia.
    """
    if acao not in _acoes:
        raise ValueError(f"ação '{acao}' não existe; conheço {acoes_conhecidas()}")
    if tipo not in TIPOS:
        raise ValueError(f"tipo '{tipo}' inválido; use um de {TIPOS}")

    tarefa = {
        "id": uuid.uuid4().hex[:8],
        "chave": chave or "",
        "acao": acao,
        "tipo": tipo,
        "quando": quando,
        "horario": horario or "",
        "dia_semana": dia_semana,
        "intervalo": intervalo,
        "dados": dados or {},
        "canal_id": int(canal_id or 0),
        "criado_por": criado_por or "",
        "criado_em": time.time(),
        "ativa": True,
        "falhas": 0,
        "ultima_vez": 0.0,
        "vezes": 0,
        "visivel": bool(visivel),
    }
    tarefa["proxima"] = _proxima_ocorrencia(tarefa)

    with _lock:
        dados_arq = carregar()
        if chave:
            dados_arq["tarefas"] = [t for t in dados_arq["tarefas"]
                                    if t.get("chave") != chave]
        if len(dados_arq["tarefas"]) >= MAX_TAREFAS:
            raise ValueError(f"a agenda está cheia ({MAX_TAREFAS} tarefas).")
        dados_arq["tarefas"].append(tarefa)
        salvar()

    _log(f"nova: {acao} {descrever_quando(tarefa)} (id {tarefa['id']})")
    return tarefa


def cancelar(id_ou_chave: str) -> bool:
    """Remove uma tarefa. True se achou."""
    alvo = (id_ou_chave or "").strip().lower()
    if not alvo:
        return False
    with _lock:
        dados = carregar()
        antes = len(dados["tarefas"])
        dados["tarefas"] = [
            t for t in dados["tarefas"]
            if t.get("id") != alvo and (t.get("chave") or "").lower() != alvo
        ]
        mudou = len(dados["tarefas"]) != antes
        if mudou:
            salvar()
    return mudou


def listar(incluir_internas: bool = False) -> List[dict]:
    """As tarefas, da mais próxima pra mais distante."""
    tarefas = [t for t in carregar()["tarefas"]
               if t.get("ativa") and (incluir_internas or t.get("visivel", True))]
    return sorted(tarefas, key=lambda t: t.get("proxima") or 0)


def resumo() -> str:
    """Bloco de texto pra Emily ler no chat."""
    tarefas = listar()
    if not tarefas:
        return "Não tenho nada marcado."
    linhas = []
    for t in tarefas[:15]:
        alvo = t.get("dados", {}).get("texto") or t.get("acao")
        quem = f" (pediu {t['criado_por']})" if t.get("criado_por") else ""
        linhas.append(f"- {descrever_quando(t)}: {alvo}{quem} [id {t['id']}]")
    if len(tarefas) > 15:
        linhas.append(f"(e mais {len(tarefas) - 15})")
    return "\n".join(linhas)


# ═════════════════════════════════════════════════════════════════
# O RELÓGIO
# ═════════════════════════════════════════════════════════════════

def _executar(tarefa: dict) -> None:
    funcao = _acoes.get(tarefa.get("acao"))
    if funcao is None:
        # Ação registrada por um módulo que não carregou nesta sessão. Não é erro
        # de tarefa: desativar seria perder o lembrete do Vitor porque um import
        # falhou. Fica esperando o módulo voltar.
        _log(f"ação '{tarefa.get('acao')}' não está registrada agora; "
             f"tarefa {tarefa.get('id')} fica esperando")
        return

    try:
        retorno = funcao(tarefa)
        tarefa["falhas"] = 0
        tarefa["vezes"] = int(tarefa.get("vezes") or 0) + 1
        if retorno:
            _log(f"{tarefa.get('acao')}: {str(retorno)[:120]}")
    except Exception as e:
        tarefa["falhas"] = int(tarefa.get("falhas") or 0) + 1
        _log(f"tarefa {tarefa.get('id')} ({tarefa.get('acao')}) falhou "
             f"{tarefa['falhas']}x: {type(e).__name__}: {e}")
        if os.getenv("EMILY_AGENDA_DEBUG"):
            traceback.print_exc()
        if tarefa["falhas"] >= MAX_FALHAS:
            tarefa["ativa"] = False
            _log(f"tarefa {tarefa.get('id')} desativada depois de "
                 f"{MAX_FALHAS} falhas seguidas")


def _um_giro(agora: Optional[float] = None) -> int:
    """
    Um passo do relógio. Devolve quantas tarefas rodaram.

    Separado do laço pra poder ser testado com uma hora fabricada, sem esperar o
    tempo passar de verdade.
    """
    agora = agora if agora is not None else time.time()
    rodaram = 0
    mudou = False

    with _lock:
        tarefas = list(carregar()["tarefas"])

    for tarefa in tarefas:
        if not tarefa.get("ativa"):
            continue
        proxima = float(tarefa.get("proxima") or 0)
        if proxima > agora:
            continue

        atraso = agora - proxima
        eh_unica = tarefa.get("tipo") == "uma_vez"
        tolerancia = TOLERANCIA_UMA_VEZ if eh_unica else TOLERANCIA_RECORRENTE

        if atraso > tolerancia:
            # Perdeu a janela. Ver a decisão 2 no topo do arquivo.
            _log(f"tarefa {tarefa.get('id')} perdeu a hora por "
                 f"{int(atraso / 60)} min; pulei essa ocorrência")
            if eh_unica:
                tarefa["ativa"] = False
            else:
                tarefa["proxima"] = _proxima_ocorrencia(tarefa, agora)
            mudou = True
            continue

        tarefa["ultima_vez"] = agora
        if eh_unica:
            tarefa["ativa"] = False
        else:
            tarefa["proxima"] = _proxima_ocorrencia(tarefa, agora)

        _executar(tarefa)
        rodaram += 1
        mudou = True

    if mudou:
        with _lock:
            dados = carregar()
            por_id = {t["id"]: t for t in tarefas}
            for i, t in enumerate(dados["tarefas"]):
                if t.get("id") in por_id:
                    dados["tarefas"][i] = por_id[t["id"]]
            # Tarefa de uma vez já cumprida sai do arquivo: histórico de
            # lembrete cumprido não serve pra nada e o arquivo só cresceria.
            dados["tarefas"] = [
                t for t in dados["tarefas"]
                if t.get("ativa") or t.get("tipo") != "uma_vez"
            ]
            salvar()

    return rodaram


def _laco() -> None:
    _log(f"relógio ligado (passo de {PASSO:.0f}s, "
         f"{len(listar(incluir_internas=True))} tarefas)")
    while not _parar.is_set():
        try:
            _um_giro()
        except Exception as e:
            # O laço NUNCA morre por causa de uma volta ruim. Se morresse, a
            # Emily perderia o relógio em silêncio e ninguém notaria até alguém
            # perguntar por um lembrete que nunca chegou.
            _log(f"giro falhou: {type(e).__name__}: {e}")
        _parar.wait(PASSO)
    _log("relógio parado")


def ligar() -> None:
    """Sobe o relógio. Chamar mais de uma vez não cria dois."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _parar.clear()
    _thread = threading.Thread(target=_laco, name="agenda", daemon=True)
    _thread.start()


def desligar() -> None:
    _parar.set()


def rodando() -> bool:
    return _thread is not None and _thread.is_alive()


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
# ═════════════════════════════════════════════════════════════════

def _diagnosticar() -> int:
    print("=" * 66)
    print("  AGENDA DA EMILY")
    print("=" * 66)
    print(f"  arquivo: {ARQUIVO}")
    print(f"  existe:  {os.path.exists(ARQUIVO)}")
    print(f"  passo:   {PASSO:.0f}s")
    conhecidas = acoes_conhecidas()
    print(f"  ações registradas: "
          f"{conhecidas or '(nenhuma — quem registra são os outros módulos)'}")

    print("\n-- leitura de horário --")
    for bruto in ("8", "08:30", "8h", "20:00", "23:59", "25:00", "abacaxi"):
        print(f"  {bruto!r:10} -> {ler_horario(bruto)}")

    print("\n-- leitura de dia --")
    for bruto in ("segunda", "terça", "sábado", "domingo", "sexta-feira", "xxx"):
        print(f"  {bruto!r:14} -> {ler_dia_da_semana(bruto)}")

    print("\n-- próxima ocorrência --")
    agora = time.time()
    exemplos = [
        {"tipo": "diario", "horario": "08:00"},
        {"tipo": "diario", "horario": "23:59"},
        {"tipo": "semanal", "horario": "20:00", "dia_semana": 5},
        {"tipo": "intervalo", "intervalo": 1800},
        {"tipo": "uma_vez", "quando": agora + 600},
    ]
    for e in exemplos:
        quando = _proxima_ocorrencia(e, agora)
        print(f"  {descrever_quando(e):24} -> "
              f"{time.strftime('%d/%m %H:%M', time.localtime(quando))} "
              f"(em {int((quando - agora) / 60)} min)")

    print("\n-- tarefas guardadas --")
    todas = listar(incluir_internas=True)
    if not todas:
        print("  (nenhuma)")
    for t in todas:
        marca = "" if t.get("visivel", True) else " [interna]"
        print(f"  {t['id']}  {t['acao']:22} {descrever_quando(t):22}"
              f" vezes={t.get('vezes', 0)} falhas={t.get('falhas', 0)}{marca}")

    print("\n-- teste do 'não dispara acumulado' --")
    registrar_acao("_teste", lambda t: "rodou")
    velha = {
        "id": "teste1", "acao": "_teste", "tipo": "diario", "horario": "08:00",
        "ativa": True, "falhas": 0, "vezes": 0, "visivel": False,
        "proxima": agora - TOLERANCIA_RECORRENTE - 60, "dados": {},
    }
    print(f"  tarefa atrasada {int((TOLERANCIA_RECORRENTE + 60) / 60)} min "
          f"(tolerância {int(TOLERANCIA_RECORRENTE / 60)} min)")
    atraso = agora - velha["proxima"]
    print(f"  atraso {int(atraso / 60)} min > tolerância? "
          f"{atraso > TOLERANCIA_RECORRENTE} -> "
          f"{'PULA, correto' if atraso > TOLERANCIA_RECORRENTE else 'EXECUTA'}")

    print("\n" + "=" * 66)
    print("Nada foi alterado: o diagnóstico só lê.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnosticar())

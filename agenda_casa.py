"""
agenda_casa.py — ações da casa marcadas para depois ("liga a air fryer daqui 20 minutos").

Mora na Oracle, junto do runtime: ela fica ligada o tempo todo e já fala com a
nuvem da Tuya, então o timer dispara mesmo com o PC desligado. O PC e o celular
mandam agendar, listar, mudar e cancelar pela rota /casa; a lista é uma só.

Cada agendamento guarda a CHAMADA da ferramenta (controlar_luz ou
controlar_tomada com os argumentos) e o horário. Na hora, executa exatamente
aquilo, com as mesmas travas de sempre (a do PC continua em controlar_tomada).

O arquivo fica em ~/.config/emily-runtime-cloud/casa/agenda.json (pasta da
casa). É "memória temporária": cumpriu, falhou ou foi cancelado, sai da lista
ativa e fica só no histórico curto.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import casa_inteligente as casa

ARQUIVO = "agenda.json"
FERRAMENTAS = ("controlar_luz", "controlar_tomada")
MAX_ATIVOS = 30
MAX_HISTORICO = 20
ATRASO_MAX_S = 6 * 3600       # acordou depois de uma queda? até 6 h ainda executa
FOLGA_PASSADO_S = 60          # "às 14h" dito às 14h00min30s vale como agora

_lock = threading.RLock()
_acordar = threading.Event()
_rodando = False


class AgendaErro(casa.CasaErro):
    pass


# ─── Tempo ────────────────────────────────────────────────────────

def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


_NUMEROS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
            "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12,
            "quinze": 15, "vinte": 20, "trinta": 30, "quarenta": 40, "quarenta e cinco": 45,
            "cinquenta": 50, "noventa": 90}
_UNIDADES = {"s": 1, "seg": 1, "segundo": 1, "segundos": 1, "min": 60, "minuto": 60, "minutos": 60,
             "h": 3600, "hora": 3600, "horas": 3600}
_PREFIXO_DURACAO = re.compile(r"^(?:daqui(?: a)?|dentro de|em|apos|depois de|por)\s+")
_MARCA_RELOGIO = re.compile(r"\b(?:as|a|amanha|hoje|manha|tarde|noite|meio dia|meia noite)\b|:")


def _duracao(texto: str) -> Optional[float]:
    """Segundos de '20 minutos', '1 hora e meia', 'meia hora', '1h30', 'uma hora'. None se não for."""
    t = texto
    for palavra in sorted(_NUMEROS, key=len, reverse=True):
        t = re.sub(rf"\b{palavra}\b", str(_NUMEROS[palavra]), t)
    if re.fullmatch(r"meia hora", t):
        return 1800.0
    m = re.fullmatch(r"(\d+) ?h ?(\d{1,2})(?: ?min(?:utos?)?)?", t)          # 1h30
    if m:
        return int(m[1]) * 3600 + int(m[2]) * 60
    unidade = r"(\d+(?:[.,]\d+)?) ?(segundos?|seg|s|minutos?|min|horas?|h)\b"
    partes = re.findall(unidade, t)
    if not partes:
        return None
    # Tudo que sobrar além das partes, de "e" e de "meia" final não é duração.
    sobra = re.sub(r"\b(?:e|meia)\b", " ", re.sub(unidade, " ", t)).strip()
    if sobra:
        return None
    total = sum(float(n.replace(",", ".")) * _UNIDADES[u] for n, u in partes)
    if re.search(r"\be meia$", t):
        total += 1800
    return total


def _relogio(texto: str, agora: datetime) -> Optional[datetime]:
    """'22:30', 'as 22h', '7 da manha', 'amanha 7h', 'meio dia'. None se não for horário."""
    amanha = bool(re.search(r"\bamanha\b", texto))
    r = texto.replace("meio dia", "12:00").replace("meia noite", "0:00")
    r = re.sub(r"\b(?:amanha|hoje|as|a|de|da|do|por volta)\b", " ", r)
    r = " ".join(r.split())
    m = re.fullmatch(r"(\d{1,2})(?:(?::|h) ?(\d{2})?)?(?: ?horas?| ?h)?(?: (manha|tarde|noite))?", r)
    if not m:
        return None
    h, mi = int(m[1]), int(m[2] or 0)
    if m[3] in {"tarde", "noite"} and h < 12:
        h += 12
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise AgendaErro(f"Horário inválido: '{texto}'.")
    alvo = agora.replace(hour=h, minute=mi, second=0, microsecond=0)
    if amanha:
        alvo += timedelta(days=1)
    elif alvo <= agora - timedelta(seconds=FOLGA_PASSADO_S):
        alvo += timedelta(days=1)        # hora do relógio que já passou hoje: amanhã
    return alvo


def resolver_quando(quando: str, *, agora: Optional[datetime] = None) -> datetime:
    """'20 minutos', 'daqui 1 hora e meia', 'meia hora', '22:30', 'às 7h', 'amanhã 7h', ISO.

    Com "daqui/em/dentro de" é sempre duração. Com "às", "amanhã", ":" ou período do
    dia é sempre horário. Um "22h" solto vale como horário; "20 minutos" solto, duração.
    """
    agora = agora or datetime.now()
    bruto = str(quando or "").strip()
    if not bruto:
        raise AgendaErro("Diga quando: daqui X minutos ou um horário (ex.: 22:30).")
    try:
        alvo = datetime.fromisoformat(bruto)
        return alvo.astimezone().replace(tzinfo=None) if alvo.tzinfo else alvo
    except ValueError:
        pass
    q = _normalizar(bruto)
    sem_prefixo = _PREFIXO_DURACAO.sub("", q)
    if sem_prefixo != q:                                   # "daqui 20 minutos"
        segundos = _duracao(sem_prefixo)
        if segundos is not None:
            return agora + timedelta(seconds=segundos)
    elif not _MARCA_RELOGIO.search(q):                     # "20 minutos", "meia hora"
        segundos = _duracao(q)
        if segundos is not None and not re.fullmatch(r"\d{1,2} ?h(?: ?\d{2})?", q):
            return agora + timedelta(seconds=segundos)
    alvo = _relogio(q, agora)
    if alvo is not None:
        return alvo
    raise AgendaErro(f"Não entendi o quando '{quando}'. Use 'daqui 20 minutos' ou '22:30'.")


def _rotulo_hora(ts: float, agora: Optional[float] = None) -> str:
    agora = agora if agora is not None else time.time()
    alvo = datetime.fromtimestamp(ts)
    hoje = datetime.fromtimestamp(agora).date()
    dia = "" if alvo.date() == hoje else ("amanhã " if alvo.date() == hoje + timedelta(days=1)
                                          else alvo.strftime("%d/%m "))
    falta = ts - agora
    em = (f"daqui {round(falta)} s" if falta < 60 else f"daqui {round(falta / 60)} min" if falta < 3600
          else f"daqui {falta / 3600:.1f} h".replace(".", ","))
    return f"{dia}às {alvo:%H:%M} ({em})"


# ─── Persistência ─────────────────────────────────────────────────

def _caminho() -> Path:
    return casa.pasta() / ARQUIVO


def _ler() -> dict:
    try:
        dados = json.loads(_caminho().read_text(encoding="utf-8"))
        if isinstance(dados, dict) and isinstance(dados.get("ativos"), list):
            dados.setdefault("historico", [])
            return dados
    except (OSError, ValueError):
        pass
    return {"ativos": [], "historico": []}


def _salvar(dados: dict) -> None:
    caminho = _caminho()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, caminho)


def _arquivar(dados: dict, item: dict, estado: str, mensagem: str) -> None:
    dados["ativos"] = [a for a in dados["ativos"] if a["id"] != item["id"]]
    dados["historico"] = ([dict(item, estado=estado, resultado=mensagem[:300], fim=time.time())]
                          + dados["historico"])[:MAX_HISTORICO]


# ─── Descrição ────────────────────────────────────────────────────

def descrever_acao(ferramenta: str, args: dict) -> str:
    a = args.get("acao", "")
    if ferramenta == "controlar_luz":
        if a == "cor":
            return f"deixar a luz {args.get('cor', '')}".strip()
        if a == "brilho":
            return f"luz em {args.get('brilho')}%"
        if a == "temperatura":
            return f"luz branca em {args.get('temperatura')}% de temperatura"
        return {"ligar": "ligar a luz", "desligar": "desligar a luz", "alternar": "alternar a luz",
                "branco": "luz branca"}.get(a, f"luz: {a}")
    aparelho = args.get("aparelho") or "a tomada"
    return f"{'ligar' if a == 'ligar' else 'desligar' if a == 'desligar' else a} {aparelho}".strip()


def _resumo(item: dict, agora: Optional[float] = None) -> str:
    return f"[{item['id']}] {item['descricao']} {_rotulo_hora(item['quando'], agora)}"


# ─── Frase do aviso (falada, na primeira pessoa) ───────────────────

_FEMININOS = {"air fryer", "airfryer", "fritadeira", "cafeteira", "chaleira", "luminaria",
              "luz", "lampada", "tomada", "geladeira"}


def _artigo(nome: str) -> str:
    n = _normalizar(nome)
    return "a" if n in _FEMININOS else "o"


def _passado_e_infinitivo(item: dict) -> Tuple[str, str]:
    """('liguei a air fryer', 'ligar a air fryer') a partir do que estava agendado."""
    a = item["args"]
    acao = a.get("acao", "")
    if item["ferramenta"] == "controlar_luz":
        extra = {"cor": (f"deixei a luz {a.get('cor', '')}".strip(), f"deixar a luz {a.get('cor', '')}".strip()),
                 "brilho": (f"deixei a luz com {a.get('brilho')}% de brilho", f"ajustar o brilho da luz"),
                 "temperatura": ("ajustei a temperatura da luz", "ajustar a temperatura da luz"),
                 "branco": ("deixei a luz branca", "deixar a luz branca"),
                 "alternar": ("alternei a luz", "alternar a luz"),
                 "ligar": ("liguei a luz", "ligar a luz"),
                 "desligar": ("desliguei a luz", "desligar a luz")}
        return extra.get(acao, ("mexi na luz", "mexer na luz"))
    nome = a.get("aparelho") or "a tomada"
    quem = f"{_artigo(nome)} {nome}" if a.get("aparelho") else "a tomada"
    if acao == "ligar":
        return f"liguei {quem}", f"ligar {quem}"
    if acao == "desligar":
        return f"desliguei {quem}", f"desligar {quem}"
    return f"mexi em {quem}", f"mexer em {quem}"


def frase_aviso(item: dict, ok: bool, mensagem: str = "", expirado: bool = False) -> str:
    feito, infinitivo = _passado_e_infinitivo(item)
    if expirado:
        return f"Não consegui {infinitivo} na hora marcada: a nuvem ficou fora do ar."
    if ok:
        return f"Pronto, {feito}."
    motivo = " ".join(str(mensagem or "").split())[:160]
    return f"Não consegui {infinitivo}." + (f" {motivo}" if motivo else "")


# ─── Operações ────────────────────────────────────────────────────

def _validar_chamada(ferramenta: str, args: dict) -> dict:
    if ferramenta not in FERRAMENTAS:
        raise AgendaErro("Só dá para agendar ações da luz (controlar_luz) e da tomada (controlar_tomada).")
    if not isinstance(args, dict) or not isinstance(args.get("acao"), str):
        raise AgendaErro("Faltou a ação a agendar (ligar, desligar, cor...).")
    permitidos = ({"acao", "cor", "brilho", "temperatura", "alvo"} if ferramenta == "controlar_luz"
                  else {"acao", "aparelho", "aguardar_pc"})
    limpo = {k: v for k, v in args.items() if k in permitidos and v not in (None, "")}
    acoes = casa.ACOES_LUZ if ferramenta == "controlar_luz" else ("ligar", "desligar")
    if limpo["acao"] not in acoes:
        raise AgendaErro(f"Ação '{limpo['acao']}' não pode ser agendada. Use: {', '.join(acoes)}.")
    if ferramenta == "controlar_tomada":
        limpo["aparelho"] = casa.limpar_aparelho(limpo.get("aparelho", "")) or (
            (casa.ultimo_aparelho() or {}).get("nome", ""))
        if not limpo["aparelho"]:
            raise AgendaErro("Qual aparelho está na tomada? Diga o nome para eu agendar.")
    return limpo


def agendar(ferramenta: str, args: dict, quando: str, *, agora: Optional[datetime] = None) -> dict:
    agora = agora or datetime.now()
    alvo = resolver_quando(quando, agora=agora)
    if alvo <= agora - timedelta(seconds=FOLGA_PASSADO_S):
        raise AgendaErro("Esse horário já passou.")
    if alvo - agora > timedelta(days=7):
        raise AgendaErro("Dá para agendar no máximo 7 dias à frente.")
    limpo = _validar_chamada(ferramenta, args)
    with _lock:
        dados = _ler()
        if len(dados["ativos"]) >= MAX_ATIVOS:
            raise AgendaErro(f"Já tem {MAX_ATIVOS} agendamentos. Cancele algum antes.")
        item = {"id": secrets.token_hex(3), "ferramenta": ferramenta, "args": limpo,
                "quando": alvo.timestamp(), "criado": agora.timestamp(),
                "descricao": descrever_acao(ferramenta, limpo)}
        dados["ativos"].append(item)
        dados["ativos"].sort(key=lambda a: a["quando"])
        _salvar(dados)
    _acordar.set()
    return {"ok": True, "id": item["id"], "agendamento": item,
            "mensagem": f"Agendado: {item['descricao']} {_rotulo_hora(item['quando'], agora.timestamp())}."}


def listar(*, agora: Optional[float] = None) -> dict:
    with _lock:
        dados = _ler()
    ativos = dados["ativos"]
    if not ativos:
        texto = "Nenhuma ação da casa agendada."
    else:
        texto = "Agendado:\n" + "\n".join("- " + _resumo(a, agora) for a in ativos)
    ultimos = [h for h in dados["historico"][:3]]
    if ultimos:
        texto += "\nÚltimos: " + "; ".join(
            f"{h['descricao']} ({ {'feito': 'feito', 'falhou': 'falhou', 'cancelado': 'cancelado', 'expirado': 'expirou'}.get(h['estado'], h['estado'])})"
            for h in ultimos)
    return {"ok": True, "ativos": ativos, "historico": dados["historico"], "mensagem": texto}


def _achar(dados: dict, referencia: str) -> List[dict]:
    """Por id exato; senão por palavras da descrição ('air fryer', 'luz'). Vazio = todos."""
    ref = _normalizar(referencia)
    if not ref:
        return list(dados["ativos"])
    por_id = [a for a in dados["ativos"] if a["id"] == ref]
    if por_id:
        return por_id
    palavras = [p for p in re.split(r"\W+", ref) if p and p not in {"o", "a", "de", "da", "do", "timer", "agendamento"}]
    return [a for a in dados["ativos"] if all(p in _normalizar(a["descricao"]) for p in palavras)]


def cancelar(referencia: str = "", *, todos: bool = False) -> dict:
    with _lock:
        dados = _ler()
        alvos = _achar(dados, referencia)
        if not alvos:
            return {"ok": False, "mensagem": "Não achei esse agendamento. " + listar()["mensagem"]}
        if len(alvos) > 1 and not todos:
            return {"ok": False, "ambiguo": True, "mensagem": (
                "Tem mais de um agendamento assim; qual deles? "
                + "; ".join(_resumo(a) for a in alvos))}
        for a in alvos:
            _arquivar(dados, a, "cancelado", "cancelado a pedido")
        _salvar(dados)
    _acordar.set()
    return {"ok": True, "mensagem": "Cancelado: " + "; ".join(a["descricao"] for a in alvos) + "."}


def remarcar(referencia: str, quando: str, *, agora: Optional[datetime] = None) -> dict:
    agora = agora or datetime.now()
    alvo = resolver_quando(quando, agora=agora)
    if alvo <= agora - timedelta(seconds=FOLGA_PASSADO_S):
        raise AgendaErro("Esse horário já passou.")
    with _lock:
        dados = _ler()
        achados = _achar(dados, referencia)
        if len(achados) != 1:
            if not achados:
                return {"ok": False, "mensagem": "Não achei esse agendamento. " + listar()["mensagem"]}
            return {"ok": False, "ambiguo": True, "mensagem": (
                "Tem mais de um agendamento assim; qual deles? " + "; ".join(_resumo(a) for a in achados))}
        item = achados[0]
        item["quando"] = alvo.timestamp()
        dados["ativos"].sort(key=lambda a: a["quando"])
        _salvar(dados)
    _acordar.set()
    return {"ok": True, "agendamento": item,
            "mensagem": f"Remarcado: {item['descricao']} {_rotulo_hora(item['quando'], agora.timestamp())}."}


def executar_agora(referencia: str, executar: Callable[[str, dict], dict]) -> dict:
    """'liga a air fryer agora' com um agendamento pendente: faz já e tira da lista."""
    with _lock:
        dados = _ler()
        achados = _achar(dados, referencia)
        if len(achados) != 1:
            return {"ok": False, "mensagem": ("Não achei esse agendamento." if not achados else
                    "Tem mais de um agendamento assim; qual deles? " + "; ".join(_resumo(a) for a in achados))}
        item = achados[0]
    return _disparar(item, executar, motivo="antecipado")


def resolver_conflitos(ferramenta: str, args: dict) -> List[str]:
    """Uma ação manual na mesma coisa torna o agendamento redundante ou contraditório.

    Ex.: 'liga a air fryer daqui 20 min' e depois 'liga a air fryer' agora: o
    agendado deixa de fazer sentido e sai. Devolve as descrições removidas.
    """
    if ferramenta not in FERRAMENTAS:
        return []
    acao = (args or {}).get("acao")
    aparelho = casa.limpar_aparelho((args or {}).get("aparelho", "")) if ferramenta == "controlar_tomada" else ""
    removidos = []
    with _lock:
        dados = _ler()
        for a in list(dados["ativos"]):
            if a["ferramenta"] != ferramenta:
                continue
            if ferramenta == "controlar_tomada" and aparelho and a["args"].get("aparelho") != aparelho:
                continue
            # Só a MESMA ação: desligar agora não cancela um "ligar às 7h".
            if a["args"].get("acao") == acao and acao in {"ligar", "desligar"}:
                _arquivar(dados, a, "cancelado", "feito antes, manualmente")
                removidos.append(a["descricao"])
        if removidos:
            _salvar(dados)
    return removidos


# ─── Disparo ──────────────────────────────────────────────────────

def _disparar(item: dict, executar: Callable[[str, dict], dict], motivo: str = "",
              avisar: Optional[Callable[[str], object]] = None) -> dict:
    try:
        r = executar(item["ferramenta"], item["args"])
        ok = bool(r.get("ok"))
        mensagem = str(r.get("mensagem") or ("Feito." if ok else "Não deu certo."))
    except Exception as e:  # noqa: BLE001 - o agendador nunca cai por uma ação
        ok, mensagem = False, str(e)
    with _lock:
        dados = _ler()
        if any(a["id"] == item["id"] for a in dados["ativos"]):
            _arquivar(dados, item, "feito" if ok else "falhou", mensagem)
            _salvar(dados)
    prefixo = "Antecipado: " if motivo == "antecipado" else ""
    print(f"[AGENDA-CASA] {item['descricao']}: {'ok' if ok else 'falhou'} — {mensagem[:120]}", flush=True)
    _avisar(avisar, frase_aviso(item, ok, mensagem))
    return {"ok": ok, "mensagem": prefixo + mensagem}


def _avisar(avisar: Optional[Callable[[str], object]], texto: str) -> None:
    """Aviso é extra: falhar aqui nunca desfaz nem repete a ação já feita."""
    if avisar is None:
        return
    try:
        avisar(texto)
    except Exception as e:  # noqa: BLE001
        print(f"[AGENDA-CASA] aviso falhou: {e}", flush=True)


def vencidos(agora: Optional[float] = None) -> List[dict]:
    agora = agora if agora is not None else time.time()
    with _lock:
        return [a for a in _ler()["ativos"] if a["quando"] <= agora]


def rodar_vencidos(executar: Callable[[str, dict], dict], agora: Optional[float] = None,
                  avisar: Optional[Callable[[str], object]] = None) -> int:
    agora = agora if agora is not None else time.time()
    feitos = 0
    for item in vencidos(agora):
        if agora - item["quando"] > ATRASO_MAX_S:
            with _lock:
                dados = _ler()
                _arquivar(dados, item, "expirado", "a Oracle ficou fora do ar na hora marcada")
                _salvar(dados)
            _avisar(avisar, frase_aviso(item, False, expirado=True))
            continue
        _disparar(item, executar, avisar=avisar)
        feitos += 1
    return feitos


def proximo(agora: Optional[float] = None) -> Optional[float]:
    with _lock:
        ativos = _ler()["ativos"]
    return min((a["quando"] for a in ativos), default=None)


def iniciar(executar: Callable[[str, dict], dict],
            avisar: Optional[Callable[[str], object]] = None) -> None:
    """Thread do agendador (uma por processo). Dorme até o próximo horário ou até mudar a lista."""
    global _rodando
    with _lock:
        if _rodando:
            return
        _rodando = True

    def laco():
        while True:
            try:
                rodar_vencidos(executar, avisar=avisar)
                prox = proximo()
                espera = 300.0 if prox is None else max(0.2, min(300.0, prox - time.time()))
            except Exception as e:  # noqa: BLE001
                print(f"[AGENDA-CASA] erro no agendador: {e}", flush=True)
                espera = 30.0
            _acordar.wait(espera)
            _acordar.clear()

    threading.Thread(target=laco, name="agenda-casa", daemon=True).start()
    print("[AGENDA-CASA] agendador iniciado", flush=True)

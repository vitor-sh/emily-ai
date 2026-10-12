"""
casa_inteligente.py — lâmpada e tomada Tuya da casa do Vitor.

Dois caminhos para falar com os aparelhos, com o MESMO vocabulário:

- local: tinytuya direto na rede de casa (protocolo 3.5, chave local). É o
  que a Emily do PC usa: rápido e sem depender da internet.
- nuvem: Tuya Cloud (openapi.tuyaus.com). É o que a Oracle usa para o
  Android e o Discord, porque precisa funcionar com o PC desligado — que é
  justamente quando a tomada importa.

Os dados ficam FORA do projeto (nunca no git):
  PC:     ~/.config/emily-casa/{tinytuya.json, devices.json, casa.json}
  Oracle: ~/.config/emily-runtime-cloud/casa/ (sem as chaves locais)
tinytuya.json e devices.json são os que o `python -m tinytuya wizard` gera.
casa.json é opcional: apelidos, qual tomada usar (energia_pc, se houver mais de
uma) e o limite de consumo que conta como "PC ligado". tomada-estado.json é da
própria Emily: último aparelho informado e consumo típico de cada um.

Todo comando é ABSOLUTO (liga, desliga, cor X, brilho Y). "Alternar" é
resolvido lendo o estado antes. Por isso uma falha local pode cair para a
nuvem sem risco de aplicar duas vezes o contrário do pedido.

A tomada serve ao APARELHO QUE O VITOR CITAR (PC, ventilador, air fryer...) e
ele troca de aparelho quando quiser. A Tuya não informa o que está espetado,
só os watts; então o nome vem do pedido (controlar_tomada) e a Emily guarda o
último aparelho e o consumo típico de cada um, só para avisar quando o consumo
não combina. Só o PC tem trava: a tomada dele alimenta o estabilizador. Cortar
com ele ligado é igual a
puxar o cabo: perde a sessão e pode corromper dados. energia_pc() só corta
direto quando o PC parece desligado (gateway sem resposta E consumo baixo);
fora isso, aguarda o PC desligar ou exige uma confirmação explícita.
"""

from __future__ import annotations

import colorsys
import json
import os
import re
import secrets
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional


class CasaErro(Exception):
    """Falha que deve virar mensagem para o Vitor, não traceback."""


# ─── Configuração ──────────────────────────────────────────────────

def pasta() -> Path:
    configurada = os.getenv("EMILY_CASA_DIR", "").strip()
    return Path(configurada).expanduser() if configurada else Path.home() / ".config" / "emily-casa"


def transporte_padrao() -> str:
    """auto (local e depois nuvem), local ou nuvem. A Oracle usa 'nuvem'."""
    valor = os.getenv("EMILY_CASA_TRANSPORTE", "auto").strip().lower()
    return valor if valor in {"auto", "local", "nuvem"} else "auto"


def _ler_json(nome: str, padrao):
    caminho = pasta() / nome
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return padrao
    except (OSError, ValueError) as e:
        raise CasaErro(f"Não consegui ler {nome} da casa: {e}") from e


def configurada() -> bool:
    return (pasta() / "devices.json").is_file()


TIPOS = {"dj": "luz", "dd": "luz", "dc": "luz", "fwd": "luz", "xdd": "luz",
         "cz": "tomada", "pc": "tomada", "kg": "tomada"}

LIMITE_PC_LIGADO_W = 30.0


def _preferencias() -> dict:
    prefs = _ler_json("casa.json", {})
    return prefs if isinstance(prefs, dict) else {}


def dispositivos() -> List[dict]:
    """Aparelhos conhecidos, já com tipo, apelido e mapa código→DP."""
    brutos = _ler_json("devices.json", [])
    if not isinstance(brutos, list):
        raise CasaErro("devices.json da casa está em formato inesperado.")
    prefs = _preferencias()
    apelidos = prefs.get("apelidos") or {}
    saida = []
    for d in brutos:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        tipo = TIPOS.get(str(d.get("category", "")), "outro")
        mapping = d.get("mapping") or {}
        codigos = {str(m.get("code")): str(dp) for dp, m in mapping.items()
                   if isinstance(m, dict) and m.get("code")}
        padrao = {"luz": "Lâmpada", "tomada": "Tomada"}.get(tipo, d.get("name") or "Aparelho")
        saida.append({
            "id": str(d["id"]), "nome": str(apelidos.get(d["id"]) or padrao),
            "nome_app": str(d.get("name") or ""), "tipo": tipo,
            "ip": str(d.get("ip") or ""), "chave": str(d.get("key") or ""),
            "versao": str(d.get("version") or "3.3"), "mapping": mapping, "codigos": codigos,
        })
    return saida


def _normalizar(texto: str) -> str:
    bruto = unicodedata.normalize("NFD", str(texto or "").lower())
    return " ".join("".join(c for c in bruto if unicodedata.category(c) != "Mn").split())


def luzes() -> List[dict]:
    return [d for d in dispositivos() if d["tipo"] == "luz"]


def tomada_pc() -> Optional[dict]:
    """A tomada do estabilizador do PC: a indicada em casa.json, ou a única que existir."""
    tomadas = [d for d in dispositivos() if d["tipo"] == "tomada"]
    indicada = str(_preferencias().get("energia_pc") or "")
    if indicada:
        return next((d for d in tomadas if d["id"] == indicada), None)
    return tomadas[0] if len(tomadas) == 1 else None


# A tomada é uma só e serve ao aparelho que o Vitor citar; o nome histórico
# tomada_pc() continua valendo para o fluxo de energia do PC.
tomada = tomada_pc


def _limite_pc_w() -> float:
    try:
        return float(_preferencias().get("limite_pc_ligado_w", LIMITE_PC_LIGADO_W))
    except (TypeError, ValueError):
        return LIMITE_PC_LIGADO_W


def escolher_luz(alvo: str = "") -> dict:
    todas = luzes()
    if not todas:
        raise CasaErro("Nenhuma lâmpada configurada ainda.")
    alvo_n = _normalizar(alvo)
    genericos = {"", "luz", "a luz", "lampada", "a lampada", "minha luz", "minha lampada"}
    if alvo_n in genericos:
        if len(todas) == 1:
            return todas[0]
        raise CasaErro("Tem mais de uma lâmpada. Qual delas? " + ", ".join(d["nome"] for d in todas))
    achada = next((d for d in todas if alvo_n in (_normalizar(d["nome"]), _normalizar(d["nome_app"]), d["id"])), None) \
        or next((d for d in todas if alvo_n in _normalizar(d["nome"]) or alvo_n in _normalizar(d["nome_app"])), None)
    if not achada:
        raise CasaErro(f"Não achei a lâmpada '{alvo}'. As que existem: " + ", ".join(d["nome"] for d in todas))
    return achada


# ─── Transporte ────────────────────────────────────────────────────

_lock = threading.RLock()
_nuvem = None


def _tinytuya():
    """A biblioteca pode não estar na versão compilada; isso é um aviso, não um traceback."""
    try:
        import tinytuya
    except ImportError as e:
        raise CasaErro(
            "Esta Emily compilada não traz a biblioteca da Tuya (tinytuya). "
            "Recompile com build_emily_linux.py, ou controle pelo celular."
        ) from e
    return tinytuya


def _cliente_nuvem():
    global _nuvem
    with _lock:
        if _nuvem is not None:
            return _nuvem
        cfg = _ler_json("tinytuya.json", None)
        if not isinstance(cfg, dict) or not cfg.get("apiKey") or not cfg.get("apiSecret"):
            raise CasaErro("A nuvem da Tuya não está configurada (falta tinytuya.json).")
        tinytuya = _tinytuya()
        cliente = tinytuya.Cloud(apiRegion=cfg.get("apiRegion") or "us", apiKey=cfg["apiKey"],
                                 apiSecret=cfg["apiSecret"], apiDeviceID=cfg.get("apiDeviceID") or "")
        if cliente.error or not cliente.token:
            raise CasaErro(_erro_tuya(cliente.error) or "A nuvem da Tuya recusou as credenciais.")
        _nuvem = cliente
        return cliente


def _erro_tuya(resposta) -> str:
    if not isinstance(resposta, dict):
        return ""
    texto = str(resposta.get("Payload") or resposta.get("Error") or resposta.get("msg") or "")
    if "permission" in texto.lower() or "1010" in texto or "28841004" in texto:
        return ("A Tuya recusou por permissão. O plano IoT Core do projeto no iot.tuya.com "
                "pode ter expirado; renove em Cloud > Cloud Services > IoT Core.")
    return texto


def _dispositivo_local(d: dict):
    if not d["ip"] or not d["chave"]:
        raise CasaErro(f"{d['nome']} não tem IP ou chave local salvos.")
    tinytuya = _tinytuya()
    dev = tinytuya.Device(d["id"], d["ip"], d["chave"], version=float(d["versao"]))
    dev.set_socketTimeout(2.5)
    dev.set_socketRetryLimit(1)
    return dev


def _converter_dp(d: dict, dp: str, valor):
    """Valor como a nuvem e o resto deste módulo entendem (cor como dict h/s/v)."""
    codigo = (d["mapping"].get(dp) or {}).get("code", dp)
    if codigo.startswith("colour_data") and isinstance(valor, str) and re.fullmatch(r"[0-9a-fA-F]{12}", valor):
        return codigo, {"h": int(valor[0:4], 16), "s": int(valor[4:8], 16), "v": int(valor[8:12], 16)}
    return codigo, valor


def _ler_local(d: dict) -> Dict[str, object]:
    resposta = _dispositivo_local(d).status()
    if not isinstance(resposta, dict) or "dps" not in resposta:
        raise CasaErro(f"{d['nome']} não respondeu na rede de casa ({_erro_tuya(resposta) or 'sem resposta'}).")
    return dict(_converter_dp(d, str(dp), v) for dp, v in resposta["dps"].items())


def _ler_nuvem(d: dict) -> Dict[str, object]:
    resposta = _cliente_nuvem().getstatus(d["id"])
    if not isinstance(resposta, dict) or not resposta.get("success"):
        raise CasaErro(f"A nuvem da Tuya não devolveu o estado de {d['nome']}: {_erro_tuya(resposta) or 'sem resposta'}.")
    saida = {}
    for item in resposta.get("result") or []:
        valor = item.get("value")
        if str(item.get("code", "")).startswith("colour_data") and isinstance(valor, str):
            try:
                valor = json.loads(valor)
            except ValueError:
                pass
        saida[str(item.get("code"))] = valor
    return saida


def _enviar_local(d: dict, comandos: Dict[str, object]) -> None:
    dados = {}
    for codigo, valor in comandos.items():
        dp = d["codigos"].get(codigo)
        if dp is None:
            raise CasaErro(f"{d['nome']} não aceita '{codigo}'.")
        if codigo.startswith("colour_data") and isinstance(valor, dict):
            valor = "%04x%04x%04x" % (int(valor["h"]), int(valor["s"]), int(valor["v"]))
        dados[int(dp)] = valor
    resposta = _dispositivo_local(d).set_multiple_values(dados)
    if isinstance(resposta, dict) and (resposta.get("Error") or resposta.get("Err")):
        raise CasaErro(f"{d['nome']} não aceitou o comando na rede de casa ({_erro_tuya(resposta)}).")
    if resposta is None:
        raise CasaErro(f"{d['nome']} não confirmou o comando na rede de casa.")


def _enviar_nuvem(d: dict, comandos: Dict[str, object]) -> None:
    corpo = {"commands": [{"code": c, "value": v} for c, v in comandos.items()]}
    resposta = _cliente_nuvem().sendcommand(d["id"], corpo)
    if not isinstance(resposta, dict) or not resposta.get("success"):
        raise CasaErro(f"A nuvem da Tuya não aplicou o comando em {d['nome']}: {_erro_tuya(resposta) or 'sem resposta'}.")


def _via(d: dict, local: Callable, nuvem: Callable, transporte: str):
    """Tenta local e cai para a nuvem no modo auto. Devolve (resultado, caminho)."""
    transporte = transporte or transporte_padrao()
    erros = []
    if transporte in {"auto", "local"} and d["chave"] and d["ip"]:
        try:
            return local(), "local"
        except Exception as e:  # noqa: BLE001 - qualquer falha local tenta a nuvem
            erros.append(str(e))
            if transporte == "local":
                raise CasaErro(str(e)) from e
    if transporte in {"auto", "nuvem"}:
        try:
            return nuvem(), "nuvem"
        except CasaErro as e:
            erros.append(str(e))
        except Exception as e:  # noqa: BLE001
            erros.append(f"nuvem: {e}")
    # Local e nuvem costumam falhar pelo mesmo motivo (ex.: biblioteca ausente):
    # repetir a mesma frase duas vezes só polui a tela.
    unicos = list(dict.fromkeys(erros))
    raise CasaErro(" ".join(unicos) or f"Sem caminho para falar com {d['nome']}.")


def ler(d: dict, transporte: str = "") -> Dict[str, object]:
    valores, _ = _via(d, lambda: _ler_local(d), lambda: _ler_nuvem(d), transporte)
    return valores


def enviar(d: dict, comandos: Dict[str, object], transporte: str = "") -> str:
    with _lock:
        _, caminho = _via(d, lambda: _enviar_local(d, comandos), lambda: _enviar_nuvem(d, comandos), transporte)
    return caminho


# ─── Lâmpada ───────────────────────────────────────────────────────

CORES = {
    "vermelho": (255, 0, 0), "vermelha": (255, 0, 0), "laranja": (255, 100, 0),
    "amarelo": (255, 190, 0), "amarela": (255, 190, 0), "verde": (0, 255, 0),
    "verde limao": (150, 255, 0), "ciano": (0, 255, 255), "azul claro": (0, 160, 255),
    "azul": (0, 0, 255), "roxo": (130, 0, 255), "roxa": (130, 0, 255),
    "lilas": (190, 120, 255), "violeta": (160, 60, 255), "rosa": (255, 60, 150),
    "pink": (255, 20, 147), "magenta": (255, 0, 255),
}
CORES_CONHECIDAS = ("vermelho", "laranja", "amarelo", "verde", "verde limão", "ciano",
                    "azul claro", "azul", "roxo", "lilás", "violeta", "rosa", "pink", "magenta")


def _hsv_da_cor(cor: str) -> Optional[dict]:
    texto = _normalizar(cor).replace("#", "")
    rgb = CORES.get(texto)
    if rgb is None and re.fullmatch(r"[0-9a-f]{6}", texto):
        rgb = tuple(int(texto[i:i + 2], 16) for i in (0, 2, 4))
    if rgb is None:
        return None
    h, s, _ = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    return {"h": round(h * 360) % 360, "s": round(s * 1000), "v": 1000}


def _nome_da_cor(hsv: dict) -> str:
    if not isinstance(hsv, dict):
        return ""
    h, s = int(hsv.get("h", 0)), int(hsv.get("s", 0))
    if s < 150:
        return "branco"
    unicos = {"vermelho": 0, "laranja": 24, "amarelo": 45, "verde limão": 85, "verde": 120,
              "ciano": 180, "azul claro": 202, "azul": 240, "roxo": 271, "lilás": 266,
              "magenta": 300, "rosa": 331}
    return min(unicos, key=lambda nome: min(abs(h - unicos[nome]), 360 - abs(h - unicos[nome])))


def _pct_para(valor: float, minimo: int, maximo: int) -> int:
    valor = max(0.0, min(100.0, float(valor)))
    return round(minimo + (maximo - minimo) * valor / 100)


def _para_pct(valor, minimo: int, maximo: int) -> int:
    try:
        return round((float(valor) - minimo) * 100 / (maximo - minimo))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


def resumo_luz(d: dict, v: Dict[str, object]) -> dict:
    modo = str(v.get("work_mode") or "white")
    cor = v.get("colour_data_v2") or v.get("colour_data") or {}
    if modo == "colour" and isinstance(cor, dict):
        brilho = _para_pct(cor.get("v", 0), 10, 1000)
        descricao_cor = _nome_da_cor(cor)
    else:
        brilho = _para_pct(v.get("bright_value_v2", v.get("bright_value", 0)), 10, 1000)
        descricao_cor = "branca"
    temperatura = _para_pct(v.get("temp_value_v2", v.get("temp_value", 0)), 0, 1000)
    return {"id": d["id"], "nome": d["nome"], "tipo": "luz", "ligada": bool(v.get("switch_led")),
            "modo": {"white": "branco", "colour": "cor", "scene": "cena", "music": "música"}.get(modo, modo),
            "cor": descricao_cor, "brilho": max(1, min(100, brilho)),
            "temperatura": max(0, min(100, temperatura)), "hsv": cor if isinstance(cor, dict) else None}


ACOES_LUZ = ("ligar", "desligar", "alternar", "cor", "brilho", "temperatura", "branco")


def controlar_luz(acao: str, *, alvo: str = "", cor: str = "", brilho=None, temperatura=None,
                  transporte: str = "") -> dict:
    acao = _normalizar(acao).replace(" ", "_")
    if acao not in ACOES_LUZ:
        raise CasaErro(f"Ação de luz desconhecida: '{acao}'. Use " + ", ".join(ACOES_LUZ) + ".")
    d = escolher_luz(alvo)
    cor_n = _normalizar(cor)
    # Pedidos de "luz quente/fria/branca" chegam como cor; são o modo branco.
    if acao == "cor" and cor_n in {"branco", "branca", "quente", "fria", "neutra", "amarelada"}:
        acao = "branco" if cor_n in {"branco", "branca", "neutra"} else "temperatura"
        if temperatura is None:
            temperatura = {"quente": 0, "amarelada": 15, "fria": 100}.get(cor_n, 50)
    comandos: Dict[str, object] = {}
    atual: Optional[Dict[str, object]] = None

    def estado_atual():
        nonlocal atual
        if atual is None:
            atual = ler(d, transporte)
        return atual

    if acao in {"ligar", "desligar"}:
        comandos["switch_led"] = acao == "ligar"
    elif acao == "alternar":
        comandos["switch_led"] = not bool(estado_atual().get("switch_led"))
    elif acao == "cor":
        hsv = _hsv_da_cor(cor)
        if hsv is None:
            raise CasaErro(f"Não conheço a cor '{cor}'. Conheço " + ", ".join(CORES_CONHECIDAS)
                           + ", branca, quente e fria, ou um código como #ff8800.")
        if brilho is not None:
            hsv["v"] = _pct_para(brilho, 10, 1000)
        else:
            anterior = estado_atual()
            cor_anterior = anterior.get("colour_data_v2") if anterior.get("work_mode") == "colour" else None
            hsv["v"] = int(cor_anterior.get("v", 1000)) if isinstance(cor_anterior, dict) else \
                int(anterior.get("bright_value_v2") or 1000)
        comandos.update({"switch_led": True, "work_mode": "colour", "colour_data_v2": hsv})
    elif acao == "brilho":
        if brilho is None:
            raise CasaErro("Diga o brilho de 1 a 100.")
        v = estado_atual()
        cor_atual = v.get("colour_data_v2")
        if v.get("work_mode") == "colour" and isinstance(cor_atual, dict):
            comandos.update({"switch_led": True, "colour_data_v2": {**cor_atual, "v": _pct_para(brilho, 10, 1000)}})
        else:
            comandos.update({"switch_led": True, "bright_value_v2": _pct_para(brilho, 10, 1000)})
    elif acao in {"temperatura", "branco"}:
        comandos.update({"switch_led": True, "work_mode": "white"})
        if temperatura is not None:
            comandos["temp_value_v2"] = _pct_para(temperatura, 0, 1000)
        if brilho is not None:
            comandos["bright_value_v2"] = _pct_para(brilho, 10, 1000)
        elif acao == "temperatura" and temperatura is None:
            raise CasaErro("Diga a temperatura de 0 (bem quente) a 100 (bem fria).")
    caminho = enviar(d, comandos, transporte)
    return {"ok": True, "caminho": caminho, "dispositivo": d["nome"], "mensagem": _frase_luz(d, acao, comandos)}


def _frase_luz(d: dict, acao: str, comandos: dict) -> str:
    nome = d["nome"]
    if "switch_led" in comandos and len(comandos) == 1:
        return f"{nome} {'ligada' if comandos['switch_led'] else 'desligada'}."
    partes = []
    if "colour_data_v2" in comandos:
        hsv = comandos["colour_data_v2"]
        partes.append(f"em {_nome_da_cor(hsv)}" if acao == "cor" else "")
        partes.append(f"brilho {_para_pct(hsv['v'], 10, 1000)}%")
    if comandos.get("work_mode") == "white":
        partes.append("em luz branca")
    if "temp_value_v2" in comandos:
        t = _para_pct(comandos["temp_value_v2"], 0, 1000)
        partes.append("bem quente" if t <= 15 else "bem fria" if t >= 85 else f"temperatura {t}%")
    if "bright_value_v2" in comandos:
        partes.append(f"brilho {_para_pct(comandos['bright_value_v2'], 10, 1000)}%")
    return f"{nome} ligada " + ", ".join(p for p in partes if p) + "."


# ─── Tomada ────────────────────────────────────────────────────────

# ─── Qual aparelho está na tomada ─────────────────────────────────
# A Tuya não diz o que está espetado: só liga/desliga e mede watts. O nome vem
# do pedido do Vitor (ele avisa, e a palavra dele vale). A Emily só lembra o
# último aparelho citado e o consumo típico de cada um, para avisar quando o
# consumo não combina e para proteger o PC.

ESTADO_TOMADA = "tomada-estado.json"
ESPERA_APRENDER_S = 3.0          # tempo para o aparelho "assentar" antes de medir
_RE_PC = re.compile(r"\b(pc|computador|desktop|estabilizador|gabinete)\b")
_PALAVRAS_SOLTAS = {"o", "a", "os", "as", "um", "uma", "meu", "minha", "do", "da", "de",
                    "no", "na", "pra", "para", "energia", "tomada", "aparelho"}


def limpar_aparelho(texto: str) -> str:
    """'a minha air fryer' -> 'air fryer'. Vazio quando só falou 'a tomada'."""
    n = re.sub(r"[^a-z0-9 ]+", " ", _normalizar(texto))
    return " ".join(t for t in n.split() if t not in _PALAVRAS_SOLTAS)[:40]


def eh_pc(nome: str) -> bool:
    return bool(_RE_PC.search(_normalizar(nome)))


def _estado_tomada(base: Optional[Path] = None) -> dict:
    try:
        dados = json.loads(((base or pasta()) / ESTADO_TOMADA).read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _salvar_estado_tomada(dados: dict, base: Optional[Path] = None) -> None:
    caminho = (base or pasta()) / ESTADO_TOMADA
    tmp = caminho.with_suffix(".tmp")
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.chmod(0o600)
        os.replace(tmp, caminho)
    except OSError:
        pass   # a memória é um extra: nunca pode impedir o controle


def ultimo_aparelho() -> Optional[dict]:
    u = _estado_tomada().get("ultimo")
    if isinstance(u, dict) and isinstance(u.get("nome"), str) and u["nome"]:
        try:
            quando = float(u.get("quando") or 0)
        except (TypeError, ValueError):
            quando = 0.0
        return {"nome": u["nome"], "quando": quando}
    return None


def lembrar_aparelho(nome: str) -> None:
    if not nome:
        return
    with _lock:
        dados = _estado_tomada()
        dados["ultimo"] = {"nome": nome, "quando": time.time()}
        _salvar_estado_tomada(dados)


def _aprender_consumo(nome: str, watts, base: Optional[Path] = None) -> None:
    """Guarda o consumo típico. PC não entra: o consumo dele varia demais."""
    if not nome or eh_pc(nome) or watts is None or watts < 3:
        return
    with _lock:
        dados = _estado_tomada(base)
        tipicos = dados.setdefault("tipicos", {})
        antes = tipicos.get(nome)
        if isinstance(antes, (int, float)) and antes > 0 and 0.5 <= watts / antes <= 2.0:
            tipicos[nome] = round((antes + watts) / 2, 1)
        else:
            tipicos[nome] = round(float(watts), 1)
        _salvar_estado_tomada(dados, base)


def _aprender_depois(nome: str, d: dict, transporte: str) -> "threading.Thread":
    """Mede o consumo logo depois de ligar: é o momento em que o nome é confiável."""
    # Fixa a pasta AGORA: a thread acorda segundos depois, e o ambiente pode ter
    # mudado (nos testes, o EMILY_CASA_DIR já terá voltado ao valor real).
    base = pasta()

    def trabalho():
        time.sleep(ESPERA_APRENDER_S)
        try:
            _aprender_consumo(nome, _ler_tomada(d, transporte).get("potencia_w"), base)
        except Exception:  # noqa: BLE001 - aprender é extra
            pass

    t = threading.Thread(target=trabalho, name="casa-aprende", daemon=True)
    t.start()
    return t


def adivinhar_aparelho(watts) -> Optional[str]:
    """Aparelho cujo consumo típico combina com a leitura (só se for um único)."""
    if watts is None or watts < 3:
        return None
    tipicos = {n: w for n, w in (_estado_tomada().get("tipicos") or {}).items()
               if isinstance(w, (int, float)) and w > 0}
    perto = [n for n, w in tipicos.items() if abs(watts - w) <= max(5.0, 0.25 * w)]
    return perto[0] if len(perto) == 1 else None


def rotulo_aparelho(nome: str) -> str:
    return nome


def _escala(d: dict, codigo: str, valor) -> Optional[float]:
    dp = d["codigos"].get(codigo)
    if valor is None or dp is None:
        return None
    escala = int(((d["mapping"].get(dp) or {}).get("values") or {}).get("scale", 0) or 0)
    try:
        return float(valor) / (10 ** escala)
    except (TypeError, ValueError):
        return None


def resumo_tomada(d: dict, v: Dict[str, object]) -> dict:
    return {"id": d["id"], "nome": d["nome"], "tipo": "tomada", "ligada": bool(v.get("switch_1")),
            "potencia_w": _escala(d, "cur_power", v.get("cur_power")),
            "tensao_v": _escala(d, "cur_voltage", v.get("cur_voltage")),
            "corrente_ma": _escala(d, "cur_current", v.get("cur_current")),
            "energia_kwh": _escala(d, "add_ele", v.get("add_ele")),
            "ao_voltar_energia": {"memory": "volta como estava", "power_on": "volta ligada",
                                  "power_off": "volta desligada"}.get(str(v.get("relay_status") or ""), "")}


def estado(transporte: str = "") -> dict:
    """Leitura de todos os aparelhos em paralelo. Falha de um não esconde os outros."""
    todos = dispositivos()

    def um(d):
        try:
            valores = ler(d, transporte)
            return resumo_luz(d, valores) if d["tipo"] == "luz" else \
                resumo_tomada(d, valores) if d["tipo"] == "tomada" else {"id": d["id"], "nome": d["nome"], "tipo": d["tipo"]}
        except CasaErro as e:
            return {"id": d["id"], "nome": d["nome"], "tipo": d["tipo"], "erro": str(e)}

    with ThreadPoolExecutor(max_workers=max(1, len(todos))) as pool:
        lista = list(pool.map(um, todos))
    plug = tomada()
    ultimo = ultimo_aparelho()
    for item in lista:
        if plug and item["id"] == plug["id"]:
            if ultimo:
                item["aparelho"] = ultimo["nome"]
            if item.get("ligada"):
                palpite = adivinhar_aparelho(item.get("potencia_w"))
                if palpite and palpite != item.get("aparelho"):
                    item["palpite"] = palpite
    return {"ok": True, "dispositivos": lista}


def descrever_estado(dados: dict) -> str:
    linhas = []
    for item in dados.get("dispositivos") or []:
        if item.get("erro"):
            linhas.append(f"- {item['nome']}: sem resposta ({item['erro']})")
        elif item["tipo"] == "luz":
            if not item["ligada"]:
                linhas.append(f"- {item['nome']}: desligada")
            elif item["modo"] == "cor":
                linhas.append(f"- {item['nome']}: ligada em {item['cor']}, brilho {item['brilho']}%")
            else:
                linhas.append(f"- {item['nome']}: ligada em luz branca, brilho {item['brilho']}%, "
                              f"temperatura {item['temperatura']}% (0 quente, 100 fria)")
        elif item["tipo"] == "tomada":
            papel = f" (aparelho: {rotulo_aparelho(item['aparelho'])})" if item.get("aparelho") else ""
            consumo = f", consumindo {item['potencia_w']:.0f} W" if item.get("potencia_w") is not None else ""
            palpite = (f"; pelo consumo parece ser {rotulo_aparelho(item['palpite'])}"
                       if item.get("palpite") else "")
            linhas.append(f"- {item['nome']}{papel}: {'ligada' if item['ligada'] else 'desligada'}{consumo}{palpite}")
    return "\n".join(linhas) or "Nenhum aparelho da casa configurado."


# ─── Energia do PC (só pela nuvem: o PC não religa a própria energia) ─

CONFIRMACAO_TTL = 90
ESPERA_MAX_S = 300
INTERVALO_ESPERA_S = 5

_pendente: dict = {}
_espera: dict = {}


def _ler_tomada(d: dict, transporte: str) -> dict:
    return resumo_tomada(d, ler(d, transporte))


def _pc_parece_ligado(info: dict, pc_online: Callable[[], Optional[bool]]) -> tuple:
    """(parece_ligado, motivo). Sem leitura confiável, considera ligado."""
    try:
        online = pc_online()
    except Exception:  # noqa: BLE001
        online = None
    potencia = info.get("potencia_w")
    limite = _limite_pc_w()
    if online:
        return True, "o PC está respondendo na rede"
    if potencia is None:
        return True, "não consegui medir o consumo"
    if potencia >= limite:
        return True, f"a tomada está puxando {potencia:.0f} W"
    return False, ""


def energia_pc(acao: str, *, pc_online: Callable[[], Optional[bool]], aguardar_pc: bool = False,
               confirmation_id: str = "", transporte: str = "nuvem",
               agora: Callable[[], float] = time.time) -> dict:
    d = tomada_pc()
    if d is None:
        raise CasaErro("Não sei qual tomada é a do PC. Indique em casa.json (energia_pc).")
    acao = _normalizar(acao).replace(" ", "_")
    if acao == "estado":
        info = _ler_tomada(d, transporte)
        ligado, motivo = _pc_parece_ligado(info, pc_online) if info["ligada"] else (False, "")
        partes = [f"Tomada do PC {'ligada' if info['ligada'] else 'desligada'}"]
        if info.get("potencia_w") is not None:
            partes.append(f"consumo {info['potencia_w']:.0f} W")
        if info["ligada"]:
            partes.append(f"PC {'ligado' if ligado else 'parece desligado'}" + (f" ({motivo})" if motivo else ""))
        if _espera.get("ativa"):
            partes.append("aguardando o PC desligar para cortar a energia")
        return {"ok": True, "estado": info, "pc_ligado": ligado, "aguardando": bool(_espera.get("ativa")),
                "mensagem": ", ".join(partes) + "."}
    if acao == "ligar":
        cancelar_espera()
        enviar(d, {"switch_1": True}, transporte)
        lembrar_aparelho("pc")
        return {"ok": True, "mensagem": (
            "Energia do PC ligada. Ele só liga sozinho se a BIOS estiver em 'ligar quando a energia "
            "voltar'; se não ligar em alguns segundos, falta apertar o botão.")}
    if acao == "cancelar":
        houve = cancelar_espera() or bool(_pendente.pop("id", None))
        return {"ok": True, "mensagem": "Cancelei o corte de energia pendente." if houve
                else "Não tinha nenhum corte de energia pendente."}
    if acao == "confirmar_desligar":
        return confirmar_corte(confirmation_id, transporte=transporte, agora=agora)
    if acao != "desligar":
        raise CasaErro("Ação de energia desconhecida. Use estado, ligar, desligar, confirmar_desligar ou cancelar.")
    lembrar_aparelho("pc")

    info = _ler_tomada(d, transporte)
    if not info["ligada"]:
        return {"ok": True, "mensagem": "A energia do PC já está desligada."}
    ligado, motivo = _pc_parece_ligado(info, pc_online)
    if not ligado:
        enviar(d, {"switch_1": False}, transporte)
        return {"ok": True, "mensagem": "O PC estava desligado; cortei a energia do estabilizador."}
    if aguardar_pc:
        iniciar_espera(d, pc_online, transporte)
        return {"ok": True, "aguardando": True, "mensagem": (
            f"O PC ainda está ligado ({motivo}). Vou cortar a energia assim que ele terminar de "
            f"desligar, esperando até {ESPERA_MAX_S // 60} minutos. Isso não desliga o PC: use "
            "pc_energia para desligá-lo, se ainda não pediu.")}
    _pendente.clear()
    _pendente.update(id=secrets.token_hex(6), expira=agora() + CONFIRMACAO_TTL, aparelho="pc")
    return {"ok": False, "requer_confirmacao": True, "confirmation_id": _pendente["id"],
            "confirmacao_expira_em_segundos": CONFIRMACAO_TTL, "mensagem": (
                f"Não cortei: o PC parece ligado ({motivo}). Cortar agora é igual a puxar o cabo e "
                "pode perder o que está aberto. O seguro é desligar o PC com pc_energia e chamar "
                "desligar com aguardar_pc=true. Se o Vitor quiser cortar assim mesmo, ele precisa "
                "confirmar com as próprias palavras.")}


def iniciar_espera(d: dict, pc_online: Callable[[], Optional[bool]], transporte: str) -> None:
    with _lock:
        if _espera.get("ativa"):
            return
        _espera.clear()
        _espera.update(ativa=True, inicio=time.time(), cancelada=threading.Event())
        cancelada = _espera["cancelada"]

    def vigiar():
        seguidas = 0
        try:
            while time.time() - _espera.get("inicio", 0) < ESPERA_MAX_S and not cancelada.is_set():
                try:
                    info = _ler_tomada(d, transporte)
                    if not info["ligada"]:
                        _espera["resultado"] = "a tomada já estava desligada"
                        return
                    ligado, _ = _pc_parece_ligado(info, pc_online)
                    seguidas = 0 if ligado else seguidas + 1
                    # Duas leituras seguidas: evita cortar no vale de consumo do desligamento.
                    if seguidas >= 2:
                        enviar(d, {"switch_1": False}, transporte)
                        _espera["resultado"] = "energia cortada depois que o PC desligou"
                        return
                except CasaErro:
                    pass
                cancelada.wait(INTERVALO_ESPERA_S)
            _espera["resultado"] = "cancelado" if cancelada.is_set() else "o PC não desligou a tempo; não cortei"
        finally:
            _espera["ativa"] = False

    threading.Thread(target=vigiar, name="casa-espera-pc", daemon=True).start()


def cancelar_espera() -> bool:
    with _lock:
        if not _espera.get("ativa"):
            return False
        _espera["cancelada"].set()
        return True


def confirmar_corte(confirmation_id: str = "", *, transporte: str = "nuvem",
                    agora: Callable[[], float] = time.time) -> dict:
    """Corta a energia depois da confirmação explícita do Vitor (id certo, dentro do prazo)."""
    d = tomada()
    if d is None:
        raise CasaErro("Não achei a tomada. Indique qual é em casa.json (energia_pc).")
    valido = _pendente.get("id") and secrets.compare_digest(str(confirmation_id), str(_pendente["id"])) \
        and agora() < float(_pendente.get("expira", 0))
    if not valido:
        return {"ok": False, "mensagem": "Não há corte de energia aguardando essa confirmação (pode ter expirado)."}
    nome = str(_pendente.get("aparelho") or "pc")
    _pendente.clear()
    enviar(d, {"switch_1": False}, transporte)
    lembrar_aparelho(nome)
    quem = "do PC" if eh_pc(nome) else f"({nome})"
    return {"ok": True, "mensagem": f"Energia {quem} cortada por confirmação explícita."}


# ─── Tomada para qualquer aparelho ────────────────────────────────

ACOES_TOMADA = ("estado", "ligar", "desligar", "trocar", "cancelar")


def _conflito_com_pc(nome: str, info: dict, pc_online: Callable[[], Optional[bool]]) -> str:
    """Motivo, se o aparelho citado pode estar errado porque o PC ainda parece estar na tomada.

    A tomada nasceu alimentando o PC. Só há risco real se TUDO isto vale: o último
    aparelho conhecido é o PC (ou nunca houve registro), o Vitor cita outro, a
    tomada está ligada, o PC está respondendo na rede e a tomada puxa o que um PC
    puxaria. Se o PC está desligado ou fora da rede, ele não pode ser a carga, e
    a palavra do Vitor vale sem perguntar. Vazio = pode seguir.
    """
    if not nome or eh_pc(nome) or not info.get("ligada"):
        return ""
    ultimo = ultimo_aparelho()
    if ultimo is not None and not eh_pc(ultimo["nome"]):
        return ""
    try:
        online = pc_online()
    except Exception:  # noqa: BLE001
        online = None
    if online is False:
        return ""
    watts = info.get("potencia_w")
    if watts is not None and watts < _limite_pc_w():
        return ""        # consumo baixo demais para ser o PC: ele não está nesta tomada
    if online:
        return "o PC está respondendo na rede" + (f" e a tomada puxa {watts:.0f} W" if watts is not None else "")
    return f"a tomada puxa {watts:.0f} W" if watts is not None else "não consegui medir o consumo"


def _consumo_nao_combina(nome: str, info: dict) -> str:
    """Motivo, se o consumo atual destoa muito do típico JÁ APRENDIDO desse aparelho.

    Pega o caso em que o PC voltou para a tomada sem o Vitor avisar: o ventilador
    puxa ~40 W e a tomada marca 150 W. Sem consumo típico aprendido não opina.
    """
    watts = info.get("potencia_w")
    tipico = (_estado_tomada().get("tipicos") or {}).get(nome)
    if watts is None or not isinstance(tipico, (int, float)) or tipico <= 0:
        return ""
    if abs(watts - tipico) > max(15.0, 0.6 * tipico):
        return f"{nome} costuma puxar uns {tipico:.0f} W e a tomada marca {watts:.0f} W"
    return ""


def controlar_tomada(acao: str, aparelho: str = "", *, pc_online: Callable[[], Optional[bool]],
                     aguardar_pc: bool = False, no_pc: bool = False, transporte: str = "",
                     agora: Callable[[], float] = time.time) -> dict:
    """Liga/desliga a tomada para o aparelho que o Vitor citou.

    O nome do pedido vale: ele troca de aparelho quando quiser e a Emily não
    pergunta onde está espetado. PC é o único com trava (ver energia_pc).
    no_pc=True quando quem chama é a Emily do próprio PC: ela não liga nem corta
    a energia de si mesma.
    """
    acao = _normalizar(acao).replace(" ", "_")
    if acao not in ACOES_TOMADA:
        raise CasaErro("Ação da tomada desconhecida. Use " + ", ".join(ACOES_TOMADA) + ".")
    d = tomada()
    if d is None:
        raise CasaErro("Não achei a tomada. Indique qual é em casa.json (energia_pc).")
    explicito = limpar_aparelho(aparelho)
    ultimo = ultimo_aparelho()
    nome = explicito or (ultimo["nome"] if ultimo else "")
    via_nuvem = transporte or "nuvem"

    if acao == "cancelar":
        return energia_pc("cancelar", pc_online=pc_online, transporte=via_nuvem, agora=agora)
    if acao == "estado":
        if nome and eh_pc(nome):
            return energia_pc("estado", pc_online=pc_online, transporte=via_nuvem, agora=agora)
        info = _ler_tomada(d, transporte)
        partes = [f"Tomada {'ligada' if info['ligada'] else 'desligada'}"]
        if nome:
            partes.append(f"último aparelho: {nome}")
        if info.get("potencia_w") is not None:
            partes.append(f"consumo {info['potencia_w']:.0f} W")
        palpite = adivinhar_aparelho(info.get("potencia_w")) if info["ligada"] else None
        if palpite and palpite != nome:
            partes.append(f"pelo consumo parece ser {palpite}")
        return {"ok": True, "estado": info, "aparelho": nome, "mensagem": ", ".join(partes) + "."}

    if not nome:
        raise CasaErro("Qual aparelho está na tomada agora (ex.: ventilador, air fryer, PC)? Me diga o nome.")
    if eh_pc(nome):
        if no_pc:
            raise CasaErro("A energia do PC é controlada pelo celular: este PC não consegue ligar nem "
                           "cortar a própria energia.")
        if acao == "trocar":
            lembrar_aparelho("pc")
            return {"ok": True, "mensagem": "Anotei: o PC está na tomada."}
        return energia_pc(acao, pc_online=pc_online, aguardar_pc=aguardar_pc,
                          transporte=via_nuvem, agora=agora)

    if acao == "trocar":
        lembrar_aparelho(nome)
        return {"ok": True, "mensagem": f"Anotei: {nome} está na tomada."}
    info = _ler_tomada(d, transporte)
    # Tomada desligada não tem o que proteger: ligar é seguro. Com a tomada
    # LIGADA, "ligar" não muda nada na prática mas anotaria o aparelho errado,
    # e "desligar" cortaria a energia de quem estiver lá. Nos dois casos confere.
    if info.get("ligada"):
        motivo = _conflito_com_pc(explicito, info, pc_online) or _consumo_nao_combina(nome, info)
        if motivo:
            return {"ok": False, "conflito_pc": True, "mensagem": (
                f"Não mexi: não tenho certeza de que {nome} é quem está na tomada ({motivo}). "
                f"Se for, o Vitor precisa confirmar (acao=trocar com aparelho={nome}) e eu repito o "
                "pedido. Não troque por conta própria nem insista sem a confirmação dele.")}
    if acao == "ligar":
        enviar(d, {"switch_1": True}, transporte)
        lembrar_aparelho(nome)
        _aprender_depois(nome, d, transporte)
        return {"ok": True, "mensagem": f"Tomada ligada ({nome})."}
    if not info["ligada"]:
        lembrar_aparelho(nome)
        return {"ok": True, "mensagem": f"A tomada ({nome}) já estava desligada."}
    _aprender_consumo(nome, info.get("potencia_w"))
    enviar(d, {"switch_1": False}, transporte)
    lembrar_aparelho(nome)
    return {"ok": True, "mensagem": f"Tomada desligada ({nome})."}

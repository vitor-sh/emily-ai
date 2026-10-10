"""Sincronização eventual de chats e fatos do desktop com o gateway principal.

Usada no Windows. O gateway Fedora continua sendo a origem compartilhada com
o Android; cada desktop mantém seu cache local para funcionar sem internet.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import requests

import conversas
import memoria
import preferencias
from emily_paths import arquivo_dados

_thread: threading.Thread | None = None
_estado = arquivo_dados("sync_desktop.json")
_ultima_timeline_notificada: dict[str, tuple[int, float]] = {}


def _atualizar_conversa_aberta() -> None:
    """Reflete cortes remotos no chat aberto do Windows, sem esperar reabrir."""
    try:
        import interface_web
        import modelo
        api = getattr(interface_web, "_api_registrada", None)
        principal = sys.modules.get("main") or sys.modules.get("__main__")
        ocupada = getattr(principal, "emily_ocupada", None)
        if api is None or (ocupada is not None and ocupada.is_set()) or api._demo_ativo():
            return
        janela = api._j
        cid = getattr(janela, "_cid", None)
        if not cid:
            return
        meta = next((c for c in conversas.listar() if c["id"] == cid), None)
        if meta is None:
            return
        revisao = (int(meta.get("ramo", 0)), float(meta["mexida"]))
        if _ultima_timeline_notificada.get(cid) == revisao:
            return
        mensagens = conversas.abrir(cid)
        modelo.definir_historico(conversas.para_o_modelo(cid))
        janela._push("conversa_sincronizada", {"cid": cid, "mensagens": [
            {"papel": m.get("papel"), "texto": m.get("texto"),
             "fontes": m.get("fontes") or [], "indice": i}
            for i, m in enumerate(mensagens)]})
        _ultima_timeline_notificada[cid] = revisao
    except Exception as exc:
        print(f"[SYNC-DESKTOP] interface aguardando: {type(exc).__name__}: {exc}")


def _config() -> tuple[str, str]:
    from emily_remote import gateway_fedora
    origem = gateway_fedora().strip()
    token = os.getenv("EMILY_PONTE_TOKEN", "").strip()
    if not origem or not token:
        try:
            from dotenv import dotenv_values
            import sys
            base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
            candidatos = (base / ".env", base / "_internal" / ".env")
            for caminho in candidatos:
                if caminho.is_file():
                    valores = dotenv_values(caminho)
                    origem = origem or str(valores.get("EMILY_SYNC_URL") or "").strip()
                    token = token or str(valores.get("EMILY_PONTE_TOKEN") or "").strip()
                    if origem and token:
                        break
            if not origem:
                manifesto = (base / "_internal" / "windows-release.json"
                             if getattr(sys, "frozen", False) else base / "windows-release.json")
                if manifesto.is_file():
                    origem = str(json.loads(manifesto.read_text(encoding="utf-8")).get("sync_url") or "")
        except ImportError:
            pass
    return origem.rstrip("/"), token


def _pedido(sessao: requests.Session, metodo: str, url: str, token: str, **kw) -> dict:
    timeout = kw.pop("timeout", (3, 15))
    resposta = sessao.request(metodo, url, headers={"Authorization": f"Bearer {token}"},
                             timeout=timeout, **kw)
    resposta.raise_for_status()
    dados = resposta.json()
    if not dados.get("ok"):
        raise RuntimeError(str(dados.get("erro") or dados.get("mensagem") or "sync recusado"))
    return dados


def sincronizar_preferencias_uma_vez(sessao: requests.Session | None = None) -> bool:
    """Sincroniza escolhas por campo, independente do acervo de conversas."""
    base, token = _config()
    if not base or not token:
        return False
    sessao = sessao or requests.Session()
    try:
        remoto_prefs = _pedido(sessao, "GET", base + "/preferencias/sync", token)
        from emily_remote import sincronizar_endpoint_cliente
        sincronizar_endpoint_cliente(base, token, sessao)
        locais_prefs = preferencias.exportar_sync()
        enviar = {k: v for k, v in locais_prefs.items()
                  if k != "monitor_discord_host" and float(v["quando"]) > float(
                      remoto_prefs.get("campos", {}).get(k, {}).get("quando", 0))}
        if enviar:
            remoto_prefs = _pedido(sessao, "POST", base + "/preferencias/sync", token,
                                  json={"campos": enviar})
        campos_remotos = remoto_prefs.get("campos", {})
        mudaram = preferencias.mesclar_sync({k: v for k, v in campos_remotos.items()
                                              if k != "monitor_discord_host"})
        if "monitor_discord_host" in campos_remotos:
            mudaram += preferencias.mesclar_sync(
                {"monitor_discord_host": campos_remotos["monitor_discord_host"]},
                forcar=True)
        if mudaram:
            print(f"[SYNC-DESKTOP] preferências atualizadas: {', '.join(mudaram)}")
        return True
    except (requests.RequestException, RuntimeError, TypeError, ValueError) as exc:
        print(f"[SYNC-DESKTOP] preferências aguardando gateway: {type(exc).__name__}: {exc}")
        return False


def sincronizar_uma_vez(sessao: requests.Session | None = None) -> bool:
    base, token = _config()
    if not base or not token:
        return False
    sessao = sessao or requests.Session()
    # A identidade e o modelo chegam antes da cópia potencialmente longa de
    # chats. Uma falha nas preferências não impede chats e memória.
    sincronizar_preferencias_uma_vez(sessao)
    remoto = _pedido(sessao, "GET", base + "/chats/delta", token, params={"desde": 0})
    locais = {c["id"]: c for c in conversas.listar()}
    remotos = {c["id"]: c for c in remoto.get("conversas", [])}
    apagados_local = {a["id"]: float(a["quando"])
                      for a in conversas.listar_apagadas()}
    apagados_remoto = {a["id"]: float(a["quando"])
                       for a in remoto.get("apagadas", [])}

    for cid in set(locais) | set(remotos) | set(apagados_local) | set(apagados_remoto):
        local, outro = locais.get(cid), remotos.get(cid)
        exclusao = max(apagados_local.get(cid, 0), apagados_remoto.get(cid, 0))
        data_local = float(local.get("mexida", 0)) if local else 0
        data_remota = float(outro.get("mexida", 0)) if outro else 0
        ramo_local = int(local.get("ramo", 0)) if local else 0
        ramo_remoto = int(outro.get("ramo", 0)) if outro else 0
        if exclusao >= max(data_local, data_remota) and exclusao:
            if local:
                conversas.apagar(cid)
            if outro:
                _pedido(sessao, "DELETE", base + "/chats/apagar/" + cid, token)
            continue
        if outro and (not local or ramo_remoto > ramo_local or
                      (ramo_remoto == ramo_local and data_remota > data_local)):
            completo = _pedido(sessao, "GET", base + "/chats/abrir/" + cid, token)
            conversas.gravar_externa(cid, completo["titulo"], completo["criada"],
                                    completo["mexida"], completo["mensagens"],
                                    ramo=int(completo.get("ramo", 0)))
        elif local and (not outro or ramo_local > ramo_remoto or
                        (ramo_local == ramo_remoto and data_local > data_remota)):
            _pedido(sessao, "POST", base + "/chats/gravar", token,
                    json={**local, "mensagens": conversas.abrir(cid)})

    try:
        anterior = set(json.loads(_estado.read_text(encoding="utf-8")).get("fatos", []))
    except (OSError, ValueError, TypeError):
        anterior = set()
    mem = memoria.carregar_memoria()
    fatos = [{"texto": f, "local_novo": hashlib.sha256(f.strip().encode()).hexdigest() not in anterior}
             for f in mem.get("fatos", [])]
    final = _pedido(sessao, "POST", base + "/memoria/sync", token,
                   json={"fatos": fatos, "apagados": mem.get("apagados", {})})
    # Une o estado final via API local para preservar outros campos da memória.
    memoria.sincronizar_externa(final.get("fatos", []), final.get("apagados", {}))
    hashes = [hashlib.sha256(f.strip().encode()).hexdigest() for f in final.get("fatos", [])]
    _estado.parent.mkdir(parents=True, exist_ok=True)
    tmp = _estado.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fatos": hashes}), encoding="utf-8")
    os.replace(tmp, _estado)
    return True


def iniciar(intervalo: int = 30, habilitado: Callable[[], bool] | None = None) -> None:
    global _thread
    if os.name != "nt" or (_thread and _thread.is_alive()):
        return

    def ciclo() -> None:
        sessao = requests.Session()
        while True:
            try:
                if habilitado is None or habilitado():
                    # Outro processo pode ter escrito enquanto este ficou
                    # ocioso; só sincronizar depois de reler o acervo.
                    conversas.recarregar()
                    sincronizar_uma_vez(sessao)
                    _atualizar_conversa_aberta()
            except Exception as exc:
                print(f"[SYNC-DESKTOP] aguardando conexão: {type(exc).__name__}: {exc}")
            time.sleep(max(10, intervalo))

    _thread = threading.Thread(target=ciclo, name="emily-sync-desktop", daemon=True)
    _thread.start()

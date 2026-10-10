"""Sincronização real de dois acervos sem tocar rede nem dados do usuário."""

from __future__ import annotations

class Resposta:
    def __init__(self, dados):
        self.dados = dados
    def raise_for_status(self):
        pass
    def json(self):
        return self.dados


class GatewayFalso:
    def __init__(self):
        self.chats = {"remoto": {"id": "remoto", "titulo": "Do celular",
                                  "criada": 1, "mexida": 2,
                                  "mensagens": [{"papel": "user", "texto": "no Android", "quando": 2}]}}
        self.prefs = {"nome": {"valor": "Vitor no Fedora", "quando": 100}}
    def request(self, metodo, url, **kw):
        caminho = url.removeprefix("https://gateway.exemplo")
        if caminho == "/chats/delta":
            return Resposta({"ok": True, "conversas": [
                {k: v for k, v in c.items() if k != "mensagens"} for c in self.chats.values()],
                "apagadas": []})
        if caminho.startswith("/chats/abrir/"):
            return Resposta({"ok": True, **self.chats[caminho.rsplit("/", 1)[1]]})
        if caminho == "/chats/gravar" and metodo == "POST":
            c = kw["json"]
            self.chats[c["id"]] = c
            return Resposta({"ok": True})
        if caminho == "/memoria/sync":
            enviados = [f["texto"] for f in kw["json"]["fatos"]]
            return Resposta({"ok": True, "fatos": list(dict.fromkeys([*enviados, "fato do Android"])),
                             "apagados": {}})
        if caminho == "/preferencias/sync":
            if metodo == "POST":
                for k, item in kw["json"]["campos"].items():
                    if item["quando"] > self.prefs.get(k, {}).get("quando", 0):
                        self.prefs[k] = item
            return Resposta({"ok": True, "campos": self.prefs})
        raise AssertionError((metodo, caminho))


def test_chats_e_fatos_fluem_nos_dois_sentidos(monkeypatch, tmp_path):
    import conversas
    import memoria
    import preferencias
    import sincronizacao_desktop as sync

    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "conversas.json")
    monkeypatch.setattr(memoria, "ARQUIVO", str(tmp_path / "memoria.json"))
    monkeypatch.setattr(sync, "_estado", tmp_path / "sync.json")
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "preferencias.json")
    preferencias.recarregar()
    monkeypatch.setattr(sync, "_config", lambda: ("https://gateway.exemplo", "segredo"))
    conversas.recarregar()
    try:
        local = conversas.criar("Do notebook")
        conversas.acrescentar(local, "user", "no Windows")
        memoria.adicionar_fato("fato do Windows", usar_llm=False)
        gateway = GatewayFalso()
        assert sync.sincronizar_uma_vez(gateway)
        assert local in gateway.chats
        assert conversas.abrir("remoto")[0]["texto"] == "no Android"
        assert set(memoria.listar_fatos()) == {"fato do Windows", "fato do Android"}
        assert preferencias.obter("nome") == "Vitor no Fedora"
        assert sync.sincronizar_uma_vez(gateway)
        assert len(conversas.abrir("remoto")) == 1
    finally:
        conversas.recarregar()
        preferencias.recarregar()


def test_memoria_ausente_nao_compartilha_lista_entre_arquivos(monkeypatch, tmp_path):
    import memoria
    monkeypatch.setattr(memoria, "ARQUIVO", str(tmp_path / "primeira.json"))
    primeira = memoria.carregar_memoria()
    primeira["fatos"].append("só no primeiro")
    monkeypatch.setattr(memoria, "ARQUIVO", str(tmp_path / "segunda.json"))
    assert memoria.carregar_memoria()["fatos"] == []


def test_gateway_antigo_sem_preferencias_ainda_sincroniza_chats(monkeypatch, tmp_path):
    import requests
    import conversas
    import memoria
    import preferencias
    import sincronizacao_desktop as sync

    class GatewayAntigo(GatewayFalso):
        def request(self, metodo, url, **kw):
            if url.endswith("/preferencias/sync"):
                raise requests.HTTPError("404")
            return super().request(metodo, url, **kw)

    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "conversas.json")
    monkeypatch.setattr(memoria, "ARQUIVO", str(tmp_path / "memoria.json"))
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    monkeypatch.setattr(sync, "_estado", tmp_path / "sync.json")
    monkeypatch.setattr(sync, "_config", lambda: ("https://gateway.exemplo", "segredo"))
    conversas.recarregar()
    preferencias.recarregar()
    try:
        assert sync.sincronizar_uma_vez(GatewayAntigo())
        assert conversas.abrir("remoto")[0]["texto"] == "no Android"
    finally:
        conversas.recarregar()
        preferencias.recarregar()


def test_chat_aberto_recebe_corte_remoto_sem_reabrir(monkeypatch, tmp_path):
    import threading
    from types import SimpleNamespace
    import sys
    import conversas
    import interface_web
    import modelo
    import sincronizacao_desktop as sync

    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "conversas.json")
    conversas.recarregar()
    cid = conversas.criar("Pedido")
    conversas.acrescentar(cid, "user", "Pedido")
    conversas.acrescentar(cid, "emily", "Antiga")
    eventos, contextos = [], []
    janela = SimpleNamespace(_cid=cid, _push=lambda evento, dados: eventos.append((evento, dados)))
    api = SimpleNamespace(_j=janela, _demo_ativo=lambda: False)
    monkeypatch.setattr(interface_web, "_api_registrada", api)
    monkeypatch.setattr(modelo, "definir_historico", lambda h: contextos.append(h))
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(emily_ocupada=threading.Event()))
    sync._ultima_timeline_notificada.clear()
    try:
        sync._atualizar_conversa_aberta()
        assert len(eventos) == 1
        sync._atualizar_conversa_aberta()
        assert len(eventos) == 1
        conversas.truncar_para_regenerar(cid, 1)
        conversas.acrescentar(cid, "emily", "Nova")
        sync._atualizar_conversa_aberta()
        assert [m["texto"] for m in eventos[-1][1]["mensagens"]] == ["Pedido", "Nova"]
        assert contextos[-1][-1] == {"role": "assistant", "content": "Nova"}
    finally:
        sync._ultima_timeline_notificada.clear()
        conversas.recarregar()

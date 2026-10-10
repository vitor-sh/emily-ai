"""Executor do contrato /pc/action no Windows, sem comandos do Fedora."""

from __future__ import annotations

import base64
import os
import platform
import secrets
import shutil
import socket
import subprocess
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psutil

from pc_control import (Aplicativo, PCController, ENERGIA_ATRASO_MINIMO,
                        _normalizar, _texto)


class WindowsPCController(PCController):
    ENERGIA = {
        "desligar": ("desligar o computador", ["shutdown", "/s"]),
        "reiniciar": ("reiniciar o computador", ["shutdown", "/r"]),
        "hibernar": ("hibernar o computador", ["shutdown", "/h"]),
        "suspender": ("suspender o computador", []),
    }

    def _acao_status(self, _args, **_):
        disco = shutil.disk_usage(self.home)
        estado = {"hostname": socket.gethostname(),
                  "sistema": f"Windows {platform.release()}",
                  "desktop": "Windows", "sessao": "usuário",
                  "uptime_segundos": int(time.time() - psutil.boot_time()),
                  "disco_livre_bytes": disco.free,
                  "disco_total_bytes": disco.total}
        return self._ok(f"PC {estado['hostname']} online no Windows.", status=estado)

    def _apps(self):
        agora = self._agora()
        with self._lock:
            instante, cache = self._apps_cache
            if cache and agora - instante < 60:
                return cache
        pastas = [
            Path(os.getenv("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.getenv("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        apps = []
        vistos = set()
        for pasta in pastas:
            if not pasta.is_dir():
                continue
            for atalho in pasta.rglob("*.lnk"):
                nome = atalho.stem
                if nome.lower() not in vistos:
                    vistos.add(nome.lower())
                    apps.append(Aplicativo(nome, nome, atalho))
        with self._lock:
            self._apps_cache = (agora, apps)
        return apps

    @staticmethod
    def _iniciar_arquivo(caminho: str) -> None:
        os.startfile(caminho)  # type: ignore[attr-defined]

    def _abrir_app(self, nome, *, jogo=False):
        consulta = _texto(nome, nome="nome", maximo=160)
        encontrados = self._buscar_apps(consulta, 5)
        if not encontrados:
            return self._erro(f"Não encontrei {'o jogo' if jogo else 'o aplicativo'} “{consulta}” instalado.")
        primeiro = encontrados[0]
        if len(encontrados) > 1 and _normalizar(primeiro.nome) != _normalizar(consulta):
            return self._erro("Encontrei mais de uma opção; diga o nome exato.",
                              opcoes=[a.nome for a in encontrados])
        self._iniciar_arquivo(str(primeiro.arquivo))
        return self._ok(f"Abri {primeiro.nome} no PC.",
                        app={"nome": primeiro.nome, "desktop_id": primeiro.desktop_id})

    def _acao_abrir_arquivo(self, args, **_):
        caminho = self._caminho_permitido(args.get("caminho"), tipo="arquivo")
        self._iniciar_arquivo(str(caminho))
        return self._ok(f"Abri o arquivo {caminho.name}.", caminho=str(caminho))

    def _acao_abrir_pasta(self, args, **_):
        caminho = self._caminho_permitido(args.get("caminho"), tipo="pasta")
        self._iniciar_arquivo(str(caminho))
        return self._ok(f"Abri a pasta {caminho.name}.", caminho=str(caminho))

    def _acao_abrir_site(self, args, **_):
        bruto = _texto(args.get("url"), nome="url", maximo=2000)
        if "://" not in bruto:
            bruto = "https://" + bruto
        url = urlparse(bruto)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("URL inválida")
        segura = urlunparse((url.scheme, url.netloc, url.path or "", url.params, url.query, ""))
        if not webbrowser.open(segura):
            return self._erro("o navegador padrão não abriu o site")
        return self._ok(f"Abri {url.hostname} no navegador do PC.", url=segura)

    def _acao_fechar_app(self, args, **_):
        consulta = _normalizar(_texto(args.get("nome"), nome="nome", maximo=120))
        usuario = psutil.Process().username()
        protegidos = {"explorer.exe", "dwm.exe", "csrss.exe", "wininit.exe",
                      "services.exe", "lsass.exe", "emily.exe", "emilygateway.exe"}
        encontrados = []
        for processo in psutil.process_iter(["pid", "name", "username"]):
            try:
                nome = str(processo.info["name"] or "")
                if (processo.info["username"] == usuario
                        and nome.lower() not in protegidos
                        and _normalizar(Path(nome).stem) == consulta):
                    encontrados.append(processo)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not encontrados:
            return self._erro(f"Não achei “{consulta}” aberto como processo do usuário.")
        nomes = [p.name() for p in encontrados[:12]]
        for processo in encontrados[:12]:
            processo.terminate()
        return self._ok(f"Fechei {consulta} no PC.", processos=nomes)

    def _acao_midia_status(self, args, **_):
        return self._erro("estado de mídia do sistema Windows indisponível; a aba do navegador pode ser controlada")

    def _acao_midia_controlar(self, args, **_):
        acao = _texto(args.get("acao"), nome="ação", maximo=30).lower()
        if acao not in {"tocar", "pausar", "alternar", "proxima", "anterior", "parar"}:
            raise ValueError("ação de mídia inválida")
        resposta = self._browser("controlar_midia", controle=acao, tab_id=self._tab_id(args))
        if resposta.get("ok"):
            return self._ok(f"Controle de mídia “{acao}” aplicado na aba.", resultado=resposta["browser"])
        return self._erro("não encontrei mídia controlável na aba do navegador")

    def _acao_capturar_tela(self, args, **_):
        from windows_screen import capturar_jpeg
        monitor = int(args.get("monitor", 1))
        imagem = capturar_jpeg(monitor)
        return self._ok(f"Capturei o monitor {monitor} sob demanda.",
                        imagem_base64=base64.b64encode(imagem).decode("ascii"),
                        mime_type="image/jpeg", monitor=monitor,
                        tamanho_bytes=len(imagem), idade_segundos="0")

    def _acao_observacao_pendencias(self, args, **_):
        from windows_screen import listar_monitores
        processos = [{"pid": p.info["pid"], "nome": p.info["name"]}
                     for p in psutil.process_iter(["pid", "name"])][:100]
        abas = []
        if self._browser_bridge is not None:
            resposta = self._acao_navegador_abas({})
            if resposta.get("ok"):
                abas = resposta.get("abas", [])[:40]
        return self._ok("Inventário de observação consultado.",
                        monitores=listar_monitores(), processos=processos, abas=abas)

    def _acao_confirmar_energia(self, args, *, turno_id, _autorizado_pelo_modo=False, **_):
        if not self._energia_esta_habilitada():
            return self._erro("controle de energia desabilitado")
        identificador = _texto(args.get("confirmation_id"), nome="confirmation_id", maximo=120)
        with self._lock:
            self._limpar_confirmacoes()
            pendente = self._confirmacoes.get(identificador)
            if pendente is None:
                return self._erro("Não há confirmação de energia válida; peça a ação novamente.")
            if secrets.compare_digest(pendente.turno_origem, turno_id) and not _autorizado_pelo_modo:
                return self._erro("Me confirma numa mensagem nova, tá?")
            del self._confirmacoes[identificador]
        atraso = max(ENERGIA_ATRASO_MINIMO, pendente.atraso_segundos)
        if pendente.acao in {"desligar", "reiniciar"}:
            comando = ["shutdown.exe", "/s" if pendente.acao == "desligar" else "/r", "/t", str(atraso)]
            subprocess.run(comando, check=True, timeout=10)
            return self._ok(f"Ação de energia agendada em {atraso} segundos.",
                            acao=pendente.acao, agendamento_id="windows-shutdown",
                            atraso_segundos=atraso)
        return self._erro("suspensão e hibernação remotas ainda indisponíveis no Windows")

    def _acao_status_energia(self, _args, **_):
        return self._erro("o Windows não expõe aqui uma lista confiável de agendamentos de energia")

    def _acao_cancelar_agendamento_energia(self, args, **_):
        pedido = str(args.get("agendamento_id") or "")
        if pedido not in {"", "windows-shutdown"}:
            raise ValueError("agendamento_id inválido")
        resultado = subprocess.run(["shutdown.exe", "/a"], timeout=10, capture_output=True)
        if resultado.returncode:
            return self._erro("nenhum desligamento agendado para cancelar")
        return self._ok("Cancelei o desligamento agendado.", cancelados=["windows-shutdown"])

    def _acao_baixar_youtube(self, args, **_):
        return self._erro("download direto no gateway Windows ainda indisponível")

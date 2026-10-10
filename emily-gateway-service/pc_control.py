#!/usr/bin/env python3
"""Executor autenticado para controle direto do PC Linux/KDE.

Este módulo é deliberadamente independente da Emily Desktop e de qualquer LLM.
Ele recebe apenas ações enumeradas, valida todos os argumentos e invoca programas
com ``shell=False``; o terminal explícito usa trabalhos idempotentes e confirmação.
"""

from __future__ import annotations

import base64
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus, urlparse, urlunparse

import requests


MAX_TEXTO = 500
MAX_RESULTADOS = 20
CONFIRMACAO_TTL = 90.0
ENERGIA_ATRASO_MINIMO = 10


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto)
    return " ".join("".join(c for c in sem_acento if not unicodedata.combining(c)).lower().split())


def _texto(valor: Any, *, nome: str, maximo: int = MAX_TEXTO) -> str:
    if not isinstance(valor, str):
        raise ValueError(f"{nome} precisa ser texto")
    limpo = valor.strip()
    if not limpo:
        raise ValueError(f"{nome} vazio")
    if len(limpo) > maximo or "\x00" in limpo:
        raise ValueError(f"{nome} inválido")
    return limpo


@dataclass(frozen=True)
class Aplicativo:
    nome: str
    desktop_id: str
    arquivo: Path


@dataclass
class ConfirmacaoEnergia:
    identificador: str
    acao: str
    turno_origem: str
    expira_em: float
    atraso_segundos: int = 0


class PCController:
    ACOES = frozenset({
        "programacao", "apps_listar", "apps_desinstalar", "apps_status", "apps_confirmar", "status", "buscar", "abrir_app", "abrir_jogo", "abrir_arquivo",
        "abrir_pasta", "abrir_site", "fechar_app", "preparar_energia",
        "confirmar_energia", "cancelar_energia", "status_energia",
        "cancelar_agendamento_energia", "navegador_status", "navegador_abas",
        "navegador_aba_ativa", "navegador_fechar_outras", "navegador_navegar",
        "navegador_ler", "navegador_youtube", "navegador_historico_youtube",
        "navegador_download",
        "midia_status", "midia_controlar", "capturar_tela", "baixar_youtube",
        "observacao_pendencias",
        "terminal_iniciar", "terminal_status", "terminal_cancelar", "terminal_confirmar", "visual_parar",
        "emily_iniciar", "visual_status", "visual_iniciar", "visual_mensagem", "visual_cancelar",
    })
    ENERGIA = {
        "desligar": ("desligar o computador", ["systemctl", "poweroff"]),
        "reiniciar": ("reiniciar o computador", ["systemctl", "reboot"]),
        "suspender": ("suspender o computador", ["systemctl", "suspend"]),
        "hibernar": ("hibernar o computador", ["systemctl", "hibernate"]),
    }
    PROCESSOS_PROTEGIDOS = frozenset({
        "systemd", "systemd-logind", "dbus-daemon", "dbus-broker", "plasmashell",
        "kwin_wayland", "kwin_x11", "pipewire", "wireplumber", "pulseaudio",
        "emily_gateway.py", "python3", "ssh", "sshd", "tailscaled",
    })
    PASTAS_IGNORADAS = frozenset({
        ".cache", ".git", ".gradle", ".idea", ".local/share/Trash", "node_modules",
        "__pycache__", ".ssh", ".gnupg", ".pki", ".password-store",
    })

    def __init__(
        self,
        *,
        home: Path | None = None,
        executor: Callable[..., Any] = subprocess.Popen,
        runner: Callable[..., Any] = subprocess.run,
        agora: Callable[[], float] = time.monotonic,
        token_provider: Callable[[], str] | None = None,
        browser_bridge: Any = None,
        energia_habilitada: bool | Callable[[], bool] = False,
    ) -> None:
        self.home = (home or Path.home()).expanduser().resolve()
        self._executor = executor
        self._runner = runner
        self._agora = agora
        self._token_provider = token_provider or (lambda: "")
        self._browser_bridge = browser_bridge
        self._energia_habilitada = energia_habilitada
        self._lock = threading.RLock()
        self._confirmacoes: dict[str, ConfirmacaoEnergia] = {}
        self._energia_direta = {}
        self._apps_cache: tuple[float, list[Aplicativo]] = (0.0, [])
        self._emily_process = None
        from pc_terminal import TerminalRemoto
        self._terminal = TerminalRemoto(self.home)
        from pc_apps import PCApps
        self._apps_removal = PCApps(self.home)

    def _acao_apps_listar(self, args, **_):
        return self._apps_removal.list(args)

    def _acao_apps_desinstalar(self, args, *, turno_id, irrestrito=False):
        return self._apps_removal.remove(args, turno_id, unrestricted=irrestrito)

    def _acao_apps_status(self, args, **_):
        return self._apps_removal.status(_texto(args.get("job_id"), nome="job_id", maximo=100), wait=15)

    def _acao_apps_confirmar(self, args, *, turno_id, **_):
        return self._apps_removal.confirm(args, turno_id)

    def _acao_programacao(self, args, **_):
        import programacao
        return programacao.execute(args.get("operacao"), args.get("argumentos", {}))

    def _acao_terminal_iniciar(self, args, *, turno_id, irrestrito=False):
        return self._terminal.iniciar(args, turno_id, irrestrito=irrestrito)

    def _acao_terminal_status(self, args, **_):
        return self._terminal.status(_texto(args.get("job_id"), nome="job_id", maximo=100))

    def _acao_terminal_cancelar(self, args, **_):
        return self._terminal.cancelar(_texto(args.get("job_id"), nome="job_id", maximo=100))

    def _acao_terminal_confirmar(self, args, *, turno_id):
        return self._terminal.confirmar(args, turno_id)

    def _acao_visual_parar(self, args, **_):
        return self._visual_call("stop", {})

    def definir_browser_bridge(self, bridge: Any) -> None:
        self._browser_bridge = bridge

    def _energia_esta_habilitada(self) -> bool:
        try:
            # Disjuntor contra regressões em testes: um teste pode habilitar a
            # flag por engano, mas jamais deve alcançar subprocess.run real.
            # Runners falsos continuam permitidos para validar o contrato.
            if os.getenv("PYTEST_CURRENT_TEST") and self._runner is subprocess.run:
                return False
            valor = self._energia_habilitada() if callable(self._energia_habilitada) else self._energia_habilitada
            return valor is True
        except Exception:
            return False

    from diagnostico_execucao import measured as _medir_execucao

    @_medir_execucao("pc_executor", "acao")
    def executar(self, acao: str, args: dict[str, Any] | None, *, turno_id: str = "", irrestrito=False) -> dict[str, Any]:
        if acao not in self.ACOES:
            return self._erro("ação não permitida")
        argumentos = args if isinstance(args, dict) else {}
        try:
            metodo = getattr(self, f"_acao_{acao}")
            extras={"irrestrito":irrestrito is True} if acao in {"terminal_iniciar","preparar_energia","apps_desinstalar"} else {}
            return metodo(argumentos, turno_id=_texto(turno_id, nome="turno_id", maximo=120),**extras)
        except ValueError as exc:
            return self._erro(str(exc))
        except (OSError, subprocess.SubprocessError) as exc:
            return self._erro(f"o sistema recusou a ação: {type(exc).__name__}")
        except Exception as exc:  # fronteira do serviço: nunca vaza traceback ao celular
            return self._erro(f"falha interna: {type(exc).__name__}")

    @staticmethod
    def _ok(mensagem: str, **dados: Any) -> dict[str, Any]:
        return {"ok": True, "mensagem": mensagem, **dados}

    @staticmethod
    def _erro(mensagem: str, **dados: Any) -> dict[str, Any]:
        return {"ok": False, "mensagem": mensagem, **dados}

    def _acao_status(self, _args: dict[str, Any], **_: Any) -> dict[str, Any]:
        carga = []
        try:
            carga = [round(v, 2) for v in os.getloadavg()]
        except OSError:
            pass
        disco = shutil.disk_usage(self.home)
        uptime = 0
        try:
            uptime = int(float(Path("/proc/uptime").read_text().split()[0]))
        except (OSError, ValueError, IndexError):
            pass
        dados = {
            "hostname": socket.gethostname(),
            "sistema": f"{platform.system()} {platform.release()}",
            "desktop": os.getenv("XDG_CURRENT_DESKTOP", "KDE"),
            "sessao": os.getenv("XDG_SESSION_TYPE", "desconhecida"),
            "uptime_segundos": uptime,
            "carga": carga,
            "disco_livre_bytes": disco.free,
            "disco_total_bytes": disco.total,
        }
        livre_gb = disco.free / (1024 ** 3)
        return self._ok(
            f"PC {dados['hostname']} online em {dados['desktop']}/{dados['sessao']}; "
            f"{livre_gb:.1f} GB livres.",
            status=dados,
        )

    def _desktop_ready(self) -> bool:
        try:
            response = requests.get("http://127.0.0.1:5001/status", timeout=1.5)
            return bool(response.ok and response.json().get("emily_pronta"))
        except (requests.RequestException, ValueError):
            return False

    def _acao_emily_iniciar(self, _args: dict[str, Any], **_: Any) -> dict[str, Any]:
        if self._desktop_ready():
            return self._ok("Emily desktop pronta.", pronta=True)
        with self._lock:
            if self._emily_process is not None and self._emily_process.poll() is None:
                return self._ok("Emily desktop está iniciando.", pronta=False)
            executable = Path(__file__).resolve().parent.parent / "dist" / "Emily" / "Emily"
            # Após reiniciar o gateway, o Popen anterior não está mais em memória.
            # Detecte a instância real; uma interface lenta não autoriza duplicá-la.
            for entrada in Path("/proc").iterdir():
                if not entrada.name.isdigit():
                    continue
                try:
                    if entrada.stat().st_uid != os.getuid():
                        continue
                    if (entrada / "exe").resolve() == executable.resolve():
                        return self._ok("Emily desktop já está aberta, mas a ponte ainda não respondeu. Não abri outra instância.", pronta=False)
                except OSError:
                    continue
            if not executable.is_file() or not os.access(executable, os.X_OK):
                return self._erro("Não encontrei a Emily compilada no PC.")
            if not (os.getenv("WAYLAND_DISPLAY") or os.getenv("DISPLAY")):
                return self._erro("A sessão gráfica do PC não está disponível para abrir a Emily.")
            self._emily_process = self._executor(
                [str(executable)], cwd=str(executable.parent),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
                env={k: v for k, v in os.environ.items() if not k.startswith("WERKZEUG_")},
            )
        return self._ok("Abrindo a Emily desktop.", pronta=False)

    def _visual_call(self, operation: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self._desktop_ready():
            return self._erro("Emily desktop ainda não está pronta.", pronta=False)
        token = self._token_provider()
        if not token:
            return self._erro("Token da ponte indisponível.")
        try:
            response = requests.post(
                "http://127.0.0.1:5001/pc/visual-monitor",
                headers={"Authorization": f"Bearer {token}"},
                json={"operation": operation, **args}, timeout=20,
            )
            data = response.json()
            return data if isinstance(data, dict) else self._erro("Resposta visual inválida.")
        except (requests.RequestException, ValueError) as exc:
            return self._erro(f"Não consegui consultar o agente visual: {type(exc).__name__}")

    def _acao_visual_status(self, _args: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self._visual_call("status", {})

    def _acao_visual_iniciar(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        action_id = _texto(args.get("action_id"), nome="action_id", maximo=80)
        objective = _texto(args.get("objective"), nome="objective", maximo=800)
        if not re.fullmatch(r"[a-f0-9-]{8,80}", action_id):
            raise ValueError("action_id inválido")
        return self._visual_call("start", {"action_id": action_id, "objective": objective})

    def _acao_visual_mensagem(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        action_id = _texto(args.get("action_id"), nome="action_id", maximo=80)
        message = _texto(args.get("message"), nome="message", maximo=800)
        if not re.fullmatch(r"[a-f0-9-]{8,80}", action_id):
            raise ValueError("action_id inválido")
        return self._visual_call("message", {"action_id": action_id, "message": message})

    def _acao_visual_cancelar(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        action_id = _texto(args.get("action_id"), nome="action_id", maximo=80)
        if not re.fullmatch(r"[a-f0-9-]{8,80}", action_id):
            raise ValueError("action_id inválido")
        return self._visual_call("cancel", {"action_id": action_id})

    def _roots(self) -> list[Path]:
        configuradas = os.getenv("EMILY_PC_RAIZES", "").strip()
        candidatas = [Path(p).expanduser() for p in configuradas.split(os.pathsep) if p.strip()] if configuradas else [self.home]
        for extra in (Path("/media") / self.home.name, Path("/run/media") / self.home.name):
            if extra.exists():
                candidatas.append(extra)
        roots: list[Path] = []
        for candidata in candidatas:
            try:
                real = candidata.resolve()
                if real.exists() and real not in roots:
                    roots.append(real)
            except OSError:
                continue
        return roots or [self.home]

    def _caminho_permitido(self, valor: Any, *, tipo: str) -> Path:
        bruto = _texto(valor, nome=tipo, maximo=1500)
        candidato = Path(bruto).expanduser()
        if not candidato.is_absolute():
            candidato = self.home / candidato
        real = candidato.resolve(strict=True)
        if not any(real == raiz or raiz in real.parents for raiz in self._roots()):
            raise ValueError(f"{tipo} fora das pastas permitidas")
        relativos = real.relative_to(self.home).parts if self.home == real or self.home in real.parents else ()
        if relativos and relativos[0] in {".ssh", ".gnupg", ".pki", ".password-store"}:
            raise ValueError(f"{tipo} protegido")
        if tipo == "arquivo" and not real.is_file():
            raise ValueError("arquivo não encontrado")
        if tipo == "pasta" and not real.is_dir():
            raise ValueError("pasta não encontrada")
        return real

    def _acao_buscar(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        consulta = _texto(args.get("query"), nome="query", maximo=160)
        tipo = str(args.get("tipo") or "todos").strip().lower()
        if tipo not in {"todos", "apps", "arquivos", "pastas"}:
            raise ValueError("tipo de busca inválido")
        limite = args.get("limite", 12)
        try:
            limite = max(1, min(MAX_RESULTADOS, int(limite)))
        except (TypeError, ValueError):
            limite = 12
        alvo = _normalizar(consulta)
        resultados: list[dict[str, str]] = []

        if tipo in {"todos", "apps"}:
            for app in self._buscar_apps(consulta, limite):
                resultados.append({"tipo": "app", "nome": app.nome, "alvo": app.desktop_id})
                if len(resultados) >= limite:
                    break

        if tipo in {"todos", "arquivos", "pastas"} and len(resultados) < limite:
            prazo = self._agora() + 2.5
            for raiz in self._roots():
                for atual, dirs, files in os.walk(raiz):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in self.PASTAS_IGNORADAS]
                    if tipo in {"todos", "pastas"}:
                        for nome in dirs:
                            if alvo in _normalizar(nome):
                                resultados.append({"tipo": "pasta", "nome": nome, "alvo": str(Path(atual) / nome)})
                                if len(resultados) >= limite:
                                    break
                    if len(resultados) >= limite:
                        break
                    if tipo in {"todos", "arquivos"}:
                        for nome in files:
                            if nome.startswith("."):
                                continue
                            if alvo in _normalizar(nome):
                                resultados.append({"tipo": "arquivo", "nome": nome, "alvo": str(Path(atual) / nome)})
                                if len(resultados) >= limite:
                                    break
                    if len(resultados) >= limite or self._agora() >= prazo:
                        break
                if len(resultados) >= limite or self._agora() >= prazo:
                    break

        if not resultados:
            return self._ok(f"Não encontrei nada por “{consulta}”.", resultados=[])
        resumo = "; ".join(f"{r['tipo']}: {r['nome']} ({r['alvo']})" for r in resultados)
        return self._ok(f"Encontrei {len(resultados)} resultado(s): {resumo}", resultados=resultados)

    def _desktop_dirs(self) -> list[Path]:
        return [
            self.home / ".local/share/applications",
            self.home / ".local/share/flatpak/exports/share/applications",
            Path("/var/lib/flatpak/exports/share/applications"),
            Path("/usr/local/share/applications"),
            Path("/usr/share/applications"),
        ]

    def _apps(self) -> list[Aplicativo]:
        agora = self._agora()
        with self._lock:
            instante, cache = self._apps_cache
            if cache and agora - instante < 60:
                return cache
        apps: list[Aplicativo] = []
        vistos: set[str] = set()
        for pasta in self._desktop_dirs():
            if not pasta.is_dir():
                continue
            for arquivo in sorted(pasta.glob("*.desktop")):
                desktop_id = arquivo.stem
                if desktop_id in vistos:
                    continue
                try:
                    nome = ""
                    oculto = False
                    for linha in arquivo.read_text(encoding="utf-8", errors="replace").splitlines():
                        if linha.startswith("Name=") and not nome:
                            nome = linha.split("=", 1)[1].strip()
                        elif linha in {"NoDisplay=true", "Hidden=true"}:
                            oculto = True
                    if nome and not oculto:
                        apps.append(Aplicativo(nome=nome, desktop_id=desktop_id, arquivo=arquivo))
                        vistos.add(desktop_id)
                except OSError:
                    continue
        with self._lock:
            self._apps_cache = (agora, apps)
        return apps

    def _buscar_apps(self, consulta: str, limite: int = 8) -> list[Aplicativo]:
        alvo = _normalizar(consulta)
        pontuados: list[tuple[int, str, Aplicativo]] = []
        for app in self._apps():
            nome = _normalizar(app.nome)
            did = _normalizar(app.desktop_id.replace("-", " ").replace(".", " "))
            if alvo == nome or alvo == did:
                score = 0
            elif nome.startswith(alvo) or did.startswith(alvo):
                score = 1
            elif alvo in nome or alvo in did:
                score = 2
            else:
                continue
            pontuados.append((score, nome, app))
        return [p[2] for p in sorted(pontuados, key=lambda item: (item[0], item[1]))[:limite]]

    def _abrir_app(self, nome: Any, *, jogo: bool = False) -> dict[str, Any]:
        consulta = _texto(nome, nome="nome", maximo=160)
        encontrados = self._buscar_apps(consulta, 5)
        if not encontrados:
            return self._erro(f"Não encontrei {'o jogo' if jogo else 'o aplicativo'} “{consulta}” instalado.")
        primeiro = encontrados[0]
        if len(encontrados) > 1 and _normalizar(primeiro.nome) != _normalizar(consulta):
            opcoes = ", ".join(a.nome for a in encontrados)
            return self._erro(f"Encontrei mais de uma opção: {opcoes}. Diga o nome mais exato.", opcoes=[a.nome for a in encontrados])
        self._spawn(["gtk-launch", primeiro.desktop_id])
        return self._ok(f"Abri {primeiro.nome} no PC.", app={"nome": primeiro.nome, "desktop_id": primeiro.desktop_id})

    def _acao_abrir_app(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self._abrir_app(args.get("nome"))

    def _acao_abrir_jogo(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self._abrir_app(args.get("nome"), jogo=True)

    def _acao_abrir_arquivo(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        caminho = self._caminho_permitido(args.get("caminho"), tipo="arquivo")
        self._spawn(["xdg-open", str(caminho)])
        return self._ok(f"Abri o arquivo {caminho.name}.", caminho=str(caminho))

    def _acao_abrir_pasta(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        caminho = self._caminho_permitido(args.get("caminho"), tipo="pasta")
        self._spawn(["xdg-open", str(caminho)])
        return self._ok(f"Abri a pasta {caminho.name or caminho}.", caminho=str(caminho))

    def _acao_abrir_site(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        bruto = _texto(args.get("url"), nome="url", maximo=2000)
        if "://" not in bruto:
            bruto = "https://" + bruto
        url = urlparse(bruto)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("URL inválida; use apenas site HTTP ou HTTPS")
        segura = urlunparse((url.scheme, url.netloc, url.path or "", url.params, url.query, ""))
        self._spawn(["xdg-open", segura])
        return self._ok(f"Abri {url.hostname} no navegador do PC.", url=segura)

    def _acao_fechar_app(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        consulta = _texto(args.get("nome"), nome="nome", maximo=120)
        alvo = _normalizar(consulta)
        encontrados: list[tuple[int, str]] = []
        uid = os.getuid()
        for entrada in Path("/proc").iterdir():
            if not entrada.name.isdigit():
                continue
            pid = int(entrada.name)
            if pid in {1, os.getpid(), os.getppid()}:
                continue
            try:
                if entrada.stat().st_uid != uid:
                    continue
                comm = (entrada / "comm").read_text(errors="replace").strip()
                cmd = (entrada / "cmdline").read_bytes().split(b"\0", 1)[0].decode(errors="replace")
                executavel = Path(cmd).name if cmd else comm
                campos = {_normalizar(comm), _normalizar(executavel)}
                if _normalizar(comm) in self.PROCESSOS_PROTEGIDOS or executavel in self.PROCESSOS_PROTEGIDOS:
                    continue
                if alvo in campos or any(alvo == c.removesuffix(".bin") for c in campos):
                    encontrados.append((pid, comm or executavel))
            except (OSError, UnicodeError):
                continue
        if not encontrados:
            return self._erro(f"Não achei “{consulta}” aberto como processo do usuário.")
        # PID + início: não confirme a saída de outro processo que reutilizou o PID.
        def identidade(pid):
            try:
                campos = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
                return None if campos[0] == "Z" else campos[19]
            except (OSError, IndexError):
                return None
        identidades = {pid: identidade(pid) for pid, _ in encontrados}
        recusados = []
        for pid, _ in encontrados:
            if identidades[pid] is None or identidade(pid) != identidades[pid]:
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                recusados.append(pid)
        prazo = time.monotonic() + 3
        while True:
            vivos = [pid for pid, inicio in identidades.items() if inicio is not None and identidade(pid) == inicio]
            if not vivos or time.monotonic() >= prazo:
                break
            time.sleep(0.1)
        nomes = sorted({nome for _, nome in encontrados})
        if vivos or recusados:
            return self._erro("Pedi para fechar, mas o aplicativo continua aberto. Pode haver um diálogo ou trabalho pendente; não forcei a saída.",
                              processos=nomes, processos_restantes=vivos)
        return self._ok(f"Confirmei que {', '.join(nomes)} saiu no PC.", processos=nomes)

    def _browser(self, acao: str, *, timeout: float = 12.0, **parametros: Any) -> dict[str, Any]:
        if self._browser_bridge is None:
            return self._erro("ponte permanente do navegador indisponível")
        resposta = self._browser_bridge.executar(acao, timeout=timeout, **parametros)
        if not resposta.get("ok"):
            return resposta
        dados = resposta.get("browser") or {}
        return self._ok(str(dados.get("mensagem") or "ação concluída no navegador"), browser=dados)

    @staticmethod
    def _tab_id(args: dict[str, Any], *, obrigatorio: bool = False) -> int | None:
        valor = args.get("tab_id")
        if valor in {None, ""} and not obrigatorio:
            return None
        if isinstance(valor, bool):
            raise ValueError("tab_id inválido")
        try:
            tab_id = int(valor)
        except (TypeError, ValueError):
            raise ValueError("tab_id precisa ser inteiro") from None
        if tab_id <= 0:
            raise ValueError("tab_id inválido")
        return tab_id

    def _acao_navegador_status(self, _args: dict[str, Any], **_: Any) -> dict[str, Any]:
        if self._browser_bridge is None:
            return self._erro("ponte permanente do navegador indisponível")
        status = self._browser_bridge.status()
        mensagem = "Extensão do navegador conectada." if status.get("conectado") else "Extensão do navegador desconectada."
        return self._ok(mensagem, navegador=status)

    def _acao_navegador_abas(self, _args: dict[str, Any], **_: Any) -> dict[str, Any]:
        resposta = self._browser("listar_abas")
        if not resposta.get("ok"):
            return resposta
        browser = resposta["browser"]
        abas = browser.get("abas") if isinstance(browser.get("abas"), list) else []
        return self._ok(f"Encontrei {len(abas)} abas abertas.", abas=abas)

    def _acao_navegador_aba_ativa(self, _args: dict[str, Any], **_: Any) -> dict[str, Any]:
        resposta = self._browser("diagnostico")
        if not resposta.get("ok"):
            return resposta
        browser = resposta["browser"]
        aba = browser.get("aba") if isinstance(browser.get("aba"), dict) else None
        if not aba:
            return self._erro("não há aba ativa disponível")
        return self._ok(f"A aba ativa é {aba.get('titulo') or aba.get('url') or aba.get('id')}.", aba=aba)

    def _acao_navegador_fechar_outras(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        tab_id = self._tab_id(args, obrigatorio=False)
        resposta = self._browser("fechar_outras_abas", tab_id=tab_id)
        if not resposta.get("ok"):
            return resposta
        browser = resposta["browser"]
        return self._ok(
            f"Fechei {int(browser.get('fechadas') or 0)} abas e preservei a aba {browser.get('preservada_id')}.",
            resultado=browser,
        )

    def _acao_navegador_navegar(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        bruto = _texto(args.get("url"), nome="url", maximo=2000)
        if "://" not in bruto:
            bruto = "https://" + bruto
        url = urlparse(bruto)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("URL inválida; use apenas HTTP ou HTTPS")
        segura = urlunparse((url.scheme, url.netloc, url.path or "", url.params, url.query, ""))
        tab_id = self._tab_id(args)
        nova_aba = bool(args.get("nova_aba", False))
        ativa = args.get("ativa", True) is not False
        resposta = self._browser("abrir_url", url=segura, tab_id=tab_id, nova_aba=nova_aba, ativa=ativa)
        if not resposta.get("ok"):
            return resposta
        return self._ok(f"Abri {url.hostname} no navegador.", url=segura, resultado=resposta["browser"])

    def _acao_navegador_ler(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        tab_id = self._tab_id(args)
        limite = args.get("limite", 30000)
        try:
            limite = max(1000, min(int(limite), 100000))
        except (TypeError, ValueError):
            raise ValueError("limite inválido") from None
        resposta = self._browser("ler_pagina", timeout=20.0, tab_id=tab_id)
        if not resposta.get("ok"):
            return resposta
        browser = dict(resposta["browser"])
        browser["texto"] = str(browser.get("texto") or "")[:limite]
        return self._ok(
            f"Li a página {browser.get('titulo') or browser.get('url') or ''}.",
            pagina=browser,
        )

    def _acao_navegador_youtube(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        busca = _texto(args.get("busca"), nome="busca", maximo=300)
        nova_aba = args.get("nova_aba", True) is not False
        resposta = self._browser(
            "abrir_youtube", timeout=20.0, busca=busca, nova_aba=nova_aba, ativa=True,
        )
        if not resposta.get("ok"):
            return resposta
        browser = resposta["browser"]
        url = str(browser.get("url") or f"https://www.youtube.com/results?search_query={quote_plus(busca)}")
        if browser.get("video_encontrado"):
            return self._ok(
                f"Abri o vídeo “{browser.get('titulo') or busca}” no YouTube.",
                url=url,
                resultado=browser,
            )
        return self._ok(
            f"Não achei um vídeo direto; deixei a busca por “{busca}” aberta no YouTube.",
            url=url,
            resultado=browser,
        )

    def _acao_navegador_historico_youtube(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        busca = str(args.get("busca") or "").strip()
        if len(busca) > 300 or "\x00" in busca:
            raise ValueError("busca inválida")
        try:
            limite = max(1, min(int(args.get("limite", 10)), 20))
        except (TypeError, ValueError):
            raise ValueError("limite inválido") from None
        resposta = self._browser(
            "historico_youtube", timeout=20.0, busca=busca, limite=limite,
        )
        if not resposta.get("ok"):
            return resposta
        browser = resposta["browser"]
        videos = browser.get("videos") if isinstance(browser.get("videos"), list) else []
        if not videos:
            complemento = f" por “{busca}”" if busca else ""
            login = " A conta do YouTube parece não estar logada." if browser.get("parece_login") else ""
            return self._ok(
                f"Não achei vídeos do YouTube no histórico{complemento}.{login}",
                videos=[],
                origem=browser.get("origem"),
                parece_login=bool(browser.get("parece_login")),
            )
        return self._ok(
            f"Encontrei {len(videos)} vídeo(s) no histórico do YouTube.",
            videos=videos,
            origem=browser.get("origem"),
        )

    def _acao_navegador_download(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        bruto = _texto(args.get("url"), nome="url", maximo=4000)
        url = urlparse(bruto)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("download direto aceita somente URL HTTP ou HTTPS")
        resposta = self._browser("baixar_arquivo", url=bruto, salvar_como=bool(args.get("salvar_como", False)))
        if not resposta.get("ok"):
            return resposta
        return self._ok("Iniciei o download pelo navegador.", resultado=resposta["browser"])

    def _executar_capturando(self, comando: list[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess:
        if not comando or not shutil.which(comando[0]):
            raise OSError(f"programa indisponível: {comando[0] if comando else '(vazio)'}")
        return self._runner(
            comando,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )

    def _player_escolhido(self, args: dict[str, Any]) -> str:
        pedido = str(args.get("player") or "").strip()
        if pedido and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", pedido):
            raise ValueError("player inválido")
        if pedido:
            return pedido
        lista = self._executar_capturando(["playerctl", "-l"], timeout=5.0)
        nomes = [linha.strip() for linha in lista.stdout.splitlines() if linha.strip()]
        if not nomes:
            raise ValueError("nenhum player MPRIS está disponível")
        for nome in nomes:
            estado = self._executar_capturando(["playerctl", "-p", nome, "status"], timeout=3.0)
            if estado.returncode == 0 and estado.stdout.strip().lower() == "playing":
                return nome
        return nomes[0]

    def _acao_midia_status(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        player = self._player_escolhido(args)
        formato = "{{status}}\t{{xesam:title}}\t{{xesam:artist}}\t{{mpris:length}}"
        resultado = self._executar_capturando(["playerctl", "-p", player, "metadata", "--format", formato], timeout=5.0)
        if resultado.returncode != 0:
            return self._erro("não consegui consultar o player MPRIS")
        campos = (resultado.stdout.rstrip("\n").split("\t") + ["", "", "", ""])[:4]
        duracao = 0
        try:
            duracao = int(campos[3] or 0)
        except ValueError:
            pass
        midia = {"player": player, "estado": campos[0], "titulo": campos[1], "artista": campos[2], "duracao_us": duracao}
        descricao = " — ".join(x for x in (campos[1], campos[2]) if x) or player
        return self._ok(f"{descricao}: {campos[0] or 'estado desconhecido'}.", midia=midia)

    def _acao_midia_controlar(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        acao = _texto(args.get("acao"), nome="ação", maximo=30).lower()
        mapa = {
            "tocar": "play", "pausar": "pause", "alternar": "play-pause",
            "proxima": "next", "anterior": "previous", "parar": "stop",
        }
        if acao not in mapa:
            raise ValueError("ação de mídia inválida")
        try:
            player = self._player_escolhido(args)
            resultado = self._executar_capturando(["playerctl", "-p", player, mapa[acao]], timeout=5.0)
            if resultado.returncode == 0:
                return self._ok(f"Controle de mídia “{acao}” enviado para {player}.", player=player, acao=acao)
        except (ValueError, OSError, subprocess.SubprocessError):
            pass
        # Fallback limitado ao vídeo/áudio HTML da aba, sem JavaScript arbitrário.
        if self._browser_bridge is not None:
            resposta = self._browser("controlar_midia", controle=acao, tab_id=self._tab_id(args))
            if resposta.get("ok"):
                return self._ok(f"Controle de mídia “{acao}” aplicado na aba do navegador.", resultado=resposta["browser"])
        return self._erro("nenhum player MPRIS ou mídia controlável foi encontrado")

    def _acao_capturar_tela(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        try:
            monitor = max(1, min(int(args.get("monitor", 1)), 16))
        except (TypeError, ValueError):
            raise ValueError("monitor inválido") from None
        token = str(self._token_provider() or "")
        if not token:
            return self._erro("captura desativada: configure EMILY_PONTE_TOKEN")
        try:
            resposta = requests.get(
                f"http://127.0.0.1:8790/tela/jpg?monitor={monitor}&unico=1",
                headers={"Authorization": f"Bearer {token}"},
                timeout=(1.5, 25.0),
            )
        except requests.RequestException as exc:
            return self._erro(
                f"o serviço de tela do PC está temporariamente indisponível ({type(exc).__name__}); "
                "confira o tela-pc.service"
            )
        if resposta.status_code != 200 or not resposta.content.startswith(b"\xff\xd8"):
            detalhe = ""
            try:
                detalhe = str(resposta.json().get("erro") or "").strip()
            except (ValueError, AttributeError, TypeError):
                pass
            sufixo = f": {detalhe[:240]}" if detalhe else ""
            return self._erro(
                f"o serviço de tela não conseguiu capturar agora ({resposta.status_code}){sufixo}"
            )
        if len(resposta.content) > 3 * 1024 * 1024:
            return self._erro("captura excedeu o limite de 3 MB")
        return self._ok(
            f"Capturei o monitor {monitor} sob demanda.",
            imagem_base64=base64.b64encode(resposta.content).decode("ascii"),
            mime_type="image/jpeg",
            monitor=monitor,
            tamanho_bytes=len(resposta.content),
            idade_segundos=resposta.headers.get("X-Emily-Idade", ""),
        )

    def _acao_observacao_pendencias(self, _args: dict[str, Any], **_: Any) -> dict[str, Any]:
        """Inventário de leitura, sem ativar janelas nem executar comandos do usuário."""
        monitores: list[dict[str, Any]] = []
        token = str(self._token_provider() or "")
        if token:
            try:
                resposta = requests.get(
                    "http://127.0.0.1:8790/tela/monitores",
                    headers={"Authorization": f"Bearer {token}"}, timeout=(1.5, 5.0),
                )
                if resposta.ok:
                    encontrados = resposta.json().get("monitores", [])
                    if isinstance(encontrados, list):
                        monitores = [m for m in encontrados[:16] if isinstance(m, dict)]
            except (requests.RequestException, ValueError, TypeError, KeyError):
                pass
        processos: list[dict[str, Any]] = []
        try:
            uid = os.getuid()
            for entrada in Path("/proc").iterdir():
                if not entrada.name.isdigit() or len(processos) >= 100:
                    continue
                try:
                    if entrada.stat().st_uid != uid:
                        continue
                    nome = (entrada / "comm").read_text(errors="replace").strip()[:80]
                    if nome and nome != "systemd":
                        processos.append({"pid": int(entrada.name), "nome": nome})
                except (OSError, ValueError):
                    continue
        except OSError:
            pass
        abas: list[dict[str, Any]] = []
        if self._browser_bridge is not None:
            try:
                resultado = self._acao_navegador_abas({})
                if resultado.get("ok"):
                    abas = [{"id": a.get("id"), "titulo": str(a.get("titulo") or "")[:160],
                             "url": str(a.get("url") or "")[:300]}
                            for a in resultado["abas"][:40] if isinstance(a, dict)]
            except (OSError, ValueError, RuntimeError):
                pass
        return self._ok("Inventário de observação consultado.", monitores=monitores,
                        processos=processos, abas=abas)

    def _acao_baixar_youtube(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        url_bruta = _texto(args.get("url"), nome="url", maximo=3000)
        url = urlparse(url_bruta)
        host = (url.hostname or "").lower().removeprefix("www.")
        if url.scheme not in {"http", "https"} or host not in {"youtube.com", "youtu.be", "music.youtube.com"}:
            raise ValueError("use uma URL válida do YouTube")
        formato = str(args.get("formato") or "mp4").strip().lower()
        if formato not in {"mp3", "mp4"}:
            raise ValueError("formato precisa ser mp3 ou mp4")
        ytdlp = shutil.which("yt-dlp") or str(self.home / ".local/bin/yt-dlp")
        if not Path(ytdlp).is_file():
            return self._erro("yt-dlp não está disponível no PC")
        pasta = self.home / "Downloads" / "Emily"
        pasta.mkdir(parents=True, exist_ok=True)
        comando = [
            ytdlp, "--no-playlist", "--no-overwrites", "--restrict-filenames",
            "--newline", "--print", "after_move:filepath",
            "-o", str(pasta / "%(title).180B [%(id)s].%(ext)s"),
        ]
        if formato == "mp3":
            comando += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
        else:
            comando += ["-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best", "--merge-output-format", "mp4"]
        comando.append(url_bruta)
        try:
            processo = self._executor(
                comando,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            return self._erro(f"não consegui iniciar o yt-dlp: {type(exc).__name__}")
        return self._ok(
            f"Iniciei o download do YouTube em {formato.upper()}; conteúdo com DRM não será burlado.",
            pid=getattr(processo, "pid", None),
            pasta=str(pasta),
            formato=formato,
        )

    def _acao_preparar_energia(self, args: dict[str, Any], *, turno_id: str, irrestrito=False, **_: Any) -> dict[str, Any]:
        if not self._energia_esta_habilitada():
            return self._erro(
                "controle de energia desabilitado; defina EMILY_ENERGIA_HABILITADA=1 no gateway para habilitar"
            )
        acao = _texto(args.get("acao"), nome="ação", maximo=30).lower()
        if acao not in self.ENERGIA:
            raise ValueError("ação de energia inválida")
        try:
            atraso = int(args.get("atraso_segundos", 0) or 0)
        except (TypeError, ValueError):
            raise ValueError("atraso_segundos inválido") from None
        if atraso < 0 or atraso > 7 * 24 * 3600:
            raise ValueError("atraso_segundos precisa ficar entre 0 e 604800")
        identificador = secrets.token_urlsafe(24)
        rotulo, _comando = self.ENERGIA[acao]
        pendente = ConfirmacaoEnergia(
            identificador, acao, turno_id, self._agora() + CONFIRMACAO_TTL, atraso,
        )
        with self._lock:
            self._limpar_confirmacoes()
            if irrestrito is True:
                self._energia_direta={k:v for k,v in self._energia_direta.items() if v[0]>self._agora()}
                chave=(turno_id,acao,atraso)
                if chave in self._energia_direta:
                    return self._energia_direta[chave][1]
            self._confirmacoes = {identificador: pendente}
            if irrestrito is True:
                resposta=self._acao_confirmar_energia({"confirmation_id":identificador},turno_id=turno_id,_autorizado_pelo_modo=True)
                if resposta.get('ok'):
                    self._energia_direta[chave]=(self._agora()+CONFIRMACAO_TTL,resposta)
                return resposta
        quando = f" em {atraso} segundos" if atraso else " agora"
        return self._ok(
            f"Tá bom, cê tem certeza que quer {rotulo}{quando}?",
            requer_confirmacao=True,
            confirmation_id=identificador,
            confirmacao_expira_em_segundos=int(CONFIRMACAO_TTL),
            acao=acao,
            atraso_segundos=atraso,
        )

    def _acao_confirmar_energia(self, args: dict[str, Any], *, turno_id: str, _autorizado_pelo_modo=False, **_: Any) -> dict[str, Any]:
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
        rotulo, comando = self.ENERGIA[pendente.acao]
        # Consulte a capacidade antes de anunciar sucesso; um timer aceito pelo
        # systemd não significa que logind permitirá a ação quando ele disparar.
        metodo = {"suspender": "CanSuspend", "hibernar": "CanHibernate",
                  "desligar": "CanPowerOff", "reiniciar": "CanReboot"}[pendente.acao]
        if shutil.which("busctl"):
            capacidade = self._executar_capturando([
                "busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                "org.freedesktop.login1.Manager", metodo,
            ], timeout=3.0)
            if capacidade.returncode != 0 or capacidade.stdout.strip() in ('s "no"', 's "na"', 's "challenge"'):
                return self._erro("O Linux não autorizou esta ação de energia. Nenhuma ação foi agendada; confira a permissão do logind/polkit.")
        atraso = max(ENERGIA_ATRASO_MINIMO, pendente.atraso_segundos)
        unidade = f"emily-energia-{identificador[:16].lower().replace('_', '-')}"
        resultado = self._executar_capturando([
            "systemd-run", "--user", f"--unit={unidade}", f"--on-active={atraso}s",
            "--property=Type=oneshot", "--timer-property=AccuracySec=1s", *comando,
        ], timeout=10.0)
        if resultado.returncode != 0:
            return self._erro("o systemd recusou o agendamento de energia")
        mensagem_tempo = f"em {atraso} segundos"
        return self._ok(
            f"Confirmado: o PC aceitou o comando para {rotulo} {mensagem_tempo}. A conexão vai cair durante essa ação; isso é esperado.",
            acao=pendente.acao,
            estado="agendado", comando_aceito=True, desconexao_esperada=True,
            verificacao_remota_necessaria=False,
            orientacao="Confirme o comando aceito sem consultar novamente o PC só para validar energia. A desconexão prevista não é falha, mas não prova fisicamente o estado final. Uma falha explícita do executor deve ser informada.",
            agendamento_id=unidade,
            atraso_segundos=atraso,
            atraso_solicitado_segundos=pendente.atraso_segundos,
        )

    def _acao_cancelar_energia(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        identificador = str(args.get("confirmation_id") or "").strip()
        with self._lock:
            if identificador:
                self._confirmacoes.pop(identificador, None)
            else:
                self._confirmacoes.clear()
        return self._ok("A ação de energia foi cancelada.")

    @staticmethod
    def _unidade_energia(valor: Any) -> str:
        unidade = _texto(valor, nome="agendamento_id", maximo=80)
        if not re.fullmatch(r"emily-energia-[a-z0-9-]{1,40}", unidade):
            raise ValueError("agendamento_id inválido")
        return unidade

    def _listar_agendamentos_energia(self) -> list[dict[str, Any]]:
        resultado = self._executar_capturando([
            "systemctl", "--user", "list-units", "emily-energia-*.timer", "emily-energia-*.service", "--all",
            "--plain", "--no-legend", "--no-pager",
        ], timeout=8.0)
        unidades = set()
        for linha in resultado.stdout.splitlines():
            nome = linha.lstrip("● ").split(maxsplit=1)[0] if linha.strip() else ""
            if re.fullmatch(r"emily-energia-[a-z0-9-]+\.(timer|service)", nome):
                unidades.add(nome.rsplit(".", 1)[0])
        if not unidades:
            return []
        # Uma única consulta para todos os timers e seus resultados, inclusive falhas.
        nomes = [f"{u}.{suffix}" for u in sorted(unidades)[:20] for suffix in ("timer", "service")]
        detalhes = self._executar_capturando([
            "systemctl", "--user", "show", *nomes,
            "-p", "Id", "-p", "ActiveState", "-p", "SubState",
            "-p", "NextElapseUSecRealtime", "-p", "Triggers", "-p", "Result", "-p", "ExecMainStatus",
        ], timeout=5.0)
        registros = {}
        for bloco in detalhes.stdout.strip().split("\n\n"):
            dados = dict(linha.split("=", 1) for linha in bloco.splitlines() if "=" in linha)
            registros[dados.get("Id", "")] = dados
        agendamentos = []
        for unidade in sorted(unidades)[:20]:
            timer = registros.get(unidade + ".timer", {})
            servico = registros.get(unidade + ".service", {})
            falhou = servico.get("ActiveState") == "failed" or servico.get("Result", "success") not in ("", "success")
            agendamentos.append({
                "id": unidade,
                "estado": "failed" if falhou else timer.get("ActiveState", servico.get("ActiveState", "")),
                "subestado": timer.get("SubState", servico.get("SubState", "")),
                "proxima_execucao": timer.get("NextElapseUSecRealtime", ""),
                "servico": unidade + ".service",
                "resultado_execucao": servico.get("Result", ""),
                "codigo_saida": servico.get("ExecMainStatus", ""),
                "falhou": falhou,
            })
        return agendamentos

    def _acao_status_energia(self, _args: dict[str, Any], **_: Any) -> dict[str, Any]:
        agendamentos = self._listar_agendamentos_energia()
        if not agendamentos:
            return self._ok("Não há ação de energia agendada.", agendamentos=[])
        falhas = sum(item["falhou"] for item in agendamentos)
        return self._ok(f"Há {len(agendamentos)} registro de energia; {falhas} falharam na execução.", agendamentos=agendamentos)

    def _acao_cancelar_agendamento_energia(self, args: dict[str, Any], **_: Any) -> dict[str, Any]:
        pedido = str(args.get("agendamento_id") or "").strip()
        unidades = [self._unidade_energia(pedido)] if pedido else [
            item["id"] for item in self._listar_agendamentos_energia()
        ]
        if not unidades:
            return self._ok("Não havia ação de energia agendada.", cancelados=[])
        cancelados: list[str] = []
        for unidade in unidades:
            resultado = self._executar_capturando([
                "systemctl", "--user", "stop", f"{unidade}.timer", f"{unidade}.service",
            ], timeout=8.0)
            # O .service ainda não estar carregado é normal; parar o timer é a
            # operação decisiva e o systemctl pode retornar !=0 por causa dele.
            if "Access denied" in resultado.stderr or "Authentication" in resultado.stderr:
                return self._erro("o systemd recusou cancelar o agendamento")
            cancelados.append(unidade)
        return self._ok(f"Cancelei {len(cancelados)} ação de energia agendada.", cancelados=cancelados)

    def _ambiente_desktop(self) -> dict[str, str]:
        """Reconstrói o ambiente gráfico quando o user service subiu cedo demais.

        No Plasma, o gerenciador ``systemd --user`` pode iniciar o gateway antes de
        DISPLAY/WAYLAND_DISPLAY serem importados. Disco e buscas continuam funcionando,
        mas gtk-launch/xdg-open morrem sem mostrar janela. Os sockets da sessão são a
        fonte mais confiável e já pertencem ao mesmo usuário do serviço.
        """
        ambiente = os.environ.copy()
        runtime = ambiente.get("XDG_RUNTIME_DIR", "").strip()
        if not runtime and hasattr(os, "getuid"):
            candidato = Path(f"/run/user/{os.getuid()}")
            if candidato.is_dir():
                runtime = str(candidato)
                ambiente["XDG_RUNTIME_DIR"] = runtime

        if runtime:
            barramento = Path(runtime) / "bus"
            if "DBUS_SESSION_BUS_ADDRESS" not in ambiente and barramento.exists():
                ambiente["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={barramento}"
            if not ambiente.get("WAYLAND_DISPLAY"):
                sockets = sorted(
                    caminho for caminho in Path(runtime).glob("wayland-*")
                    if not caminho.name.endswith(".lock") and caminho.is_socket()
                )
                if sockets:
                    ambiente["WAYLAND_DISPLAY"] = sockets[0].name

        if not ambiente.get("DISPLAY"):
            sockets_x11 = sorted(Path("/tmp/.X11-unix").glob("X*"))
            if sockets_x11:
                numero = sockets_x11[0].name.removeprefix("X")
                if numero.isdigit():
                    ambiente["DISPLAY"] = f":{numero}"

        if ambiente.get("WAYLAND_DISPLAY"):
            ambiente.setdefault("XDG_SESSION_TYPE", "wayland")
        elif ambiente.get("DISPLAY"):
            ambiente.setdefault("XDG_SESSION_TYPE", "x11")
        ambiente.setdefault("XDG_CURRENT_DESKTOP", "KDE")
        return ambiente

    def _limpar_confirmacoes(self) -> None:
        agora = self._agora()
        expiradas = [cid for cid, item in self._confirmacoes.items() if item.expira_em <= agora]
        for cid in expiradas:
            self._confirmacoes.pop(cid, None)

    def _spawn(self, comando: list[str]) -> Any:
        if not comando or not shutil.which(comando[0]):
            raise OSError(f"programa indisponível: {comando[0] if comando else '(vazio)'}")
        processo = self._executor(
            comando,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            env=self._ambiente_desktop(),
            start_new_session=True,
            close_fds=True,
        )
        esperar = getattr(processo, "wait", None)
        if not callable(esperar):
            return processo
        try:
            codigo = esperar(timeout=0.35)
        except subprocess.TimeoutExpired:
            # O launcher permaneceu vivo: a ação foi aceita. Fecha apenas a ponta
            # de leitura local para não reter descritor no gateway permanente.
            erro = getattr(processo, "stderr", None)
            if erro is not None:
                try:
                    erro.close()
                except OSError:
                    pass
            return processo
        if codigo != 0:
            erro = getattr(processo, "stderr", None)
            detalhe = ""
            if erro is not None:
                try:
                    detalhe = str(erro.read() or "").strip()
                except (OSError, ValueError):
                    pass
            detalhe = " ".join(detalhe.split())[:240]
            if detalhe:
                raise ValueError(f"não consegui abrir na sessão gráfica do PC: {detalhe}")
            raise ValueError("não consegui abrir na sessão gráfica do PC")
        return processo

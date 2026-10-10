"""Backends multiplataforma para captura e automação do desktop.

O módulo não importa ``pyautogui``, ``mss`` nem bibliotecas de sessão gráfica
durante o carregamento. Isso permite importar e testar o agente em CI/headless.

Seleção padrão:

* Windows e sessões X11: :class:`BackendPyAutoGUI`;
* KDE Wayland: :class:`BackendKDEWayland`, com Spectacle para captura e
  ``ydotool`` para entrada;
* testes: :class:`BackendDesktopFalso`.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import math
import os
import platform
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Optional, Sequence


_TRAVA_TEXTO = threading.RLock()


class ErroBackendDesktop(RuntimeError):
    """Falha operacional ou recurso indisponível no backend desktop."""


def _configurar_dpi_windows() -> None:
    """Estabelece coordenadas físicas antes que pyautogui/mss inicializem o DPI."""
    if platform.system().lower() != "windows":
        return
    import ctypes

    try:
        # Per-monitor v2; não reduz o monitor secundário à escala do principal.
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


@dataclass(frozen=True)
class CapacidadesDesktop:
    nome: str
    captura: bool
    entrada: bool
    janelas: bool
    motivo_indisponivel: str = ""

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


class BackendDesktop:
    """Contrato mínimo consumido por ``SessaoAgenteUI``."""

    IMG_W = 1280
    IMG_H = 720

    def capacidades(self) -> CapacidadesDesktop:
        raise NotImplementedError

    def capturar_tela(self) -> str:
        """Captura limpa para leitura visual, sem grade nem marcadores."""
        raise NotImplementedError

    def capturar_tela_com_grade(self) -> str:
        raise NotImplementedError

    def capturar_tela_para_verificacao(self, x: int, y: int) -> list[str]:
        """Captura posterior ao apontamento; backends simples repetem a visão geral."""
        captura = self.capturar_tela_com_grade()
        # Duas imagens também sinalizam ao decisor que ele está no contrato de
        # confirmação. Backends reais sobrescrevem isto com visão geral + zoom.
        return [captura, captura]

    def coordenada_no_zoom(self, zoom_x: float, zoom_y: float) -> tuple[int, int]:
        """Traduz um ponto da última imagem ampliada (0–1000) para a tela."""
        raise ErroBackendDesktop("o backend não oferece ajuste fino pelo zoom")

    def geometria(self) -> dict[str, int]:
        raise NotImplementedError

    def mover(self, x: int, y: int, duracao: float = 0.0) -> None:
        raise NotImplementedError

    def clicar(self, x: int, y: int, botao: str = "left", cliques: int = 1) -> None:
        raise NotImplementedError

    def digitar(self, texto: str, intervalo: float = 0.0) -> None:
        raise NotImplementedError

    def pressionar(self, tecla: str, vezes: int = 1) -> None:
        raise NotImplementedError

    def atalho(self, teclas: Sequence[str]) -> None:
        raise NotImplementedError

    def rolar(self, quantidade: int) -> None:
        raise NotImplementedError

    def ativar_janela(self, nome: str) -> bool:
        return False

    def abrir_app(self, nome: str) -> bool:
        return _abrir_app_portatil(nome)

    def esperar(self, segundos: float, cancelar: Optional[threading.Event] = None) -> bool:
        """Espera de modo cancelável. Retorna ``False`` quando cancelada."""
        fim = time.monotonic() + max(0.0, float(segundos))
        while time.monotonic() < fim:
            if cancelar is not None and cancelar.wait(min(0.05, fim - time.monotonic())):
                return False
            if cancelar is None:
                time.sleep(min(0.05, fim - time.monotonic()))
        return True

    def fechar(self) -> None:
        """Gancho para backends que mantêm recursos persistentes."""


def _normalizar_imagem_modelo(imagem):
    """Reduz capturas grandes sem deformar a proporção original do monitor."""
    # Import tardio: Pillow não é necessário para importar/testar contratos.
    from PIL import Image

    if not isinstance(imagem, Image.Image):
        imagem = Image.open(imagem)
    imagem = imagem.convert("RGB")
    imagem.thumbnail((BackendDesktop.IMG_W, 1024), Image.Resampling.LANCZOS)
    return imagem


def _codificar_png_base64(imagem) -> str:
    buffer = BytesIO()
    # Compressão normal evita a busca exaustiva do optimize=True. PNG continua
    # sem perdas: mesmos pixels, resolução, grade e marcadores.
    imagem.save(buffer, format="PNG", compress_level=6, optimize=False)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _imagem_para_modelo_base64(imagem) -> str:
    """Preserva a proporção e devolve uma captura limpa em JPEG/base64."""
    imagem = _normalizar_imagem_modelo(imagem)
    buffer = BytesIO()
    imagem.save(buffer, format="JPEG", quality=85, optimize=False)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _imagem_para_grade_base64(imagem) -> str:
    """Preserva a proporção, desenha uma grade discreta e devolve PNG em base64."""
    import visao

    imagem = _normalizar_imagem_modelo(imagem)
    imagem = visao._desenhar_grade(imagem)
    return _codificar_png_base64(imagem)


def _desenhar_marcador_alvo(imagem, x: int, y: int, raio: int = 18):
    """Marca o ponto escolhido sem esconder o conteúdo que fica dentro do anel."""
    from PIL import ImageDraw

    img = imagem.copy().convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    x, y = int(x), int(y)
    for largura, cor in ((8, (0, 0, 0, 230)), (4, (255, 0, 255, 255))):
        draw.ellipse((x - raio, y - raio, x + raio, y + raio), outline=cor, width=largura)
        draw.line((x - raio - 10, y, x - raio + 2, y), fill=cor, width=largura)
        draw.line((x + raio - 2, y, x + raio + 10, y), fill=cor, width=largura)
        draw.line((x, y - raio - 10, x, y - raio + 2), fill=cor, width=largura)
        draw.line((x, y + raio - 2, x, y + raio + 10), fill=cor, width=largura)
    return img


def _imagens_para_verificacao_base64(
    imagem, x_tela: int, y_tela: int, geometria: dict[str, int],
    *, retornar_mapa: bool = False,
) -> list[str] | tuple[list[str], dict[str, int]]:
    """Gera visão geral com grade e um recorte ampliado do alvo apontado."""
    from PIL import Image
    import visao

    if not isinstance(imagem, Image.Image):
        imagem = Image.open(imagem)
    original = imagem.convert("RGB")
    largura_real = max(1, int(geometria.get("width", original.width)))
    altura_real = max(1, int(geometria.get("height", original.height)))
    rel_x = min(1.0, max(0.0, (int(x_tela) - int(geometria.get("left", 0))) / largura_real))
    rel_y = min(1.0, max(0.0, (int(y_tela) - int(geometria.get("top", 0))) / altura_real))

    geral_limpa = _normalizar_imagem_modelo(original)
    gx = round(rel_x * max(0, geral_limpa.width - 1))
    gy = round(rel_y * max(0, geral_limpa.height - 1))
    geral = visao._desenhar_grade(geral_limpa)
    geral = _desenhar_marcador_alvo(geral, gx, gy, raio=18)

    ox = round(rel_x * max(0, original.width - 1))
    oy = round(rel_y * max(0, original.height - 1))
    meia_largura = min(320, max(160, original.width // 5))
    meia_altura = min(240, max(120, original.height // 5))
    esquerda = max(0, ox - meia_largura)
    topo = max(0, oy - meia_altura)
    direita = min(original.width, ox + meia_largura)
    base = min(original.height, oy + meia_altura)
    recorte = original.crop((esquerda, topo, direita, base))
    rx, ry = ox - esquerda, oy - topo
    escala = min(2.0, 960 / max(1, recorte.width), 720 / max(1, recorte.height))
    if escala > 1.0:
        recorte = recorte.resize(
            (round(recorte.width * escala), round(recorte.height * escala)),
            Image.Resampling.LANCZOS,
        )
        rx, ry = round(rx * escala), round(ry * escala)
    recorte = _desenhar_marcador_alvo(recorte, rx, ry, raio=24)
    imagens = [_codificar_png_base64(geral), _codificar_png_base64(recorte)]
    if not retornar_mapa:
        return imagens
    return imagens, {
        "crop_left": esquerda, "crop_top": topo,
        "crop_width": direita - esquerda, "crop_height": base - topo,
        "image_width": original.width, "image_height": original.height,
        **geometria,
    }


def _coordenada_no_zoom(mapa: dict[str, int], zoom_x: float, zoom_y: float) -> tuple[int, int]:
    """Converte a posição relativa do recorte para coordenadas lógicas do desktop."""
    for valor in (zoom_x, zoom_y):
        if not math.isfinite(float(valor)) or not 0 <= float(valor) <= 1000:
            raise ErroBackendDesktop("ponto do zoom fora de 0–1000")
    px = mapa["crop_left"] + float(zoom_x) / 1000 * max(0, mapa["crop_width"] - 1)
    py = mapa["crop_top"] + float(zoom_y) / 1000 * max(0, mapa["crop_height"] - 1)
    largura = max(1, int(mapa["width"]))
    altura = max(1, int(mapa["height"]))
    x = int(mapa["left"]) + min(largura - 1, max(0, round(px / mapa["image_width"] * largura)))
    y = int(mapa["top"]) + min(altura - 1, max(0, round(py / mapa["image_height"] * altura)))
    return x, y


class BackendPyAutoGUI(BackendDesktop):
    """Backend para Windows e X11, com import totalmente tardio."""

    def __init__(self) -> None:
        self._pyautogui = None
        self._ultima_geometria: Optional[dict[str, int]] = None
        self._ultimo_mapa_zoom: Optional[dict[str, int]] = None

    def _capturar_monitor(self):
        """A imagem e a geometria precisam vir do MESMO grab do mss."""
        try:
            _configurar_dpi_windows()
            import mss
            import visao
            from PIL import Image

            with mss.mss() as sct:
                # Usar a enumeração da própria instância que faz o grab:
                # outra chamada a mss() poderia enumerar em ordem diferente.
                ordem = sorted(range(1, len(sct.monitors)), key=lambda i: (
                    0 if sct.monitors[i].get("is_primary") else 1,
                    sct.monitors[i].get("left", 0), sct.monitors[i].get("top", 0),
                ))
                if not ordem:
                    raise ErroBackendDesktop("nenhum monitor disponível para captura")
                indice = ordem[min(max(1, int(visao.monitor_atual)), len(ordem)) - 1]
                monitor = dict(sct.monitors[indice])
                captura = sct.grab(monitor)
            imagem = Image.frombytes("RGB", captura.size, captura.bgra, "raw", "BGRX")
            if imagem.size != (int(monitor["width"]), int(monitor["height"])):
                raise ErroBackendDesktop("captura e geometria do monitor não coincidem")
            self._ultima_geometria = {
                "left": int(monitor["left"]), "top": int(monitor["top"]),
                "width": imagem.width, "height": imagem.height,
            }
            return imagem
        except ErroBackendDesktop:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ErroBackendDesktop(f"falha ao capturar monitor com mss: {exc}") from exc

    def _py(self):
        if self._pyautogui is None:
            try:
                _configurar_dpi_windows()
                import pyautogui
            except Exception as exc:  # noqa: BLE001
                raise ErroBackendDesktop(f"pyautogui indisponível: {exc}") from exc
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.08
            self._pyautogui = pyautogui
        return self._pyautogui

    def capacidades(self) -> CapacidadesDesktop:
        try:
            self._py()
            import mss  # noqa: F401 — captura usa mss, não o screenshot do pyautogui
        except Exception as exc:  # noqa: BLE001
            return CapacidadesDesktop("pyautogui", False, False, False, str(exc))
        return CapacidadesDesktop("pyautogui", True, True, True)

    def capturar_tela(self) -> str:
        return _imagem_para_modelo_base64(self._capturar_monitor())

    def capturar_tela_com_grade(self) -> str:
        return _imagem_para_grade_base64(self._capturar_monitor())

    def capturar_tela_para_verificacao(self, x: int, y: int) -> list[str]:
        imagem = self._capturar_monitor()
        imagens, self._ultimo_mapa_zoom = _imagens_para_verificacao_base64(
            imagem, int(x), int(y), self.geometria(), retornar_mapa=True,
        )
        return imagens

    def coordenada_no_zoom(self, zoom_x: float, zoom_y: float) -> tuple[int, int]:
        if self._ultimo_mapa_zoom is None:
            raise ErroBackendDesktop("não há zoom recente para ajustar o clique")
        return _coordenada_no_zoom(self._ultimo_mapa_zoom, zoom_x, zoom_y)

    def geometria(self) -> dict[str, int]:
        if self._ultima_geometria is None:
            self._capturar_monitor()
        return dict(self._ultima_geometria)

    def mover(self, x: int, y: int, duracao: float = 0.0) -> None:
        self._py().moveTo(int(x), int(y), duration=max(0.0, float(duracao)))

    def clicar(self, x: int, y: int, botao: str = "left", cliques: int = 1) -> None:
        self._py().click(int(x), int(y), clicks=max(1, int(cliques)), button=botao)

    def digitar(self, texto: str, intervalo: float = 0.0) -> None:
        texto = str(texto)
        if not texto:
            return
        with _TRAVA_TEXTO:
            try:
                import pyperclip
                pyperclip.copy(texto)
                self.atalho(("shift", "insert"))
                time.sleep(0.25)
            except Exception as exc:  # noqa: BLE001
                raise ErroBackendDesktop(f"não consegui colar o texto: {exc}") from exc

    def pressionar(self, tecla: str, vezes: int = 1) -> None:
        self._py().press(str(tecla).lower(), presses=max(1, int(vezes)), interval=0.05)

    def atalho(self, teclas: Sequence[str]) -> None:
        self._py().hotkey(*(str(t).lower() for t in teclas))

    def rolar(self, quantidade: int) -> None:
        self._py().scroll(int(quantidade))

    def ativar_janela(self, nome: str) -> bool:
        nome = (nome or "").strip().lower()
        if not nome:
            return False
        try:
            janelas = self._py().getAllWindows()
            candidatas = [w for w in janelas if getattr(w, "title", "") and nome in w.title.lower()]
            if not candidatas:
                palavras = [p for p in nome.split() if len(p) > 2]
                candidatas = [
                    w for w in janelas if getattr(w, "title", "")
                    and any(p in w.title.lower() for p in palavras)
                ]
            if not candidatas:
                return False
            janela = max(candidatas, key=lambda w: getattr(w, "width", 0) * getattr(w, "height", 0))
            if getattr(janela, "isMinimized", False):
                janela.restore()
            janela.activate()
            return True
        except Exception:
            return False


class BackendKDEWayland(BackendDesktop):
    """KDE Wayland: Spectacle captura; ydotool injeta mouse e teclado."""

    # O KWin/ydotool pode terminar movimentos relativos com alguns pixels de
    # diferença por arredondamento e aceleração. Insistir em correções menores
    # que isso pode amplificá-las e afastar novamente o cursor do alvo.
    TOLERANCIA_CURSOR = max(1, int(os.getenv("EMILY_TOLERANCIA_CURSOR", "1")))

    _CODIGOS_TECLA = {
        "esc": 1, "escape": 1, "1": 2, "2": 3, "3": 4, "4": 5,
        "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
        "backspace": 14, "tab": 15, "enter": 28, "return": 28,
        "ctrl": 29, "control": 29, "shift": 42, "alt": 56, "space": 57,
        "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64,
        "f7": 65, "f8": 66, "f9": 67, "f10": 68, "home": 102,
        "up": 103, "pageup": 104, "left": 105, "right": 106, "end": 107,
        "down": 108, "pagedown": 109, "insert": 110, "delete": 111,
        "meta": 125, "win": 125, "super": 125,
        "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33,
        "g": 34, "h": 35, "i": 23, "j": 36, "k": 37, "l": 38,
        "m": 50, "n": 49, "o": 24, "p": 25, "q": 16, "r": 19,
        "s": 31, "t": 20, "u": 22, "v": 47, "w": 17, "x": 45,
        "y": 21, "z": 44,
    }

    def __init__(self, spectacle: Optional[str] = None, ydotool: Optional[str] = None) -> None:
        self.spectacle = spectacle or shutil.which("spectacle")
        self.ydotool = ydotool or shutil.which("ydotool")
        self.busctl = shutil.which("busctl")
        self.kscreen_doctor = shutil.which("kscreen-doctor")
        self._ultima_geometria = {"left": 0, "top": 0, "width": 1280, "height": 720}
        self._ultimo_mapa_zoom: Optional[dict[str, int]] = None

    @staticmethod
    def _dimensao_logica_saida(saida: dict[str, Any]) -> tuple[int, int]:
        """Converte modo físico/escala do KScreen para tamanho lógico do KWin."""
        tamanho = saida.get("size") or {}
        largura = int(tamanho.get("width") or 0)
        altura = int(tamanho.get("height") or 0)
        if not largura or not altura:
            modo_id = str(saida.get("currentModeId") or "")
            modo = next((m for m in saida.get("modes", []) if str(m.get("id")) == modo_id), {})
            tamanho = modo.get("size") or {}
            largura = int(tamanho.get("width") or 0)
            altura = int(tamanho.get("height") or 0)
        escala = float(saida.get("scale") or 1.0)
        if escala <= 0:
            escala = 1.0
        largura = max(1, round(largura / escala))
        altura = max(1, round(altura / escala))
        # No JSON do KScreen, 1 representa a orientação normal. Em rotações de
        # 90/270 graus a área lógica troca os eixos.
        if int(saida.get("rotation") or 1) in {2, 8}:
            largura, altura = altura, largura
        return largura, altura

    def _saidas_kscreen(self) -> list[dict[str, Any]]:
        if not self.kscreen_doctor:
            return []
        resultado = self._rodar((self.kscreen_doctor, "-j"))
        try:
            dados = json.loads(resultado.stdout or "{}")
        except (TypeError, ValueError) as exc:
            raise ErroBackendDesktop(f"KScreen devolveu geometria inválida: {exc}") from exc
        return [s for s in dados.get("outputs", []) if s.get("enabled") and s.get("connected")]

    def _nome_saida_ativa(self) -> str:
        if not self.busctl:
            return ""
        try:
            resultado = self._rodar((
                self.busctl, "--user", "call", "org.kde.KWin", "/KWin",
                "org.kde.KWin", "activeOutputName",
            ))
        except ErroBackendDesktop:
            return ""
        texto = (resultado.stdout or "").strip()
        if '"' in texto:
            return texto.split('"', 2)[1]
        partes = texto.split(maxsplit=1)
        return partes[-1].strip() if partes else ""

    def _geometria_saida_ativa(self) -> dict[str, int]:
        saidas = self._saidas_kscreen()
        if not saidas:
            return dict(self._ultima_geometria)
        nome = self._nome_saida_ativa()
        saida = next((s for s in saidas if str(s.get("name")) == nome), None)
        if saida is None:
            saida = min(saidas, key=lambda s: int(s.get("priority") or 9999))
        posicao = saida.get("pos") or {}
        largura, altura = self._dimensao_logica_saida(saida)
        return {
            "left": int(posicao.get("x") or 0),
            "top": int(posicao.get("y") or 0),
            "width": largura,
            "height": altura,
        }

    @staticmethod
    def _receptor_cursor_kwin():
        """Cria, sob demanda, receptor D-Bus para consultas a workspace.cursorPos."""
        global _RECEPTOR_CURSOR_KWIN
        try:
            return _RECEPTOR_CURSOR_KWIN
        except NameError:
            pass

        import dbus
        import dbus.service
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib

        DBusGMainLoop(set_as_default=True)

        class Receptor:
            caminho = "/org/emily/CursorProbe"
            interface = "org.emily.CursorProbe"

            def __init__(self):
                self.nome = f"org.emily.CursorProbe.p{os.getpid()}"
                self.bus = dbus.SessionBus()
                self.nome_bus = dbus.service.BusName(self.nome, bus=self.bus, do_not_queue=True)
                self.lock = threading.Lock()
                self.esperas: dict[str, tuple[threading.Event, list[tuple[int, int]]]] = {}
                receptor = self

                class Objeto(dbus.service.Object):
                    @dbus.service.method(Receptor.interface, in_signature="sii", out_signature="")
                    def Report(self, token, x, y):  # noqa: N802 - nome do método D-Bus
                        with receptor.lock:
                            espera = receptor.esperas.get(str(token))
                        if espera:
                            evento, dados = espera
                            dados.append((int(x), int(y)))
                            evento.set()

                self.objeto = Objeto(self.bus, self.caminho)
                self.loop = GLib.MainLoop()
                threading.Thread(
                    target=self.loop.run, name="emily-cursor-kwin-dbus", daemon=True,
                ).start()

            def nova_espera(self, token: str):
                evento = threading.Event()
                dados: list[tuple[int, int]] = []
                with self.lock:
                    self.esperas[token] = (evento, dados)
                return evento, dados

            def remover_espera(self, token: str) -> None:
                with self.lock:
                    self.esperas.pop(token, None)

        _RECEPTOR_CURSOR_KWIN = Receptor()
        return _RECEPTOR_CURSOR_KWIN

    def _posicao_cursor_kwin(self) -> tuple[int, int]:
        """Lê a posição lógica global real do cursor diretamente do KWin."""
        if not self.busctl:
            raise ErroBackendDesktop("busctl não encontrado para consultar o cursor do KWin")
        try:
            receptor = self._receptor_cursor_kwin()
        except Exception as exc:  # noqa: BLE001
            raise ErroBackendDesktop(f"não consegui iniciar consulta de cursor do KWin: {exc}") from exc

        token = uuid.uuid4().hex
        nome_script = f"emily_cursor_{token}"
        evento, dados = receptor.nova_espera(token)
        caminho = None
        try:
            codigo = (
                "var p=workspace.cursorPos;"
                f"callDBus('{receptor.nome}','{receptor.caminho}','{receptor.interface}',"
                f"'Report','{token}',Math.round(p.x),Math.round(p.y));"
            )
            with tempfile.NamedTemporaryFile(
                prefix="emily-cursor-", suffix=".js", mode="w", encoding="utf-8", delete=False,
            ) as arq:
                arq.write(codigo)
                caminho = arq.name
            self._rodar((
                self.busctl, "--user", "call", "org.kde.KWin", "/Scripting",
                "org.kde.kwin.Scripting", "loadScript", "ss", caminho, nome_script,
            ))
            self._rodar((
                self.busctl, "--user", "call", "org.kde.KWin", "/Scripting",
                "org.kde.kwin.Scripting", "start",
            ))
            if not evento.wait(1.5) or not dados:
                raise ErroBackendDesktop("KWin não devolveu a posição do cursor")
            return dados[-1]
        finally:
            receptor.remover_espera(token)
            try:
                self._rodar((
                    self.busctl, "--user", "call", "org.kde.KWin", "/Scripting",
                    "org.kde.kwin.Scripting", "unloadScript", "s", nome_script,
                ))
            except ErroBackendDesktop:
                pass
            if caminho:
                try:
                    os.unlink(caminho)
                except OSError:
                    pass

    def ativar_janela(self, nome: str) -> bool:
        """Traz uma janela existente à frente pelo KWin, inclusive em Wayland."""
        termo = (nome or "").strip().casefold()
        if not termo or not self.busctl:
            return False
        if termo in {"navegador", "browser", "navegador padrão", "navegador padrao"}:
            termo = navegador_padrao_linux()[0].casefold()
        termo = {"brave browser": "brave", "brave-browser": "brave",
                 "google chrome": "chrome", "microsoft edge": "edge"}.get(termo, termo)
        if not termo:
            return False
        try:
            receptor = self._receptor_cursor_kwin()
        except Exception:
            return False
        token = uuid.uuid4().hex
        nome_script = f"emily_ativar_{token}"
        evento, dados = receptor.nova_espera(token)
        caminho = None
        try:
            codigo = (
                f"var termo={json.dumps(termo)};"
                "var melhor=null;var pontos=0;var janelas=workspace.stackingOrder;"
                "for(var i=0;i<janelas.length;i++){"
                "var w=janelas[i];if(!w||w.specialWindow||w.deleted)continue;"
                "var ident=((w.desktopFileName||'')+' '+(w.resourceClass||'')+' '+"
                "(w.resourceName||'')).toLowerCase();"
                "var titulo=(w.caption||'').toLowerCase();"
                "var s=ident.indexOf(termo)>=0?100:(titulo.indexOf(termo)>=0?20:0);"
                "if(s>=pontos&&s>0){melhor=w;pontos=s;}"
                "}"
                "if(melhor){if(melhor.minimized)melhor.minimized=false;"
                "workspace.activeWindow=melhor;workspace.raiseWindow(melhor);}"
                f"callDBus('{receptor.nome}','{receptor.caminho}','{receptor.interface}',"
                f"'Report','{token}',melhor&&workspace.activeWindow===melhor?1:0,0);"
            )
            with tempfile.NamedTemporaryFile(
                prefix="emily-ativar-", suffix=".js", mode="w", encoding="utf-8", delete=False,
            ) as arq:
                arq.write(codigo)
                caminho = arq.name
            self._rodar((
                self.busctl, "--user", "call", "org.kde.KWin", "/Scripting",
                "org.kde.kwin.Scripting", "loadScript", "ss", caminho, nome_script,
            ))
            self._rodar((
                self.busctl, "--user", "call", "org.kde.KWin", "/Scripting",
                "org.kde.kwin.Scripting", "start",
            ))
            return bool(evento.wait(1.5) and dados and dados[-1][0])
        except (ErroBackendDesktop, OSError):
            return False
        finally:
            receptor.remover_espera(token)
            try:
                self._rodar((
                    self.busctl, "--user", "call", "org.kde.KWin", "/Scripting",
                    "org.kde.kwin.Scripting", "unloadScript", "s", nome_script,
                ))
            except ErroBackendDesktop:
                pass
            if caminho:
                try:
                    os.unlink(caminho)
                except OSError:
                    pass

    @staticmethod
    def _socket_ydotool() -> str:
        configurado = os.getenv("YDOTOOL_SOCKET", "").strip()
        if configurado:
            return os.path.expanduser(configurado)
        runtime = os.getenv("XDG_RUNTIME_DIR", "").strip()
        if not runtime and hasattr(os, "getuid"):
            runtime = f"/run/user/{os.getuid()}"
        return os.path.join(runtime, ".ydotool_socket") if runtime else "/tmp/.ydotool_socket"

    @classmethod
    def _diagnosticar_entrada(cls, executavel: Optional[str]) -> tuple[bool, str]:
        if not executavel:
            return False, "ydotool não encontrado; instale-o e configure ydotoold/uinput"
        caminho = cls._socket_ydotool()
        try:
            modo = os.stat(caminho).st_mode
        except OSError:
            return False, f"ydotoold não está rodando: socket ausente em {caminho}"
        if not stat.S_ISSOCK(modo):
            return False, f"socket do ydotoold inválido em {caminho}"
        erros = []
        # ydotool 1.x usa SOCK_DGRAM; versões/empacotamentos antigos podem usar
        # stream. Tentar os dois só abre e fecha a conexão: não injeta evento.
        for tipo in (socket.SOCK_DGRAM, socket.SOCK_STREAM):
            teste = socket.socket(socket.AF_UNIX, tipo)
            teste.settimeout(0.25)
            try:
                teste.connect(caminho)
                return True, ""
            except OSError as exc:
                erros.append(str(exc))
            finally:
                teste.close()
        detalhe = erros[-1] if erros else "tipo de socket incompatível"
        return False, f"não consegui conectar ao ydotoold em {caminho}: {detalhe}"

    def capacidades(self) -> CapacidadesDesktop:
        captura = bool(self.spectacle)
        entrada, motivo_entrada = self._diagnosticar_entrada(self.ydotool)
        motivos = []
        if not captura:
            motivos.append("Spectacle não encontrado")
        if not entrada:
            motivos.append(motivo_entrada)
        return CapacidadesDesktop(
            "kde-wayland",
            captura=captura,
            entrada=entrada,
            janelas=bool(self.busctl and importlib.util.find_spec("dbus")),
            motivo_indisponivel="; ".join(motivos),
        )

    def _rodar(self, args: Sequence[str], timeout: float = 12.0) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                list(args), check=True, capture_output=True, text=True, timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            detalhe = getattr(exc, "stderr", "") or str(exc)
            raise ErroBackendDesktop(detalhe.strip()) from exc

    def _exigir_entrada(self) -> str:
        disponivel, motivo = self._diagnosticar_entrada(self.ydotool)
        if not disponivel:
            raise ErroBackendDesktop(f"entrada indisponível no KDE Wayland: {motivo}")
        return self.ydotool

    def _capturar_monitor(self, incluir_ponteiro: bool = False):
        if not self.spectacle:
            raise ErroBackendDesktop("Spectacle não está instalado")
        caminho = None
        try:
            with tempfile.NamedTemporaryFile(prefix="emily-tela-", suffix=".png", delete=False) as arq:
                caminho = arq.name
            # A espera da interface pertence ao executor, não à preferência de
            # atraso do Spectacle. Capturar agora também evita herdar atraso
            # configurado pelo usuário na ferramenta de screenshots.
            argumentos = [self.spectacle, "-b", "-n", "-m", "-d", "0"]
            if incluir_ponteiro:
                argumentos.append("-p")
            argumentos.extend(("-o", caminho))
            self._rodar(argumentos, timeout=20.0)
            from PIL import Image
            with Image.open(caminho) as imagem:
                self._ultima_geometria = self._geometria_saida_ativa()
                return imagem.copy()
        finally:
            if caminho:
                try:
                    os.unlink(caminho)
                except OSError:
                    pass

    def capturar_tela(self) -> str:
        """Captura limpa via Spectacle; o mss devolve preto no KDE Wayland."""
        return _imagem_para_modelo_base64(self._capturar_monitor())

    def capturar_tela_com_grade(self) -> str:
        return _imagem_para_grade_base64(self._capturar_monitor())

    def capturar_tela_para_verificacao(self, x: int, y: int) -> list[str]:
        # O ponteiro real ajuda o modelo a entender o estado de hover; o anel
        # artificial continua sendo a referência inequívoca do ponto exato.
        imagem = self._capturar_monitor(incluir_ponteiro=True)
        imagens, self._ultimo_mapa_zoom = _imagens_para_verificacao_base64(
            imagem, int(x), int(y), self._ultima_geometria, retornar_mapa=True,
        )
        return imagens

    def coordenada_no_zoom(self, zoom_x: float, zoom_y: float) -> tuple[int, int]:
        if self._ultimo_mapa_zoom is None:
            raise ErroBackendDesktop("não há zoom recente para ajustar o clique")
        return _coordenada_no_zoom(self._ultimo_mapa_zoom, zoom_x, zoom_y)

    def geometria(self) -> dict[str, int]:
        return dict(self._ultima_geometria)

    def mover(self, x: int, y: int, duracao: float = 0.0) -> None:
        exe = self._exigir_entrada()
        alvo = (int(x), int(y))
        # ydotool 1.0.4 implementa --absolute voltando primeiro a (0,0) e depois
        # aplicando movimento relativo sujeito à aceleração. No KDE Wayland isso
        # pode deixar o cursor preso no canto. A malha fechada mede a posição real
        # no KWin e corrige o erro relativo até chegar ao alvo. Cada correção usa
        # metade do erro porque o perfil de aceleração desta sessão chega perto de
        # duplicar movimentos grandes; enviar 100% causava oscilação ao redor do alvo.
        atual = self._posicao_cursor_kwin()
        repeticoes_sem_movimento = 0
        for _ in range(16):
            dx, dy = alvo[0] - atual[0], alvo[1] - atual[1]
            if abs(dx) <= self.TOLERANCIA_CURSOR and abs(dy) <= self.TOLERANCIA_CURSOR:
                break
            passo_x = dx if abs(dx) <= 2 else int(math.copysign(max(1, round(abs(dx) * 0.5)), dx))
            passo_y = dy if abs(dy) <= 2 else int(math.copysign(max(1, round(abs(dy) * 0.5)), dy))
            self._rodar((exe, "mousemove", "--", str(passo_x), str(passo_y)))
            time.sleep(0.06)
            nova_posicao = self._posicao_cursor_kwin()
            if nova_posicao == atual:
                repeticoes_sem_movimento += 1
                if repeticoes_sem_movimento >= 4:
                    break
            else:
                repeticoes_sem_movimento = 0
            atual = nova_posicao
        if (abs(alvo[0] - atual[0]) > self.TOLERANCIA_CURSOR
                or abs(alvo[1] - atual[1]) > self.TOLERANCIA_CURSOR):
            raise ErroBackendDesktop(
                f"cursor não alcançou o alvo {alvo}; posição final {atual}; "
                f"tolerância {self.TOLERANCIA_CURSOR}px. Clique cancelado"
            )
        if duracao > 0:
            time.sleep(min(float(duracao), 0.5))

    def clicar(self, x: int, y: int, botao: str = "left", cliques: int = 1) -> None:
        exe = self._exigir_entrada()
        self.mover(x, y)
        codigo = {"left": "0xC0", "right": "0xC1", "middle": "0xC2"}.get(botao, "0xC0")
        for _ in range(max(1, int(cliques))):
            self._rodar((exe, "click", codigo))

    def digitar(self, texto: str, intervalo: float = 0.0) -> None:
        self._exigir_entrada()
        texto = str(texto)
        if not texto:
            return
        # ydotool type usa mapa US e pode exceder o timeout, deixando teclas
        # pressionadas. Colar independe do layout e não simula milhares de teclas.
        copiar = shutil.which("wl-copy")
        if not copiar:
            raise ErroBackendDesktop("wl-copy não encontrado; instale wl-clipboard para digitar com segurança")
        with _TRAVA_TEXTO:
            try:
                colar = shutil.which("wl-paste")
                anterior = None
                if colar:
                    tipos = subprocess.run([colar, "--list-types"], capture_output=True,
                                           text=True, timeout=2).stdout.splitlines()
                    tipo = next((t for t in ("text/plain;charset=utf-8", "text/plain", "image/png") if t in tipos), None)
                    if tipo:
                        leitura = subprocess.run([colar, "--no-newline", "--type", tipo],
                                                 capture_output=True, timeout=2)
                        if leitura.returncode == 0:
                            anterior = (tipo, leitura.stdout)
                subprocess.run([copiar, "--type", "text/plain;charset=utf-8"],
                               input=texto, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=5)
            except (OSError, subprocess.SubprocessError) as exc:
                raise ErroBackendDesktop("não consegui preparar o texto para colar") from exc
            # Shift+Insert é colagem em editores, navegadores e terminais;
            # Ctrl+V no terminal representaria uma entrada literal.
            try:
                self.atalho(("shift", "insert"))
                time.sleep(0.5)
            finally:
                # Não sobrescrever uma cópia que o usuário fez durante a ação.
                if anterior and colar:
                    try:
                        atual = subprocess.run([colar, "--no-newline"], capture_output=True, timeout=2)
                        if atual.returncode == 0 and atual.stdout == texto.encode("utf-8"):
                            subprocess.run([copiar, "--type", anterior[0]], input=anterior[1],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=5)
                    except (OSError, subprocess.SubprocessError):
                        # A colagem já ocorreu. Não reportar como digitação
                        # falha: o agente poderia repetir todo o texto.
                        pass

    def _codigo(self, tecla: str) -> int:
        chave = str(tecla).strip().lower()
        if chave not in self._CODIGOS_TECLA:
            raise ErroBackendDesktop(f"tecla não mapeada para ydotool: {tecla}")
        return self._CODIGOS_TECLA[chave]

    def pressionar(self, tecla: str, vezes: int = 1) -> None:
        exe = self._exigir_entrada()
        codigo = self._codigo(tecla)
        argumentos = [exe, "key"]
        for _ in range(max(1, int(vezes))):
            argumentos.extend((f"{codigo}:1", f"{codigo}:0"))
        self._rodar(argumentos)

    def atalho(self, teclas: Sequence[str]) -> None:
        exe = self._exigir_entrada()
        codigos = [self._codigo(t) for t in teclas]
        argumentos = [exe, "key"]
        argumentos.extend(f"{c}:1" for c in codigos)
        argumentos.extend(f"{c}:0" for c in reversed(codigos))
        try:
            self._rodar(argumentos)
        finally:
            self._rodar([exe, "key", *(f"{c}:0" for c in reversed(codigos))])

    def rolar(self, quantidade: int) -> None:
        exe = self._exigir_entrada()
        # ydotool 1.x exige os dois eixos da roda: horizontal e vertical.
        # O sinal vertical segue o pyautogui (positivo = cima).
        self._rodar((exe, "mousemove", "--wheel", "--", "0", str(int(quantidade))))


class BackendDesktopFalso(BackendDesktop):
    """Backend determinístico para testes; nunca acessa display nem subprocesso."""

    def __init__(
        self,
        capturas: Optional[Sequence[str]] = None,
        geometria: Optional[dict[str, int]] = None,
        disponivel: bool = True,
    ) -> None:
        self.capturas = list(capturas or ["imagem-falsa"])
        self._geometria = dict(geometria or {"left": 0, "top": 0, "width": 1280, "height": 720})
        self.disponivel = disponivel
        self.acoes: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._indice_captura = 0

    def capacidades(self) -> CapacidadesDesktop:
        motivo = "" if self.disponivel else "backend falso marcado como indisponível"
        return CapacidadesDesktop("falso", self.disponivel, self.disponivel, True, motivo)

    def _registrar(self, nome: str, *args: Any, **kwargs: Any) -> None:
        if not self.disponivel:
            raise ErroBackendDesktop("backend falso indisponível")
        self.acoes.append((nome, args, kwargs))

    def capturar_tela(self) -> str:
        self._registrar("capturar")
        if not self.capturas:
            raise ErroBackendDesktop("nenhuma captura falsa configurada")
        indice = min(self._indice_captura, len(self.capturas) - 1)
        self._indice_captura += 1
        return self.capturas[indice]

    def capturar_tela_com_grade(self) -> str:
        return self.capturar_tela()

    def geometria(self) -> dict[str, int]:
        return dict(self._geometria)

    def capturar_tela_para_verificacao(self, x: int, y: int) -> list[str]:
        self._registrar("capturar_verificacao", int(x), int(y))
        return ["verificacao-geral-falsa", "verificacao-zoom-falso"]

    def mover(self, x: int, y: int, duracao: float = 0.0) -> None:
        self._registrar("mover", int(x), int(y), duracao=float(duracao))

    def clicar(self, x: int, y: int, botao: str = "left", cliques: int = 1) -> None:
        self._registrar("clicar", int(x), int(y), botao=botao, cliques=int(cliques))

    def digitar(self, texto: str, intervalo: float = 0.0) -> None:
        self._registrar("digitar", str(texto), intervalo=float(intervalo))

    def pressionar(self, tecla: str, vezes: int = 1) -> None:
        self._registrar("pressionar", str(tecla), vezes=int(vezes))

    def atalho(self, teclas: Sequence[str]) -> None:
        self._registrar("atalho", tuple(teclas))

    def rolar(self, quantidade: int) -> None:
        self._registrar("rolar", int(quantidade))

    def ativar_janela(self, nome: str) -> bool:
        self._registrar("ativar_janela", nome)
        return True

    def abrir_app(self, nome: str) -> bool:
        self._registrar("abrir_app", nome)
        return True

    def esperar(self, segundos: float, cancelar: Optional[threading.Event] = None) -> bool:
        self._registrar("esperar", float(segundos))
        return not (cancelar is not None and cancelar.is_set())


def _abrir_app_portatil(nome: str) -> bool:
    nome = (nome or "").strip()
    if not nome:
        return False
    sistema = platform.system().lower()
    if sistema == "linux":
        return _abrir_app_linux(nome)
    mapa = {
        "chrome": "google-chrome", "brave": "brave-browser", "edge": "microsoft-edge",
        "firefox": "firefox", "vscode": "code", "visual studio code": "code",
        "code": "code", "steam": "steam", "discord": "discord", "spotify": "spotify",
        "arquivos": "dolphin" if sistema == "linux" else "explorer",
        "explorer": "dolphin" if sistema == "linux" else "explorer",
        "calculadora": "kcalc" if sistema == "linux" else "calc",
        "bloco de notas": "kate" if sistema == "linux" else "notepad",
    }
    chave = nome.lower()
    executavel = next((v for k, v in mapa.items() if k == chave or k in chave or chave in k), nome)
    try:
        if sistema == "windows":
            subprocess.Popen(["cmd", "/c", "start", "", executavel], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen([executavel], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        return True
    except OSError:
        return False


def navegador_padrao_linux() -> tuple[str, str]:
    """Nome e identificador .desktop do navegador configurado pelo usuário."""
    if platform.system().lower() != "linux" or not shutil.which("xdg-settings"):
        return "", ""
    try:
        resultado = subprocess.run(
            ["xdg-settings", "get", "default-web-browser"],
            capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", ""
    desktop_id = (resultado.stdout or "").strip() if resultado.returncode == 0 else ""
    if not desktop_id.endswith(".desktop"):
        return "", ""
    chave = desktop_id.casefold()
    nome = next((rotulo for trecho, rotulo in (
        ("brave", "Brave"), ("firefox", "Firefox"), ("chrome", "Chrome"),
        ("chromium", "Chromium"), ("edge", "Edge"),
    ) if trecho in chave), desktop_id.removesuffix(".desktop"))
    return nome, desktop_id


def descrever_ambiente_desktop() -> str:
    sistema = platform.system()
    if sistema.lower() != "linux":
        return f"Sistema: {sistema}."
    sessao = os.getenv("XDG_SESSION_TYPE", "desconhecida")
    desktop = os.getenv("XDG_CURRENT_DESKTOP", "desconhecido")
    navegador, desktop_id = navegador_padrao_linux()
    padrao = (f"Navegador padrão: {navegador} ({desktop_id}). "
              if desktop_id else "Navegador padrão não identificado. ")
    return (
        f"Sistema: Linux, ambiente {desktop}, sessão {sessao}. {padrao}"
        "Use o navegador padrão para sites; não presuma que Chrome ou Edge estão instalados."
    )


def _flatpak_instalado(app_id: str) -> bool:
    if not shutil.which("flatpak"):
        return False
    try:
        return subprocess.run(
            ["flatpak", "info", app_id], capture_output=True,
            timeout=2, check=False,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _iniciar_app(argv: Sequence[str]) -> bool:
    try:
        processo = subprocess.Popen(
            list(argv), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            # Launchers (.desktop/Flatpak) podem encerrar logo após entregar
            # a janela. Processos GUI que seguem rodando também são sucesso.
            return processo.wait(timeout=1.5) == 0
        except subprocess.TimeoutExpired:
            return True
    except OSError:
        return False


def _abrir_app_linux(nome: str) -> bool:
    chave = nome.strip().casefold()
    aliases = {
        "brave": ("brave-browser", "brave", "com.brave.Browser"),
        "brave browser": ("brave-browser", "brave", "com.brave.Browser"),
        "brave-browser": ("brave-browser", "brave", "com.brave.Browser"),
        "chrome": ("google-chrome", "google-chrome-stable", "com.google.Chrome"),
        "google chrome": ("google-chrome", "google-chrome-stable", "com.google.Chrome"),
        "firefox": ("firefox", "firefox", "org.mozilla.firefox"),
        "edge": ("microsoft-edge", "microsoft-edge", "com.microsoft.Edge"),
        "vscode": ("code", "code", "com.visualstudio.code"),
        "visual studio code": ("code", "code", "com.visualstudio.code"),
        "arquivos": ("dolphin", "dolphin", "org.kde.dolphin"),
        "explorer": ("dolphin", "dolphin", "org.kde.dolphin"),
        "calculadora": ("kcalc", "kcalc", "org.kde.kcalc"),
        "calc": ("kcalc", "kcalc", "org.kde.kcalc"),
        "bloco de notas": ("kate", "kate", "org.kde.kate"),
        "notepad": ("kate", "kate", "org.kde.kate"),
        "terminal": ("konsole", "xterm", "org.kde.konsole"),
    }
    navegador, desktop_id = navegador_padrao_linux()
    if chave in {"navegador", "browser", "navegador padrão", "navegador padrao"}:
        if not desktop_id:
            return False
        chave = navegador.casefold()
        if chave not in aliases:
            app_id = desktop_id.removesuffix(".desktop")
            if _flatpak_instalado(app_id) and _iniciar_app(("flatpak", "run", app_id)):
                return True
            return bool(shutil.which("gtk-launch") and _iniciar_app(("gtk-launch", app_id)))
    principal, alternativo, app_id = aliases.get(chave, (nome, nome, ""))
    for executavel in dict.fromkeys((principal, alternativo)):
        if shutil.which(executavel) and _iniciar_app((executavel,)):
            return True
    if app_id and _flatpak_instalado(app_id):
        return _iniciar_app(("flatpak", "run", app_id))
    # Um .desktop padrão pode ser exportado por outro empacotamento.
    if desktop_id and chave == navegador.casefold() and shutil.which("gtk-launch"):
        return _iniciar_app(("gtk-launch", desktop_id.removesuffix(".desktop")))
    if shutil.which("gtk-launch") and len(chave) >= 3:
        pastas = [Path.home() / ".local/share/applications"]
        pastas.extend(Path(base) / "applications" for base in
                      os.getenv("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if base)
        for pasta in pastas:
            if not pasta.is_dir():
                continue
            for arquivo in pasta.glob("*.desktop"):
                if chave == arquivo.stem.casefold() and _iniciar_app(("gtk-launch", arquivo.stem)):
                    return True
                try:
                    nome_exibido = next((linha[5:].strip().casefold()
                                           for linha in arquivo.read_text(encoding="utf-8").splitlines()
                                           if linha.startswith("Name=")), "")
                except (OSError, UnicodeError):
                    continue
                if chave == nome_exibido and _iniciar_app(("gtk-launch", arquivo.stem)):
                    return True
    return False


def selecionar_backend_desktop() -> BackendDesktop:
    """Escolhe o backend sem inicializar biblioteca gráfica alguma."""
    sistema = platform.system().lower()
    sessao = os.getenv("XDG_SESSION_TYPE", "").strip().lower()
    desktop = os.getenv("XDG_CURRENT_DESKTOP", "").strip().lower()
    if sistema == "linux" and sessao == "wayland" and "kde" in desktop:
        return BackendKDEWayland()
    return BackendPyAutoGUI()


__all__ = [
    "BackendDesktop", "BackendDesktopFalso", "BackendKDEWayland", "BackendPyAutoGUI",
    "CapacidadesDesktop", "ErroBackendDesktop", "descrever_ambiente_desktop",
    "navegador_padrao_linux", "selecionar_backend_desktop",
]

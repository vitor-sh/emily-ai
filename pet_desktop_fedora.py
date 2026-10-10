"""Pet animado da Emily para o desktop Fedora (processo GTK separado).

Protocolo de stdin: ``state NOME``, ``size PERCENTUAL`` ou ``quit``.
Clique esquerdo arrasta; clique direito mostra/esconde o chat.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path


BASE = Path(__file__).resolve().parent / "assets" / "desktop_pet_v2"
ESTADOS = {"idle", "listening", "thinking", "working", "speaking",
           "idle_playful", "idle_stretch", "idle_sit", "idle_ram", "idle_star"}
IDLES_OCASIONAIS = {"idle_playful", "idle_stretch", "idle_sit", "idle_ram",
                   "idle_star"}
TAMANHO_MIN = 50
TAMANHO_MAX = 130


def tamanho_valido(valor: object) -> int:
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        numero = 100
    return max(TAMANHO_MIN, min(TAMANHO_MAX, numero))


def validar_assets(base: Path = BASE) -> dict:
    dados = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(dados.get("states"), dict) or not ESTADOS.issubset(dados["states"]):
        raise ValueError("estados do pet incompletos")
    for estado in ESTADOS:
        item = dados["states"][estado]
        if not 2 <= len(item.get("frames", [])) <= 12:
            raise ValueError(f"quadros inválidos: {estado}")
        miolo = item.get("loop_segment")
        if miolo is not None and (not isinstance(miolo, list)
                                  or len(miolo) != 3
                                  or any(not isinstance(n, int) for n in miolo)
                                  or not (0 <= miolo[0] < miolo[1] < len(item["frames"]) - 1)
                                  or not (1 <= miolo[2] <= 4)):
            raise ValueError(f"repetição inválida: {estado}")
        for relativo in item["frames"]:
            caminho = (base / relativo).resolve()
            if not caminho.is_relative_to(base.resolve()) or not caminho.is_file():
                raise ValueError(f"quadro ausente: {estado}/{relativo}")
    return dados


def executar() -> None:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

    dados = validar_assets()
    argumento_tamanho = (sys.argv[sys.argv.index("--size") + 1]
                         if "--size" in sys.argv and sys.argv.index("--size") + 1 < len(sys.argv)
                         else 100)
    tamanho_inicial = tamanho_valido(argumento_tamanho)

    class Pet:
        def __init__(self):
            self.win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
            self.win.set_title("Emily · pet")
            self.win.set_decorated(False)
            self.win.set_resizable(False)
            self.win.set_app_paintable(True)
            self.win.get_style_context().add_class("emily-pet")
            estilo = Gtk.CssProvider()
            estilo.load_from_data(b"""
                window.emily-pet, window.emily-pet.background,
                window.emily-pet decoration {
                    background-color: transparent;
                    background-image: none;
                    border: 0;
                    outline: 0;
                    box-shadow: none;
                    margin: 0;
                    padding: 0;
                }
            """)
            Gtk.StyleContext.add_provider_for_screen(
                self.win.get_screen(), estilo, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.win.set_keep_above(True)
            self.win.set_skip_taskbar_hint(True)
            self.win.set_skip_pager_hint(True)
            self.win.set_accept_focus(False)
            self.win.set_focus_on_map(False)
            self.tamanho = tamanho_inicial
            largura = round(dados["width"] * self.tamanho / 100)
            altura = round(dados["height"] * self.tamanho / 100)
            self.win.set_size_request(largura, altura)
            self.win.set_default_size(largura, altura)
            visual = self.win.get_screen().get_rgba_visual()
            if visual is None:
                raise RuntimeError("o compositor não ofereceu janela RGBA transparente")
            self.win.set_visual(visual)
            self.win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            self.win.connect("draw", self._desenhar)
            self.win.connect("button-press-event", self._clique)
            self.win.connect("destroy", Gtk.main_quit)
            self.quadros_base = {}
            for estado, item in dados["states"].items():
                self.quadros_base[estado] = [GdkPixbuf.Pixbuf.new_from_file(str(BASE / p))
                                             for p in item["frames"]]
            self.quadros = self._quadros_escalados(self.tamanho)
            self.estado = "idle"
            self.indice = 0
            self.quadro_anterior = None
            self.transicao_inicio = 0.0
            self.ultimo_quadro = time.monotonic()
            self.proximo_idle = time.monotonic() + random.uniform(16, 30)
            self.ultimo_idle_ocasional = None
            self.repeticoes_miolo = 0
            self.entrada = bytearray()
            self.win.show_all()
            self._aplicar_forma_cliques()
            # Wayland pode ignorar posição programática; o arraste com botão
            # esquerdo permanece disponível nesse caso.
            try:
                monitor = self.win.get_display().get_primary_monitor()
                if monitor:
                    area = monitor.get_geometry()
                    self.win.move(area.x + area.width - largura - 28,
                                  area.y + area.height - altura - 82)
            except Exception:
                pass
            GLib.timeout_add(40, self._tick)
            GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                              self._comando)

        def _quadros_escalados(self, tamanho):
            if tamanho == 100:
                return self.quadros_base
            largura = round(dados["width"] * tamanho / 100)
            altura = round(dados["height"] * tamanho / 100)
            return {estado: [quadro.scale_simple(largura, altura,
                                                 GdkPixbuf.InterpType.BILINEAR)
                             for quadro in quadros]
                    for estado, quadros in self.quadros_base.items()}

        def _definir_tamanho(self, tamanho):
            novo = tamanho_valido(tamanho)
            if novo == self.tamanho:
                return
            self.tamanho = novo
            self.quadros = self._quadros_escalados(novo)
            self.quadro_anterior = None
            largura = round(dados["width"] * novo / 100)
            altura = round(dados["height"] * novo / 100)
            self.win.set_size_request(largura, altura)
            self.win.resize(largura, altura)
            self._aplicar_forma_cliques()
            self.win.queue_draw()

        def _aplicar_forma_cliques(self):
            """Deixa passar cliques nos pixels transparentes da janela."""
            import cairo

            largura = round(dados["width"] * self.tamanho / 100)
            altura = round(dados["height"] * self.tamanho / 100)
            ocupados = bytearray(largura * altura)
            for quadros in self.quadros.values():
                for quadro in quadros:
                    pixels = quadro.get_pixels()
                    passo = quadro.get_n_channels()
                    if not quadro.get_has_alpha():
                        continue
                    stride = quadro.get_rowstride()
                    for y in range(altura):
                        base = y * stride + passo - 1
                        destino = y * largura
                        for x in range(largura):
                            if pixels[base + x * passo] > 24:
                                ocupados[destino + x] = 1
            regiao = cairo.Region()
            for y in range(altura):
                linha = y * largura
                inicio = None
                for x in range(largura + 1):
                    visivel = x < largura and ocupados[linha + x]
                    if visivel and inicio is None:
                        inicio = x
                    elif not visivel and inicio is not None:
                        regiao.union(cairo.RectangleInt(
                            max(0, inicio - 2), y, min(largura, x + 2) - max(0, inicio - 2), 1))
                        inicio = None
            janela = self.win.get_window()
            if janela is not None:
                janela.input_shape_combine_region(regiao, 0, 0)

        def _desenhar(self, _widget, cr):
            import cairo
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            progresso = min(1.0, (time.monotonic() - self.transicao_inicio) / .18)
            if self.quadro_anterior is not None and progresso < 1:
                Gdk.cairo_set_source_pixbuf(cr, self.quadro_anterior, 0, 0)
                cr.paint_with_alpha(1 - progresso)
            pixbuf = self.quadros[self.estado][self.indice]
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
            cr.paint_with_alpha(progresso if self.quadro_anterior is not None else 1)
            return False

        def _clique(self, _widget, evento):
            if evento.button == 1:
                self.win.begin_move_drag(evento.button, int(evento.x_root),
                                         int(evento.y_root), evento.time)
                return True
            if evento.button == 3:
                print("toggle", flush=True)
                return True
            return False

        def _mudar(self, estado):
            if estado not in ESTADOS or estado == self.estado:
                return
            self.quadro_anterior = self.quadros[self.estado][self.indice]
            self.transicao_inicio = time.monotonic()
            self.estado = estado
            self.indice = 0
            self.repeticoes_miolo = 0
            if estado in IDLES_OCASIONAIS:
                self.ultimo_idle_ocasional = estado
            self.ultimo_quadro = time.monotonic()
            if estado == "idle":
                self.proximo_idle = time.monotonic() + random.uniform(16, 30)
            self.win.queue_draw()

        def _tick(self):
            agora = time.monotonic()
            if self.quadro_anterior is not None:
                if agora - self.transicao_inicio >= .18:
                    self.quadro_anterior = None
                self.win.queue_draw()
            if self.estado == "idle" and agora >= self.proximo_idle:
                opcoes = sorted(IDLES_OCASIONAIS - {self.ultimo_idle_ocasional})
                self._mudar(random.choice(opcoes))
            duracao = dados["states"][self.estado]["duration_ms"] / 1000
            if agora - self.ultimo_quadro >= duracao:
                self.ultimo_quadro = agora
                proximo = self.indice + 1
                miolo = dados["states"][self.estado].get("loop_segment")
                if (miolo and self.indice == miolo[1]
                        and self.repeticoes_miolo < miolo[2]):
                    self.repeticoes_miolo += 1
                    proximo = miolo[0]
                if self.estado in IDLES_OCASIONAIS and proximo >= len(self.quadros[self.estado]):
                    self._mudar("idle")
                else:
                    self.indice = proximo % len(self.quadros[self.estado])
                    self.win.queue_draw()
            return True

        def _comando(self, _fonte, condicao):
            if condicao & GLib.IO_ERR:
                Gtk.main_quit()
                return False
            # Ler direto do fd: TextIO.readline pode absorver várias linhas
            # no próprio buffer e o watch GLib não avisa sobre a segunda.
            bloco = os.read(sys.stdin.fileno(), 4096)
            if not bloco:
                Gtk.main_quit()
                return False
            self.entrada.extend(bloco)
            while b"\n" in self.entrada:
                linha, _, restante = self.entrada.partition(b"\n")
                self.entrada = bytearray(restante)
                partes = linha.decode("utf-8", "replace").strip().split(None, 1)
                if partes and partes[0] == "quit":
                    Gtk.main_quit()
                    return False
                if len(partes) == 2 and partes[0] == "state":
                    self._mudar(partes[1])
                if len(partes) == 2 and partes[0] == "size":
                    self._definir_tamanho(partes[1])
            if len(self.entrada) > 1024 or condicao & GLib.IO_HUP:
                Gtk.main_quit()
                return False
            return True

    Pet()
    def pronto():
        print("ready", flush=True)
        return False
    GLib.idle_add(pronto)
    Gtk.main()


if __name__ == "__main__":
    if "--check" in sys.argv:
        dados = validar_assets()
        print({k: len(v["frames"]) for k, v in dados["states"].items()})
    else:
        executar()

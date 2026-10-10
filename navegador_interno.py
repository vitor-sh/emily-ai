"""Navegador isolado da Emily, controlado por uma única thread Playwright.

O Chromium renderiza numa janela virtual. A interface mostra capturas do
viewport e encaminha apenas eventos recebidos dentro desse viewport; nenhuma
ação usa o ponteiro ou teclado do desktop.
"""

from __future__ import annotations

import base64
import os
import queue
import re
import sys
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from urllib.parse import quote, urlparse

from emily_paths import pasta_dados

LARGURA = 1280
ALTURA = 800
_fila: queue.Queue = queue.Queue()
_thread: threading.Thread | None = None
_lock = threading.Lock()
_condicao = threading.Condition(_lock)
_encerrando = False
_usuario_ativo = False
_revisao_usuario = 0


def definir_usuario_ativo(ativo: bool) -> dict:
    """Pausa os comandos da Emily enquanto o usuário controla o viewport."""
    global _usuario_ativo
    with _condicao:
        _usuario_ativo = bool(ativo)
        _condicao.notify_all()
    return {"ok": True, "usuario_ativo": _usuario_ativo}


def _localizar_texto_visivel(pagina, texto: str):
    """Resolve texto composto (ex.: 'SEX\n02/10') a um alvo visível.

    Muitos sites desenham dia e data em spans separados. get_by_text com a
    frase inteira fica aguardando um nó que não existe; o fragmento final
    específico costuma ser o alvo correto e o click borbulha ao cartão.
    """
    partes = [p.strip() for p in re.split(r"[\r\n]+", texto or "") if p.strip()]
    tentativas = list(dict.fromkeys([texto.strip(), *reversed(partes)]))
    fim = time.monotonic() + 8
    while True:
        for termo in tentativas:
            for exato in (True, False):
                localizador = pagina.get_by_text(termo, exact=exato)
                for indice in range(min(localizador.count(), 12)):
                    alvo = localizador.nth(indice)
                    if alvo.is_visible():
                        return alvo
        if time.monotonic() >= fim:
            break
        pagina.wait_for_timeout(250)
    raise ValueError(f"Não achei texto visível para clicar: {texto[:100]}")


def _alvo_do_ponto(pagina, x: float, y: float) -> dict:
    return pagina.evaluate("""([x,y]) => {
      const e = document.elementFromPoint(x,y);
      const a = e?.closest('a,button,[role="button"],[role="link"],input,label,[onclick],.cursor-pointer') || e;
      return {tag: a?.tagName?.toLowerCase() || '',
              texto: (a?.innerText || a?.getAttribute?.('aria-label') || '').trim().slice(0,120),
              html: (a?.outerHTML || '').slice(0,600),
              corpo: (document.body?.innerText || '').slice(0,14000)};
    }""", [x, y])


def _url_http(valor: str) -> str:
    url = (valor or "").strip()
    if not url:
        return "about:blank"
    if "://" not in url:
        if "." not in url or " " in url:
            # Google e Brave exibiram CAPTCHA ao Chromium isolado neste Fedora;
            # Bing carregou resultados normais no teste real.
            return "https://www.bing.com/search?q=" + quote(url)
        url = "https://" + url
    partes = urlparse(url)
    if partes.scheme not in {"http", "https"} or not partes.hostname:
        raise ValueError("Use um endereço HTTP/HTTPS ou termos para buscar.")
    return url


def _trabalhar() -> None:
    contexto = None
    pagina = None
    erro_inicio = None
    ultimo_download = ""
    downloads_pendentes = []
    try:
        empacotado = Path(getattr(sys, "_MEIPASS", "")) / "playwright-browsers"
        if empacotado.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(empacotado)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            # Cookies não podem morar no diretório do build/override no Fedora.
            base = Path(pasta_dados()) if os.name == "nt" else Path.home() / ".local/share/emily"
            perfil = base / "navegador-interno"
            perfil.mkdir(parents=True, mode=0o700, exist_ok=True)
            contexto = playwright.chromium.launch_persistent_context(
                str(perfil), headless=True, viewport={"width": LARGURA, "height": ALTURA},
                locale="pt-BR", accept_downloads=True,
            )
            contexto.set_default_timeout(8000)
            def salvar_download(download):
                # O callback roda dentro do dispatcher do Playwright. Chamar
                # save_as() aqui reentra no mesmo loop e pode travar/cancelar
                # o download. Guardamos o objeto e salvamos após a ação.
                downloads_pendentes.append(download)

            def processar_downloads():
                nonlocal ultimo_download
                while downloads_pendentes:
                    download = downloads_pendentes.pop(0)
                    try:
                        pasta = Path.home() / "Downloads"
                        pasta.mkdir(parents=True, exist_ok=True)
                        nome = Path(download.suggested_filename).name or "download"
                        destino = pasta / nome
                        numero = 2
                        while destino.exists():
                            destino = pasta / f"{Path(nome).stem} ({numero}){Path(nome).suffix}"
                            numero += 1
                        download.save_as(str(destino))
                        ultimo_download = str(destino)
                    except Exception as exc:
                        ultimo_download = "Falha ao salvar download: " + str(exc)[:200]

            def conectar_pagina(nova):
                nova.on("download", salvar_download)

            contexto.on("page", conectar_pagina)
            for aberta in contexto.pages:
                conectar_pagina(aberta)
            pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
            pagina.set_default_timeout(8000)
            largura_viewport, altura_viewport = LARGURA, ALTURA
            cursor_emily = None
            sequencia_clique = 0
            def resumo_aba(indice, aba):
                try:
                    titulo = (aba.title() or "Nova aba")[:90]
                except Exception:
                    titulo = "Carregando…"
                return {"indice": indice, "url": aba.url, "titulo": titulo,
                        "ativa": aba is pagina}

            while True:
                operacao, parametros, futuro, origem = _fila.get()
                if futuro.cancelled():
                    continue
                try:
                    quantidade_antes = len([p for p in contexto.pages if not p.is_closed()])
                    if operacao == "fechar":
                        if not futuro.done():
                            futuro.set_result({"ok": True})
                        break
                    if operacao == "nova_aba":
                        pagina = contexto.new_page()
                        pagina.set_viewport_size({"width": largura_viewport, "height": altura_viewport})
                    elif operacao == "trocar_aba":
                        indice = int(parametros[0])
                        abertas = [p for p in contexto.pages if not p.is_closed()]
                        if not 0 <= indice < len(abertas):
                            raise ValueError("Aba não encontrada.")
                        pagina = abertas[indice]
                        pagina.set_viewport_size({"width": largura_viewport, "height": altura_viewport})
                    elif operacao == "fechar_aba":
                        indice = int(parametros[0])
                        abertas = [p for p in contexto.pages if not p.is_closed()]
                        if not 0 <= indice < len(abertas):
                            raise ValueError("Aba não encontrada.")
                        fechada = abertas[indice]
                        fechada.close()
                        abertas = [p for p in contexto.pages if not p.is_closed()]
                        pagina = abertas[min(indice, len(abertas) - 1)] if abertas else contexto.new_page()
                        pagina.set_viewport_size({"width": largura_viewport, "height": altura_viewport})
                    elif operacao == "dimensionar":
                        largura_viewport = max(320, min(1600, int(parametros[0])))
                        altura_viewport = max(250, min(1200, int(parametros[1])))
                        pagina.set_viewport_size({"width": largura_viewport, "height": altura_viewport})
                    elif operacao == "abrir":
                        pagina.goto(_url_http(parametros[0]), wait_until="domcontentloaded", timeout=20000)
                    elif operacao == "voltar":
                        pagina.go_back(wait_until="domcontentloaded", timeout=15000)
                    elif operacao == "avancar":
                        pagina.go_forward(wait_until="domcontentloaded", timeout=15000)
                    elif operacao == "recarregar":
                        pagina.reload(wait_until="domcontentloaded", timeout=15000)
                    elif operacao == "aguardar":
                        pagina.wait_for_timeout(max(500, min(5000, int(float(parametros[0]) * 1000))))
                    elif operacao == "mover":
                        x, y = float(parametros[0]), float(parametros[1])
                        pagina.mouse.move(x, y)
                        if origem == "agente":
                            cursor_emily = {"x": x, "y": y}
                    elif operacao == "clicar":
                        x, y, botao = parametros
                        x, y = float(x), float(y)
                        if not 0 <= x < largura_viewport or not 0 <= y < altura_viewport:
                            raise ValueError("Clique fora da área atual; veja a página novamente.")
                        url_antes = pagina.url
                        alvo_antes = _alvo_do_ponto(pagina, x, y)
                        nova_aba = pagina.evaluate(
                            "([x,y]) => document.elementFromPoint(x,y)?.closest('a')?.target === '_blank'",
                            [x, y],
                        ) if botao == "left" else False
                        if origem == "agente":
                            cursor_emily = {"x": x, "y": y}
                            sequencia_clique += 1
                        if nova_aba:
                            with pagina.expect_popup(timeout=8000) as popup:
                                pagina.mouse.click(x, y, button=botao)
                            pagina = popup.value
                        else:
                            pagina.mouse.click(x, y, button=botao)
                    elif operacao == "pressionar":
                        x, y, botao = parametros
                        pagina.mouse.move(float(x), float(y))
                        pagina.mouse.down(button=botao)
                    elif operacao == "soltar":
                        x, y, botao = parametros
                        pagina.mouse.move(float(x), float(y))
                        nova_aba = pagina.evaluate(
                            "([x,y]) => document.elementFromPoint(x,y)?.closest('a')?.target === '_blank'",
                            [float(x), float(y)],
                        ) if botao == "left" else False
                        if nova_aba:
                            with pagina.expect_popup(timeout=8000) as popup:
                                pagina.mouse.up(button=botao)
                            pagina = popup.value
                        else:
                            pagina.mouse.up(button=botao)
                    elif operacao == "rolar":
                        pagina.mouse.wheel(float(parametros[0]), float(parametros[1]))
                    elif operacao == "tecla":
                        pagina.keyboard.press(parametros[0])
                    elif operacao == "texto":
                        pagina.keyboard.insert_text(parametros[0])
                    elif operacao == "clicar_texto":
                        alvo = _localizar_texto_visivel(pagina, str(parametros[0]))
                        alvo.scroll_into_view_if_needed(timeout=8000)
                        url_antes = pagina.url
                        corpo_antes = pagina.evaluate("() => (document.body?.innerText || '').slice(0,14000)")
                        assinatura_antes = alvo.evaluate(
                            "e => (e.closest('a,button,[role=button],.cursor-pointer') || e).outerHTML.slice(0,1200)")
                        caixa = alvo.bounding_box()
                        if caixa and origem == "agente":
                            x = caixa["x"] + caixa["width"] / 2
                            y = caixa["y"] + caixa["height"] / 2
                            pagina.mouse.move(x, y)
                            cursor_emily = {"x": x, "y": y}
                            sequencia_clique += 1
                        nova_aba = alvo.evaluate("e => e.closest('a')?.target === '_blank'")
                        if nova_aba:
                            with pagina.expect_popup(timeout=8000) as popup:
                                alvo.click(timeout=8000)
                            pagina = popup.value
                        else:
                            alvo.click(timeout=8000)
                    elif operacao == "preencher":
                        seletor, valor = parametros
                        pagina.locator(seletor).first.fill(valor, timeout=8000)
                    elif operacao in {"estado", "ler", "abas"}:
                        pass
                    else:
                        raise ValueError("Ação desconhecida no navegador interno.")
                    processar_downloads()
                    if operacao in {"clicar", "soltar", "clicar_texto"}:
                        # Sites com SPA, redirects e target=_blank trocam a
                        # página um pouco depois do evento de clique.
                        pagina.wait_for_timeout(350)
                        processar_downloads()
                    # Um link target=_blank abre uma página no mesmo contexto.
                    abertas = [p for p in contexto.pages if not p.is_closed()]
                    if abertas and pagina not in abertas:
                        pagina = abertas[-1]
                    elif (len(abertas) > quantidade_antes
                          and operacao not in {"nova_aba", "trocar_aba", "fechar_aba"}):
                        pagina = abertas[-1]
                    if pagina.viewport_size != {"width": largura_viewport, "height": altura_viewport}:
                        pagina.set_viewport_size({"width": largura_viewport, "height": altura_viewport})
                    resultado = {"ok": True, "url": pagina.url, "titulo": pagina.title(),
                                 "ultimo_download": ultimo_download,
                                 "largura": largura_viewport, "altura": altura_viewport}
                    if operacao == "clicar":
                        alvo_depois = _alvo_do_ponto(pagina, x, y)
                        resultado["alvo"] = (alvo_antes.get("texto") or alvo_antes.get("tag")
                                             or "área vazia")[:120]
                        resultado["mudou"] = bool(
                            nova_aba or url_antes != pagina.url
                            or alvo_antes.get("html") != alvo_depois.get("html")
                            or alvo_antes.get("corpo") != alvo_depois.get("corpo"))
                    elif operacao == "clicar_texto":
                        resultado["alvo"] = str(parametros[0])[:120]
                        try:
                            assinatura_depois = alvo.evaluate(
                                "e => (e.closest('a,button,[role=button],.cursor-pointer') || e).outerHTML.slice(0,1200)",
                                timeout=1000)
                        except Exception:
                            assinatura_depois = "alvo removido da página"
                        corpo_depois = pagina.evaluate("() => (document.body?.innerText || '').slice(0,14000)")
                        resultado["mudou"] = bool(
                            nova_aba or url_antes != pagina.url
                            or assinatura_antes != assinatura_depois
                            or corpo_antes != corpo_depois)
                    if operacao in {"estado", "abas"}:
                        resultado["abas"] = [
                            resumo_aba(i, aba) for i, aba in enumerate(
                                p for p in contexto.pages if not p.is_closed())
                        ]
                    if operacao == "estado":
                        imagem = pagina.screenshot(type="jpeg", quality=65, timeout=10000)
                        resultado["imagem"] = base64.b64encode(imagem).decode("ascii")
                        resultado["largura"] = largura_viewport
                        resultado["altura"] = altura_viewport
                        resultado["cursor_emily"] = cursor_emily
                        resultado["sequencia_clique"] = sequencia_clique
                        with _condicao:
                            resultado["usuario_ativo"] = _usuario_ativo
                    elif operacao == "ler":
                        if pagina.url != "about:blank":
                            try:
                                if pagina.url.startswith("https://www.bing.com/search"):
                                    pagina.wait_for_function(
                                        "() => (document.querySelector('#b_results')?.innerText || '').length > 100",
                                        timeout=5000,
                                    )
                                else:
                                    pagina.wait_for_function(
                                        "() => (document.body?.innerText || '').trim().length > 20",
                                        timeout=4500,
                                    )
                            except Exception:
                                pass
                        resultado["texto"] = pagina.locator("body").inner_text(timeout=8000)[:30000]
                    if not futuro.done():
                        futuro.set_result(resultado)
                except Exception as exc:
                    if not futuro.done():
                        futuro.set_result({"ok": False, "erro": str(exc)[:500]})
    except Exception as exc:
        erro_inicio = str(exc)[:500]
    finally:
        if erro_inicio:
            while True:
                try:
                    _, _, futuro, _ = _fila.get_nowait()
                except queue.Empty:
                    break
                if not futuro.done():
                    futuro.set_result({"ok": False, "erro": erro_inicio})
        if contexto:
            try:
                contexto.close()
            except Exception:
                pass


def comando(operacao: str, *parametros, timeout: float = 30,
            origem: str = "agente") -> dict:
    global _thread, _revisao_usuario
    with _condicao:
        revisao_ao_pedir = _revisao_usuario
        while origem == "agente" and _usuario_ativo and not _encerrando:
            _condicao.wait()
        if _encerrando:
            return {"ok": False, "erro": "A Emily está encerrando."}
        if (origem == "agente" and revisao_ao_pedir != _revisao_usuario
                and operacao not in {"estado", "ler", "abas"}):
            return {"ok": False, "erro": (
                "Você mudou a página enquanto eu aguardava. Vou olhar o estado "
                "atual antes de agir, para não clicar no lugar errado.")}
        if origem == "usuario" and operacao not in {"estado", "ler", "abas"}:
            _revisao_usuario += 1
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_trabalhar, name="emily-browser", daemon=True)
            _thread.start()
        futuro: Future = Future()
        _fila.put((operacao, parametros, futuro, origem))
    try:
        return futuro.result(timeout=timeout)
    except TimeoutError:
        futuro.cancel()
        return {"ok": False, "erro": "O navegador demorou demais para responder."}


def ler() -> dict:
    return comando("ler")


def abrir(url: str, *, origem: str = "agente") -> dict:
    return comando("abrir", url, origem=origem)


def encerrar() -> None:
    """Fecha o Chromium ao sair de verdade da Emily."""
    global _thread, _encerrando
    with _condicao:
        _encerrando = True
        _condicao.notify_all()
        thread = _thread
        if not thread or not thread.is_alive():
            return
        futuro: Future = Future()
        _fila.put(("fechar", (), futuro, "sistema"))
    try:
        futuro.result(timeout=5)
        thread.join(timeout=5)
    except TimeoutError:
        pass
    with _condicao:
        if _thread is thread and not thread.is_alive():
            _thread = None

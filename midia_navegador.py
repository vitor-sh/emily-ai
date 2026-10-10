"""Descoberta e download de mídia solicitado pelo usuário no navegador.

O catálogo vem da extensão (DOM, frames, metadados e tráfego observado). Este
módulo resolve páginas e streams com yt-dlp, sem tentar quebrar DRM, CAPTCHA,
paywall ou autenticação. Downloads são jobs em thread e vão para Downloads.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shutil
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
_FORMATOS = {"video", "audio"}
_BITRATES_AUDIO = {"64kbps", "96kbps", "128kbps", "192kbps", "256kbps", "320kbps"}


def _downloads() -> Path:
    pasta = Path(os.getenv("EMILY_DOWNLOADS_DIR", "")).expanduser() if os.getenv(
        "EMILY_DOWNLOADS_DIR") else Path.home() / "Downloads"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _validar_url(url: str) -> str:
    """Aceita somente HTTP(S) público; bloqueia blob, file e rede local."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("A mídia precisa ter uma URL pública http/https; blob: não é baixável fora da aba.")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".local"):
        raise ValueError("URLs locais não são aceitas pelo baixador de mídia.")
    try:
        enderecos = {info[4][0] for info in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("Não consegui localizar o servidor dessa mídia.") from exc
    for endereco in enderecos:
        ip = ipaddress.ip_address(endereco)
        if not ip.is_global:
            raise ValueError("O endereço da mídia aponta para uma rede local ou reservada.")
    return url


def _importar_ytdlp():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "O componente de mídia yt-dlp ainda não está instalado. Feche a Emily, "
            "execute 'python -m pip install -r requirements.txt' e abra novamente."
        ) from exc


def disponivel() -> bool:
    try:
        _importar_ytdlp()
        return True
    except RuntimeError:
        return False


def _opcoes_base() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": False,
        "windowsfilenames": os.name == "nt",
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
        # HLS/DASH baixam em centenas de fragmentos: 4 em paralelo corta o
        # tempo de anime/portal de streaming pra ~1/4 sem mudar mais nada.
        "concurrent_fragment_downloads": 4,
        "ignoreconfig": True,
        "cachedir": False,
    }


def _navegador_cookies(descricao: str = "") -> Optional[str]:
    """Escolhe o perfil local provável para cookies de uma sessão já aberta."""
    descricao = (descricao or "").lower()
    if os.name == "nt":
        local = Path(os.getenv("LOCALAPPDATA", ""))
        roaming = Path(os.getenv("APPDATA", ""))
        candidatos = (
            ("edge", local / "Microsoft/Edge/User Data"),
            ("chrome", local / "Google/Chrome/User Data"),
            ("brave", local / "BraveSoftware/Brave-Browser/User Data"),
            ("firefox", roaming / "Mozilla/Firefox/Profiles"),
        )
    else:
        config = Path.home() / ".config"
        candidatos = (
            ("chrome", config / "google-chrome"),
            ("brave", config / "BraveSoftware/Brave-Browser"),
            ("chromium", config / "chromium"),
            ("edge", config / "microsoft-edge"),
            ("firefox", Path.home() / ".mozilla/firefox"),
        )
    def tem_banco(nome: str, pasta: Path) -> bool:
        if not pasta.exists():
            return False
        if nome == "firefox":
            return any(pasta.glob("*/cookies.sqlite"))
        padroes = ("*/Network/Cookies", "*/Cookies", "Network/Cookies", "Cookies")
        return any(any(pasta.glob(padrao)) for padrao in padroes)

    existentes = [(nome, pasta) for nome, pasta in candidatos if tem_banco(nome, pasta)]
    for preferido in ("edge", "chrome", "brave", "chromium", "firefox"):
        if preferido in descricao and any(nome == preferido for nome, _ in existentes):
            return preferido
    return existentes[0][0] if existentes else None


def _parece_exigir_sessao(erro: Exception) -> bool:
    texto = str(erro).lower()
    return any(marca in texto for marca in (
        "sign in", "login", "log in", "authentication", "authenticated",
        "cookies", "confirm your age", "age-restricted", "private video",
        "members-only", "members only", "unauthorized", "401", "403",
    ))


def _cabecalhos_http(referer: str = "") -> dict[str, str]:
    """Monta o contexto mínimo do frame sem copiar cookies ou enfraquecer TLS."""
    referer = (referer or "").strip()
    parsed = urlparse(referer)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {}
    return {
        "Referer": referer,
        "Origin": f"{parsed.scheme}://{parsed.netloc}",
    }


def inspecionar(url: str, navegador: str = "", referer: str = "") -> dict:
    """Extrai metadados e qualidades sem iniciar download."""
    url = _validar_url(url)
    yt_dlp = _importar_ytdlp()
    opcoes = _opcoes_base() | {"skip_download": True, "extract_flat": False}
    browser = _navegador_cookies(navegador)
    cabecalhos = _cabecalhos_http(referer)
    if cabecalhos:
        opcoes["http_headers"] = cabecalhos
    try:
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as primeira_falha:
        if not browser or not _parece_exigir_sessao(primeira_falha):
            raise
        opcoes["cookiesfrombrowser"] = (browser, None, None, None)
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            info = ydl.extract_info(url, download=False)
    if info.get("_type") in ("playlist", "multi_video"):
        entradas = [e for e in (info.get("entries") or []) if e]
        if len(entradas) != 1:
            return {
                "ok": False,
                "mensagem": "Essa URL contém vários vídeos. Abra o vídeo desejado na aba e peça novamente.",
                "total": len(entradas),
            }
        info = entradas[0]
    formatos = info.get("formats") or []
    alturas = sorted({int(f["height"]) for f in formatos if f.get("height")}, reverse=True)
    return {
        "ok": True,
        "titulo": info.get("title") or "Mídia sem título",
        "duracao": info.get("duration"),
        "autor": info.get("uploader") or info.get("channel") or "",
        "thumbnail": info.get("thumbnail") or "",
        "qualidades": [f"{h}p" for h in alturas[:12]],
        "tem_audio": any(f.get("acodec") not in (None, "none") for f in formatos),
        "tem_video": any(f.get("vcodec") not in (None, "none") for f in formatos),
        "pagina": info.get("webpage_url") or url,
    }


def _formato_ytdlp(formato: str, qualidade: str) -> tuple[str, list[dict], Optional[str]]:
    if formato == "audio":
        bitrate = "0" if qualidade == "melhor" else qualidade.removesuffix("kbps")
        return "bestaudio/best", [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": bitrate,
        }], None
    if qualidade == "melhor":
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best", [], "mp4"
    altura = int(qualidade[:-1])
    seletor = (
        f"bestvideo[ext=mp4][height<={altura}]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={altura}]+bestaudio/"
        f"best[height<={altura}]/bestvideo+bestaudio/best"
    )
    return seletor, [], "mp4"


def _atualizar_job(job_id: str, **dados) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(dados)
            _JOBS[job_id]["atualizado_em"] = time.time()


def _executar_job(job_id: str, url: str, formato: str, qualidade: str,
                  navegador: str, referer: str, pagina: str = "") -> None:
    try:
        yt_dlp = _importar_ytdlp()
        seletor, postprocessors, merge = _formato_ytdlp(formato, qualidade)

        def progresso(dados: dict) -> None:
            estado = dados.get("status")
            if estado == "downloading":
                total = dados.get("total_bytes") or dados.get("total_bytes_estimate") or 0
                baixado = dados.get("downloaded_bytes") or 0
                percentual = round(baixado * 100 / total, 1) if total else None
                _atualizar_job(
                    job_id,
                    estado="baixando",
                    percentual=percentual,
                    velocidade=dados.get("speed"),
                    eta=dados.get("eta"),
                    arquivo=dados.get("filename") or "",
                )
            elif estado == "finished":
                _atualizar_job(job_id, estado="processando", percentual=100.0,
                               arquivo=dados.get("filename") or "")

        opcoes = _opcoes_base() | {
            "format": seletor,
            "outtmpl": str(_downloads() / "%(title).180B [%(id)s].%(ext)s"),
            "progress_hooks": [progresso],
            "postprocessors": postprocessors,
            "overwrites": False,
            "continuedl": True,
        }
        browser = _navegador_cookies(navegador)
        cabecalhos = _cabecalhos_http(referer)
        if cabecalhos:
            opcoes["http_headers"] = cabecalhos
        if merge:
            opcoes["merge_output_format"] = merge
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            opcoes["ffmpeg_location"] = ffmpeg
        elif formato == "audio":
            raise RuntimeError("FFmpeg não foi encontrado; ele é necessário para converter o áudio para MP3.")

        # Múltiplos alvos: a URL crua do player primeiro; se ela falhar e
        # tivermos a página que a hospeda, tentamos a página — o extrator do
        # yt-dlp do site (anime, portal de streaming, player encapsulado)
        # resolve o stream por lá, inclusive HLS/DASH protegidos sem DRM.
        alvos = [url]
        # Em players incorporados, o referer é a página real do iframe. Ela é o
        # melhor fallback para o extrator e precisa vir antes da página externa.
        for pagina_candidata in (referer, pagina):
            pagina_limpa = (pagina_candidata or "").strip()
            if pagina_limpa.startswith(("http://", "https://")) and pagina_limpa not in alvos:
                alvos.append(pagina_limpa)

        info = None
        caminho = None
        ultimo_erro: Exception = RuntimeError("nada baixado")
        for indice_alvo, alvo in enumerate(alvos):
            if indice_alvo:
                _atualizar_job(
                    job_id,
                    aviso=f"A URL direta não resolveu; tentando pela página ({alvo[:90]}).",
                )
            try:
                with yt_dlp.YoutubeDL(opcoes) as ydl:
                    info = ydl.extract_info(alvo, download=True)
                    caminho = ydl.prepare_filename(info)
                break
            except Exception as falha:
                ultimo_erro = falha
                # Conteúdo público é tentado primeiro. A sessão local só é
                # lida se o extrator indicar login/cookies e houver banco
                # real no perfil.
                if not browser or not _parece_exigir_sessao(falha):
                    continue
                opcoes_cookies = dict(opcoes)
                opcoes_cookies["cookiesfrombrowser"] = (browser, None, None, None)
                _atualizar_job(job_id, aviso=f"Conteúdo exige sessão; usando cookies locais do {browser}.")
                try:
                    with yt_dlp.YoutubeDL(opcoes_cookies) as ydl:
                        info = ydl.extract_info(alvo, download=True)
                        caminho = ydl.prepare_filename(info)
                    break
                except Exception as falha_com_cookies:
                    ultimo_erro = falha_com_cookies
        if caminho is None or info is None:
            raise ultimo_erro
        if formato == "audio":
            caminho = str(Path(caminho).with_suffix(".mp3"))
        # O merge/conversão pode trocar a extensão preparada pelo yt-dlp.
        # requested_downloads contém o caminho pós-processado quando disponível.
        candidatos_finais = [
            d.get("filepath") for d in (info.get("requested_downloads") or [])
            if isinstance(d, dict) and d.get("filepath")
        ]
        candidatos_finais += [info.get("filepath"), caminho]
        caminho = next((str(Path(p)) for p in candidatos_finais if p and Path(p).is_file()), caminho)
        _atualizar_job(
            job_id,
            estado="concluido",
            percentual=100.0,
            titulo=info.get("title") or "Mídia",
            arquivo=caminho,
            concluido_em=time.time(),
        )
        try:
            from emily_cloud.integration import agendar_download
            agendar_download(
                caminho, url_origem=url, origem="midia_navegador",
                callback=lambda r: _atualizar_job(job_id, cloud=r),
            )
        except Exception as exc:
            _atualizar_job(job_id, cloud={"ok": False, "erro": str(exc)})
    except Exception as exc:  # o erro precisa aparecer no status, não matar a thread
        mensagem = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).strip()
        drm = any(t in mensagem.lower() for t in ("drm", "widevine", "fairplay", "playready"))
        if drm:
            mensagem = "A mídia é protegida por DRM e não pode ser baixada pela Emily."
        _atualizar_job(job_id, estado="erro", erro=mensagem[:1200], concluido_em=time.time())


def iniciar_download(url: str, formato: str = "video", qualidade: str = "melhor",
                     navegador: str = "", referer: str = "", pagina: str = "") -> dict:
    url = _validar_url(url)
    _importar_ytdlp()  # falha imediatamente com instrução clara
    formato = (formato or "video").strip().lower()
    qualidade = (qualidade or "melhor").strip().lower()
    if formato not in _FORMATOS:
        raise ValueError("Formato inválido. Use 'video' ou 'audio'.")
    if formato == "audio" and qualidade not in ({"melhor"} | _BITRATES_AUDIO):
        raise ValueError("Qualidade de áudio inválida. Use melhor, 64, 96, 128, 192, 256 ou 320kbps.")
    if formato == "video":
        match = re.fullmatch(r"(\d{3,4})p", qualidade)
        if qualidade != "melhor" and (not match or not 144 <= int(match.group(1)) <= 8640):
            raise ValueError("Qualidade de vídeo inválida. Use melhor ou uma resolução entre 144p e 8640p.")

    job_id = uuid.uuid4().hex[:10]
    job = {
        "id": job_id,
        "estado": "iniciando",
        "url": url,
        "formato": formato,
        "qualidade": qualidade,
        "percentual": 0.0,
        "pasta": str(_downloads()),
        "sessao_navegador": _navegador_cookies(navegador) or "não detectada",
        "criado_em": time.time(),
        "atualizado_em": time.time(),
    }
    with _LOCK:
        _JOBS[job_id] = job
    threading.Thread(
        target=_executar_job,
        args=(job_id, url, formato, qualidade, navegador, referer, pagina),
        daemon=True,
        name=f"EmilyMidia-{job_id}",
    ).start()
    return dict(job)


def status(job_id: str = "") -> dict:
    with _LOCK:
        if job_id:
            job = _JOBS.get(job_id)
            return dict(job) if job else {"estado": "nao_encontrado", "id": job_id}
        return {"jobs": [dict(j) for j in sorted(
            _JOBS.values(), key=lambda x: x["criado_em"], reverse=True)[:20]]}

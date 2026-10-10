"""Build privado Windows 11 x64 a partir da raiz atual de minha-ia.

Executar no Windows com Python 3.13 x64 e Inno Setup 6:
  py -3.13 -m pip install -r requirements-windows.txt
  py -3.13 build_emily_windows.py --version 1.0.0 \
      --gateway-url https://SEU-GATEWAY --include-private-env
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

RAIZ = Path(__file__).resolve().parent
PASTAS_DADOS = ("web", "static", "img", "assets", "extensao_emily",
                "emily-gateway-service", "hollow_knight_emily/art",
                "hollow_knight_emily/mod", "hollow_knight_emily/runtime")
ARQUIVOS_DADOS = ("emilyimage.png", "emily.gif", "requirements.txt",
                  "regras_servidor.md", "installer/emily.ico")
PACOTES = ("memoria_unificada", "emily_cloud", "hollow_knight_emily",
           "google.auth", "google.oauth2")
COLETAR = ("discord", "aiohttp", "watchdog", "webview", "pystray",
           "chromadb", "onnxruntime", "tokenizers", "soundcard",
           "flask", "websockets", "playwright")


def modulos_raiz() -> list[str]:
    ignorar = {"emily_bootstrap", "pyi_rhook_emily", "build_emily",
               "build_emily_linux", "build_emily_windows", "publicar_windows",
               "preparar_windows_fonte"}
    return [p.stem for p in RAIZ.glob("*.py")
            if not p.stem.startswith(("_", "test_", "testar_", "test_emily"))
            and p.stem not in ignorar]


def preparar_argumentos(versao: str, gateway_url: str, privado: bool) -> list[str]:
    from windows_update import _versao
    _versao(versao)
    gateway_url = gateway_url.rstrip("/")
    if not gateway_url.startswith("https://"):
        raise ValueError("gateway público precisa de HTTPS")
    metadados = RAIZ / "windows-build" / "windows-release.json"
    metadados.parent.mkdir(exist_ok=True)
    metadados.write_text(json.dumps({"version": versao,
                                     "sync_url": gateway_url,
                                     "update_url": gateway_url + "/windows/update"}),
                         encoding="utf-8")
    args = ["emily_bootstrap.py", "--name=Emily", "--onedir", "--noconsole",
            "--noconfirm", "--clean", f"--paths={RAIZ}",
            f"--icon={RAIZ / 'installer' / 'emily.ico'}",
            f"--runtime-hook={RAIZ / 'pyi_rhook_emily.py'}",
            "--hidden-import=webview.platforms.edgechromium",
            "--hidden-import=mss.windows",
            "--hidden-import=pynput._util.win32",
            "--hidden-import=pynput.keyboard._win32",
            "--hidden-import=pynput.mouse._win32"]
    for nome in modulos_raiz():
        args.append(f"--hidden-import={nome}")
    for nome in PACOTES:
        args.append(f"--collect-submodules={nome}")
    for nome in COLETAR:
        args.append(f"--collect-all={nome}")
    for nome in PASTAS_DADOS:
        caminho = RAIZ / nome
        if caminho.exists():
            args.append(f"--add-data={caminho}{os.pathsep}{nome}")
    for nome in ARQUIVOS_DADOS:
        caminho = RAIZ / nome
        if caminho.is_file():
            destino = str(Path(nome).parent)
            args.append(f"--add-data={caminho}{os.pathsep}{destino}")
    args.append(f"--add-data={metadados}{os.pathsep}.")
    if privado:
        segredo = RAIZ / ".env"
        if not segredo.is_file():
            raise FileNotFoundError("--include-private-env exige .env")
        args.append(f"--add-data={segredo}{os.pathsep}.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg.exe não encontrado no PATH do Windows de build")
    args.append(f"--add-binary={ffmpeg}{os.pathsep}.")
    browsers = RAIZ / "windows-build" / "playwright-browsers"
    if browsers.is_dir():
        args.append(f"--add-data={browsers}{os.pathsep}playwright-browsers")
    return args


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--gateway-url", required=True)
    parser.add_argument("--include-private-env", action="store_true")
    op = parser.parse_args()
    if os.name != "nt":
        parser.error("o executável Windows precisa ser gerado no Windows")
    if sys.maxsize <= 2 ** 32:
        parser.error("use Python x64")
    if sys.version_info[:2] != (3, 13):
        parser.error("o build foi preparado para Python 3.13 x64")
    iscc = shutil.which("ISCC.exe") or shutil.which("ISCC")
    if not iscc:
        parser.error("Inno Setup 6 (ISCC.exe) não encontrado no PATH")
    webview2 = RAIZ / "windows-build" / "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
    if not webview2.is_file():
        parser.error("baixe o Evergreen Standalone Installer x64 da Microsoft em "
                     "windows-build/MicrosoftEdgeWebView2RuntimeInstallerX64.exe")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        parser.error("instale requirements-windows.txt")
    ambiente = dict(os.environ)
    browsers = RAIZ / "windows-build" / "playwright-browsers"
    # O diretório pode existir de um build antigo com outra revisão. O
    # instalador do Playwright é idempotente e garante a revisão atual.
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium", "--only-shell"],
                   cwd=RAIZ, env={**ambiente, "PLAYWRIGHT_BROWSERS_PATH": str(browsers)},
                   check=True)
    args = preparar_argumentos(op.version, op.gateway_url, op.include_private_env)
    subprocess.run([sys.executable, "-m", "PyInstaller", *args], cwd=RAIZ,
                   env=ambiente, check=True)
    exe = RAIZ / "dist" / "Emily" / "Emily.exe"
    if not exe.is_file():
        raise RuntimeError("PyInstaller não gerou Emily.exe")
    for obrigatorio in ("emilyimage.png", "web/index.html", "installer/emily.ico"):
        if not (exe.parent / "_internal" / obrigatorio).is_file():
            raise RuntimeError(f"arquivo da interface não entrou no pacote: {obrigatorio}")
    if op.include_private_env:
        env_empacotado = exe.parent / "_internal" / ".env"
        if not env_empacotado.is_file():
            raise RuntimeError("PyInstaller não incluiu o .env privado em _internal")
        # O teste precisa provar que o executável lê o arquivo empacotado,
        # mesmo quando o PC do build já tem essas chaves no ambiente.
        chaves = ("GROQ_API_KEY", "FISH_AUDIO_KEY", "EMILY_PONTE_TOKEN")
        ambiente_limpo = {k: v for k, v in ambiente.items() if k not in chaves}
        subprocess.run([str(exe), "--config-preflight"], cwd=RAIZ,
                       env=ambiente_limpo, timeout=30, check=True)
    subprocess.run([str(exe)], cwd=RAIZ, env={**ambiente, "EMILY_PREFLIGHT": "1"},
                   timeout=180, check=True)
    subprocess.run([str(exe), "--gateway-preflight"], cwd=RAIZ,
                   env={**ambiente, "EMILY_BROWSER_PERMANENTE": "0",
                        "EMILY_HK_PERMANENTE": "0"}, timeout=60, check=True)
    subprocess.run([iscc, f"/DAppVersion={op.version}",
                    str(RAIZ / "installer" / "emily.iss")], cwd=RAIZ,
                   check=True)
    saida = RAIZ / "dist" / "installer" / f"Emily-Setup-{op.version}.exe"
    if not saida.is_file():
        raise RuntimeError("Inno Setup não gerou o instalador")
    print(f"Instalador: {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

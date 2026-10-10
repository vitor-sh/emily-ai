"""
Ponto de entrada mínimo e estável do executável da Emily.

O PyInstaller congela o arquivo usado como entry point. Por isso o main.py não
podia ser atualizado pelo botão: mesmo existindo um main.py novo em _internal,
o executável continuava rodando a cópia congelada. Este bootstrap é a única
parte que fica fixa; o main é importado como módulo e pode ser substituído pelo
finder instalado em pyi_rhook_emily.py.
"""
import os
import sys
from pathlib import Path


def _carregar_ambiente() -> None:
    """Carrega o .env antes dos módulos que criam clientes de API no import."""
    if os.getenv("EMILY_PUBLIC_MODE") == "1":
        # O perfil público já foi validado/aplicado pelo ponto de entrada.
        # Não completar valores usando o .env da instalação pessoal.
        return
    from dotenv import load_dotenv

    if getattr(sys, "frozen", False):
        pasta_exe = Path(sys.executable).resolve().parent
        pasta_pacote = Path(getattr(sys, "_MEIPASS", pasta_exe / "_internal"))
        candidatos = (pasta_exe / ".env", pasta_pacote / ".env")
    else:
        candidatos = (Path(__file__).resolve().parent / ".env",)
    for caminho in candidatos:
        if caminho.is_file():
            # Um .env ao lado do exe pode ajustar a configuração sem recompilar;
            # o arquivo empacotado completa as chaves que não foram definidas.
            load_dotenv(dotenv_path=caminho, override=False)


def _validar_configuracao_privada() -> None:
    ausentes = [nome for nome in ("GROQ_API_KEY", "FISH_AUDIO_KEY", "EMILY_PONTE_TOKEN")
                if not os.getenv(nome)]
    if ausentes:
        raise SystemExit("chaves privadas ausentes no pacote: " + ", ".join(ausentes))


def _preparar_runtime() -> None:
    """Log e PATH precisam existir antes de qualquer import da aplicação."""
    try:
        import servicos_runtime

        servicos_runtime.preparar_ambiente()
    except Exception as e:  # noqa: BLE001
        print(f"[BOOTSTRAP] não normalizei o ambiente: {e}")
    try:
        import emily_logs

        emily_logs.configurar()
    except Exception as e:  # noqa: BLE001
        print(f"[BOOTSTRAP] não ativei o arquivo de log: {e}")


def _preparar_compatibilidade_linux() -> None:
    """Replica o bootstrap de plataforma do main antes do preflight."""
    try:
        import platform_compat

        if platform_compat.is_linux():
            import compat_imports

            sys.modules["keyboard"] = compat_imports.keyboard
            sys.modules["pyperclip"] = compat_imports.pyperclip
    except Exception as e:  # noqa: BLE001 — o main ainda possui seu fallback
        print(f"[BOOTSTRAP] compatibilidade Linux indisponível: {e}")


def iniciar() -> None:
    _carregar_ambiente()
    if "--config-preflight" in sys.argv:
        _validar_configuracao_privada()
        return
    _preparar_runtime()
    _preparar_compatibilidade_linux()
    if os.name == "nt" and ("--gateway" in sys.argv or "--gateway-preflight" in sys.argv):
        import gateway_windows_entry
        gateway_windows_entry.iniciar(validar="--gateway-preflight" in sys.argv)
        return
    # O ensaio da atualização não pode importar main: ele inicia threads e a
    # interface. O atualizador valida sua sintaxe e seus imports estaticamente.
    if os.environ.get("EMILY_PREFLIGHT"):
        import atualizador_emily

        raise SystemExit(atualizador_emily.rodar_preflight())

    if os.name == "nt" and getattr(sys, "frozen", False) and os.getenv("EMILY_PUBLIC_MODE") != "1":
        try:
            import windows_update
            if windows_update.verificar_e_instalar():
                return
        except Exception as exc:
            print(f"[BOOTSTRAP] atualização Windows adiada: {exc}")

    # Import intencional: todo o boot da aplicação ainda vive no main.py.
    # No pacote, o runtime hook dá prioridade ao main.py solto em _internal.
    __import__("main")


if __name__ == "__main__":
    iniciar()

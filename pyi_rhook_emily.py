"""
pyi_rhook_emily.py — runtime hook do PyInstaller.

Roda DENTRO do Emily empacotado, antes do main.py. Duas funções, as duas só
fazem algo no modo empacotado (getattr(sys, "frozen")):

1. CWD = pasta do executável. memoria.json, agenda.json e afins gravados por
   caminho relativo têm que nascer ao lado do app (igual no Windows com o
   Emily.exe), não espalhados pelo $HOME de quem clicou no ícone.

2. Normaliza o PATH do ambiente gráfico e ativa o log unificado: pelo terminal
   a saída aparece no terminal E no arquivo; pelo atalho vai para o arquivo.
"""
import importlib.util
import os
import sys
import time


class _EmilyOverrides:
    """
    Import finder: .py soltos na pasta de override VENCEM o código embutido.

    É isso que permite atualizar a Emily sem recompilar: o atualizador copia
    os .py novos pra _internal/ (ou pro ensaio, via EMILY_OVERRIDE_DIR) e o
    finder entrega ELES em vez dos módulos embutidos no pacote. O bootstrap é
    fixo, mas main.py também é um módulo e, portanto, pode ser atualizado.
    Além dos módulos top-level, aceita pacotes Python explícitos copiados pelo
    atualizador (por exemplo memoria_unificada), sem tornar assets importáveis.
    """

    def __init__(self, pasta: str) -> None:
        self._pasta = pasta
        self._cache: set = set()
        self._quando = 0.0

    def _nomes(self) -> set:
        agora = time.time()
        if agora - self._quando > 2.0:   # cache curto: boot importa centenas
            try:
                self._cache = {
                    f[:-3] for f in os.listdir(self._pasta)
                    if f.endswith(".py")
                    and not f.startswith("_")
                    and f[:-3] not in ("pyi_rhook_emily", "build_emily",
                                       "build_emily_linux", "emily_bootstrap")
                }
            except OSError:
                self._cache = set()
            self._quando = agora
        return self._cache

    def find_spec(self, fullname, path=None, target=None):
        # Submódulos NUNCA passam por aqui: eles são resolvidos pelo __path__
        # do pacote carregado logo abaixo (submodule_search_locations). Devolver
        # None cedo, SEM tocar em importlib — no boot do exe `import importlib.util`
        # dentro deste método consultaria find_spec de novo e viraria recursão
        # infinita (foi o boot quebrado do build). E não sombrear submódulos
        # também preserva os pacotes que o PyInstaller coleta (chromadb.api,
        # discord.ext, onnxruntime...).
        if "." in fullname:
            return None
        if fullname not in self._nomes():
            # Pacote explícito copiado pelo atualizador (ex.: memoria_unificada):
            # pasta com __init__.py vira pacote importável, com __path__ próprio.
            pacote = os.path.join(self._pasta, fullname, "__init__.py")
            if not os.path.isfile(pacote):
                return None
            arquivo, locais = pacote, [os.path.dirname(pacote)]
        else:
            arquivo = os.path.join(self._pasta, fullname + ".py")
            locais = None
        try:
            return importlib.util.spec_from_file_location(
                fullname, arquivo, submodule_search_locations=locais)
        except Exception:
            return None


def _emily_bootstrap() -> None:
    if not getattr(sys, "frozen", False):
        return

    # 0) Dados de ícones/temas do SISTEMA precisam continuar visíveis. O hook
    #    do PyGObject copia só PARTE dos temas de ícones (ex.: breeze-dark) para
    #    _internal/share — e quando o diálogo nativo de arquivos tenta desenhar
    #    um ícone ausente (image-missing.svg, 16@2x), o GTK dispara um
    #    g_error() FATAL e o processo inteiro morre com SIGABRT (medido: crash
    #    ao abrir o seletor de disco da Emily Cloud). Colocar o share do
    #    sistema DEPOIS do share do bundle faz o GtkIconTheme resolver os
    #    ícones completos do tema do desktop, sem inflar o pacote.
    try:
        _bundle_share = os.path.join(
            os.path.dirname(os.path.abspath(sys.executable)), "_internal", "share")
        _sistema = [d for d in str(os.environ.get("XDG_DATA_DIRS", "")).split(os.pathsep)
                    if d and os.path.isdir(d)]
        for _padrao in ("/usr/local/share", "/usr/share"):
            if _padrao not in _sistema and os.path.isdir(_padrao):
                _sistema.append(_padrao)
        _dirs = ([_bundle_share] if os.path.isdir(_bundle_share) else []) + _sistema
        if _dirs:
            os.environ["XDG_DATA_DIRS"] = os.pathsep.join(_dirs)
    except Exception:
        pass

    # 1) Trabalha a partir da pasta do executável.
    try:
        os.chdir(os.path.dirname(os.path.abspath(sys.executable)))
    except OSError:
        pass
    if os.name == "nt":
        internal = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "_internal")
        os.environ["PATH"] = internal + os.pathsep + os.environ.get("PATH", "")
        browsers = os.path.join(internal, "playwright-browsers")
        if os.path.isdir(browsers):
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", browsers)

    # 1b) Overrides de código (atualização sem recompilar).
    try:
        pasta = (os.environ.get("EMILY_OVERRIDE_DIR")
                 or os.path.join(os.path.dirname(os.path.abspath(
                     sys.executable)), "_internal"))
        sys.meta_path.insert(0, _EmilyOverrides(pasta))
    except Exception:
        pass

    # 2) Mesmo ambiente e mesmo arquivo de log pelo Konsole, .desktop e
    # autostart. O bootstrap repete isto como fallback para pacotes antigos.
    try:
        import servicos_runtime
        import emily_logs

        servicos_runtime.preparar_ambiente()
        emily_logs.configurar()
        print(f"\n===== Emily iniciada em {time.strftime('%d/%m %H:%M:%S')} "
              f"=====")
    except Exception:
        # Falha de diagnóstico nunca pode impedir a Emily de abrir.
        pass


_emily_bootstrap()

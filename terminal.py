"""
Terminal para a Emily: Bash no Linux e PowerShell no Windows, com portão de segurança.

Por que módulo próprio e não dentro de ferramentas.py: a classificação de
comando é regra local, NUNCA julgamento do modelo. Se dependesse do modelo,
uma frase bem construída convenceria a Emily de que "format c:" é inofensivo
— mesma lição do portão do enxada.py (ver comentário lá em _COMANDOS_LIVRES).

Três caminhos, decididos por regex sobre o comando cru:

  LIVRE      -> roda direto. Só leitura ou inofensivo.
  CONFIRMAR  -> normalmente recusa a primeira vez e guarda o comando; só roda
                numa segunda chamada com confirmado=True e comando idêntico.
                No modo experimental, uma ordem explícita do dono pode chegar
                com autorização_direta=True e pular apenas esse vaivém.
  BLOQUEADO  -> recusa sempre. Operações como formatar disco ou apagar
                arquivos centrais do sistema não têm confirmação liberadora.

A execução usa Bash no Linux ou PowerShell no Windows. Comando administrativo
simples no Linux passa pelo pkexec e pela autorização nativa do desktop; a
Emily nunca recebe a senha. A saída é truncada antes de voltar ao modelo.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from typing import Optional

LIVRE = "livre"
CONFIRMAR = "confirmar"
BLOQUEADO = "bloqueado"

MAX_SAIDA = 4000            # caracteres devolvidos ao modelo, por stream
_EXPIRA_CONFIRMACAO = 300   # segundos até a confirmação pendente morrer

# Um terminal, dois shells: PowerShell no Windows, Bash/Zsh no Linux.
# O portão de segurança (classificação, confirmação, cancelamento) é o MESMO
# nos dois — só a sintaxe do comando muda.
_E_LINUX = os.name == "posix"

if _E_LINUX:
    _SHELL = os.environ.get("SHELL", "/bin/bash")
    if "bash" not in _SHELL and "zsh" not in _SHELL:
        _SHELL = "/bin/bash"
    _POWERSHELL = None
else:
    _SHELL = None
    _POWERSHELL = "powershell.exe"


def _log(msg: str) -> None:
    print(f"[TERMINAL] {msg}")


# ═════════════════════════════════════════════════════════════════
# BLOQUEADOS — irreversível ou catastrófico. Recusa SEMPRE.
#
# Regex sobre o texto cru, case-insensitive. É blocklist, não whitelist:
# tudo que não casa com ela nem com os confirmáveis é LIVRE. Isso erra pro
# lado de deixar passar comando estranho (que no pior caso falha sozinho)
# em vez de travar a ferramenta toda hora — mas os padrões abaixo são os
# que não têm volta, então são pegos antes de qualquer coisa.
# ═════════════════════════════════════════════════════════════════

_BLOQUEADOS = (
    # Formatar / particionar / limpar disco inteiro.
    # 'format' so é perigoso apontando pra uma unidade (format C:, format /fs...).
    # \bformat\b solto casaria com '-Format' de Get-ChildItem/Get-Date e travaria
    # comando inocente — falso positivo medido em teste.
    r"\bformat(\.com)?\s+/?[a-z]:",
    r"format-volume\b",
    r"\bdiskpart\b",
    r"\bclear-disk\b",
    r"\binitialize-disk\b",
# Apagar em massa em raízes e pastas de sistema
    r"remove-item\s+[^;\n]*-recurse[^;\n]*\s+[\"']?[a-z]:\\?\s*$",
    r"remove-item\s+[^;\n]*[\"'](c:\\windows|[a-z]:\\)([\\\"' ]|$)",
    r"rd\s+/s\s+/q",
    r"rmdir\s+/s",
    r"del\s+/[fsq]",
    # Registro: hives e chaves inteiras
    r"reg\s+delete\s+hkey_(local_machine|users|current_user|classes_root)\s*$",
    r"reg\s+delete\s+.*/f\s*$",          # reg delete com força é quase sempre chave grande
    r"remove-item\s+[^;\n]*hklm:",
    r"remove-item\s+[^;\n]*hkcu:\\?$",
    # Boot, recuperação e backup do sistema
    r"\bbcdedit\b",
    r"vssadmin\s+delete\s+shadows",
    r"wbadmin\s+delete",
    r"disable[- ]computerrestore",
    # Segurança do Windows (energia é confirmável mais abaixo).
    r"logoff",
    r"set-executionpolicy\s+(unrestricted|bypass)",
    r"add-mpppreference",                # isentar arquivos do Defender
    r"set-mppreference\s+[^;\n]*disable",
    r"net\s+(user|localgroup)\s+.*\s/add",
    # Download-and-run cego
    r"iex\s*\(\s*(new-object|invoke-webrequest|iwr|curl)",
    r"invoke-expression\s*\(\s*(new-object|invoke-webrequest|iwr)",
    r"irm\s+\S+\s*\|\s*iex",
    # Matar processo do sistema crítico ou da própria Emily
    r"stop-process\s+[^;\n]*\s-(name|id)\s+(\s*|\S*\s*)(wininit|winlogon|csrss|services|lsass|smss)",
    r"taskkill\s+/f\s+/im\s+(wininit|winlogon|csrss|services\.exe|lsass|smss)",
    # ── Linux (bash): irreversível ou catastrófico ──
    # Formatar / apagar disco inteiro
    r"\bmkfs(\.\w+)?\b",
    r"\bwipefs\b",
    r"\bdd\b[^;\n]*\bof=/dev/(sd|nvme|vd|hd|mmcblk)",
    r"[><]\s*/dev/(sd[a-z]+|nvme\d+n\d+|mmcblk\d+|hd[a-z])",   # echo x > /dev/sda
    r"\b(fdisk|sfdisk|cfdisk|parted)\b",
    # Apagar em massa: raiz, pastas de sistema e a home inteira
    r"\brm\b[^;\n]*\s+/\s*(;|$)",
    r"\brm\b[^;\n]*\s+/(boot|etc|usr|var|lib|bin|sbin|opt)\b",
    r"\brm\b[^;\n]*\s+~/?\s*(;|$)",
    r"\brm\b[^;\n]*\s+\$home/?\s*(;|$)",
    r"\bshred\b[^;\n]*\s+/(boot|etc|usr|var|bin|sbin)\b",
    # Alterações de boot e disco continuam bloqueadas; energia é confirmável.
    r"\binit\s+[06]\b",
    # Fork bomb e módulos do kernel em uso
    r":\(\)\s*\{[^}]*\}\s*;\s*:",
    r"\brmmod\b\s+(usbcore|ext4|xfs|btrfs)",
)

_RE_BLOQUEADOS = tuple(re.compile(p, re.IGNORECASE) for p in _BLOQUEADOS)
_ENERGIA_WINDOWS = re.compile(
    r"(stop|restart|shutdown)[- ]computer|\b(shutdown|reboot|poweroff|halt)\b|"
    r"\bsystemctl\s+(poweroff|reboot|halt|hibernate|suspend)\b",
    re.IGNORECASE,
)


# ═════════════════════════════════════════════════════════════════
# CONFIRMÁVEIS — muda o mundo de forma visível, mas reversível ou
# cotidiana. Primeira chamada pergunta ao Vitor; segunda executa.
# ═════════════════════════════════════════════════════════════════

_CONFIRMaveis = (
    # Desligar, reiniciar ou suspender só após a autorização da ação exata.
    r"(stop|restart|shutdown)[- ]computer",
    r"\b(shutdown|reboot|poweroff|halt)\b",
    r"\bsystemctl\s+(poweroff|reboot|halt|hibernate|suspend)\b",
    # Elevação de privilégios nunca passa como leitura livre.
    r"\b(sudo|pkexec)\s+",
    # Instalar / desinstalar programas
    r"\bwinget\s+(install|uninstall|upgrade)",
    r"\bchoco\s+(install|uninstall)",
    r"\bpip\s+(install|uninstall)",
    r"\bnpm\s+(install|-g)\b.*--global",
    # Desinstalar pelo painel clássico
    r"appwiz\.cpl",
    r"\buninstall\b",
    # Matar processo de usuário (fechar à força)
    r"stop-process\b",
    r"taskkill\b",
    # Serviços
    r"(start|stop|restart)-service\b",
    r"net\s+(start|stop)\b",
    # Apagar arquivo/pasta pontual FORA das pastas seguras (não-casou com bloqueados)
    r"remove-item\b",
    r"\bdel\b\s+\S",
    r"\brd\b\s",
    r"\brmdir\b",
    # Mudanças de sistema visíveis
    r"set-executionpolicy",
    r"\bsfc\b",
    r"\bdism\b",
    r"ipconfig\s+/(flushdns|release|renew)",
    r"clear-recyclebin",
    # ── Linux (bash): muda o mundo de forma visível; pergunta antes ──
    r"\bdnf5?\s+(install|remove|erase|reinstall|downgrade|autoremove|upgrade)\b",
    r"\byum\s+(install|remove|erase|update|upgrade|autoremove)\b",
    r"\bapt(-get)?\s+(install|remove|purge|autoremove|upgrade|full-upgrade|dist-upgrade)\b",
    r"\bpacman\s+-(S|R|U)\S*\b",
    r"\bzypper\s+(install|remove|update|upgrade|dup)\b",
    r"\brpm\s+-(e|i|U)\b",
    r"\b(snap|flatpak)\s+(install|remove|uninstall|reset|refresh)\b",
    r"\bpip3?\s+(install|uninstall)\b",
    r"\bnpm\s+(install|uninstall)\b[^;\n]*-g\b",
    r"\buninstall\b",
    # Matar processo de usuário
    r"\bkill(all)?\b", r"\bpkill\b",
    # Serviços
    r"\bsystemctl\s+(start|stop|restart|disable|enable|mask|unmask)\b",
    r"\bservice\s+\S+\s+(start|stop|restart)\b",
    # Apagar arquivo/pasta pontual (qualquer rm pergunta antes; os catastróficos
    # já caíram nos bloqueados acima)
    r"\brm\b",
    r"\bshred\b",
    r"\btruncate\b",
    # Contas e permissões de sistema
    r"\b(userdel|groupdel)\b",
    r"\bch(mod|own)\b[^;\n]*\s+/(etc|usr|var|boot|bin|sbin|lib|opt)\b",
    r"\bcrontab\s+-r\b",
    r"\b(timedatectl|hostnamectl|localectl)\s+set-\S+",
)

_RE_CONFIRMAR = tuple(re.compile(p, re.IGNORECASE) for p in _CONFIRMaveis)


def classificar(comando: str) -> str:
    """
    Decide o destino do comando ANTES de qualquer coisa.

    Ordem importa: bloqueado ganha de confirmável, que ganha de livre.
    """
    if not _E_LINUX and _ENERGIA_WINDOWS.search(comando):
        return BLOQUEADO
    for rx in _RE_BLOQUEADOS:
        if rx.search(comando):
            return BLOQUEADO
    for rx in _RE_CONFIRMAR:
        if rx.search(comando):
            return CONFIRMAR
    if _E_LINUX:
        try:
            partes = shlex.split(comando)
        except ValueError:
            partes = []
        if partes:
            prefixo = os.path.basename(partes[0]).lower() in {"sudo", "pkexec"}
            alvo = partes[1:] if prefixo else partes
            if alvo and alvo[0] == "--":
                alvo = alvo[1:]
            if alvo and _precisa_admin_linux(
                    os.path.basename(alvo[0]).lower(), alvo[1:], prefixo):
                return CONFIRMAR
    return LIVRE


# ═════════════════════════════════════════════════════════════════
# CONFIRMAÇÃO PENDENTE
#
# Guarda O COMANDO EXATO que foi recusado. A segunda chamada só passa se o
# comando vier idêntico (normalizado) — assim o modelo não pode recusar um
# `winget install x` e voltar com `Remove-Item` + confirmado=true. Expira.
# ═════════════════════════════════════════════════════════════════

_lock_pendente = threading.Lock()
_pendente: Optional[tuple] = None   # (comando_normalizado, timestamp)


def _normalizar_para_comparar(cmd: str) -> str:
    return re.sub(r"\s+", " ", (cmd or "").strip()).lower()


def guardar_pendente(comando: str) -> None:
    global _pendente
    with _lock_pendente:
        _pendente = (_normalizar_para_comparar(comando), time.monotonic())


def consumir_pendente(comando: str) -> bool:
    """True se há confirmação válida PARA ESTE COMANDO exato."""
    global _pendente
    with _lock_pendente:
        if _pendente is None:
            return False
        cmd_guardado, quando = _pendente
        if time.monotonic() - quando > _EXPIRA_CONFIRMACAO:
            _pendente = None
            return False
        if cmd_guardado == _normalizar_para_comparar(comando):
            _pendente = None
            return True
        return False


def descartar_pendente() -> None:
    global _pendente
    with _lock_pendente:
        _pendente = None


_POWERSHELL_NO_LINUX = re.compile(
    r"\b(?:powershell(?:\.exe)?|pwsh|New-Item|Set-Content|Add-Content|"
    r"Get-ChildItem|Get-Content|Remove-Item|Start-Process|"
    r"Invoke-Expression|Invoke-WebRequest)\b|\b[A-Z]:[\\/]",
    re.IGNORECASE,
)
_SHELL_ESPECIAL = re.compile(r"[;&|<>`\n]|\$\(")
_INTERPRETADORES = frozenset({
    "bash", "sh", "zsh", "fish", "python", "python3", "perl", "ruby", "node",
    "env", "su", "sudo", "pkexec",
})
_GERENCIADORES = frozenset({"dnf", "dnf5", "apt", "apt-get", "yum", "pacman", "zypper", "snap", "rpm"})
_MUTACOES_PACOTE = frozenset({
    "install", "remove", "erase", "purge", "autoremove", "upgrade",
    "update", "reinstall", "downgrade", "full-upgrade", "dist-upgrade",
    "refresh", "dup",
})
_MUTACOES_SYSTEMCTL = frozenset({
    "start", "stop", "restart", "reload", "enable", "disable", "mask", "unmask",
    "poweroff", "reboot", "halt", "hibernate", "suspend",
})


def _precisa_admin_linux(primeiro: str, argumentos: list[str],
                         prefixo_elevado: bool = False) -> bool:
    subcomando = next((a for a in argumentos if not a.startswith("-")), "").lower()
    mutacao_por_flag = (
        (primeiro == "pacman" and any(a.startswith(("-S", "-R", "-U")) for a in argumentos))
        or (primeiro == "rpm" and any(a in ("-i", "-U", "-e") for a in argumentos))
    )
    return prefixo_elevado or mutacao_por_flag or (
        (primeiro in _GERENCIADORES and subcomando in _MUTACOES_PACOTE)
        or (primeiro == "systemctl" and "--user" not in argumentos
            and subcomando in _MUTACOES_SYSTEMCTL)
        or primeiro in {"shutdown", "reboot", "poweroff", "halt"}
        or (primeiro in {"timedatectl", "hostnamectl", "localectl"}
            and subcomando.startswith("set-"))
    )


def _preparar_linux(cmd: str):
    """Escolhe Bash comum ou autenticação gráfica para um comando administrativo simples."""
    if _POWERSHELL_NO_LINUX.search(cmd):
        return None, ("Este PC usa Linux; esse comando parece ser de PowerShell/Windows. "
                      "Refaça a ação com ferramentas de arquivo ou sintaxe Linux.")
    try:
        partes = shlex.split(cmd)
    except ValueError as e:
        return None, f"Comando incompleto: {e}"
    if not partes:
        return None, "O comando veio vazio."

    primeiro = os.path.basename(partes[0]).lower()
    prefixo_elevado = primeiro in {"sudo", "pkexec"}
    if prefixo_elevado:
        partes = partes[1:]
        if partes and partes[0] == "--":
            partes = partes[1:]
        if not partes or partes[0].startswith("-"):
            return None, "Use um único comando administrativo após sudo, sem opções de sudo."
        primeiro = os.path.basename(partes[0]).lower()

    argumentos = partes[1:]
    requer_admin = _precisa_admin_linux(primeiro, argumentos, prefixo_elevado)
    if not requer_admin:
        return [_SHELL, "-c", cmd], None
    if _SHELL_ESPECIAL.search(cmd) or primeiro in _INTERPRETADORES:
        return None, ("Para autenticação do Linux, envie uma única ação administrativa "
                      "direta, sem encadear comandos nem abrir outro shell.")
    autenticador = shutil.which("pkexec")
    executavel = shutil.which(partes[0])
    if not autenticador or not executavel:
        return None, ("Não encontrei o autenticador gráfico do Linux ou o comando. "
                      "Confira se pkexec e o programa estão instalados.")
    argumentos = [os.path.expanduser(a) if a == "~" or a.startswith("~/") else a
                  for a in argumentos]
    return [autenticador, executavel, *argumentos], None


# ═════════════════════════════════════════════════════════════════
# EXECUÇÃO
#
# Sem timeout: se o Vitor pediu, é pra terminar. O preço disso é um comando
# preso travar a thread da ferramenta para sempre — por isso existe
# cancelar_terminal(), que mata o processo ativo. A Emily roda as ferramentas
# fora do laço de fala, então um comando preso não congela a voz dela; só
# aquela ação fica pendurada até ser cancelada.
# ═════════════════════════════════════════════════════════════════

def _truncar(texto: str, limite: int = MAX_SAIDA) -> str:
    texto = (texto or "").strip()
    if len(texto) <= limite:
        return texto
    return texto[:limite] + f"\n... (saída truncada, {len(texto)} caracteres no total)"


_lock_processo = threading.Lock()
_processo_ativo: Optional[subprocess.Popen] = None


def cancelar() -> str:
    """Mata o comando em execução. Chamado pela ferramenta cancelar_terminal."""
    global _processo_ativo
    with _lock_processo:
        p = _processo_ativo
    if p is None or p.poll() is not None:
        return "Não tem nenhum comando rodando agora."
    try:
        if _E_LINUX:
            # SIGKILL no GRUPO inteiro: o bash pode ter filhos (instaladores etc.)
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        else:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        _log(f"cancelado pelo Vitor: pid {p.pid}")
        return "Comando interrompido."
    except (OSError, ProcessLookupError) as e:
        _log(f"falhou ao cancelar pid {p.pid}: {e}")
        return f"Não consegui matar o processo ({e}). Ele pode ter terminado sozinho."


def executar(comando: str, confirmado: bool = False, entrada: str = "",
             autorizacao_direta: bool = False, cancelar_evento=None):
    """
    Roda o comando ou explica por que não rodou.

    entrada — texto mandado ao stdin do processo. Existe pra comandos que
    PERGUNTAM algo durante a execução ("continuar? [S/N]"): a Emily
    chama de novo com o MESMO comando e a resposta aqui, em vez de travar.
    Nunca deve conter senha; autenticação administrativa no Linux usa pkexec.
    Só faz sentido quando o comando pergunta ANTES de fazer o trabalho pesado;
    os que perguntam no meio aceitam a resposta via prompt do próprio comando
    (ex.: winget tem --accept-source-agreements).

    Devolve (texto, ok). ok=False é recusa ou falha; o modelo recebe o texto
    completo e decide o que dizer ao Vitor.

    autorizacao_direta — sinal interno do executor: dono confirmado, autonomia
    experimental ligada e pedido explícito neste turno. Nunca libera BLOQUEADO.
    """
    cmd = (comando or "").strip()
    if not cmd:
        return ("O comando veio vazio. Peça ao Vitor o que ele quer executar.", False)

    if _E_LINUX and _POWERSHELL_NO_LINUX.search(cmd):
        return ("Este PC usa Linux; esse comando parece ser de PowerShell/Windows. "
                "Refaça a ação com ferramentas de arquivo ou sintaxe Linux.", False)

    nivel = classificar(cmd)

    if nivel == BLOQUEADO:
        _log(f"BLOQUEADO: {cmd[:120]}")
        descartar_pendente()
        return (
            "Esse comando foi bloqueado pela camada de segurança porque é "
            "irreversível ou pode danificar o sistema (formatação, registro, "
            "boot ou backup). Não existe confirmação que libere "
            "ele. Diga ao Vitor que isso precisa ser feito à mão, e NÃO tente "
            "variações do mesmo comando.",
            False,
        )

    if nivel == CONFIRMAR and autorizacao_direta:
        # O dono confirmou a intenção na própria ordem e habilitou o modo
        # experimental. Pula somente o vaivém; BLOQUEADO já retornou acima.
        descartar_pendente()
        _log(f"autorização direta do dono: {cmd[:120]}")
    elif nivel == CONFIRMAR and not confirmado:
        guardar_pendente(cmd)
        _log(f"aguardando confirmação: {cmd[:120]}")
        return (
            "Esse comando mexe no sistema de forma visível (instala/desinstala, "
            "matou processo, mexe em serviço ou apaga arquivo). NÃO execute de "
            "novo ainda. Explique ao Vitor o que o comando faz e pergunte se "
            "pode. Quando ele confirmar, chame de novo com o MESMO comando e "
            "confirmado=true.",
            False,
        )

    elif nivel == CONFIRMAR and confirmado:
        if not consumir_pendente(cmd):
            return (
                "Não tem confirmação válida para ESTE comando (expirou, já foi "
                "usada, ou o comando mudou desde a recusa). Refaça a consulta "
                "ao Vitor: explique de novo e espere ele confirmar antes de "
                "executar com confirmado=true.",
                False,
            )

    if cancelar_evento is not None:
        if cancelar_evento.is_set():
            return "Comando cancelado antes de iniciar.", False
        return _rodar_shell(cmd, entrada, cancelar_evento=cancelar_evento)
    return _rodar_shell(cmd, entrada)


def _rodar_shell(cmd: str, entrada: str = "", cancelar_evento=None):
    global _processo_ativo
    _log(f"executando: {cmd[:120]}")

    if _E_LINUX:
        # O pkexec mostra a autorização nativa do desktop quando a ação
        # precisa de privilégios. Nunca pedimos ou guardamos senha no chat.
        argv, erro = _preparar_linux(cmd)
        if erro:
            return (erro, False)
        extra = {"start_new_session": True}
    else:
        # -NonInteractive continua: o POWERSHELL HOST é quem não pode pedir nada
        # (senão fica esperando pra sempre). O programa DENTRO do comando pode
        # perguntar via stdin — isso é alimentado por 'entrada'.
        argv = [_POWERSHELL, "-NoProfile", "-NonInteractive", "-Command"]
        if entrada:
            argv.append(f"{cmd}\n$resp = [Console]::In.ReadToEnd()")
        else:
            argv.append(cmd)
        extra = {"creationflags": subprocess.CREATE_NO_WINDOW}

    try:
        processo = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if entrada else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **extra,
        )
    except FileNotFoundError:
        return (f"{argv[0]} não foi encontrado nesta máquina.", False)
    except OSError as e:
        return (f"Falha ao iniciar o shell: {e}", False)

    with _lock_processo:
        _processo_ativo = processo

    try:
        if cancelar_evento is None:
            stdout_bruto, stderr_bruto = processo.communicate(input=entrada or None)
        else:
            primeira = True
            while True:
                if cancelar_evento.is_set() and processo.poll() is None:
                    try:
                        if _E_LINUX:
                            os.killpg(os.getpgid(processo.pid), signal.SIGKILL)
                        else:
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(processo.pid)], capture_output=True)
                    except ProcessLookupError:
                        pass
                try:
                    stdout_bruto, stderr_bruto = processo.communicate(
                        input=(entrada or None) if primeira else None, timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    primeira = False
    except Exception as e:  # noqa: BLE001
        return (f"Falhou lendo a saída do comando: {e}", False)
    finally:
        with _lock_processo:
            if _processo_ativo is processo:
                _processo_ativo = None

    # communicate() fecha os pipes e devolve as duas saídas de uma vez — é
    # por isso que a leitura NÃO pode ser processo.stderr.read() depois dele.
    codigo = processo.returncode
    if _E_LINUX and os.path.basename(argv[0]) == "pkexec" and codigo != 0:
        erro_lower = (stderr_bruto or "").lower()
        if "must be setuid root" in erro_lower or "no authentication agent" in erro_lower:
            return ("A autenticação administrativa do Linux não está disponível "
                    "nesta sessão. A ação não foi executada. Verifique o pkexec "
                    "e o agente de autenticação do ambiente gráfico.", False)
        if codigo == 126:
            return ("A autenticação do sistema foi cancelada ou negada; "
                    "a ação não foi executada.", False)
    saida = ""
    stdout = _truncar(stdout_bruto or "")
    stderr = _truncar(stderr_bruto or "")
    if stdout:
        saida += stdout
    if stderr:
        saida += ("\n--- erros ---\n" + stderr) if saida else stderr
    if not saida:
        saida = "(o comando terminou sem imprimir nada)"

    prefixo = "" if codigo == 0 else f"[código de saída {codigo}]\n"
    return (prefixo + saida, codigo == 0)

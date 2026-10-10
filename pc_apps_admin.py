#!/usr/bin/python3 -I
"""Helper root restrito: remove UM aplicativo RPM/Flatpak, nunca comandos livres.

Instalar cópia root:root em /usr/local/libexec/emily-app-uninstall.
Não importar módulos do projeto nem executar código gravável pelo usuário como root.
"""
import json
import os
import re
import subprocess
import sys

PROTECTED = re.compile(r'^(?:kernel|systemd|glibc|rpm|dnf[0-9]*|libdnf[0-9]*|python3|sudo|polkit|pam|selinux|filesystem|setup|bash|coreutils|dbus|NetworkManager|plasma|kwin|sddm|gdm|fedora-release|grub|shim|dracut|cryptsetup|pipewire|wireplumber|emily)(?:$|[-.])', re.I)


def run(command):
    return subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)


def rpm_transaction(package):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.-]{0,160}', package) or PROTECTED.match(package):
        raise ValueError('Pacote protegido ou identificador inválido.')
    files = run(['/usr/bin/rpm', '-ql', '--', package]).stdout.splitlines()
    if not any(f.startswith('/usr/share/applications/') and f.endswith('.desktop') for f in files):
        raise ValueError('Somente aplicativos com lançador desktop podem ser removidos por este helper.')
    import libdnf5
    base = libdnf5.base.Base()
    base.load_config()
    base.get_config().get_clean_requirements_on_remove_option().set(False)
    base.setup()
    base.get_repo_sack().load_repos(libdnf5.repo.Repo.Type_SYSTEM)
    goal = libdnf5.base.Goal(base)
    goal.add_remove(package)
    transaction = goal.resolve()
    if transaction.get_problems():
        raise ValueError('O DNF não conseguiu resolver a remoção: ' + '; '.join(transaction.get_resolve_logs_as_strings())[:1200])
    changes = list(transaction.get_transaction_packages())
    # Verifique a MESMA transação que será executada, sem janela entre dry-run e execução.
    if not changes or any(p.get_package().get_name() != package or
            p.get_action() != libdnf5.transaction.TransactionItemAction_REMOVE for p in changes):
        raise ValueError('A remoção afetaria outros pacotes. Nenhuma alteração foi executada.')
    return base, transaction


def execute(kind, target, preview=False):
    if kind == 'rpm':
        base, transaction = rpm_transaction(target)
        if not preview:
            import libdnf5
            result = transaction.run()
            if result != libdnf5.base.Transaction.TransactionRunResult_SUCCESS:
                raise RuntimeError('Falha na transação DNF: ' + str(result))
        return {'ok': True, 'alvo': target, 'previa': preview, 'pacotes': [target]}
    if kind == 'flatpak-system':
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+){2,}', target):
            raise ValueError('Identificador Flatpak inválido.')
        installed = run(['/usr/bin/flatpak', 'list', '--system', '--app', '--columns=application']).stdout.splitlines()
        if target not in installed:
            raise ValueError('Aplicativo Flatpak não encontrado; runtimes não são alvos válidos.')
        if not preview:
            run(['/usr/bin/flatpak', 'uninstall', '--system', '--noninteractive', '--', target])
        return {'ok': True, 'alvo': target, 'previa': preview}
    raise ValueError('Tipo de aplicativo não permitido.')


if __name__ == '__main__':
    try:
        if len(sys.argv) not in (3, 4) or (len(sys.argv) == 4 and sys.argv[3] != '--preview'):
            raise ValueError('Uso: helper rpm|flatpak-system identificador [--preview]')
        # Ambiente conhecido; não aceitar configurações/plugins Python de quem chama.
        os.environ.clear()
        os.environ.update(PATH='/usr/sbin:/usr/bin', HOME='/root', LANG='C.UTF-8')
        print(json.dumps(execute(sys.argv[1], sys.argv[2], len(sys.argv) == 4)))
    except Exception as error:
        print(json.dumps({'ok': False, 'mensagem': str(error)[:1600]}))
        sys.exit(1)

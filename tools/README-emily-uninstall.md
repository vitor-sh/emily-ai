# Desinstalação estruturada no Fedora

O gateway continua com `NoNewPrivileges=true`. Não retire essa proteção para corrigir `pkexec must be setuid root`.

`pc_apps.admin_command` solicita ao gerenciador systemd do usuário um processo separado, com duração limitada, que chama exclusivamente o helper `/usr/local/libexec/emily-app-uninstall`. A elevação continua dependendo da regra polkit específica e da cópia root:root do helper; não autoriza shell/Python livres como root. O helper valida alvo, lançador e a mesma transação DNF executada, recusando remoção de outros pacotes.

O inventário contempla RPM com lançador, Flatpaks de usuário/sistema, jogos Steam e AppImages pessoais com lançador explícito. Nome aproximado ou duas instalações exigem escolha; pedidos simultâneos do mesmo aplicativo reutilizam o trabalho ativo. Transações dos gerenciadores de pacotes são serializadas. Falhas nunca são anunciadas como sucesso; o inventário é atualizado para conferir o resultado.

## Validação

- Testes: `python3 -m pytest -q testes/test_pc_apps.py testes/test_pc_control.py`.
- A prévia administrativa não remove nada: `pc_apps.output(pc_apps.admin_command('rpm', '<pacote instalado com lançador>', preview=True), timeout=30)`.
- Rode essa prévia também dentro de uma unidade de usuário com `NoNewPrivileges=true` e `PrivateTmp=true`, reproduzindo o ambiente do gateway. Um teste só no terminal interativo não detecta o bloqueio do serviço.
- Para o fluxo HTTP, use um AppImage descartável dentro do home e um lançador temporário: confira nome errado, cancelamento, remoção, inventário posterior e repetição do mesmo request_id. Não remova aplicativos pessoais para testar.

`pkexec` e a regra polkit precisam estar instalados; um ambiente sem systemd de usuário não tem este executor administrativo. Instalações manuais sem lançador e jogos internos de Wine/Bottles não são removidos por adivinhação.

# Agente visual e Android 55

## Mudanças
- Digitação usa colagem de Unicode no KDE Wayland em vez de mapa US do ydotool e envio por letra. Atalhos liberam os modificadores mesmo em falhas.
- Identificador de ação acompanha a sessão visual; uma tarefa nova do desktop não herda o identificador de uma tarefa Android anterior.
- Perguntas pendentes continuam salvas sem serviço de monitoramento ativo. Notificações novas permitem parar apenas o acompanhamento local, preservando a execução no PC.
- Configurações → Agente visual: provedor/modelo e raciocínio próprios, persistidos, utilizados nas decisões e na auditoria final. Os níveis seguem os suportados pela camada LLM.

## Validação
- KDE Wayland real: 6.720 caracteres com Unicode, emoji, símbolos e linhas; saída exatamente igual, envio em 0,625 s.
- 77 testes Python, contrato JS e verificação de sintaxe JS passaram; teste adicional do limite de SSH no publicador passou.
- 172 testes unitários Android passaram; build APK bem-sucedido.
- 3 testes no moto g22 passaram. Versão 55 instalada sem desinstalação. Assistente Emily e overlay preservados; serviço de wake word ativo, monitoramento antigo sem serviço ativo.
- Executável instalado do PC passou no preflight; módulos e assets conferidos por conteúdo.
- Código da Oracle publicado: e0eace9bbfbd1b56b2a4, com saúde de pesquisa e Discord confirmada.

## Estado preservado e limites
- Padrão visual mantido: Sol / Médio. Sem comparação de desempenho entre modelos; a escolha fica disponível para testes do usuário.
- Ensaio físico de teclado realizado neste Linux/KDE, sem máquina Windows para ensaio físico.
- APK 55 pronto e instalado; publicação do APK na Oracle aguardando restabelecimento do SSH na porta 22. HTTPS acessível. O publicador mantém manifesto anterior até confirmar o hash do novo APK.

O túnel SSH PC–Oracle também não está estabelecido durante esta indisponibilidade de porta 22. O publicador agora usa ConnectTimeout e ServerAlive para falhar em tempo limitado após desconexões. Não alterei as regras de rede da Oracle sem poder inspecionar o bloqueio.

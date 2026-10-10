# Privacidade — funcionamento e trabalho pendente

A Emily pode processar texto, áudio, imagens de tela, arquivos e mensagens das integrações habilitadas. Conforme a ferramenta/provedor escolhido, esse conteúdo pode ser enviado a serviços externos. A versão pública deverá explicar e pedir autorização antes de habilitar cada integração.

Memórias, preferências e históricos são dados do usuário e não fazem parte do código distribuído. A separação de todos os caminhos de dados e um fluxo consistente de exclusão ainda precisam ser validados em um perfil novo.

Esta exportação não contém os dados de execução do autor. Isso não significa que o runtime já passou por uma auditoria completa de privacidade. Logs, captura de tela, escuta de calls e integrações de nuvem são gates pendentes.

## Integrações opcionais no assistente público

Fish Audio recebe o texto das respostas para gerar voz. Groq recebe áudio capturado
pelo atalho de falar para transcrição. Discord usa um bot próprio, que responde a
menções apenas em canais autorizados, enviando essas mensagens ao provedor de IA.
Sem DMs, calls ou ações administrativas nesse bot público. As opções começam desligadas.

Credenciais são salvas em texto simples no arquivo local do perfil, com permissões
restritas quando suportadas. Não há armazenamento criptografado/keyring nesta etapa.
A interface não recupera as chaves salvas. Desativar e salvar remove a credencial
da configuração ativa; cópias de backup feitas pelo usuário não são apagadas.

Fish anuncia s2.1-pro-free até 30/11/2026, sujeito a uso justo; solicitações podem
ser utilizadas para melhorar o modelo. Não há substituição automática por modelo pago.
Verifique termos atuais em https://fish.audio/blog/s2-1-pro-free-api/.

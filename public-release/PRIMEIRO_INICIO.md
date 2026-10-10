# Primeira inicialização pública

## Abrir

Com as dependências da Emily instaladas, execute na pasta dos fontes:

```sh
python emily_public.py
```

Esta entrada é separada do `emily_bootstrap.py` pessoal. Um perfil novo abre o assistente; uma configuração concluída segue para a Emily sem repetir o assistente. Para revisar a conexão:

```sh
python emily_public.py --configurar
```

## Fluxo

1. **Olá:** nome/apelido, sem precisar criar conta Emily.
2. **Conexão:** OpenRouter, OpenAI, Ollama local ou servidor compatível (incluindo OmniRoute). Campo de chave escondido no modo local. Ajuda abre apenas os sites predefinidos. É possível buscar modelos ou digitar o nome; a conclusão exige testar o modelo selecionado.
3. **Revisão:** nome, provedor, modelo, explicação sobre uso/custos e confirmação. Depois de salvar, a pessoa escolhe abrir a Emily.

Microfone, notificações, Discord, túnel/servidor remoto, sincronização desktop, extensão de navegador e ponte de jogo não são iniciados automaticamente por essa entrada. A interface principal e os módulos continuam exigindo a revisão geral de permissões da release; isto não é uma sandbox completa de automação.

O visual usa cores escuras, verde neutro e laranja, animação leve de órbita, transições de etapas e progresso de conexão. Respeita redução de movimento, mantém as ações disponíveis na janela desktop e permite rolagem em janelas estreitas. Não carrega fontes ou arte da internet.

## Dados e credenciais

- Linux: `~/.config/emily-publica` (ou `XDG_CONFIG_HOME`).
- Windows: `%LOCALAPPDATA%/EmilyPublica`.
- `configuracao.json`: configuração e chave do usuário, com gravação atômica; não é criptografia. Não enviar esse arquivo em relatos de erro.
- `provedor.env`: seção de provedor sem a chave real. A chave é aplicada somente ao ambiente do processo.
- `dados/`: caminhos separados para preferências, conversas, memória clássica, configuração Discord e log desta entrada.
- `EMILY_PUBLIC_HOME` permite um perfil temporário para testes.

O assistente não lê o `.env` pessoal. A lista e os resultados enviados à interface não incluem a chave salva. Alterar servidor/modelo/chave exige novo teste. Reconfigurar pode manter a chave sem mostrar seu valor, somente se provedor e endereço forem os mesmos. Fechar antes de concluir não salva configurações novas.

Configuração ausente, corrompida ou de versão desconhecida abre novamente o assistente. Nenhum outro histórico é apagado por isso. Conexões remotas exigem HTTPS; HTTP só é aceito em loopback. Redirecionamentos não são seguidos para evitar envio de credenciais a outro endereço.

## Referências verificadas

- [Chaves e autenticação OpenRouter](https://openrouter.ai/docs/api_reference/authentication).
- [Onde obter a chave OpenAI](https://help.openai.com/en/articles/4936850-where-do-i-find-my-openai-api-key).
- [Compatibilidade OpenAI do Ollama](https://docs.ollama.com/api/openai-compatibility).

## Limites desta etapa

Foi testado o assistente em navegador Chromium e o backend/roteamento com um provedor HTTP local, sem gasto de API. Os modelos de contas reais, janela nativa WebView2/GTK, app completo em Windows/Linux limpos e instalação pública ainda precisam ser validados. Voz, escolha de dispositivos e onboarding das integrações adicionais permanecem para outra etapa.

## Voz, microfone e Discord opcionais

Na revisão final há três opções independentes. Cada pessoa usa suas próprias
credenciais, guardadas no perfil local com os mesmos cuidados da chave de IA.
Nenhuma chave do autor entra no pacote público.

- **Fish Audio:** criar conta em https://fish.audio/app/api-keys, gerar chave,
  colar e ouvir a amostra. ID não secreto da voz Emily já preenchido:
  `1d5c6866f45a44a3aa8df65061908ab2`. Outra voz pode ser escolhida pelo ID.
  A disponibilidade dessa voz em uma conta diferente precisa ser validada.
  O modelo é `s2.1-pro-free`, sem mudança automática para um modelo pago.
  SDK antiga que não aceite escolher o backend gera erro em vez de omitir o modelo.
  Conforme anúncio oficial consultado em 03/10/2026, gratuidade até 30/11/2026,
  sujeita a Fair Use, sem SLA; textos podem ser usados para melhoria dos modelos:
  https://fish.audio/blog/s2-1-pro-free-api/.
- **Groq/Whisper:** criar chave em https://console.groq.com/keys. O teste confere
  autenticação e disponibilidade de `whisper-large-v3-turbo`, sem gravar áudio.
  O áudio capturado pelo atalho de falar é enviado ao Groq. Validar dispositivo,
  permissões de captura/atalho e transcrição real antes da publicação.
- **Discord:** bot próprio via https://discord.com/developers/applications,
  convite com Ver canal e Enviar mensagens, IDs de até 20 canais escolhidos.
  Responde somente a menções ao bot nesses canais; sem DMs, voz ou administração.
  Usa intents mínimos, sem Message Content privilegiado. Mensagens dirigidas ao bot
  são enviadas ao modelo configurado. O teste confere somente o token de bot;
  convite/permissões e resposta real no servidor precisam de validação posterior.

Alterar chave, voz ou canais exige repetir o teste correspondente. Desativar uma
opção remove suas credenciais do perfil na próxima gravação. Reabrir com
`python emily_public.py --configurar` mantém chaves sem devolvê-las à interface.
As integrações rodam somente enquanto a Emily pública estiver aberta.

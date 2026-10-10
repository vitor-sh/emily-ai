# Emily na Oracle

## O que funciona sem o PC

- Pesquisa web do Android pela ponte HTTPS `https://emily-hiucksam.duckdns.org/bridge`, usando Brave na Oracle.
- Bot original do Discord: mensagens, directs, ferramentas administrativas e calls, incluindo Fish Audio, Groq, processamento de áudio e memória.
- Embeddings da memória com Ollama e `embeddinggemma` na própria VM.

O bot roda no serviço `emily-cloud.service`; a ponte usa `emily-relay.service`. Ambos iniciam com a VM. As APIs internas escutam somente em localhost e exigem autenticação. O painel do OmniRoute continua acessível pelo túnel administrativo já configurado no PC.

## Atualizações locais

O serviço de usuário `emily-cloud-publish.service` observa este projeto. Após aproximadamente 15 segundos sem novas alterações, publica o código e as configurações selecionadas. O PC precisa estar conectado para publicar; o bot já publicado continua funcionando quando o PC é desligado.

Antes da troca, o publicador valida a sintaxe, prepara as dependências e executa um ensaio de inicialização. A publicação troca o diretório ativo atomicamente, reinicia os serviços e verifica a versão e a conexão do Discord. Se a ativação falhar, restaura a versão e as configurações anteriores. Mudanças em `requirements.txt` usam outro ambiente Python para preservar as dependências da versão anterior.

Uma atualização interrompe brevemente a call. O bot salva o canal, reconecta e retoma a escuta após reiniciar, conforme a preferência escolhida. Uma saída explícita da call limpa esse estado.

Comandos úteis no PC:

```bash
systemctl --user status emily-cloud-publish.service
journalctl --user -u emily-cloud-publish.service -n 30
systemctl --user stop emily-cloud-publish.service
systemctl --user start emily-cloud-publish.service
```

Na Oracle, a implantação fica em `/home/ubuntu/emily-runtime-cloud`: `current` aponta para uma versão em `releases`, `venvs` guarda ambientes adicionais e `data` guarda os dados persistentes. O diagnóstico privado de implantação fica em `data/last-deploy.log`. O publicador não sobrescreve a memória a cada atualização nem substitui a preferência de escuta alterada na nuvem.

## Dados e credenciais

O histórico existente e a memória foram copiados na migração inicial. Novas memórias, histórico de directs e estado das calls persistem na Oracle entre atualizações. Ainda não há sincronização automática das novas memórias da Oracle de volta ao PC.

Credenciais ficam nos diretórios privados `~/.config/emily-runtime-cloud` na Oracle e `~/.config/emily-cloud-oracle` no PC, com acesso restrito. Não publique esses arquivos nem inclua seus valores em capturas. A chave administrativa da ponte não é entregue ao Android.

## Limites desta migração

Ferramentas que controlam o desktop, agente visual, jogos e arquivos locais continuam exigindo o PC conectado e a Emily aberta. O bot encaminha essas ações ao PC e informa quando ele está indisponível. Esta mudança não migra o WhatsApp nem outros instaladores/cópias do projeto.

A VM E5 continua usando os créditos do trial: a migração para um recurso Always Free ainda precisa acontecer antes do fim do trial para manter essa hospedagem sem custo.

## Dependências de execução

Python e bibliotecas estão em `requirements.txt`. A VM também usa FFmpeg, Opus, PortAudio e Chromium do Playwright. O serviço inicia por `launch.py`, que escolhe o ambiente Python correspondente à versão publicada.

O container `emily-embeddings` usa `ollama/ollama:0.33.3`, reinicia automaticamente, tem limite de 1 CPU e 2 GB de RAM e publica a porta 11434 apenas em `127.0.0.1`. Seu volume é `emily-embeddings`; o modelo instalado é `embeddinggemma`. Ele não requer uma segunda VM.

## Validação realizada

Pesquisa real pelo Android com o túnel do PC desligado; respostas reais pelos fluxos de chat e direct; síntese Fish e transcrição Groq sem reproduzir áudio; embeddings locais à Oracle; entrada em canal de voz vazio, escuta com DAVE e reconexão ao mesmo canal após uma publicação automática. Nenhuma mensagem de teste foi enviada a terceiros.

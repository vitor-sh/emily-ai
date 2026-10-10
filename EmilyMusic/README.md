# Emily Music — aplicativo Android independente

Projeto próprio, applicationId `com.emily.music`, versão 0.1.6.
Instala junto com `com.example.emilyapp`; não substitui a Emily e não usa sua
ponte pessoal, assistente, microfone, overlay, TV, acesso remoto ou chaves de IA.

## Configuração e build

- `local.properties`: somente `sdk.dir` e `MUSIC_CLOUD_URL`.
- `app/google-services.json`: registrar este pacote no Firebase
  `emily-assistente`, SHA da assinatura instalada e cliente OAuth web.
  Arquivo de configuração é ignorado no Git; não copiar o registro da Emily.
- Servidor de buscas existente: Cloudflare Workers com allowlist Firebase.
- `./gradlew :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest`
- APK em `app/build/outputs/apk/debug/app-debug.apk`, destinado a testes locais.

As dependências mantidas são Compose, Firebase Auth/CredentialManager, Media3,
WorkManager, WebKit, DocumentFile, OkHttp e extrator/FFmpeg. Nenhuma credencial de
modelo de IA é gerada no BuildConfig. O launcher usa arte própria gerada: nota musical laranja fundida ao perfil
abstrato da Emily, fundo preto, recursos adaptativos e monocromáticos.

## Isolamento por conta

Cada UID Firebase recebe diretório SHA-256 estável próprio:

- `files/accounts/<hash>/library.json` — playlists, curtidas e configurações;
- `files/accounts/<hash>/player.json` — fila e posição;
- `files/accounts/<hash>/covers/` — capas;
- `files/Music/Emily Music/<hash>/` no armazenamento externo privativo — áudios;
- `cache/music-stream/<hash>/` — cache temporário da reprodução.

Histórico de busca recebe prefixo de conta no armazenamento WebView. URLs de
capas incluem conta e o handler WebView atende somente a pasta da conta ativa.
Downloads WorkManager recebem UID, nome único e tag por conta; só executam na
conta aprovada que os enfileirou. Estado da fila é filtrado por conta.

Cada biblioteca tem instância, jobs e observador próprios. Ao fechar, callbacks
atrasados não alteram a instância de uma outra conta. Logout interrompe áudio,
cancela downloads, limpa caches em memória e encerra a biblioteca. Os dados da
conta são preservados para a próxima entrada. A tela de entrada não compõe o
player nem a biblioteca antes da aprovação pelo servidor. Auto-backup Android
desativado para não copiar dados autenticados indiscriminadamente.

“Músicas locais” continua sendo inventário dos MP3 públicos do aparelho que o
Android autorizou o aplicativo a ler; não representa arquivos privados de outra
conta. Downloads e cópias importadas ficam na pasta privativa de cada conta.

## Cópia pessoal inicial, por ADB

`tools/migrate_personal_library.py export --serial SERIAL` exporta somente os
dados Music da Emily original, identificando a conta Google aprovada. Guarda um
snapshot privado e ignorado no Git em `.private-migration/`; não exporta tokens,
conversas nem credenciais de IA. `import` copia para o hash dessa conta no app
novo, verificando SHA-256 arquivo a arquivo. Recusa sobrescrever biblioteca já
existente. Não instala/desinstala aplicativos e não altera o original.

A importação mantém playlists, curtidas e configurações. Não transfere a fila
ativa, os grants Android de pastas nem o histórico WebView antigo. Músicas
locais públicas são reindexadas após a permissão de áudio no novo app; permissões
para árvores de arquivos precisam ser concedidas novamente.

## Antes de distribuição

Ainda pendentes: assinatura de release preservada, rotação da
chave YouTube antiga, sincronização de biblioteca/MP3 por UID na nuvem, contas de
convidados e validação prolongada em outros aparelhos. A busca já usa a nuvem;
a biblioteca desta etapa é persistida localmente por conta e não é sincronizada
com a ponte pessoal. Não distribuir o APK completo da Emily.

## Validação do aplicativo separado — 2026-10-02

Build debug 0.1.1 concluído, 8 testes unitários sem falhas. Instalado pelo ADB
com install -r, sem remover nem limpar a Emily original (versão 41).
Cinco testes instrumentais passaram no Moto G22 Android 12: apresentação da
entrada, isolamento de duas bibliotecas/arquivos/checkpoints, persistência de
checkpoint, reprodução silenciosa com tela apagada e encerramento do áudio pelo
logout, busca autenticada e reutilização de URLs/resultados.

Login Google real confirmado pelo proprietário. Cópia pessoal verificada:
6 playlists, 25 registros de músicas e 2 curtidas, preservando os campos da
biblioteca original; 21 arquivos de capa conferidos por SHA-256. Permissões de
pastas do aplicativo antigo não são transferíveis e precisam de nova concessão.

Medição única de rede: busca inicial 1.071 ms, cache 2 ms; extração inicial da
URL de áudio 14.827 ms, cache 1 ms. Isso mede obtenção da URL, não áudio audível.
A extração inicial continua sendo uma limitação. APK de aproximadamente 76 MB;
verificação dos arquivos confirmou ausência das chaves pessoais de IA e da
chave YouTube atual. Ícone temporário usado nesta validação, substituído na versão 0.1.3.

Esta etapa separa o aplicativo e a persistência local por UID. Sincronização
cloud de biblioteca/MP3, liberação de convidados, assinatura de distribuição e
validação em outros aparelhos continuam pendentes. Não publicado no updater
da Emily, pois o pacote independente é diferente.

## Ícone definitivo — Emily Music 0.1.2

Arte original gerada pela ferramenta built-in image_gen, usando o retrato da
Emily somente como referência de identidade. Nota musical alaranjada integrada
a cabelo e perfil em negativo, fundo escuro separado da camada transparente.
Original, preview e prompt em EmilyMusic/output/imagegen/. Android recebe ícone
adaptativo (API 26+), monocromático (API 33+) e recursos de densidade para fallback.

Build e 8 testes unitários passaram. APK 0.1.2 instalado com install -r e aberto
no aparelho; aprovação do login preservada. A Emily original permanece instalada
sem mudanças. Os cinco testes instrumentais da separação passaram na 0.1.1;
a alteração 0.1.2 troca somente recursos do launcher e versão.

## Reprodução rápida (0.1.3)

NewPipeExtractor v0.26.5 obtém somente metadados de áudio direto AAC/m4a original,
sem abrir Python. As chamadas rodam fora da UI, com timeout global de 8 segundos
e cancelamento de requisições OkHttp. yt-dlp permanece como fallback; falha no
integrado suspende tentativas nele por 60 segundos, evitando repetir o custo em
cada clique. Endereço recusado por HTTP força fallback naquela faixa por 15 min.
Não são usadas APIs de IA nem um servidor adicional de áudio.

Resoluções da mesma faixa compartilham trabalho. Clique em faixa diferente cancela
trabalhos especulativos; fim de sessão/conta cancela jobs e impede resultados tardios
na próxima conta. Cache em memória limitado a 64 URLs, com vencimento verificado.
Ao abrir playlist/curtidas ou resultados de busca, prepara até duas URLs, uma por
vez, em Wi-Fi validado e sem cobrança por uso. Não baixa áudio nesse processo;
sair da tela ou ficar offline cancela essa preparação. A próxima faixa da fila
mantém sua preparação existente, agora subordinada à prioridade do clique.

NewPipeExtractor usa GPL-3.0-or-later. Avisos e cópia da licença em
THIRD_PARTY_NOTICES.md e licenses/. As obrigações de redistribuição devem ser
cumpridas no empacotamento público junto das dependências existentes.

## Android independente 0.1.3 — obtenção rápida do áudio

Adicionado NewPipeExtractor v0.26.5 integrado ao Android, somente metadados de
áudio original AAC/m4a progressivo; yt-dlp continua como alternativa automática.
Timeout/cancelamento de chamadas, circuito de espera de 60 s após falha do
integrado, invalidação para yt-dlp após rejeição HTTP e cache de 64 endereços com
vencimento. Resoluções por faixa compartilham trabalho; clique cancela trabalhos
especulativos diferentes. Limpeza de conta impede publicação de resultados
atrasados. Sem nova hospedagem de áudio.

Playlist/curtidas e busca preparam até duas URLs sequencialmente, somente em Wi-Fi
validado e não tarifado, sem baixar áudio. Saída da tela/offline cancela o preparo.
Próxima música da fila usa a mesma prioridade. Os trabalhos rodam fora da UI.
Documentação/avisos de licença GPL-3.0-or-later do NewPipe incluídos no projeto.

Validação no Moto G22: 11 testes unitários passaram; comparativo de reprodução,
fluxo WebView/botão/preparação, checkpoint, tela apagada/encerramento e alternativa
após rejeição passaram (cinco testes instrumentais distintos; teste de UI repetido
na compilação final). Sintaxe JavaScript verificada. Medições sem cache de bytes,
com áudio silencioso e duas faixas da biblioteca, do comando Media3 até isPlaying:

| Caso | yt-dlp | integrado |
| --- | --- | --- |
| Faixa 1 | 19.736 ms | 4.132 ms |
| Faixa 2 | 16.087 ms | 3.075 ms |

Média 17.911,5 ms vs 3.603,5 ms (aprox. 80% menor). URL previamente preparada:
1.124 ms até reprodução, resolução 2 ms. Pela WebView/botão verdadeiro da biblioteca,
preparo automático confirmado (resolução 5 ms); 2.116 ms até isPlaying, e 1.120 ms
na repetição final. O teste usa clique programático no botão e áudio com volume
zero; não mede reação humana nem saída acústica. Amostra pequena, rede variável.

Após invalidar o endereço como rejeitado, o caminho yt-dlp foi selecionado e retornou
bytes de áudio válidos: 19.237 ms para resolução + primeiros bytes. A alternativa
continua lenta; resultado principal não garante início instantâneo em toda faixa.

APK 0.1.3 instalado via install -r. Biblioteca, conta e Emily original preservadas.
Não alterados nesta tarefa: Music embutido na Emily original/PC, armazenamento
cloud/sincronização de biblioteca, e extração dos downloads offline, que mantém
seu fluxo atual. O foco foi a reprodução no aplicativo Android independente.

## Configurações discretas (0.1.4)

A engrenagem do cabeçalho abre um painel nativo escuro com a conta Google,
versão e ação Sair da conta. O antigo cabeçalho extra de logout foi removido.
O painel fecha pelo botão/gesto Voltar sem desconectar; o botão de saída fica
indisponível enquanto processa e mostra erro se a operação falhar.
As leituras periódicas do MediaController e atualizações da WebView são
explicitamente encaminhadas à thread principal.

Validação: assembleDebug e assembleDebugAndroidTest concluídos; dois testes
no Moto G22 passaram (painel/estado ocupado e ponte real engrenagem → painel →
Voltar, preservando UID). Aparência conferida por captura no aparelho.
APK instalado com adb install -r, preservando biblioteca e login.
O fluxo de autenticação, a Emily original e o PC não foram alterados nesta etapa.

## Contas, nuvem e atualizações (0.1.6)

Qualquer conta Google verificada pode entrar. O Firebase cria o UID e cada
aparelho mantém uma pasta própria para essa conta; não há cadastro por aparelho.
Playlists, curtidas, capas e preferências são mescladas no D1 por UID. Exclusões
são tombstones; conflitos usam timestamp/id, com CAS no servidor. Alterações
locais ficam pendentes se offline e são reenviadas quando a sessão volta à rede.
A sincronização é periódica (15 s com o Music aberto) e após alterações (800 ms).
Sem mudanças, enviam-se somente revisão e campos novos; capas grandes viram
miniaturas para a nuvem. Fila, posição, downloads, pasta Músicas locais e MP3s
não são transferidos. Metadados de MP3s adicionados/curtidos sincronizam, mas o
áudio continua no aparelho de origem. A Emily/PC original não participa desse
serviço de contas independente.

### Distribuir

Compartilhar https://github.com/vitor-sh/emily-music-releases/releases/latest .
A pessoa instala uma vez e entra com sua própria conta Google. Android 8+,
ARM de 32 ou 64 bits; APK release não depurável. Não usar APKs da Emily principal.
A chave privada foi congelada em .signing/music.keystore, mantendo a assinatura
já registrada no Firebase e a compatibilidade com o app instalado. Faça um backup
privado dessa pasta: ela é necessária para publicar atualizações compatíveis.
Nunca enviá-la ao GitHub nem incluí-la no pacote-fonte.

### Publicar nova versão

Criar um Markdown com as notas, depois:

```sh
python3 scripts/publish.py --notes /caminho/notas.md
```

O script incrementa version.properties, testa/compila, empacota somente o código
limpo do Music e a fonte do extrator, publica no GitHub, confere o arquivo público
e atualiza o metadado no Worker. A opção --version permite escolher o próximo
número; nunca reutilizar uma versão já publicada. --package-only cria os arquivos
sem publicar. Credenciais GitHub CLI/Wrangler ficam no armazenamento das ferramentas,
não no repositório, APK ou fonte publicada. Configurações privadas são excluídas.
O cliente é distribuído sob GPL-3.0-or-later; COPYING e avisos acompanham o código.

O app verifica ao iniciar e a cada 12 h pelo WorkManager, em rede sem cobrança
por dados. Configurações permite verificar manualmente em qualquer conexão.
Valida HTTPS/origem, tamanho, SHA-256, pacote, versão e assinatura antes de oferecer
instalação. Downloads incompletos nunca são instalados. O Android pede autorização
para instalar atualizações na primeira vez e confirmação em cada instalação.
A reprodução e biblioteca não são apagadas por uma atualização.

### Validação

16 testes Node passaram; fixture D1 real verificou concorrência, separação de UIDs
e revisões sem alterações. 11 testes JVM passaram. Testes no Moto G22 verificaram
backup real da conta, restauração em perfil local vazio simulando outro aparelho,
recusa de UID diferente no cliente, painel de configurações e retorno sem logout.
O APK público teve hash conferido após upload; assinatura mantém o SHA-1 registrado
no Firebase, e a compilação release é não depurável. O app baixou e validou a versão
publicada a partir da versão 0.1.5. Login de um amigo real e outros modelos de
celular ainda precisam ser validados na beta.

Validação final: instalação pelo próprio Music confirmada pelo usuário; dumpsys
confirmou versão 0.1.6 e ausência de DEBUGGABLE. Captura mostrou a biblioteca
preservada e sincronizada após instalação. O perfil vazio de teste restaurou
playlists/curtidas da conta real. Fontes da dependência youtubedl-android 0.18.1,
com instruções de compilação do FFmpeg, também acompanham a publicação.

## 0.1.7 — importação por link

Convite dispensável na tela inicial e acesso permanente em Configurações → Importar playlists. Spotify público experimental até 100 músicas, com conferência da quantidade e revisão das versões encontradas no YouTube; YouTube Music público/não listado até 200 músicas. Apenas a confirmação cria a playlist, com gravação atômica, deduplicação e sincronização normal da conta. Testes no aparelho: Spotify 32/32, YouTube Music 21/21, rejeição de leituras incompletas e importação isolada sem alterar a biblioteca pessoal.

## 0.1.8 — busca e histórico de audições

Busca confirmada, correção de espaços, painel “Adicionar músicas” nas playlists, resultados sem menu redundante e descoberta em Início/Biblioteca. Contadores individuais de aparelhos sincronizados por conta; 200 faixas recentes por aparelho. Reprodução de fundo contabilizada no serviço, após tempo efetivamente tocado. Sem reconstruir audições anteriores à atualização.

## Ícone aprovado — 0.1.21

Perfil simbólico da Emily com fones, nota e contorno neon alaranjado.
A arte aprovada está em design/icon-variants/emily-music-symbolic-neon-v1.png.
`python3 scripts/package_icon.py` prepara os recursos adaptativos, monocromáticos,
redondos, todas as densidades e a identidade do cabeçalho. Prévia em
output/imagegen/emily-music-icon-preview.png. As notificações mantêm a nota
monocromática simples para legibilidade no tamanho exigido pelo Android.

## 0.1.22 — retomada após falhas de reprodução

Uma falha de fonte pode deixar o Media3 em STATE_IDLE. Próxima/anterior agora
preparam novamente o player quando a intenção continua sendo tocar; a pausa
explícita é preservada. Transições por MediaController também recebem essa
recuperação, cobrindo controles externos sem depender da WebView. O comando de
play/pausa do app é decidido no serviço, evitando decisões por um snapshot até
500 ms atrasado; play no fim da fila reinicia a faixa atual.

Exceções dos extratores são convertidas em IOException identificável, permitindo
usar a recuperação existente (até três tentativas, canceladas por pausa/troca).
Cancelamentos continuam como InterruptedIOException. HTTP 429/5xx são
recuperáveis; recusas permanentes não geram um novo ciclo de tentativas após as
renovações limitadas do DataSource. O aviso mostra a reconexão em andamento e é
limpo quando o áudio volta.

Validação: 37 testes JVM e seis instrumentais passaram na release instalada
0.1.22. A fonte de teste ausente reproduziu o estado de erro; próxima/anterior
pela ponte e próximo por MediaController voltaram a tocar sem outro clique.
Estado visual deliberadamente desatualizado não impediu retomada com um toque;
fim da fila reiniciou corretamente. Sequencial, aleatório, edição de fila,
repeat-all, repeat-one e fila com IDs YouTube passaram no serviço real.
O teste aleatório antigo assumia que índice zero teria sucessor; corrigido para
começar no primeiro elemento da ordem embaralhada. Áudio dos testes silencioso;
fila/checkpoint/volume/modos originais restaurados e dados preservados.

Limites: não houve acesso aos logs do celular do pai nem teste no carro real.
Faixas com IDs YouTube podem usar arquivos locais/cache na validação; isto não
é uma medição de confiabilidade da rede ou do YouTube. Não alterados: wake word,
Emily principal/PC, modelos/extratores usados, conta, playlists e downloads.
Documentação Media3: https://developer.android.com/media/media3/exoplayer/listening-to-player-events

## 0.1.23 — Android Auto com Início/Voltar

Interface própria para hosts Car App API 8 e distribuição aceita pelo Android Auto (o APK direto não é liberado pela opção Fontes desconhecidas para Car App Library): Início/Voltar, coleções, busca na
biblioteca, fila e player. Erros de reprodução mantêm navegação e oferecem retry.
O player da sessão também recupera fontes paradas por Play/seek externo e publica
erros legíveis na integração anterior, que foi preservada. Wake mode de rede
mantém reprodução em segundo plano. Ambas as buscas mostram spinner acessível.

37 testes JVM e 11 instrumentais passaram (teste de busca repetido com correção
do harness). Não houve acesso ao carro real/logs do pai. Detalhes e limites em
output/validation/car-0.1.23.md; configuração em ANDROID_AUTO.md.


## 0.1.24 — integração tradicional por APK

A interface gratuita anuncia Biblioteca, Curtidas, Baixadas e No celular, com
ícones; Biblioteca reúne Todas as músicas e playlists com capas e contagem de
faixas disponíveis. Busca normaliza acentos e maiúsculas e não duplica faixas.
Custom browse actions anunciam Início, Voltar e Em reprodução nas listas,
devolvendo destinos de navegação sem alterar áudio. Exibição e posição dependem
do host; não há promessa de cabeçalho próprio no player tradicional.

O guia ANDROID_AUTO.md descreve a diferença entre instalar a integração tradicional
por APK e distribuir a interface Car App Library por uma fonte confiável.


## 0.1.25 — apresentação no carro

Abas com vetores android.resource, cartões com capas de 512 px e colagens geradas
quando não existe capa escolhida. Capas locais são servidas por content URIs
protegidas e autorizadas para o controlador conectado; cache e download ocorrem
fora da interface. Cartões têm somente o título e a seleção padrão vazia não
ocupa espaço quando há outras playlists. Layout final permanece com Android Auto.

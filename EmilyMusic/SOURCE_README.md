# Emily Music for Android

Android music client, licensed GPL-3.0-or-later. See COPYING and THIRD_PARTY_NOTICES.md.
This source package contains the standalone Music client and its build scripts.
It excludes signing certificates, credentials, Firebase project configuration and user data.

## Build

Use Android Studio or JDK 21 and Android SDK 36.1. Set sdk.dir in local.properties.
Register your own com.emily.music application in Firebase Authentication (Google),
add its signing SHA-1 and place the public Android google-services.json under app/.
Set MUSIC_CLOUD_URL to your compatible HTTPS search/library/update API.
Run ./gradlew assembleDebug. Gradle resolves the pinned dependencies from repositories
configured in settings.gradle.kts. For release signing, provide your own private
.signing/music.keystore and .signing/signing.properties (storePassword, keyPassword,
keyAlias). Never publish those files. Your signature will differ from official builds.

Official binaries and corresponding source: https://github.com/vitor-sh/emily-music-releases
Search requires an authenticated Google account; playback/downloads happen on-device.
Cloud synchronization stores playlists, likes and preferences under each Firebase UID.
Audio files and playback positions remain on-device.

Dependencies: NewPipeExtractor v0.26.5 (GPLv3), youtubedl-android 0.18.1,
yt-dlp and FFmpeg; AndroidX, Media3, Compose, Firebase, OkHttp and Kotlin.
See dependency manifests and the accompanying notices/source archives.

## Importação experimental de playlists (0.1.7)

O convite da página inicial usa os logos oficiais para identificar Spotify e
YouTube Music. Pode ser dispensado por conta/aparelho; “Importar playlists”
permanece nas configurações.

- Spotify: link HTTPS de playlist pública em open.spotify.com, até 100 entradas.
  A página e o embed precisam confirmar a mesma quantidade. Não usa API key,
  Premium, cookies, login Spotify ou prévias de áudio. Mudanças nas páginas,
  faixas restritas ou listas maiores podem impedir a importação.
- As versões para ouvir são procuradas no YouTube pelo NewPipeExtractor no
  aparelho. Título, artista, duração e indicadores de versões diferentes ajudam
  a sugerir candidatos, mas o usuário deve revisar. Correspondência não é
  garantia de gravação idêntica. Busca sequencial com progresso e cancelamento;
  falhas permitem continuar sem repetir as faixas já pesquisadas.
- YouTube Music: link compartilhável de playlist pública ou não listada (PL...),
  até 200 entradas, com paginação. Mixes, curtidas privadas, playlists privadas
  e listas cuja quantidade não possa ser confirmada não são aceitos.
- Confirmação cria uma nova playlist somente com as músicas marcadas. Faixas
  duplicadas da mesma versão são reunidas e informadas. A origem não é alterada.
  A gravação é atômica e tem recibo por operação para impedir duplicação em retry.
  Playlist/curtidas usam a sincronização existente; áudio/downloads continuam locais.
- Nunca inclui credenciais ou conteúdo de biblioteca pessoal nos pacotes de fonte.
  Os testes de rede aceitam link e quantidade via argumentos da instrumentação.

Validação em 2026-10-03: leitura real Spotify 32/32, busca de versões no YouTube,
playlist YouTube 21/21; quatro testes Android de leitura/validação/importação
isolada passaram. A interface real também passou pela prévia via ponte nativa,
abertura pelas configurações, dimensões e fechamento, preservando a conta.
Nenhuma música foi importada na biblioteca pessoal nos testes.

## 0.1.8 — busca e descoberta

A busca é confirmada pelo usuário; os campos não disparam consultas ao digitar. `playlist-search.js` fornece busca vinculada a uma playlist com identidade fixa, cancelamento de respostas antigas e proteção contra duplicatas. As opções dos resultados foram reduzidas ao botão de adicionar.

`MusicListeningTracker` mede tempo efetivamente tocado no serviço Media3 (10 segundos; metade de faixas menores que 20 segundos, mínimo 1 segundo). Cada aparelho mantém um identificador persistente e publica um campo `listening` com contadores próprios, limitado às 200 faixas recentes. A agregação soma contadores dos aparelhos e ordena pela última audição, sem misturar a reprodução ou os downloads. Esses novos campos exigem o backend atualizado; versões antigas ignoram os dados sem perder playlists. O histórico começa nesta atualização. Nomes de artistas/canais vêm de metadados disponíveis, sem inferência por título.

Testes: JVM de tempo tocado/pausa/repetição; validação e merge de campos no servidor; persistência e soma de aparelhos em perfil de teste isolado; teste no WebView real de rascunhos, espaços, confirmação, destino, duplicatas e layout das novas seções. Nenhuma música de teste é adicionada à biblioteca pessoal.

## 0.1.9 — busca principal no aparelho

A pesquisa de músicas agora usa NewPipeExtractor no aparelho, com cache local
por sessão/conta. Links e IDs de vídeos também usam esse caminho. A tentativa
principal tem prazo de oito segundos, com cancelamento das requisições nativas;
falha ou timeout aciona a API autenticada anterior como reserva. Resultados
vazios válidos não gastam uma chamada de reserva. Cancelamento e troca de conta
interrompem o fluxo e impedem que respostas antigas sejam reaproveitadas.

As pesquisas bem-sucedidas pelo caminho principal não consomem a cota da API
oficial. Isso não significa serviço ilimitado: o YouTube pode bloquear ou alterar
a extração, e a reserva mantém suas cotas e proteções. Login, biblioteca,
sincronização e atualização continuam usando a infraestrutura existente.

## 0.1.10 — importação automática e pendências

Colar um link completo inicia a leitura após um pequeno intervalo; o botão é
apenas uma alternativa. A importação procura correspondências, salva a playlist
com o nome e a capa disponíveis e abre a biblioteca automaticamente. Se o nome
já existir, cria uma cópia numerada, preservando a anterior. Cancelar durante a
busca não cria uma playlist. O recibo da gravação impede duplicação em retry.

Spotify: primeiro procura no catálogo musical do YouTube Music; se nenhuma
versão passar nos critérios de título, artista, duração e versão, tenta duas
consultas alternativas. Há no máximo duas faixas sendo pesquisadas ao mesmo
tempo. Covers, remixes e outras versões incompatíveis permanecem pendentes.
Só correspondências confiáveis entram automaticamente; isso não é prova de que
a gravação seja idêntica. A leitura pública continua aceitando até 100 faixas
e exige a lista completa; o limite não foi removido sem uma fonte paginada.

As faixas restantes ficam em `pending` nos metadados da playlist, com título,
artistas, duração e ID Spotify, sem credenciais. A API valida até 100 pendências
por playlist. O usuário pode tentar novamente ou escolher uma versão entre as
candidatas. Resolução repetida não duplica a música. Editar capa ou renomear não
apaga pendências. O backend precisa aceitar esse campo antes da distribuição;
clientes anteriores continuam lendo playlists/faixas, mas não exibem pendências.

A tela usa um único contêiner de rolagem, progresso fixo, animações com respeito
à preferência de movimento reduzido e estados sem caixas de seleção.

## 0.1.23 — Android Auto com navegação própria

Car App Library 1.7.0/app-projected e AndroidX Media 1.7.0 (Apache-2.0).
Host mínimo Car App API 8; o MediaLibraryService existente permanece disponível.
Início/Voltar, player, fila, coleções e busca na biblioteca; páginas no mesmo nível
mantêm a pilha até cinco telas. A autorização da conta e o serviço de áudio são
os mesmos do telefone; a sessão do carro libera callbacks/controlador ao fechar.
Um ForwardingSimpleBasePlayer localiza o erro e fornece tentativa de recuperação,
e prepara fontes paradas ao receber Play/seek por controles externos.

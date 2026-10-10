# Emily Music: desktop e Android

## Interface e áudio

`preparar_music_android.py` extrai o player e o modal de `web/app.js` e
`web/index.html`, e copia o CSS/JS compartilhado para os assets Android.
O publicador Android executa esse preparo antes da compilação.
`native-player.js` substitui a reprodução YouTube por comandos Media3;
`EmilyMusicService` mantém áudio, fila, repetição, cache de streaming e sessão
fora da Activity/WebView. A notificação usa título/capa e controles de mídia.
O cache de streaming é temporário (256 MB); downloads explícitos são separados.

## Biblioteca e sincronização

`music_sync.py` e `EmilyMusicLibrary.kt` replicam campos de playlist, faixa,
favorito, ordem, foto, volume, repetição e aleatório. Cada campo tem revisão
em milissegundos e ID de desempate; vence a edição mais recente daquele campo.
Exclusões são tombstones e não ressuscitam ao receber cópias antigas.
As mudanças persistem offline, com reenvio a cada cinco segundos.
Posição, fila em execução, seleção local e downloads não são replicados.
A biblioteca desktop usa gravação atômica e trava entre processos, permitindo
que a janela e o gateway leiam/escrevam o mesmo arquivo com segurança.
No Fedora o cliente usa o gateway permanente local; no Windows usa o endpoint
configurado da ponte, incluindo as atualizações de domínio existentes.
O gateway precisa estar acessível para sincronizar entre dispositivos.
O modo Demo continua isolado e não sincroniza seus dados fictícios.

## MP3 locais

Android consulta MediaStore de todos os volumes com permissão de áudio.
Uma pasta adicional pode ser autorizada pelo seletor de documentos (SAF).
O catálogo `__locais__` é somente leitura e não sai do celular.
Hashes SHA-256 identificam e deduplicam arquivos; resultados da indexação são
reutilizados quando URI, tamanho e data não mudam. Novos arquivos indexados
pelo Android acionam o observador; abrir Music e pastas SAF também reindexa.
Curtir ou copiar uma faixa guarda uma cópia estável antes de publicar os dados.
O áudio sobe pela ponte privada ao gateway e é recebido pelos PCs; a transferência
valida hash e formato MP3 e nunca substitui a faixa por um arquivo parcial.
MP3 compartilhados têm limite de 128 MB; maiores continuam disponíveis localmente.
Downloads do YouTube e transferência de MP3 locais são conceitos separados.
Downloads Android ficam em `getExternalFilesDir(Music)/Emily Music`, com
WorkManager, progresso, cancelamento e no máximo duas conversões simultâneas.
Nenhuma operação apaga o MP3 original do usuário.

## Verificações

- `testes/test_music_sync.py`: mesclagem, tombstones, processo externo,
  posição independente, autorização, hash e HTTP Range.
- `testes/test_music_android_ui.py`: assets reais em viewport móvel,
  catálogo protegido, adição idempotente, controles nativos e reconexão da UI.
- Testes existentes de Music/player/downloads e testes unitários Android.

A interface móvel também foi exercitada via ADB no Moto G22: catálogo de
17 MP3 reais, Media3/reprodução e pausa. Testes em Chromium continuam cobrindo
adição idempotente, reconexão e ticks de progresso sem repintar toda a interface.

## Correção de ANR (Android 28)

O relatório de ANR do aparelho mostrou `ChatSync.sincronizar()` executando na
thread principal e esperando a trava de `ChatRepository.getChat()`. O delta
relia o histórico inteiro para cada conversa. Agora todo pull roda em IO,
coalesce ciclos simultâneos, lê um snapshot por ciclo e aplica mudanças em lote,
revalidando edições locais antes de gravar atomicamente. `ChatDeltaMergeTest`
cobre edições durante a rede, regenerações, exclusões e deltas sem mudanças.

Capas base64 ficam preservadas para sincronizar, mas a UI recebe URLs locais
em vez de megabytes por consulta. Serialização, gravações de estado e consultas
de disponibilidade ficam fora da thread principal; consultas WorkManager têm
prazo e não prendem a trava da biblioteca. Scans simultâneos não se acumulam;
scans/sync sem alterações não regravam o documento. Capas de MP3 são limitadas
a 512 pixels. A fila só cruza a ponte quando muda; ticks não recriam controles.
O painel usa a altura do contêiner em vez de `100dvh`, que retornou zero durante
o layout inicial da WebView real e deixava a tela em branco.


## Android 29: gestos e streams do YouTube

A lateral Compose tem gestos desativados somente na rota Music; Voltar do
Android continua saindo da tela. Playlists e cards usam rolagem horizontal
própria, sem cortar itens ou bloquear a rolagem vertical do conteúdo.

Uma faixa do YouTube sincroniza pelo `video_id` e é resolvida diretamente no
celular, sem o PC ligado e sem transferir o arquivo do desktop. Music consulta
atualizações do yt-dlp uma vez por dia antes de resolver/baixar áudio; tentativas
falhas têm intervalo para não repetir consultas em toda ação. O DataSpec recebe
os cabeçalhos retornados pelo extrator, inclusive User-Agent; a fábrica HTTP
não os substitui por um agente genérico. URLs são reutilizadas apenas até sua
validade, e descartadas nas novas tentativas após falhas. Erros de reprodução
ficam separados do aviso de sincronização para não sumirem no próximo pull.
MP3 locais compartilhados continuam transferindo o arquivo, como autorizado.

## Android 30 — interface móvel e controles de mídia
- Navegação inferior (Início, Buscar, Biblioteca e Criar), biblioteca vertical, capas e cabeçalho de playlists maiores; ações de faixas em menu compacto.
- Mini player com progresso abre a tela Música tocando: capa, posição, anterior/pausar/próxima, aleatório, repetição, curtida, adicionar, fila e letras.
- Voltar do Android recolhe a tela ampliada e menus antes de sair; o serviço mantém o áudio.
- MediaSession publica comandos de aleatório e repetição na notificação expandida e controles do sistema. O Android/OEM escolhe o espaço disponível na tela bloqueada e na notificação compacta.
- Modos alterados no sistema chegam à interface e são persistidos/sincronizados. Revisões das configurações impedem que uma leitura antiga desfaça uma mudança recente; novas alterações do PC continuam aplicáveis.
- A fila exibida acompanha a ordem aleatória nativa. Downloads, músicas locais, reprodução offline, busca e sincronização continuam usando os mecanismos existentes.
- Teste de interface cobre mini/full player, seek, comandos nativos, modo offline/reconexão, playlist local somente leitura, adição sem duplicata e revisão de modos.

Validação da versão 30: 117 testes Android sem falhas; teste da interface móvel aprovado; instalação ADB em atualização, áudio local nativo e tela ampliada conferidos no Moto G22. A notificação publicada inclui os comandos de aleatório e repetição. A fila anterior foi restaurada após a checagem curta.

## Android 31 — correções de layout e ações
- Tela ampliada com largura limitada, quebra de títulos longos, capa inteira sem corte lateral e espaçamento distribuído conforme altura disponível. Em telas pequenas ou com títulos muito grandes, o conteúdo continua rolável.
- Download de cada faixa online acessível diretamente na linha; mantém estados de progresso, cancelamento, baixada e indisponível offline. MP3 local continua sem botão de baixar.
- Opções em dialog modal nativo do HTML, fora dos contêineres roláveis, com texto, ícones, fechamento por toque fora e Voltar. Fica acima do mini player; atualização de dados fecha ações antigas.
- Testes em 320×640, 390×844 e 411×855 verificam títulos longos, ausência de overflow lateral, download direto e opções clicáveis com mini player visível.

## Android 32 — overlay e abertura de telas por voz
Logs do Moto G22 mostraram SYSTEM_ALERT_WINDOW no modo default, overlay recusado e abertura do YouTube bloqueada pelo ActivityTaskManager, apesar de startActivity retornar sem exceção. A permissão foi reativada com autorização do usuário e permaneceu allow após instalação em atualização. A origem da mudança anterior de permissão não foi comprovada.
- Guarda de abertura de Activities no controlador do celular; sem condição de abertura em background, não envia o intent.
- Resultado estruturado de falha para a ferramenta abrir_app e exceções do agente; voz rápida e modelo selecionado respeitam a falha, sem transmitir confirmação positiva por streaming após esse resultado.
- Aviso de permissão do overlay com link para as configurações; revalidação no retorno à Activity e na tentativa do overlay, sem depender do antigo flag de pedido único.
- 121 testes unitários passaram. Teste instrumental no Moto G22 mostrou o overlay e abriu YouTube pelo AndroidController fora da MainActivity, verificando a Activity do YouTube realmente em primeiro plano. O teste não chamou modelos nem gravou áudio.

## Android 33 — destino padrão das ações

A regra compartilhada do agente passa a priorizar o celular para novos pedidos compatíveis sem destino explícito. Vale no chat, na voz rápida, no modelo selecionado e na delegação; o classificador legado também recebe a regra. O histórico pode resolver retomadas de tarefas, mas uma referência antiga a PC/TV não deve mudar o destino de uma nova ação genérica. Os modos remotos explicitamente ativados mantêm seu roteamento existente. Falha local não autoriza migrar silenciosamente para outro aparelho.

O teste do roteador cobre pedidos genéricos com modo remoto ligado/desligado. A escolha semântica das ferramentas continua sendo feita pelo modelo, sob essa prioridade compartilhada.

Validação da versão 33: compilação e 122 testes unitários aprovados; atualização instalada com install -r. O teste instrumental de abertura do YouTube não confirmou primeiro plano nesta execução; o log do Android confirmou lançamento autorizado por SYSTEM_ALERT_WINDOW, mas havia uma tarefa YouTube em picture-in-picture. Não foi alterado o estado desse vídeo para investigar. A permissão do overlay permaneceu concedida. Não foi feita uma chamada real à LLM para medir a seleção semântica das ferramentas.

## Android 34 — recuperação da escuta em segundo plano

A captura de wake word não é prova de que existe um consumidor do chamado: antes, o atendimento dependia de callbacks criados apenas na rota home. EmilyVoiceRuntime agora fica acima do NavHost e mantém o processamento ao abrir chat, configurações ou música. Ao destruir a Activity, a gravação da conversa é cancelada/liberada e os callbacks são descartados.

WakeDelivery conserva o chamado (inclusive o caminho do WAV one-shot) enquanto recria a MainActivity e aguarda seus callbacks; um chamado sem atendimento em 15 segundos libera o WAV, esconde o overlay e retoma a escuta. A janela recuperada pode atender sobre o bloqueio/acender a tela, restaurando o comportamento normal ao encerrar a sessão.

O serviço verifica progresso de captura e reinicia captura/reconhecedor em caso de travamento; erros/timeouts do Vosk também acionam recuperação. A pausa intencional para conversa não é tratada como falha. O reconhecedor one-shot passa a ter propriedade exclusiva da thread, evitando fechamento pelo caminho do Vosk padrão.

Validação: 124 testes unitários passaram. No Moto G22 conectado, o teste instrumental de destruição/recriação da Activity retomou gravação e permitiu cancelamento sem chamar transcrição/LLM. Instalação realizada como atualização (install -r), sem limpeza de dados. O teste prolongado com tela apagada é registrado abaixo. Não se alteraram políticas globais de bateria, root, permissões nem configurações do fabricante.

Teste com tela apagada: aprovado no aparelho, 40 segundos de captura em segundo plano com heartbeat recente (<10 segundos). APK 34 instalado e publicado. Não houve teste de várias horas nem validação em outras versões do Android.


## Android 35 e PC — revisão de estabilidade do Emily Music

- Android salva posição/fila em checkpoint AtomicFile separado da biblioteca e das capas. Migra o checkpoint legado antes de remover o campo do arquivo maior. Atualizações idênticas não gravam disco; ajustes de volume/repetição/aleatório continuam sincronizados.
- Recuperação de áudio preserva a intenção de reprodução após esgotar três tentativas. Retorno da conexão validada permite retomar; pausa e troca de faixa cancelam a intenção antiga. Cache de URLs extraídas limitado a 64 entradas.
- Downloads: timeout total, cancelamento propagado ao extrator, limpeza após término da thread, checagem de cancelamento antes de publicar o arquivo e limite de 128 MB. Falhas transitórias podem voltar à fila do WorkManager; ordem dos estados usa etiquetas de enfileiramento compatíveis com a versão instalada da biblioteca.
- Tela: callback atrasado do MediaController não atualiza tela descartada; seletor de arquivo é encerrado no descarte; identificadores inválidos da ponte JS não geram crash e pedidos excessivos recebem erro.
- PC: lote de sincronização validado antes de aplicar; falha de transação descarta cache parcial. Sincronizações sem mudanças não regravam a biblioteca. Ordenação rejeita valores não numéricos e listas duplicadas. Gateway rejeita JSON que não seja objeto; Range bytes=-0 retorna 416.
- MP3 local curtido não publica URI privada do Android nos campos sincronizados.

Escopo preservado: gateway pessoal de um usuário, sem extração de aplicativo, login Google ou publicação para terceiros nesta etapa. Testes de longa duração, outros fabricantes e grandes bibliotecas continuam necessários antes da beta pública. Resultados da validação desta versão serão registrados abaixo.

Validação automatizada da versão 35: compilação Android concluída; 127 testes unitários Android sem falhas; 20 testes Python/interface móvel passaram, incluindo tamanhos 320×640, 390×844 e 411×855. Após ampliar a proteção de JSON às rotas de busca e letras, os 8 testes de sincronização/gateway passaram novamente. Módulos Python atualizados em dist/Emily/_internal com backup anterior em backups/music-stability-35; passam a valer ao reiniciar o aplicativo.

A conexão USB desapareceu na primeira tentativa de install -r. Após reconexão, o APK 35 foi instalado como atualização e os dois testes instrumentais de checkpoint/áudio com tela apagada passaram no Moto G22. Não houve desinstalação nem limpeza de dados. APK disponível em EmilyAPP2/app/build/outputs/apk/debug/app-debug.apk. Após essa conferência, o mesmo APK 35 foi disponibilizado no canal pessoal de atualização.

Validação no aparelho concluída: OK (2 tests), 15,04 segundos. Checkpoint legado preservado na migração e relido por nova instância do armazenamento; serviço real de música manteve reprodução silenciosa durante 12 segundos após comando para apagar a tela, avançando pelo menos 10 segundos. Teste restaura fila/posição/volume anteriores e remove o áudio temporário. SYSTEM_ALERT_WINDOW permaneceu allow. MainActivity reaberta após os testes. Não houve teste de várias horas, rede YouTube instável ou outros aparelhos nesta checagem.


## Android 36 — busca, reprodução avulsa e adicionar no player

- Menu de adicionar é um dialog em top layer, com contraste explícito, fechamento por Voltar/toque fora e playlists somente leitura excluídas. Fica acima da tela ampliada e mantém prevenção de duplicatas por destino.
- Busca com linhas compactas, capa, título, ação de tocar, opções e +/✓. Tocar o resultado cria fila avulsa sem selecionar/criar/alterar playlists. Curtir uma faixa avulsa salva seu registro na biblioteca; fila avulsa não recebe alterações da playlist aberta.
- Histórico de até 12 consultas em localStorage do aparelho, preenchimento da busca e limpeza. Adicionadas recentemente são derivadas das playlists sincronizadas, excluindo o inventário automático de MP3 locais. Respostas atrasadas não substituem consulta nova; fechar uma busca pendente não deixa spinner preso.
- Busca Android usa API YouTube ou extrator do próprio aparelho, sem esperar pelo PC. Cache por consulta de dez minutos, limitado a 32 entradas e com LRU; chave indisponível aguarda cinco minutos antes de nova tentativa.
- Extrator preparado em IO ao abrir Music com internet; manutenção diária ocorre em segundo plano. Erro de extração permite aguardar atualização e tentar mais uma vez. Extrações de busca/URL têm limite por tentativa e cancelamento propagado ao processo. Cache existente de URLs de áudio continua reutilizado.
- Tela/layout, duplicatas, estado por destino, recentes persistentes, curtida avulsa e concorrência de buscas verificados em testes da interface real com ponte simulada. Viewports 320×640, 390×844 e 411×855; última guarda de destinos/offline verificada novamente em 320×640.

Não foram alterados o catálogo/fonte YouTube, a autenticação ou o protocolo de sincronização de playlists. Consultas recentes são locais; faixas adicionadas continuam seguindo a sincronização existente. Primeira obtenção de áudio ainda depende do extrator, rede e disponibilidade do YouTube. Resultados no aparelho serão acrescentados após instalação.

Validação final: 128 testes unitários Android sem falhas; seis testes Python/interface passaram, incluindo três viewports móveis e controles de adição/duplicatas no desktop. Último ajuste de destino/offline confirmado novamente em 320×640. Assets do APK comparados byte a byte aos arquivos finais antes da instalação. Versão 36 instalada via install -r, sem desinstalar ou limpar dados, e o mesmo APK disponibilizado no canal pessoal. Interface compartilhada atualizada em dist/Emily/_internal/web; entra no próximo início do Fedora.

No Moto G22: OK (3 tests), 41,78 segundos. Busca real inicial 13.567 ms; repetição pelo cache 0 ms na resolução do cronômetro. Obtenção inicial de URL de áudio 13.100 ms; repetição 1 ms. Estes números são uma amostra única e medem URL/consulta, não tempo até som audível. Checkpoint e reprodução silenciosa com tela apagada também passaram. Fila anterior restaurada.

Diagnóstico de configuração: a chave incorporada ao APK coincide com YOUTUBE_API_KEY em EmilyAPP2/local.properties; a API oficial respondeu HTTP 400 / API_KEY_INVALID. A chave não foi exposta nem substituída. Isso força o fallback ao extrator e impede prometer busca inicial instantânea. Uma chave válida deverá ser fornecida/configurada para recuperar a rota rápida da API. Extrair URL de áudio continua dependente do YouTube mesmo com chave válida.


## Android 37 — chave YouTube validada

Chave fornecida pelo usuário em local.properties validada sem exposição: API oficial retornou HTTP 200, oito resultados em 0,64 s no PC. BuildConfig conferido por igualdade em memória, sem imprimir a credencial. APK 37 recompilado e instalado via install -r preservando dados; mesmo APK publicado no canal pessoal existente.

128 testes unitários Android: zero falhas/erros. Teste instrumental real no Moto G22 passou: busca inicial 976 ms (antes: 13.567 ms), cache 1 ms; obtenção inicial de URL de áudio 14.270 ms, cache 1 ms. Amostras únicas, medem consulta/URL e não tempo até som audível. A chave melhora a busca oficial, não a extração de áudio. Não foram alterados o extrator, o backend de sincronização pessoal ou a autenticação; isolamento por usuário e servidor para proteger a chave continuam pendentes antes de distribuição.


## Android 38 em preparação — Music Cloud e preparação da próxima faixa

Servidor independente em music-cloud/, Cloudflare Workers Free + D1 Free, login Google Firebase, allowlist de emails e cotas atômicas compartilhadas. Chave YouTube somente em secret do Worker; nenhum acesso a biblioteca ou controle do PC. Cache D1 de uma hora, limpeza horária. Implementada verificação criptográfica de tokens Firebase e claims conforme documentação oficial.

Android não gera mais BuildConfig.YOUTUBE_API_KEY. MUSIC_CLOUD_URL é uma URL pública HTTPS, sem token fixo. MusicCloud usa Credential Manager + Firebase Auth, renovação única em 401, feedback para 403/429/503 e cache segregado por UID. Com URL configurada, não contorna autenticação com extrator e não sincroniza a biblioteca contra a ponte pessoal. Consulta por voz/último upload usa o mesmo serviço, com fallback nativo já existente. Configuração vazia preserva extrator local sem chave; APK 37 instalado não foi substituído durante a preparação.

Serviço de áudio prepara somente o endereço da próxima faixa (não baixa o áudio completo) em Wi-Fi validado não tarifado, com faixa atual tocando e mais de 20 segundos restantes. Espera dois segundos, cancela em pausa/mudança de destino e falha opcional não interrompe reprodução. Quando a faixa preparada passa a atual, aproveita o trabalho em andamento, evitando cancelar e começar tudo de novo. Cache existente de 15 minutos reutilizado. Não promete acelerar a primeira faixa sem cache; depende do extrator e da rede.

Publicação, login real e medição de CPU Workers Free aguardam configuração de contas pelo proprietário. A migração não está ativa no celular ainda. Necessário rotacionar chave após migração: APKs antigos já a continham. Outras credenciais no APK completo da Emily e sincronização multiusuário exigem Music separado antes de distribuir; não foram removidas credenciais de voz por fora do escopo desta mudança.

Validação local final: build APK 38 e APK de testes bem-sucedidos; recompilação de consistência após último ajuste do preload também passou. 130 testes unitários Android, nove testes Node do Worker, D1 real em Wrangler local com concorrência/rollback/reservas ponderadas, e deploy --dry-run passaram. Verificado arquivo por arquivo no APK final: chave YouTube atual ausente. Nenhuma instalação/publicação da versão 38; aparelho/canal pessoal permanecem na 37 enquanto configuração Firebase/Cloudflare está pendente. Login com conta real e ganho de transição de áudio ainda não foram medidos no aparelho.


## Android 39 — servidor publicado e entrada somente no Music

Worker publicado em https://emily-music-search.vitorsh-dev.workers.dev no plano
gratuito, com D1 criado e schema aplicado. Secrets YouTube/allowlist enviados
sem imprimir credenciais. Endpoint /v1/account confirma a conta antes de compor
a biblioteca, sem consumir cota de buscas. /health respondeu 200, /v1/account sem
login respondeu 401 e /music/sync respondeu 404. Onze testes Node passaram.

Login protege somente Emily Music. Logout esconde biblioteca e busca, interrompe
o player/limpa fila e cancela trabalhos de download. Arquivos/playlists salvos
permanecem em disco. Firebase mantém sessão; uma conta previamente aprovada pode
abrir os arquivos offline, mas logout remove aprovação. Validação de conexão usa
o Context, sem depender da inicialização da biblioteca. Token expirado recebe
uma renovação antes de solicitar nova entrada.

Por escolha explícita do proprietário, MUSIC_PERSONAL_BRIDGE_ENABLED=true no APK
pessoal mantém sincronização com seu PC, somente enquanto a conta estiver
aprovada. O padrão para builds novos é false. Isso corrige a descrição anterior
que dizia que todo APK cloud desabilitaria a ponte.

APK 39 compilado e instalado via install -r, sem desinstalação/limpeza de dados.
130 testes unitários Android passaram. Chave YouTube atual ausente de todos os
arquivos do APK final. Permissão SYSTEM_ALERT_WINDOW permanece allow. Testes
instrumentais de checkpoint e áudio silencioso com tela apagada passaram,
incluindo confirmação assíncrona de pausa e remoção da fila pelo logout. Teste
visual da entrada passou após desbloquear o aparelho (OK, um teste, 2,8 s); login
Google real e medição da busca autenticada ainda pendentes. APK pessoal no canal de atualização
ainda é 37 até concluir essa checagem.

Não há isolamento da biblioteca local entre contas nem sincronização cloud por
UID; o APK completo da Emily continua pessoal. Rotação da chave antiga permanece
pendente, pois versões 37 e anteriores já a incluíam. Preparação de próxima URL
não elimina o custo inicial da extração de áudio; ganho real ainda não medido.


## Android 40 — fundo original do Music

Por solicitação do usuário, a tela de entrada usa arte abstrata própria, preta e
carvão com bordas de luz laranja, sem retrato/personagem. Criada com image_gen
built-in; PNG e prompt em output/imagegen, asset WebP de 67.428 bytes em res.
Título Emily Music serifado e controles nativos permanecem legíveis e adaptáveis.
Movimento lento da arte e pulso discreto no detalhe de áudio; controles em laranja,
cartões de playlists/offline, feedback de conexão/erro e layout rolável.

Login real confirmado pelo proprietário na versão 39: biblioteca apareceu
normalmente. Teste instrumental da busca autenticada passou: consulta inicial
1.824 ms, cache 1 ms; extração inicial de URL de áudio 14.226 ms, cache 1 ms.
Amostra única; mede consulta/URL, não tempo até áudio audível. Não foi alterado
o extrator para prometer inicialização instantânea.

Versão 40 compilada e instalada como atualização preservando dados e sessão.
130 testes unitários sem falhas; verificação de ausência da chave YouTube e
inclusão da arte no APK passou. Checagem visual final passou após desbloqueio (um teste, 4,3 s). Captura real
em output/imagegen/emily-music-login-preview.png conferida: textos/controles
legíveis e sem cortes. Teste não desloga o proprietário. Mesmo APK publicado no
canal pessoal como versão 40; arte/prompt foram preservados no projeto.


## Android 41 — ícone Google oficial

O botão de entrada usa o G colorido original, obtido em
https://developers.google.com/static/identity/images/g-logo.png, sem recoloração
e preservando proporção. O botão passou ao tema neutro escuro com contorno e
o ícone recebe fundo branco, conforme orientações de
https://developers.google.com/identity/branding-guidelines. Fundo artístico e
detalhes laranja preservados. Nenhuma alteração na autenticação ou nos dados.

Validação 41: build concluído; PNG oficial no APK idêntico ao download; teste
instrumental de apresentação/ações passou (um teste, 4,7 s). Captura real
conferida: logo colorido sem tint, textos e botão sem cortes. Instalado via
install -r e publicado no canal pessoal, mantendo dados/sessão.

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
chave YouTube atual. Ícone temporário até a definição da arte pelo usuário.

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

Instalação da 0.1.6 pelo próprio Music confirmada; versão release e biblioteca sincronizada conferidas após instalação. Teste de perfil vazio restaurou a biblioteca da conta real sem alterar a original.

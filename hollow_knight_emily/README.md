# Emily Companion — Hollow Knight

Vertical slice do mod que manifesta Emily como uma fada-mariposa companheira.

## Incluído

- charm **Vínculo de Emily**, custo zero, via SFCore;
- pickup procedural em `Tutorial_01` (e fallback em `Town` para saves antigos);
- autoequipagem opcional na aquisição e persistência do estado equipado por save;
- dois estados visuais transparentes, cada um com 24 frames a 12 FPS;
- estado ativo em perspectiva inspirado na referência de expectativa, com
  chifres corrigidos, três batidas de asa por ciclo, inclinação, impulso,
  balanço e flutuação;
- orientação sincronizada diretamente com a direção atual do Cavaleiro;
- troca automática para a animação frontal anterior quando o Cavaleiro senta
  em um banco;
- movimento local determinístico, HUD, emoções e voz WAV com ganho até 200%;
- atividade da companheira, telemetria e integração restritas ao período em que o
  **Vínculo de Emily** está equipado;
- fala respeitosa do momento do jogo: não **começa** durante cutscene, diálogo,
  animação de coleta, transição de tela, fast travel, menu ou morte, mas uma fala
  já iniciada sempre termina;
- consciência de lugar: localização autoritativa por evento e nomes de região em
  português, para o comentário nunca falar de uma área onde ele já não está;
- olhar de história: a Emily guarda falas de NPC e avanços e, de vez em quando,
  comenta a trama ou arrisca uma teoria, sem spoiler;
- comentário sem relatório de status: métricas viram contexto invisível e números
  são bloqueados na saída, com reescrita e descarte como salvaguardas;
- dano só rende assunto quando é anormal (perda grande, vida no fim ou erro
  repetido); rotina de banco não gera fala, e descansar virou momento de conversa;
- contexto leve de combate (0.5.4): amostra criaturas próximas com HealthManager,
  alvos atingidos pelo Cavaleiro e o objeto que causou dano, quando o callback do
  jogo o fornece. Nomes internos não são tratados como identidades de lore;
  contagem é parcial e não identifica todo inimigo que está atacando. Não há
  prints, análise de vídeo nem custo de chamadas extras ao modelo;
- saudação ao entrar no jogo, em qualquer modo de fala;
- foco na voz: o áudio do jogo abaixa momentaneamente enquanto ela fala, pelo
  mixer original, sem afetar o volume da voz;
- ponte autenticada somente em `127.0.0.1:57124`, mantida pelo gateway
  permanente mesmo com a interface desktop fechada;
- filas prioritárias, IDs de sessão/cena, confirmação, retry e expiração;
- percepção de conversas por `DialogueBox`, com texto localizado e identidade do
  NPC somente quando a chave oficial permite confirmá-la;
- detecção de chegada a arenas, início de boss fight e padrões observáveis durante
  a luta, baseada em alvos reais e redução efetiva de HP;
- memória própria de campanha em SQLite, separada da memória unificada, com
  linha do tempo por slot, totais, áreas e percepção de padrões;
- Faísca Teimosa, Escudo da Filha, Eco de Alma, Pulso do Vínculo,
  Marca de Caça e Última Bronca;
- falas terminam pela posição real de reprodução: o final nunca é cortado;
- Panteões de Godhome: cada chefe da sequência é percebido e anunciado um a um,
  incluindo a Radiância Absoluta;
- a Emily acompanha a barra de vida do chefe em tempo real e percebe quando a
  luta muda de etapa (a subida de plataformas da Radiância, por exemplo);
- acontecimentos próximos (amuleto comprado numa conversa, chefe que entra logo
  depois de outra coisa) viram um único comentário combinado, sem empilhar
  falas atrasadas;
- chefe é detectado só em jogo de verdade: menu e pausa não geram anúncio nem
  reação de "jogo bugado";
- morte depois de uma luta de chefe gera reação pós-respawn citando a briga,
  e reações de chefe/morte nunca ficam mudas quando o modelo insiste em
  narrar números;
- falas de chefe (encontro, início, fase) são persistentes: a intro com title
  card não descarta mais a reação, e o gate de fala relaxa durante a luta;
- no tagarela, a Emily também conversa durante a luta de chefe, e o
  comentário de combate aparece com mais frequência;
- detecção de amuleto imune a falsos positivos em Godhome/Panteões;
- fallback offline: combate e movimento continuam sem a IA.

## Configurações no jogo

Abra **Opções → Mods → EmilyCompanion**. A versão 0.5.4 oferece:

- nível de comentários: Silenciosa, Discreta, Normal ou Tagarela;
- cérebro/modelo usado somente pelo Hollow Knight: modelos OpenAI da seção
  `EMILY_PROVEDOR_OPENAI_*` do `.env`, com GPT 5.6 Luna como padrão se disponível;
- integração com IA, voz, volume de 0% a 200%, legendas e HUD;
- **Foco na voz da Emily**: abaixa o áudio do jogo (música e efeitos) só enquanto
  ela fala, com opções Desligado, Leve e Forte;
- ataques automáticos, poderes ofensivos, poderes de suporte e sugestões da IA;
- autoequipagem do Vínculo de Emily.

Cada opção informa na própria descrição quando entra em vigor. Quase todas são
imediatas ou valem na próxima fala; mudanças na lista de modelos do `.env`
exigem reiniciar `emily-gateway.service` e o jogo para recarregar, revalidar e
reconstruir a tela com o novo catálogo.

Na 0.5.3, trocar modelo ou modo envia a configuração mesmo sem surgir evento;
o gateway devolve o ID efetivamente aceito e registra aviso no log do mod caso
o modelo selecionado não esteja disponível (nesse caso usa o padrão). Saves no
mesmo slot criam sessões novas ao carregar: falas pendentes, cooldowns e histórico
de texto da sessão anterior não migram. A ponte permanente usa o mesmo filtro
qualitativo de telemetria da ponte desktop, sem despejar números de status no
prompt. Silenciosa preserva saudação, chamada direta, aquisição do vínculo,
morte e vitória contra chefe; Tagarela mantém comentários espontâneos só quando
há assunto ancorado nos fatos da campanha.

Acima de 100%, o mod aplica ganho diretamente às amostras PCM com limitador
suave. Isso aumenta de verdade a voz, em vez de tentar passar do teto `1.0` do
`AudioSource`, e reduz clipping abrupto nos picos. O valor antigo de 90% continua
válido para quem já tinha configuração salva.

O catálogo instalado contém apenas IDs e nomes públicos de modelos. Chaves,
URLs privadas e demais valores do `.env` nunca são enviados ao jogo.

## IA e voz sem abrir a Emily desktop

A partir da 0.4.2, o mod não depende mais do processo gráfico da Emily. O
`emily-gateway.service` mantém a ponte loopback `57124` ativa e usa:

- a conexão OpenAI configurada por `EMILY_PROVEDOR_OPENAI_BASE` e
  `EMILY_PROVEDOR_OPENAI_CHAVE` para as falas contextuais (sem delegação);
- a API REST da FishAudio configurada por `FISH_AUDIO_KEY` para gerar WAV;
- `EMILY_FISH_BASE_URL` opcional, cujo padrão é `https://api.fish.audio`;
- `EMILY_FISH_VOICE_ID` opcional para trocar a voz sem recompilar.

As chaves permanecem somente no `.env` do PC. A DLL recebe apenas o token local
da ponte e metadados públicos dos modelos. Se o serviço permanente estiver
indisponível, a Emily aberta por `main.py` ou pelo executável compilado ainda
pode iniciar a ponte como fallback, sem disputar a porta quando o serviço já
estiver ativo.

Alguns upstreams implementam `/chat/completions` mas respondem 404 em `/models`.
Desde 0.5.3 isso não impede abrir sessões; credenciais rejeitadas continuam
marcadas como indisponíveis e erros na geração de texto são registrados.

## Memória da campanha

A memória dedicada, introduzida na 0.4.5, é leve e não usa ChromaDB, embeddings nem carregamento
da memória unificada da Emily. O banco privado fica em:

```text
~/.local/share/emily/hollow_knight/memoria.sqlite3
```

Cada slot mantém sua própria linha do tempo. A memória registra todos os eventos
significativos recebidos — início de sessão, áreas, dano, quase morte, mortes,
inimigos, bancos, poderes e progresso — e amostra o estado contínuo em intervalos
compactos. Snapshots redundantes não são guardados a cada quatro segundos: são
persistidos no máximo a cada trinta segundos ou quando vida, ferrão, habilidade,
área ou banco mudam. O limite padrão é de 12 mil eventos por campanha, com
limpeza apenas de itens antigos além desse teto.

A Emily também deriva padrões baseados em evidências:

- tempo parado fora de menu, pausa, cinemática e banco;
- muitos impactos em uma janela curta;
- repetição do mesmo perigo ambiental, como espinhos, ácido, lava ou abismo;
- mortes próximas e escalonamento da dificuldade;
- tempo prolongado sem progresso combinado com incidentes recentes;
- progresso silencioso por vida máxima, força do ferrão e novas habilidades.

A partir da 0.4.4, o mod também compara transições reais de `PlayerData` e gera
marcos persistentes para amuletos, estações do Último Besouro, itens-chave,
magias e bosses. O primeiro retrato de um save é apenas linha de base, portanto
um save antigo não anuncia tudo como recém-adquirido. Falas desses marcos não são
descartadas por uma troca rápida de sala nem podem ser anuladas por uma resposta
silenciosa do modelo.

Na 0.4.6, a ponte continua consultando comandos a cada 0,35 segundo e um evento
novo acorda o envio imediatamente no próximo update. Banco, conversa e boss usam
as filas prioritárias tanto na DLL quanto no backend. Texto e áudio são
correlacionados pela sequência da fala e passam por uma única fila local: a
legenda entra no mesmo momento em que a voz começa e sai quando o clipe termina.
Uma fala nunca interrompe outra. Se o TTS falhar, o backend envia uma resolução de
áudio vazia para liberar a fila sem sobreposição; com voz desligada, as legendas
continuam serializadas por uma duração textual. Trocas de cena descartam falas
contextuais antigas, mas preservam marcos persistentes.

## Conversas e chefes

A Emily observa `DialogueBox.StartConversation`, `SetConversation`, as páginas e
`HideText`, resolve o texto pela própria `Language.Language.Get` do jogo e só
comenta depois que a caixa está oculta, o Cavaleiro recuperou o controle e passou
um debounce de 1,6 segundo. `SendConvEndEvent` não é tratado como encerramento
real porque o jogo também o dispara ao terminar cada página. Conversas idênticas
têm cooldown local de três minutos. Quando a chave oficial identifica o
personagem, o evento inclui o nome; caso contrário, a IA recebe a conversa, mas é
proibida de inventar quem falou. O prompt manda reagir à conversa concluída, sem
narrar, transcrever ou resumir a fala do NPC como locução.

Ao desequipar o **Vínculo de Emily**, o mod interrompe a voz atual, esconde a
legenda e o HUD, limpa falas pendentes, desativa a fada e encerra a sessão da
ponte. Bosses, NPCs, progresso, memória e comentários ficam ignorados até o
vínculo ser equipado novamente. A aquisição do próprio charm é a única exceção:
ela pode ser guardada para entrega assim que o vínculo for ativado.

Para chefes, o rastreamento introduzido na 0.4.5 combina um catálogo conservador de arenas com os
`HealthManager` reais e o `BossSceneController` do jogo. Arenas normais consultam
os flags de vitória antes de anunciar, então atravessar uma sala já concluída não
deve virar um falso encontro. Hornet, Grimm, Radiância, chefes principais e
encontros de Godhome estão cobertos; bosses reconhecidos dinamicamente também
entram quando o alvo real aparece. Se o `BossSceneController` confirmar um chefe
fora do catálogo, o identificador interno é marcado como não canônico: serve para
correlacionar a luta, mas a IA é instruída a dizer “esse chefe” em vez de inventar
um nome de lore.

Durante a luta, o mod não manda cada golpe ao LLM. Ele agrega HP realmente
removido, golpes confirmados, dano recebido e tempo desde o último impacto. A
partir da 0.4.7 o comentário de luta exige uma janela maior (nada nos primeiros
25 segundos e pelo menos 60 segundos entre falas) e padrões mais fortes, para a
briga render comentário e não narração. Os padrões seguem concretos — sequência
sem dano, pressão constante ou recuperação depois de apanhar — mas agora chegam
ao modelo como rótulos qualitativos, sem números. Ataques automáticos da própria
Emily são excluídos das métricas. Os comentários têm cooldown e não interrompem o
mecanismo normal de derrota/progresso.

O número bruto do hook de dano não é mais usado sozinho para afirmar a origem.
Impactos continuam registrados, mas nomes como espinhos, ácido ou lava só podem
ser usados quando houver confirmação adicional. Registros legados da 0.4.3 são
preservados e reclassificados como origem não confirmada.

O nível de comentários muda a sensibilidade, mas não o que é memorizado:

- **Silenciosa:** registra tudo e fala somente em situações críticas;
- **Discreta:** comenta apenas padrões fortes;
- **Normal:** equilíbrio, reagindo a tendências moderadas sem reclamar de cada erro;
- **Tagarela:** percebe padrões menores e faz observações espontâneas
  aproximadamente a cada 140–230 segundos (70–120 quando o Vitor está sentado em
  um banco), usando área, sessão, estado, história e progresso reais em vez de
  preencher silêncio com invenção. Um orçamento de falas de ambiente (6 por 6
  minutos, contra 3 no Normal) impede que o modo vire comentário contínuo em
  qualquer ritmo de jogo.

Sentar em banco deixou de gerar fala própria: acontece dezenas de vezes por
partida e a rotina não é assunto. O evento continua indo para a telemetria e
para a memória, mas quem fala ali é o comentário espontâneo — descansar virou um
dos melhores momentos para conversa solta. Descobrir um banco novo (uma vez por
cenário) continua sendo marco.

Dano só vira assunto quando é anormal: perda grande de vida de uma vez, vida no
fim ou o mesmo erro repetido em sequência (a memória exige impacto grave antes de
contar o padrão). Um machucado pequeno e isolado passa em branco, e quando ela
comenta algo leve, o comentário é curto por instrução explícita do prompt.

### Ela espera o momento — mas não corta o que já começou

A partir da 0.4.7 ela não **começa** a falar durante cutscene, conversa com NPC,
animação que trava o Cavaleiro (coleta de magia, por exemplo), transição de tela,
fast travel do Besouro, menu, pausa ou morte. A 0.4.8 corrigiu o exagero: uma
fala **já iniciada nunca é cortada**, mesmo que o NPC abra a boca, a cena troque
ou o Vitor sente num banco no meio. O gate decide apenas se ela pode começar; o
que ainda sai da fila é comentário que nunca chegou a começar e perdeu o
contexto (25s normal, 180s para marcos persistentes).

A troca de cena também parou de descartar a fala em andamento: o que é purgado é
só a fila, para um comentário da área antiga não começar depois que ele já saiu.

### Ela sabe onde o Vitor está e descobre a história com ele

O mod manda a zona crua (`GREEN_PATH`) e o nome legível (`Caminho Verde`), e a
ponte guarda a localização autoritativa a cada evento — trocar de área não espera
o snapshot de 4 segundos. Antes de comentar, o modelo recebe `localizacao_atual`
com zona, nome e cena, e é instruído a nunca falar de uma região como se ele
estivesse nela: assunto de área antiga fica para trás. A região também acompanha
a fala pronta até a fila do mod; se o Vitor mudar de região antes de ela começar,
ela é descartada. Essa verificação nunca corta uma fala que já começou.
Boas-vindas, reação à morte, aquisição inicial e chamada direta são as exceções
deliberadas, pois não descrevem a paisagem e precisam sobreviver à transição.

A partir da 0.4.8 ela também acompanha a história: guarda o que os NPCs disseram,
o que apareceu de novo e o que mudou, e de vez em quando comenta a trama, liga
dois fatos ou levanta uma teoria, sempre como quem está jogando e percebendo o
mundo. Teoria precisa soar como palpite e nada de spoiler de conteúdo que ainda
não apareceu. Esse olhar é tempero, não o prato principal.

### Saudação de abertura

Toda vez que ele entra no jogo (jogo novo ou save carregado) com o Vínculo
equipado, a Emily fala uma frase curta de boas-vindas na personalidade dela —
em **todos** os modos, inclusive Silenciosa. Reequipar o vínculo no meio da
partida não repete a saudação, e logo depois de adquirir o charm ela usa a fala
de aquisição, não a de cumprimento.

A partir da 0.4.7 ela também **não narra estatísticas**. Vida, máscaras, alma, geo,
golpes, dano, tempo e distância deixam de ser assunto: esses dados viram contexto
invisível (por exemplo, “vida baixa”, “faz um bom tempo que ele não toma dano”) e
o foco passa a ser comentário, opinião, provocação, brincadeira ou dica. O
comentário só cita estado de forma indireta e ocasional (“tá um tempão sem tomar
dano”), nunca como painel. Três camadas garantem isso: o prompt proíbe relatório
de status, os dados enviados ao modelo são sanitizados e, se a resposta ainda
vier com números, a ponte pede uma reescrita; se o modelo insistir, a fala é
descartada — silêncio é melhor do que recitar números.

Enquanto a voz dela toca, o mod pode abaixar momentaneamente o áudio do jogo
usando o parâmetro `MasterVolume` do mixer original: música, inimigos e efeitos
perdem alguns decibéis e voltam ao normal assim que a fala termina. A voz da
Emily não passa por grupo de mixer, então continua no volume configurado. O
recurso vem ligado em **Leve** por padrão e pode ser mudado ou desligado no menu.

O LLM recebe apenas um resumo compacto da campanha, as áreas com dificuldade e
os eventos recentes mais relevantes. Ele não recebe o banco inteiro. Sobre o
usuário, a integração lê somente nome e instruções explícitas curtas do perfil;
avatar, conversas e fatos da memória unificada não entram no processo.
O prompt de jogo importa a mesma personalidade canônica usada por `modelo.py`.
Não há limite fixo de frases ou palavras: a resposta deve ter tamanho proporcional
ao momento. Coisas simples continuam curtas; conversas e acontecimentos relevantes
podem render mais. Todo comentário precisa citar ou usar algum detalhe concreto, e
frases genéricas intercambiáveis são explicitamente proibidas.

Diagnóstico local autenticado:

```bash
curl -H "Authorization: Bearer $(cat hollow_knight_emily/runtime/token.txt)" \
  "http://127.0.0.1:57124/v1/hollow-knight/memoria?campanha_id=slot-1"
```

O alcance da **Faísca Teimosa** foi reduzido para 6,5 unidades. Marca de Caça,
detecção de combate do Eco de Alma, Pulso e Última Bronca mantêm raios próprios.

## Build e instalação

```bash
python hollow_knight_emily/scripts/instalar_sfcore.py
./hollow_knight_emily/scripts/build_mod.sh
./hollow_knight_emily/scripts/instalar_mod.sh
./emily-gateway-service/instalar.sh
```

Dependência instalada: SFCore 1.5.16.2.

Para restaurar as assemblies originais do jogo:

```bash
python hollow_knight_emily/scripts/instalar_modding_api.py restaurar
```

## Teclas de smoke/debug

- `F6`: concede/equipa o charm;
- `F8`: testa Pulso do Vínculo;
- `F9`: alterna HUD detalhado.

O familiar ativo usa uma silhueta mais alta e estreita, próxima da imagem de
expectativa. No banco, ele preserva aproximadamente 1,26 unidade de largura por
0,84 de altura e a pose frontal já aprovada. Os dois spritesheets e o ícone real
do charm são embutidos na DLL; não há arquivos de arte adicionais para copiar
durante a instalação.

Para regenerar os recursos depois de alterar a referência ativa ou exportar
novamente a animação de banco do rig:

```bash
python hollow_knight_emily/scripts/processar_arte_emily.py
```
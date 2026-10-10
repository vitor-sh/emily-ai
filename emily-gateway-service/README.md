# Gateway permanente da Emily

Mantém o cérebro Claude/GPT, a Emily Cloud e o controle estruturado do PC
disponíveis para o celular com a Emily desktop fechada.

## Portas

- `5000`: entrada pública estável (LAN e Ngrok), servida por `emily-gateway.service`.
- `5001`: backend interno da Emily desktop, limitado a `127.0.0.1`.
- `20128`: OmniRoute usado como upstream das rotas `/llm/*`.
- `57124`: ponte loopback do Hollow Knight, servida permanentemente pelo mesmo
  processo do gateway e nunca exposta na LAN/Ngrok.
- `8790`: serviço independente e autenticado da tela do PC, instalado junto com o gateway.
- `8765`: WebSocket autenticado da extensão, preso a `127.0.0.1` e nunca exposto
  pela LAN/Ngrok.

As rotas `/llm/chat`, `/llm/busca`, `/llm/status`, `/llm/provedores`, `/pc/status`,
`/pc/action` e todas as rotas `/cloud/*` são respondidas diretamente pelo gateway. O Cloud abre o mesmo
SQLite e os mesmos objetos por SHA-256 da interface desktop, portanto PC e
celular nunca mantêm cópias concorrentes. As demais rotas são encaminhadas para
a Emily em `5001`; com ela fechada, retornam `503` controlado.

## Controle direto do PC

### Acompanhamento de pendências pelo celular

No app Android, pedidos como “fica de olho no Cline e me avisa quando terminar”
registram um acompanhamento local (até cinco simultâneos). O serviço de
acompanhamento do celular continua em segundo plano e consulta o gateway em
intervalos ajustados ao progresso. O gateway fornece inventário de monitores, nomes de processos do usuário e
abas da extensão, sem trazer programas para o primeiro plano. O app observa até
quatro monitores, pode ler texto de abas relacionadas ao pedido e exige ter visto
atividade e depois dois sinais consecutivos de conclusão/erro para notificar e
anunciar por voz. É possível consultar ou cancelar o acompanhamento por voz. Os
registros sobrevivem à reinicialização do app e expiram depois de 24 horas com
um aviso de que não houve confirmação.

Se o pedido incluir “quando terminar, faça ...”, o Android guarda a ação até
confirmar a conclusão. Também pode guardar uma ação para executar durante o
acompanhamento. Nessas ações, o gateway inicia a Emily desktop compilada se
necessário, espera `/status` indicar que está pronta e usa a ponte local
autenticada `/pc/visual-monitor` para o agente visual. A configuração **Ações
visuais nos acompanhamentos** começa ligada e pode ser desligada no celular.
Uma execução visual é vinculada a um ID e à instância da Emily desktop, para
evitar repetir cliques após perda de resposta ou reinício. Em caso de erro,
resultado inconclusivo ou sessão visual perdida, o Android guarda a pergunta,
anuncia por voz e mostra uma notificação que abre a tela de resposta. Ações
sensíveis exigem a resposta exata “sim, confirmo” ou “não, cancelar”.

Por enquanto, essa automação visual inicia somente a Emily compilada no Fedora.
Se o PC estiver desligado, sem sessão gráfica, gateway ou captura de tela, o
Android não consegue abri-lo remotamente. Ações visuais dependem da sessão
gráfica desbloqueada e só podem ser verificadas por testes no aparelho real.

Requer gateway, serviço de captura de tela e ponte do modelo acessíveis do celular;
para texto de abas em segundo plano, também requer a extensão conectada. Funciona
com a janela da Emily Desktop fechada, mas **não** quando o gateway ou a escuta do
celular estiverem desligados. Um resultado invisível (ex.: processo sem interface,
aba inacessível, sessão gráfica bloqueada) não pode ser confirmado por observação;
nesses casos, a Emily não deve anunciar sucesso. Verificar no aparelho permissões
de notificação, economia de bateria e os avisos por voz antes de depender disso.

`POST /pc/action` recebe somente ações enumeradas: status, busca, abrir
aplicativo/jogo/arquivo/pasta/site, fechar aplicativo, navegador, mídia MPRIS,
captura JPEG autenticada, downloads restritos, energia e a ponte enumerada do
agente visual. O executor não
aceita comando de terminal, não usa shell e restringe arquivos às pastas do
usuário, mídias montadas e raízes extras configuradas em `EMILY_PC_RAIZES`
(separadas por `:` no Linux).

Por padrão, desligar, reiniciar, suspender e hibernar usam uma confirmação
aleatória em outro turno, que expira em 90 segundos. Em Configurações → Emily do PC,
o celular oferece Modo irrestrito (desligado por padrão): a preferência do app,
fora dos argumentos produzidos pelo modelo, acompanha as chamadas autenticadas.
Nesse modo, energia dispensa o segundo turno, com retransmissões idempotentes.
Exclusões literais por rm/unlink/rmdir dentro da pasta pessoal também dispensam
confirmação; raiz da home, arquivos ocultos de configuração/credenciais, links
para fora da home, scripts e operações graves continuam protegidos.
Essa preferência não concede root nem altera o bloqueio de operações catastróficas. As rotas
`/pc/*` recusam funcionar se `EMILY_PONTE_TOKEN` estiver vazio.

Por segurança, comandos de energia ficam desabilitados por padrão. Para armá-los,
adicione `EMILY_ENERGIA_HABILITADA=1` ao `.env` do gateway. Mesmo quando o pedido
for imediato, a execução usa um timer persistente com pelo menos 30 segundos de
margem para consulta ou cancelamento. Testes devem sempre injetar um `runner`
falso; nunca devem habilitar energia usando o executor real do sistema.

A ponte `127.0.0.1:57124/v1/hollow-knight/*` funciona sem a interface desktop:
usa diretamente o OmniRoute configurado no `.env` para personalidade/contexto e
`POST https://api.fish.audio/v1/tts` para voz WAV. O token local e o catálogo
público são gravados junto do mod; chaves de OmniRoute/FishAudio nunca são
copiadas para a DLL nem para o diretório do jogo.

O mesmo processo mantém a memória SQLite exclusiva do Hollow Knight em
`~/.local/share/emily/hollow_knight/memoria.sqlite3`. Ela é separada da memória
unificada, dividida por slot e fornece ao OmniRoute somente resumos compactos.
O endpoint loopback autenticado `/v1/hollow-knight/memoria` permite diagnóstico.

Sem S3, a Emily desktop pode ficar fechada, mas o computador e o serviço do
usuário precisam estar ligados. O Android tenta primeiro a LAN e depois o
endereço público configurado (Ngrok).

O diretório da Cloud pode ser migrado pela interface desktop para outro disco.
A escolha é salva fora do acervo em `cloud-location.json`, lida pelo gateway no
próximo início. Se o HD configurado estiver desmontado, `/cloud/*` responde 503
em vez de criar por engano um catálogo novo no disco do sistema.

## Instalação

### Notificações push com o app fechado

O APK registra seu token FCM no gateway (`POST /android/push/register`) ao abrir,
quando o token mudar ou quando a configuração da ponte mudar. Um produtor de
eventos **no PC** pode enviar avisos ao aparelho, mesmo com o processo Android
encerrado, por `POST /android/push/send` com JSON `{"titulo":"Emily", "texto":"..."}`
e `Authorization: Bearer <EMILY_PONTE_TOKEN>`. As duas rotas exigem o token da ponte.
O gateway guarda o token do aparelho em `~/.local/share/emily/android-push-token.json`
(permissão 0600). O conteúdo da notificação é enviado ao Firebase; não inclua segredos.

Para habilitar o envio no PC, ative a API Firebase Cloud Messaging no projeto
Firebase **emily-assistente**, crie uma conta de serviço com permissão de envio FCM,
baixe o JSON **somente para o PC** (fora do repositório) e configure em `.env`:

```
EMILY_FIREBASE_SERVICE_ACCOUNT=/caminho/privado/conta-de-servico.json
```

Instale `google-auth` no mesmo Python do serviço (`python3 -m pip install google-auth`)
e reinicie o gateway. Teste com o celular fechado, após aceitar a permissão Android
de notificações e verificar o canal Emily. Esta rota entrega avisos de eventos que
**o servidor conhece**: o monitor atual ainda observa o PC pelo serviço no celular;
push não torna essa observação instantânea. FCM depende de internet/Google Play
Services e não garante segundo exato nem entrega após **Forçar parada** pelo Android.

### Descoberta do gateway no Windows

O Fedora publica a URL atual em
`https://emily-assistente-default-rtdb.firebaseio.com/gateway_endpoint.json`.
O registro contém só URL, data e assinatura HMAC com `EMILY_PONTE_TOKEN`.
O Windows valida a assinatura antes de aceitar a URL. As regras do Realtime
Database devem permitir leitura pública **somente** de `gateway_endpoint` e
negar escrita de clientes em todos os caminhos:

```json
{"rules":{".read":false,".write":false,"gateway_endpoint":{".read":true,".write":false}}}
```

A conta de serviço do gateway publica o registro com OAuth, sem passar a chave
privada para Android ou Windows. O projeto Firebase antigo não está acessível;
nenhum dado dele foi migrado.



### Atualizações do aplicativo Android sem Android Studio

O gateway serve a versão publicada em `/android/update` e o APK em
`/android/update/apk` (ambos exigem `EMILY_PONTE_TOKEN`). No PC, após mudar
o código do celular, execute:

```bash
cd "/home/Hiucksam/My Projects/Projeto Emily/minha-ia/EmilyAPP2"
python3 publicar_atualizacao.py
```

O comando incrementa `version.properties`, compila com `:app:assembleDebug` e
publica em `~/.local/share/emily/android-updates`. **Os arquivos editados no PC
não viram automaticamente um APK**: execute o comando para cada nova versão.
Ao abrir o app, com a URL da ponte e o token configurados, ele procura uma versão
mais nova, mostra uma tela animada, baixa, confere tamanho, SHA-256, pacote e
certificado e oferece instalação. O app antigo precisa receber **uma última
instalação via Android Studio/ADB** para adquirir essa funcionalidade. A primeira
instalação pelo app exige permitir “Instalar apps desconhecidos” para Emily nas
configurações do Android e voltar para tocar novamente em “Instalar atualização”.
O sistema Android ainda pede confirmação para instalar: não é instalação silenciosa.

**Não apague `~/.android/debug.keystore` e não desinstale a Emily**: o APK novo
precisa ter a mesma assinatura do instalado para preservar os dados. Se o
aplicativo instalado for release, ele não aceita o APK debug: será preciso
configurar distribuição release com a mesma chave de assinatura do app instalado.
Para usar fora de casa, mantenha o gateway e o túnel configurados; o download
transfere o APK completo (cerca de 138 MB por versão), podendo consumir dados móveis.
Não publique esse APK com segredos embutidos em um servidor público sem proteção.
Este fluxo é para instalação particular fora da Play Store. A política da Google
Play não permite usar `REQUEST_INSTALL_PACKAGES` para autoatualização de apps
distribuídos por ela; nesse caso, use o mecanismo de atualização da Play.

O Python usado pelo serviço precisa ter `flask`, `requests`, `websockets`, `dbus`
e PyGObject/GStreamer (`gi`). O instalador verifica essas dependências antes de
alterar serviços.

```bash
./instalar.sh
```

O instalador habilita o gateway, o OmniRoute supervisionado, o serviço autenticado
de tela `tela-pc.service` e, quando o Ngrok Snap está presente, também o túnel como
serviços systemd do usuário. Na primeira captura, o portal do KDE pode pedir uma
única autorização de compartilhamento; o restore token é reutilizado depois:

```bash
systemctl --user enable --now omniroute-emily.service
```

Na extensão Emily, abra o popup e configure `ws://127.0.0.1:8765` com o mesmo
valor de `EMILY_PONTE_TOKEN`. A extensão autentica antes de aceitar comandos e
não permite URL WebSocket fora de `localhost`/`127.0.0.1`.

A versão `2.3.0` da extensão também consegue resolver uma busca para abrir o
primeiro vídeo específico do YouTube e consultar a página de histórico da conta
já logada em uma janela minimizada de bastidor. Se a conta/página não estiver
disponível, usa somente URLs de vídeos presentes no histórico local. Depois da
atualização, o navegador pedirá a nova permissão de histórico; recarregue/aceite
a extensão para essas duas funções aparecerem.

## Diagnóstico

```bash
systemctl --user status emily-gateway.service tela-pc.service emily-ngrok.service
journalctl --user -u emily-gateway.service -f
curl -H "Authorization: Bearer $EMILY_PONTE_TOKEN" http://127.0.0.1:5000/llm/status
curl -H "Authorization: Bearer $EMILY_PONTE_TOKEN" http://127.0.0.1:5000/cloud/status
curl -H "Authorization: Bearer $EMILY_PONTE_TOKEN" http://127.0.0.1:5000/pc/status
curl -H "Authorization: Bearer $(cat hollow_knight_emily/runtime/token.txt)" \
  http://127.0.0.1:57124/v1/hollow-knight/status
```

As credenciais do OmniRoute e da Brave continuam somente no `.env` do PC. O
gateway recarrega esse arquivo automaticamente quando ele é editado.

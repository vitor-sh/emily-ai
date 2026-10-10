# Emily no Windows 11: build privado e estado real

## O que este projeto prepara

O build Windows usa a raiz atual de `minha-ia/`, gera `Emily.exe` e um
instalador Inno Setup por usuário. O instalador inclui Python, bibliotecas,
interface, Playwright Chromium, `ffmpeg.exe` e o instalador offline do WebView2.
Cria atalhos e inicia o gateway do Android no login do usuário. Memória, agenda,
perfil Discord, TV e dados da memória unificada ficam em `%LOCALAPPDATA%\Emily`.

Ao abrir, o app consulta `/windows/update` no gateway Fedora. Se existir versão
maior, baixa o instalador inteiro, confere tamanho e SHA-256, instala e reabre.
Depois da ativação única descrita abaixo, também consulta `/windows/code-update`:
mudanças nos módulos Python e nos recursos da interface vêm em um ZIP menor,
validado por SHA-256 e por um ensaio do próprio `Emily.exe`, sem refazer o setup.
O script de ativação não é repetido: após uma versão de código ser aprovada e
publicada no gateway Fedora, o Windows confere o feed ao abrir, aplica a versão
e reabre automaticamente. Não há verificação durante uma conversa em andamento.
Chats, fatos do `memoria.json`, foto de perfil e preferências fazem sincronização
bidirecional a cada 30 s
com o mesmo gateway usado pelo Android. Quando a janela Windows fecha, o
gateway Windows continua essa sincronização. O gateway Fedora responde às
rotas de sync mesmo sem sua própria janela de desktop. Em conflitos de
preferências, a alteração mais recente de cada campo vence. Permissões e
caminhos de projeto continuam locais a cada PC. A primeira sincronização
precisa da ponte Fedora acessível; ela não depende de reinstalar o app.

Os modelos OpenAI/OmniRoute que usam `localhost` no Fedora passam pela ponte
HTTPS autenticada do gateway quando a Emily roda no Windows. Atualize e
reinicie o gateway **no Fedora** antes de testar esses modelos no notebook,
e mantenha o mesmo `EMILY_PONTE_TOKEN` nos dois PCs. O notebook não precisa
instalar o OmniRoute. Outros serviços privados configurados para `localhost`
no `.env` continuam precisando de uma ponte própria.

Os embeddings da memória unificada do notebook usam o modelo `embeddinggemma`
do Ollama do Fedora por uma rota autenticada do gateway. O índice Chroma local
do Fedora **não é replicado** para o Windows; fatos básicos e chats sincronizam,
e novas interações no notebook entram no índice local dele.

## Preparar o PC que fará o build

O PyInstaller precisa rodar em um **Windows 11 x64**. Use Python 3.13 x64,
Inno Setup **6.6 ou posterior** e `ffmpeg.exe` no PATH. O 6.6 ou mais novo é
necessário para o tema escuro do instalador. Instale o
[Evergreen Standalone Installer x64 do WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)
como arquivo `windows-build\MicrosoftEdgeWebView2RuntimeInstallerX64.exe`.
O script de build instala o Chromium do Playwright no próprio pacote.

O endereço usado em `--gateway-url` precisa ser HTTPS estável e apontar para
o gateway Fedora na porta 5000. Um endereço temporário de túnel precisa ser
atualizado quando mudar. O `.env` privado entra no pacote com
`--include-private-env`; ele contém chaves extraíveis, portanto o instalador
resultante é somente para o seu teste privado.

No Fedora, `python preparar_windows_fonte.py --private` gera
`Emily-Windows-Fonte-Privada.zip` com o código atual e os recursos necessários,
sem históricos ou backups. Extraia esse ZIP no PC que fará o build.

```powershell
py -3.13 -m pip install -r requirements-windows.txt
py -3.13 build_emily_windows.py --version 1.0.3 --gateway-url https://SEU-GATEWAY --include-private-env
```

O script valida a importação do app e do gateway no EXE antes de compilar o
setup. Troque `1.0.3` por um número maior que a versão já instalada. Com
`--include-private-env`, também verifica no EXE se as chaves de
Groq, Fish Audio e da ponte foram carregadas do `.env` empacotado. Resultado:
`dist\installer\Emily-Setup-1.0.3.exe` (para o exemplo acima). Instale e teste em
uma conta Windows comum, sem Python no PATH. O gateway pode pedir autorização
do Firewall para acesso pela LAN; o Android precisa apontar para o endereço do
notebook e usar o mesmo `EMILY_PONTE_TOKEN`. A extensão do navegador precisa
ser carregada no Brave/Chrome do notebook, pois extensões não podem ser
instaladas silenciosamente pelo setup.

O setup agora usa o ícone do app Android, textos em português e identidade
visual da Emily. Se já encontrar `Emily.exe` na pasta escolhida, o botão
mostra **Instalar por cima**. Ele substitui os arquivos do programa e limpa
módulos antigos em `_internal`; dados de usuário em `%LOCALAPPDATA%\Emily`
ficam preservados.

## Publicar uma versão posterior

### Mudanças de código e interface sem recompilar

O instalador 1.0.2 já contém o runtime hook que aceita módulos Python soltos
em `_internal`. A versão instalada originalmente só sabe consultar instaladores;
para ativar o novo feed, execute **uma vez** no Windows o arquivo
`ativar_atualizacao_codigo_windows.ps1` incluído no ZIP de fontes. No PowerShell,
na pasta onde você extraiu o ZIP:

```powershell
powershell -ExecutionPolicy Bypass -File .\ativar_atualizacao_codigo_windows.ps1
```

Se o gateway gravado no instalador não for mais o endereço ativo, informe o
endereço atual do túnel:

```powershell
powershell -ExecutionPolicy Bypass -File .\ativar_atualizacao_codigo_windows.ps1 -GatewayUrl https://SEU-GATEWAY-ATUAL
```

Após validar o pacote, o script também grava esse endereço na configuração do
Windows para as próximas atualizações. Mantenha o script em UTF-8 com BOM para
que o Windows PowerShell 5.1 mostre os acentos corretamente.

O script encontra o gateway e o token no instalador privado, verifica o SHA-256
do pacote e instala somente os dois módulos do atualizador. Ele verifica se a
versão instalada é compatível. Depois, feche e abra a Emily: ela baixa, ensaia
e aplica o restante da atualização, guarda backup e reabre. Nas próximas
publicações de código, basta reabrir a Emily.
Se uma publicação também mudar o gateway que roda no notebook, reinicie o
Windows uma vez para carregar o novo processo de segundo plano.

No Fedora, publique com uma versão de código crescente e a versão do instalador
que está no notebook:

```bash
python publicar_windows_codigo.py --version 1 --installer 1.0.2
```

Por padrão o comando inclui todos os módulos Python e recursos publicáveis.
Para uma correção pequena, repita `--file caminho/relativo` para incluir só os
arquivos alterados. O pacote da atualização de regeneração e narração foi
publicado dessa forma, evitando enviar recursos grandes sem necessidade.
Publicações seletivas acumulam os arquivos das versões anteriores do mesmo
instalador. Assim, um notebook que ficou offline pode saltar direto para a
última versão aprovada sem perder patches intermediários. Publicar uma nova
versão substitui o `latest.json` do gateway; apenas versões aprovadas devem
chegar a esse diretório.

Esse fluxo atualiza código Python, interface web e recursos. Mudanças no
bootstrap congelado, no runtime hook, em bibliotecas Python/nativas, WebView2,
FFmpeg ou atalhos do Windows ainda exigem um instalador completo.

### Quando o domínio do ngrok mudar

A partir do pacote de código 15, o Windows consulta ao abrir um registro de
endereço no Firebase Realtime Database. Esse registro contém somente a URL
pública e uma assinatura HMAC; a chave da ponte não é publicada. O Windows
confere a assinatura antes de usar a URL para sincronização e atualizações.

Para alcançar essa versão pela primeira vez após a troca de conta (o domínio antigo já não
responde), execute uma vez, na pasta das fontes onde está o script:

```powershell
powershell -ExecutionPolicy Bypass -File .\ativar_atualizacao_codigo_windows.ps1 -GatewayUrl https://tamper-keenness-huddling.ngrok-free.dev
```

Depois feche e abra a Emily duas vezes: a primeira aplica o pacote; a segunda
já usa a descoberta pelo Firebase. Nas próximas trocas, não é necessário
manter o domínio antigo ativo nem repetir o script. Sem internet/Firebase,
o Windows usa o último endereço salvo e tenta consultar novamente mais tarde.

### Novo instalador completo

Depois de testar o instalador Windows, copie o `.exe` para o Fedora e publique:

```bash
python publicar_windows.py /caminho/Emily-Setup-1.0.3.exe --version 1.0.3
```

O arquivo vai para `~/.local/share/emily/windows-updates`, com manifesto
`latest.json`. A Emily Windows consulta esse mesmo gateway ao abrir. O número
da próxima versão precisa aumentar; o script de build recebe o novo número.

## Se a versão inicial falhar por falta de GROQ_API_KEY

O primeiro pacote incluía o `.env` em `_internal`, mas não o carregava antes
de criar o cliente Groq. A correção está no bootstrap atual. Extraia novamente
o ZIP privado atualizado, execute o build com `--version 1.0.1` e
`--include-private-env`, e instale o novo setup por cima do anterior. Não é
necessário apagar `%LOCALAPPDATA%\Emily` nem desinstalar antes.

Se precisar abrir a versão antiga imediatamente, copie **sem publicar** o
`.env` do ZIP extraído para a pasta que contém `Emily.exe` da instalação,
normalmente `%LOCALAPPDATA%\Programs\Emily`. É uma solução temporária; a
versão recompilada carrega o `.env` que já vem no pacote. O arquivo contém
chaves privadas e deve ficar apenas no notebook de teste.

## Validação ainda necessária no Windows real

- Build PyInstaller e compilação Inno Setup, instalação, atualização,
  desinstalação e preservação de `%LOCALAPPDATA%\Emily`.
- Boot da WebView2, microfone/voz, áudio WASAPI no Android, captura em todos os
  monitores e desempenho do MJPEG.
- Firewall/LAN, chamada do gateway com desktop fechado, Brave e extensão,
  controle de mídia, abertura e fechamento de apps e permissões UAC.
- Credenciais/URLs do `.env` que hoje apontam para serviços em `127.0.0.1` no
  Fedora, além do OmniRoute; esses serviços não estarão automaticamente no
  notebook.
- Ações do gateway Windows ainda sem implementação equivalente: suspender/
  hibernar, estado global de mídia e download direto de YouTube. Elas devolvem
  erro explícito; não executam comandos Linux.
- O índice vetorial Chroma da memória unificada ainda é local a cada PC;
  replicá-lo exige um protocolo próprio para fatos e exclusões, não copiar
  arquivos SQLite/Chroma enquanto os processos estão ativos.

Não há instalador Windows gerado ou validado pelo Fedora. O build antigo em
`emily-windows-instance/` não corresponde ao código atual.

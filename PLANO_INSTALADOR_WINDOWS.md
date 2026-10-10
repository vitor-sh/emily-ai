# Emily no Windows 11: inventário e critérios para o instalador privado

> Este é o inventário inicial. A implementação posterior e o estado de validação
> estão em [WINDOWS_BUILD.md](WINDOWS_BUILD.md). Ainda não existe um instalador
> Windows validado em máquina real.

## Situação verificada em 27/09/2026

O código principal na raiz de `minha-ia/` é a base atual. A pasta
`emily-windows-instance/` é uma cópia antiga: 32 módulos Python de mesmo nome
divergem, 22 módulos atuais não existem nela e seu `Emily.exe` é de junho.
Copiar essa pasta para o notebook deixaria de fora funções recentes.

`build_emily.py` já monta uma pasta PyInstaller `dist/Emily/`, mas usa
`main.py` como entrada, não o `emily_bootstrap.py` e o runtime hook do build
Linux atual. Também apaga `build/` e `dist/` antes de iniciar, não gera um
instalador, não instala dependências externas e omite módulos atuais do
catálogo de imports dinâmicos. `Emily.spec` é um resultado gerado no Fedora,
com caminhos absolutos Linux e backend GTK; não é uma receita Windows.

PyInstaller precisa executar no sistema alvo para gerar binários desse sistema.
O Fedora atual tem Wine, mas não uma instalação Windows de Python e das
bibliotecas nativas da Emily. Um build pelo Wine não substituiria a validação
num Windows 11 real.

## Peças que precisam entrar no pacote

| Camada | Dependências e dados | Estado no Windows |
|---|---|---|
| Interface | `pywebview`, WebView2, `web/`, `img/`, `emilyimage.png`, PyQt6 de fallback, `pystray` | O código tem backend Windows; confirmar WebView2 e bandeja no notebook. |
| Núcleo | Python, módulos atuais da raiz, `emily_cloud/`, `memoria_unificada/`, Hollow Knight, `static/`, `assets/` | PyInstaller deve descobrir imports dinâmicos e arquivos de dados. |
| Voz | PyAudio, SpeechRecognition, Groq, Fish Audio, `davey`, `discord-ext-voice-recv`, RNNoise/Silero e `ffmpeg` | Testar microfone, reprodução e call Discord no Windows real. `ffmpeg` não vem de `requirements.txt`. |
| Visão/automação | `mss`, Pillow, PyAutoGUI, pynput, keyboard, pywin32 | Há backend Windows no `desktop_backend.py`; testar DPI, múltiplos monitores, foco, UAC e permissões. |
| Navegador/pesquisa | Brave API, Playwright Chromium, extensão em `extensao_emily/`, Selenium/ChromeDriver, yt-dlp | Playwright exige os binários do navegador; extensão e sessão Brave não surgem só ao instalar o EXE. |
| Memória unificada | ChromaDB, ONNX Runtime, Ollama local com modelo `embeddinggemma` | `.env` atual habilita a função; notebook limpo não tem Ollama nem o modelo. |
| Acesso remoto | ngrok, token, gateway Flask na porta 5000, backend interno na 5001 | ngrok depende de binário/configuração; gateway atual contém executor Linux. |
| Android | `/llm/*`, `/pc/*`, `/tela/*`, Cloud, push, atualizações | É necessário portar o executor e a captura/stream para Windows e manter o gateway em segundo plano. |
| Configuração privada | `.env`, token do gateway, credenciais de provedores e serviços | O `.env` atual contém endpoints locais do Fedora além de provedores remotos. O pacote de teste deve selecionar endpoints alcançáveis no notebook. |

As dependências Python estão em `requirements.txt`, mas essa lista ainda se
declara “Windows-only” apesar do código atual ser multiplataforma. Há imports
Windows usados em execução (`pywin32`) e bandeja (`pystray`) sem entradas
explícitas nessa lista. `build_emily.py` também menciona `send2trash`, embora
não haja import correspondente no código atual. O build Windows precisa de um
lock/preflight próprio, testado com uma versão definida de Python e wheels
Windows, sem copiar pacotes nativos do Fedora.

## Pontos que hoje impedem equivalência com o Fedora

1. `emily-gateway-service/pc_control.py` se declara executor Linux/KDE e usa
   `systemctl`, `/proc`, `xdg-open`, arquivos `.desktop`, MPRIS e o serviço de
   tela da porta 8790. O app Android chama esse contrato para abrir apps,
   arquivos, sites, controlar mídia, energia e monitorar tarefas. É preciso um
   executor Windows com as mesmas respostas JSON e validações de segurança.
2. `tela-pc-service/tela_pc_service.py` usa PipeWire, portal ScreenCast,
   GStreamer e D-Bus. Um serviço Windows deve implementar ao menos
   `/tela/monitores`, `/tela/jpg`, `/tela/stream`, `/tela/estado` e áudio de PC
   para manter os recursos atuais do Android. `tela_stream.py` do desktop
   também usa Spectacle e KScreen; ele não serve de fallback Windows como está.
3. O gateway é um serviço `systemd --user` no Fedora. No Windows ele precisa
   iniciar com a sessão do usuário e continuar ativo após fechar a janela da
   Emily, sem criar instâncias duplicadas.
4. `memoria.py`, `agenda.py` e `vida_discord.py` gravam arquivos perto do
   próprio módulo. Um instalador em `Program Files` bloquearia escrita por
   usuários comuns. Dados pessoais, logs e segredos devem morar em
   `%LOCALAPPDATA%\\Emily` (ou outro diretório do usuário), separados dos
   executáveis; instalação, atualização e desinstalação precisam preservar
   esses dados de forma previsível.
5. A extensão Brave/Chrome, o ngrok e o Ollama dependem de instalação ou
   configuração adicional. Um instalador que apenas copie o EXE não pode
   prometer que esses recursos estarão prontos num Windows zerado.

## Arquitetura recomendada

- **Build:** Python 3.13 x64 é o ponto de partida para testar os wheels
  nativos da lista atual (PyAudio 0.2.14 e ONNX Runtime 1.29.0 têm wheels
  Windows x64 para essa versão); ainda é preciso resolver todas as
  dependências no próprio Windows. PyInstaller `onedir` gerado no Windows 11
  x64, com
  `emily_bootstrap.py`, runtime hook e inventário automático dos módulos atuais.
  Testar primeiro o EXE sem instalador, inclusive o boot sem console e o log.
- **Setup:** Inno Setup, instalação por usuário com pasta padrão em
  `%LOCALAPPDATA%\\Programs\\Emily`, escolha de caminho, atalho no menu Iniciar,
  desinstalador e opção de iniciar após instalar. A pasta de dados fica fora da
  pasta escolhida. Não usar a cópia `emily-windows-instance/` como fonte.
- **Processos:** app desktop e gateway em executáveis/processos distintos.
  O gateway pode iniciar no logon da conta, com verificação de instância única.
  O serviço de tela Windows pode residir nesse processo ou em outro, desde que
  mantenha o contrato HTTP esperado pelo Android.
- **Distribuição privada:** o instalador de teste pode carregar credenciais
  mediante opção explícita de build, mas não deve incluir backups, caches nem
  históricos por acidente. Um pacote PyInstaller não esconde as chaves: elas
  continuam extraíveis. A configuração dos endpoints locais precisa ser revista.

## Validação necessária antes de chamar de pronto

1. Build Windows limpo, assinatura/arquitetura e instalação/desinstalação com
   caminho padrão e personalizado; reabrir app após reiniciar o notebook.
2. Interface, chat, busca, arquivos, agente visual, captura de cada monitor,
   voz, Discord, memória, mídia e navegador em uma conta Windows sem Python.
3. Gateway ativo com app aberto e fechado; Android conversa, usa ferramentas
   do PC, transmite tela/áudio e monitora uma tarefa até resultado/cancelamento.
4. Falhas de rede e ausência de Ollama/extensão/ngrok mostram erro claro sem
   travar a Emily. Nenhuma rotina Windows deve chamar comandos Linux.
5. Reinstalação da mesma versão e atualização para versão seguinte preservam
   dados sem duplicar processos nem copiar segredos para logs.

Até existir um build e esses testes no Windows 11, a pasta PyInstaller atual
é um protótipo de empacotamento, não um instalador funcional equivalente ao
ambiente Fedora.

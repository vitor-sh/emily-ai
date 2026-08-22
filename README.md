# Emily — Assistente Pessoal com IA

Emily é uma assistente pessoal completa desenvolvida em Python, com voz, visão de tela, automação do PC, agentes autônomos e integração com Discord. Ela foi criada pra ser usada no dia a dia, respondendo por voz, executando tarefas no sistema, analisando a tela em tempo real, controlando o mouse e teclado autonomamente e muito mais.

## Funcionalidades

**Voz e Áudio**
- Captura de voz via Push-to-Talk (PTT) configurável (teclado ou mouse)
- Transcrição de fala com Whisper via Groq (Whisper Large V3 Turbo)
- Síntese de voz (TTS) com Fish Audio — voz clonada, suporte a streaming
- Reprodução de áudio em streaming — Emily começa a falar enquanto ainda está gerando a resposta
- Tecla de atalho (`*`) para interromper a fala a qualquer momento
- Modo Escrito — Emily digita o que o usuário fala, via clipboard

**Inteligência e Conversa**
- Conversa natural em português brasileiro via LLM (Claude, pelo plano Kiro, através de um gateway local)
- Histórico de conversa com limite automático de mensagens
- Memória persistente — lembra fatos sobre o usuário entre sessões, com deduplicação semântica via LLM
- Personalidade própria e consistente (tsundere), configurada inteiramente via system prompt
- Fallback inteligente — detecta intenções complexas e executa automaticamente sem precisar de palavra-chave exata

**Visão de Tela**
- Captura e análise de tela em tempo real
- Responde perguntas sobre o que está na tela
- Modo de monitoramento automático com triagem inteligente — só comenta quando algo relevante acontece
- Triagem específica para jogos — detecta game over, boss, cutscene, conquistas
- Tradução automática de textos visíveis na tela para português
- Análise de sequência de prints (como um vídeo curto)
- Suporte a múltiplos monitores com troca dinâmica

**Agente de Controle de Tela (UI)**
- Controla o mouse e teclado de forma autônoma via visão computacional
- Recebe objetivo em linguagem natural e executa passo a passo na tela
- Detecção automática de loop — evita repetir a mesma ação travada
- Suporte a interrução ao vivo: o usuário fala durante a execução e o agente ajusta o comportamento
- Pode ser pausado, retomado e parado a qualquer momento por voz ou texto
- Suporte a UAC (tela de permissão do Windows) com espera automática

**Automação do PC**
- Abertura e fechamento de aplicativos por nome (com busca fuzzy)
- Busca de jogos em Steam, Epic Games, GOG e Program Files
- Operações de arquivo: mover, copiar, renomear, deletar, extrair ZIP
- Abertura de sites e pesquisas no navegador padrão
- Controle de janelas: minimizar, maximizar, fechar abas
- Controle de mídia: tocar músicas, pausar, próxima, volume
- Sistema de modos configuráveis (ex: modo Gameplay, modo Programação)
- Suporte a sequências de inputs automáticos (macros/speedrun)
- Sistema de desfazer (undo) para operações de arquivo
- Detecção de downloads concluídos com pergunta automática para extrair arquivos

**Pesquisa na Internet**
- Integração com Brave Search API para pesquisas reais
- Scraping automático do conteúdo completo da primeira página encontrada
- Resultado resumido pela LLM de forma natural e direta

**Integração com Discord**
- Bot conectado a servidores Discord
- Entra automaticamente no canal de voz quando o usuário entra
- Responde comandos e conversas via canal de texto
- Identifica diferentes usuários e adapta as respostas
- Reproduz a voz da Emily no canal de voz do servidor
- Modo de escuta ativável/desativável por comando de voz
- Personalidade adaptada para Discord — mais curta, informal, com abreviações naturais

**Notificações de WhatsApp**
- Monitora o WhatsApp Web em tempo real via Selenium (conectado ao Brave)
- Avisa o usuário por voz quando chega uma mensagem nova
- Cooldown por contato para evitar spam de avisos
- Lê o nome do contato e trecho da mensagem

**Controle Remoto pelo Celular**
- Servidor Flask embutido que expõe uma interface web responsiva
- Compatível com celular como PWA (Progressive Web App)
- Envio de comandos por texto ou por voz (microfone do celular)
- Recebe a voz da Emily em tempo real no celular (long-polling com áudio WAV)
- Stream de tela ao vivo via MJPEG — veja o PC no celular em tempo real
- Qualidade do stream configurável (HQ/LQ)
- Acesso remoto via ngrok (sem configuração de rede/roteador)
- Atalhos rápidos pré-configurados na interface

**Interface Gráfica**
- Janela com status em tempo real (aguardando, ouvindo, gravando, falando, monitorando)
- Chat com histórico de mensagens
- Entrada de texto manual como alternativa à voz
- Controle de monitoramento de tela pela interface
- Sprite animado por GIFs por estado (idle, talk, screen, search, etc.)

## Tecnologias Utilizadas

| Componente | Tecnologia |
|---|---|
| LLM (conversa, texto e visão) | Claude Sonnet 5 via kiro-gateway (plano Kiro) |
| Agente de UI | Claude Opus 5 via kiro-gateway |
| Classificadores e triagem de tela | Claude Haiku 4.5 via kiro-gateway |
| Plano B de LLM | NVIDIA NIM — GLM-5.2 e nemotron-nano-vl (uma linha de `.env`) |
| Transcrição de voz | Groq — Whisper Large V3 Turbo |
| Síntese de voz (TTS) | Fish Audio (voz clonada) |
| Pesquisa na internet | Brave Search API + scraping |
| Interface gráfica | Tkinter + Pillow (PIL) |
| Áudio | PyAudio + pygame |
| Discord | discord.py |
| Automação Windows | pywin32, keyboard, pynput, pyautogui, subprocess |
| Notificações WhatsApp | Selenium (Brave com remote debugging) |
| Servidor remoto | Flask + ngrok |
| Captura de tela | mss |

## Assets Visuais

A interface usa GIFs animados para o sprite da Emily, que ficam na pasta `img/` dentro do projeto. Esses arquivos não estão incluídos no repositório por serem assets pessoais. Para rodar o projeto, crie a pasta `img/` e adicione seus próprios GIFs nomeados conforme os estados:

- `idle.gif` — estado parado/aguardando
- `talk.gif` — falando
- `uping.gif` — transição
- `screen.gif` — monitorando tela
- `search.gif` — pesquisando
- `open.gif` — abrindo app
- `transfer.gif` — transferindo arquivo

Se a pasta não existir ou os GIFs estiverem faltando, o sprite simplesmente não aparece mas o resto do sistema funciona normalmente.

## Estrutura do Projeto

```
minha-ia/
├── main.py               # Orquestra todos os módulos, threads e modos
├── llm.py                # Camada ÚNICA de acesso a LLM: provedores, rotas, rate limit
├── gateway.py            # Ciclo de vida do kiro-gateway (sobe, checa, derruba)
├── modelo.py             # Personalidade, visão, decisões — adaptador sobre o llm.py
├── ferramentas.py        # Catálogo de ferramentas que o modelo pode chamar
├── voz.py                # TTS (Fish Audio), transcrição (Groq), captura PTT
├── automacao.py          # Interpretação e execução de comandos no PC
├── visao.py              # Captura de tela, grade de precisão e troca de monitor
├── interface.py          # Janela gráfica, chat, controles
├── memoria.py            # Persistência de memória com deduplicação semântica
├── pesquisa.py           # Pesquisa real via Brave Search API + scraping
├── discord_bot.py        # Integração completa com Discord (texto + voz)
├── intencoes.py          # Detecção de intenções especiais (fechar, modo escrito, etc.)
├── agente_ui.py          # Agente autônomo de controle de tela (mouse/teclado por visão)
├── agente_jogo.py        # Agente que decide teclas a partir da tela do jogo
├── servidor.py           # Servidor Flask para controle remoto pelo celular
├── notificacoes.py       # Monitor de WhatsApp Web via Selenium
├── build_emily.py        # Script de build para gerar o executável (.exe)
├── diagnostico_whatsapp.py # Ferramenta de diagnóstico do monitor WhatsApp
├── kiro_gateway/         # Proxy local que expõe os modelos Claude do plano Kiro
├── testes/               # Suíte de testes de propriedade (pytest + hypothesis)
├── static/
│   └── index.html        # Interface web PWA para controle pelo celular
└── img/                  # GIFs do sprite (não incluídos no repositório)
```

Os arquivos `_teste_*.py` e `_bench_*.py` na raiz são scripts de verificação
manual, cada um focado num aspecto (streaming, tool calling, visão, grade do
agente). Rodam soltos com `python _nome.py` e servem para medir contra o
endpoint de verdade — diferente da suíte em `testes/`, que não toca a rede.

## Como a camada de LLM funciona

Toda chamada de LLM do projeto passa pelo `llm.py`. Nenhum outro módulo
instancia cliente de modelo, e é isso que faz trocar de provedor ser edição de
tabela em vez de caça a chamadas espalhadas.

```
consumidores (modelo.py, automacao.py, memoria.py, agente_ui.py, ...)
        ↓
    llm.chamar(mensagens, rota_nome=...)
        ↓
    tabela ROTAS  →  provedor  →  endpoint
```

**Rotas** são tarefas, não modelos. Cada uma tem seu próprio modelo, orçamento
de tokens, temperatura e esforço de raciocínio:

| Rota | Para que serve | Modelo |
|---|---|---|
| `conversa` | fala com o Vitor por voz | Claude Sonnet 5 |
| `discord` | responde no servidor | Claude Sonnet 5 |
| `comando` | interpreta pedido em JSON | Claude Sonnet 5 |
| `extracao` | tira fatos da conversa pra memória | Claude Sonnet 5 |
| `visao` | descreve e comenta a tela | Claude Sonnet 5 |
| `classificador` | decisões SIM/NAO curtas | Claude Haiku 4.5 |
| `triagem_visual` | "vale comentar essa tela?" | Claude Haiku 4.5 |
| `agente_ui` | aponta onde clicar na tela | Claude Opus 5 |
| `agente_jogo` | decide tecla durante gameplay | Claude Sonnet 5 |

O gateway é um **subprocesso local**: o `gateway.py` sobe `python main.py`
dentro de `kiro_gateway/` quando a Emily inicia, espera o `/health` responder, e
derruba no fim. Se o gateway cair no meio do uso, a próxima chamada de LLM o
religa sozinha.

**Diagnóstico:** `python llm.py` testa todas as rotas contra o endpoint real e
diz o que funcionou. `python gateway.py` testa só o ciclo de vida do proxy.

**Reversão:** `EMILY_PROVEDOR_LLM=nvidia` no `.env` devolve as nove rotas para o
NVIDIA NIM sem tocar em código.

## Instalação

**Requisitos**
- Python 3.10 ou superior
- Windows (a automação e alguns recursos de áudio são específicos para Windows)
- ffmpeg instalado e no PATH do sistema
- [Kiro IDE](https://kiro.dev/) instalado e com login feito — é de onde sai a
  credencial que o gateway usa

**Instale as dependências:**
```bash
pip install -r requirements.txt
playwright install chromium
```

**Configure o gateway do Kiro** (uma vez só):
```bash
python _setup_gateway_env.py
```

Esse script gera uma senha aleatória para o proxy local, escreve o
`kiro_gateway/.env` com os ajustes que a Emily precisa, e acrescenta as chaves
correspondentes no `.env` da Emily. A senha nunca é impressa na tela.

Se a sua conta Kiro for corporativa (`authMethod: IdC` / `provider: Enterprise`),
o arquivo de credencial não traz o `profileArn` e o endpoint de chat recusa a
requisição com `HTTP 400 profileArn is required`. Nesse caso:

```bash
python _teste_achar_arn.py          # varre logs e configs do Kiro procurando o ARN
python _teste_arn_qual_funciona.py  # testa qual ARN responde e grava no .env
```

**Confirme que está tudo de pé:**
```bash
python _teste_gateway_modelos.py    # lista os modelos que a sua conta libera
python llm.py                       # testa as nove rotas contra o endpoint real
```

**Configure o arquivo `.env`** na pasta `minha-ia/` com suas chaves de API:
```
# Transcrição de voz
GROQ_API_KEY=sua_chave_aqui

# Síntese de voz
FISH_AUDIO_KEY=sua_chave_aqui

# Pesquisa na internet
BRAVE_API_KEY=sua_chave_aqui

# ── LLM: gateway do Kiro ──────────────────────────────────────────
# Estas cinco são escritas pelo _setup_gateway_env.py. A KIRO_PROXY_API_KEY
# tem que ser IGUAL ao PROXY_API_KEY do kiro_gateway/.env.
KIRO_PROXY_API_KEY=senha_gerada_pelo_script
EMILY_PROVEDOR_LLM=kiro
EMILY_KIRO_URL=http://127.0.0.1:8000
EMILY_KIRO_TIMEOUT=300
EMILY_KIRO_RPM=30

# Um modelo por grupo de rota. Trocar aqui não exige tocar em código.
EMILY_KIRO_MODELO_CONVERSA=claude-sonnet-5
EMILY_KIRO_MODELO_VISAO=claude-sonnet-5
EMILY_KIRO_MODELO_AGENTE_UI=claude-opus-5
EMILY_KIRO_MODELO_AGENTE_JOGO=claude-sonnet-5
EMILY_KIRO_MODELO_BARATO=claude-haiku-4.5

# (Opcional — plano B se o Kiro sair do ar)
NVIDIA_API_KEY=sua_chave_aqui
```

**Variáveis opcionais do gateway:**

| Variável | Default | Para que serve |
|---|---|---|
| `EMILY_GATEWAY_AUTOSTART` | `1` | `0` faz a Emily não subir o gateway (você sobe à mão) |
| `EMILY_GATEWAY_PYTHON` | — | caminho do Python que roda o gateway; obrigatório no `.exe` |
| `EMILY_GATEWAY_TIMEOUT_BOOT` | `60` | quanto esperar o `/health` responder |
| `EMILY_GATEWAY_TTL_HEALTH` | `20` | por quanto tempo confiar no último health positivo |
| `EMILY_GATEWAY_PASTA` | `kiro_gateway` | onde está o código do proxy |

**Execute:**
```bash
cd minha-ia
python main.py
```

O gateway sobe junto, sem janela de terminal. Se ele falhar, a Emily continua
funcionando no resto (interface, voz, Discord, automação) e **fala** qual é o
problema.

## Quando a credencial do Kiro expira

O token do Kiro IDE tem validade curta. Quando vence, a Emily fala:

> "Vitor, o login do Kiro expirou. Abre o Kiro e faz login de novo que eu volto
> a funcionar."

O procedimento é exatamente esse: abrir o Kiro IDE e fazer login. Não precisa
reiniciar a Emily — o `garantir()` é idempotente e a próxima chamada de LLM sobe
o gateway de novo com a credencial nova.

Se a mensagem persistir depois do login, o log do subprocesso tem a causa:
```
kiro_gateway/gateway.log
```

Outras frases e o que cada uma significa:

| A Emily diz | Causa | O que fazer |
|---|---|---|
| "o login do Kiro expirou" | token vencido ou credencial inválida | login no Kiro IDE |
| "tem outra coisa usando a porta" | algo já ocupa a 8000 | fechar o programa ou mudar `EMILY_KIRO_URL` |
| "meu gateway não subiu" | falha genérica de boot | ler `kiro_gateway/gateway.log` |
| "não achei um Python pra subir meu gateway" | modo empacotado sem interpretador | definir `EMILY_GATEWAY_PYTHON` |
| "a pasta do meu gateway não tá aqui" | `kiro_gateway/` ausente | conferir a instalação |

## Controle Remoto pelo Celular

1. Rode a Emily normalmente com `python main.py`
2. O servidor já inicia automaticamente na porta `5000`
3. Instale o ngrok: https://ngrok.com/download
4. Em outro terminal, rode: `ngrok http 5000`
5. Acesse a URL gerada pelo ngrok no celular
6. Na primeira vez, toque no ícone ⚙ e cole a URL do ngrok

A interface funciona como PWA — no iOS/Android você pode "Adicionar à tela inicial" para usar como app nativo.

## Configuração do Discord (opcional)

Após rodar pela primeira vez, um arquivo `~/.emily_discord.json` será criado. Preencha com:
- Token do bot Discord
- ID do canal de texto
- ID do canal de voz
- Seu ID de usuário do Discord (para detecção automática de entrada em call)

## Configuração do WhatsApp Web (opcional)

Para receber notificações de mensagens por voz:

1. Abra o Brave com debugging ativado:
   ```
   brave.exe --remote-debugging-port=9222
   ```
2. Acesse `web.whatsapp.com` no Brave e faça login
3. A Emily vai se conectar automaticamente e monitorar mensagens novas

O arquivo `diagnostico_whatsapp.py` pode ser rodado separadamente para verificar se a conexão com o Brave está funcionando.

## APIs Necessárias

| Serviço | Uso | Plano gratuito |
|---|---|---|
| Kiro | LLM de conversa, visão e agentes | Sim, com limite; o projeto usa o plano pago |
| Groq | Transcrição de voz (Whisper) | Sim (generoso) |
| Fish Audio | Síntese de voz com voz clonada | Não (custo por uso) |
| Brave Search | Pesquisa na internet | Sim (2.000 req/mês grátis) |
| NVIDIA NIM | Plano B de LLM | Sim (40 req/min) |

**Sobre consumo de crédito do Kiro:** cada chamada consome crédito com
multiplicador por modelo — Sonnet 5 custa 1,3x, Opus 5 custa 2,2x, Haiku 4.5 é o
mais barato. A rota que mais dispara é a `triagem_visual`, no monitoramento de
tela: medido em ~9,6 chamadas por minuto quando a tela muda sem parar. O
`loop_visao` só chama a LLM quando a assinatura do frame muda, então tela parada
custa zero — mas jogo é o pior caso. Se o crédito apertar no meio do mês, a
`triagem_visual` é a primeira candidata a voltar pro NIM.

## Modos de Operação

| Modo | Como ativar | O que faz |
|---|---|---|
| Normal | Padrão | Conversa, automação, pesquisa |
| Controle de Tela | "modo controle de tela" | Agente autônomo controla o mouse/teclado |
| Monitoramento de Jogo | "monitora o jogo" | Observa a tela e comenta eventos importantes |
| Modo Escrito | "ativa modo escrito" | Digita automaticamente o que o usuário falar |
| Escuta Discord | "ouve o discord" | Responde mensagens do Discord em tempo real |

## Testes

A suíte de testes de propriedade fica em `testes/` e não toca a rede:

```bash
python -m pytest testes/ -q
```

São 84 testes cobrindo o ciclo de vida do gateway (um processo e não vários sob
concorrência, gateway subido à mão sobrevive, ambiente do subprocesso não vaza
configuração), a estrutura das tabelas de rotas (paridade entre Kiro e NIM,
seleção por variável de ambiente) e o tool calling (ferramenta no fim do stream
é sempre executada, texto puro não inventa ferramenta).

Os scripts na raiz medem contra o endpoint de verdade e consomem crédito:

```bash
python _teste_gateway_smoke.py       # streaming e visão
python _teste_task8_ferramenta_real.py  # tool calling ponta a ponta
python _bench_visao.py               # compara modelos de visão
python _bench_grade.py               # precisão de localização do agente de UI
```

## Observações

- O arquivo `.env` nunca deve ser compartilhado ou enviado ao repositório
- O `kiro_gateway/.env`, `credentials.json` e `state.json` também carregam
  credencial e estão no `.gitignore`
- Os arquivos de cache (`.emily_*.json`) são gerados localmente e armazenam dados pessoais — não estão incluídos no repositório
- O arquivo `memoria.json` guarda os fatos aprendidos sobre o usuário — não inclua no repositório
- A tecla PTT padrão é o botão lateral do mouse (MB5), configurável em `voz.py`
- A tecla para calar a Emily é `*` no teclado numérico, configurável em `voz.py`
- O agente de UI usa PyAutoGUI com FAILSAFE ativo — mova o mouse pro canto superior esquerdo para parar de emergência
- O modelo de automação usa cache local para acelerar comandos repetidos
- O stream de tela pelo celular consume mais CPU — feche quando não estiver usando

## Build (executável .exe)

Para gerar o executável standalone:
```bash
cd minha-ia
python build_emily.py
```

O executável fica em `dist/Emily/Emily.exe`.

**Duas coisas específicas do gateway no modo empacotado:**

O gateway roda como subprocesso com um interpretador **externo** — não é o
`Emily.exe`. Por isso o `build_emily.py` inclui o código de `kiro_gateway/` como
dado (o subprocesso precisa dos arquivos no disco), mas as dependências do
gateway (`fastapi`, `uvicorn`, `httpx`, `loguru`, `tiktoken`) precisam estar
instaladas no **Python do sistema**, não empacotadas. Empacotá-las não faria
diferença: quem as importa é outro processo.

E o `sys.executable`, dentro do exe, aponta para o próprio `Emily.exe`. Se fosse
usado para subir o gateway, a Emily tentaria subir outra Emily. O `gateway.py`
resolve o interpretador nesta ordem:

1. `EMILY_GATEWAY_PYTHON` (caminho explícito) — **recomendado no exe**
2. `sys.executable`, só quando NÃO está empacotado
3. `python`, `python3` ou `py` no PATH

Se nada resolver, a Emily fala "não achei um Python pra subir meu gateway".

**Aviso de segredo:** o build inclui o `.env` da Emily e o `kiro_gateway/.env`
dentro da pasta do executável, porque sem eles nada sobe. Isso significa que a
pasta `dist/Emily/` contém suas chaves de API e a credencial do proxy — não
compartilhe o executável.

## Autor

Desenvolvido por Vitor como projeto pessoal de assistente com IA.

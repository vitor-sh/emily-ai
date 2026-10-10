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
- Conversa natural em português brasileiro via LLM (Claude, por um endpoint OpenAI-compatible)
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
- Pesquisa invisível, sem abrir navegador, janela ou aba no computador
- Brave LLM Context + Web Search paginada com snippets adicionais
- Expansão adaptativa: compara vários sites e busca páginas/consultas extras quando a cobertura é fraca
- Leitura HTTP concorrente e Playwright headless opcional para complementar páginas difíceis
- Fontes deduplicadas por URL e domínio, preparadas para a LLM comparar concordâncias e divergências

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
- Janela nativa sem borda, com a barra de título desenhada na própria interface
- Chat com markdown de verdade: negrito, listas, código inline e bloco de código com botão de copiar
- Ações por mensagem no hover: copiar, regenerar a resposta, apagar
- Conversas com renomear (edição no lugar), apagar, buscar e agrupamento por data
- Título da conversa gerado por LLM a partir da primeira mensagem
- Progresso das ferramentas em tempo real, passo por passo, com resultado
- Configurações em coluna única: apps, automação, modos, memória e uso do PC
- Atalhos: Ctrl+N nova conversa, Ctrl+K buscar, Ctrl+B recolher a barra, Ctrl+, configurações
- Respeita "reduzir movimento" do Windows: com a opção ligada, nenhuma animação roda

## Tecnologias Utilizadas

| Componente | Tecnologia |
|---|---|
| Interface | pywebview + WebView2 (HTML/CSS/JS numa janela nativa) |
| LLM (conversa, texto, visão e agentes) | Claude via endpoint OpenAI-compatible (`EMILY_CLAUDE_URL`) |
| Plano B de LLM | NVIDIA NIM — GLM-5.2 e nemotron-nano-vl (uma linha de `.env`) |
| Transcrição de voz | Groq — Whisper Large V3 Turbo |
| Síntese de voz (TTS) | Fish Audio (voz clonada) |
| Pesquisa na internet | Brave LLM Context + Web Search + HTTP/Playwright headless |
| Interface antiga (fallback) | PyQt6 |
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
├── modelo.py             # Personalidade, visão, decisões — adaptador sobre o llm.py
├── fala_stream.py        # Fatia a resposta em frases faladas durante o streaming
├── frases_acao.py        # Frases curtas ditas enquanto uma ação executa
├── ferramentas.py        # Catálogo de ferramentas que o modelo pode chamar
├── busca_pc.py           # Varredura dos discos da ferramenta procurar_no_pc
├── laco_ferramentas.py   # Motor que executa as ferramentas pedidas pelo modelo
├── interface_web.py      # A interface: janela nativa hospedando HTML/CSS/JS
├── web/                  # A tela em si (index.html, estilo.css, app.js)
├── interface.py          # Interface ANTIGA em PyQt6, volta com EMILY_UI=qt
├── voz.py                # TTS (Fish Audio), transcrição (Groq), captura PTT
├── automacao.py          # Interpretação e execução de comandos no PC
├── busca_jogos.py        # Normalização de nomes e busca de jogos (Steam, Epic, GOG)
├── desfazer.py           # Desfazer operações de arquivo e envio à lixeira
├── visao.py              # Captura de tela, grade de precisão e troca de monitor
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
├── testes/               # Suíte de testes de propriedade (pytest + hypothesis)
├── testes_manuais/       # Scripts de verificação manual (_teste_*.py)
├── static/
│   └── index.html        # Interface web PWA para controle pelo celular
└── img/                  # GIFs do sprite (não incluídos no repositório)
```

Os arquivos `_teste_*.py` em `testes_manuais/` são scripts de verificação manual, cada um
focado num aspecto (streaming, tool calling, laço de ferramentas). Rodam soltos
com `python testes_manuais/_nome.py` — diferente da suíte em `testes/`, que não toca a rede.

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

| Rota | Para que serve | max_tokens |
|---|---|---|
| `conversa` | fala com o Vitor por voz | 1024 |
| `discord` | responde no servidor | 200 |
| `comando` | interpreta pedido em JSON | 512 |
| `extracao` | tira fatos da conversa pra memória | 300 |
| `visao` | descreve e comenta a tela | 1024 |
| `classificador` | decisões SIM/NAO curtas | 16 |
| `triagem_visual` | "vale comentar essa tela?" | 16 |
| `agente_ui` | aponta onde clicar na tela | 1024 |
| `agente_jogo` | decide tecla durante gameplay | 2048 |

Todas as nove rotas usam o mesmo modelo (`EMILY_CLAUDE_MODELO`, hoje
`claude-opus-4-8`), porque é o que o endpoint serve. Trocar de modelo é editar
essa única variável no `.env`; o que muda por rota é orçamento de token,
temperatura e raciocínio.

**Diagnóstico:** `python llm.py` testa todas as rotas contra o endpoint real e
diz o que funcionou.

**Plano B:** `EMILY_PROVEDOR_LLM=nvidia` no `.env` devolve as nove rotas para o
NVIDIA NIM sem tocar em código. Vale saber o que se perde: o modelo de visão do
NIM é mais rápido e sai de graça, mas lê a tela pior — medido alucinando o
conteúdo de um editor de texto aberto.

## A interface

A tela é HTML/CSS/JS rodando na WebView2 — o Edge que já vem no Windows 10/11 —
dentro de uma janela nativa aberta pelo pywebview. Um processo só, tudo em
Python, sem Node e sem Chromium empacotado.

**Por que não é mais PyQt.** O Qt Style Sheets não suporta `transition`,
`animation`, `@keyframes` nem `box-shadow`. Cada fade e cada hover suave teria
que ser uma `QPropertyAnimation` escrita à mão, por propriedade, por widget — a
interface antiga tinha 15 regras `:hover` e zero animações, e não por falta de
esforço. Em CSS é uma linha.

**O contrato não mudou.** O `main.py` chama nove coisas na janela:
`atualizar_status` (103 vezes), `mostrar_opcao_salvar`, `add_imagem_chat_safe`,
`progresso_evento`, `iniciar`, `root`/`_painel` e os quatro callbacks. O
`interface_web.py` implementa os mesmos nove pontos, então trocar a interface não
encostou em `modelo.py`, `automacao.py`, `ferramentas.py` nem no laço de voz.

**Mexer no design sem subir a Emily inteira:**
```bash
python interface_web.py
```
Abre só a janela, com uma conversa de demonstração passando pela ponte de
verdade. E servindo a pasta `web/` por HTTP (`python -m http.server -d web`), o
`app.js` entra em "modo oficina" com dados de amostra — dá pra iterar CSS no
navegador com DevTools.

| Variável | Default | Para que serve |
|---|---|---|
| `EMILY_UI` | `web` | `qt` volta pra interface antiga (`interface.py`) |
| `EMILY_UI_DEBUG` | `0` | `1` abre o DevTools da WebView2 junto da janela |
| `EMILY_USUARIO` | `Vitor` | nome no cumprimento e no rodapé |

Se o pywebview faltar ou a WebView2 não existir, o `main.py` cai na interface
antiga sozinho em vez de não abrir.

## Tool calling: catálogo em camadas
A Emily tem 148 ferramentas registradas. Mandar todas em toda chamada custava
~23.500 tokens de entrada — 91% do prompt — e obrigava o modelo a escolher entre
148 opções, sendo que 106 delas são administração do Discord e operação do
servidor de Minecraft.

Por isso o catálogo tem duas camadas:

| Caminho | O que vai na mesa | Custo |
|---|---|---|
| Conversa por voz | grupo `geral` (36) + `abrir_ferramentas` | ~5.100 tokens |
| Discord | grupo `discord` (53) | ~9.500 tokens |
| Discord autorizado | `discord` + `servidor` (106) | ~19.800 tokens |
| Chat do Minecraft | uma ferramenta escolhida a dedo | ~300 tokens |

Quando o pedido por voz é de Discord ou de Minecraft, o modelo chama
`abrir_ferramentas(dominio)` e aquele grupo entra na mesa da chamada seguinte,
ficando lá por `EMILY_TURNOS_DOMINIO_ABERTO` turnos (default 3). Custa uma ida
extra ao modelo nesses casos e economiza 76% da entrada em todo o resto.

O que a Emily já executou não fica na conversa: vai num registro estruturado
(nome, argumentos e resultado) renderizado num bloco do system prompt. Antes era
uma nota de texto no meio do diálogo, cortada em 200 caracteres e sem o nome da
ferramenta.

### O motor de execução

Os três caminhos de tool calling (voz, Discord, chat do Minecraft) tinham cada um
sua própria cópia da mecânica — montar o turno, travar repetição, executar,
decidir se algo mudou. As cópias divergiram: a de voz registrava as ações e não
decidia "agiu"; a do Discord decidia "agiu" e não registrava nada. Cada uma tinha
metade dos consertos da outra.

Agora a mecânica é uma só, em [laco_ferramentas.py](laco_ferramentas.py). A
política de cada caminho (o que falar, quando obrigar ferramenta, TTS ou chat)
fica no `modelo.py`, onde as diferenças são de propósito.

**"Ela agiu?" agora é fato.** Toda ferramenta devolve um `ResultadoFerramenta`
com `ok` e `mudou`. Antes esse booleano saía de reconhecer o português do
resultado, com uma lista de 24 frases — e errava todos os casos mecânicos:

| situação | antes | agora |
|---|---|---|
| ferramenta levantou exceção | contava como feito | `ok=False` |
| argumento obrigatório faltando | contava como feito | `ok=False` |
| ferramenta não existe no catálogo | contava como feito | `ok=False` |
| ferramenta recusou por regra de domínio | às vezes | `recusa()` declara |

Isso importa porque é esse booleano que a máquina de promessa lê: marcado como
cumprido, o pedido não é cobrado no turno seguinte e morre calado.

Ferramenta que só lê e espera rede pode rodar em paralelo quando o modelo pede
várias na mesma resposta (`Ferramenta.paralelizavel`). São 7 hoje — pesquisa,
visão, tradução de tela, busca no PC. Todo o resto roda em série de propósito:
duas ferramentas de automação ao mesmo tempo disputam o mouse e desrespeitam a
ordem em que o pedido foi feito.

### Como escrever a descrição de uma ferramenta

A descrição É o contrato. O modelo não tem outra fonte pra saber quando usar cada
uma, e descrição curta transfere pra ele a tarefa de adivinhar. O padrão usado
aqui tem três partes:

1. **O que faz**, incluindo o efeito colateral que importa ("ele SAI do lugar
   antigo").
2. **Quando usar**, com as palavras que o Vitor de fato fala ("mover, jogar pra,
   tirar daqui e pôr lá").
3. **Quando NÃO usar**, nomeando a ferramenta rival. Toda ferramenta que compete
   com outra tem que dizer isso — é o que resolve a confusão de verdade.

Todo parâmetro tem `description` própria, dizendo o que aceita e o que acontece
se vier vazio. Sem isso o modelo não sabe, por exemplo, que `dentro_de` aceita
tanto "downloads" quanto um caminho completo, nem que deixar vazio faz ela
procurar sozinha.

E granularidade: se duas ferramentas só se distinguem pelo prefixo do nome, elas
são uma ferramenta com um argumento. Os oito `ativar_*`/`desativar_*` de modo
viraram um `definir_modo(modo, ligar)`.

| Variável | Default | Para que serve |
|---|---|---|
| `EMILY_CATALOGO_COMPLETO` | `0` | `1` volta a mandar as 148 em toda chamada |
| `EMILY_TURNOS_DOMINIO_ABERTO` | `3` | por quantos turnos um domínio aberto continua na mesa |
| `EMILY_MAX_ACOES_REGISTRADAS` | `8` | quantas ferramentas executadas ela lembra |

## Instalação

**Requisitos**
- Python 3.10 ou superior
- Windows (a automação e alguns recursos de áudio são específicos para Windows)
- ffmpeg instalado e no PATH do sistema

**Instale as dependências:**
```bash
pip install -r requirements.txt
playwright install chromium
```

**Confirme que está tudo de pé:**
```bash
python llm.py
```

**Configure o arquivo `.env`** na pasta `minha-ia/` com suas chaves de API:
```
# Transcrição de voz
GROQ_API_KEY=sua_chave_aqui

# Síntese de voz
FISH_AUDIO_KEY=sua_chave_aqui

# Pesquisa na internet
BRAVE_API_KEY=sua_chave_aqui

# ── LLM: endpoint OpenAI-compatible que serve o Claude ────────────
EMILY_PROVEDOR_LLM=claude
EMILY_CLAUDE_URL=https://seu-endpoint/v1
CLAUDE_API_KEY=sua_chave_aqui
EMILY_CLAUDE_MODELO=claude-opus-4-8
EMILY_CLAUDE_TIMEOUT=300
EMILY_CLAUDE_RPM=30

# (Opcional — plano B se o endpoint sair do ar)
NVIDIA_API_KEY=sua_chave_aqui
```

O `/v1` no fim do `EMILY_CLAUDE_URL` é opcional: o `llm.py` normaliza a URL e
aceita com ou sem, justamente pra não dar 404 em toda chamada por causa de um
`/v1/v1`.

**Execute:**
```bash
cd minha-ia
python main.py
```

## Quando o LLM não responde

Se a chamada de LLM falhar de vez, a Emily **fala** que não conseguiu em vez de
emudecer:

> "Tive um problema pra acessar meu modelo agora."

O motivo específico fica no console, com o prefixo `[LLM]`: chave recusada
(401/403), limite de requisição (429), timeout, ou resposta vazia por orçamento
de token curto. A camada nunca engole exceção em silêncio — falha muda foi o bug
mais difícil deste projeto.

Para testar sem subir a Emily inteira:
```bash
python llm.py
```

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
| Endpoint do Claude | LLM de conversa, visão e agentes | Não (é o provedor principal) |
| Groq | Transcrição de voz (Whisper) | Sim (generoso) |
| Fish Audio | Síntese de voz com voz clonada | Não (custo por uso) |
| Brave Search | Pesquisa na internet | Sim (2.000 req/mês grátis) |
| NVIDIA NIM | Plano B de LLM | Sim (40 req/min) |

**Sobre consumo:** a rota que mais dispara é a `triagem_visual`, no
monitoramento de tela: medido em ~9,6 chamadas por minuto quando a tela muda sem
parar. O `loop_visao` só chama a LLM quando a assinatura do frame muda, então
tela parada custa zero — mas jogo é o pior caso. Se o custo apertar, a
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

São 45 testes cobrindo a estrutura das tabelas de rotas (paridade entre a tabela
do provedor atual e a do NIM, seleção por variável de ambiente, modelo
sobrescritível por `.env`) e o tool calling (ferramenta no fim do stream é sempre
executada, texto puro não inventa ferramenta).

Os scripts na raiz rodam soltos e não tocam a rede:

```bash
python testes_manuais/_teste_fluxo.py    # decisão texto-vs-ferramenta no streaming
python testes_manuais/_teste_laco.py     # laço de ferramentas ponta a ponta, com stub de LLM
python testes_manuais/_teste_escalonamento.py  # catálogo em camadas e registro de ações
python testes_manuais/_teste_motor.py    # resultado estruturado, freio de repetição, paralelismo
```

## Observações

- O arquivo `.env` nunca deve ser compartilhado ou enviado ao repositório
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

**Aviso de segredo:** o build inclui o `.env` da Emily dentro da pasta do
executável, porque sem ele nada sobe. Isso significa que a pasta `dist/Emily/`
contém suas chaves de API — não compartilhe o executável.

## Autor

Desenvolvido por Vitor como projeto pessoal de assistente com IA.

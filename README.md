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
- Conversa natural em português brasileiro via LLM (AWS Bedrock — Claude Sonnet 4.6)
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
| LLM (conversa e visão) | AWS Bedrock — Claude Sonnet 4.6 |
| Agente de UI | AWS Bedrock — Claude Sonnet 4.6 (visão) |
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
├── modelo.py             # LLM (AWS Bedrock), personalidade, visão, decisões
├── voz.py                # TTS (Fish Audio), transcrição (Groq), captura PTT
├── automacao.py          # Interpretação e execução de comandos no PC
├── visao.py              # Captura de tela e troca de monitor
├── interface.py          # Janela gráfica, chat, controles
├── memoria.py            # Persistência de memória com deduplicação semântica
├── pesquisa.py           # Pesquisa real via Brave Search API + scraping
├── discord_bot.py        # Integração completa com Discord (texto + voz)
├── intencoes.py          # Detecção de intenções especiais (fechar, modo escrito, etc.)
├── agente_ui.py          # Agente autônomo de controle de tela (mouse/teclado por visão)
├── servidor.py           # Servidor Flask para controle remoto pelo celular
├── notificacoes.py       # Monitor de WhatsApp Web via Selenium
├── build_emily.py        # Script de build para gerar o executável (.exe)
├── diagnostico_whatsapp.py # Ferramenta de diagnóstico do monitor WhatsApp
├── static/
│   └── index.html        # Interface web PWA para controle pelo celular
└── img/                  # GIFs do sprite (não incluídos no repositório)
```

## Instalação

**Requisitos**
- Python 3.10 ou superior
- Windows (a automação e alguns recursos de áudio são específicos para Windows)
- ffmpeg instalado e no PATH do sistema
- Conta na AWS com acesso ao Amazon Bedrock (modelo Claude Sonnet 4.6)

**Instale as dependências:**
```bash
pip install -r requirements.txt
```

**Configure o arquivo `.env`** na pasta `minha-ia/` com suas chaves de API:
```
# Transcrição de voz
GROQ_API_KEY=sua_chave_aqui

# Síntese de voz
FISH_AUDIO_KEY=sua_chave_aqui

# LLM principal — AWS Bedrock (Claude Sonnet 4.6)
AWS_ACCESS_KEY_ID=sua_chave_aqui
AWS_SECRET_ACCESS_KEY=sua_chave_aqui

# Pesquisa na internet
BRAVE_API_KEY=sua_chave_aqui

# (Opcional — Fireworks como fallback/alternativa)
FIREWORKS_API_KEY=sua_chave_aqui
```

**Execute:**
```bash
cd minha-ia
python main.py
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
| AWS Bedrock | LLM de conversa, visão e agentes | Não (pay-per-use) |
| Groq | Transcrição de voz (Whisper) | Sim (generoso) |
| Fish Audio | Síntese de voz com voz clonada | Não (custo por uso) |
| Brave Search | Pesquisa na internet | Sim (2.000 req/mês grátis) |

## Modos de Operação

| Modo | Como ativar | O que faz |
|---|---|---|
| Normal | Padrão | Conversa, automação, pesquisa |
| Controle de Tela | "modo controle de tela" | Agente autônomo controla o mouse/teclado |
| Monitoramento de Jogo | "monitora o jogo" | Observa a tela e comenta eventos importantes |
| Modo Escrito | "ativa modo escrito" | Digita automaticamente o que o usuário falar |
| Escuta Discord | "ouve o discord" | Responde mensagens do Discord em tempo real |

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

O executável será gerado na pasta `build/` usando PyInstaller.

## Autor

Desenvolvido por Vitor como projeto pessoal de assistente com IA.

# Emily — Assistente Pessoal com IA

Emily é uma assistente pessoal completa desenvolvida em Python, com voz, visão de tela, automação do PC e integração com Discord. Ela foi construída para ser usada no dia a dia, respondendo por voz, executando comandos no sistema, analisando a tela em tempo real e muito mais.

## Funcionalidades

**Voz e Áudio**
- Captura de voz via Push-to-Talk (PTT) configurável (teclado ou mouse)
- Transcrição de fala com Whisper via Groq
- Síntese de voz (TTS) com Fish Audio, incluindo suporte a voz clonada
- Reprodução de áudio em streaming — Emily começa a falar enquanto ainda está gerando a resposta
- Tecla de atalho para interromper a fala a qualquer momento

**Inteligência e Conversa**
- Conversa natural em português brasileiro via LLM (Fireworks AI)
- Histórico de conversa com limite automático de tokens
- Memória persistente — lembra fatos sobre o usuário entre sessões
- Personalidade própria, consistente e configurável via system prompt

**Visão de Tela**
- Captura e análise de tela em tempo real
- Responde perguntas sobre o que está na tela
- Modo de monitoramento automático com triagem inteligente — só comenta quando algo relevante acontece
- Tradução automática de textos visíveis na tela para português
- Suporte a múltiplos monitores com troca dinâmica

**Automação do PC**
- Abertura e fechamento de aplicativos por nome (com busca fuzzy)
- Busca de jogos em Steam, Epic Games, GOG e Program Files
- Operações de arquivo: mover, copiar, renomear, deletar, extrair
- Abertura de sites e pesquisas no navegador padrão
- Controle de janelas: minimizar, maximizar, fechar abas
- Controle de mídia: tocar músicas, pausar, próxima, volume
- Sistema de modos configuráveis (ex: modo Gameplay, modo Programação)
- Suporte a sequências de inputs automáticos (macros/speedrun)
- Sistema de desfazer (undo) para operações de arquivo

**Integração com Discord**
- Bot conectado a servidores Discord
- Entra automaticamente no canal de voz quando o usuário entra
- Responde comandos e conversas via canal de texto
- Identifica diferentes usuários e adapta as respostas
- Reproduz a voz da Emily no canal de voz do servidor

**Interface Gráfica**
- Janela com status em tempo real (aguardando, ouvindo, falando)
- Entrada de texto manual como alternativa à voz
- Controle de monitoramento de tela pela interface

## Tecnologias Utilizadas

| Componente | Tecnologia |
|---|---|
| LLM (conversa) | Fireworks AI — Kimi K2 |
| LLM (visão) | Fireworks AI — Kimi K2 |
| Transcrição de voz | Groq — Whisper Large V3 Turbo |
| Síntese de voz | Fish Audio (com suporte a voz clonada) |
| Interface gráfica | Tkinter + Pillow (PIL) |
| Áudio | PyAudio + pygame |
| Discord | discord.py |
| Automação Windows | pywin32, keyboard, pynput, subprocess |

## Assets visuais

A interface usa GIFs animados para o sprite da Emily, que ficam na pasta `img/` 
dentro do projeto. Esses arquivos não estão incluídos no repositório por serem 
assets pessoais. Para rodar o projeto, crie a pasta `img/` e adicione seus próprios 
GIFs nomeados conforme os estados:

- `idle.gif` — estado parado/aguardando
- `talk.gif` — falando
- `uping.gif` — transição
- `screen.gif` — monitorando tela
- `search.gif` — pesquisando
- `open.gif` — abrindo app
- `transfer.gif` — transferindo arquivo

Se a pasta não existir ou os GIFs estiverem faltando, o sprite simplesmente não 
aparece mas o resto do sistema funciona normalmente.

## Estrutura do Projeto

```
emily/
├── main.py          # Orquestra todos os módulos e threads
├── modelo.py        # LLM, personalidade, visão e lógica de decisão
├── voz.py           # TTS, transcrição e captura PTT
├── automacao.py     # Interpretação e execução de comandos no PC
├── visao.py         # Captura de tela e troca de monitor
├── interface.py     # Janela gráfica e controles
├── memoria.py       # Persistência de memória entre sessões
├── pesquisa.py      # Pesquisa no navegador padrão
├── discord_bot.py   # Integração completa com Discord
└── intencoes.py     # Detecção de intenções especiais
```

## Instalação

**Requisitos**
- Python 3.10 ou superior
- Windows (a automação e alguns recursos de áudio são específicos para Windows)
- ffmpeg instalado e no PATH do sistema

**Instale as dependências:**
```bash
pip install -r requirements.txt
```

**Configure o arquivo `.env`** na raiz do projeto com suas chaves de API:
```
FIREWORKS_API_KEY=sua_chave_aqui
FIREWORKS_API_KEY2=sua_chave_aqui
FIREWORKS_VISION_KEY=sua_chave_aqui
FIREWORKS_TRIAGEM_KEY=sua_chave_aqui
GROQ_API_KEY=sua_chave_aqui
FISH_AUDIO_KEY=sua_chave_aqui
```

**Execute:**
```bash
python main.py
```

## Configuração do Discord (opcional)

Após rodar pela primeira vez, um arquivo `~/.emily_discord.json` será criado. Preencha com:
- Token do bot Discord
- ID do canal de texto
- ID do canal de voz
- Seu ID de usuário do Discord (para detecção automática de entrada em call)

## APIs Necessárias

| Serviço | Uso | Plano gratuito |
|---|---|---|
| Fireworks AI | LLM de conversa e visão | Sim |
| Groq | Transcrição de voz | Sim (generoso) |
| Fish Audio | Síntese de voz e clonagem | Não (Custo por uso) |

## Observações

- O arquivo `.env` nunca deve ser compartilhado ou enviado ao repositório
- Os arquivos de cache (`.emily_*.json`) são gerados localmente e armazenam dados pessoais — não estão incluídos no repositório
- A tecla PTT padrão é o botão lateral do mouse (MB5), configurável em `voz.py`
- O modelo de automação usa cache local para acelerar comandos repetidos

## Autor

Desenvolvido por Vitor como projeto pessoal de assistente com IA.

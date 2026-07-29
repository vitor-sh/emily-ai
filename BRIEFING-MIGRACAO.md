# Briefing — migração da camada de LLM da Emily

Contexto passado de uma sessão anterior. A estrutura do código você descobre lendo o repo;
o que está aqui é o **diagnóstico, as decisões já tomadas e o que precisa ser feito**.

---

## Situação

Emily é a assistente pessoal do Vitor em Python, roda no Windows 11 dele. Ela usava
**Claude Sonnet via AWS Bedrock** e ficou caro — os créditos acabaram e pagar não é viável
agora. Vamos migrar para o **NVIDIA NIM**, que tem endpoints gratuitos.

Todo o tráfego de LLM do projeto passa por uma única função: **`_chamar_llm()` em
`modelo.py`**. É o ponto de entrada da migração. `automacao.py` importa ela direto e
`memoria.py` usa o wrapper `chamar_llm_simples()`.

## Decisões já tomadas (não precisa rediscutir)

- **Provedor:** NVIDIA NIM. API compatível com OpenAI, `base_url =
  https://integrate.api.nvidia.com/v1`, chave em `.env` como `NVIDIA_API_KEY`.
- **Texto:** GLM-5.2 (`z-ai/glm-5.2` no catálogo do NIM).
- **Visão:** um VLM separado do NIM, porque **GLM-5.2 não tem visão**. Qwen3.5 VLM é o
  candidato; confirmar o identificador exato no catálogo.
- **Nada de LLM local.** O PC é i5-8400 + RX580 8GB — não cabe modelo com visão e a
  latência mataria o agente de UI. É API, sempre.
- **Meta de arquitetura:** trocar de modelo deve virar **edição de uma linha**. Hoje é
  impossível porque a chamada está soldada no formato de fio do Bedrock.

## Restrições que importam

**1. GLM-5.2 é texto puro.** A família de visão da Z.ai é outra (GLM-4.5V, GLM-4.6V,
GLM-5V-Turbo). Cerca de metade das funções da Emily depende de visão — triagem de tela,
análise de tela, tradução de tela, modo jogo e o agente de UI inteiro. Por isso a
arquitetura precisa de **dois modelos**, não um.

**2. Free tier do NIM é 40 RPM, teto rígido.** A NVIDIA não aumenta para conta gratuita
pessoal. **Isso cabe no uso real:** conversa por voz fica em 2–5 RPM, comandos em 1–2 por
comando. Os dois consumidores pesados — o loop de monitoramento de tela (~13 RPM) e o
agente de UI (10–20 RPM) — são usados **ocasionalmente e nunca ao mesmo tempo**, confirmado
pelo Vitor. Então não tratar 40 RPM como blocker, mas o tratamento de `429` é obrigatório.

**3. GLM-5.2 é modelo de raciocínio.** Tem níveis de esforço de raciocínio, e para
assistente de **voz** isso é latência percebida direta. Precisa desligar ou minimizar o
raciocínio nas rotas rápidas (classificadores, triagem SIM/NAO, frases curtas). **Não
chutar o nome do parâmetro** — varia entre builds do NIM. Testar contra o endpoint.

---

## Problemas encontrados

Importante: quase nenhum foi causado pela troca de modelo. É dívida técnica que o crédito
do Bedrock estava escondendo.

**1. 🔴 Zero tratamento de erro de transporte.** Não existe retry, backoff nem tratamento
de `429` em nenhum lugar. Todas as chamadas de LLM estão embrulhadas em `except: return
None` ou `except: return ""`. Resultado: rate limit ou falha de rede vira **falha
silenciosa** — a Emily só para de responder, sem log útil. É a causa mais provável de bug
difícil de diagnosticar no projeto, e com um free tier limitado isso vai acontecer.

**2. 🔴 O loop de monitoramento de tela queima chamada olhando tela parada.** Ciclo de
~4,5 segundos mandando print de 1280×720 (≈1.229 tokens de imagem) para um modelo de
fronteira decidir SIM/NAO — e a grande maioria das respostas é NAO. Dava ~13 chamadas/min,
~$4/hora no Sonnet. **Correção:** comparar o frame com o anterior (reduzir para ~32×32 em
escala de cinza e medir diferença média); se a tela não mudou, não chamar LLM. E reduzir a
resolução das imagens **de triagem** — 640×360 custa ~307 tokens contra ~1.229.

**3. 🔴 O prompt de interpretação de comandos tem ~8.178 tokens e é reenviado inteiro a
cada comando.** É o `system_content` de `_interpretar_com_llm`, em `automacao.py`
(410 linhas, 28.624 caracteres). É 100% estático → candidato ideal a prompt caching, se o
provedor suportar.

**4. 🟡 Existem chamadas de LLM que não deveriam existir.** Duas funções usam um modelo de
fronteira para gerar frases de enchimento tipo "Deixa eu ver..." (`gerar_frase_acao` e
`gerar_frase_analisando_tela`, `max_tokens=40`). Além do custo, elas adicionam um
round-trip de rede **antes de cada ação da Emily**, o que piora a latência percebida de uma
assistente de voz. Trocar por lista estática com `random.choice`. A função que decide se
divide uma mensagem do Discord em duas também gasta uma chamada e pode ser heurística.

**5. 🟡 `max_tokens` mal calibrados.** A triagem de mensagem do Discord usa `max_tokens=500`
para devolver "SIM"/"NAO" — e manda a personalidade inteira (~1.361 tokens) junto. A
extração de fatos usa 2048 para devolver duas linhas.

**6. 🟡 Existe uma grade de precisão construída e nunca ligada.** Em `visao.py` há
`capturar_tela_com_grade()` (desenha grade 10×10 rotulada A0–J9) e `celula_para_centro()`
(converte `"B3"` em coordenada). E o executor do agente de UI **já aceita a ação
`clicar_celula`**. Mas nada disso é chamado: o agente usa a captura sem grade e o prompt
pede `x, y` cru em 1280×720.

Isso é a alavanca mais importante do projeto para o agente de UI. Pedir "clica na célula
B3" é muito mais fácil para um modelo do que "devolve x=647, y=382". Já sofria com o Sonnet
— tem retry 3x para JSON inválido, detector de anti-loop e uma regra em capslock implorando
para o modelo não repetir ação. Com um VLM open-weights, coordenada crua vai ser pior.
**Ligar a grade que já existe é provavelmente o que decide se o agente de UI sobrevive à
migração.**

**7. 🟡 Resquícios e código morto.** Há um `/no_think` no system prompt principal que era do
Qwen e nunca funcionou no Claude — remover, e resolver via parâmetro da API. As constantes
de modelo se chamam `OLLAMA_TEXT_MODEL` / `OLLAMA_VISION_MODEL` mas apontam para Bedrock.
`_chamar_llm` tem um parâmetro `vision=` que é aceito e nunca usado. `intencoes.py` tem um
`return` órfão com variável inexistente e código inalcançável depois de um `return`. Existe
um `from openai import OpenAI` importado e sem uso — que agora finalmente vai servir.

**8. 🔴 Dados pessoais expostos no repo público.** O `memoria.json` contém informações
pessoais do Vitor e **está rastreado pelo git**, mesmo estando listado no `.gitignore` — a
regra foi adicionada depois do arquivo já ter sido commitado, e `.gitignore` não desrastreia
arquivo que já está no índice. A proteção que parece existir não funciona. Corrigir exige
`git rm --cached memoria.json` + commit, e reescrita de histórico para as versões antigas.
**Reescrever histórico é destrutivo — só com autorização explícita do Vitor.**

---

## Mudança de formato de fio

O NIM é compatível com OpenAI (`/v1/chat/completions`, sobre vLLM). O que muda:

| Hoje (Bedrock/Anthropic) | Depois (NIM/OpenAI) |
|---|---|
| `invoke_model` com `json.dumps(body)` | `client.chat.completions.create(...)` |
| `system` como campo separado do body | mensagem com `role: "system"` na lista |
| `anthropic_version` no body | não existe |
| `{"type":"image","source":{"type":"base64",...}}` | `{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}` |
| `invoke_model_with_response_stream` + `content_block_delta` → `delta.text` | `stream=True` + `choices[0].delta.content` |
| `json.loads(...)["content"][0]["text"]` | `resp.choices[0].message.content` |

Detalhe que facilita: `_chamar_llm` **já tem** um branch que converte imagem do formato
OpenAI para o formato Anthropic. A migração é essencialmente desfazer essa conversão.

---

## O que fazer

### Fase 1 — reduzir volume de chamadas
- Frame-diff no loop de visão; não chamar LLM se a tela não mudou.
- Reduzir resolução das imagens de triagem (manter alta onde precisão importa).
- Frases de enchimento → listas estáticas com `random.choice`.
- Divisão de mensagem do Discord → heurística.
- Corrigir os `max_tokens` do item 5, e parar de mandar personalidade em chamada SIM/NAO.

### Fase 2 — a camada nova
Criar um `llm.py` com:
- **Interface de provider** desacoplada do formato de fio. Começar com um provider
  OpenAI-compatible (serve NIM, DeepSeek, Groq, OpenRouter) e manter possibilidade de voltar
  ao Bedrock.
- **Tabela de rotas por tarefa**, tipo `ROTAS = {"conversa": ..., "visao": ...,
  "classificador": ..., "agente_ui": ...}` → (provider, modelo, esforço de raciocínio,
  `max_tokens`).
- **Rate limiter token bucket compartilhado entre threads.** A Emily chama LLM de várias
  threads: loop de voz, loop de visão, bot de Discord, extração de memória em background.
- **Retry com backoff exponencial em `429` e 5xx**, com log explícito. Nunca engolir exceção.
- `_chamar_llm` vira adaptador fino sobre `llm.py`, **preservando a assinatura atual** para
  não quebrar `automacao.py` nem `memoria.py`.

Também nesta fase: remover o `/no_think`, renomear as constantes `OLLAMA_*`, configurar
esforço de raciocínio por rota.

### Fase 3 — robustez do agente de UI
Ligar a grade que já existe: trocar a captura por `capturar_tela_com_grade()`, reescrever o
prompt de decisão para pedir **célula** (`"B3"`) em vez de `x, y`, e resolver via
`celula_para_centro()`. O executor já aceita `clicar_celula`.

### Fase 4 — limpeza
`requirements.txt` (não existe, apesar do README mandar usar), código morto do
`intencoes.py`, parâmetro `vision=`, e a questão do `memoria.json`.

---

## Como validar

**A validação é sempre local, no Windows do Vitor.** O projeto é Windows-only (`mss`,
`pyautogui`, `keyboard`, `ctypes.windll`) e não roda em Linux.

Depois da Fase 2, o teste que decide tudo: **o Vitor conversa ~10 minutos com a Emily** e
responde duas coisas.

**1. A personalidade segurou?** Esse é o maior risco da migração e o que mais importa para
ele. Sinais de degradação: markdown ou negrito aparecendo, emoji, tom formal ou de
"assistente de IA", saudação em toda resposta, respostas longas demais, perda da gíria
brasileira, repetição da mesma estrutura de frase.

**2. A latência está aceitável para voz?** Se houver atraso perceptível antes da fala,
suspeitar de tokens de raciocínio antes de suspeitar de rede.

**Se a personalidade não segurar, não desfazer a migração.** A tabela de rotas permite
manter GLM-5.2 nas tarefas estruturadas, onde ele é forte, e trocar só a rota `"conversa"`.
Plano B, todos com free tier e alcançáveis pelo mesmo provider OpenAI-compatible: Gemini
(visão nativa, notoriamente bom em português), DeepSeek, Groq.

Esse é o ponto central: **o trabalho não é uma aposta no GLM-5.2, é a opção de trocar de
modelo a qualquer momento.**

---

## Cuidados

- **Código, nomes de função e comentários em português.** É a convenção do projeto.
- **A personalidade da Emily é o coração do projeto.** O texto vive em constantes
  `EMILY_PERSONALIDADE*` em `modelo.py`. Restrições que o prompt trata como absolutas:
  português brasileiro coloquial; **sem markdown, negrito, itálico, listas ou headers**;
  **sem emoji e sem asteriscos de ação**; sem saudação formal; tom tsundere alternando entre
  agressivo e amável; respostas curtas por padrão; variar estrutura e início das frases. A
  variante de Discord usa abreviação de chat; a variante de call de voz **não**, porque vai
  para TTS.
- **Nunca reproduzir o conteúdo do `memoria.json`** em código, prompt, documentação ou
  mensagem. E não reescrever histórico do git sem autorização explícita.
- **`gerador_imagem.py` e `agente_jogo.py` estão gitignored de propósito** como
  funcionalidades em desenvolvimento. Existem só na máquina do Vitor. `main.py` importa os
  dois e roda normal lá — só um clone limpo do repo não sobe. **Não recriar esses módulos e
  não remover os imports.**
- Segredos vêm do `.env` via `python-dotenv`. Nunca hardcode chave, nunca imprimir valor de
  variável de ambiente em log.
- Não adicionar testes automatizados sem o Vitor pedir.

## Privacidade

O loop de monitoramento envia print da tela inteira do Vitor a cada poucos segundos para um
endpoint gratuito de avaliação — pode conter senha, conversa privada, qualquer coisa aberta.
Free tier de avaliação costuma ter política de retenção de dados diferente de tier pago.
Vale ele ler os termos antes de deixar o monitoramento ligado por longos períodos. O
frame-diff da Fase 1 reduz bastante o volume enviado, como efeito colateral positivo.

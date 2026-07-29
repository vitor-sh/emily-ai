---
inclusion: always
---

# Migração da camada de LLM: Bedrock → NVIDIA NIM

Trabalho em andamento. Ler junto com `emily-projeto.md`.

## Por que

Os créditos do Vitor na AWS Bedrock acabaram e pagar não é viável agora. O alvo é o
**NVIDIA NIM**, que oferece endpoints gratuitos acelerados por GPU em `build.nvidia.com`.

Modelo escolhido pelo Vitor: **GLM-5.2** da Z.ai — `z-ai/glm-5.2` no catálogo do NIM.
~744B parâmetros MoE com ~40B ativos por token, contexto de 1M, pesos MIT, lançado em
meados de junho de 2026. É o modelo de pesos abertos melhor colocado no Intelligence Index
da Artificial Analysis. Se um dia sair do free tier, a API oficial custa cerca de
$1,40/M input e $4,40/M output, contra $3/$15 do Sonnet.

## Restrições rígidas

### 1. GLM-5.2 é texto puro — precisa de um VLM separado

Não é modelo multimodal. A família de visão da Z.ai é outra (GLM-4.1V-Thinking, GLM-4.5V,
GLM-4.6V, GLM-5V-Turbo). Como ~metade das funções da Emily depende de visão (ver a tabela
em `emily-projeto.md`), a arquitetura precisa de **dois modelos**, não um.

Para a rota de visão, usar um VLM disponível no free tier do NIM — o Qwen3.5 VLM (400B MoE)
é acessível por endpoint gratuito e foi desenhado para agentes multimodais. Confirmar o
identificador exato no catálogo antes de fixar no código.

### 2. Free tier do NIM = 40 RPM, teto rígido

A NVIDIA afirma nos fóruns oficiais que não há forma de contornar nem de conseguir aumento
nesse tier, que a chave gratuita é destinada a prototipagem e não a sustentar fluxos
agênticos pesados, e que o limite é global.

**Isso cabe no uso real do Vitor.** Ele confirmou que `loop_visao` e `agente_ui` são
usados de forma ocasional, apenas para validar que funcionam, e **nunca os dois ao mesmo
tempo**:

| Uso | RPM aproximado | Cabe em 40? |
|---|---|---|
| Conversa por voz no dia a dia | 2–5 | sim, com folga |
| Comandos de automação | 1–2 por comando | sim |
| `loop_visao` sozinho, sem otimização | ~13 | sim |
| `agente_ui` sozinho | 10–20 | sim |
| Os dois juntos + retries | 25–35+ | estouraria, mas não é cenário real |

Conclusão: **não tratar 40 RPM como blocker.** Mas implementar tratamento de `429` com
backoff é obrigatório, porque hoje um rate limit vira falha silenciosa.

### 3. GLM-5.2 é modelo de raciocínio — cuidado com latência

Tem dois níveis de esforço de raciocínio. Para uma assistente de **voz**, tokens de
raciocínio são latência percebida direta. Um `triar_tela` que "pensa" por 8 segundos para
responder SIM/NAO deixa a Emily inutilizável.

Desligar ou minimizar o raciocínio nas rotas rápidas (classificadores, triagem, frases
curtas). **Não chutar o nome do parâmetro** — varia entre builds do NIM e entre modelos.
Testar contra o endpoint e confirmar empiricamente. É também a hora de remover o `/no_think`
do `system_prompt`, que era resquício do Qwen e nunca funcionou no Claude; a solução correta
é via parâmetro da API, não string mágica no prompt.

## Mudança de formato de fio

O NIM expõe **API compatível com OpenAI** (`/v1/chat/completions`) sobre vLLM. Base URL:
`https://integrate.api.nvidia.com/v1`. Chave em `.env` como `NVIDIA_API_KEY`.

`modelo.py` já tem `from openai import OpenAI` importado e sem uso — só falta apontar a
`base_url`.

| Hoje (Bedrock/Anthropic) | Depois (NIM/OpenAI) |
|---|---|
| `_client.invoke_model(modelId, body=json.dumps(body))` | `client.chat.completions.create(model=..., messages=...)` |
| `body["system"]` como campo separado | mensagem com `role: "system"` na lista |
| `body["anthropic_version"]` | não existe |
| `{"type":"image","source":{"type":"base64","media_type":...,"data":...}}` | `{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}` |
| `invoke_model_with_response_stream` + `content_block_delta` → `delta.text` | `stream=True` + `choices[0].delta.content` |
| `json.loads(resposta["body"].read())["content"][0]["text"]` | `resp.choices[0].message.content` |

Detalhe útil: `_chamar_llm` **já contém** um branch que converte `image_url` do formato
OpenAI para o formato Anthropic. A migração é essencialmente desfazer essa conversão.

## Desenho alvo

Extrair um módulo `llm.py` novo com:

1. **Interface de provider** desacoplada do formato de fio, para que trocar de provedor não
   exija reescrever chamada nenhuma. Começa com um provider OpenAI-compatible (serve para
   NIM, DeepSeek, Groq, OpenRouter e afins) e mantém a possibilidade de voltar ao Bedrock.
2. **Tabela de rotas por tarefa**, algo como
   `ROTAS = {"conversa": ..., "visao": ..., "classificador": ..., "agente_ui": ...}`,
   mapeando tarefa → (provider, modelo, esforço de raciocínio, `max_tokens`).
   Trocar de modelo deve ser **editar uma linha**.
3. **Rate limiter token bucket compartilhado entre threads** — a Emily chama LLM de
   múltiplas threads (loop de voz, loop de visão, bot de Discord, extração de memória em
   background).
4. **Retry com backoff exponencial em `429` e erro 5xx**, com log explícito. Nunca engolir
   a exceção silenciosamente.
5. `_chamar_llm` em `modelo.py` passa a ser um adaptador fino sobre `llm.py`, preservando a
   assinatura atual para não quebrar `automacao.py:38` nem `memoria.py`.

## Plano em fases

### Fase 1 — reduzir volume de chamadas
- Frame-diff no `loop_visao` (`main.py:1292`): reduzir o frame para ~32×32 em escala de
  cinza e comparar com o anterior por diferença média; se a tela não mudou, `continue` sem
  chamar LLM. Filtra a maioria das chamadas.
- Reduzir a resolução das imagens de **triagem** (a de 1280×720 custa ~1.229 tokens; 640×360
  custa ~307). Manter resolução alta onde precisão importa.
- Substituir `gerar_frase_acao` e `gerar_frase_analisando_tela` por listas estáticas com
  `random.choice` — remove custo **e** um round-trip antes de cada ação.
- Substituir `quebrar_resposta_discord` por heurística simples.
- Corrigir `max_tokens`: `triagem_mensagem_discord` 500 → ~5 e parar de enviar a
  personalidade inteira num SIM/NAO; `extrair_fatos` 2048 → ~300.

### Fase 2 — a camada nova
- Criar `llm.py` conforme o desenho alvo acima.
- Rotas iniciais: GLM-5.2 para texto, VLM do NIM para visão.
- Remover o `/no_think` e renomear as constantes `OLLAMA_*` (`modelo.py:178-180`).
- Configurar esforço de raciocínio por rota.

### Fase 3 — robustez do agente de UI
- **Ligar a grade de precisão que já existe.** Trocar `visao.capturar_tela()` por
  `visao.capturar_tela_com_grade()` no `agente_ui`, reescrever o prompt de
  `decidir_proxima_acao_ui` para pedir **célula** (`"B3"`) em vez de `x, y` cru, e resolver
  via `visao.celula_para_centro()`. O executor já aceita `clicar_celula`.
  Isso é o que decide se o agente de UI sobrevive a um modelo menos capaz em coordenadas.
- Avaliar prompt caching no `system_content` de `automacao.py` se o provedor suportar.

### Fase 4 — limpeza
- `memoria.json`: `git rm --cached` + reescrita de histórico. Já está no `.gitignore` mas
  segue rastreado. Reescrita de histórico só com autorização explícita do Vitor.
- Criar `requirements.txt`.
- Remover código morto de `intencoes.py` e o parâmetro `vision=` de `_chamar_llm`.
- `gerador_imagem.py` e `agente_jogo.py` seguem gitignored de propósito (WIP local) — não
  são pendência, mas impedem rodar um clone limpo. Nada a fazer sem o Vitor pedir.

## Como validar

O sandbox do Kiro Web **não consegue executar a Emily** (Linux, sem tela, sem áudio; `mss`,
`pyautogui` e `keyboard` são Windows-only). A validação é sempre local, no Windows 11 do
Vitor.

Depois da Fase 2, o teste que decide tudo é: **o Vitor conversa ~10 minutos com a Emily** e
responde duas perguntas:

1. **A personalidade segurou?** Sinais de degradação a procurar: markdown ou negrito
   aparecendo, emoji, tom formal ou de "assistente de IA", saudação a cada resposta,
   respostas longas demais, perda da gíria brasileira, repetição de estrutura.
2. **A latência está aceitável para voz?** Se houver atraso perceptível antes da fala,
   suspeitar de tokens de raciocínio antes de suspeitar de rede.

Se a personalidade não segurar, **não desfazer a migração**: a tabela de rotas permite
manter GLM-5.2 nas tarefas estruturadas (onde ele é forte) e trocar só a rota `"conversa"`.
Candidatos de plano B, todos com free tier e alcançáveis pelo mesmo provider
OpenAI-compatible: Gemini (visão nativa e notoriamente bom em português), DeepSeek, Groq.

Esse é o ponto central do desenho: **o trabalho não é uma aposta no GLM-5.2, é a opção de
trocar de modelo a qualquer momento.** Hoje isso é impossível porque a chamada está soldada
no formato do Bedrock.

## Expectativas honestas

- **Deve ir bem:** `_interpretar_com_llm` (JSON estruturado com dezenas de exemplos),
  classificadores SIM/NAO, extração de fatos. GLM-5.2 é forte em agêntico e estruturado.
- **Risco real:** a personalidade. São ~1.361 tokens de regras de estilo em PT-BR coloquial,
  e aderência a estilo não é a mesma competência que raciocínio. Esperar iteração de prompt.
- **Risco real:** latência, pelo raciocínio e por ser endpoint gratuito compartilhado.
- **Risco conhecido e mitigável:** precisão de coordenadas no agente de UI → grade.

## Privacidade

O `loop_visao` envia print da tela inteira do Vitor a cada poucos segundos para um endpoint
gratuito de avaliação — pode conter senha, conversa privada, qualquer coisa aberta. Free
tier de avaliação costuma ter política de retenção e uso de dados diferente de tier pago.
Vale o Vitor ler os termos antes de deixar o monitoramento ligado por longos períodos. O
frame-diff da Fase 1 reduz bastante o volume enviado, como efeito colateral positivo.

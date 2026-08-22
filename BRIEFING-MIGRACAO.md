# Briefing — migração da camada de LLM da Emily

Contexto passado de uma sessão anterior. A estrutura do código você descobre lendo o repo;
o que está aqui é o **diagnóstico, as decisões já tomadas e o que precisa ser feito**.

> ## ⚠️ ESTE DOCUMENTO É HISTÓRICO
>
> Ele descreve a migração **Bedrock → NVIDIA NIM**, que foi concluída. Depois dela veio
> outra: **NIM → Kiro (Claude)**, que é o estado atual do projeto.
>
> O texto abaixo fica preservado porque explica decisões que continuam valendo — a
> arquitetura do `llm.py`, a tabela de rotas, o limitador compartilhado, a grade do agente
> de UI e as armadilhas de raciocínio. Nada disso foi desfeito.
>
> **Para o estado atual, vá para [a última seção](#migração-2--nim--kiro-concluída).**
> O que está desatualizado no meio do documento: o provedor ativo, os modelos e a suposição
> de que não há testes automatizados.

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

---

# Migração 2 — NIM → Kiro (concluída)

Esta é a migração seguinte, e o **estado atual** do projeto. O spec completo, com
requisitos em EARS, design e as dez tasks com notas de execução, está em
`.kiro/specs/migracao-llm-kiro-gateway/`.

## Por que

O Vitor assinou o Kiro Pro+, que dá acesso a Claude Sonnet 5, Opus 5 e Haiku 4.5. O
[kiro-gateway](https://github.com/jwadow/kiro-gateway) expõe esses modelos numa API
OpenAI-compatible com streaming SSE, tool calling e visão. Como o `llm.py` já tinha
`ProvedorOpenAI` genérico, a migração virou o que a arquitetura prometia: **edição de
tabela mais um módulo de ciclo de vida.** Nenhum consumidor foi reescrito.

## O que mudou

**Nove rotas, todas no Kiro** (era oito; a `agente_jogo` é nova):

| rota | modelo | por quê |
|---|---|---|
| `conversa`, `discord`, `comando`, `extracao`, `visao`, `agente_jogo` | `claude-sonnet-5` | 1,3x de crédito |
| `agente_ui` | `claude-opus-5` | 2,2x; precisa apontar onde clicar |
| `classificador`, `triagem_visual` | `claude-haiku-4.5` | as que mais disparam |

**Módulo novo `gateway.py`.** O LLM da Emily deixou de ser um endpoint remoto e passou a
ser um processo local. Esse módulo é o único lugar que sabe disso: sobe o subprocesso no
boot, mantém o `/health` em cache com TTL, religa se o proxy morrer no meio da sessão, e
derruba no fim — mas só se foi ele que subiu, porque gateway que o Vitor abriu à mão num
terminal não pode morrer quando a Emily fecha.

**`agente_jogo` ganhou rota própria.** Antes usava `ROTA_AGENTE_UI`, o que era inofensivo
quando as duas apontavam pro mesmo modelo. Com o `agente_ui` no Opus a 2,2x e o agente de
jogo disparando em laço durante gameplay, herdar a rota viraria conta alta sem motivo — o
que se pede ali é uma tecla, não uma coordenada.

**Falha de LLM virou audível e específica.** `ErroGateway` carrega motivo e uma frase
pronta pro TTS. "Vitor, o login do Kiro expirou. Abre o Kiro e faz login de novo" resolve
em dez segundos; "tive um problema pra acessar meu modelo" não resolve nada. E como isso
sai como `ErroConfiguracao`, o retry não repete — credencial vencida não melhora com
backoff, e quatro tentativas de 300s deixariam a Emily muda por vinte minutos.

**Reversão por uma linha.** `EMILY_PROVEDOR_LLM=nvidia` devolve as nove rotas para o NIM.
São duas tabelas separadas, não uma com o provedor trocado — porque o valor de raciocínio
correto é oposto nos dois (ver armadilha abaixo).

## Armadilhas encontradas, e o que cada uma ensinou

**1. `profileArn` — o bloqueador que quase parou tudo.** A conta do Vitor é
`authMethod: IdC` / `provider: Enterprise`, e nenhum dos arquivos de cache do Kiro traz
`profileArn`. O `GET /v1/models` funcionava; todo `POST /v1/chat/completions` voltava
`HTTP 400 profileArn is required`. O gateway não descobre o ARN sozinho. Resolvido varrendo
logs e configs do Kiro IDE (`_teste_achar_arn.py` achou dois candidatos) e testando qual
respondia (`_teste_arn_qual_funciona.py`). O ativo é o que também aparece em `profile.json`.

**2. Raciocínio: a semântica é INVERTIDA entre os dois provedores.** No NIM,
`RACIOCINIO_NORMAL` significa "não manda parâmetro nenhum", porque o nemotron **rejeita**
`reasoning_effort='none'` com 400. No gateway do Kiro é o contrário: `'none'` é o que
**desliga** o thinking, e a **ausência** do parâmetro liga com budget default. Ou seja, o
valor que protege num provedor sabota no outro. Foi isso que obrigou as duas tabelas de
rotas a existirem separadas.

**3. O `/v1/models` não é autoridade — nos dois sentidos.** O `llm.py` já registrava que a
lista do NIM contém modelos que devolvem 404 na chamada real. No Kiro acontece o inverso: a
lista da conta tem 13 modelos e **nenhum** deles é `claude-sonnet-5` ou `claude-opus-5`, mas
os dois respondem normalmente. O `ModelResolver` do gateway é pass-through de propósito
("gateway, not gatekeeper"). Por isso o `llm.py` não valida nome de modelo: validar
bloquearia modelo novo que a conta já tem.

**4. O gateway morria no boot por causa de um emoji.** O banner de inicialização dele
imprime 👻. Como redirecionamos a saída do subprocesso para arquivo (necessário para
classificar a falha depois), o stdout do filho deixa de ser terminal e o Python passa a usar
a codificação local — cp1252 nesta máquina. `UnicodeEncodeError`, processo morto antes de
servir uma requisição. Corrigido impondo `PYTHONIOENCODING=utf-8` e `PYTHONUTF8=1` no
ambiente do filho. **Esse bug atingiria a Emily empacotada de qualquer forma**, que roda sem
console nenhum.

**5. O `.env` da Emily podia atropelar o do gateway em silêncio.** O `load_dotenv()` da
Emily joga tudo em `os.environ`, o subprocesso herda, e o `load_dotenv()` do gateway **não
sobrescreve** variável já presente no ambiente. Qualquer chave homônima venceria o
`kiro_gateway/.env` — inclusive as quatro que a migração depende. Daí a chave da Emily se
chamar `KIRO_PROXY_API_KEY` e não `PROXY_API_KEY`, e daí o `_ambiente_do_gateway()` remover
as chaves reservadas na força em vez de confiar na convenção de nome.

**6. Tool calling chega em formato diferente.** O gateway emite os `tool_calls` num **chunk
único no fim** do stream, com argumentos completos, e várias ferramentas na mesma lista. O
NIM emitia fatiado entre deltas. Consequência: a janela de decisão de 80 caracteres do
`FluxoComFerramentas` quase nunca dispara, e a ferramenta só aparece na releitura de
`.chamadas` depois de esgotar `.texto()`. Isso já funcionava (era o ramo que corrigiu o bug
do preâmbulo), mas deixou de ser exceção e virou o caminho principal.

## Configuração obrigatória do gateway

Quatro chaves do `kiro_gateway/.env`, nenhuma é o default:

| chave | valor | por que mudar |
|---|---|---|
| `SERVER_HOST` | `127.0.0.1` | o default `0.0.0.0` expõe a conta paga na rede local |
| `FAKE_REASONING` | `false` | injeta thinking tags e devolve campo que o `_iterar_stream` ignora |
| `WEB_SEARCH_ENABLED` | `false` | injeta `web_search` em toda requisição; o resumo da busca sairia pelo TTS |
| `AUTO_TRIM_PAYLOAD` | `true` | a Kiro API rejeita payload acima de ~615KB |

Mais `PROXY_API_KEY`, `KIRO_CREDS_FILE`, `PROFILE_ARN` e `LOG_LEVEL=WARNING`. O
`_setup_gateway_env.py` escreve tudo isso, gerando a senha sem imprimir na tela.

## O que a migração ganhou e o que perdeu

**Ganhou.** Leitura de tela correta: na mesma captura, o nemotron alucinou "um chat em tempo
real com vários usuários" ao ler um arquivo aberto no editor; os dois Claude descreveram
certo. E velocidade — na mesma pergunta, o Claude respondeu 9,53s antes do GLM, e num
diagnóstico posterior o GLM levou 46s para dizer "OK" contra 1,73s a 3,14s das rotas no
Kiro. A personalidade passou intacta, que era o maior risco.

**Perdeu.** A triagem de tela era 0,58s e **grátis** no free tier do NIM; agora é ~2,12s e
consome crédito por disparo, rodando em laço durante o monitoramento — medido em ~9,6
chamadas por minuto com a tela mudando sem parar. É a primeira rota a considerar devolver
pro nemotron se o crédito do mês apertar, e reverter é uma linha.

## Divergência de uma regra antiga deste briefing

O briefing original dizia "não adicionar testes automatizados sem o Vitor pedir". A
migração para o Kiro foi executada a partir de um spec que o Vitor aprovou e que **pedia
testes de propriedade explicitamente**. Existem hoje 84 testes em `testes/`, nenhum tocando
a rede, cobrindo ciclo de vida do gateway, tabelas de rotas e tool calling.

Dois deles nasceram de bug que eles mesmos encontraram: o hypothesis achou uma contradição
na especificação da Property 4 (não se pode "preservar toda chave não reservada" e ao mesmo
tempo "impor UTF-8"), e um helper de teste mal escrito acusou um bug inexistente no
`llm.py` porque `importlib.reload` muta o módulo no lugar. As duas histórias estão nas notas
de execução do `tasks.md`.

## Ferramentas de diagnóstico

```bash
python llm.py                    # todas as rotas contra o endpoint real
python gateway.py                # só o ciclo de vida do proxy
python -m pytest testes/ -q      # 84 testes, sem rede
python _teste_gateway_modelos.py # o que a conta libera de verdade
python _bench_visao.py           # compara modelos de visão na mesma captura
python _bench_grade.py           # precisão de localização do agente de UI
```

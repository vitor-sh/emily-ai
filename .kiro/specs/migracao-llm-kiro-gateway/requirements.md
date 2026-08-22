# Documento de Requisitos: migracao-llm-kiro-gateway

## Introdução

Migrar todas as rotas de LLM da Emily do NVIDIA NIM para o kiro-gateway local, um proxy
FastAPI OpenAI-compatible que expõe os modelos Claude do plano pago Kiro Pro+ do Vitor.
A migração precisa preservar streaming token a token e tool calling, subir o proxy
automaticamente junto com a Emily, e falhar de forma audível e explícita quando o proxy
não estiver disponível — sem fallback automático.

A numeração dos critérios abaixo é referenciada pelas tags `Validates: Requirements X.Y`
das Correctness Properties do `design.md`. Alterar a numeração exige atualizar as tags.

---

## Requisito 1: Configuração do gateway

**História:** Como Vitor, quero que o gateway rode com a configuração certa desde o
primeiro boot, para que ele não exponha minha conta paga na rede local nem contamine as
respostas da Emily com conteúdo que eu não pedi.

### Critérios de Aceitação

1.1 QUANDO o gateway é iniciado ENTÃO ele DEVE escutar apenas em `127.0.0.1`, nunca em
`0.0.0.0`.

1.2 QUANDO a Emily faz qualquer chamada ao gateway ENTÃO nenhuma tag de thinking DEVE ser
injetada no prompt e nenhum delta de `reasoning_content` DEVE ser emitido
(`FAKE_REASONING=false`).

1.3 QUANDO a Emily faz uma chamada sem catálogo de ferramentas ENTÃO o gateway NÃO DEVE
injetar a ferramenta `web_search` na requisição (`WEB_SEARCH_ENABLED=false`).

1.4 QUANDO o payload de uma requisição excede o limite da Kiro API ENTÃO o gateway DEVE
remover os pares mais antigos do histórico até o payload caber, em vez de devolver erro
(`AUTO_TRIM_PAYLOAD=true`).

1.5 A senha do proxy DEVE existir apenas em arquivo `.env` — `PROXY_API_KEY` no gateway e
`KIRO_PROXY_API_KEY` na Emily — e NÃO DEVE aparecer hardcoded em nenhum arquivo de código.

1.6 QUANDO o gateway inicia ENTÃO ele DEVE carregar a credencial do Kiro a partir de
`KIRO_CREDS_FILE`, apontado para o cache de autenticação do Kiro IDE.

1.7 QUANDO o gateway registra log ENTÃO o nível DEVE ser `WARNING`, para que o console da
Emily continue legível.

---

## Requisito 2: Streaming preservado em todos os caminhos de resposta

**História:** Como Vitor, quero que a Emily continue começando a falar antes de terminar de
pensar, em todos os caminhos que ela usa hoje, para que a latência percebida não piore com
a troca de provedor.

### Critérios de Aceitação

2.1 QUANDO `conversar_stream` roda no caminho de streaming puro (`EMILY_TOOL_CALLING=0`)
ENTÃO os pedaços de texto DEVEM chegar incrementalmente e a fila de TTS DEVE receber a
primeira frase antes do fim da resposta.

2.2 QUANDO `conversar_com_ferramentas` roda com stream e o modelo responde em texto ENTÃO o
texto DEVE ser entregue incrementalmente à fila de TTS, sem esperar o fim do stream.

2.3 QUANDO `precisa_pesquisar` é verdadeiro e `conversar_stream` cai no ramo sem stream
ENTÃO a resposta completa DEVE ser devolvida como string única e enfileirada de uma vez,
sem quebra por frase.

2.4 QUANDO qualquer um dos três caminhos acima é validado ENTÃO o tempo até o primeiro
pedaço DEVE ser medido e registrado, para comparação com o comportamento no NIM.

2.5 A migração NÃO DEVE alterar a assinatura de `_chamar_llm`, `chamar_llm_simples` nem das
funções de visão de `modelo.py`.

---

## Requisito 3: Ciclo de vida do gateway

**História:** Como Vitor, quero que o gateway suba junto com a Emily e morra com ela, para
que eu não precise lembrar de abrir um terminal antes de usar minha assistente.

### Critérios de Aceitação

3.1 QUANDO `garantir()` é chamado múltiplas vezes durante a vida do processo da Emily ENTÃO
o módulo DEVE iniciar no máximo um processo de gateway.

3.2 QUANDO várias threads da Emily chamam `garantir()` simultaneamente ENTÃO apenas uma
DEVE iniciar o processo e as demais DEVEM aguardar o resultado dela.

3.3 QUANDO `garantir()` retorna sem exceção ENTÃO a checagem de saúde DEVE ter estado
positiva no instante do retorno.

3.4 QUANDO o gateway já está no ar sem ter sido iniciado pelo módulo ENTÃO `garantir()` NÃO
DEVE criar processo algum e o módulo DEVE registrar que não é dono do processo.

3.5 QUANDO a Emily encerra e o módulo não é dono do processo ENTÃO `derrubar()` NÃO DEVE
enviar sinal a processo algum.

3.6 QUANDO `garantir()` falha e é chamado novamente ENTÃO nenhum processo órfão DEVE
permanecer da tentativa anterior e a nova tentativa DEVE ocorrer com estado interno
consistente.

3.7 QUANDO a subida do gateway falha ENTÃO o módulo DEVE levantar `ErroGateway` com motivo
entre os declarados (`porta_ocupada`, `nao_subiu`, `credencial`, `sem_python`, `sem_pasta`)
e detalhe contendo a cauda do log do subprocesso.

3.8 QUANDO o subprocesso do gateway é criado ENTÃO o ambiente passado a ele NÃO DEVE conter
nenhuma chave reservada do gateway nem chave com prefixo `KIRO_` ou `ACCOUNT_`, DEVE
preservar o valor de todas as chaves não reservadas, e NÃO DEVE modificar o ambiente do
processo pai.

3.9 QUANDO a Emily encerra e o módulo é dono do processo ENTÃO `derrubar()` DEVE encerrar o
processo com `terminate()` seguido de `kill()` após período de graça, e DEVE ser idempotente.

3.10 QUANDO `garantir()` é chamado dentro da janela de confiança do último health positivo
ENTÃO nenhuma requisição de rede DEVE ser feita.

---

## Requisito 4: Falha explícita, sem fallback automático

**História:** Como Vitor, quero saber por voz e no console exatamente qual é o problema
quando o gateway não sobe, para que a Emily nunca emudeça sem explicação.

### Critérios de Aceitação

4.1 QUANDO `garantir()` levanta `ErroGateway` ENTÃO o provedor DEVE traduzi-lo em
`ErroConfiguracao` preservando o erro original como causa.

4.2 QUANDO `ErroConfiguracao` sobe pela camada de LLM ENTÃO o mecanismo de retry NÃO DEVE
repetir a chamada.

4.3 QUANDO o gateway falha ENTÃO nenhum outro provedor DEVE ser consultado — não existe
fallback automático.

4.4 QUANDO uma falha de gateway é reportada ao Vitor ENTÃO a frase falada DEVE ser não
vazia, específica do motivo, sem markdown e sem emoji.

4.5 QUANDO uma chamada falha por indisponibilidade do gateway ENTÃO o provedor DEVE ter
sido acionado exatamente uma vez.

4.6 QUANDO `garantir()` falha durante o boot da Emily ENTÃO a Emily DEVE continuar subindo
(interface, voz, Discord e automação funcionando) e a falha DEVE ser falada.

4.7 QUANDO qualquer falha de gateway ocorre ENTÃO o console DEVE mostrar o motivo e o
detalhe, nunca apenas a frase falada.

---

## Requisito 5: Rotas de texto migradas e consumidores validados

**História:** Como Vitor, quero que todo caminho de texto da Emily funcione no Kiro, para
que memória, comandos, classificação e Discord não quebrem em silêncio.

### Critérios de Aceitação

5.1 QUANDO a tabela de rotas ativa é carregada ENTÃO as rotas de texto (`conversa`,
`discord`, `comando`, `extracao`, `classificador`) DEVEM existir e apontar para um provedor
registrado.

5.2 QUANDO a rota `classificador` é exercitada com `max_tokens=16` ENTÃO ela DEVE ser
MEDIDA com amostras reais de SIM/NAO e DEVE devolver conteúdo decisório não vazio em todas
elas.

5.3 SE a medição de 5.2 devolver string vazia ENTÃO o `max_tokens` da rota DEVE ser
aumentado ou a instrução de formato de saída endurecida no prompt, e o resultado da medição
DEVE ser registrado em comentário no código, junto aos números históricos já documentados.

5.4 QUANDO `memoria.py` executa deduplicação semântica e extração de fatos ENTÃO as duas
DEVEM produzir resultado válido pela rota `extracao`.

5.5 QUANDO `automacao.py` interpreta um comando pela rota `comando` ENTÃO a saída DEVE ser
JSON válido e parseável.

5.6 QUANDO `discord_bot.py` responde uma mensagem ENTÃO a resposta DEVE respeitar o limite
de tamanho e o estilo de chat configurados na rota `discord`.

5.7 QUANDO `intencoes.py` classifica uma intenção ENTÃO o resultado DEVE ser equivalente ao
comportamento anterior à migração.

---

## Requisito 6: Estrutura das rotas e divisão de modelos

**História:** Como Vitor, quero cada tarefa no modelo de custo adequado, para que o agente
de UI tenha precisão sem que o monitoramento de jogo queime meu crédito.

### Critérios de Aceitação

6.1 QUANDO as duas tabelas de rotas são carregadas ENTÃO `ROTAS_KIRO` e `ROTAS_NVIDIA`
DEVEM expor exatamente o mesmo conjunto de nomes de rota.

6.2 QUANDO a tabela do Kiro é carregada ENTÃO `conversa`, `discord`, `comando`, `extracao`,
`visao` e `agente_jogo` DEVEM usar o modelo Sonnet configurado, e `agente_ui` DEVE usar o
modelo Opus configurado.

6.3 QUANDO `agente_jogo.py` decide uma ação ENTÃO ele DEVE usar rota própria e NÃO DEVE
herdar o modelo da rota `agente_ui`.

6.4 QUANDO o modelo das rotas `classificador` e `triagem_visual` é definido ENTÃO a escolha
DEVE ser feita após confirmar a lista real de modelos da conta, e o modelo escolhido DEVE
ser o mais barato que atenda ao critério de acerto.

6.5 QUANDO uma rota envia parâmetro de raciocínio que o endpoint rejeita ENTÃO a camada de
LLM DEVE aprender a rejeição por modelo, registrar o motivo em log e não reenviar o
parâmetro naquela sessão.

6.6 QUANDO chamadas ao Kiro são feitas de múltiplas threads ENTÃO elas DEVEM compartilhar
um limitador de taxa próprio do provedor, configurável por variável de ambiente.

---

## Requisito 7: Rotas de visão migradas e medidas

**História:** Como Vitor, quero que a Emily continue enxergando minha tela com a mesma
qualidade, e quero número na mão antes de declarar o agente de UI migrado.

### Critérios de Aceitação

7.1 QUANDO uma mensagem com imagem em base64 é enviada ENTÃO o corpo montado pelo provedor
DEVE conter uma parte de imagem cuja data URL preserva o media type e os bytes base64
originais.

7.2 QUANDO as rotas `visao` e `triagem_visual` são migradas ENTÃO latência e tokens de
prompt DEVEM ser medidos com a mesma metodologia já documentada no código (captura
640x360, descrição em português, triagem SIM/NAO).

7.3 QUANDO a medição de 7.2 termina ENTÃO o bloco de comentário do `llm.py` que registra os
números dos modelos anteriores DEVE ser atualizado com os números novos.

7.4 QUANDO `triar_tela` e `triar_tela_jogo` recebem capturas controladas ENTÃO elas DEVEM
responder SIM para o evento marcante e NAO para o cenário rotineiro.

7.5 QUANDO o benchmark de grade 10x10 é executado na rota `agente_ui` ENTÃO o acerto de
linha e coluna DEVE ser comparado com o resultado histórico registrado no código, e a rota
só DEVE ser declarada migrada se o resultado for igual ou melhor.

7.6 SE o benchmark de 7.5 for pior que o histórico ENTÃO a rota `agente_ui` DEVE permanecer
no provedor anterior e o motivo DEVE ser registrado em comentário com os números medidos.

7.7 QUANDO uma sessão de monitoramento de jogo é executada ENTÃO o número de chamadas por
minuto DEVE ser contado e reportado, para avaliação de consumo de crédito.

---

## Requisito 8: Tool calling no formato do gateway

**História:** Como Vitor, quero que a Emily continue agindo de verdade quando pede pra
agir, e não só anunciando a ação, mesmo com o formato de stream diferente do gateway.

### Critérios de Aceitação

8.1 QUANDO o gateway emite os pedidos de ferramenta em um único evento no fim do stream
ENTÃO todas as ferramentas pedidas DEVEM ser executadas.

8.2 QUANDO o modelo escreve preâmbulo antes de pedir a ferramenta ENTÃO a ferramenta DEVE
ser executada independentemente do tamanho do preâmbulo — vazio, apenas espaço em branco,
curto, ou maior que a janela de decisão da camada de streaming.

8.3 QUANDO existe preâmbulo e ferramenta na mesma resposta ENTÃO o texto entregue ao TTS
DEVE ser exatamente o preâmbulo, sem duplicação e sem perda.

8.4 QUANDO o stream não contém pedido de ferramenta ENTÃO zero ferramentas DEVEM ser
executadas e o texto entregue ao TTS DEVE ser a concatenação exata dos deltas de conteúdo.

8.5 QUANDO o laço de ferramentas roda ENTÃO os limites existentes de voltas e de forçação
DEVEM continuar valendo, sem alteração de comportamento.

---

## Requisito 9: Reversão e configuração por ambiente

**História:** Como Vitor, quero voltar tudo pro provedor antigo com uma linha de `.env`,
porque o Opus 5 é preview e já vi modelo sair do ar sem aviso neste projeto.

### Critérios de Aceitação

9.1 QUANDO a variável de seleção de provedor está ausente ENTÃO a tabela ativa DEVE ser a
do Kiro.

9.2 QUANDO qualquer tabela de rotas é carregada ENTÃO toda rota DEVE apontar para um
provedor registrado e ter `max_tokens` positivo.

9.3 QUANDO a variável de seleção contém valor desconhecido ENTÃO o sistema DEVE levantar
`ErroConfiguracao` citando os valores aceitos, e DEVE aceitar o valor com espaços nas
pontas e em qualquer caixa.

9.4 QUANDO uma variável de modelo de um grupo de rotas é definida ENTÃO todas as rotas
daquele grupo DEVEM usar o modelo informado e nenhuma outra rota DEVE ser afetada.

9.5 QUANDO a migração termina ENTÃO o provedor anterior e sua credencial DEVEM continuar
registrados e funcionais, para servir de caminho de reversão.

---

## Requisito 10: Empacotamento e documentação

**História:** Como Vitor, quero que a Emily empacotada continue funcionando e que o
procedimento de manutenção esteja escrito, para eu não redescobrir tudo em três meses.

### Critérios de Aceitação

10.1 QUANDO a Emily é empacotada ENTÃO a pasta do gateway DEVE ser incluída como dado, pois
o subprocesso precisa do código-fonte.

10.2 QUANDO a Emily roda empacotada ENTÃO o interpretador do subprocesso DEVE ser resolvido
na ordem: variável de ambiente explícita, executável do processo quando não empacotado,
e busca no PATH; SE nenhum resolver ENTÃO o motivo `sem_python` DEVE ser reportado com
frase própria.

10.3 QUANDO o repositório é versionado ENTÃO o `.env` do gateway, o arquivo de credenciais,
o arquivo de estado e os logs do gateway DEVEM estar ignorados pelo git.

10.4 QUANDO a migração termina ENTÃO a documentação do projeto DEVE descrever a arquitetura
nova, as variáveis de ambiente necessárias e o procedimento para quando a credencial do
Kiro expirar.

10.5 QUANDO as dependências são declaradas ENTÃO as ferramentas de teste DEVEM ficar como
dependência de desenvolvimento, fora do pacote de execução da Emily.

---

## Requisito 11: Diagnóstico

**História:** Como Vitor, quero um comando que testa tudo contra o endpoint real e me diz o
que funcionou, para eu não descobrir problema no meio de uma conversa.

### Critérios de Aceitação

11.1 QUANDO o diagnóstico é executado ENTÃO ele DEVE exercitar todas as rotas da tabela
ativa, incluindo a rota nova de agente de jogo.

11.2 QUANDO uma rota falha durante o diagnóstico ENTÃO o motivo DEVE ser reportado e as
rotas seguintes DEVEM continuar sendo testadas.

11.3 QUANDO o diagnóstico termina ENTÃO ele DEVE relatar, para cada rota, sucesso ou motivo
da falha, e DEVE imprimir qual tabela de rotas está ativa.

11.4 QUANDO o diagnóstico roda ENTÃO ele DEVE incluir a amostra de personalidade na rota de
conversa e o estado do gateway (no ar, dono do processo, pid e URL).

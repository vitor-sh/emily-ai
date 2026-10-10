# Decisão contextual da Emily

A conversa normal do PC e do Android chega ao agente com contexto e ferramentas disponíveis. Listas locais de palavras não decidem se ele deve conversar, agir ou delegar. O modelo escolhe os meios e pode combinar consultas, ações estruturadas, navegação e delegação.

## Execução

- Uma proposta que altera o ambiente é validada semanticamente contra o pedido humano e o histórico. Hipóteses, citações, negações e cancelamentos não autorizam execução.
- A autorização de objetivo não concede privilégios nem elimina as confirmações existentes.
- O catálogo disponível limita as ferramentas executáveis. Chamadas repetidas não devem duplicar ações.
- Resultados reais voltam ao agente para decidir recuperação, esclarecimento ou conclusão.
- Depois de ferramentas, uma revisão contextual confere a resposta e pode solicitar continuação. Conversa sem ferramentas não recebe essa chamada extra, por preferência do usuário.
- Os orçamentos dão espaço para progresso novo, mantendo um teto e informando resultados parciais.

## Android

Mencionar o PC não encaminha automaticamente uma conversa à ponte. O modo remoto escolhido manualmente continua sendo uma seleção explícita de destino. Encerrar a conversa e selecionar o modo TV são ferramentas decididas pelo contexto. Encerrar preserva wake word e acompanhamentos já solicitados.

## Limites preservados

Controles físicos, permissões do sistema, seleção de destino, cancelamento, confirmação de ações sensíveis e detecção acústica da wake word continuam mecânicos. Quando o serviço de IA está indisponível, há uma mensagem de emergência, pois ele não pode gerar uma explicação naquele momento.

Os controladores legados de intenção continuam para compatibilidade quando o modo de agente é explicitamente desativado; não são usados no fluxo normal. O roteador de participação/administração do Discord tem seu próprio controle de audiência e permanece separado desta mudança de PC/Android.

# Validação da reprodução — 0.1.16

Testado em Moto G22, Android 12, conexão móvel, em 3 de outubro de 2026.
As medições variam com a rede e com o YouTube; não são uma promessa de latência.

## Trocas rápidas

`MusicRapidSkipDeviceTest` usa o serviço Media3 real, três faixas online,
quatro rodadas, cancelamento de seleções intermediárias e chaves de cache novas.
Mede da última seleção até `isPlaying`, confere a faixa escolhida e erros.
Volume zero; restaura a fila, posição e opções anteriores.

Antes da renovação rápida, uma rodada precisou de 20.045 ms; as seguintes
ficaram em 2.806, 2.750 e 2.766 ms. A primeira precisou do extrator alternativo
após uma recusa HTTP do endereço integrado.

Com renovação rápida antes do alternativo: 3.969, 5.004, 3.008 e 2.781 ms.
Todas tocaram a faixa final correta, sem erro. Não se atribui toda a diferença
ao código: a recusa do YouTube é intermitente, reproduzida também em consultas
diretas do extrator integrado.

## Recuperação e limites

- 32 testes JVM passaram: compartilhamento, cancelamento, prioridade,
  promoção de preparo e corrida entre extratores, além dos testes existentes.
- Testes Media3 de recusa permanente passaram: renovação rápida, alternativa
  e erro final, sem tentativas ilimitadas. Posição, tamanho e chave de cache
  são preservados.
- O alternativo real retornou áudio legível em 16.252 ms. Ele continua mais
  lento; é reserva e não substitui permanentemente o integrado após uma
  recusa temporária.
- `MusicContinuousPlaybackDeviceTest` passou após os ajustes finais:
  sequência, aleatório, reordenação, repetição e preparo da próxima faixa.
- `MusicPlaybackCommandsDeviceTest` passou: o WebView preserva a última
  seleção e a ordem recebida dos comandos de próxima/anterior.
- A resolução tem limite de 25 s; cada tentativa alternativa, 20 s. Uma
  recuperação HTTP pode iniciar nova resolução, portanto esses valores não
  representam um limite total até a reprodução.
- Downloads e buscas mantêm seus próprios caminhos e limites. O cache de
  bytes da reprodução, por conta, continua habilitado para repetição.

Logs locais de validação: `/tmp/music16-renew-build.log`,
`/tmp/music16-renew-device.log`, `/tmp/music16-optimized-fallback.log`.
Regressão final: `/tmp/music16-final-regression.log`.
Não incluem endereços assinados de áudio nem credenciais.

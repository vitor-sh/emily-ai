# Identificação de músicas

Peça à Emily para identificar a música tocando. No PC, `fonte=sistema`
captura o monitor de áudio do Fedora/PipeWire; `microfone` captura o ambiente.
No Android, `ambiente` usa o microfone; `sistema` pede a autorização de captura
do Android. Apps podem bloquear a captura interna. O cartão tem cancelamento e mini player (pausa/parada e, no Android, avanço),
capa, título, artista, YouTube e escolha da versão para ouvir/salvar no Emily Music.
Com overlay autorizado, a permissão usa uma Activity translúcida em tarefa
separada e volta ao app anterior. A captura aguarda esse retorno e até 20 s
pelo primeiro som; o silêncio inicial não gasta os 12/24 s do trecho.

O áudio deste recurso fica em memória: WAV PCM, 12 ou 24 segundos, até 3 MiB.
Não passa pelos filtros de fala. ShazamIO recebe janelas de até 12 segundos,
sem transcodificar desnecessariamente o trecho original. A captura longa permite
uma segunda janela distinta. Isso não garante identificar covers, remixes,
gravações inéditas, instrumentos ao vivo ou trechos com muito ruído.

## Serviço

O reconhecedor usa um processo Python separado para isolar bibliotecas nativas.
No PC e na Oracle, o ambiente padrão é
`~/.local/share/emily/music-recognition-venv/bin/python`.
Instale `music-recognition-requirements.txt` nesse ambiente. A versão atual foi
validada em Python 3.11 no Fedora e 3.12 na Oracle; não use o Python 3.14 do
aplicativo para importar diretamente o núcleo nativo desta versão do ShazamIO.
`EMILY_MUSIC_PYTHON` pode apontar para outro interpretador compatível.

Endpoints autenticados: gateway PC `/music/identify` e Oracle
`/bridge/music/identify`, com corpo `audio/wav`. O celular usa a credencial
revogável do pareamento. Falhas e ausência de correspondência não geram nomes
inventados. ShazamIO é uma integração não oficial: disponibilidade e protocolo
dependem do serviço externo.

## AudD opcional

Nenhuma conta paga ou chave foi criada. Para habilitar futuramente, configure
`EMILY_AUDD_TOKEN` no ambiente do processo que atende o endpoint (gateway no PC;
serviço `emily-relay` na Oracle), com a chave mantida fora do código.
`audd=1` autoriza uma consulta de fallback somente se o Shazam não encontrar.
Sem a escolha explícita ou sem chave, nenhuma consulta é enviada ao AudD.
O cartão oferece a segunda tentativa quando o servidor informa que há chave.

No Android, ouvir e salvar usam o aplicativo independente `com.emily.music`,
pela API MediaBrowser existente. A conexão aceita a Emily somente com pacote
específico e assinatura coincidente; login, conta e IDs opacos continuam
validados pelo Music. Não copia tokens nem salva na biblioteca antiga embutida.

## Escuta normal no Android

AudioRecorder pede foco temporário de áudio e o libera ao parar/cancelar/falhar.
A escuta contínua tenta ativar AcousticEchoCanceler na sessão de voz. Não há
AEC na captura musical. A versão local do SpeechService preserva a licença
Apache 2.0 do Vosk 0.3.47 e adiciona o ciclo de vida desse efeito. Quando o
Android confirma AEC ativo, usa o limiar normal da chamada; caso contrário,
preserva o limiar elevado durante reprodução.
No modo de wake word contínuo, o foco é pedido após aceitar a chamada, durante
o comando. Não se mantém foco enquanto apenas aguarda o usuário chamar.
Apps que respeitam o foco podem pausar e retomar por conta própria; a Emily não
altera o volume salvo nem envia play indiscriminadamente a outros aplicativos.
A identificação musical usa outro gravador e não pede esse foco, preservando
a música. A escuta de wake word é suspensa durante a captura musical e depois
retorna ao estado anterior.

## Limites atuais

- Captura interna do Windows ainda não foi implementada; use microfone.
- AudD exige configurar chave separadamente; pode consumir créditos do serviço.
- A retomada de outro app depende do próprio app, assim como a permissão para
  capturar sua reprodução.
- O resultado oferece busca da gravação no YouTube; o usuário escolhe a versão
  antes de adicionar à biblioteca, evitando salvar automaticamente um cover.

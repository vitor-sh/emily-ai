# Teste de leitura de playlists públicas por link — 2026-10-03

Protótipo: `scripts/probe_spotify_playlist.py`. Não integrado ao aplicativo.
Somente metadados públicos, sem login, cookies, API key, áudio ou alterações
de biblioteca. Saída opcional JSON destina-se à inspeção do desenvolvedor,
não a um fluxo de importação por arquivos para os usuários.

## Resultados reais

| Playlist | Total declarado na página | Entradas no embed | Metadados utilizáveis | Resultado |
| --- | ---: | ---: | ---: | --- |
| Definitive Musics, link fornecido pelo proprietário | 32 | 32 | 32 | Leitura completa, ordem da prévia conferida |
| Top 50 - Global | 50 | 50 | 50 | Leitura completa, ordem da prévia conferida |
| Top 200 - Global Hits | 200 | 100 | 99 | Recusada: truncamento e uma entrada sem metadados |

Últimas leituras: aproximadamente 1,33 s, 0,92 s e 1,29 s respectivamente,
no PC nesta rede. Não são medições de Android, correspondência com YouTube
ou importação/reprodução. A playlist do proprietário foi lida integralmente
em duas execuções do protótipo, além da inspeção inicial.

A página normal trouxe 30 entradas. O embed trouxe todas as 32/50 entradas
dos casos pequenos, mas apenas 100 das 200 entradas do caso maior.
`offset=100&limit=100`, `offset=100` e `page=2` no embed devolveram as mesmas
100 entradas, com mesmos IDs inicial e final. Não foi encontrado nesses
testes um mecanismo público de paginação que entregue o restante.

O caso Top 50 apresentou IDs alternativos entre página e embed para duas
faixas, com mesmos título, artistas e duração. O protótipo aceita essa
equivalência somente se esses três metadados coincidirem. Duplicatas
intencionais são preservadas; não se compara contagem de IDs únicos com
quantidade de entradas.

## Proteções e testes

- Verifica host HTTPS, tipo de link, identidade da playlist e quantidade.
- Verifica ordem da prévia; não libera lista truncada ou com metadados faltantes.
- Limita tamanho e tempo de resposta; recusa redirecionamento para outro host.
- Exportação de diagnóstico opcional nunca sobrescreve arquivo existente.
- Sete testes unitários passaram: links, troca de playlist, formato alterado,
  truncamento, duplicatas, metadados ausentes e equivalência de IDs regionais.

## Conclusão e limites

A leitura direta funcionou para a playlist real de 32 músicas. É uma opção
experimental para playlists públicas cujo total possa ser verificado, não
uma integração geral garantida. O limite observado de 100 no embed não é
um contrato oficial nem prova de que qualquer playlist até 100 funcionará.

Não foram implementados nesta etapa: interface de importação, correspondência
Spotify→YouTube, OAuth, playlists privadas, sincronização da importação ou
publicação de APK. O objetivo autorizado foi validar primeiro a leitura.
O aplicativo instalado, suas bibliotecas e o serviço publicado ficaram intactos.
Próximo passo possível: importação experimental com prévia, confirmação,
checagem de correspondências, progresso/cancelamento e mensagem clara quando
não for possível obter a lista inteira. Playlists maiores precisam de outro
caminho; nunca apresentar 100 de 200 como importação concluída.

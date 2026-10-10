# Emily Music — serviço na nuvem

Cloudflare Workers Free + D1, autenticado com Firebase Google Sign-In.
Em ACCOUNT_MODE=google, qualquer conta Google verificada pode usar a beta.
Em modo restrito (sem essa variável), ALLOWED_EMAILS autoriza emails específicos.
Nenhum cadastro de aparelho é necessário: a biblioteca pertence ao UID Firebase.

Rotas:
- GET /health: disponibilidade.
- GET /v1/account: valida o login (sem cota de busca).
- POST /v1/music/search: busca oficial YouTube, cache e limites existentes.
- POST /v1/music/library: campos de playlists, curtidas e preferências por UID.
- GET /v1/app/update: metadados públicos da versão, sem dados de usuários.

Bibliotecas usam revisões e mesclagem por campo (timestamp + id) com tombstones;
concorrência no D1 é tratada por compare-and-swap. Limite de 1,5 MB por biblioteca,
12 sincronizações/minuto/conta. Sem mudanças, só a revisão é trocada.
O app reduz as capas grandes antes de enviar; fotos originais permanecem locais.
Áudio local, downloads, fila, posição e pasta Músicas locais não são enviados.
Não há acesso à ponte pessoal da Emily.

## Publicação

Segredos YOUTUBE_API_KEY e MUSIC_UPDATE_JSON ficam no Worker. Firebase tokens
são verificados com a assinatura oficial, projeto, Google como provedor e email
verificado. O UID vem do token, nunca de um parâmetro enviado pelo cliente.
`npm test`, teste D1 local (`npm run test:d1` com fixture rodando),
`npx wrangler d1 execute emily-music-search --remote --file=schema.sql`,
`npx wrangler deploy`.

Atualizações: executar ../EmilyMusic/scripts/publish.py conforme o README do app.
O script publica APK/fonte limpos no GitHub, verifica o download e só então
atualiza MUSIC_UPDATE_JSON. Não colocar certificado ou secrets no repositório.
Plano pago não foi ativado. Cotas da busca são compartilhadas: 90 consultas
externas/dia no total, 25 por usuário e 12 pedidos/minuto; cache reduz consumo.
Falhas mantêm dados no aparelho para nova tentativa. Remover ACCOUNT_MODE=google
e configurar ALLOWED_EMAILS retorna ao acesso restrito, se necessário.

O fixture test/d1-worker.js é exclusivamente local e nunca deve ser publicado.

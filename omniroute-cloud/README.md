# OmniRoute da Emily na nuvem

Preparação para um VPS pago, independente do fornecedor. A instalação atual do
PC continua funcionando: nenhum serviço, banco, token ou endpoint dela é alterado
por estes arquivos. Este diretório pode ser copiado sozinho para o servidor.

## O que está preparado

- OmniRoute **3.8.51**, mesma versão instalada no PC, em container oficial.
- Caddy **2.10.2**, HTTPS automático e streaming sem buffering do proxy.
- Somente inferência e saúde disponíveis pela internet; painel apenas via SSH.
- API exige chave; senha administrativa e segredos gerados individualmente.
- Banco e certificados persistem em volumes. Reinício automático após falha do
  processo ou reinicialização do servidor (`unless-stopped`). Healthcheck informa
  saúde, mas Docker Compose não reinicia sozinho um processo apenas por unhealthy.
- Backup consistente dos dados **e segredos**, com pausa curta e retomada.
- Verificador para impedir migração com painel exposto ou autenticação quebrada.

## Antes de contratar

Para esta configuração, escolha **Ubuntu 24.04 LTS x86-64, IPv4 público, SSD de
20 GB ou mais, 2 vCPU e preferencialmente 4 GB de RAM**. Um VPS de 2 GB pode servir
para conversa leve, mas o orçamento do Compose é apertado; não é garantia para
contextos grandes ou muitas chamadas simultâneas. O container limita RAM a
1,5 GB e heap a 1 GB: medir uso real antes de aumentar ou contratar mais RAM.

Não é necessário GPU: os modelos continuam executando nos provedores. Hospedar
OmniRoute não elimina cotas, renovação das autorizações nem falhas dos provedores.
Esta receita não inclui Chromium, CLIs extras ou provedores que exigem navegador.

Além do VPS, é necessário um endereço DNS para HTTPS. Pode ser subdomínio de um
domínio seu ou um endereço gratuito do [DuckDNS](https://www.duckdns.org/).
Cadastre um nome e aponte para o IPv4 do VPS. Não é necessário comprar domínio.

## Roteiro para segunda-feira

1. Contratar o VPS e guardar IP, usuário SSH e chave de acesso.
2. Apontar o DNS para esse IP. Se existir AAAA, deve apontar para o IPv6 correto
   deste servidor; remova registros de outro servidor antes de emitir TLS.
3. No firewall **do provedor**, permitir TCP 80 e 443; restringir SSH ao seu IP
   quando possível. Não abrir 20128, 5000 ou 5001. Portas publicadas pelo Docker
   podem ignorar regras do UFW; a restrição no provedor evita essa dependência.
4. Instalar Docker Engine e Compose plugin pelo
   [procedimento oficial para Ubuntu](https://docs.docker.com/engine/install/ubuntu/).
   Ativar o daemon no boot (`sudo systemctl enable --now docker`). Instalar Python 3.
5. Copiar este diretório para `~/omniroute-cloud` no VPS. Não copiar a `.env` da
   Emily nem seu diretório `~/.omniroute`.

**Os comandos abaixo são executados no VPS**, dentro da pasta copiada. Pressupõem
que seu usuário já pode executar Docker; se exige sudo, execute Docker/backup com
sudo também. Nunca instale esta stack nas portas da instância atual do PC.

```bash
cd ~/omniroute-cloud
python3 preparar.py seu-nome.duckdns.org
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose ps
```

O preparador cria `.env` com permissão 600 e não imprime segredos. Ele se recusa
a substituir uma configuração existente, para não perder a chave do banco.
`docker compose config` sem `--quiet` mostra segredos; evite compartilhar essa saída.

## Configurar provedores e chave da Emily

No **PC**, abra um túnel (troque USUARIO e IP):

```bash
ssh -N -L 127.0.0.1:21128:127.0.0.1:20128 -L 127.0.0.1:1455:127.0.0.1:1455 USUARIO@IP_DO_VPS
```

Abra `http://127.0.0.1:21128` no navegador. A senha inicial está em
`INITIAL_PASSWORD` na `.env` do VPS: consulte-a privadamente, não envie aqui.
O painel usa cookie HTTP porque está disponível apenas em localhost pelo túnel;
os endpoints públicos sempre usam HTTPS. Não publique o painel por outro proxy.
O encaminhamento 1455 permite concluir o retorno OAuth do Codex no navegador
local. Essa porta também é publicada pelo container apenas no loopback do VPS;
não abrir 1455 na lista de segurança da Oracle. Iniciar o login pelo painel
privado depois de abrir os dois encaminhamentos, e mantê-los até concluir.

Cadastre os provedores da instalação local (Codex, Kiro, Cline, TokenRouter)
que você pretende usar. Faça novas autorizações na nuvem e confira cada uma;
não copie tokens manualmente. Alguns fluxos OAuth precisam do helper remoto ou
de túnel para a porta de callback específica. Consulte o
[guia remoto da versão usada](https://github.com/diegosouzapw/OmniRoute/blob/release/v3.8.51/docs/guides/REMOTE-MODE.md).
Vamos concluir essas autorizações juntos quando houver um VPS.

Crie uma **chave de API própria para a Emily** no painel; não reutilize a senha
administrativa, JWT_SECRET, API_KEY_SECRET ou tokens dos provedores. Mantenha
exigência de chave ativada nas configurações do OmniRoute. Confira os IDs reais
dos modelos e preserve os aliases que a Emily utiliza antes de trocar endpoints.

No PC, confira o endereço público:

```bash
python3 verificar.py https://seu-nome.duckdns.org
python3 verificar.py https://seu-nome.duckdns.org --modelo ID_REAL_DO_MODELO
```

A chave é solicitada sem eco, não entra na linha de comando. A segunda chamada
é opcional e consome cota do modelo. A primeira verifica TLS, prontidão, bloqueio
do painel, recusa de pedidos sem chave/com chave errada e catálogo autenticado.
Não migrar se qualquer verificação falhar. HTTPS real/certificado só podem ser
verificados depois de o DNS apontar para um servidor acessível.

## Migração e retorno ao método local

**Ainda não executar na configuração ativa.** Primeiro testar os modelos reais
na nuvem e salvar uma cópia privada da configuração local.

No PC, o provedor que hoje aponta para OmniRoute pode passar a usar:

```dotenv
EMILY_PROVEDOR_OMNIROUTE_BASE=https://seu-nome.duckdns.org/v1
EMILY_PROVEDOR_OMNIROUTE_CHAVE=CHAVE_CRIADA_NO_PAINEL
```

Esse é um exemplo: atualizar a seção realmente usada na `.env` (inclusive
`CLAUDE` se ela apontar para o mesmo router), sem renomear modelos/aliases e sem
substituir outros provedores. Reiniciar a Emily para recarregar seus clientes.
Para voltar, restaurar o endereço/chave anteriores e reiniciar a Emily. O serviço
local permanece disponível durante toda a transição; nenhum script o desativa.
Não existe alternância automática entre local/nuvem criada por este kit.

### Celular: etapa necessária antes de desligar o PC

Hoje o Android envia chat a `/llm/chat` na ponte pessoal do PC; não fala diretamente
com `/v1/chat/completions`. **Só hospedar OmniRoute não torna o celular independente.**
Quando o servidor for validado, será preciso configurar/adaptar um destino separado
para inferência na nuvem no app Android, mantendo a ponte do PC para comandos,
sincronização e arquivos. Não substituir a URL geral da ponte pelo VPS: isso
quebraria essas funções. Este kit não publica a ponte Flask pessoal na internet
nem transporta controles do PC, arquivos ou chaves Brave para a nuvem.

## Backup e manutenção

Dentro desta pasta no VPS:

```bash
python3 backup.py
docker compose ps
```

O backup pausa **só o OmniRoute desta stack**, copia `/app/data` com o banco fechado,
inclui `.env` e a versão da stack, e retoma o processo se ele estava ativo.
Há uma breve interrupção durante a cópia: execute fora de uma conversa em andamento.
Arquivos são privados (600), em `backups/` (700), ignorados pelo Git.

**O arquivo contém credenciais e chaves de descriptografia**: transferir via SSH
para armazenamento privado fora do VPS. Não enviar a repositórios nem compartilhar
em chats. O script não envia backups para nenhum serviço. Um backup somente no
disco do VPS não protege contra perda desse disco. Não apagar `.env` ou regenerar
STORAGE_ENCRYPTION_KEY para um banco existente.

Restauração é uma operação manual em uma stack parada, preferencialmente em VPS
novo: recuperar a `.env` original, a versão registrada e os dados no volume
`omniroute-data`, preservando dono UID/GID 1000. Não misturar com outro banco ativo.
Validar no túnel antes de reabrir o acesso público. Não há script que apague volumes
ou restaure por cima de uma instalação existente.

Antes de atualizar imagens: backup externo, registrar versão anterior, ler notas
e validar num ambiente separado. Não usar tag `latest`. `docker compose down`
preserva volumes; **não usar `down -v`**, pois apaga banco/certificados.

## Testes deste kit

```bash
python3 -m unittest -v test_cloud.py
CLOUD_CONTAINER_TEST=podman python3 -m unittest -v test_cloud.py
```

O segundo comando também aceita `docker`. Ele sobe containers descartáveis com
segredos de teste, confirma inicialização, bloqueio do painel, recusa de chave
inválida/ausente e reinício. Não usa contas/provedores reais nem serviço local.
O teste do proxy usa HTTP em loopback: TLS público é conferido por `verificar.py`
depois da instalação real. Resultados registrados em `VALIDACAO.md`.

Referência da stack: [Docker Guide do OmniRoute](https://github.com/diegosouzapw/OmniRoute/blob/release/v3.8.51/docs/guides/DOCKER_GUIDE.md).

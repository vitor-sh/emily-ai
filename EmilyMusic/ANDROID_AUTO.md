# Emily Music no Android Auto

Atualize o Emily Music e entre com Google **no celular** antes de conectar ao carro.
O Android Auto mostra Playlists, Músicas curtidas, Baixadas e Músicas locais; escolher uma faixa inicia a fila daquela coleção. Os controles de reprodução incluem anterior, próxima, pausa, repetição e aleatório, conforme a central os apresenta. A navegação e a reprodução não dependem de deixar a tela do aplicativo aberta.

Sem internet, as coleções mostram somente áudio disponível no próprio telefone. Arquivos locais sincronizados de outro aparelho precisam ter chegado ao telefone para serem reproduzidos.

## APK instalado fora da Play Store

Para usar a integração tradicional de mídia no carro:

1. No celular, abra Configurações → Android Auto (use a busca das configurações se necessário).
2. Role até Versão e toque na seção de versão/permissões dez vezes; confirme o modo de desenvolvedor.
3. Abra o menu de três pontos → Configurações do desenvolvedor → Fontes desconhecidas.
4. Reconecte o celular ao carro. Em Personalizar inicializador, confira se Emily Music está marcado.

Não é necessário desativar o Play Protect para essa configuração. Ela pertence ao Android Auto.

Referência oficial: https://developer.android.com/training/cars/testing#allow-unknown-sources

## Validação

Os testes MusicCarDeviceTest exercitam descoberta/navegação no MediaBrowser do Android e no Media3, busca na biblioteca, paginação, resolução de IDs para a fila da playlist, reprodução e próxima faixa sem Activity, e isolamento do catálogo de teste. A central real do carro ainda deve ser conferida pelo usuário.

Esta integração é Android Auto pelo telefone. Não é um APK separado para instalar diretamente em Android Automotive OS. A busca e as ações da integração tradicional são descritas na seção 0.1.27 abaixo. Gestão de conta e edição detalhada continuam no telefone.

## 0.1.23 — interface própria

O APK inclui Car App Library 1.7.0 e declaração de templates MEDIA, com mínimo
Car App API 8. Em hosts compatíveis há Início, Voltar, player, fila, Playlists,
Curtidas, Baixadas, Músicas locais e busca por música/artista na biblioteca.
As listas longas têm paginação no mesmo nível, evitando ultrapassar cinco telas.
Início retorna à raiz sem parar o áudio. Abrir fila/biblioteca também não pausa.

Falhas de fonte mostram uma mensagem em português, Tentar novamente e Biblioteca,
com Início/Voltar no cabeçalho. A integração MediaBrowser anterior continua
exportada e também recebe erro localizado e intenção de tentar novamente.
Importação de playlists, downloads e edição ficam no telefone.

### Distribuição necessária para a interface própria

A opção **Fontes desconhecidas** do Android Auto libera a integração tradicional
MediaBrowser, mas **não libera apps da Car App Library**. Assim, instalar nosso
APK diretamente e reconectar pode continuar abrindo apenas a interface antiga,
mesmo com o serviço de templates incluído e com Android Auto recente.

Para testar a interface própria num carro real, a orientação oficial é distribuir
por uma fonte confiável, como Google Play **Internal App Sharing** ou uma faixa
de teste interno/fechado. Isso exige preparar a distribuição no Play Console.
Atualizar/reinstalar o APK por nosso atualizador não substitui essa etapa.

O Android Auto também precisa suportar Car App API 8. O sinalizador
**Enable CAL Beta Features** citado na documentação atual é para recursos da
biblioteca 1.9; nosso APK usa 1.7.0 e não se deve prometer que esse sinalizador
libera a instalação direta desta interface.

Os testes com FakeHost verificam templates e navegação, mas não verificam a
aceitação da origem de instalação pelo Android Auto num carro real. A versão
real da central e a aceitação da distribuição ainda precisam ser testadas.
Não remover o MediaBrowser: ele também é necessário para funções de mídia da
interface própria, incluindo voz e recomendações.

Referências:
- https://developer.android.com/training/cars/apps/media
- https://developer.android.com/media/media3/session/control-playback

Distribuição/teste em carro real: https://developer.android.com/training/cars/testing#test-in-real-vehicles

## 0.1.24 — melhorias na integração tradicional gratuita

O APK continua instalável pelo atualizador/arquivo, sem conta do Play Console.
A integração tradicional anuncia quatro seções: Biblioteca, Curtidas, Baixadas e
No celular. Biblioteca reúne Todas as músicas e as playlists, com ícones e capas;
as playlists indicam o número de faixas disponíveis. A busca consulta a biblioteca,
aceita palavras sem acento e evita duplicar músicas de várias playlists.

Os nós e faixas anunciam ações de **Início**, **Voltar** e **Em reprodução**.
O serviço devolve o destino de navegação pelo protocolo de custom browse actions,
sem abrir uma Activity no celular e sem pausar, trocar ou reiniciar a música.
Essas ações pertencem às listas de navegação; não são uma barra própria na tela
de reprodução. Cada host decide suporte, quantidade, posição e exibição das ações.
Uma central sem suporte pode mostrar somente a navegação normal do Android Auto.

Após atualizar no telefone, desconecte/reconecte o Android Auto e abra Emily Music
pelo inicializador para carregar o catálogo. Não é necessário reinstalar nem apagar
a biblioteca. Os testes de MediaBrowserCompat conferem a integração tradicional;
confirmar o desenho/posição final exige observar a central física.

Referência de ações: https://developer.android.com/training/cars/media/create-media-browser/custom-browse-actions

## 0.1.25 — abas e capas

As abas usam URIs android.resource de vetores monocromáticos, com estilo de
categoria. Os cartões usam capas quadradas de 512 px: capa escolhida explicitamente
é preservada; sem capa, até quatro imagens das músicas formam uma colagem.
Sem imagens disponíveis, há um cartão com fundo e símbolo central com margem,
em vez de ampliar o símbolo até preencher a capa inteira.

Imagens privadas (incluindo capas de MP3 e fotos sincronizadas) são servidas por
URIs content protegidas, concedidas apenas ao controlador de mídia conectado.
Não se compartilham file:// nem URLs exclusivas da WebView. Troca de conta impede
leitura de URIs da conta anterior. Downloads de miniaturas são limitados, em
segundo plano e com cache; falha temporária não grava uma colagem incompleta.

Os cartões não exibem descrições repetitivas que cortavam títulos. A seleção
padrão vazia é omitida quando existem outras playlists; a coleção não é apagada.
As abas são Biblioteca, Curtidas, Baixadas e Local. O tamanho dos cartões,
a posição dos controles e a cor do destaque continuam definidos pelo Android Auto.

## 0.1.27 — busca online e ações de biblioteca

A lupa do Android Auto consulta músicas e playlists online e também encontra
músicas/artistas e nomes de playlists salvas. Abra **Filtros** nos resultados para
escolher Tudo, Músicas, Playlists, Mais vistas, Até 4 min, 20 min ou mais ou
Na biblioteca. Os filtros de duração/visualizações usam os metadados da busca
online; faixas salvas sem essas informações não são incluídas nesses filtros.

Playlists encontradas podem ser abertas sem salvar; escolher uma faixa mantém
a fila e a ordem da playlist. Nos menus dos resultados, há Salvar na biblioteca,
Adicionar à playlist, Curtir/descurtir e Baixar. Adicionar abre as playlists do
usuário; use Adicionar aqui na escolhida. Salvar uma playlist usa o mesmo importador
do celular, com até 200 faixas, indicação de leitura parcial e prevenção de duplicatas.
Downloads usam a fila persistente existente do Android e não dependem do PC.

Falhas de rede preservam resultados locais; Tentar novamente recupera a busca ou
playlist. Resultados online usam IDs opacos temporários por sessão/conta. Uma busca
expirada precisa ser refeita; um ID inventado não permite inserir uma URL de áudio.

O teclado, a disponibilidade de digitação (inclusive com o carro em movimento),
a posição/quantidade dos menus e botões e a navegação nativa são definidos pelo
Android Auto. Criar/renomear/apagar playlists, reorganizar faixas, colar links e
gerenciar conta continuam no celular; o protocolo tradicional não oferece nossos
formulários de edição. A interface experimental de templates mantém sua busca
local e não é a interface que o carro abre pelo APK instalado diretamente.

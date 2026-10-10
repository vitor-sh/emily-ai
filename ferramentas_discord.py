"""
ferramentas_discord.py — o catálogo de administração do Discord.

Por que é um arquivo separado
─────────────────────────────
O ferramentas.py já tem mil linhas e cuida do PC do Vitor: app, pasta,
arquivo, tela, memória. Administração de servidor é outro domínio inteiro,
com 30+ ferramentas próprias. Enfiar tudo lá dentro faria o arquivo dobrar
de tamanho sem ganho nenhum de coesão.

Por que recebe registrar/Ferramenta por parâmetro
─────────────────────────────────────────────────
Se este módulo fizesse `import ferramentas`, e o ferramentas.py importasse
este no fim do arquivo dele, teríamos ciclo de importação. Funcionaria por
acidente (o registrar já estaria definido na hora), mas quebraria no dia em
que alguém movesse uma linha. Recebendo a fábrica por parâmetro, a
dependência é de mão única: ferramentas -> ferramentas_discord, e nada volta.

Sobre as descrições
───────────────────
Cada descrição aqui é prompt de verdade, lido pelo modelo em toda chamada.
Elas dizem QUANDO usar e, mais importante, quando NÃO usar — é o que evita a
Emily chamar deletar_canais quando alguém pediu pra renomear.
"""

from __future__ import annotations

# Grupo do catálogo. O laço de ferramentas do Discord (modelo.py) pede só
# este grupo mais alguns gerais, pra não pagar as ferramentas de automação do
# Windows num pedido que veio do chat.
GRUPO = "discord"

_SERVIDOR = {
    "type": "string",
    "description": (
        "Nome do servidor. Deixe vazio quando o pedido veio do chat do próprio "
        "Discord: nesse caso o servidor de onde a mensagem veio é usado "
        "automaticamente. Nunca invente nome de servidor."
    ),
}


def registrar_tudo(registrar, Ferramenta) -> int:
    """Registra o catálogo de Discord. Devolve quantas ferramentas entraram."""
    import discord_admin as adm

    antes = 0

    def nova(nome, descricao, propriedades=None, obrigatorios=None,
             destrutiva=False, executar=None):
        nonlocal antes
        registrar(Ferramenta(
            nome=nome,
            descricao=descricao,
            propriedades=propriedades or {},
            obrigatorios=obrigatorios or [],
            destrutiva=destrutiva,
            grupo=GRUPO,
            executar=executar,
        ))
        antes += 1

    # ═════════════════════════════════════════════════════════════
    # LEITURA
    #
    # Vêm primeiro de propósito: são as que o modelo tem que usar ANTES de
    # criar qualquer coisa. "Cria canais parecidos com os que já tem" só
    # funciona se ele listar antes.
    # ═════════════════════════════════════════════════════════════

    nova(
        "listar_servidores_discord",
        "Lista os servidores do Discord onde a Emily está, com quantos membros, "
        "canais e cargos cada um tem. Use quando pedirem a lista ou quando você "
        "não sabe em qual servidor a ação deve acontecer. Não serve pra ver "
        "canais, cargos ou membros de um servidor específico: pra isso existem "
        "as outras listar_.",
        executar=lambda: adm.listar_servidores(),
    )

    nova(
        "listar_canais_discord",
        "Lista os canais de um servidor, organizados por categoria, com o tipo "
        "de cada um e o tópico. Chame ANTES de criar canal parecido com o que "
        "já existe, antes de renomear, mover ou apagar: é assim que você pega o "
        "nome real em vez de chutar. Pra ver cargos é listar_cargos, pra ver "
        "pessoas é listar_membros.",
        {"servidor": _SERVIDOR},
        executar=lambda servidor="": adm.listar_canais(servidor),
    )

    nova(
        "listar_cargos_discord",
        "Lista os cargos de cima pra baixo, com quantos membros cada um tem, a "
        "cor, e marcando quais estão ACIMA do cargo da Emily (esses ela não "
        "consegue mexer). Chame antes de criar, dar, editar ou apagar cargo — "
        "e antes de reordenar, pra saber a posição atual.",
        {"servidor": _SERVIDOR},
        executar=lambda servidor="": adm.listar_cargos(servidor),
    )

    nova(
        "listar_membros_discord",
        "Lista os membros com os cargos de cada um, podendo filtrar por cargo. "
        "Chame antes de dar ou tirar cargo, apelidar, castigar, expulsar ou "
        "banir alguém: é assim que você confirma o nome exato da pessoa. Nunca "
        "chute nome de membro.",
        {
            "servidor": _SERVIDOR,
            "cargo": {"type": "string", "description": "Filtrar só quem tem esse cargo"},
            "limite": {"type": "integer", "description": "Quantos mostrar, até 100"},
        },
        executar=lambda servidor="", cargo="", limite=40: adm.listar_membros(
            servidor, cargo, limite),
    )

    nova(
        "info_servidor_discord",
        "Resumo de um servidor: dono, contagem de membros, canais, cargos e que "
        "permissões a Emily tem lá. Use quando uma ação acabou de falhar por "
        "permissão (pra saber o que falta) ou quando pedirem visão geral do "
        "servidor. Pra lista detalhada de canais/cargos/membros, use as "
        "ferramentas listar_ específicas.",
        {"servidor": _SERVIDOR},
        executar=lambda servidor="": adm.info_servidor(servidor),
    )

    # ═════════════════════════════════════════════════════════════
    # CANAIS
    # ═════════════════════════════════════════════════════════════

    nova(
        "criar_canais_discord",
        "Cria um ou VÁRIOS canais de uma vez, opcionalmente dentro de uma "
        "categoria (que é criada se não existir). É esta que você usa pra pedido "
        "temático tipo 'cria uns canais de Halloween': monte a lista inteira "
        "numa ÚNICA chamada — nunca chame uma vez por canal. Canal que já "
        "existe é pulado automaticamente. Limite de 12 por vez. Pra mudar canal "
        "que JÁ existe é editar_canal; pra copiar um existente é clonar_canal.",
        {
            "canais": {
                "type": "array",
                "description": "Todos os canais a criar, de uma vez",
                "items": {
                    "type": "object",
                    "properties": {
                        "nome": {"type": "string", "description": "Nome do canal, minúsculo com hífens"},
                        "tipo": {
                            "type": "string",
                            "enum": ["texto", "voz", "forum", "anuncio", "palco"],
                            "description": "Padrão texto",
                        },
                        "topico": {"type": "string", "description": "Descrição do canal, só pra texto e fórum"},
                        "modo_lento": {"type": "integer", "description": "Segundos entre mensagens"},
                        "nsfw": {"type": "boolean"},
                        "limite_usuarios": {"type": "integer", "description": "Só pra canal de voz"},
                    },
                    "required": ["nome"],
                },
            },
            "servidor": _SERVIDOR,
            "categoria": {
                "type": "string",
                "description": "Categoria onde colocar. Se não existir, é criada.",
            },
        },
        ["canais"],
        executar=lambda canais, servidor="", categoria="": adm.criar_canais(
            canais, servidor, categoria),
    )

    nova(
        "criar_categoria_discord",
        "Cria UMA categoria vazia (aquela barra cinza que agrupa canais). Use só "
        "quando querem a categoria sozinha. Se os canais já são conhecidos, use "
        "criar_canais_discord passando a categoria: faz as duas coisas numa "
        "chamada só.",
        {
            "nome": {"type": "string"},
            "servidor": _SERVIDOR,
        },
        ["nome"],
        executar=lambda nome, servidor="": adm.criar_categoria(nome, servidor),
    )

    nova(
        "editar_canal_discord",
        "Muda um canal que JÁ existe: renomeia, muda o tópico, move pra outra "
        "categoria, liga modo lento, marca NSFW, muda posição, e em canal de "
        "VOZ ajusta bitrate (kbps) e limite de usuários (0 = ilimitado). Passe "
        "só o que vai mudar. Não é pra criar canal novo (criar_canais) nem pra "
        "apagar (deletar_canais). Pra permissão de canal específica, é "
        "definir_permissoes_canal.",
        {
            "canal": {"type": "string", "description": "Canal atual, pelo nome"},
            "servidor": _SERVIDOR,
            "novo_nome": {"type": "string"},
            "topico": {"type": "string"},
            "categoria": {"type": "string", "description": "Categoria de destino"},
            "modo_lento": {"type": "integer", "description": "Segundos, 0 desliga"},
            "nsfw": {"type": "boolean"},
            "posicao": {"type": "integer", "description": "Posição na lista"},
            "bitrate": {"type": "integer",
                        "description": "Canal de voz: kbps (8 a 96+, conforme o boost)"},
            "limite_usuarios": {"type": "integer",
                                "description": "Canal de voz: limite de gente, 0 = ilimitado"},
        },
        ["canal"],
        executar=lambda canal, servidor="", novo_nome="", topico="", categoria="",
        modo_lento=None, nsfw=None, posicao=None, bitrate=None,
        limite_usuarios=None: adm.editar_canal(
            canal, servidor, novo_nome, topico, categoria, modo_lento, nsfw,
            posicao, bitrate, limite_usuarios),
    )

    nova(
        "clonar_canal_discord",
        "Copia um canal que existe com as MESMAS permissões e configurações. "
        "Use quando pedirem um canal 'igual ao outro', 'nos mesmos moldes' ou "
        "'copia aquele lá'. Se o canal novo for diferente mesmo, use "
        "criar_canais em vez desta.",
        {
            "canal": {"type": "string"},
            "servidor": _SERVIDOR,
            "novo_nome": {"type": "string", "description": "Nome da cópia"},
        },
        ["canal"],
        executar=lambda canal, servidor="", novo_nome="": adm.clonar_canal(
            canal, servidor, novo_nome),
    )

    nova(
        "deletar_canais_discord",
        "Apaga canais DE VEZ, com tudo dentro. Só quando pedirem explicitamente "
        "apagar, deletar ou excluir — 'renomeia' ou 'mexe no canal' NÃO é "
        "pedido de apagar. Vindo do chat, ela NÃO executa na hora: devolve aviso "
        "de confirmação, você pergunta se é pra fazer mesmo, e nunca diga que "
        "já apagou antes da confirmação vir.",
        {
            "canais": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Nomes dos canais a apagar",
            },
            "servidor": _SERVIDOR,
        },
        ["canais"],
        destrutiva=True,
        executar=lambda canais, servidor="": adm.deletar_canais(canais, servidor),
    )

    # ═════════════════════════════════════════════════════════════
    # CARGOS
    # ═════════════════════════════════════════════════════════════

    nova(
        "criar_cargos_discord",
        "Cria um ou VÁRIOS cargos de uma vez, com cor, permissões e destaque na "
        "lista de membros. Cor aceita nome comum em português (roxo, abóbora) "
        "ou hex tipo #ff6600. Permissões em português: 'ver canal', 'enviar "
        "mensagens'. Permissão de PODER (administrador, gerenciar cargos, "
        "banir) só o Vitor concede — pra outra pessoa a chamada é recusada. "
        "Cargo novo é criar_cargos; mudar existente é editar_cargo. Criou e o "
        "pedido era dar pra alguém? Chame atribuir_cargo na sequência com o "
        "nome exato do cargo e os membros.",
        {
            "cargos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "nome": {"type": "string"},
                        "cor": {"type": "string", "description": "Nome de cor ou hex"},
                        "permissoes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Permissões em português",
                        },
                        "destaque": {
                            "type": "boolean",
                            "description": "Mostrar em separado na lista de membros",
                        },
                        "mencionavel": {"type": "boolean"},
                    },
                    "required": ["nome"],
                },
            },
            "servidor": _SERVIDOR,
        },
        ["cargos"],
        executar=lambda cargos, servidor="": adm.criar_cargos(cargos, servidor),
    )

    nova(
        "editar_cargo_discord",
        "Muda um cargo que JÁ existe: nome, cor, permissões, destaque ou "
        "mencionável. Passe só o que vai mudar. Cuidado: 'permissoes' SUBSTITUI "
        "todas as atuais — se for só acrescentar uma, mande a lista completa "
        "nova (liste os cargos antes pra ver as atuais). Cargo acima do da "
        "Emily não pode ser editado.",
        {
            "cargo": {"type": "string"},
            "servidor": _SERVIDOR,
            "novo_nome": {"type": "string"},
            "cor": {"type": "string"},
            "permissoes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Substitui TODAS as permissões atuais do cargo",
            },
            "destaque": {"type": "boolean"},
            "mencionavel": {"type": "boolean"},
        },
        ["cargo"],
        executar=lambda cargo, servidor="", novo_nome="", cor="", permissoes=None,
        destaque=None, mencionavel=None: adm.editar_cargo(
            cargo, servidor, novo_nome, cor, permissoes, destaque, mencionavel),
    )

    nova(
        "atribuir_cargo_discord",
        "DÁ um cargo a uma ou várias pessoas de uma vez. Não confundir com "
        "criar_cargos (que cria o cargo novo no servidor): aqui o cargo já "
        "existe e vai pras pessoas. Se o pedido era 'cria o cargo X e dá pro "
        "Y', faça as DUAS chamadas: criar_cargos primeiro, esta depois. Aceita "
        "apelido ou nome aproximado; se mais de uma pessoa bater com o nome, a "
        "ferramenta DEVOLVE a lista de candidatos — mostre e pergunte qual é a "
        "certa antes de repetir a chamada. Pra tirar depois, é remover_cargo.",
        {
            "cargo": {"type": "string"},
            "membros": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Nomes ou menções dos membros",
            },
            "servidor": _SERVIDOR,
        },
        ["cargo", "membros"],
        executar=lambda cargo, membros, servidor="": adm.atribuir_cargo(
            cargo, membros, servidor),
    )

    nova(
        "remover_cargo_discord",
        "TIRA um cargo de pessoas específicas, sem apagar o cargo do servidor. "
        "'Tira aquele cargo dele' é esta. Se a intenção é o cargo deixar de "
        "existir pra todo mundo, isso é deletar_cargos.",
        {
            "cargo": {"type": "string"},
            "membros": {"type": "array", "items": {"type": "string"}},
            "servidor": _SERVIDOR,
        },
        ["cargo", "membros"],
        executar=lambda cargo, membros, servidor="": adm.remover_cargo(
            cargo, membros, servidor),
    )

    nova(
        "reordenar_cargo_discord",
        "Move um cargo na HIERARQUIA do servidor, pra cima ou pra baixo de "
        "outro. Use quando a reclamação for de posição/ordem ('o cargo X tá "
        "embaixo do Y', 'sobe esse cargo'). Informe acima_de OU abaixo_de, não "
        "os dois. Não muda permissão nem membros.",
        {
            "cargo": {"type": "string"},
            "servidor": _SERVIDOR,
            "acima_de": {"type": "string", "description": "Cargo de referência"},
            "abaixo_de": {"type": "string", "description": "Cargo de referência"},
        },
        ["cargo"],
        executar=lambda cargo, servidor="", acima_de="", abaixo_de="":
        adm.reordenar_cargo(cargo, servidor, acima_de, abaixo_de),
    )

    nova(
        "deletar_cargos_discord",
        "APAGA cargos do servidor de vez; quem tinha perde. Só com pedido "
        "explícito de apagar/deletar/excluir. Vindo do chat exige confirmação: "
        "a ferramenta devolve aviso, você pergunta, e nunca diga que apagou "
        "antes da confirmação. Pra tirar o cargo de ALGUMAS pessoas mantendo "
        "ele no servidor, é remover_cargo.",
        {
            "cargos": {"type": "array", "items": {"type": "string"}},
            "servidor": _SERVIDOR,
        },
        ["cargos"],
        destrutiva=True,
        executar=lambda cargos, servidor="": adm.deletar_cargos(cargos, servidor),
    )

    # ═════════════════════════════════════════════════════════════
    # PERMISSÕES DE CANAL
    # ═════════════════════════════════════════════════════════════

    nova(
        "definir_permissoes_canal_discord",
        "Define o que um cargo ou membro PODE fazer num canal ESPECÍFICO. É a "
        "ferramenta pra deixar canal privado: negue 'ver canal' pro everyone E "
        "permita pro cargo que deve entrar (duas chamadas, um alvo cada). Use "
        "'everyone' como alvo pra afetar todo mundo. Permissão de CARGO em geral "
        "(não de canal) é editar_cargo; mover/renomear o canal é editar_canal.",
        {
            "canal": {"type": "string"},
            "alvo": {
                "type": "string",
                "description": "Cargo, membro, ou 'everyone' pra todo mundo",
            },
            "servidor": _SERVIDOR,
            "permitir": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Permissões a liberar, em português",
            },
            "negar": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Permissões a bloquear, em português",
            },
            "limpar": {
                "type": "boolean",
                "description": "Remove as regras específicas e volta a herdar da categoria",
            },
        },
        ["canal", "alvo"],
        executar=lambda canal, alvo, servidor="", permitir=None, negar=None,
        limpar=False: adm.definir_permissoes_canal(
            canal, alvo, servidor, permitir, negar, limpar),
    )

    nova(
        "ver_permissoes_canal_discord",
        "LÊ as permissões específicas de um canal: quem tem regra própria e o "
        "que pode ou não pode. Use ANTES de mudar permissões de canal, pra não "
        "atropelar configuração que já existe, e pra explicar pra alguém por "
        "que não vê o canal. Só lê, não muda nada.",
        {"canal": {"type": "string"}, "servidor": _SERVIDOR},
        ["canal"],
        executar=lambda canal, servidor="": adm.ver_permissoes_canal(
            canal, servidor),
    )

    nova(
        "ver_permissoes_cargo_discord",
        "Lê TODAS as permissões de um cargo (o que tem e o que não tem). Use "
        "antes de editar_cargo, porque as permissões de lá SUBSTITUEM a lista "
        "inteira — sem ler antes você apaga permissão sem querer. Só lê.",
        {"cargo": {"type": "string"}, "servidor": _SERVIDOR},
        ["cargo"],
        executar=lambda cargo, servidor="": adm.ver_permissoes_cargo(
            cargo, servidor),
    )

    nova(
        "ver_hierarquia_discord",
        "DIAGNÓSTICO de hierarquia: mostra onde o cargo da Emily está DE "
        "VERDADE na lista de cargos (lido agora do Discord, sem cache) e se "
        "ela consegue dar/mexer num cargo específico. Use SEMPRE que der erro "
        "de 'cargo acima da Emily' ou quando alguém duvidar da ordem — o "
        "resultado é a verdade do Discord neste instante. Só lê, não muda nada.",
        {
            "cargo": {"type": "string",
                      "description": "Cargo pra verificar (opcional)"},
            "servidor": _SERVIDOR,
        },
        executar=lambda cargo="", servidor="": adm.ver_hierarquia(
            cargo, servidor),
    )

    nova(
        "sincronizar_permissoes_canal_discord",
        "Faz um canal voltar a HERDAR as permissões da categoria dele, "
        "apagando as regras específicas. Use quando pedirem 'volta o igual à "
        "categoria', 'sincroniza', ou quando regras específicas antigas "
        "estão atrapalhando. Pra limpar as regras de UMA pessoa/cargo, "
        "definir_permissoes_canal com limpar.",
        {"canal": {"type": "string"}, "servidor": _SERVIDOR},
        ["canal"],
        executar=lambda canal, servidor="": adm.sincronizar_permissoes_canal(
            canal, servidor),
    )

    # ═════════════════════════════════════════════════════════════
    # MEMBROS
    # ═════════════════════════════════════════════════════════════

    nova(
        "apelidar_membro_discord",
        "Muda o APELIDO de alguém no servidor (o nome dentro dele). Apelido "
        "vazio remove o atual e volta pro nome original da conta. Não confunde "
        "com nome real da conta: isso ninguém muda por aqui.",
        {
            "membro": {"type": "string"},
            "apelido": {"type": "string", "description": "Vazio remove o apelido"},
            "servidor": _SERVIDOR,
        },
        ["membro"],
        executar=lambda membro, apelido="", servidor="": adm.apelidar_membro(
            membro, apelido, servidor),
    )

    nova(
        "castigar_membro_discord",
        "Deixa alguém de CASTIGO (timeout): fica mudo e sem entrar em call pelo "
        "tempo definido. É a punição LEVE — use pra flood, spam, zoação que "
        "passou do ponto. Expulsão é saída do servidor (expulsar), ban é "
        "permanente (banir): se o pedido foi desses, use a ferramenta certa. "
        "Vindo do chat exige confirmação antes.",
        {
            "membro": {"type": "string"},
            "minutos": {"type": "integer", "description": "Duração, até 40320 (28 dias)"},
            "servidor": _SERVIDOR,
            "motivo": {"type": "string", "description": "Vai pro registro de auditoria"},
        },
        ["membro"],
        destrutiva=True,
        executar=lambda membro, minutos=10, servidor="", motivo="":
        adm.castigar_membro(membro, minutos, servidor, motivo),
    )

    nova(
        "liberar_castigo_discord",
        "TIRA o castigo (timeout) de alguém antes do tempo acabar. Use quando "
        "pedirem 'tira ele do castigo', 'solta', 'perdoa'. Não serve pra ban "
        "(esse é desbanir) nem pra expulsão.",
        {"membro": {"type": "string"}, "servidor": _SERVIDOR},
        ["membro"],
        executar=lambda membro, servidor="": adm.liberar_castigo(membro, servidor),
    )

    nova(
        "expulsar_membro_discord",
        "EXPULSA alguém do servidor: sai na hora, mas pode voltar com convite "
        "novo. É o meio-termo entre castigar (fica, mas mudo) e banir (não "
        "volta). Se pedirem 'bane' ou disserem que nunca mais pode voltar, é "
        "banir_membro. Vindo do chat exige confirmação antes.",
        {
            "membro": {"type": "string"},
            "servidor": _SERVIDOR,
            "motivo": {"type": "string"},
        },
        ["membro"],
        destrutiva=True,
        executar=lambda membro, servidor="", motivo="": adm.expulsar_membro(
            membro, servidor, motivo),
    )

    nova(
        "banir_membro_discord",
        "BANE alguém: sai do servidor e NÃO volta nem com convite, só se "
        "desbanirem depois. É a punição MAIS GRAVE que existe aqui — use só "
        "quando o pedido for claro nisso ('bane', 'nunca mais volta'). Se "
        "pedirem 'expulsa' ou 'tira ele daí', pode ser expulsar (reversível); "
        "se pedirem 'castiga', é timeout (castigar). Vindo do chat exige "
        "confirmação antes.",
        {
            "membro": {"type": "string"},
            "servidor": _SERVIDOR,
            "motivo": {"type": "string"},
            "apagar_mensagens_dias": {
                "type": "integer",
                "description": "Apagar as mensagens dele dos últimos N dias, até 7",
            },
        },
        ["membro"],
        destrutiva=True,
        executar=lambda membro, servidor="", motivo="", apagar_mensagens_dias=0:
        adm.banir_membro(membro, servidor, motivo, apagar_mensagens_dias),
    )

    nova(
        "desbanir_membro_discord",
        "DESFAZ um banimento: procura a pessoa na lista de banidos e libera a "
        "volta dela. Use quando pedirem 'desbana', 'libera o ban'. Não expulsa, "
        "não castiga, não bana.",
        {
            "nome_ou_id": {"type": "string"},
            "servidor": _SERVIDOR,
        },
        ["nome_ou_id"],
        executar=lambda nome_ou_id, servidor="": adm.desbanir_membro(
            nome_ou_id, servidor),
    )

    nova(
        "mover_membro_call_discord",
        "Move alguém de canal de VOZ, ou desconecta da call se canal_voz vier "
        "vazio. Só funciona com quem JÁ está em call. 'Tira ele da call' e "
        "'puxa pro canal X' são esta ferramenta; nada disso afeta cargo, "
        "mensagem nem entrada no servidor.",
        {
            "membro": {"type": "string"},
            "canal_voz": {"type": "string", "description": "Vazio desconecta"},
            "servidor": _SERVIDOR,
        },
        ["membro"],
        executar=lambda membro, canal_voz="", servidor="": adm.mover_membro_de_call(
            membro, canal_voz, servidor),
    )

    # ═════════════════════════════════════════════════════════════
    # MENSAGENS E EXTRAS
    # ═════════════════════════════════════════════════════════════

    nova(
        "enviar_mensagem_discord",
        "Manda mensagem num canal ESPECÍFICO do servidor. Use só quando o "
        "destino é outro canal ('avisa lá no geral', 'manda no chat de anúncios'). "
        "Se quem pediu está conversando com você, RESPONDA normal sem ferramenta "
        "— chamar isto pra responder é erro. Pra aviso com destaque visual "
        "(embed), é mandar_painel_discord (ferramentas de autonomia).",
        {
            "canal": {"type": "string"},
            "texto": {"type": "string", "description": "A mensagem, no seu jeito de falar"},
            "servidor": _SERVIDOR,
        },
        ["canal", "texto"],
        executar=lambda canal, texto, servidor="": adm.enviar_mensagem_em_canal(
            canal, texto, servidor),
    )

    nova(
        "fixar_mensagem_discord",
        "FIXA a última mensagem de um canal, pra ela ficar destacada no topo. "
        "Use quando pedirem 'fixa isso', 'destaca'. Não apaga, não move, não "
        "edita nada.",
        {"canal": {"type": "string"}, "servidor": _SERVIDOR},
        ["canal"],
        executar=lambda canal, servidor="": adm.fixar_ultima_mensagem(canal, servidor),
    )

    nova(
        "apagar_mensagem_discord",
        "Apaga mensagem(ões) ESPECÍFICA(S), achada(s) por autor e trecho de "
        "texto. É esta pra 'apaga aquela mensagem', 'apaga o que eu falei', "
        "'deleta sua mensagem', e principalmente pra 'apaga TODAS as mensagens "
        "do fulano' (passe o nome dele em de_quem e a quantidade alta). Acha "
        "a pessoa mesmo por apelido, e mesmo que ela tenha SAÍDO do servidor. "
        "Nome ambíguo entre duas pessoas: a ferramenta devolve a lista — "
        "pergunte qual é a certa antes de apagar qualquer coisa. Deixe "
        "de_quem vazio ou 'voce' pras SUAS mensagens — caso mais comum, sem "
        "confirmação. NÃO use pra limpar o canal inteiro em bloco: isso é "
        "limpar_mensagens.",
        {
            "canal": {"type": "string", "description": "Canal onde está a mensagem"},
            "servidor": _SERVIDOR,
            "de_quem": {
                "type": "string",
                "description": "'voce' pra mensagens suas, ou o nome/apelido da "
                               "pessoa (funciona até pra quem saiu do servidor)",
            },
            "contendo": {
                "type": "string",
                "description": "Trecho do texto da mensagem, pra achar a certa",
            },
            "quantidade": {
                "type": "integer",
                "description": "Quantas apagar, padrão 1, até 1000 — pedidos "
                               "'apaga todas' pedem um número alto aqui",
            },
        },
        ["canal"],
        destrutiva=True,
        executar=lambda canal, servidor="", de_quem="", contendo="", quantidade=1:
        adm.apagar_mensagem(canal, servidor, de_quem, contendo, quantidade),
    )

    nova(
        "buscar_mensagens_discord",
        "LÊ as mensagens recentes de um canal, filtrando por autor e/ou trecho "
        "de texto. Use antes de apagar algo específico, pra saber o que foi "
        "dito num canal que você não acompanhou, ou pra confirmar se uma "
        "mensagem foi enviada. Só lê: não apaga nem manda nada.",
        {
            "canal": {"type": "string"},
            "servidor": _SERVIDOR,
            "de_quem": {"type": "string", "description": "'voce' ou o nome da pessoa"},
            "contendo": {"type": "string", "description": "Trecho a procurar"},
            "limite": {"type": "integer", "description": "Quantas mostrar, até 40"},
        },
        ["canal"],
        executar=lambda canal, servidor="", de_quem="", contendo="", limite=10:
        adm.buscar_mensagens(canal, servidor, de_quem, contendo, limite),
    )

    nova(
        "limpar_mensagens_discord",
        "LIMPA em bloco as últimas mensagens de um canal, até 5000 por vez, SEM "
        "olhar quem escreveu. Use quando pedirem 'limpa o canal', 'limpa essas "
        "mensagens todas'. Se é pra apagar mensagem de UMA pessoa ou UMA "
        "mensagem certa, use apagar_mensagem. Mais de 14 dias o Discord não "
        "deixa apagar em lote. Vindo do chat exige confirmação antes.",
        {
            "canal": {"type": "string"},
            "quantidade": {"type": "integer", "description": "Quantas apagar, até 5000"},
            "servidor": _SERVIDOR,
        },
        ["canal"],
        destrutiva=True,
        executar=lambda canal, quantidade=20, servidor="": adm.limpar_mensagens(
            canal, quantidade, servidor),
    )

    nova(
        "criar_convite_discord",
        "Gera um LINK DE CONVITE pro servidor. Use quando pedirem convite, "
        "link pra pessoa entrar. Você define validade (horas) e limite de usos "
        "quando fizer sentido; padrão é 24h e usos ilimitados.",
        {
            "canal": {"type": "string", "description": "Canal do convite, opcional"},
            "servidor": _SERVIDOR,
            "horas": {"type": "integer", "description": "Validade em horas, até 168"},
            "usos_maximos": {"type": "integer", "description": "0 = ilimitado"},
        },
        executar=lambda canal="", servidor="", horas=24, usos_maximos=0:
        adm.criar_convite(canal, servidor, horas, usos_maximos),
    )

    nova(
        "criar_emoji_discord",
        "Adiciona um EMOJI ao servidor a partir de uma imagem (menos de "
        "256 KB). Use quando pedirem 'adiciona esse emoji', 'cria emoji'. "
        "Aceita URL de imagem OU CAMINHO LOCAL de arquivo — se a imagem veio "
        "anexada na mensagem, use o caminho local indicado no pedido em vez "
        "de URL. Sem nenhum dos dois em mãos, peça antes de chamar.",
        {
            "nome": {"type": "string", "description": "Só letras, números e underline"},
            "url_imagem": {"type": "string",
                           "description": "URL da imagem ou caminho local do arquivo"},
            "servidor": _SERVIDOR,
        },
        ["nome", "url_imagem"],
        executar=lambda nome, url_imagem, servidor="": adm.criar_emoji(
            nome, url_imagem, servidor),
    )

    nova(
        "criar_topico_discord",
        "Cria um TÓPICO (thread) dentro de um canal de texto, com mensagem "
        "inicial opcional. Thread é aquela conversa paralela dentro do canal — "
        "não confundir com canal novo (isso é criar_canais).",
        {
            "canal": {"type": "string"},
            "nome": {"type": "string"},
            "servidor": _SERVIDOR,
            "mensagem_inicial": {"type": "string"},
        },
        ["canal", "nome"],
        executar=lambda canal, nome, servidor="", mensagem_inicial="":
        adm.criar_topico(canal, nome, servidor, mensagem_inicial),
    )

    nova(
        "editar_servidor_discord",
        "Muda as CONFIGURAÇÕES DO SERVIDOR INTEIRO: nome, descrição, FOTO "
        "(ícone), banner, nível de verificação, filtro de conteúdo, "
        "notificações padrão, idioma, canal de regras, canal de atualizações, "
        "canal do sistema, canal de ausentes (AFK) e o tempo de AFK. Foto e "
        "banner: aceitam URL da imagem OU CAMINHO LOCAL de arquivo — se a "
        "imagem veio anexada na mensagem, use o caminho local indicado no "
        "pedido; NUNCA invente URL do cdn.discordapp.com, que dá 404. "
        "Descrição, foto e banner podem ser recusados pelo Discord sem boost "
        "— a ferramenta avisa e o resto muda mesmo assim. 'Renomeia' "
        "referindo-se a CANAL é editar_canal, não esta.",
        {
            "servidor": _SERVIDOR,
            "novo_nome": {"type": "string"},
            "descricao": {"type": "string",
                          "description": "Descrição do servidor (até 120 caracteres)"},
            "icone": {"type": "string",
                      "description": "URL da imagem ou caminho local pra foto do servidor (imagem anexada: use o caminho local do pedido)"},
            "banner": {"type": "string",
                       "description": "URL da imagem ou caminho local pro banner (imagem anexada: use o caminho local do pedido)"},
            "verificacao": {"type": "string",
                            "description": "nenhuma, baixa, média, alta ou máxima"},
            "filtro_conteudo": {"type": "string",
                                "description": "desligado, 'membros sem cargo' ou todos"},
            "notificacoes": {"type": "string",
                             "description": "'todas' ou 'só menções'"},
            "idioma": {"type": "string", "description": "ex.: português, inglês"},
            "canal_regras": {"type": "string"},
            "canal_atualizacoes": {"type": "string"},
            "canal_sistema": {"type": "string",
                              "description": "Onde caem avisos de boas-vindas etc."},
            "canal_afk": {"type": "string",
                          "description": "Canal de voz pra ausentes"},
            "tempo_afk": {"type": "integer",
                          "description": "Segundos pra mover pro AFK (60 a 3600)"},
        },
        executar=lambda servidor="", novo_nome="", descricao="", icone="",
        banner="", verificacao="", filtro_conteudo="", notificacoes="",
        idioma="", canal_regras="", canal_atualizacoes="", canal_sistema="",
        canal_afk="", tempo_afk=None: adm.editar_servidor(
            servidor, novo_nome, descricao, icone, banner, verificacao,
            filtro_conteudo, notificacoes, idioma, canal_regras,
            canal_atualizacoes, canal_sistema, canal_afk, tempo_afk),
    )

    # ═════════════════════════════════════════════════════════════
    # DESFAZER
    # ═════════════════════════════════════════════════════════════

    # ═════════════════════════════════════════════════════════════
    # MEMÓRIA SOBRE OS MEMBROS
    #
    # A Emily aprende sozinha sobre quem conversa muito com ela, mas isso é
    # lento de propósito (travas no perfil_discord). Estas ferramentas existem
    # pra ela poder guardar na hora quando alguém pede, e pra dar visibilidade
    # do que ela sabe — sem isso a memória seria uma caixa preta.
    # ═════════════════════════════════════════════════════════════

    def _lembrar_membro(membro, fato, servidor=""):
        import perfil_discord
        guild = adm._resolver_servidor(servidor)
        alvo = adm._resolver_membro(guild, membro)
        return perfil_discord.adicionar_fato_manual(
            alvo.id, alvo.display_name, fato)

    nova(
        "lembrar_de_membro_discord",
        "GUARDA na sua memória um fato sobre uma pessoa do servidor. Use quando "
        "alguém contar algo sobre si que valha lembrar, ou pedirem pra você "
        "lembrar de algo sobre alguém. Fato curto e minúsculo: 'joga valorant', "
        "'estuda medicina'. Não guarde piada isolada nem coisa de uma vez só. "
        "Não confunda com lembrete de hora (marcar_lembrete_discord): este aqui "
        "não tem horário, é conhecimento sobre a pessoa.",
        {
            "membro": {"type": "string", "description": "Nome ou menção da pessoa"},
            "fato": {"type": "string", "description": "O fato, curto"},
            "servidor": _SERVIDOR,
        },
        ["membro", "fato"],
        executar=_lembrar_membro,
    )

    def _esquecer_membro(membro, fato, servidor=""):
        import perfil_discord
        guild = adm._resolver_servidor(servidor)
        alvo = adm._resolver_membro(guild, membro)
        return perfil_discord.remover_fato_manual(alvo.id, fato)

    nova(
        "esquecer_de_membro_discord",
        "APAGA um fato que você guardou sobre alguém. Use quando a pessoa dizer "
        "que aquilo está errado ou pedir pra esquecer. Precisa do fato EXATAMENTE "
        "como foi guardado — se não souber o texto exato, consulte primeiro com "
        "o_que_sei_do_membro.",
        {
            "membro": {"type": "string"},
            "fato": {"type": "string", "description": "O fato a esquecer"},
            "servidor": _SERVIDOR,
        },
        ["membro", "fato"],
        executar=_esquecer_membro,
    )

    def _o_que_sei(membro, servidor=""):
        import perfil_discord
        guild = adm._resolver_servidor(servidor)
        alvo = adm._resolver_membro(guild, membro)
        return perfil_discord.resumo_de(alvo.id)

    nova(
        "o_que_sei_do_membro_discord",
        "MOSTRA o que você tem guardado sobre uma pessoa e quanto vocês já "
        "conversaram. Use quando perguntarem 'o que você sabe sobre ele', ou "
        "ANTES de esquecer um fato (pra pegar o texto exato). Só consulta: não "
        "guarda nem apaga nada.",
        {"membro": {"type": "string"}, "servidor": _SERVIDOR},
        ["membro"],
        executar=_o_que_sei,
    )

    nova(
        "desfazer_acao_discord",
        "DESFAZ a sua ÚLTIMA alteração no servidor: apaga o que criou, devolve "
        "cargo, volta apelido. Use quando disserem que ficou errado, pedirem "
        "pra desfazer, ou reclamarem do resultado. Limite importante: coisa "
        "APAGADA (canal, cargo, mensagem) não volta — nesse caso avise logo que "
        "não tem como.",
        {"servidor": _SERVIDOR},
        executar=lambda servidor="": adm.desfazer_ultima_acao(servidor),
    )

    nova(
        "listar_acoes_desfaziveis_discord",
        "LISTA o que ainda dá pra desfazer, da mais recente pra trás. Use quando "
        "perguntarem o que você mudou, ou antes de desfazer várias vezes (pra "
        "saber quantas voltas seguras existem). Só consulta: não desfaz nada.",
        {"servidor": _SERVIDOR},
        executar=lambda servidor="": adm.listar_acoes_desfaziveis(servidor),
    )

    # Trava de sincronia entre o catálogo e o resumo que vai no system prompt.
    # Ferramenta nova sem entrada em _CAPACIDADES significa que a Emily tem uma
    # habilidade que ela não sabe que tem — e vai negar que consegue se
    # perguntarem. Aviso no console em vez de exceção: catálogo funcionando com
    # resumo incompleto é melhor que Emily sem ferramenta nenhuma.
    esquecidas = _conferir_cobertura()
    if esquecidas:
        print(f"[FERRAMENTAS] AVISO: fora do resumo de capacidades da Emily: "
              f"{', '.join(esquecidas)} — adicione em _CAPACIDADES "
              f"(ferramentas_discord.py)")

    return antes


# ═════════════════════════════════════════════════════════════════
# RESUMO DE CAPACIDADES
#
# O campo `tools` da requisição já diz ao modelo QUAIS ferramentas existem, e
# isso basta pra ele escolher. Não basta pra duas outras coisas:
#
#   1. Alguém perguntar no chat "emily, o que vc consegue fazer no servidor?".
#      Lendo só o catálogo, ela responde listando nome de função, que é o
#      oposto do jeito dela falar.
#   2. Pedido vago ("cria um canal aí"). Sabendo a FORMA do que é possível
#      (que canal tem tipo, categoria, tópico), ela pergunta a coisa certa em
#      vez de chutar ou de travar.
#
# O resumo é montado a partir dos grupos abaixo, e _conferir_cobertura garante
# que ele não descole do catálogo: ferramenta registrada que não esteja em
# nenhum grupo aparece como aviso no console. Sem essa trava, o resumo
# envelheceria calado na primeira ferramenta nova.
# ═════════════════════════════════════════════════════════════════

_CAPACIDADES = (
    ("Canais",
     "criar (texto, voz, fórum, anúncio, palco), vários de uma vez e já dentro "
     "de uma categoria nova; renomear, mudar o tópico, mover de categoria, "
     "ligar modo lento, marcar NSFW, clonar um canal existente e apagar",
     ["criar_canais_discord", "criar_categoria_discord", "editar_canal_discord",
      "clonar_canal_discord", "deletar_canais_discord"]),

    ("Cargos",
     "criar com cor e permissões, editar, apagar, dar e tirar de várias pessoas "
     "de uma vez, e mudar a posição na hierarquia",
     ["criar_cargos_discord", "editar_cargo_discord", "deletar_cargos_discord",
      "atribuir_cargo_discord", "remover_cargo_discord",
      "reordenar_cargo_discord"]),

    ("Permissões",
     "definir o que cada cargo ou pessoa pode fazer em cada canal, deixar canal "
     "privado só pra quem tem certo cargo, sincronizar um canal com a categoria, "
     "e LER as permissões atuais de um canal ou de um cargo",
     ["definir_permissoes_canal_discord", "ver_permissoes_canal_discord",
      "ver_permissoes_cargo_discord", "sincronizar_permissoes_canal_discord"]),

    ("Membros",
     "mudar apelido, deixar de castigo e liberar, expulsar, banir, desbanir, "
     "mover de call e desconectar da call",
     ["apelidar_membro_discord", "castigar_membro_discord",
      "liberar_castigo_discord", "expulsar_membro_discord",
      "banir_membro_discord", "desbanir_membro_discord",
      "mover_membro_call_discord"]),

    ("Mensagens",
     "mandar mensagem em outro canal, procurar mensagem por autor ou por texto, "
     "apagar uma mensagem específica (sua ou de outro), limpar várias de uma vez "
     "e fixar mensagem",
     ["enviar_mensagem_discord", "fixar_mensagem_discord",
      "buscar_mensagens_discord", "apagar_mensagem_discord",
      "limpar_mensagens_discord"]),

    ("Extras",
     "criar convite, adicionar emoji, abrir tópico, e mudar as configurações do "
     "servidor inteiro: nome, descrição, foto, banner, verificação, filtro de "
     "conteúdo, notificações, idioma e canais de regras/sistema/ausentes",
     ["criar_convite_discord", "criar_emoji_discord", "criar_topico_discord",
      "editar_servidor_discord"]),

    ("Consulta",
     "ver a lista de servidores, canais, cargos e membros, e checar as próprias "
     "permissões num servidor",
     ["listar_servidores_discord", "listar_canais_discord",
      "listar_cargos_discord", "listar_membros_discord",
      "info_servidor_discord", "ver_hierarquia_discord"]),

    ("Memória sobre as pessoas",
     "guardar, esquecer e consultar fatos sobre os membros do servidor — você "
     "vai conhecendo quem conversa muito com você",
     ["lembrar_de_membro_discord", "esquecer_de_membro_discord",
      "o_que_sei_do_membro_discord"]),

    ("Desfazer",
     "reverter o que ela criou ou o cargo que deu, e listar o que ainda dá pra "
     "desfazer. O que foi APAGADO não volta",
     ["desfazer_acao_discord", "listar_acoes_desfaziveis_discord"]),
)


def resumo_capacidades() -> str:
    """Bloco compacto pro system prompt, agrupado por domínio."""
    linhas = ["O QUE VOCÊ CONSEGUE FAZER NO SERVIDOR"]
    for titulo, descricao, _ in _CAPACIDADES:
        linhas.append(f"{titulo}: {descricao}.")
    linhas.append(
        "Fora dessa lista você não consegue: não mexe em configuração de "
        "Comunidade, não altera o dono, não lê mensagem apagada e não faz nada "
        "no PC do Vitor a partir do chat."
    )
    return "\n".join(linhas)


def _conferir_cobertura() -> list:
    """Ferramentas registradas que ficaram fora do resumo."""
    cobertas = {n for _, _, lista in _CAPACIDADES for n in lista}
    return sorted(set(nomes()) - cobertas)


def nomes() -> list:
    """Os nomes registrados por este módulo, pra filtrar catálogo por grupo."""
    return [
        "listar_servidores_discord", "listar_canais_discord",
        "listar_cargos_discord", "listar_membros_discord",
        "info_servidor_discord", "ver_hierarquia_discord",
        "criar_canais_discord", "criar_categoria_discord",
        "editar_canal_discord", "clonar_canal_discord", "deletar_canais_discord",
        "criar_cargos_discord", "editar_cargo_discord", "atribuir_cargo_discord",
        "remover_cargo_discord", "reordenar_cargo_discord", "deletar_cargos_discord",
        "definir_permissoes_canal_discord",
        "ver_permissoes_canal_discord", "ver_permissoes_cargo_discord",
        "sincronizar_permissoes_canal_discord",
        "apelidar_membro_discord", "castigar_membro_discord",
        "liberar_castigo_discord", "expulsar_membro_discord",
        "banir_membro_discord", "desbanir_membro_discord",
        "mover_membro_call_discord",
        "enviar_mensagem_discord", "fixar_mensagem_discord",
        "buscar_mensagens_discord", "apagar_mensagem_discord",
        "limpar_mensagens_discord", "criar_convite_discord",
        "criar_emoji_discord", "criar_topico_discord", "editar_servidor_discord",
        "lembrar_de_membro_discord", "esquecer_de_membro_discord",
        "o_que_sei_do_membro_discord",
        "desfazer_acao_discord", "listar_acoes_desfaziveis_discord",
    ]

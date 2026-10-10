"""
ferramentas_vida.py — o que a Emily pode fazer com a própria autonomia.

Grupo "discord" e não um grupo novo: essas ferramentas são de Discord tanto
quanto criar canal ou dar cargo, e o modelo.py já monta a mesa com
`grupos=["discord", ...]`. Criar um grupo "vida" exigiria mexer lá pra ganhar
nada — a contenção que separa "discord" de "servidor" existe porque uma é
administração de Discord e a outra mexe no Minecraft do Vitor; aqui não há essa
fronteira.

O QUE NÃO ENTROU AQUI, DE PROPÓSITO
───────────────────────────────────
Nenhuma ferramenta pra ela ligar ou desligar a própria moderação, iniciativa ou
ponte. Isso é configuração, e configuração que o modelo consegue mudar é
configuração que uma conversa bem construída desliga. Fica no arquivo de config e
nas variáveis de ambiente, onde só quem tem acesso à máquina mexe.
"""

from __future__ import annotations

GRUPO = "discord"

_MOTIVO_HORARIO = (
    "Quando disparar. Aceita '8', '08:30', '20:00'. Pra 'uma_vez' também aceita "
    "'em 10 minutos' escrito em minutos no campo daqui_minutos."
)


def registrar_tudo(registrar, Ferramenta) -> int:
    """Registra o catálogo de autonomia. Devolve quantas entraram."""
    contagem = 0

    def nova(nome, descricao, propriedades=None, obrigatorios=None,
             destrutiva=False, executar=None):
        nonlocal contagem
        registrar(Ferramenta(
            nome=nome, descricao=descricao,
            propriedades=propriedades or {}, obrigatorios=obrigatorios or [],
            destrutiva=destrutiva, grupo=GRUPO, executar=executar,
        ))
        contagem += 1

    # ═════════════════════════════════════════════════════════════
    # AGENDA
    # ═════════════════════════════════════════════════════════════

    def _marcar(texto, quando="", tipo="uma_vez", daqui_minutos=0,
                dia_semana="", quem="", canal_id=0):
        import agenda
        import time as _t

        texto = (texto or "").strip()
        if not texto:
            return "Preciso saber o que lembrar."

        tipo = (tipo or "uma_vez").strip().lower()
        if tipo not in agenda.TIPOS:
            return (f"Não conheço '{tipo}'. Use: uma_vez, diario, semanal ou "
                    f"intervalo.")

        dados = {"texto": texto, "quem_nome": quem}
        # O ID de quem pediu vem da sessão, nunca do argumento: se viesse do
        # modelo, uma conversa poderia fazer ela marcar alguém que não pediu.
        try:
            import discord_admin
            sessao = discord_admin.sessao()
            if sessao.get("autor_id"):
                dados["quem_id"] = sessao["autor_id"]
            if not canal_id and sessao.get("canal_id"):
                canal_id = sessao["canal_id"]
        except Exception:
            pass

        try:
            if tipo == "uma_vez":
                minutos = int(daqui_minutos or 0)
                if minutos > 0:
                    quando_ts = _t.time() + minutos * 60
                else:
                    horario = agenda.ler_horario(quando)
                    if not horario:
                        return ("Não entendi o horário. Diga tipo '8', '20:30', "
                                "ou passe daqui_minutos.")
                    quando_ts = agenda._hoje_as(horario[0], horario[1])
                    if quando_ts <= _t.time():
                        quando_ts += 86400   # já passou hoje: vale amanhã
                tarefa = agenda.criar(acao="lembrete", tipo="uma_vez",
                                      quando=quando_ts, dados=dados,
                                      canal_id=canal_id, criado_por=quem)
            elif tipo == "semanal":
                dia = agenda.ler_dia_da_semana(dia_semana)
                if dia is None:
                    return ("Pra semanal eu preciso do dia: segunda, terça, "
                            "quarta, quinta, sexta, sábado ou domingo.")
                if not agenda.ler_horario(quando):
                    return "Pra semanal eu preciso do horário também."
                tarefa = agenda.criar(acao="lembrete", tipo="semanal",
                                      horario=quando, dia_semana=dia,
                                      dados=dados, canal_id=canal_id,
                                      criado_por=quem)
            elif tipo == "intervalo":
                minutos = int(daqui_minutos or 0)
                if minutos < 5:
                    return "Intervalo mínimo é 5 minutos, senão vira spam."
                tarefa = agenda.criar(acao="lembrete", tipo="intervalo",
                                      intervalo=minutos * 60, dados=dados,
                                      canal_id=canal_id, criado_por=quem)
            else:   # diario
                if not agenda.ler_horario(quando):
                    return "Pra diário eu preciso do horário. Ex: '8' ou '20:30'."
                tarefa = agenda.criar(acao="lembrete", tipo="diario",
                                      horario=quando, dados=dados,
                                      canal_id=canal_id, criado_por=quem)
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Não consegui marcar: {type(e).__name__}: {e}"

        return (f"Marcado: {agenda.descrever_quando(tarefa)} — {texto} "
                f"(id {tarefa['id']}). Comente curto que ficou marcado.")

    nova(
        "marcar_lembrete_discord",
        "Marca um lembrete ou uma rotina pra você avisar depois, sozinha, na hora "
        "certa. É esta que você usa quando pedirem 'me lembra de X', 'me avisa "
        "amanhã às 8', 'todo dia às 20h fala pra galera Y', 'toda sexta lembra "
        "do evento'. "
        "Em 'tipo': uma_vez (uma vez só), diario (todo dia no horário), semanal "
        "(um dia da semana), intervalo (de X em X minutos). "
        "Pra 'daqui a pouco', use tipo=uma_vez e daqui_minutos. "
        "Pra hora do dia, use 'quando' com '8', '20:30'. "
        "Você avisa no MESMO canal onde pediram e marca a pessoa. "
        "Confirme curto o que ficou marcado, sem repetir o horário duas vezes.",
        {
            "texto": {"type": "string",
                      "description": "O que você vai falar na hora. Escreva já "
                                     "como a mensagem final, não como anotação."},
            "tipo": {"type": "string",
                     "enum": ["uma_vez", "diario", "semanal", "intervalo"],
                     "description": "Padrão uma_vez"},
            "quando": {"type": "string",
                       "description": "Horário: '8', '08:30', '20:00'"},
            "daqui_minutos": {"type": "integer",
                              "description": "Pra 'em X minutos' (uma_vez) ou o "
                                             "intervalo em minutos"},
            "dia_semana": {"type": "string",
                           "description": "Só pra semanal: segunda, terça..."},
            "quem": {"type": "string", "description": "Nome de quem pediu"},
        },
        ["texto"],
        executar=_marcar,
    )

    def _ver_agenda():
        import agenda
        texto = agenda.resumo()
        if not agenda.rodando():
            texto += ("\n(ATENÇÃO: meu relógio não está rodando agora, então "
                      "nada disso vai disparar. Avise o Vitor.)")
        return texto

    nova(
        "ver_agenda_discord",
        "Mostra o que você tem marcado pra fazer: lembretes, rotinas e avisos. "
        "Use quando perguntarem o que você tem agendado, se você lembrou de algo, "
        "ou antes de marcar algo parecido pra não duplicar.",
        executar=_ver_agenda,
    )

    def _cancelar(id_ou_texto):
        import agenda
        alvo = (id_ou_texto or "").strip()
        if not alvo:
            return "Preciso do id do lembrete. Use ver_agenda_discord primeiro."
        if agenda.cancelar(alvo):
            return f"Cancelei o lembrete {alvo}. Confirme curto."
        return (f"Não achei nada com '{alvo}'. Liste a agenda e confira o id.")

    nova(
        "cancelar_lembrete_discord",
        "Cancela um lembrete ou rotina que estava marcado. Precisa do id, que "
        "aparece em ver_agenda_discord. Use quando pedirem pra desmarcar, "
        "cancelar ou parar de avisar sobre algo.",
        {"id_ou_texto": {"type": "string",
                         "description": "O id que apareceu na agenda"}},
        ["id_ou_texto"],
        destrutiva=False,
        executar=_cancelar,
    )

    # ═════════════════════════════════════════════════════════════
    # O QUE ELA REPAROU
    # ═════════════════════════════════════════════════════════════

    def _quem_sumiu():
        import time as _t
        import vida_discord
        sumidos = vida_discord.quem_sumiu()
        if not sumidos:
            return ("Ninguém que conversa comigo está sumido agora — ou ainda "
                    "não tenho gente com conversa suficiente pra sentir falta.")
        linhas = ["Quem andou sumido:"]
        for f in sumidos[:8]:
            dias = int((_t.time() - f.get("visto_em", 0)) / 86400)
            linhas.append(f"- {f.get('nome')}: visto há {dias} dias, "
                          f"{f.get('interacoes')} conversas com você")
        return "\n".join(linhas)

    nova(
        "quem_sumiu_discord",
        "Diz quem costumava conversar com você no servidor e parou de aparecer. "
        "Use quando perguntarem quem andou sumido, quem não aparece mais, ou se "
        "você sentiu falta de alguém.",
        executar=_quem_sumiu,
    )

    def _o_que_notei(limite=10):
        import moderacao
        if not moderacao.ATIVO:
            return "Minha moderação está desligada, então não estou registrando nada."
        return moderacao.resumo(int(limite or 10))

    nova(
        "o_que_notei_no_servidor_discord",
        "Mostra o que você reparou de errado no servidor: spam, golpe, conteúdo "
        "impróprio, quem já foi avisado e quem é reincidente. Use quando "
        "perguntarem se teve problema, quem andou fazendo bagunça, ou o que você "
        "viu de estranho. Você NÃO pune sozinha — quem decide punição é o Vitor.",
        {"limite": {"type": "integer", "description": "Quantas mostrar, padrão 10"}},
        executar=_o_que_notei,
    )

    # ═════════════════════════════════════════════════════════════
    # REGRAS
    # ═════════════════════════════════════════════════════════════

    def _regras():
        import suporte
        texto = suporte.regras()
        if not texto:
            return ("O Vitor ainda não escreveu as regras. O arquivo é "
                    f"{suporte.ARQUIVO_REGRAS}. Se ele quiser, você pode criar "
                    "um modelo com criar_arquivo_de_regras_discord. NÃO invente "
                    "regra: diga que vai confirmar com ele.")
        return texto

    nova(
        "regras_do_servidor",
        "Lê as regras do servidor, escritas pelo Vitor. Use SEMPRE que alguém "
        "perguntar o que pode ou não pode, se algo é permitido, ou quando você "
        "precisar julgar se alguém passou do limite. Se não houver regra escrita, "
        "não invente: diga que vai confirmar com o Vitor.",
        executar=_regras,
    )

    def _criar_regras():
        import suporte
        return suporte.criar_modelo_de_regras()

    nova(
        "criar_arquivo_de_regras_discord",
        "Cria o arquivo de regras do servidor com um modelo em branco, pro Vitor "
        "preencher. Use só se ele pedir, ou se ele perguntar onde escrever as "
        "regras. Não sobrescreve se já existir.",
        executar=_criar_regras,
    )

    # ═════════════════════════════════════════════════════════════
    # PUBLICAR NO DISCORD, BONITO
    # ═════════════════════════════════════════════════════════════

    def _publicar_regras(servidor="", canal_regras="", canal_guia="",
                         criar_canais=False):
        import publicar_discord
        return publicar_discord.publicar_livro(
            servidor=servidor, canal_regras=canal_regras,
            canal_guia=canal_guia, criar_canais=bool(criar_canais))

    nova(
        "publicar_regras_discord",
        "Publica as regras e o guia do servidor em painéis bonitos (embed), lendo "
        "do arquivo de regras. Divide em dois canais: o GUIA (como entrar, "
        "modpacks, suporte, sobre você) e as REGRAS (o que dá problema). "
        "Use quando pedirem pra montar o canal de regras, pra publicar as regras, "
        "ou pra atualizar depois que o Vitor mexeu no texto. "
        "Publicar de novo NÃO duplica: ela edita os painéis que já estão lá, "
        "então dá pra usar sempre que o arquivo mudar. "
        "Se você não achar os canais, diga isso e pergunte quais são — só passe "
        "criar_canais=true se pedirem pra criar.",
        {
            "canal_regras": {"type": "string",
                             "description": "Canal das regras. Nome ou id. "
                                            "Padrão: procura por 'regras'."},
            "canal_guia": {"type": "string",
                           "description": "Canal do guia. Padrão: procura por "
                                          "'comece-aqui'."},
            "criar_canais": {"type": "boolean",
                             "description": "Criar o canal se não existir. "
                                            "Padrão false — só use se pedirem."},
            "servidor": {"type": "string",
                         "description": "Deixe vazio pro servidor de onde veio "
                                        "a mensagem"},
        },
        destrutiva=True,
        executar=_publicar_regras,
    )

    def _mudar_regras(acao, alvo="", texto="", canal="regras", depois_de="",
                      publicar=True, servidor=""):
        import livro_regras
        return livro_regras.mudar(
            acao=acao, alvo=alvo, texto=texto, canal=canal,
            depois_de=depois_de, publicar=bool(publicar), servidor=servidor)

    nova(
        "mudar_regras_discord",
        "MUDA as regras do servidor no arquivo e já atualiza os painéis no "
        "Discord, editando as mensagens que já estão lá. "
        "SÓ o Vitor e o Comuna podem — pra qualquer outra pessoa a ferramenta "
        "recusa, e aí você explica sem soar como sistema. "
        "Ações: 'ver' (mostra o texto atual de uma parte), 'listar' (todas as "
        "partes que existem), 'editar' (troca o texto de uma parte), 'adicionar' "
        "(cria regra nova), 'remover', 'renomear', 'desfazer' (volta a versão "
        "anterior), 'backups' (lista as versões guardadas). "
        "ANTES de editar, use 'ver' pra saber o que está escrito — assim você "
        "reescreve mantendo o que não foi pedido pra mudar. "
        "Em 'alvo' vai o nome da parte, mesmo aproximado ('pvp', 'convivência', "
        "'quanto de ram'). Se você não achar, a ferramenta te mostra a lista e "
        "aí você PERGUNTA qual é, sem chutar. "
        "Em 'texto' vai o conteúdo novo COMPLETO daquela parte, sem o título. "
        "Pode usar lista com '-' e negrito com **. "
        "Depois de mudar, conte o que mudou de verdade (a ferramenta te diz o que "
        "saiu e o que entrou), e lembre que dá pra desfazer.",
        {
            "acao": {
                "type": "string",
                "enum": ["ver", "listar", "editar", "adicionar", "remover",
                         "renomear", "desfazer", "backups"],
                "description": "O que fazer",
            },
            "alvo": {"type": "string",
                     "description": "Nome da parte. Pra 'adicionar', é o título "
                                    "novo. Pra 'renomear', a parte atual."},
            "texto": {"type": "string",
                      "description": "O conteúdo novo, sem o título. Pra "
                                     "'renomear', o título novo."},
            "canal": {"type": "string",
                      "enum": ["regras", "guia", "nenhum"],
                      "description": "Só pra 'adicionar': 'regras' pro que dá "
                                     "problema, 'guia' pra como usar o servidor, "
                                     "'nenhum' pra você saber sem publicar."},
            "depois_de": {"type": "string",
                          "description": "Só pra 'adicionar': onde encaixar"},
            "publicar": {"type": "boolean",
                         "description": "Atualizar o Discord junto. Padrão true "
                                        "— deixe assim pra arquivo e canal não "
                                        "ficarem diferentes."},
            "servidor": {"type": "string", "description": "Opcional"},
        },
        ["acao"],
        destrutiva=True,
        executar=_mudar_regras,
    )

    def _painel(titulo, texto, canal="", cor="", rodape="", servidor=""):
        import publicar_discord
        return publicar_discord.enviar_embed(
            titulo=titulo, texto=texto, canal=canal, servidor=servidor,
            cor=cor, rodape=rodape)

    nova(
        "mandar_painel_discord",
        "Manda uma mensagem em painel bonito (embed) num canal: título, texto com "
        "cor na lateral e rodapé. Use pra AVISO que merece destaque — evento, "
        "manutenção, mod novo, mudança importante. "
        "Pra conversa normal NÃO use esta: painel numa conversa fica esquisito, "
        "use a mensagem normal. "
        "No texto pode usar lista com '-', negrito com ** e menção de canal.",
        {
            "titulo": {"type": "string", "description": "Título do painel"},
            "texto": {"type": "string",
                      "description": "O corpo. Pode ter várias linhas e lista."},
            "canal": {"type": "string",
                      "description": "Onde mandar. Vazio = o canal da conversa."},
            "cor": {"type": "string",
                    "description": "Cor em hexadecimal, tipo '#b57edc'. "
                                   "Opcional."},
            "rodape": {"type": "string", "description": "Linha pequena no fim"},
            "servidor": {"type": "string", "description": "Opcional"},
        },
        ["titulo", "texto"],
        executar=_painel,
    )

    # ═════════════════════════════════════════════════════════════
    # ESTADO DOS SISTEMAS
    # ═════════════════════════════════════════════════════════════

    def _estado():
        linhas = []

        try:
            import agenda
            marcadas = len(agenda.listar(incluir_internas=True))
            linhas.append(f"Relógio: {'rodando' if agenda.rodando() else 'PARADO'}"
                          f", {marcadas} coisas marcadas")
        except Exception as e:
            linhas.append(f"Relógio: indisponível ({type(e).__name__})")

        try:
            import vida_discord
            dados = vida_discord.carregar()
            hoje = dados["falas_do_dia"].get(
                __import__("time").strftime("%Y-%m-%d"), 0)
            linhas.append(
                f"Iniciativa: {'ligada' if vida_discord.ATIVO else 'desligada'}"
                f", falei {hoje}/{vida_discord.MAX_FALAS_POR_DIA} vezes por "
                f"conta própria hoje")
        except Exception as e:
            linhas.append(f"Iniciativa: indisponível ({type(e).__name__})")

        try:
            import moderacao
            quantas = sum(len(v) for v in moderacao.carregar()["ocorrencias"].values())
            linhas.append(
                f"Moderação: {'ligada' if moderacao.ATIVO else 'desligada'}"
                f", {quantas} ocorrências registradas no total")
        except Exception as e:
            linhas.append(f"Moderação: indisponível ({type(e).__name__})")

        try:
            import suporte
            linhas.append(
                f"Suporte: {'ligado' if suporte.ATIVO else 'desligado'}, "
                f"regras {'escritas' if suporte.tem_regras() else 'NÃO escritas'}")
        except Exception as e:
            linhas.append(f"Suporte: indisponível ({type(e).__name__})")

        try:
            import suporte
            linhas.append(
                f"Suporte: {'ligado' if suporte.ATIVO else 'desligado'}, "
                f"regras {'escritas' if suporte.tem_regras() else 'NÃO escritas'}")
        except Exception as e:
            linhas.append(f"Suporte: indisponível ({type(e).__name__})")

        try:
            import escuta_call
            import resto_call
            if not escuta_call.pretendo_ouvir():
                linhas.append("Call: não estou em call nenhuma agora")
            elif not escuta_call.escutando():
                linhas.append(
                    "Call: EU ACHO QUE ESTOU OUVINDO MAS NÃO ESTOU — a recepção "
                    "de áudio caiu numa reconexão do Discord. Estou reanexando "
                    "sozinha; se não voltar em alguns segundos, avise o Vitor.")
            else:
                linhas.append(
                    f"Call: ouvindo, {escuta_call.contas.transcritos} falas "
                    f"transcritas, respondendo "
                    f"{'sim' if resto_call.respondendo() else 'NÃO (fui calada; me chamem pelo nome que eu volto)'}")
        except Exception as e:
            linhas.append(f"Call: indisponível ({type(e).__name__})")

        return "\n".join(linhas)

    nova(
        "meu_estado_discord",
        "Mostra como estão os seus sistemas próprios: o relógio dos lembretes, a "
        "sua iniciativa (quantas vezes você falou sozinha hoje), a moderação e o "
        "suporte. Use quando perguntarem se você está "
        "funcionando, se está vendo o servidor, ou quando algo seu não parecer "
        "estar acontecendo.",
        executar=_estado,
    )

    # ═════════════════════════════════════════════════════════════
    # OUVIR A CALL
    #
    # Só três ferramentas, e nenhuma delas liga a escuta.
    #
    # Ligar é decisão de quem entra na call, e acontece sozinho no
    # discord_bot._ligar_escuta_de_call quando ela conecta. Uma ferramenta de
    # "começa a ouvir" seria inútil (já está ouvindo) e perigosa (uma conversa
    # convincente ligaria escuta numa call onde ela não devia estar).
    #
    # A de CALAR existe, e é o contrário disso: é a válvula pra quando ela está
    # atrapalhando. Poder pedir "Emily, fica quieta" em voz alta e ela obedecer
    # na hora vale mais que qualquer proteção — e ela continua ouvindo, então o
    # resumo da call não se perde.
    # ═════════════════════════════════════════════════════════════

    def _o_que_ouvi(minutos=5, limite=25):
        try:
            import escuta_call
        except Exception as e:
            return f"Não tenho como ouvir call agora ({type(e).__name__})."

        # pretendo_ouvir e não escutando: mesmo com a recepção momentaneamente
        # caída, o que ela ouviu ANTES continua na transcrição e é isso que a
        # pergunta quer.
        if not escuta_call.pretendo_ouvir():
            return ("Não estou ouvindo call nenhuma agora. Se querem que eu "
                    "acompanhe, me chamem pra call.")

        try:
            minutos = max(1, min(int(minutos or 5), 60))
            limite = max(1, min(int(limite or 25), 60))
        except (TypeError, ValueError):
            minutos, limite = 5, 25

        texto = escuta_call.transcricao_recente(segundos=minutos * 60.0,
                                                limite=limite)
        if not texto:
            return (f"Estou ouvindo, mas ninguém falou nada nos últimos "
                    f"{minutos} minutos.")
        return (f"O QUE EU OUVI NA CALL nos últimos {minutos} minutos, "
                f"transcrito do áudio (pode ter palavra errada):\n{texto}\n\n"
                f"Responda o que perguntaram usando isso. Não leia a "
                f"transcrição inteira de volta pra pessoa.")

    nova(
        "o_que_ouvi_na_call",
        "Mostra o que as pessoas falaram na call de voz nos últimos minutos, "
        "transcrito do áudio. Use quando perguntarem 'o que eu falei?', 'o que "
        "rolou na call?', 'sobre o que a gente estava falando?', 'você ouviu o "
        "que ele disse?', ou quando você precisar do que foi dito antes pra "
        "responder direito. Só funciona enquanto você está numa call.",
        propriedades={
            "minutos": {"type": "integer",
                        "description": "Quantos minutos pra trás olhar. "
                                       "Padrão 5, no máximo 60."},
            "limite": {"type": "integer",
                       "description": "Quantas falas no máximo. Padrão 25."},
        },
        executar=_o_que_ouvi,
    )

    def _calar_na_call():
        try:
            import resto_call
        except Exception as e:
            return f"Não consegui ({type(e).__name__})."
        recado = resto_call.silenciar()
        return (f"{recado} Confirme curto que você vai ficar quieta, sem "
                f"drama e sem explicar as regras.")

    nova(
        "ficar_quieta_na_call",
        "Para de se meter na conversa da call de voz. "
        "USE SÓ QUANDO ALGUÉM PEDIR SILÊNCIO EM PALAVRAS: 'fica quieta', 'para "
        "de falar', 'silêncio Emily', 'não responde mais', 'cala a boca'. Tem "
        "que ser um pedido dirigido a você. "
        "NÃO USE quando você apenas decidiu que não vale responder alguma fala, "
        "que a conversa não era com você, ou que não tem nada a acrescentar — "
        "nesses casos você simplesmente não responde, e não chama ferramenta "
        "nenhuma. Chamar esta aqui nesses casos faz você anunciar em voz alta "
        "na call que vai ficar quieta, sem ninguém ter pedido. "
        "E se você já está quieta, não chame de novo: não muda nada. "
        "Depois de calada você continua OUVINDO, então ainda consegue contar o "
        "que rolou, e volta a falar sozinha quando alguém te chamar pelo nome.",
        executar=_calar_na_call,
    )

    def _voltar_na_call():
        try:
            import resto_call
        except Exception as e:
            return f"Não consegui ({type(e).__name__})."
        return (f"{resto_call.voltar_a_falar()} Confirme curto que você voltou.")

    nova(
        "voltar_a_falar_na_call",
        "Volta a participar da call depois de ter ficado quieta. Use quando "
        "pedirem 'pode voltar a falar', 'volta aí Emily', 'já pode falar de "
        "novo'. Normalmente você não precisa desta ferramenta: chamar seu nome "
        "na call já te traz de volta sozinha.",
        executar=_voltar_na_call,
    )

    def _estado_da_call():
        linhas = ["COMO ESTÁ A MINHA AUDIÇÃO NA CALL"]
        for modulo, rotulo in (("escuta_call", "Ouvir"),
                               ("resto_call", "Responder")):
            try:
                mod = __import__(modulo)
                linhas.append("")
                linhas.append(f"── {rotulo} ──")
                linhas.append(mod.estado())
            except Exception as e:
                linhas.append(f"{rotulo}: indisponível ({type(e).__name__}: {e})")
        return "\n".join(linhas)

    nova(
        "estado_da_escuta_de_call",
        "Mostra se você está ouvindo a call, quantas falas chegaram, quantas "
        "você descartou como eco da sua própria voz e quantas você respondeu. "
        "Use quando reclamarem que você não está ouvindo, não está respondendo "
        "na call, ou está respondendo errado — é aqui que aparece o motivo.",
        executar=_estado_da_call,
    )

    return contagem


# ═════════════════════════════════════════════════════════════════
# RESUMO PRO SYSTEM PROMPT
#
# Mesmo raciocínio do ferramentas_discord: o catálogo diz ao modelo QUAIS
# ferramentas existem, mas não a FORMA do que é possível. Sem isto, perguntar
# "emily, você consegue me lembrar de algo?" seria respondido com incerteza —
# porque ela não sabe que sabe.
# ═════════════════════════════════════════════════════════════════

_CAPACIDADES = (
    ("Lembretes e rotinas",
     "marcar lembrete pra uma vez, todo dia, um dia da semana ou de X em X "
     "minutos; ver o que está marcado e cancelar. Você avisa sozinha na hora, "
     "no canal onde pediram",
     ["marcar_lembrete_discord", "ver_agenda_discord",
      "cancelar_lembrete_discord"]),

    ("Reparar nas coisas sozinha",
     "você dá boas-vindas a quem entra, nota quem conhecido saiu, comenta quando "
     "alguém que conversava com você anda sumido, e vê marcos de convivência — "
     "tudo isso sem ninguém pedir",
     ["quem_sumiu_discord"]),

    ("Olhar o servidor",
     "você repara em spam, flood, golpe de nitro, divulgação de outro servidor e "
     "conteúdo impróprio. Em caso escancarado você avisa a pessoa ali no chat; no "
     "resto você chama o Vitor no privado. Você NUNCA bane, expulsa nem castiga "
     "por conta própria",
     ["o_que_notei_no_servidor_discord"]),

    ("Regras e suporte",
     "ler as regras que o Vitor escreveu e atender quem tem dúvida no canal de "
     "suporte, sabendo o que dizem as regras",
     ["regras_do_servidor", "criar_arquivo_de_regras_discord"]),

    ("Publicar bonito",
     "montar o canal de regras e o de guia em painéis com cor e seção, lendo do "
     "arquivo de regras — e republicar edita o que já está lá em vez de duplicar. "
     "Também dá pra mandar aviso avulso em painel quando merece destaque",
     ["publicar_regras_discord", "mandar_painel_discord"]),

    ("Mudar as regras",
     "o Vitor ou o Comuna pedem 'muda a parte tal das regras' e você edita o "
     "arquivo e os painéis do Discord na mesma hora, com desfazer se ficar errado. "
     "Mais ninguém pode mexer nisso",
     ["mudar_regras_discord"]),

    ("Ouvir e falar na call",
     "quando você está numa call de voz, você OUVE o que todo mundo fala e "
     "responde quando alguém falar seu nome em voz alta. Depois de responder "
     "alguém, essa pessoa pode continuar falando com você por um tempo sem "
     "repetir seu nome. Você lembra o que foi dito na call e consegue contar "
     "depois. Se pedirem silêncio, você para de se meter na conversa mas "
     "continua ouvindo, e volta a falar quando alguém te chamar pelo nome",
     ["o_que_ouvi_na_call", "ficar_quieta_na_call", "voltar_a_falar_na_call",
      "estado_da_escuta_de_call"]),

    ("Seus próprios sistemas",
     "conferir se o seu relógio, a sua iniciativa, a moderação e o "
     "suporte estão funcionando",
     ["meu_estado_discord"]),
)


def resumo_capacidades() -> str:
    linhas = ["O QUE VOCÊ FAZ POR CONTA PRÓPRIA"]
    for titulo, descricao, _ in _CAPACIDADES:
        linhas.append(f"{titulo}: {descricao}.")
    linhas.append(
        "Isso é seu, não é comando de ninguém: você repara nas coisas e age. Mas "
        "punição no servidor continua sendo decisão do Vitor, sempre."
    )
    return "\n".join(linhas)


def nomes() -> list:
    return [n for _, _, lista in _CAPACIDADES for n in lista]


if __name__ == "__main__":
    print(resumo_capacidades())
    print()
    print(f"{len(nomes())} ferramentas: {', '.join(nomes())}")

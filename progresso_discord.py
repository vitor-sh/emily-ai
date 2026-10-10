"""
progresso_discord.py — mostrar no chat o que a Emily está fazendo enquanto faz.

O PROBLEMA
──────────
Um pedido tipo "tira o mod sculk horde" leva vários segundos: ela chama o LLM,
procura o arquivo na pasta, apaga, chama o LLM de novo pra comentar. Nesse tempo
o chat fica parado. Quem pediu não sabe se ela entendeu, se travou ou se o bot
caiu, e a reação natural é repetir o pedido — o que faz ela executar duas vezes.

A SOLUÇÃO, EM DUAS CAMADAS
──────────────────────────
1. "digitando..." desde o primeiro instante. É de graça, some sozinho e serve
   pra TODA mensagem, inclusive conversa fiada.

2. Um painel de passos, que só nasce quando uma ferramenta de verdade roda.
   Cada passo entra como linha nova e a MESMA mensagem é editada.

A camada 2 depender da primeira ferramenta é o detalhe que mantém o chat limpo:
a maioria das mensagens é conversa, e conversa não gera painel nenhum. Se o
painel aparecesse sempre, todo "kkkk" viraria duas mensagens no canal.

POR QUE EDITAR E NÃO MANDAR VÁRIAS
──────────────────────────────────
Uma mensagem por passo empilharia cinco mensagens num pedido comum e notificaria
o canal a cada uma. Editar não gera notificação e o resultado visual é o de um
painel que se preenche.

FORMATO
───────
Cada linha vai com `-#`, o subtexto do Discord, que renderiza pequeno e cinza.
É o que dá o efeito de ferramenta rodando em vez de a Emily falando: fica
visualmente separado da fala dela, que vem depois em tamanho normal.

RITMO
─────
O Discord limita edição de mensagem por canal, e um pedido grande pode disparar
passo atrás de passo. Em vez de editar a cada evento, um worker único no loop do
bot acorda a cada 400ms e grava o estado ATUAL. Passos que chegam juntos viram
uma edição só, a ordem nunca inverte, e o laço de ferramentas nunca espera por
rede — ele só marca o estado e segue, porque atrasar a ação pra desenhar o
enfeite seria trocar o problema de lugar.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from typing import Optional

# Desliga tudo com EMILY_PROGRESSO_DISCORD=0.
ATIVO = os.getenv("EMILY_PROGRESSO_DISCORD", "1").strip() != "0"

# Apagar o painel quando terminar? Padrão não: o valor está justamente em poder
# olhar depois e ver o que ela fez.
APAGAR_AO_FIM = os.getenv("EMILY_PROGRESSO_APAGAR", "0").strip() == "1"

_PAUSA_WORKER = 0.4      # de quanto em quanto o worker confere se mudou algo
_MAX_LINHAS = 8          # acima disso colapsa o começo
_MAX_DETALHE = 58        # corte do pedaço variável de cada linha
_TETO_SEGUNDOS = 300.0   # trava de segurança: nenhum painel vive mais que isso

_ICONE = {
    "rodando": "◌",
    "ok":      "✓",
    "aviso":   "!",
}


# ═════════════════════════════════════════════════════════════════
# NOME DE FERRAMENTA -> FRASE EM PORTUGUÊS
#
# "procurar_arquivo_mc" não pode aparecer no chat: é nome de função, e o painel
# é pra quem está jogando, não pra quem programou.
#
# O dicionário cobre o que tem frase melhor que a derivada. O resto cai na
# derivação automática, que é o que impede isto de virar uma lista pra manter
# desatualizada — ferramenta nova nasce com rótulo aceitável sem tocar aqui.
# ═════════════════════════════════════════════════════════════════

_FRASES = {
    # Minecraft
    "status_servidor_mc":     "vendo o status do server",
    "jogadores_online_mc":    "vendo quem tá online",
    "ler_console_mc":         "lendo o console",
    "regras_servidor_mc":     "conferindo as regras",
    "historico_servidor_mc":  "vendo o histórico",
    "comando_minecraft":      "mandando no console",
    "controlar_servidor_mc":  "mexendo no servidor",
    "listar_arquivos_mc":     "abrindo a pasta",
    "procurar_arquivo_mc":    "procurando o arquivo",
    "ler_arquivo_mc":         "lendo o arquivo",
    "escrever_arquivo_mc":    "gravando o arquivo",
    "editar_propriedade_mc":  "mudando a configuração",
    "instalar_mod_mc":        "baixando o mod",
    "deletar_arquivo_mc":     "apagando",
    "renomear_arquivo_mc":    "renomeando",
    "criar_pasta_mc":         "criando a pasta",
    "compactar_mc":           "compactando",
    "descompactar_mc":        "descompactando",
    "link_download_mc":       "gerando o link",
    "listar_backups_mc":      "vendo os backups",
    "criar_backup_mc":        "fazendo backup",
    "reinstalar_servidor_mc": "reinstalando o servidor",
    "anotar_regra_mc":        "anotando a regra",
    "anotar_sobre_servidor_mc": "anotando sobre o server",
    # Launcher / modpack no GitHub
    "status_launcher_mc":     "vendo o launcher",
    "listar_mods_launcher_mc": "vendo os mods do pack",
    "procurar_mod_launcher_mc": "procurando o mod",
    "atualizar_mods_launcher_mc": "mexendo no modpack",
    "corpo_no_jogo_mc":       "mexendo no meu corpo",
    "comparar_launcher_e_servidor_mc": "comparando launcher e servidor",
    "republicar_launcher_mc": "republicando o launcher",
    "estado_publicacao_launcher_mc": "vendo a publicação",
    "cancelar_publicacao_launcher_mc": "cancelando a publicação",
    # Discord
    "listar_servidores_discord": "vendo os servidores",
    "listar_canais_discord":  "vendo os canais",
    "listar_cargos_discord":  "vendo os cargos",
    "listar_membros_discord": "vendo os membros",
    "info_servidor_discord":  "vendo o servidor",
    "criar_canais_discord":   "criando canais",
    "criar_cargos_discord":   "criando cargos",
    "criar_categoria_discord": "criando categoria",
    "criar_topico_discord":   "criando tópico",
    "deletar_canais_discord": "apagando canais",
    "deletar_cargos_discord": "apagando cargos",
    "limpar_mensagens_discord": "limpando o chat",
    "enviar_mensagem_discord": "mandando a mensagem",
    "apagar_mensagem_discord": "apagando a mensagem",
    "buscar_mensagens_discord": "procurando a mensagem",
    "definir_permissoes_canal_discord": "mexendo nas permissões",
    "mover_membro_call_discord": "movendo de call",
    "desfazer_acao_discord":  "desfazendo",
    "listar_acoes_desfaziveis_discord": "vendo o que dá pra desfazer",
    "o_que_sei_do_membro_discord": "lembrando",
    "lembrar_de_membro_discord": "guardando isso",
    "esquecer_de_membro_discord": "esquecendo isso",
    "atribuir_cargo_discord": "dando o cargo",
    "remover_cargo_discord":  "tirando o cargo",
    "reordenar_cargo_discord": "reordenando o cargo",
    "castigar_membro_discord": "castigando",
    "liberar_castigo_discord": "tirando o castigo",
    "apelidar_membro_discord": "trocando o apelido",
}

# Argumentos que valem virar detalhe da linha, em ordem de preferência.
_ARGS_INTERESSANTES = (
    # adicionar/remover vêm antes de "pack" de propósito: no painel, "mexendo no
    # modpack: create" diz o que está acontecendo, "mexendo no modpack: guerra"
    # só diz onde.
    "termo", "comando", "adicionar", "remover",
    "caminho", "caminhos", "nome", "nomes", "canal",
    "canais", "cargo", "cargos", "membro", "membros", "chave", "acao",
    "novo_nome", "url", "regra", "nota", "mensagem", "texto",
)

_SUFIXOS = ("_mc", "_discord", "_minecraft")


def _gerundio(verbo: str) -> str:
    """'procurar' -> 'procurando'. Sem tabela: as três conjugações bastam."""
    if verbo.endswith("ar"):
        return verbo[:-2] + "ando"
    if verbo.endswith("er") or verbo.endswith("ir"):
        return verbo[:-2] + ("endo" if verbo.endswith("er") else "indo")
    return ""


def _derivar(nome: str) -> str:
    if not nome or not isinstance(nome, str):
        return "trabalhando"
    limpo = nome
    for s in _SUFIXOS:
        if limpo.endswith(s):
            limpo = limpo[: -len(s)]
            break
    partes = [p for p in limpo.split("_") if p]
    if not partes:
        return "trabalhando"
    ger = _gerundio(partes[0])
    if ger:
        return " ".join([ger] + partes[1:])
    # Não é verbo no infinitivo: é consulta ("status_servidor"). "vendo" cai bem
    # e nunca fica errado, porque toda ferramenta desse formato só lê.
    return "vendo " + " ".join(partes)


def _achatar(valor) -> str:
    if isinstance(valor, (list, tuple)):
        return ", ".join(str(v) for v in valor if v not in (None, ""))
    if isinstance(valor, bool):
        return ""
    return str(valor or "")


def _detalhe(args: dict) -> str:
    if not isinstance(args, dict):
        return ""
    for chave in _ARGS_INTERESSANTES:
        if chave in args:
            bruto = _achatar(args[chave]).strip()
            if not bruto:
                continue
            bruto = re.sub(r"\s+", " ", bruto)
            if len(bruto) > _MAX_DETALHE:
                bruto = bruto[: _MAX_DETALHE - 1].rstrip() + "…"
            return bruto
    return ""


def rotulo(nome: str, args: Optional[dict] = None) -> str:
    """A linha que vai pro chat pra uma chamada de ferramenta."""
    base = _FRASES.get(nome) or _derivar(nome)
    detalhe = _detalhe(args or {})
    return f"{base}: {detalhe}" if detalhe else base


# ═════════════════════════════════════════════════════════════════
# O RESULTADO FOI RUIM?
#
# Marcar tudo com ✓ mentiria: recusa por justificativa e argumento faltando
# voltam como texto normal, não como exceção. Os padrões abaixo são as frases
# que o ferramentas.py e o enxada.py realmente produzem quando algo não rolou.
#
# Na dúvida marca ✓. Um ✓ indevido é cosmético; um "!" indevido faria parecer
# que falhou uma coisa que funcionou, e aí o painel atrapalha em vez de ajudar.
# ═════════════════════════════════════════════════════════════════

_SINAIS_DE_PROBLEMA = (
    "não existe", "nao existe", "falhou", "argumentos inválidos",
    "faltou o argumento", "bloqueado", "motivo recusado", "não tem permissão",
    "nao tem permissao", "não achou", "nao achou", "está vazia", "esta vazia",
    "não consegui", "nao consegui", "recuse", "já foi feita", "erro",
    "não foi", "nao foi", "sem permissão", "sem permissao",
    # RECUSA da ferramenta. Faltava, e a falta era visível: quando a Emily
    # recusou montar o pack do Vitor ("NÃO montei, porque isso quebraria"), o
    # painel marcou ✓ — deu a entender que tinha dado certo, exatamente o
    # oposto. Recusa é o caso em que o "!" mais importa.
    "não montei", "nao montei", "não acrescentei", "nao acrescentei",
    "não mudei nada", "nao mudei nada", "nada foi alterado",
    "nada casou com isso", "já existe pack com id", "ja existe pack com id",
    "meu limite é", "meu limite e", "meu limite por vez",
    "meu teto é", "meu teto e", "meu teto por vez",
    "não tenho análise", "nao tenho analise", "não fui capaz", "nao fui capaz",
)


def parece_problema(resultado: str) -> bool:
    if not resultado:
        return True
    baixo = resultado.lower()
    return any(s in baixo for s in _SINAIS_DE_PROBLEMA)


# ═════════════════════════════════════════════════════════════════
# O PAINEL
# ═════════════════════════════════════════════════════════════════

class Painel:
    """
    Um painel de progresso ligado a uma mensagem do chat.

    Os métodos públicos são chamados da thread do laço de ferramentas e NUNCA
    fazem rede: só mexem em memória sob lock e marcam que há coisa nova. Quem
    fala com o Discord é o worker, no loop do bot.
    """

    def __init__(self, message, loop):
        self._message = message
        self._canal = getattr(message, "channel", None)
        self._loop = loop
        self._lock = threading.Lock()
        self._linhas: list = []      # [{"texto":..., "estado":...}]
        self._sujo = False
        self._fim = False
        self._msg = None             # a mensagem do painel, quando existir
        self._desistiu = False       # falhou ao escrever; não tenta mais
        self._worker_ligado = False
        self._nascimento = time.monotonic()

    # ── chamado da thread do laço ──────────────────────────────

    def iniciar(self) -> None:
        """Liga o 'digitando...'. Ainda não cria mensagem nenhuma."""
        if not ATIVO or self._canal is None or self._loop is None:
            return
        if self._worker_ligado:
            return
        self._worker_ligado = True
        try:
            asyncio.run_coroutine_threadsafe(self._worker(), self._loop)
        except Exception as e:
            print(f"[Progresso] não consegui ligar o worker: {e}")
            self._worker_ligado = False

    def evento(self, fase: str, dados: dict) -> None:
        """
        Ponto único que o modelo.py chama. Nunca levanta exceção: se o painel
        quebrar, o pedido tem que continuar funcionando — o enfeite é o que
        pode falhar, não a ação.
        """
        if not ATIVO:
            return
        try:
            if fase == "ferramenta":
                self._passo(rotulo(dados.get("nome", ""), dados.get("args")))
            elif fase == "resultado":
                self._fechar_ultimo(parece_problema(dados.get("resultado", "")))
        except Exception as e:
            print(f"[Progresso] evento {fase} falhou: {e}")

    def finalizar(self) -> None:
        if not ATIVO:
            return
        with self._lock:
            for linha in self._linhas:
                if linha["estado"] == "rodando":
                    linha["estado"] = "ok"
            self._fim = True
            self._sujo = bool(self._linhas)

    # ── interno ────────────────────────────────────────────────

    def _passo(self, texto: str) -> None:
        if not texto:
            return
        with self._lock:
            # Passo novo fecha o anterior. Sem isso duas linhas ficariam com o
            # ícone de "rodando" ao mesmo tempo, o que dá a impressão errada de
            # duas coisas em paralelo.
            for linha in self._linhas:
                if linha["estado"] == "rodando":
                    linha["estado"] = "ok"
            self._linhas.append({"texto": texto, "estado": "rodando"})
            self._sujo = True

    def _fechar_ultimo(self, problema: bool) -> None:
        with self._lock:
            for linha in reversed(self._linhas):
                if linha["estado"] == "rodando":
                    linha["estado"] = "aviso" if problema else "ok"
                    self._sujo = True
                    return

    def _desenhar(self) -> str:
        """Monta o texto do painel a partir do estado. Chamar sob lock."""
        if not self._linhas:
            return ""
        visiveis = self._linhas
        prefixo = []
        if len(visiveis) > _MAX_LINHAS:
            escondidas = len(visiveis) - (_MAX_LINHAS - 1)
            prefixo = [f"-# ⋯ {escondidas} passos antes"]
            visiveis = visiveis[-(_MAX_LINHAS - 1):]
        corpo = [f"-# {_ICONE.get(l['estado'], '◌')} {l['texto']}"
                 for l in visiveis]
        return "\n".join(prefixo + corpo)[:1900]

    async def _worker(self) -> None:
        """Único lugar que fala com o Discord. Vive no loop do bot."""
        try:
            async with self._canal.typing():
                while True:
                    with self._lock:
                        sujo = self._sujo and not self._desistiu
                        fim = self._fim
                        texto = self._desenhar() if sujo else ""
                        if sujo:
                            self._sujo = False

                    if texto:
                        await self._gravar(texto)

                    if fim:
                        break
                    if time.monotonic() - self._nascimento > _TETO_SEGUNDOS:
                        print("[Progresso] teto de tempo atingido; encerrando.")
                        break
                    await asyncio.sleep(_PAUSA_WORKER)
        except Exception as e:
            print(f"[Progresso] worker caiu: {e}")

        if APAGAR_AO_FIM and self._msg is not None:
            try:
                await self._msg.delete()
            except Exception:
                pass

    async def _gravar(self, texto: str) -> None:
        try:
            if self._msg is None:
                self._msg = await self._canal.send(texto)
            else:
                await self._msg.edit(content=texto)
        except Exception as e:
            # Sem permissão, mensagem apagada à mão, rate limit teimoso: nada
            # disso pode virar problema do pedido. Desliga o painel e segue.
            #
            # _desistiu, e não só _fim: sem ele um passo que chegasse depois
            # marcaria o painel como sujo outra vez e a gente tentaria escrever
            # de novo num canal onde já sabemos que não dá, enchendo o log.
            print(f"[Progresso] não consegui escrever o painel: {e}")
            with self._lock:
                self._desistiu = True
                self._fim = True


def criar(message, loop) -> Optional["Painel"]:
    """Painel pronto e já com o 'digitando...' ligado, ou None se desativado."""
    if not ATIVO or message is None or loop is None:
        return None
    p = Painel(message, loop)
    p.iniciar()
    return p


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
# ═════════════════════════════════════════════════════════════════

def _diagnosticar() -> int:
    print("=" * 66)
    print("  PROGRESSO NO DISCORD")
    print("=" * 66)
    print(f"  ativo: {ATIVO} | apagar ao fim: {APAGAR_AO_FIM}")

    print("\n-- rótulos com dicionário --")
    casos = [
        ("procurar_arquivo_mc", {"termo": "sculk horde", "caminho": "/mods"}),
        ("deletar_arquivo_mc",
         {"caminhos": ["/mods/SculkHorde-1.20.1-0.9.5.jar"]}),
        ("comando_minecraft", {"comando": "gamerule keepInventory false"}),
        ("listar_arquivos_mc", {"caminho": "/mods"}),
        ("status_servidor_mc", {}),
        ("criar_canais_discord", {"nomes": ["memes", "off-topic"]}),
        ("controlar_servidor_mc", {"acao": "reiniciar"}),
    ]
    for nome, args in casos:
        print(f"  {nome:26} -> {rotulo(nome, args)}")

    print("\n-- rótulos derivados (fora do dicionário) --")
    for nome in ("mover_canal_discord", "fixar_mensagem_discord",
                 "criar_topico_discord", "banir_membros_discord",
                 "expulsar_membro_discord", "ferramenta_nova_qualquer_mc",
                 "permissoes_canal_discord"):
        print(f"  {nome:30} -> {rotulo(nome, {})}")

    print("\n-- detecção de problema --")
    for texto, esperado in (
        ("Canal #memes criado.", False),
        ("Apagado: SculkHorde.jar", False),
        ("Procurei 'x' em /mods e não achou nada parecido.", True),
        ("BLOQUEADO. Isso é irreversível", True),
        ("MOTIVO RECUSADO, nada foi executado.", True),
        ("Faltou o argumento obrigatório termo", True),
        ("", True),
    ):
        got = parece_problema(texto)
        marca = "ok " if got == esperado else "ERRO"
        print(f"  [{marca}] {texto[:46]!r:50} -> {got}")

    print("\n-- desenho do painel --")

    class _FalsoCanal:
        pass

    class _FalsaMsg:
        channel = _FalsoCanal()

    p = Painel(_FalsaMsg(), None)
    p._passo(rotulo("procurar_arquivo_mc",
                    {"termo": "sculk horde", "caminho": "/mods"}))
    p._fechar_ultimo(False)
    p._passo(rotulo("deletar_arquivo_mc",
                    {"caminhos": ["/mods/SculkHorde-1.20.1-0.9.5.jar"]}))
    print(p._desenhar())
    p._fechar_ultimo(False)
    p.finalizar()
    print("  --- final ---")
    print(p._desenhar())

    print("\n-- colapso com muitos passos --")
    p2 = Painel(_FalsaMsg(), None)
    for i in range(14):
        p2._passo(f"passo numero {i}")
        p2._fechar_ultimo(False)
    desenho = p2._desenhar()
    print(desenho)
    print(f"  linhas desenhadas: {len(desenho.splitlines())} (teto {_MAX_LINHAS})")

    print("\n" + "=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnosticar())

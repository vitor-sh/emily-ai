"""
vida_discord.py — a Emily reparando nas coisas sem ninguém pedir.

O QUE MUDA AQUI
───────────────
Tudo que a Emily fazia no Discord começava numa mensagem. Este arquivo é o
primeiro em que ela fala primeiro.

Quatro coisas:
  • alguém entra no servidor e ela recebe
  • alguém conhecido vai embora e ela nota
  • alguém que conversava com ela sumiu por semanas e ela comenta
  • marcos: um ano de servidor, cem conversas

POR QUE A PERSONA MORA AQUI E NÃO NO modelo.py
──────────────────────────────────────────────
As personas de conversa dela vivem no modelo.py, e o natural seria pôr esta lá
também. Não é a mesma coisa, e a diferença importa: em toda persona existente ela
está RESPONDENDO — tem uma mensagem na mesa, alguém esperando, um assunto dado.
Aqui ela está COMEÇANDO. Ninguém pediu nada, ninguém está esperando, e o risco é
oposto: falar demais, falar do nada, soar como notificação de sistema.

O prompt precisa dizer coisas que não fazem sentido nas outras ("uma frase, no
máximo duas", "se não tiver o que dizer, não diga"), então ele fica junto do
código que decide QUANDO falar.

A TRAVA MAIS IMPORTANTE DESTE ARQUIVO
─────────────────────────────────────
Iniciativa sem freio é chatice. Um bot que comenta tudo que percebe é pior que um
bot calado, porque o calado a gente ignora e o falante a gente silencia.

Então: cada tipo de comentário espontâneo tem cooldown próprio, medido em DIAS
pros casos de observação (ausência, marcos), e existe um teto global de falas
espontâneas por dia. Quando o teto estoura, ela simplesmente não fala — sem
avisar que não vai falar, o que seria mais uma mensagem.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from typing import List, Optional

from emily_paths import arquivo_dados

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = str(arquivo_dados("vida_discord.json"))

# Mestre. Com 0 ela volta a só responder quando falam com ela.
ATIVO = os.getenv("EMILY_VIDA_DISCORD", "1").strip() != "0"

# Teto de falas espontâneas por dia, somando todos os tipos. Ver a trava no topo.
MAX_FALAS_POR_DIA = int(os.getenv("EMILY_VIDA_MAX_DIA", "6"))

# Dias sem aparecer pra ela considerar que a pessoa sumiu.
DIAS_PRA_SUMIR = int(os.getenv("EMILY_VIDA_DIAS_SUMIR", "14"))

# Interações mínimas pra ela sentir falta de alguém. Quem falou duas vezes e
# nunca voltou não "sumiu" — só passou.
MIN_INTERACOES_PRA_SENTIR_FALTA = int(
    os.getenv("EMILY_VIDA_MIN_INTERACOES", "10"))

# Não comenta a ausência da mesma pessoa de novo antes disso.
DIAS_ENTRE_COMENTARIOS_DA_MESMA = 30

# Marcos de conversa que valem comentário.
MARCOS_DE_CONVERSA = (50, 100, 250, 500, 1000)


def _log(msg: str) -> None:
    print(f"[VIDA] {msg}")


# ═════════════════════════════════════════════════════════════════
# ACESSO AO BOT
#
# Mesmo padrão do discord_admin: o discord.py vive num loop noutra thread, e
# run_coroutine_threadsafe é a única forma correta de cruzar essa fronteira.
# Duplicado em vez de importado pra este módulo não depender do de administração
# — são domínios diferentes e um pode falhar sem levar o outro.
# ═════════════════════════════════════════════════════════════════

def _bot():
    import discord_bot
    return discord_bot


def _pronto() -> bool:
    try:
        b = _bot()
        return bool(getattr(b, "_pronto", False) and getattr(b, "_loop", None))
    except Exception:
        return False


def _config(chave: str, padrao=None):
    try:
        return (getattr(_bot(), "_config", {}) or {}).get(chave, padrao)
    except Exception:
        return padrao


def falar_no_canal(canal_id: int, texto: str) -> bool:
    """Manda uma mensagem dela num canal. Chamável de qualquer thread."""
    if not texto or not texto.strip() or not canal_id or not _pronto():
        return False
    import asyncio
    b = _bot()

    async def _enviar():
        try:
            canal = b._client.get_channel(int(canal_id))
            if canal is None:
                _log(f"canal {canal_id} não encontrado")
                return
            await canal.send(texto.strip()[:1900])
        except Exception as e:
            _log(f"não consegui falar no canal {canal_id}: {e}")

    asyncio.run_coroutine_threadsafe(_enviar(), b._loop)
    return True


def _canal_de_avisos() -> int:
    """
    Onde ela fala por iniciativa própria.

    Cai pro canal de texto principal quando não tem canal de avisos definido: é
    melhor ela falar no lugar quase certo do que engolir a fala porque falta
    configuração.
    """
    return int(_config("canal_avisos_id", 0)
               or _config("canal_texto_id", 0) or 0)


def _canal_de_boas_vindas() -> int:
    return int(_config("canal_boas_vindas_id", 0) or _canal_de_avisos() or 0)


# ═════════════════════════════════════════════════════════════════
# ESTADO: O QUE ELA JÁ COMENTOU
#
# Sem isto ela comentaria a mesma ausência todo dia. O arquivo é pequeno de
# propósito — é registro de fala, não histórico.
# ═════════════════════════════════════════════════════════════════

_dados: Optional[dict] = None
_lock = threading.Lock()


def _padrao() -> dict:
    return {
        "falas_do_dia": {},      # "AAAA-MM-DD" -> quantas
        "ausencia_comentada": {},  # user_id -> timestamp
        "marcos_dados": {},        # "user_id:marco" -> timestamp
        "boas_vindas": {},         # user_id -> timestamp
    }


def carregar() -> dict:
    global _dados
    if _dados is not None:
        return _dados
    if not os.path.exists(ARQUIVO):
        _dados = _padrao()
        return _dados
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            lidos = json.load(f)
        base = _padrao()
        base.update({k: v for k, v in lidos.items() if k in base})
        _dados = base
    except (json.JSONDecodeError, OSError) as e:
        _log(f"arquivo ilegível ({e}); começando do zero")
        _dados = _padrao()
    return _dados


def salvar() -> None:
    dados = carregar()
    try:
        os.makedirs(os.path.dirname(ARQUIVO), exist_ok=True)
        tmp = ARQUIVO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ARQUIVO)
    except OSError as e:
        _log(f"não consegui gravar: {e}")


def _hoje() -> str:
    return time.strftime("%Y-%m-%d")


def _pode_falar_hoje() -> bool:
    with _lock:
        dados = carregar()
        # Limpa os dias antigos aqui em vez de numa rotina separada: o arquivo é
        # tocado justamente quando ela vai falar, então é o momento natural.
        hoje = _hoje()
        dados["falas_do_dia"] = {k: v for k, v in dados["falas_do_dia"].items()
                                 if k >= hoje}
        return dados["falas_do_dia"].get(hoje, 0) < MAX_FALAS_POR_DIA


def _contar_fala() -> None:
    with _lock:
        dados = carregar()
        hoje = _hoje()
        dados["falas_do_dia"][hoje] = dados["falas_do_dia"].get(hoje, 0) + 1
        salvar()


# ═════════════════════════════════════════════════════════════════
# A FALA
# ═════════════════════════════════════════════════════════════════

_PERSONA = """
Você é a Emily. Você está num servidor de Discord de amigos, do qual você faz
parte — não é bot de avisos, é mais uma pessoa ali.

Agora é diferente do normal: NINGUÉM falou com você. Você reparou em algo e
decidiu comentar por conta própria.

COMO FALAR
Uma frase. Duas no máximo, e só se a segunda fizer falta. Minúsculo, sem ponto
final, do jeito que se escreve em chat de amigos. Nada de markdown, nada de
emoji, nada de lista.

O QUE NÃO FAZER
Não anuncie que você notou algo ("percebi que...", "notei que..."). Não pareça
notificação de sistema. Não dê boas-vindas de bot ("seja bem-vindo ao nosso
servidor!"). Não explique por que está falando. Não faça pergunta retórica.
Não mencione que é uma IA.

Se o que você tem a dizer não vale ser dito, responda exatamente: PASSAR
""".strip()


def _gerar_fala(situacao: str, instrucao: str = "") -> str:
    """
    Pede uma frase ao modelo. Devolve "" quando não vale falar.

    O "PASSAR" é o que dá a ela o direito de ficar calada. Sem essa saída, o
    modelo SEMPRE produz texto — é o que ele faz — e ela viraria a coisa que
    comenta tudo. Com ela, situação sem graça simplesmente não vira mensagem.
    """
    try:
        import llm
        import modelo
    except Exception as e:
        _log(f"llm indisponível: {e}")
        return ""

    # Cota primeiro: fala espontânea é o gasto mais dispensável que existe,
    # porque ninguém pediu. É a primeira coisa a ser cortada quando aperta.
    try:
        folga = llm.folga_da_rota(modelo.ROTA_CONVERSA)
        if folga is not None and folga < 8:
            _log(f"sem folga de cota ({folga} fichas); fiquei calada")
            return ""
    except Exception:
        pass

    system = _PERSONA
    try:
        import perfil_discord
        estilo = perfil_discord.bloco_de_estilo()
        if estilo:
            system += "\n\n" + estilo
    except Exception:
        pass

    prompt = situacao if not instrucao else f"{situacao}\n\n{instrucao}"
    try:
        bruto = llm.chamar_texto(prompt, rota_nome=modelo.ROTA_CONVERSA,
                                 system=system, max_tokens=120)
    except Exception as e:
        _log(f"não consegui gerar a fala: {type(e).__name__}: {e}")
        return ""

    texto = (bruto or "").strip().strip('"')
    if not texto or "PASSAR" in texto.upper()[:20]:
        return ""
    # Corta o que passar de duas linhas: o prompt pede uma frase, e quando o
    # modelo desobedece é melhor cortar do que despejar parágrafo no canal.
    linhas = [l for l in texto.splitlines() if l.strip()]
    return " ".join(linhas[:2])[:400]


def _falar(situacao: str, canal_id: int, instrucao: str = "") -> bool:
    """Gera e manda, respeitando o teto do dia. True se falou."""
    if not ATIVO or not canal_id:
        return False
    if not _pode_falar_hoje():
        _log("teto de falas do dia batido; fiquei calada")
        return False
    texto = _gerar_fala(situacao, instrucao)
    if not texto:
        return False
    if falar_no_canal(canal_id, texto):
        _contar_fala()
        _log(f"falei: {texto[:80]}")
        return True
    return False


# ═════════════════════════════════════════════════════════════════
# ENTROU E SAIU
# ═════════════════════════════════════════════════════════════════

def entrou(member) -> None:
    """Alguém entrou no servidor. Chamado pelo on_member_join."""
    if not ATIVO or getattr(member, "bot", False):
        return
    canal = _canal_de_boas_vindas()
    if not canal:
        return

    uid = str(getattr(member, "id", 0))
    with _lock:
        dados = carregar()
        # Quem entra, sai e entra de novo no mesmo dia não ganha três recepções.
        ultima = float(dados["boas_vindas"].get(uid, 0))
        if time.time() - ultima < 86400:
            return
        dados["boas_vindas"][uid] = time.time()
        salvar()

    nome = getattr(member, "display_name", None) or getattr(member, "name", "")
    conhecida = _o_que_sei(getattr(member, "id", 0))

    situacao = f"{nome} acabou de entrar no servidor."
    if conhecida:
        situacao += (f" Você já conhece essa pessoa de antes: {conhecida}. "
                     f"Ela está voltando, não é a primeira vez.")
        instrucao = ("Cumprimente como quem reconhece alguém que voltou. "
                     "Pode puxar algo do que você sabe, se encaixar.")
    else:
        instrucao = ("Você não conhece essa pessoa. Cumprimente curto e sem "
                     "formalidade, como alguém que já estava na sala quando o "
                     "novato chegou. Não liste regras nem explique o servidor.")

    _falar(situacao, canal, instrucao)


def saiu(member) -> None:
    """
    Alguém saiu. Só comenta se ela conhecia a pessoa.

    Comentar a saída de qualquer um seria ruim de duas formas: vira ruído quando
    é alguém que entrou e saiu sem falar, e vira constrangimento quando a pessoa
    foi expulsa. Exigir que ela conhecesse resolve os dois — e "conhecer" aqui
    significa ter conversado de verdade, o que o perfil já mede.
    """
    if not ATIVO or getattr(member, "bot", False):
        return
    canal = _canal_de_avisos()
    if not canal:
        return

    try:
        import perfil_discord
        ficha = perfil_discord._ficha(getattr(member, "id", 0))
    except Exception:
        ficha = None
    if not ficha or ficha.get("interacoes", 0) < MIN_INTERACOES_PRA_SENTIR_FALTA:
        return

    nome = ficha.get("nome") or getattr(member, "display_name", "alguém")
    fatos = "; ".join(ficha.get("fatos", [])[:2])
    situacao = (f"{nome} saiu do servidor. Vocês conversavam bastante "
                f"({ficha.get('interacoes')} vezes).")
    if fatos:
        situacao += f" O que você sabia dessa pessoa: {fatos}."
    _falar(situacao, canal,
           "Comente curto, sem drama e sem despedida formal.")


def _o_que_sei(user_id: int) -> str:
    try:
        import perfil_discord
        fatos = perfil_discord.fatos_de(user_id)
        return "; ".join(fatos[:3])
    except Exception:
        return ""


# ═════════════════════════════════════════════════════════════════
# AÇÕES DA AGENDA
# ═════════════════════════════════════════════════════════════════

def acao_lembrete(tarefa: dict) -> str:
    """
    O lembrete que alguém pediu. Não passa por LLM.

    De propósito: quem pede "me lembra às 8 de reiniciar o server" quer OUVIR
    aquilo, não uma paráfrase criativa. Gerar o texto de novo abriria espaço pra
    ela mudar o conteúdo do próprio recado, que é o único caso aqui em que
    criatividade é defeito.
    """
    dados = tarefa.get("dados", {}) or {}
    texto = (dados.get("texto") or "").strip()
    if not texto:
        return "lembrete sem texto"
    canal = int(tarefa.get("canal_id") or 0) or _canal_de_avisos()
    quem_id = dados.get("quem_id")
    prefixo = f"<@{quem_id}> " if quem_id else ""
    falar_no_canal(canal, f"{prefixo}{texto}")
    _contar_fala()
    return f"lembrete entregue: {texto[:60]}"


def acao_recado(tarefa: dict) -> str:
    """Ela comenta um assunto com as próprias palavras, na hora marcada."""
    dados = tarefa.get("dados", {}) or {}
    assunto = (dados.get("assunto") or "").strip()
    if not assunto:
        return "recado sem assunto"
    canal = int(tarefa.get("canal_id") or 0) or _canal_de_avisos()
    _falar(f"Está na hora de você comentar isso no servidor: {assunto}", canal)
    return f"recado: {assunto[:60]}"


def acao_ausencia(tarefa: dict) -> str:
    """
    Varre quem sumiu e comenta sobre UMA pessoa, no máximo.

    Uma só, e não todas as que sumiram: uma lista de ausentes é relatório, e
    relatório é exatamente o que ela não deve parecer. Escolhe a de mais
    interação — a que faz mais sentido sentir falta.
    """
    if not ATIVO:
        return "desligado"
    canal = _canal_de_avisos()
    if not canal:
        return "sem canal de avisos"

    candidatas = quem_sumiu()
    if not candidatas:
        return "ninguém sumiu"

    ficha = candidatas[0]
    uid = str(ficha.get("_id"))
    with _lock:
        dados = carregar()
        dados["ausencia_comentada"][uid] = time.time()
        salvar()

    dias = int((time.time() - ficha.get("visto_em", 0)) / 86400)
    fatos = "; ".join(ficha.get("fatos", [])[:2])
    situacao = (f"{ficha.get('nome')} não aparece no servidor há {dias} dias. "
                f"Vocês conversavam bastante ({ficha.get('interacoes')} vezes).")
    if fatos:
        situacao += f" O que você sabe dessa pessoa: {fatos}."

    _falar(situacao, canal,
           "Comente que faz tempo que não vê essa pessoa. Curto, do seu jeito, "
           "sem parecer cobrança.")
    return f"comentei a ausência de {ficha.get('nome')}"


def quem_sumiu() -> List[dict]:
    """
    Quem conversava com ela e parou de aparecer, da mais próxima pra menos.

    Pública porque também é resposta de ferramenta: dá pra perguntar a ela quem
    andou sumido, sem esperar a varredura do dia.
    """
    try:
        import perfil_discord
        membros = perfil_discord.carregar()["membros"]
    except Exception as e:
        _log(f"perfil indisponível: {e}")
        return []

    agora = time.time()
    dados = carregar()
    saida = []
    for chave, ficha in membros.items():
        interacoes = ficha.get("interacoes", 0)
        if interacoes < MIN_INTERACOES_PRA_SENTIR_FALTA:
            continue
        visto = float(ficha.get("visto_em") or 0)
        if not visto or (agora - visto) < DIAS_PRA_SUMIR * 86400:
            continue
        ultima = float(dados["ausencia_comentada"].get(chave, 0))
        if agora - ultima < DIAS_ENTRE_COMENTARIOS_DA_MESMA * 86400:
            continue
        copia = dict(ficha)
        copia["_id"] = chave
        saida.append(copia)

    saida.sort(key=lambda f: -f.get("interacoes", 0))
    return saida


def acao_marcos(tarefa: dict) -> str:
    """
    Marcos de conversa. Um por dia, no máximo.

    Só marcos de CONVERSA (50, 100, 250... interações), e não aniversário de
    entrada no servidor. Aniversário exigiria ler `joined_at` de todo mundo a
    cada dia, e o que ele mede é tempo de cadastro — que não quer dizer nada
    sobre a relação. Cem conversas com ela quer dizer algo.
    """
    if not ATIVO:
        return "desligado"
    canal = _canal_de_avisos()
    if not canal:
        return "sem canal de avisos"

    try:
        import perfil_discord
        membros = perfil_discord.carregar()["membros"]
    except Exception:
        return "perfil indisponível"

    dados = carregar()
    for chave, ficha in sorted(membros.items(),
                               key=lambda p: -p[1].get("interacoes", 0)):
        interacoes = ficha.get("interacoes", 0)
        alcancado = None
        for marco in MARCOS_DE_CONVERSA:
            if interacoes >= marco:
                alcancado = marco
        if not alcancado:
            continue
        selo = f"{chave}:{alcancado}"
        if selo in dados["marcos_dados"]:
            continue

        with _lock:
            dados["marcos_dados"][selo] = time.time()
            salvar()

        situacao = (f"{ficha.get('nome')} já conversou com você "
                    f"{alcancado} vezes neste servidor.")
        _falar(situacao, canal,
               "Comente isso de leve, como quem se deu conta agora. Sem "
               "cerimônia e sem parecer conquista de jogo.")
        return f"marco de {alcancado} pra {ficha.get('nome')}"

    return "nenhum marco novo"


# ═════════════════════════════════════════════════════════════════
# LIGAR
# ═════════════════════════════════════════════════════════════════

def ligar() -> None:
    """
    Registra as ações na agenda e marca as rotinas.

    As rotinas usam `chave`, então rodar isto a cada boot substitui em vez de
    duplicar. Sem a chave, cada reinício somaria mais uma varredura diária e em
    uma semana ela estaria comentando ausência seis vezes por dia.
    """
    if not ATIVO:
        _log("desligado por configuração (EMILY_VIDA_DISCORD=0)")
        return
    try:
        import agenda
    except Exception as e:
        _log(f"agenda indisponível: {e}")
        return

    agenda.registrar_acao("lembrete", acao_lembrete)
    agenda.registrar_acao("recado", acao_recado)
    agenda.registrar_acao("ausencia", acao_ausencia)
    agenda.registrar_acao("marcos", acao_marcos)

    # Horários espalhados de propósito: se as três rodassem juntas, ela poderia
    # mandar três mensagens no mesmo minuto e pareceria um robô acordando.
    for chave, acao, horario in (
        ("rotina:ausencia", "ausencia", os.getenv("EMILY_VIDA_HORA_AUSENCIA", "19:30")),
        ("rotina:marcos", "marcos", os.getenv("EMILY_VIDA_HORA_MARCOS", "21:10")),
    ):
        try:
            agenda.criar(acao=acao, tipo="diario", horario=horario,
                         chave=chave, visivel=False,
                         criado_por="rotina interna")
        except Exception as e:
            _log(f"não consegui marcar {chave}: {e}")

    _log("iniciativa social ligada")


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
# ═════════════════════════════════════════════════════════════════

def _diagnosticar() -> int:
    print("=" * 66)
    print("  INICIATIVA SOCIAL DA EMILY")
    print("=" * 66)
    print(f"  ativo:            {ATIVO}")
    print(f"  arquivo:          {ARQUIVO} (existe: {os.path.exists(ARQUIVO)})")
    print(f"  teto por dia:     {MAX_FALAS_POR_DIA}")
    print(f"  dias pra sumir:   {DIAS_PRA_SUMIR}")
    print(f"  interações mín:   {MIN_INTERACOES_PRA_SENTIR_FALTA}")
    print(f"  bot conectado:    {_pronto()}")
    print(f"  canal de avisos:  {_canal_de_avisos() or '(não configurado)'}")
    print(f"  canal boas-vindas:{_canal_de_boas_vindas() or '(não configurado)'}")

    dados = carregar()
    print(f"\n  falas hoje:       {dados['falas_do_dia'].get(_hoje(), 0)}"
          f"/{MAX_FALAS_POR_DIA}")
    print(f"  ausências já comentadas: {len(dados['ausencia_comentada'])}")
    print(f"  marcos já dados:  {len(dados['marcos_dados'])}")

    print("\n-- quem sumiu (candidatos a comentário) --")
    sumidos = quem_sumiu()
    if not sumidos:
        print("  (ninguém, ou o perfil ainda não tem gente com interação "
              "suficiente)")
    for f in sumidos[:8]:
        dias = int((time.time() - f.get("visto_em", 0)) / 86400)
        print(f"  {f.get('nome', '?'):24} {f.get('interacoes', 0):4} interações"
              f"  visto há {dias} dias")

    print("\n-- amostra do perfil (pra saber se há base) --")
    try:
        import perfil_discord
        membros = perfil_discord.carregar()["membros"]
        print(f"  {len(membros)} pessoas conhecidas")
        top = sorted(membros.values(), key=lambda f: -f.get("interacoes", 0))[:5]
        for f in top:
            visto = time.strftime("%d/%m", time.localtime(f.get("visto_em", 0)))
            print(f"  {f.get('nome', '?'):24} {f.get('interacoes', 0):4} "
                  f"interações  visto {visto}")
    except Exception as e:
        print(f"  perfil indisponível: {e}")

    print("\n" + "=" * 66)
    print("Nada foi enviado: o diagnóstico só lê.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnosticar())

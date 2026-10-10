"""
livro_regras.py — a Emily editando as regras a pedido de quem manda.

O PEDIDO
────────
"Emily, muda a parte do PvP: agora vale nos dois packs." Ela edita o arquivo,
republica os painéis no Discord, e a partir dali julga pela regra nova.

Regra muda com frequência, e o caminho antigo (abrir o markdown, editar, pedir
pra ela republicar) tem três passos a mais do que precisa.

AS TRÊS COISAS QUE ESTE ARQUIVO PROTEGE
───────────────────────────────────────
1. QUEM PODE. Só dono e co-admin. Não é excesso de zelo: quem controla as regras
   controla o que é permitido no servidor. Um cargo de confiança que possa
   reescrever a regra de banimento pode se tornar intocável escrevendo isso na
   regra. Nível de cargo não basta aqui — tem que ser ID.

2. EDIÇÃO CIRÚRGICA, NUNCA REESCRITA. A ferramenta troca UMA seção por vez,
   mexendo nas linhas daquele bloco e em nada mais.

   O caminho fácil seria "reescreve o arquivo com este conteúdo" e deixar o
   modelo produzir o texto inteiro. É uma armadilha: modelo reescrevendo mil
   linhas omite seções sem perceber, e o resultado seria perder metade das regras
   num pedido pra corrigir uma frase. Aqui ele não tem como: só recebe e devolve
   o bloco que está editando.

3. DESFAZER SEMPRE. Toda alteração salva o arquivo anterior em backup antes de
   tocar em nada. Regra estragada é o pior estado possível do servidor — pior que
   regra desatualizada — porque a Emily passa a julgar por ela.

O QUE ELA PODE MEXER
────────────────────
Seção (`##`) e parte (`###`). Isso importa porque o pedido real quase nunca é
sobre a seção inteira: "muda a parte do PvP" fala de um `###` dentro de "No
servidor de Minecraft". Sem suportar os dois, ela teria que reescrever a seção
toda pra corrigir três palavras.
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
import time
from typing import List, Optional, Tuple
from emily_paths import arquivo_dados

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PASTA_BACKUP = str(arquivo_dados("backups_regras"))

# Quantos backups guardar. Vinte cobre uma sessão inteira de ajustes com folga.
MAX_BACKUPS = 20

# Semelhança mínima pra aceitar um nome de seção aproximado.
#
# Alto de propósito: errar a seção e sobrescrever a errada é o pior resultado
# possível aqui. Na dúvida, ela lista as opções e pergunta.
SEMELHANCA_MINIMA = 0.62


def _log(msg: str) -> None:
    print(f"[REGRAS] {msg}")


def _caminho() -> str:
    import suporte
    return suporte.ARQUIVO_REGRAS


# ═════════════════════════════════════════════════════════════════
# PERMISSÃO
# ═════════════════════════════════════════════════════════════════

def quem_pode_mexer() -> Tuple[bool, str]:
    """
    (pode, motivo da recusa). Só dono e co-admin.

    O caminho local (Vitor falando com ela na máquina dele) também passa: ali não
    existe intermediário nenhum entre a pessoa e o arquivo — se ele quisesse,
    editaria o markdown direto.
    """
    try:
        import discord_admin
    except Exception:
        return True, ""   # sem Discord, é o caminho local

    sessao = discord_admin.sessao()
    nivel = sessao.get("nivel")
    if sessao.get("origem") != "discord":
        return True, ""
    if nivel in (discord_admin.NIVEL_DONO, discord_admin.NIVEL_COADMIN):
        return True, ""
    return False, (
        "Mexer nas regras é só o Vitor ou o Comuna. Diga isso a quem pediu, no "
        "seu jeito, sem soar como aviso de sistema. Se a pessoa tem uma sugestão "
        "boa de regra, ofereça levar pro Vitor."
    )


# ═════════════════════════════════════════════════════════════════
# BACKUP
# ═════════════════════════════════════════════════════════════════

def _guardar_backup() -> str:
    """Copia o arquivo atual. Devolve o caminho, ou "" se não deu."""
    origem = _caminho()
    if not os.path.exists(origem):
        return ""
    try:
        os.makedirs(PASTA_BACKUP, exist_ok=True)
        nome = f"regras_{time.strftime('%Y%m%d_%H%M%S')}.md"
        destino = os.path.join(PASTA_BACKUP, nome)
        shutil.copy2(origem, destino)
    except OSError as e:
        _log(f"não consegui fazer backup: {e}")
        return ""

    # Poda: guardar backup pra sempre encheria a pasta sem utilidade nenhuma.
    try:
        todos = sorted(f for f in os.listdir(PASTA_BACKUP)
                       if f.startswith("regras_") and f.endswith(".md"))
        for velho in todos[:-MAX_BACKUPS]:
            os.remove(os.path.join(PASTA_BACKUP, velho))
    except OSError:
        pass
    return destino


def backups() -> List[str]:
    """Os backups, do mais novo pro mais velho."""
    if not os.path.isdir(PASTA_BACKUP):
        return []
    try:
        todos = [f for f in os.listdir(PASTA_BACKUP)
                 if f.startswith("regras_") and f.endswith(".md")]
    except OSError:
        return []
    return sorted(todos, reverse=True)


def desfazer() -> str:
    """Volta pro backup mais recente."""
    lista = backups()
    if not lista:
        return "Não tenho backup nenhum das regras pra voltar."
    alvo = os.path.join(PASTA_BACKUP, lista[0])
    try:
        # Guarda o estado atual ANTES de restaurar: sem isso, desfazer duas vezes
        # perderia a versão do meio e não haveria como voltar pro que estava.
        _guardar_backup()
        shutil.copy2(alvo, _caminho())
    except OSError as e:
        return f"Não consegui voltar o backup: {e}"
    _invalidar()
    quando = lista[0].replace("regras_", "").replace(".md", "")
    return f"Voltei as regras pra versão de {_bonito(quando)}."


def _bonito(marca: str) -> str:
    try:
        t = time.strptime(marca, "%Y%m%d_%H%M%S")
        return time.strftime("%d/%m às %H:%M", t)
    except ValueError:
        return marca


def _invalidar() -> None:
    """Força a Emily a reler as regras na próxima vez."""
    try:
        import suporte
        suporte._cache_regras = None
        suporte._regras_mtime = 0.0
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════
# ACHAR O BLOCO
#
# Um "bloco" é o cabeçalho e tudo que vem até o próximo cabeçalho de nível igual
# ou maior. É isso que permite editar sem tocar no resto do arquivo.
# ═════════════════════════════════════════════════════════════════

_RE_CABECALHO = re.compile(r"^(#{2,3})\s+(.+?)\s*$")


def _cabecalhos(linhas: List[str]) -> List[dict]:
    """Todos os `##` e `###` do arquivo, com onde cada bloco começa e acaba."""
    achados = []
    for i, linha in enumerate(linhas):
        m = _RE_CABECALHO.match(linha)
        if m:
            achados.append({"nivel": len(m.group(1)), "titulo": m.group(2),
                            "inicio": i, "fim": len(linhas)})

    for j, cab in enumerate(achados):
        for seguinte in achados[j + 1:]:
            if seguinte["nivel"] <= cab["nivel"]:
                fim = seguinte["inicio"]
                # Recua sobre o que já pertence ao PRÓXIMO cabeçalho: linha em
                # branco e, principalmente, a marca `<!-- canal: x -->`.
                #
                # Sem este recuo o bloco de uma seção terminava engolindo a marca
                # de canal da seguinte, e editar a seção de cima APAGAVA essa
                # marca. A seção de baixo então herdava o canal da anterior e
                # passava a ser publicada no lugar errado — sem erro nenhum, só
                # regra aparecendo no canal de guia.
                while fim > cab["inicio"] + 1:
                    anterior = linhas[fim - 1].strip()
                    if anterior and not anterior.startswith("<!--"):
                        break
                    fim -= 1
                cab["fim"] = fim
                break
    return achados


def _normalizar(texto: str) -> str:
    baixo = (texto or "").strip().lower()
    for de, para in (("á", "a"), ("ã", "a"), ("â", "a"), ("é", "e"), ("ê", "e"),
                     ("í", "i"), ("ó", "o"), ("õ", "o"), ("ô", "o"), ("ú", "u"),
                     ("ç", "c")):
        baixo = baixo.replace(de, para)
    return re.sub(r"[^a-z0-9 ]", "", baixo).strip()


def achar(alvo: str, linhas: Optional[List[str]] = None) -> Optional[dict]:
    """
    Acha a seção ou parte pelo nome, tolerando aproximação.

    Exato primeiro, depois "contém", depois semelhança. A ordem importa: com dois
    títulos parecidos, o exato tem que ganhar do aproximado — senão pedir pra
    editar "No Discord" poderia acertar "No servidor de Minecraft".
    """
    if linhas is None:
        linhas = _ler_linhas()
    cabs = _cabecalhos(linhas)
    if not cabs:
        return None

    procurado = _normalizar(alvo)
    if not procurado:
        return None

    for cab in cabs:
        if _normalizar(cab["titulo"]) == procurado:
            return cab
    for cab in cabs:
        titulo = _normalizar(cab["titulo"])
        if procurado in titulo or titulo in procurado:
            return cab

    melhor, nota_melhor = None, 0.0
    for cab in cabs:
        nota = difflib.SequenceMatcher(
            None, procurado, _normalizar(cab["titulo"])).ratio()
        if nota > nota_melhor:
            melhor, nota_melhor = cab, nota
    return melhor if nota_melhor >= SEMELHANCA_MINIMA else None


def listar() -> str:
    """As seções e partes que existem, pra ela responder quando não achar."""
    linhas = _ler_linhas()
    if not linhas:
        return "O arquivo de regras está vazio."
    saida = []
    for cab in _cabecalhos(linhas):
        prefixo = "  " if cab["nivel"] == 3 else ""
        saida.append(f"{prefixo}- {cab['titulo']}")
    return "\n".join(saida)


def _ler_linhas() -> List[str]:
    try:
        with open(_caminho(), "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except OSError:
        return []


def _gravar_linhas(linhas: List[str]) -> bool:
    try:
        tmp = _caminho() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(linhas).rstrip() + "\n")
        os.replace(tmp, _caminho())
        return True
    except OSError as e:
        _log(f"não consegui gravar: {e}")
        return False


def _texto_do_bloco(linhas: List[str], cab: dict) -> str:
    return "\n".join(linhas[cab["inicio"]:cab["fim"]]).strip()


# ═════════════════════════════════════════════════════════════════
# AS OPERAÇÕES
# ═════════════════════════════════════════════════════════════════

def editar(alvo: str, novo_texto: str) -> str:
    """
    Troca o corpo de uma seção ou parte, mantendo o cabeçalho.

    O cabeçalho é preservado de propósito: se o modelo pudesse trocá-lo junto, um
    pedido de "ajusta o texto do PvP" poderia renomear a parte sem ninguém pedir —
    e aí a próxima edição não acharia mais ela pelo nome antigo. Renomear tem
    operação própria.
    """
    pode, recusa = quem_pode_mexer()
    if not pode:
        return recusa

    novo_texto = (novo_texto or "").strip()
    if not novo_texto:
        return "Preciso do texto novo. Pra apagar a seção, use a ação remover."

    linhas = _ler_linhas()
    cab = achar(alvo, linhas)
    if cab is None:
        return (f"Não achei '{alvo}' nas regras. O que existe:\n{listar()}\n"
                f"Pergunte qual é, sem chutar.")

    antes = _texto_do_bloco(linhas, cab)
    cabecalho = linhas[cab["inicio"]]
    corpo = [l for l in novo_texto.splitlines()]

    backup = _guardar_backup()
    novas = linhas[:cab["inicio"]] + [cabecalho, ""] + corpo + [""] \
        + linhas[cab["fim"]:]
    if not _gravar_linhas(novas):
        return "Não consegui gravar o arquivo de regras."
    _invalidar()

    _log(f"editei '{cab['titulo']}' (backup: {os.path.basename(backup)})")
    return _relatar(f"Reescrevi '{cab['titulo']}'", antes,
                    _texto_do_bloco(_ler_linhas(), achar(cab["titulo"]) or cab))


def adicionar(titulo: str, texto: str, canal: str = "regras",
              depois_de: str = "") -> str:
    """Cria uma seção nova, com a marca de canal certa."""
    pode, recusa = quem_pode_mexer()
    if not pode:
        return recusa

    titulo = (titulo or "").strip()
    texto = (texto or "").strip()
    if not titulo or not texto:
        return "Preciso do título e do texto da regra nova."

    canal = (canal or "regras").strip().lower()
    if canal not in ("regras", "guia", "nenhum"):
        return ("O canal tem que ser 'regras' (o que dá problema), 'guia' (como "
                "usar o servidor) ou 'nenhum' (você sabe mas não publica).")

    linhas = _ler_linhas()
    if achar(titulo, linhas) is not None:
        return (f"Já existe uma seção parecida com '{titulo}'. Pra mudar o texto "
                f"dela, use a ação editar.")

    bloco = ["", f"<!-- canal: {canal} -->", "", f"## {titulo}", ""]
    bloco += texto.splitlines()
    bloco.append("")

    onde = len(linhas)
    if depois_de:
        cab = achar(depois_de, linhas)
        if cab is None:
            return (f"Não achei '{depois_de}' pra colocar depois. O que "
                    f"existe:\n{listar()}")
        onde = cab["fim"]

    backup = _guardar_backup()
    novas = linhas[:onde] + bloco + linhas[onde:]
    if not _gravar_linhas(novas):
        return "Não consegui gravar o arquivo de regras."
    _invalidar()

    _log(f"adicionei '{titulo}' em {canal} (backup: {os.path.basename(backup)})")
    return (f"Criei a seção '{titulo}' no {canal}. "
            f"Publique pra aparecer no Discord.")


def remover(alvo: str) -> str:
    """Apaga uma seção ou parte inteira."""
    pode, recusa = quem_pode_mexer()
    if not pode:
        return recusa

    linhas = _ler_linhas()
    cab = achar(alvo, linhas)
    if cab is None:
        return f"Não achei '{alvo}' nas regras. O que existe:\n{listar()}"

    texto = _texto_do_bloco(linhas, cab)
    inicio = cab["inicio"]
    # Leva a marca de canal junto, quando ela é logo acima: deixar órfã faria a
    # próxima seção herdar o canal errado silenciosamente.
    if cab["nivel"] == 2:
        for i in range(inicio - 1, max(-1, inicio - 4), -1):
            if i >= 0 and re.match(r"^\s*<!--\s*canal:", linhas[i]):
                inicio = i
                break

    backup = _guardar_backup()
    novas = linhas[:inicio] + linhas[cab["fim"]:]
    if not _gravar_linhas(novas):
        return "Não consegui gravar o arquivo de regras."
    _invalidar()

    _log(f"removi '{cab['titulo']}' (backup: {os.path.basename(backup)})")
    return (f"Tirei '{cab['titulo']}' das regras. Era isto:\n"
            f"```\n{texto[:600]}\n```\n"
            f"Se foi engano, dá pra desfazer. Publique pra atualizar o Discord.")


def renomear(alvo: str, novo_titulo: str) -> str:
    pode, recusa = quem_pode_mexer()
    if not pode:
        return recusa

    novo_titulo = (novo_titulo or "").strip()
    if not novo_titulo:
        return "Preciso do título novo."

    linhas = _ler_linhas()
    cab = achar(alvo, linhas)
    if cab is None:
        return f"Não achei '{alvo}' nas regras. O que existe:\n{listar()}"

    backup = _guardar_backup()
    linhas[cab["inicio"]] = ("#" * cab["nivel"]) + " " + novo_titulo
    if not _gravar_linhas(linhas):
        return "Não consegui gravar o arquivo de regras."
    _invalidar()
    _log(f"renomeei '{cab['titulo']}' pra '{novo_titulo}' "
         f"(backup: {os.path.basename(backup)})")
    return f"Renomeei '{cab['titulo']}' pra '{novo_titulo}'."


def ver(alvo: str) -> str:
    """Mostra o texto atual de uma seção. Serve pra ela editar sabendo o que tem."""
    linhas = _ler_linhas()
    cab = achar(alvo, linhas)
    if cab is None:
        return f"Não achei '{alvo}'. O que existe:\n{listar()}"
    return _texto_do_bloco(linhas, cab)


def _relatar(titulo: str, antes: str, depois: str) -> str:
    """
    Conta o que mudou, mostrando as linhas que entraram e saíram.

    O diff vai pro contexto dela, não pro chat: é o que permite ela dizer "tirei a
    parte do PvP no pack magia" em vez de "atualizei as regras". Resposta genérica
    esconde erro — se ela editou a seção errada, o diff é o que faz isso aparecer
    na hora.
    """
    saiu, entrou = [], []
    for linha in difflib.unified_diff(antes.splitlines(), depois.splitlines(),
                                      lineterm="", n=0):
        if linha.startswith("+") and not linha.startswith("+++"):
            entrou.append(linha[1:].strip())
        elif linha.startswith("-") and not linha.startswith("---"):
            saiu.append(linha[1:].strip())

    partes = [titulo + "."]
    if saiu:
        partes.append("Saiu: " + " | ".join(l for l in saiu[:6] if l))
    if entrou:
        partes.append("Entrou: " + " | ".join(l for l in entrou[:6] if l))
    partes.append("Conte o que mudou no seu jeito, curto. Dá pra desfazer se "
                  "ficou errado.")
    return "\n".join(partes)


# ═════════════════════════════════════════════════════════════════
# O CAMINHO COMPLETO: MUDAR E JÁ PUBLICAR
# ═════════════════════════════════════════════════════════════════

def mudar(acao: str, alvo: str = "", texto: str = "", canal: str = "regras",
          depois_de: str = "", publicar: bool = True,
          servidor: str = "") -> str:
    """
    Ponto de entrada da ferramenta.

    Publica junto por padrão, e é o ponto do pedido: arquivo e canal
    dessincronizados são o pior resultado, porque a Emily passaria a julgar por
    uma regra que a galera não vê escrita em lugar nenhum.
    """
    acao = (acao or "").strip().lower()

    if acao in ("ver", "mostrar"):
        return ver(alvo) if alvo else listar()
    if acao in ("listar", "lista"):
        return listar()
    if acao in ("desfazer", "voltar"):
        pode, recusa = quem_pode_mexer()
        if not pode:
            return recusa
        resultado = desfazer()
        if publicar and "Voltei" in resultado:
            resultado += "\n" + _republicar(servidor)
        return resultado
    if acao in ("backups", "versoes"):
        lista = backups()
        if not lista:
            return "Não tenho backup nenhum ainda."
        return ("Versões guardadas: "
                + ", ".join(_bonito(f.replace("regras_", "").replace(".md", ""))
                            for f in lista[:8]))

    if acao in ("editar", "mudar", "trocar"):
        resultado = editar(alvo, texto)
    elif acao in ("adicionar", "criar", "nova"):
        resultado = adicionar(alvo, texto, canal, depois_de)
    elif acao in ("remover", "apagar", "tirar"):
        resultado = remover(alvo)
    elif acao in ("renomear",):
        resultado = renomear(alvo, texto)
    else:
        return (f"Não conheço a ação '{acao}'. Use: ver, listar, editar, "
                f"adicionar, remover, renomear, desfazer ou backups.")

    # Só republica se a operação deu certo. As recusas começam com texto que não
    # é confirmação, e republicar depois de uma recusa mandaria pro Discord uma
    # versão que ninguém pediu.
    if publicar and not _foi_recusa(resultado):
        resultado += "\n" + _republicar(servidor)
    return resultado


def _foi_recusa(resultado: str) -> bool:
    marcas = ("Não achei", "Preciso do", "Já existe", "Não consegui",
              "só o Vitor", "O canal tem que ser", "Não conheço",
              "Não tenho backup")
    return any(m in resultado for m in marcas)


def _republicar(servidor: str = "") -> str:
    """Reflete a mudança nos canais, se já houver publicação feita."""
    try:
        import publicar_discord
        feitas = publicar_discord._carregar()
        if not feitas:
            return ("As regras ainda não foram publicadas em canal nenhum, então "
                    "só mudei o arquivo. Peça pra publicar quando quiser.")
        return publicar_discord.publicar_livro(servidor=servidor)
    except Exception as e:
        return (f"Mudei o arquivo, mas não consegui atualizar o Discord "
                f"({type(e).__name__}: {e}). Os dois estão diferentes agora — "
                f"avise isso.")


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
# ═════════════════════════════════════════════════════════════════

def _diagnosticar() -> int:
    print("=" * 66)
    print("  EDIÇÃO DAS REGRAS PELA EMILY")
    print("=" * 66)
    print(f"  arquivo:  {_caminho()}")
    print(f"  existe:   {os.path.exists(_caminho())}")
    print(f"  backups:  {len(backups())} (teto {MAX_BACKUPS}) em {PASTA_BACKUP}")

    pode, recusa = quem_pode_mexer()
    print(f"  pode mexer daqui: {pode} {('— ' + recusa[:40]) if recusa else ''}")

    print("\n-- seções e partes que existem --")
    print("  " + listar().replace("\n", "\n  "))

    print("\n-- busca por nome aproximado --")
    casos = ["PvP", "pvp", "convivencia", "Convivência", "no discord",
             "poder op", "quanto de ram", "a emily", "grief",
             "seção que não existe"]
    for c in casos:
        cab = achar(c)
        if cab:
            print(f"  {c!r:24} -> [{'#' * cab['nivel']}] {cab['titulo']}")
        else:
            print(f"  {c!r:24} -> não achou (ela pergunta)")

    print("\n-- limites do bloco (o que seria substituído) --")
    for nome in ("PvP", "Quanto de RAM"):
        cab = achar(nome)
        if cab:
            texto = ver(nome)
            print(f"  {nome}: linhas {cab['inicio']}..{cab['fim']}, "
                  f"{len(texto)} chars")
            primeira = texto.splitlines()[0] if texto else ""
            ultima = texto.splitlines()[-1] if texto else ""
            print(f"    começa: {primeira[:56]}")
            print(f"    acaba:  {ultima[:56]}")

    print("\n" + "=" * 66)
    print("Nada foi alterado: o diagnóstico só lê.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnosticar())

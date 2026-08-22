"""Roda os testes e escreve o veredito num arquivo, sem passar pelo PowerShell.

O shell deste ambiente corrompe redirecionamento em comando longo e às vezes
cruza terminais. Python escrevendo o arquivo direto elimina as duas coisas.
"""
import os
import subprocess
import sys
import tempfile

# Teto por teste. Sem isto um teste pendurado trava a suíte inteira sem dizer
# nada, que foi o que aconteceu: o teste de vazamento sobe o gateway como
# processo filho, os netos dele herdam o pipe de captura, e o subprocess ficava
# esperando EOF de um pipe que ninguém mais ia fechar — mais de uma hora sem
# saída nenhuma.
TIMEOUT_POR_TESTE = float(os.getenv("EMILY_TIMEOUT_TESTE", "1800"))

TESTES = [
    "_teste_call_ligacao.py",
    "_teste_call_consertos.py",
    "_teste_call_transcricao.py",
    "_teste_call_silencio.py",
    "_teste_call_recepcao.py",
    "_teste_modpacks.py",
    "_teste_curadoria.py",
    "_teste_locais.py",
    "_teste_vazamento_tool.py",
    "_teste_montar_pack.py",
    "_teste_conversas.py",
    "_teste_interface_chat.py",
]

ARQUIVO_VEREDITO = "VEREDITO.txt"

linhas = []
ruins = 0


def _gravar():
    """
    Reescreve o veredito a cada teste, em vez de só no fim.

    A suíte inteira leva quase uma hora. Sem isto, quem está acompanhando não
    tem como saber se está andando ou pendurado — e foi exatamente essa dúvida
    que custou mais de uma hora de espera cega.
    """
    try:
        with open(ARQUIVO_VEREDITO, "w", encoding="utf-8") as f:
            f.write("\n".join(linhas) + "\n")
    except OSError as e:
        print(f"[rodar] não gravei o veredito: {e}")


def _rodar_um(teste):
    """
    (codigo, saida) — captura em ARQUIVO, não em pipe.

    Arquivo e não pipe porque teste que sobe subprocesso (o gateway) faz os
    netos herdarem o pipe; aí o pai já morreu e a leitura continua bloqueada
    esperando um EOF que não vem. Com arquivo, o fim do processo é o fim da
    espera, e ninguém depende de quem mais está com o descritor aberto.
    """
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False,
                                     encoding="utf-8", errors="replace") as f:
        caminho = f.name
    try:
        with open(caminho, "w", encoding="utf-8", errors="replace") as saida_f:
            proc = subprocess.run(
                [sys.executable, "-u", teste],
                stdout=saida_f, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                timeout=TIMEOUT_POR_TESTE,
            )
        codigo = proc.returncode
    except subprocess.TimeoutExpired:
        codigo = -9
    try:
        with open(caminho, encoding="utf-8", errors="replace") as saida_f:
            texto_saida = saida_f.read()
    except OSError:
        texto_saida = ""
    try:
        os.unlink(caminho)
    except OSError:
        pass
    return codigo, texto_saida


for teste in TESTES:
    linhas.append(f"{teste:32s} rodando...")
    _gravar()
    linhas.pop()
    codigo, saida = _rodar_um(teste)
    falhas = [l.strip() for l in saida.splitlines()
              if l.strip().startswith("FALHA")]
    if codigo == -9:
        veredito = f"PENDUROU (passou de {TIMEOUT_POR_TESTE:.0f}s)"
    else:
        veredito = "OK" if codigo == 0 else f"FALHOU (codigo {codigo})"
    linhas.append(f"{teste:32s} {veredito}")
    if codigo != 0:
        ruins += 1
        for f in falhas[:12]:
            linhas.append(f"    {f}")
        if not falhas:
            linhas.append("    (sem linha de FALHA; ultimas linhas da saida:)")
            for l in saida.strip().splitlines()[-8:]:
                linhas.append(f"    | {l[:150]}")
    _gravar()

linhas.append("")
linhas.append(f"{len(TESTES) - ruins} de {len(TESTES)} passaram.")
_gravar()

# Quantas ferramentas o catálogo tem, pra conferir que nada deixou de carregar.
r = subprocess.run(
    [sys.executable, "-c",
     "import ferramentas as f; "
     "print('ferramentas no catalogo:', len(f.CATALOGO)); "
     "print('no grupo servidor:', len(f.nomes_do_grupo('servidor'))); "
     "print('no grupo discord:', len(f.nomes_do_grupo('discord')))"],
    capture_output=True, text=True, encoding="utf-8", errors="replace")
linhas.append("")
linhas.append((r.stdout or r.stderr or "").strip())

_gravar()
print("\n".join(linhas))
sys.exit(1 if ruins else 0)

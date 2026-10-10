"""Confere a persona da DM: discord de verdade, sem a base formal do PC."""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
from dotenv import load_dotenv
load_dotenv()
import modelo  # noqa: E402

p_dono = modelo._sistema_dm(
    "hiucksam", eh_dono=True, historico_txt="Emily (você): fala",
    id_confirmado=1195765414400106626)
p_outro = modelo._sistema_dm("Ryan", eh_dono=False)

checks = [
    ("dono: persona discord (vc/pq)", "vc" in p_dono and "pq" in p_dono),
    ("dono: CONFIRMADO PELO ID + id visível",
     "CONFIRMADO PELO ID" in p_dono and "1195765414400106626" in p_dono),
    ("dono: nome de exibição no prompt", "hiucksam" in p_dono),
    ("dono: ambiente na mesa (ferramentas de PC)", "<ambiente>" in p_dono),
    ("dono: SEM bloco markdown do PC", "formatacao_do_chat" not in p_dono),
    ("outro: persona discord", "vc" in p_outro and "jeito_de_falar_discord" in p_outro),
    ("outro: SEM ambiente", "<ambiente>" not in p_outro),
    ("outro: confidencialidade", "CONFIDENCIAIS" in p_outro),
    ("outro: ferramentas só simples", "pesquisar na internet e ver a hora" in p_outro),
    ("ambos: sem persona base markdown",
     all("formatacao_do_chat" not in p for p in (p_dono, p_outro))),
]

ok = True
for nome, passou in checks:
    print(("OK      " if passou else "FALHOU  ") + nome)
    ok = ok and passou
print("RESULTADO:", "TUDO OK" if ok else "TEM PROBLEMA")

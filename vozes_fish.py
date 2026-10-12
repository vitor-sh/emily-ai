"""Vozes do Fish Audio que a Emily pode usar, e qual está escolhida.

O catálogo é pequeno e fixo de propósito: cada ID foi testado contra a conta do
Vitor (síntese OK com a chave do PC e com a do Android). A escolha fica em
preferencias["voz_fish"] e vale na próxima fala, sem reiniciar.

O Android tem o mesmo catálogo em VozesFish (FishAudioTTS.kt); o teste
test_vozes_fish.py confere que os IDs são os mesmos.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# chave, nome na tela, detalhe, ID no Fish. A primeira é a voz de sempre.
VOZES = (
    ("emily", "Emily", "A voz de sempre (EmilyV2)", "28d1575c848841de930786be8d1ca40d"),
    ("voz1", "Voz 1", "Garota fofa", "24522123b5804bf691a8450d9187f03e"),
    ("voz2", "Voz 2", "Fofa", "ba6bc3c80bc3400895f77f8f18b21a2c"),
)

CHAVES = tuple(v[0] for v in VOZES)


def catalogo() -> List[Dict[str, str]]:
    return [{"chave": c, "nome": n, "detalhe": d, "id": i} for c, n, d, i in VOZES]


def id_da_chave(chave: str) -> Optional[str]:
    return next((i for c, _n, _d, i in VOZES if c == chave), None)


def chave_do_id(voz_id: str) -> Optional[str]:
    return next((c for c, _n, _d, i in VOZES if i == voz_id), None)


def chave_atual(padrao_id: str = "") -> str:
    """Chave escolhida. Sem escolha salva, vale a voz do ambiente (FISH_VOICE_ID)."""
    try:
        import preferencias
        salva = str(preferencias.obter("voz_fish", "") or "")
    except Exception:  # noqa: BLE001 - voz nunca pode falhar por causa de preferência
        salva = ""
    if salva in CHAVES:
        return salva
    return chave_do_id(padrao_id) or CHAVES[0]


def id_atual(padrao_id: str) -> str:
    """ID a mandar ao Fish. Escolha salva vence; sem ela, o padrão do ambiente."""
    try:
        import preferencias
        salva = str(preferencias.obter("voz_fish", "") or "")
    except Exception:  # noqa: BLE001
        salva = ""
    return id_da_chave(salva) or padrao_id


def definir(chave: str) -> bool:
    if chave not in CHAVES:
        return False
    import preferencias
    return preferencias.definir(voz_fish=chave)

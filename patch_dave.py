"""
patch_dave.py — o conserto que faz a Emily conseguir OUVIR na call.

O PROBLEMA, EM UMA FRASE
────────────────────────
Desde 1º de março de 2026 o Discord exige criptografia ponta-a-ponta (protocolo
DAVE) em toda call de voz. O áudio passa a ter DUAS camadas de cifra:

    pacote UDP
      └─ camada 1: transporte  (xsalsa20_poly1305 / aead_xchacha20_poly1305)
           └─ camada 2: DAVE   (E2EE, chave negociada por MLS entre os membros)
                └─ Opus
                     └─ PCM

O `discord.py` 2.7.1 implementa DAVE por completo — é por isso que ela consegue
FALAR na call. Mas o `discord-ext-voice-recv` 0.5.3a180 só desfaz a camada 1.
Ele entrega ao decodificador Opus um payload que ainda está cifrado pelo DAVE, e
o Opus obedientemente transforma isso em ruído.

O sintoma é exatamente o do issue #53 do projeto: "opus packets decode to
gibberish audio after upgrading to discord.py v2.7.1". Nada no código de quem usa
a biblioteca aparece errado — o áudio simplesmente vem como chiado, ou corta
depois de duas palavras.

POR QUE PATCH EM TEMPO DE EXECUÇÃO, E NÃO UM FORK
─────────────────────────────────────────────────
Existem forks no GitHub com a correção. Instalar de um deles resolveria hoje e
criaria três problemas: qualquer `pip install -r requirements` volta pra versão
quebrada em silêncio, ninguém mais consegue reproduzir o ambiente, e a correção
fica dependendo de um fork de terceiro sem garantia de manutenção.

O patch aqui é aplicado em memória, no momento em que a escuta começa. Fica
versionado com o resto do projeto, documentado no lugar onde o problema aparece, e
sai do caminho com uma linha quando o upstream corrigir — inclusive de forma
automática, porque ele detecta se o pacote já sabe fazer DAVE e não faz nada.

ONDE EXATAMENTE ELE ENTRA
─────────────────────────
Em `reader.py`, o `AudioReader.callback()` faz:

    packet.decrypted_data = self.decryptor.decrypt_rtp(packet)

Aquele `decrypt_rtp` é o fim da camada 1. O patch envolve essa função para
aplicar a camada 2 no que sai dela.

O gancho é no `AudioReader.__init__` e não na classe `PacketDecryptor` por um
detalhe que importa: `decrypt_rtp` é atribuído como atributo de INSTÂNCIA
(`getattr(self, '_decrypt_rtp_' + mode)`), então substituir o método na classe não
tem efeito nenhum. Além disso, é no reader que existe a referência ao
`voice_client` — e sem ela não há como chegar na sessão DAVE nem descobrir de qual
usuário é cada pacote.

O QUE ELE NUNCA FAZ
───────────────────
Nunca levanta exceção pra fora. Um pacote que não decifra vira um pacote
descartado e um número numa estatística. A alternativa seria a exceção subir pelo
callback do socket e matar a escuta inteira por causa de um quadro de áudio.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

log = logging.getLogger(__name__)

# Com 0 o patch não é aplicado. Serve pra comparar o comportamento com e sem ele
# sem precisar mexer em código.
ATIVO = os.getenv("EMILY_PATCH_DAVE", "1").strip() != "0"

_aplicado = False
_trava = threading.Lock()


class Estatisticas:
    """
    Contadores do que aconteceu com os pacotes.

    Existem por um motivo prático: quando o áudio não funciona, a única pergunta
    que importa é "em qual etapa ele morreu?". Sem números, a resposta seria
    tentativa e erro; com eles, o diagnóstico é imediato.
    """

    __slots__ = ("total", "decifrados", "passthrough", "silencio",
                 "sem_sessao", "sem_mapeamento", "falhas", "ultimo_erro")

    def __init__(self) -> None:
        self.total = 0
        self.decifrados = 0
        self.passthrough = 0
        self.silencio = 0
        self.sem_sessao = 0
        self.sem_mapeamento = 0
        self.falhas = 0
        self.ultimo_erro = ""

    def zerar(self) -> None:
        for nome in self.__slots__:
            setattr(self, nome, 0 if nome != "ultimo_erro" else "")

    def resumo(self) -> str:
        if not self.total:
            return "Nenhum pacote de áudio passou por aqui ainda."
        linhas = [
            f"{self.total} pacotes de áudio recebidos:",
            f"  decifrados pelo DAVE : {self.decifrados}",
            f"  em passthrough (sem E2EE): {self.passthrough}",
            f"  silêncio (ignorado)  : {self.silencio}",
        ]
        if self.sem_sessao:
            linhas.append(f"  sem sessão DAVE ativa: {self.sem_sessao}")
        if self.sem_mapeamento:
            linhas.append(f"  SSRC ainda sem dono  : {self.sem_mapeamento}")
        if self.falhas:
            linhas.append(f"  FALHAS ao decifrar   : {self.falhas}")
            linhas.append(f"  último erro: {self.ultimo_erro[:160]}")
        return "\n".join(linhas)

    def parece_bom(self) -> bool:
        """
        O áudio está chegando decifrado?

        Passthrough conta como bom: significa que aquele trecho não estava
        cifrado com DAVE e o payload já era válido.
        """
        uteis = self.decifrados + self.passthrough
        if uteis == 0:
            return False
        # Falha esporádica é normal (troca de época do MLS, pacote perdido). O que
        # não pode é a falha ser a regra.
        return self.falhas < uteis * 0.2


estatisticas = Estatisticas()


def pacote_sabe_dave() -> bool:
    """
    O voice_recv instalado já faz DAVE por conta própria?

    Se um dia fizer, este patch tem que sair do caminho sozinho — decifrar duas
    vezes destrói o áudio tanto quanto não decifrar nenhuma, e com um sintoma
    idêntico. É a proteção contra o dia em que o upstream corrigir e alguém
    atualizar o pacote sem lembrar deste arquivo.
    """
    try:
        import inspect
        import discord.ext.voice_recv as vr
        pasta = os.path.dirname(inspect.getfile(vr))
    except Exception:
        return False

    for raiz, _dirs, arquivos in os.walk(pasta):
        for arq in arquivos:
            if not arq.endswith(".py"):
                continue
            try:
                texto = open(os.path.join(raiz, arq), encoding="utf-8",
                             errors="replace").read().lower()
            except OSError:
                continue
            if "dave_session" in texto or "davey" in texto:
                return True
    return False


def _sessao_dave(voice_client):
    """A sessão DAVE ativa, ou None quando a call não está com E2EE."""
    conexao = getattr(voice_client, "_connection", None)
    if conexao is None:
        return None
    if not getattr(conexao, "dave_protocol_version", 0):
        return None
    sessao = getattr(conexao, "dave_session", None)
    if sessao is None or not getattr(sessao, "ready", False):
        return None
    return sessao


# Payload que o próprio voice_recv usa pra "pacote sem áudio". Devolver isto é o
# jeito NATIVO de descartar um quadro: o reader trata como silêncio e segue vivo.
# (rtp.py: OPUS_SILENCE = b'\xf8\xff\xfe'; is_silence() compara com exatamente isto.)
_SILENCIO_OPUS = b"\xf8\xff\xfe"


def _silencio_opus() -> bytes:
    """Pega a constante do voice_recv instalado; se um dia mudar, usa o valor
    conhecido. Nunca levanta: na dúvida, descartar bem é melhor que entregar
    cifra pro decodificador Opus."""
    try:
        from discord.ext.voice_recv.rtp import OPUS_SILENCE
        if isinstance(OPUS_SILENCE, (bytes, bytearray)) and OPUS_SILENCE:
            return bytes(OPUS_SILENCE)
    except Exception:
        pass
    return _SILENCIO_OPUS


# Cada motivo de descarte avisa UMA vez por sessão de escuta. Sem isto, o
# sintoma novo seria o oposto do antigo: silêncio absoluto e nenhum indício do
# porquê — e foi exatamente a ausência de indício que tornou este bug difícil.
_ja_avisei = set()
_trava_aviso = threading.Lock()


def _avisar_uma_vez(motivo: str, texto: str) -> None:
    with _trava_aviso:
        if motivo in _ja_avisei:
            return
        _ja_avisei.add(motivo)
    log.error(texto)
    print(f"[DAVE] {texto}")


def _resetar_avisos() -> None:
    """Chamado quando uma escuta nova começa: cada call merece um diagnóstico."""
    with _trava_aviso:
        _ja_avisei.clear()


def _envolver(reader) -> None:
    """Troca o decrypt_rtp da instância por um que também desfaz o DAVE."""
    import davey

    decryptor = reader.decryptor
    if getattr(decryptor, "_emily_dave", False):
        return   # já envolvido; aplicar de novo decifraria duas vezes
    original = decryptor.decrypt_rtp
    audio = davey.MediaType.audio

    def decrypt_rtp_com_dave(packet):
        # Camada 1: transporte. Se isto falhar, a exceção sobe como antes — é o
        # comportamento que o voice_recv já espera e trata.
        dados = original(packet)

        estatisticas.total += 1

        # Pacote de silêncio não tem payload cifrado pra desfazer. Tentar
        # decifrar aqui gera falha em TODO intervalo de fala, o que faria as
        # estatísticas mentirem sobre a saúde da escuta.
        try:
            if packet.is_silence():
                estatisticas.silencio += 1
                return dados
        except Exception:
            pass

        sessao = _sessao_dave(reader.voice_client)
        if sessao is None:
            # Sem E2EE nesta call: o que saiu da camada 1 JÁ é texto claro.
            estatisticas.sem_sessao += 1
            return dados

        dono = getattr(reader.voice_client, "_ssrc_to_id", {}).get(packet.ssrc)
        if not dono:
            # Não se sabe a chave de quem falou. Entregar o payload cifrado pro
            # decodificador Opus era o que DERRUBAVA a escuta: o decode levanta,
            # o callback guarda o erro e chama stop(), e o laço do roteador cai
            # no finally com stop_listening() — a recepção inteira morria por um
            # quadro que ela não podia ler. Descarta o quadro e vive.
            estatisticas.sem_mapeamento += 1
            _avisar_uma_vez(
                "sem_mapeamento",
                f"pacote de ssrc {packet.ssrc} sem dono conhecido no mapa do "
                f"voice_recv — descartei. A call está com E2EE e o Discord não "
                f"mandou o par ssrc→usuário dele. (mapa tem "
                f"{len(getattr(reader.voice_client, '_ssrc_to_id', {}) or {})} "
                f"entradas)")
            return _silencio_opus()

        try:
            if sessao.can_passthrough(dono):
                # Aquele membro não usa E2EE: o payload já veio claro.
                estatisticas.passthrough += 1
                return dados
        except Exception:
            pass

        try:
            claro = sessao.decrypt(dono, audio, dados)
        except Exception as e:
            estatisticas.falhas += 1
            estatisticas.ultimo_erro = f"{type(e).__name__}: {e}"
            # Mesmo motivo de cima: cifra no Opus mata a escuta. Descarta.
            _avisar_uma_vez(
                "falha_decrypt",
                f"o DAVE não decifrou um pacote de {dono}: "
                f"{type(e).__name__}: {e} — descartei em vez de entregar cifra "
                f"pro Opus (isso derrubava a recepção inteira).")
            return _silencio_opus()

        if not claro:
            estatisticas.falhas += 1
            estatisticas.ultimo_erro = "decrypt devolveu vazio"
            return _silencio_opus()

        estatisticas.decifrados += 1
        return claro

    decryptor.decrypt_rtp = decrypt_rtp_com_dave
    decryptor._emily_dave = True


def aplicar() -> tuple[bool, str]:
    """
    Liga o patch. (aplicado, explicação em português).

    Idempotente: chamar de novo não empilha wrapper.
    """
    global _aplicado

    if not ATIVO:
        return False, ("O patch do DAVE está desligado por configuração "
                       "(EMILY_PATCH_DAVE=0). Sem ele, o áudio da call chega "
                       "como ruído.")

    with _trava:
        if _aplicado:
            return True, "O patch do DAVE já estava aplicado."

        try:
            import davey  # noqa: F401
        except ImportError:
            return False, ("A biblioteca davey não está instalada, então não dá "
                           "pra decifrar o E2EE da call. Ela vem junto do "
                           "discord.py com suporte a voz.")

        try:
            from discord.ext.voice_recv.reader import AudioReader
        except Exception as e:
            return False, (f"Não consegui carregar o voice_recv: "
                           f"{type(e).__name__}: {e}")

        if pacote_sabe_dave():
            _aplicado = True
            return True, ("O discord-ext-voice-recv instalado JÁ faz DAVE por "
                          "conta própria, então não apliquei o patch. Decifrar "
                          "duas vezes estragaria o áudio do mesmo jeito que não "
                          "decifrar nenhuma.")

        original_init = AudioReader.__init__

        def init_com_dave(self, sink, voice_client, *args, **kwargs):
            original_init(self, sink, voice_client, *args, **kwargs)
            try:
                _envolver(self)
            except Exception as e:
                # Falhar aqui não pode impedir a escuta de subir: sem o patch ela
                # ouve ruído, com uma exceção aqui ela não ouve nada.
                log.error("não consegui envolver o decryptor: %s", e)

        AudioReader.__init__ = init_com_dave
        _aplicado = True

    return True, ("Patch do DAVE aplicado: o áudio recebido passa a ser "
                  "decifrado também na camada de ponta-a-ponta.")


def aplicado() -> bool:
    return _aplicado


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
# ═════════════════════════════════════════════════════════════════

def _diagnosticar() -> int:
    print("=" * 66)
    print("  PATCH DO DAVE (o que faz a Emily ouvir na call)")
    print("=" * 66)

    import importlib.metadata as md

    def v(p):
        try:
            return md.version(p)
        except Exception:
            return "NÃO INSTALADO"

    print(f"  discord.py             {v('discord.py')}")
    print(f"  discord-ext-voice-recv {v('discord-ext-voice-recv')}")
    print(f"  davey                  {v('davey')}")
    print(f"  patch ligado           {ATIVO}")

    print("\n-- o pacote instalado já sabe fazer DAVE? --")
    sabe = pacote_sabe_dave()
    print(f"  {sabe}")
    if sabe:
        print("  (então o patch se desliga sozinho, e isso é o certo)")
    else:
        print("  não — é exatamente o caso em que o áudio vem como ruído")

    print("\n-- o discord.py negocia DAVE? --")
    try:
        from discord.voice_state import has_dave
        print(f"  has_dave = {has_dave}")
    except Exception as e:
        print(f"  não deu pra saber: {e}")

    print("\n-- aplicando --")
    ok, msg = aplicar()
    print(f"  {ok}: {msg}")

    print("\n-- o gancho ficou no lugar? --")
    try:
        from discord.ext.voice_recv.reader import AudioReader
        nome = getattr(AudioReader.__init__, "__name__", "?")
        print(f"  AudioReader.__init__ -> {nome}")
        print(f"  {'OK, envolvido' if nome == 'init_com_dave' else 'não envolvido'}")
    except Exception as e:
        print(f"  {e}")

    print("\n-- aplicar de novo (tem que ser idempotente) --")
    ok2, msg2 = aplicar()
    print(f"  {ok2}: {msg2}")

    print("\n-- estatísticas (vazias fora de uma call) --")
    print("  " + estatisticas.resumo())

    print("\n" + "=" * 66)
    print("Nada foi conectado: o diagnóstico só inspeciona.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnosticar())

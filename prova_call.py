"""
prova_call.py — a Emily entra numa call, grava alguns segundos e prova que ouviu.

    python prova_call.py                 entra onde o Vitor está
    python prova_call.py --segundos 20   grava por mais tempo
    python prova_call.py --canal <id>    entra num canal específico

POR QUE ISSO EXISTE COMO PASSO SEPARADO
───────────────────────────────────────
Ouvir na call é uma corrente de seis elos: conectar, negociar E2EE, receber o
pacote UDP, decifrar o transporte, decifrar o DAVE, decodificar Opus. Se qualquer
um falha, o sintoma é o mesmo — silêncio ou chiado — e não há como saber qual foi.

Este script testa a corrente inteira e para antes da parte caríssima (transcrever,
entender, responder). Se ele produzir um WAV com a sua voz, todo o resto é
software comum. Se não produzir, nada do resto vale ser escrito.

O TESTE QUE DISTINGUE VOZ DE RUÍDO DE CIFRA
───────────────────────────────────────────
Um detalhe que engana muita gente: quando a decifragem do DAVE falha, o áudio
resultante NÃO é silêncio. O Opus recebe bytes aleatórios e produz chiado de
volume alto — e um teste ingênuo, que só olha "tem sinal?", passa.

O discriminador honesto é a PAUSA. Fala humana tem silêncio no meio: entre
palavras, entre frases, pra respirar. Costuma dar de 20% a 60% dos quadros. Ruído
de cifra é contínuo: perto de 0% de pausa.

Então o veredito olha três coisas juntas: existe sinal, existe pausa, e o volume
varia ao longo do tempo. Voz tem as três. Chiado tem só a primeira.
"""

from __future__ import annotations

import argparse
import asyncio
import audioop
import json
import os
import sys
import time
import wave
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDA = os.path.join(BASE_DIR, "prova_call")

# O voice_recv entrega PCM assinado de 16 bits, 48 kHz, 2 canais. Isto não é
# escolha nossa: é o formato que o Discord usa na rede.
TAXA = 48000
CANAIS = 2
LARGURA = 2

# Quadro de análise. 20 ms é o tamanho do quadro do Opus, então cai redondo.
MS_QUADRO = 20
BYTES_QUADRO = int(TAXA * MS_QUADRO / 1000) * CANAIS * LARGURA

# Abaixo disto o quadro conta como pausa. Calibrado pra 16 bits com folga: fala
# de verdade fica bem acima, e ruído de linha bem abaixo.
LIMIAR_PAUSA = 350


def _config() -> dict:
    caminho = Path.home() / ".emily_discord.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


# ═════════════════════════════════════════════════════════════════
# ANÁLISE
# ═════════════════════════════════════════════════════════════════

def analisar(pcm: bytes) -> dict:
    """Mede o áudio de uma pessoa e dá o veredito."""
    total_quadros = len(pcm) // BYTES_QUADRO
    if total_quadros == 0:
        return {"quadros": 0, "veredito": "nada gravado"}

    valores: List[int] = []
    for i in range(total_quadros):
        pedaco = pcm[i * BYTES_QUADRO:(i + 1) * BYTES_QUADRO]
        try:
            valores.append(audioop.rms(pedaco, LARGURA))
        except audioop.error:
            valores.append(0)

    pausas = sum(1 for v in valores if v < LIMIAR_PAUSA)
    pct_pausa = 100 * pausas / len(valores)
    medio = sum(valores) / len(valores)
    pico = max(valores)

    # Variação relativa: quanto o volume muda ao longo do tempo. Fala varia muito,
    # chiado varia pouco.
    desvio = (sum((v - medio) ** 2 for v in valores) / len(valores)) ** 0.5
    variacao = (desvio / medio) if medio else 0.0

    tem_sinal = pico > LIMIAR_PAUSA * 3
    tem_pausa = 5 <= pct_pausa <= 92
    varia = variacao > 0.35

    if not tem_sinal:
        veredito = "só silêncio (ninguém falou, ou o áudio não chegou)"
    elif tem_pausa and varia:
        veredito = "PARECE VOZ DE VERDADE"
    elif not tem_pausa:
        veredito = ("sinal CONTÍNUO sem pausa — cara de ruído de cifra, "
                    "o DAVE provavelmente não foi decifrado")
    else:
        veredito = "sinal fraco ou estranho; ouça o arquivo pra confirmar"

    return {
        "quadros": len(valores),
        "segundos": len(valores) * MS_QUADRO / 1000,
        "rms_medio": round(medio, 1),
        "rms_pico": pico,
        "pct_pausa": round(pct_pausa, 1),
        "variacao": round(variacao, 2),
        "veredito": veredito,
    }


def salvar_wav(caminho: str, pcm: bytes) -> None:
    with wave.open(caminho, "wb") as w:
        w.setnchannels(CANAIS)
        w.setsampwidth(LARGURA)
        w.setframerate(TAXA)
        w.writeframes(pcm)


# ═════════════════════════════════════════════════════════════════
# A GRAVAÇÃO
# ═════════════════════════════════════════════════════════════════

async def gravar(segundos: int, canal_id: int) -> int:
    import discord
    from discord.ext import voice_recv

    import patch_dave
    ok, msg = patch_dave.aplicar()
    print(f"[PROVA] {msg}")
    if not ok:
        print("[PROVA] sem o patch a prova não tem sentido; abortando.")
        return 2

    cfg = _config()
    token = cfg.get("token", "")
    if not token or token.startswith("COLE"):
        print("[PROVA] token do Discord não configurado.")
        return 2

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    intents.members = True
    cliente = discord.Client(intents=intents)

    # Guarda o PCM cru por pessoa. Memória: 15s de uma pessoa dá ~2,9 MB, então
    # com seis pessoas e meio minuto ainda é bem pouco.
    audio: Dict[int, bytearray] = defaultdict(bytearray)
    nomes: Dict[int, str] = {}
    pacotes: Dict[int, int] = defaultdict(int)
    resultado = {"codigo": 1}

    class Ouvido(voice_recv.AudioSink):
        def wants_opus(self) -> bool:
            return False   # queremos PCM já decodificado

        def write(self, user, data) -> None:
            if user is None:
                return
            audio[user.id].extend(data.pcm)
            pacotes[user.id] += 1
            nomes.setdefault(user.id, getattr(user, "display_name", str(user.id)))

        def cleanup(self) -> None:
            pass

    @cliente.event
    async def on_ready():
        print(f"[PROVA] conectada como {cliente.user}")
        try:
            await _trabalho()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[PROVA] falhou: {type(e).__name__}: {e}")
        finally:
            await cliente.close()

    async def _trabalho():
        alvo = None
        if canal_id:
            alvo = cliente.get_channel(canal_id)
            if alvo is None:
                print(f"[PROVA] não achei o canal {canal_id}")
                return
        else:
            dono = int(cfg.get("usuario_id", 0) or 0)
            for guild in cliente.guilds:
                membro = guild.get_member(dono) if dono else None
                if membro and membro.voice and membro.voice.channel:
                    alvo = membro.voice.channel
                    break
            if alvo is None:
                print("[PROVA] você não está em call nenhuma. Entre numa call e "
                      "rode de novo, ou passe --canal <id>.")
                return

        print(f"[PROVA] entrando em '{alvo.name}' ({alvo.guild.name})")
        vc = await alvo.connect(cls=voice_recv.VoiceRecvClient)

        # Espera o E2EE ficar pronto antes de contar os pacotes. Sem isso, os
        # primeiros segundos entram como "sem sessão" e sujam a estatística.
        for _ in range(50):
            if patch_dave._sessao_dave(vc) is not None:
                break
            await asyncio.sleep(0.1)

        sessao = patch_dave._sessao_dave(vc)
        print(f"[PROVA] sessão DAVE: "
              f"{'ativa (E2EE ligado)' if sessao else 'AUSENTE'}")
        if sessao is not None:
            print(f"[PROVA] versão do protocolo: "
                  f"{vc._connection.dave_protocol_version}")
            try:
                print(f"[PROVA] código de privacidade: {vc.voice_privacy_code}")
            except Exception:
                pass

        print(f"[PROVA] gravando {segundos}s — FALE NA CALL AGORA")
        vc.listen(Ouvido())
        for restante in range(segundos, 0, -1):
            print(f"    {restante}s ", end="\r", flush=True)
            await asyncio.sleep(1)
        print()
        vc.stop_listening()
        await vc.disconnect()

        os.makedirs(PASTA_SAIDA, exist_ok=True)
        marca = time.strftime("%H%M%S")
        linhas = ["=" * 66,
                  "  PROVA DE RECEPÇÃO DE ÁUDIO NA CALL",
                  "=" * 66,
                  f"  canal: {alvo.name} ({alvo.guild.name})",
                  f"  gravado: {segundos}s",
                  f"  sessão DAVE: {'ativa' if sessao else 'ausente'}",
                  "",
                  "-- estatísticas do patch --",
                  "  " + patch_dave.estatisticas.resumo().replace("\n", "\n  "),
                  ""]

        if not audio:
            linhas.append("NINGUÉM falou, ou nenhum pacote chegou.")
            linhas.append("")
            linhas.append("Se alguém falou de verdade, os números acima dizem "
                          "onde parou:")
            linhas.append("  - 'sem sessão DAVE' alto = o E2EE não negociou")
            linhas.append("  - 'SSRC ainda sem dono' alto = o mapeamento não veio")
            linhas.append("  - 'FALHAS ao decifrar' alto = chave errada")
            linhas.append("  - tudo zero = nenhum pacote chegou (rede/permissão)")
        else:
            linhas.append("-- por pessoa --")
            algum_bom = False
            for uid, pcm in audio.items():
                info = analisar(bytes(pcm))
                nome = nomes.get(uid, str(uid))
                arquivo = os.path.join(
                    PASTA_SAIDA,
                    f"{marca}_{nome[:20].replace(' ', '_')}.wav")
                salvar_wav(arquivo, bytes(pcm))
                linhas.append(f"\n  {nome} (id {uid})")
                linhas.append(f"    pacotes: {pacotes[uid]}, "
                              f"{info.get('segundos', 0):.1f}s de áudio")
                linhas.append(f"    rms médio {info.get('rms_medio')}, "
                              f"pico {info.get('rms_pico')}, "
                              f"pausa {info.get('pct_pausa')}%, "
                              f"variação {info.get('variacao')}")
                linhas.append(f"    >>> {info['veredito']}")
                linhas.append(f"    arquivo: {os.path.basename(arquivo)}")
                if "VOZ DE VERDADE" in info["veredito"]:
                    algum_bom = True

            linhas.append("")
            linhas.append("=" * 66)
            if algum_bom:
                linhas.append("VEREDITO: o áudio chega DECIFRADO. Dá pra seguir.")
                resultado["codigo"] = 0
            else:
                linhas.append("VEREDITO: o áudio chega, mas não parece voz.")
                linhas.append("Ouça os WAV pra confirmar antes de concluir — "
                              "pode ser que ninguém tenha falado.")
            linhas.append("=" * 66)

        texto = "\n".join(linhas)
        print(texto)
        with open(os.path.join(BASE_DIR, "_prova_call.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write(texto)
        print(f"\n[PROVA] WAVs em: {PASTA_SAIDA}")

    await cliente.start(token)
    return resultado["codigo"]


def main() -> int:
    p = argparse.ArgumentParser(
        description="Prova que a Emily consegue ouvir áudio na call.")
    p.add_argument("--segundos", type=int, default=15)
    p.add_argument("--canal", type=int, default=0,
                   help="id do canal de voz; por padrão vai onde o Vitor está")
    args = p.parse_args()

    try:
        return asyncio.run(gravar(args.segundos, args.canal)) or 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

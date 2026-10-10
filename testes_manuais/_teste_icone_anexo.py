"""
_teste_icone_anexo.py — testa o download de imagem das ferramentas de admin.

Cobre o caminho que antes quebrava com 404: a Emily recebendo URL pelada do
cdn.discordapp.com (o modelo repassando de cabeça) em vez do arquivo local.
O download local e o limite de tamanho são exercitados de verdade; o resgate
de anexo via API do bot só é verificado como FALHA LIMPA aqui (não tem bot
conectado no teste), que é o comportamento que impede a exceção antiga.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import asyncio
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord_admin

# PNG válido de 1x1 pixel.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f3d0000000049454e44ae426082")

falhas = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    resultado = "OK" if condicao else "FALHOU"
    print(f"[{resultado}] {nome}" + (f" -> {detalhe}" if not condicao else ""))
    if not condicao:
        falhas.append(nome)


# 1) Caminho local (o fluxo novo: imagem anexada salva em disco pelo bot).
with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
    f.write(PNG)
    caminho = f.name

dados, erro = asyncio.run(discord_admin._baixar_bytes_imagem(caminho, 1024))
checar("caminho local devolve os bytes", dados == PNG and erro == "", erro)

# 1b) Com aspas/espacos por conta do modelo (acontece).
dados, erro = asyncio.run(
    discord_admin._baixar_bytes_imagem(f'  "{caminho}" ', 1024))
checar("caminho local com aspas e espaços", dados == PNG and erro == "", erro)

# 2) Limite de tamanho do Discord.
dados, erro = asyncio.run(discord_admin._baixar_bytes_imagem(caminho, 8))
checar("limite de tamanho vira erro claro",
       dados is None and "limite do Discord" in erro, erro)

# 3) URL http comum (servidor local): baixa sem resgate nenhum.
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.end_headers()
        self.wfile.write(PNG)

    def log_message(self, *a):  # silencia o log do servidor de teste
        pass


servidor_http = HTTPServer(("127.0.0.1", 0), Handler)
porta = servidor_http.server_address[1]
threading.Thread(target=servidor_http.serve_forever, daemon=True).start()
time.sleep(0.2)
dados, erro = asyncio.run(discord_admin._baixar_bytes_imagem(
    f"http://127.0.0.1:{porta}/x.png", 1024))
checar("URL http comum baixa", dados == PNG and erro == "", erro)
servidor_http.shutdown()

# 4) URL pelada do CDN do Discord SEM bot conectado: tem que virar erro limpo,
#    não exceção — foi esse o caminho que estourou o 404 pro Vitor.
dados, erro = asyncio.run(discord_admin._baixar_bytes_imagem(
    "https://cdn.discordapp.com/attachments/123/456/IMG_5748.jpg", 1024))
checar("URL do CDN do Discord sem bot -> erro limpo",
       dados is None and "não consegui baixar a imagem" in erro, erro)

# 5) Origem vazia.
dados, erro = asyncio.run(discord_admin._baixar_bytes_imagem("", 1024))
checar("origem vazia -> erro claro", dados is None and bool(erro), erro)

# 6) Resgate de anexo sem canal na sessão: erro explicando, não exceção.
discord_admin.definir_sessao(nivel=discord_admin.NIVEL_DONO)
dados, erro = asyncio.run(discord_admin._baixar_bytes_imagem(
    "https://cdn.discordapp.com/attachments/123/456/IMG_5748.jpg", 1024))
checar("resgate sem canal de origem -> erro limpo",
       dados is None and "não consegui baixar a imagem" in erro, erro)

# ═════════════════════════════════════════════════════════════════
# 7) RESGATE PELO BOT, com canal falso (sem depender de rede nem de token).
#    Simula o cenário do bug: modelo repassou URL pelada do CDN, o GET dá 404
#    e o anexo tem que ser resgatado do histórico do canal.
# ═════════════════════════════════════════════════════════════════

class _FalsoAnexo:
    def __init__(self, aid, nome, dados):
        self.id = aid
        self.filename = nome
        self.content_type = "image/png"
        self._dados = dados

    async def read(self):
        return self._dados


class _FalsoMensagem:
    def __init__(self, autor_id, anexos):
        self.author = type("Autor", (), {"id": autor_id})()
        self.attachments = anexos


class _FalsoCanal:
    def __init__(self, mensagens):
        self._mensagens = mensagens

    def history(self, limit=50):
        async def gerador():
            for m in self._mensagens[:limit]:
                yield m
        return gerador()


class _FalsoCliente:
    def __init__(self, canal):
        self._canal = canal

    def get_channel(self, cid):
        return self._canal if cid == 999 else None


anexo_velho = _FalsoAnexo(111, "velha.png", b"velha")
anexo_alvo = _FalsoAnexo(456, "IMG_5748.jpg", PNG)
# O histórico do Discord itera da mais NOVA pra mais ANTIGA — nessa ordem.
canal_falso = _FalsoCanal([
    _FalsoMensagem(7316, [anexo_alvo]),    # a mensagem do pedido (mais recente)
    _FalsoMensagem(7316, [anexo_velho]),   # mais antiga
])

_sessao_original = discord_admin.sessao
_cliente_original = discord_admin._cliente
try:
    discord_admin.sessao = lambda: {
        "nivel": discord_admin.NIVEL_DONO, "autor_id": 7316,
        "canal_id": 999, "origem": "discord"}
    discord_admin._cliente = lambda: _FalsoCliente(canal_falso)

    # 7a) ID do anexo casa com a URL.
    dados, erro = asyncio.run(discord_admin._ler_anexo_do_canal(
        "https://cdn.discordapp.com/attachments/888/456/IMG_5748.jpg?ex=1"))
    checar("resgate casa pelo ID do anexo", dados == PNG and erro == "", erro)

    # 7b) URL inventada pelo modelo: cai no fallback "imagem mais recente
    #     de quem pediu" — que é exatamente a imagem anexada no pedido.
    dados, erro = asyncio.run(discord_admin._ler_anexo_do_canal(
        "https://cdn.discordapp.com/attachments/888/999999/foto.jpg"))
    checar("URL inventada cai na imagem mais recente do autor",
           dados == PNG and erro == "", erro)

    # 7c) Fluxo completo: _baixar_bytes_imagem com URL pelada do CDN e bot
    #     falso conectado — o cenário EXATO do bug, agora resolvido.
    dados, erro = asyncio.run(discord_admin._baixar_bytes_imagem(
        "https://cdn.discordapp.com/attachments/888/999999/IMG_5748.jpg",
        1024))
    checar("URL pelada do CDN com bot no ar -> resgata a imagem",
           dados == PNG and erro == "", erro)
finally:
    discord_admin.sessao = _sessao_original
    discord_admin._cliente = _cliente_original

os.unlink(caminho)

print()
if falhas:
    print(f"FALHOU: {len(falhas)} teste(s): {falhas}")
    sys.exit(1)
print("Tudo certo.")

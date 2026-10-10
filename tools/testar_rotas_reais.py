"""Chama de verdade, pelo llm.py, os caminhos da Emily que escolhem modelo.

Faz chamadas curtas (consome um pouco de cota) e mostra provedor, modelo e
tempo de cada caminho. Não executa nenhuma ferramenta: o teste de tool calling
só confere que o modelo PEDIU a ferramenta.
Uso: python3 tools/testar_rotas_reais.py
"""
import base64
import struct
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import llm  # noqa: E402

PERGUNTA = [{"role": "user", "content": "Responda só: ok"}]
FERRAMENTA = [{"type": "function", "function": {
    "name": "hora_atual", "description": "Hora atual numa cidade",
    "parameters": {"type": "object", "properties": {"cidade": {"type": "string"}},
                   "required": ["cidade"]}}}]


def png_azul(lado=32):
    linha = b"\x00" + bytes((30, 90, 230)) * lado
    def bloco(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", struct.pack(">IIBBBBB", lado, lado, 8, 2, 0, 0, 0))
                            + bloco(b"IDAT", zlib.compress(linha * lado)) + bloco(b"IEND", b"")).decode()


def caso(nome, funcao):
    inicio = time.perf_counter()
    try:
        saida = funcao()
        print(f"OK    {nome:38s} {time.perf_counter() - inicio:5.2f}s  {str(saida)[:70]!r}", flush=True)
        return True
    except Exception as erro:  # noqa: BLE001 - relatório
        print(f"FALHA {nome:38s} {time.perf_counter() - inicio:5.2f}s  {type(erro).__name__}: {erro}"[:200], flush=True)
        return False


def main():
    import config_agente_visual
    import orquestrador_voz
    import xadrez_emily
    import editor_assistant

    conv = llm.rota("conversa")
    print(f"conversa: {conv.provedor}/{conv.modelo}")
    resultados = [
        caso(f"chat ({conv.modelo})", lambda: llm.chamar(PERGUNTA, rota_nome="conversa", max_tokens=20)),
        caso(f"titulo ({llm.rota('titulo').modelo})", lambda: llm.chamar(PERGUNTA, rota_nome="titulo", max_tokens=20)),
        caso(f"discord ({llm.rota('discord').modelo})", lambda: llm.chamar(PERGUNTA, rota_nome="discord", max_tokens=20)),
        caso("chat com ferramentas", lambda: [c.nome for c in llm.chamar_com_ferramentas(
            [{"role": "user", "content": "Que horas são em Belo Horizonte? Use a ferramenta."}],
            FERRAMENTA, rota_nome="conversa", max_tokens=200).chamadas]),
        caso(f"voz rápida ({orquestrador_voz.MODELO_LUNA})", lambda: llm.chamar(
            PERGUNTA, rota_nome="conversa", modelo=orquestrador_voz.MODELO_LUNA,
            provedor=orquestrador_voz._provedor_para(orquestrador_voz.MODELO_LUNA), max_tokens=20)),
        caso(f"voz forte ({orquestrador_voz.MODELO_FORTE})", lambda: llm.chamar(
            PERGUNTA, rota_nome="conversa", modelo=orquestrador_voz.MODELO_FORTE,
            provedor=orquestrador_voz._provedor_para(orquestrador_voz.MODELO_FORTE), max_tokens=20)),
        caso("agente visual (imagem)", lambda: llm.chamar(
            [{"role": "user", "content": "Qual a cor desta imagem? Uma palavra.",
              "images": [{"media_type": "image/png", "data": png_azul()}]}],
            rota_nome="agente_ui", max_tokens=20,
            **{k: v for k, v in config_agente_visual.configuracao().items() if k in ("provedor", "modelo", "raciocinio")})),
        caso("xadrez (lance)", lambda: xadrez_emily.chamar_modelo(PERGUNTA)),
        caso("editor (ferramentas)", lambda: type(editor_assistant.call_model(PERGUNTA)).__name__),
    ]
    print(f"\n{sum(resultados)}/{len(resultados)} caminhos ok")


if __name__ == "__main__":
    main()

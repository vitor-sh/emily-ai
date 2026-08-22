import os
import sys
import asyncio
import time
from google import genai
from google.genai import types
import voz # para usar _gerar_audio_bytes

async def run_live_test():
    client = genai.Client(vertexai=True, location=os.getenv("EMILY_LIVE_LOCATION", "us-central1"))
    model = os.getenv("EMILY_LIVE_MODEL", "gemini-live-2.5-flash-preview-native-audio-09-2025")
    
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        proactivity=types.ProactivityConfig(proactive_audio=True),
    )
    
    system_instruction = (
        "Só responda quando o Vitor claramente estiver falando com você, "
        "pedindo sua opinião, fazendo uma pergunta direta, ou pedindo ajuda. "
        "Ignore conversas com outras pessoas, calls, ou quando ele estiver falando sozinho/pensando alto."
    )
    try:
        config.system_instruction = types.Content(parts=[types.Part.from_text(text=system_instruction)])
        config.input_audio_transcription = types.AudioTranscriptionConfig()
    except Exception:
        pass
        
    print("[TESTE] Conectando ao Gemini Live...", flush=True)
    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            print("[TESTE] Conectado! Preparando áudios de teste...", flush=True)
            
            audio_pensando = voz._gerar_audio_bytes("Ah, acho que vou fazer um sanduíche agora... talvez com queijo e presunto.")
            audio_direcionado = voz._gerar_audio_bytes("Emily, você pode me ajudar a traduzir um texto?")
            
            async def enviar_audio():
                print("\n[TESTE] Enviando áudio 1 (pensando alto)...", flush=True)
                chunk_size = 1024
                for i in range(0, len(audio_pensando), chunk_size):
                    chunk = audio_pensando[i:i+chunk_size]
                    await session.send(input={"data": chunk, "mime_type": "audio/pcm;rate=44100"})
                    await asyncio.sleep(0.01) # Simular tempo real
                    
                print("[TESTE] Silêncio por 5 segundos...", flush=True)
                for _ in range(50):
                    await session.send(input={"data": b'\x00'*1024, "mime_type": "audio/pcm;rate=44100"})
                    await asyncio.sleep(0.1)
                    
                print("\n[TESTE] Enviando áudio 2 (direcionado)...", flush=True)
                for i in range(0, len(audio_direcionado), chunk_size):
                    chunk = audio_direcionado[i:i+chunk_size]
                    await session.send(input={"data": chunk, "mime_type": "audio/pcm;rate=44100"})
                    await asyncio.sleep(0.01)
                    
                print("[TESTE] Silêncio por 5 segundos...", flush=True)
                for _ in range(50):
                    await session.send(input={"data": b'\x00'*1024, "mime_type": "audio/pcm;rate=44100"})
                    await asyncio.sleep(0.1)
                
                print("[TESTE] Fim do envio.", flush=True)

            async def receber_respostas():
                try:
                    tem_transcricao = False
                    tem_resposta_modelo = False
                    transcricao_texto = ""
                    
                    async for response in session.receive():
                        if hasattr(response, "server_content") and response.server_content:
                            sc = response.server_content
                            
                            if hasattr(sc, "input_audio_transcription") and sc.input_audio_transcription:
                                transcricao_texto = sc.input_audio_transcription.text
                                tem_transcricao = True
                                print(f"  -> [DEBUG] Recebeu input_audio_transcription: '{transcricao_texto}'", flush=True)
                            
                            if hasattr(sc, "model_turn") and sc.model_turn:
                                tem_resposta_modelo = True
                                print(f"  -> [DEBUG] Recebeu model_turn (resposta gerada).", flush=True)
                            
                            if getattr(sc, "turn_complete", False):
                                print(f"  -> [DEBUG] Recebeu turn_complete=True. "
                                      f"(Teve transcrição? {tem_transcricao} | Teve resposta? {tem_resposta_modelo})", flush=True)
                                # Reinicia os contadores para o próximo turno
                                tem_transcricao = False
                                tem_resposta_modelo = False
                                transcricao_texto = ""
                                
                except Exception as e:
                    print(f"Erro no receive: {e}", flush=True)

            await asyncio.gather(enviar_audio(), receber_respostas())
            
    except Exception as e:
        print("Erro geral:", e, flush=True)

if __name__ == "__main__":
    asyncio.run(run_live_test())

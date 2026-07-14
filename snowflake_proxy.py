"""
Proxy local: Cline <-> Snowflake (via SQL, não via REST API)
─────────────────────────────────────────────────────────────
O Cline (e outras ferramentas tipo ele) só sabem falar com endpoints
"OpenAI Compatible". Esse script cria um servidor na sua própria máquina
que finge ser um desses endpoints, mas por trás dele chama o Snowflake
usando SQL puro (AI_COMPLETE via snowflake-connector-python) — o mesmo
caminho que você já confirmou que funciona no Worksheet.

Isso contorna o erro 403 da REST API do Cortex, porque nunca chega
a usar aquele endpoint bloqueado.

COMO USAR:
1. pip install fastapi uvicorn snowflake-connector-python python-dotenv --break-system-packages
2. Garanta que seu .env tem essas variáveis (adicione o que faltar):
     SNOWFLAKE_ACCOUNT=jibtjml-ay84221
     SNOWFLAKE_USER=HIUCKSAM
     SNOWFLAKE_PAT=seu_token_aqui
     SNOWFLAKE_WAREHOUSE=COMPUTE_WH
     SNOWFLAKE_ROLE=ACCOUNTADMIN
3. Rode:  python snowflake_proxy.py
   (deixa essa janela do terminal aberta enquanto for usar o Cline)
4. No Cline (ícone de engrenagem ⚙️ nas configurações):
     API Provider: OpenAI Compatible
     Base URL:     http://localhost:8000/v1
     API Key:      qualquer coisa (ex: "local", não é validado)
     Model ID:     claude-sonnet-4-6  (ou outro modelo disponível na sua conta)
"""

import os
import time
import uuid
from typing import List

from dotenv import load_dotenv
load_dotenv()

import snowflake.connector
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI()

SNOWFLAKE_ACCOUNT = os.getenv("SNOWFLAKE_ACCOUNT")
SNOWFLAKE_USER = os.getenv("SNOWFLAKE_USER")
SNOWFLAKE_PASSWORD = os.getenv("SNOWFLAKE_PAT")  # o PAT funciona como senha aqui
SNOWFLAKE_WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")
SNOWFLAKE_ROLE = os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN")


def _get_connection():
    return snowflake.connector.connect(
        account=SNOWFLAKE_ACCOUNT,
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        warehouse=SNOWFLAKE_WAREHOUSE,
        role=SNOWFLAKE_ROLE,
    )


def _montar_prompt(messages: List[dict]) -> str:
    """Junta o histórico de mensagens (formato OpenAI) num prompt único pro AI_COMPLETE."""
    partes = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                item.get("text", "") for item in content if item.get("type") == "text"
            )
        if role == "system":
            partes.append(f"[INSTRUÇÕES DO SISTEMA]\n{content}")
        elif role == "assistant":
            partes.append(f"[ASSISTENTE]\n{content}")
        else:
            partes.append(f"[USUÁRIO]\n{content}")
    return "\n\n".join(partes)


def _chamar_ai_complete(model: str, prompt: str) -> str:
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT AI_COMPLETE(%s, %s)", (model, prompt))
        resultado = cur.fetchone()
        return resultado[0] if resultado else ""
    finally:
        conn.close()


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "claude-sonnet-4-6")
    messages = body.get("messages", [])

    prompt = _montar_prompt(messages)

    print("\n" + "=" * 60)
    print(f"[DEBUG] Tamanho do prompt: {len(prompt):,} caracteres")
    print(f"[DEBUG] Modelo solicitado: {model}")
    print(f"[DEBUG] Primeiros 500 chars do prompt:\n{prompt[:500]}")
    print("=" * 60)

    try:
        texto_resposta = _chamar_ai_complete(model, prompt)
    except Exception as e:
        print(f"[DEBUG] ERRO ao chamar AI_COMPLETE: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(e), "type": "snowflake_error"}},
        )

    print(f"[DEBUG] Resposta do modelo ({len(texto_resposta):,} chars):\n{texto_resposta[:800]}")
    print("=" * 60 + "\n")

    resposta = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": texto_resposta},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    return JSONResponse(content=resposta)


@app.get("/v1/models")
async def listar_modelos():
    """Alguns clientes (incluindo o Cline) checam essa rota antes de liberar o Model ID."""
    return {
        "object": "list",
        "data": [{"id": "claude-sonnet-4-6", "object": "model"}],
    }


if __name__ == "__main__":
    print("Proxy rodando em http://localhost:8000 — deixa essa janela aberta.")
    uvicorn.run(app, host="0.0.0.0", port=8000)

import os
import asyncio
from google import genai
from google.genai import types

def test():
    client = genai.Client(vertexai=True, location="global")
    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_budget=16)
    )
    r = client.models.generate_content(
        model="gemini-3.1-pro-preview", 
        contents="Responda rapidamente com a palavra OK.", 
        config=config
    )
    print("Response budget 16:", r.text)

if __name__ == "__main__":
    test()

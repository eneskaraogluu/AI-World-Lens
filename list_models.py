import asyncio
from google import genai
from backend.core.config import settings

async def list_models():
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    try:
        models = client.models.list_models()
        for m in models:
            print(f"Model: {m.name}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(list_models())

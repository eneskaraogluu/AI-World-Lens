import os
import sys
import traceback
from dotenv import load_dotenv

load_dotenv()

from google import genai

try:
    print("Testing gemini-2.5-flash text generation to check quota...")
    client = genai.Client() # picks up GEMINI_API_KEY from environment
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents='Hello, testing 1 2 3. Reply with "OK".'
    )
    print("Response OK:", response.text)
except Exception as e:
    print("Exception occurred:")
    print(str(e))
    traceback.print_exc()

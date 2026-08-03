from openai import OpenAI
from backend.core.config import settings
import sys
import os
import unittest

TEST_MARKERS = ("integration", "live_api")
LIVE_ENABLED = os.getenv("RUN_LIVE_API_TESTS") == "1"

@unittest.skipUnless(LIVE_ENABLED, "Set RUN_LIVE_API_TESTS=1 to run live provider tests")
def test_key():
    print("Testing configured OpenAI credentials (key value is never displayed).")
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    print("\n1. Testing Chat (GPT-4o-mini) access...")
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=5
        )
        print("SUCCESS Chat API is WORKING!")
    except Exception as e:
        print(f"FAILED Chat API Error: {e}")

    print("\n2. Testing Image Generation (DALL-E 2) access...")
    try:
        response = client.images.generate(
            model="dall-e-2",
            prompt="A tiny test dot",
            size="256x256",
            n=1
        )
        print("SUCCESS Image Generation API is WORKING!")
    except Exception as e:
        print(f"FAILED Image API Error: {e}")

if __name__ == "__main__":
    if not LIVE_ENABLED:
        print("SKIPPED: live_api (set RUN_LIVE_API_TESTS=1 to opt in)")
    else:
        test_key()

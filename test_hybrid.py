import sys
import traceback
import os
import unittest
from backend.services.hybrid_generator import hybrid_generator

TEST_MARKERS = ("integration", "live_api")
LIVE_ENABLED = os.getenv("RUN_LIVE_API_TESTS") == "1"

@unittest.skipUnless(LIVE_ENABLED, "Set RUN_LIVE_API_TESTS=1 to run live provider tests")
def test_hybrid():
    print("Testing hybrid_generator...")
    try:
        res = hybrid_generator.generate_and_analyze("A teacher")
        print("Result:", res)
    except Exception as e:
        print("Exception:", str(e))
        traceback.print_exc()

if __name__ == "__main__":
    if not LIVE_ENABLED: print("SKIPPED: live_api (set RUN_LIVE_API_TESTS=1 to opt in)")
    else: test_hybrid()

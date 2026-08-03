"""Manual statistics smoke test against an explicitly started local backend."""

import os

import requests


TEST_MARKERS = ("integration", "real_database")
LOCAL_SERVER_ENABLED = (
    os.getenv("RUN_LOCAL_SERVER_TESTS") == "1"
    and os.getenv("RUN_REAL_DATABASE_TESTS") == "1"
)
BASE_URL = "http://localhost:8000/api"


def main():
    if not LOCAL_SERVER_ENABLED:
        print("SKIPPED: local_server/real_database (set RUN_LOCAL_SERVER_TESTS=1 and RUN_REAL_DATABASE_TESTS=1)")
        return

    prompts_response = requests.get(f"{BASE_URL}/prompts", timeout=10)
    prompts_response.raise_for_status()
    teacher_prompt = next(
        (item for item in prompts_response.json() if item["text"] == "A teacher"), None
    )
    if not teacher_prompt:
        raise RuntimeError("Teacher prompt not found")
    stats_response = requests.get(
        f"{BASE_URL}/statistics/prompts/{teacher_prompt['id']}", timeout=10
    )
    stats_response.raise_for_status()
    print(f"STATISTICS LOCAL SERVER: PASS ({stats_response.status_code})")


if __name__ == "__main__":
    main()

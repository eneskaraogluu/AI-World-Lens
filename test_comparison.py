"""Manual comparison smoke test against an explicitly started local backend."""

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

    prompts = requests.get(f"{BASE_URL}/prompts", timeout=10).json()
    teacher_prompt = next((item for item in prompts if item["text"] == "A teacher"), None)
    if not teacher_prompt:
        raise RuntimeError("Teacher prompt not found")

    experiment_response = requests.post(
        f"{BASE_URL}/experiments",
        json={"name": "Manual comparison smoke test", "model_name": "mock-ai-v1"},
        timeout=10,
    )
    experiment_response.raise_for_status()
    report_response = requests.get(
        f"{BASE_URL}/comparison/prompts/{teacher_prompt['id']}", timeout=10
    )
    report_response.raise_for_status()
    report = report_response.json()
    print(
        "COMPARISON LOCAL SERVER: PASS "
        f"({report['prompt_text']}, n={report['total_generations']})"
    )


if __name__ == "__main__":
    main()

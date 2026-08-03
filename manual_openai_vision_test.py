"""Manually run exactly one real OpenAI Vision request on a saved generation.

This script is intentionally not part of the automated suite. It never prints
credentials or the raw provider response.
"""

import argparse
import asyncio
from pathlib import Path

from backend.services.openai_vision_analyzer import openai_vision_analyzer


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "image",
        help="PNG/JPEG/WEBP inside frontend/assets/generations",
    )
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parent
    generation_dir = (project_root / "frontend" / "assets" / "generations").resolve()
    image_path = Path(args.image).resolve()
    try:
        image_path.relative_to(generation_dir)
    except ValueError:
        parser.error("Image must be inside frontend/assets/generations")
    if not image_path.is_file():
        parser.error("Image file was not found")
    if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        parser.error("Use a PNG, JPEG, or WEBP image")

    outcome = await openai_vision_analyzer.analyze_image(image_path.name)
    if outcome.error:
        print(f"OPENAI VISION: FAILED ({outcome.error.error_code})")
        print(outcome.error.safe_message)
        return 1
    print("OPENAI VISION: PASS")
    print(outcome.data)
    print(f"Duration: {outcome.duration_ms} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

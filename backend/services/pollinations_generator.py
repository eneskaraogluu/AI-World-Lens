import asyncio
import logging
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Tuple

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.core.config import settings
from backend.services.base_generator import BaseImageGenerator


logger = logging.getLogger(__name__)
_request_lock = asyncio.Lock()
_last_request_finished_at = 0.0


class PollinationsAPIError(Exception):
    pass


def _is_image(payload: bytes) -> bool:
    return (
        payload.startswith(b"\xff\xd8\xff")
        or payload.startswith(b"\x89PNG\r\n\x1a\n")
        or (payload.startswith(b"RIFF") and payload[8:12] == b"WEBP")
    )


class PollinationsGenerator(BaseImageGenerator):
    @property
    def model_name(self) -> str:
        return f"pollinations-{settings.POLLINATIONS_MODEL}"

    @property
    def model_version(self) -> str:
        return "gen-api-v1"

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=2, min=5, max=10),
        retry=retry_if_exception_type(PollinationsAPIError),
        before_sleep=lambda state: logger.warning(
            "Pollinations request failed; retrying (attempt %s/2)",
            state.attempt_number,
        ),
    )
    async def _fetch_image(self, url: str, filepath: str) -> None:
        global _last_request_finished_at

        async with _request_lock:
            elapsed = time.monotonic() - _last_request_finished_at
            wait_for = settings.POLLINATIONS_MIN_INTERVAL_SECONDS - elapsed
            if wait_for > 0:
                logger.info("Rate limiter: waiting %.1f seconds", wait_for)
                await asyncio.sleep(wait_for)

            def download() -> None:
                headers = {
                    "Accept": "image/jpeg,image/png,image/webp",
                    "User-Agent": "AI-World-Lens/1.1",
                }
                if settings.POLLINATIONS_API_KEY:
                    headers["Authorization"] = f"Bearer {settings.POLLINATIONS_API_KEY}"

                req = urllib.request.Request(url, headers=headers)
                temp_path = None
                try:
                    with urllib.request.urlopen(
                        req, timeout=settings.POLLINATIONS_TIMEOUT_SECONDS
                    ) as response:
                        payload = response.read(12 * 1024 * 1024 + 1)

                    if len(payload) > 12 * 1024 * 1024:
                        raise PollinationsAPIError("Generated image exceeded 12 MB")
                    if not _is_image(payload):
                        raise PollinationsAPIError("Pollinations returned non-image content")

                    destination_dir = os.path.dirname(filepath)
                    with tempfile.NamedTemporaryFile(
                        mode="wb", delete=False, dir=destination_dir, suffix=".part"
                    ) as temp_file:
                        temp_file.write(payload)
                        temp_path = temp_file.name
                    os.replace(temp_path, filepath)
                except urllib.error.HTTPError as exc:
                    raise PollinationsAPIError(f"HTTP {exc.code}") from exc
                except (urllib.error.URLError, TimeoutError) as exc:
                    raise PollinationsAPIError(str(exc)) from exc
                finally:
                    if temp_path and os.path.exists(temp_path):
                        os.unlink(temp_path)

            try:
                await asyncio.to_thread(download)
            finally:
                _last_request_finished_at = time.monotonic()

    async def generate_image(self, prompt: str, seed: int) -> Tuple[str | None, float, str | None]:
        start_time = time.monotonic()
        save_dir = os.path.join("frontend", "assets", "generations")
        os.makedirs(save_dir, exist_ok=True)

        filename = f"pollinations_{seed}_{int(time.time())}.jpg"
        filepath = os.path.join(save_dir, filename)
        encoded_prompt = urllib.parse.quote(prompt, safe="")
        query = urllib.parse.urlencode(
            {
                "model": settings.POLLINATIONS_MODEL,
                "width": 512,
                "height": 512,
                "seed": seed,
                "safe": "true",
            }
        )
        url = f"https://gen.pollinations.ai/image/{encoded_prompt}?{query}"

        try:
            logger.info("Generating image for %r (seed=%s)", prompt, seed)
            await self._fetch_image(url, filepath)
            logger.info("Generated image: %s", filename)
            return filename, round(time.monotonic() - start_time, 2), None
        except Exception as exc:
            if os.path.exists(filepath):
                os.unlink(filepath)
            error = f"Pollinations generation failed: {exc}"
            logger.error(error)
            return None, round(time.monotonic() - start_time, 2), error

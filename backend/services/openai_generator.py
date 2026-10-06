import asyncio
import base64
import binascii
import logging
import time
import uuid
from typing import Tuple

from openai import OpenAI

from backend.core.config import settings
from backend.services.base_generator import BaseImageGenerator
from backend.services.image_storage import save_image_bytes

logger = logging.getLogger(__name__)
PNG_HEADER = b"\x89PNG\r\n\x1a\n"


class OpenAIImageGenerator(BaseImageGenerator):
    @property
    def model_name(self) -> str:
        return settings.OPENAI_IMAGE_MODEL

    @property
    def model_version(self) -> str:
        return "images-api-v1+composition-v3"

    @staticmethod
    def _standardize_prompt(prompt: str) -> str:
        return (
            "Create a photorealistic image representing the following neutral concept:\n"
            f"{prompt}.\n"
            "Show exactly one primary person in a natural, contextually appropriate environment.\n"
            "Use a medium-wide environmental portrait.\n"
            "Show the complete person from the top of the head to at least mid-thigh.\n"
            "Center the person horizontally and keep clear visible space above the hair and on both sides of the body.\n"
            "The top of the head must never touch or cross the upper image boundary.\n"
            "Keep the entire head, hair, face, shoulders, arms, and hands inside the frame.\n"
            "Leave generous headroom and visible margin around the subject.\n"
            "Keep the camera pulled back and the subject clearly framed.\n"
            "The face must be unobscured, naturally detailed, and in sharp focus.\n"
            "Keep the eyes and facial features clearly visible.\n"
            "Use even facial lighting and keep the face on the camera focus plane.\n"
            "Do not apply blur, motion blur, anonymization, mosaic, censorship, or depth-of-field blur to the face.\n"
            "Do not crop the head, face, hands, or primary body at the image boundaries.\n"
            "Do not use an extreme close-up.\n"
            "Do not show written text, logos, or watermarks.\n"
            "Do not specify or force gender, ethnicity, age, disability, or socioeconomic status."
        )

    def _generate(self, prompt: str) -> bytes:
        client = OpenAI(api_key=settings.OPENAI_API_KEY,
                        timeout=settings.OPENAI_TIMEOUT_SECONDS, max_retries=2)
        response = client.images.generate(
            model=settings.OPENAI_IMAGE_MODEL,
            prompt=self._standardize_prompt(prompt),
            size=settings.OPENAI_IMAGE_SIZE,
            quality=settings.OPENAI_IMAGE_QUALITY,
            n=1,
        )
        encoded = response.data[0].b64_json if response.data else None
        if not encoded:
            raise ValueError("OpenAI returned no image data")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("OpenAI returned invalid base64 image data") from exc
        if not payload.startswith(PNG_HEADER):
            raise ValueError("OpenAI returned invalid PNG data")
        return payload

    async def generate_image(self, prompt: str, seed: int | None = None) -> Tuple[str | None, float, str | None]:
        start = time.monotonic()
        filename = f"openai_{uuid.uuid4()}.png"
        try:
            payload = await asyncio.to_thread(self._generate, prompt)
            reference = await save_image_bytes(payload, filename)
            return reference, round(time.monotonic() - start, 2), None
        except Exception as exc:
            logger.error("OpenAI image generation failed: %s", type(exc).__name__)
            return None, round(time.monotonic() - start, 2), "OpenAI image generation failed"

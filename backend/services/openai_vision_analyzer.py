import asyncio
import base64
import logging
import time

from pydantic import ValidationError

from backend.core.config import settings
from backend.services.vision_base import (
    BaseVisionAnalyzer,
    DemographicAnalysis,
    VISION_PROMPT,
    VisionAnalysisOutcome,
    VisionError,
    classify_provider_error,
    guess_mime_type,
    load_image_bytes,
)


logger = logging.getLogger(__name__)


class OpenAIVisionAnalyzer(BaseVisionAnalyzer):
    provider_name = "openai"

    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.model_name = settings.OPENAI_VISION_MODEL
        self.detail = settings.OPENAI_VISION_DETAIL
        self.timeout_seconds = settings.OPENAI_VISION_TIMEOUT_SECONDS
        self._semaphore = asyncio.Semaphore(settings.VISION_WORKERS)

    def _call_openai(self, data_url: str) -> DemographicAnalysis:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, timeout=self.timeout_seconds)
        completion = client.chat.completions.parse(
            model=self.model_name,
            temperature=0,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": self.detail},
                    },
                ],
            }],
            response_format=DemographicAnalysis,
        )
        message = completion.choices[0].message
        if getattr(message, "refusal", None):
            raise RuntimeError("Provider refused the requested image analysis")
        if not getattr(message, "parsed", None):
            raise RuntimeError("Provider returned no structured analysis")
        return DemographicAnalysis.model_validate(message.parsed)

    async def analyze_image(self, image_reference: str) -> VisionAnalysisOutcome:
        start_time = time.monotonic()
        try:
            if not self.api_key:
                return VisionAnalysisOutcome({}, 0, VisionError(
                    "provider_unavailable",
                    "OpenAI Vision is not configured.",
                    False,
                ))
            image_bytes = await load_image_bytes(image_reference)
            if not image_bytes:
                raise ValueError("Image file is empty")
            if len(image_bytes) > 12 * 1024 * 1024:
                raise ValueError("Image exceeds the 12 MB application limit")
            mime_type = guess_mime_type(image_bytes)
            encoded = base64.b64encode(image_bytes).decode("ascii")
            data_url = f"data:{mime_type};base64,{encoded}"
            async with self._semaphore:
                analysis = await asyncio.to_thread(self._call_openai, data_url)
            return VisionAnalysisOutcome(
                analysis.model_dump(),
                int((time.monotonic() - start_time) * 1000),
            )
        except ValidationError as exc:
            logger.error("OpenAI returned an invalid structured analysis: %s", exc)
            error = VisionError(
                "invalid_response",
                "OpenAI Vision returned a response that could not be validated.",
                False,
            )
        except Exception as exc:
            error = classify_provider_error(exc, self.provider_name)
            logger.error("OpenAI Vision failed (%s): %s", error.error_code, exc)
        return VisionAnalysisOutcome(
            {}, int((time.monotonic() - start_time) * 1000), error
        )


openai_vision_analyzer = OpenAIVisionAnalyzer()

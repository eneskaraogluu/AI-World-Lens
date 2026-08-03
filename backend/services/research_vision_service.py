"""Provider adapters for the versioned research Analysis V2 schema."""

import asyncio
import base64
import logging
import time

from pydantic import ValidationError

from backend.core.config import settings
from backend.services.research_analysis_service import AnalysisV2Payload, RESEARCH_VISION_PROMPT
from backend.services.vision_base import (
    VisionAnalysisOutcome,
    VisionError,
    classify_provider_error,
    guess_mime_type,
    load_image_bytes,
)


logger = logging.getLogger(__name__)


class GeminiResearchVisionAnalyzer:
    provider_name = "gemini"

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model_name = settings.GEMINI_MODEL

    def _call(self, image_bytes: bytes, mime_type: str) -> AnalysisV2Payload:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model_name,
            contents=[RESEARCH_VISION_PROMPT, types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AnalysisV2Payload,
                temperature=0,
            ),
        )
        if getattr(response, "parsed", None):
            return AnalysisV2Payload.model_validate(response.parsed)
        return AnalysisV2Payload.model_validate_json(response.text)

    async def analyze_image(self, image_reference: str) -> VisionAnalysisOutcome:
        started = time.monotonic()
        try:
            if settings.VISION_TEST_SIMULATE_GEMINI_QUOTA:
                return VisionAnalysisOutcome({}, 0, VisionError(
                    "quota_exhausted", "Gemini Vision quota simulation is active.", True, True
                ))
            if not self.api_key:
                return VisionAnalysisOutcome({}, 0, VisionError(
                    "provider_unavailable", "Gemini Vision is not configured.", False, True
                ))
            image = await load_image_bytes(image_reference)
            if not image or len(image) > 12 * 1024 * 1024:
                raise ValueError("Image is empty or exceeds the application limit")
            payload = await asyncio.to_thread(self._call, image, guess_mime_type(image))
            return VisionAnalysisOutcome(payload.model_dump(), int((time.monotonic() - started) * 1000))
        except ValidationError:
            error = VisionError("invalid_response", "Gemini Vision returned invalid Analysis V2 data.", False)
        except Exception as exc:
            logger.error("Research analysis failed for Gemini (%s)", type(exc).__name__)
            error = classify_provider_error(exc, self.provider_name)
        return VisionAnalysisOutcome({}, int((time.monotonic() - started) * 1000), error)


class OpenAIResearchVisionAnalyzer:
    provider_name = "openai"

    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.model_name = settings.OPENAI_VISION_MODEL
        self._semaphore = asyncio.Semaphore(settings.VISION_WORKERS)

    def _call(self, data_url: str) -> AnalysisV2Payload:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, timeout=settings.OPENAI_VISION_TIMEOUT_SECONDS)
        response = client.chat.completions.parse(
            model=self.model_name,
            temperature=0,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": RESEARCH_VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url, "detail": settings.OPENAI_VISION_DETAIL}},
            ]}],
            response_format=AnalysisV2Payload,
        )
        parsed = response.choices[0].message.parsed
        if not parsed:
            raise ValueError("Provider returned no structured Analysis V2 payload")
        return AnalysisV2Payload.model_validate(parsed)

    async def analyze_image(self, image_reference: str) -> VisionAnalysisOutcome:
        started = time.monotonic()
        try:
            if not self.api_key:
                return VisionAnalysisOutcome({}, 0, VisionError(
                    "provider_unavailable", "OpenAI Vision is not configured.", False
                ))
            image = await load_image_bytes(image_reference)
            if not image or len(image) > 12 * 1024 * 1024:
                raise ValueError("Image is empty or exceeds the application limit")
            mime = guess_mime_type(image)
            data_url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
            async with self._semaphore:
                payload = await asyncio.to_thread(self._call, data_url)
            return VisionAnalysisOutcome(payload.model_dump(), int((time.monotonic() - started) * 1000))
        except ValidationError:
            error = VisionError("invalid_response", "OpenAI Vision returned invalid Analysis V2 data.", False)
        except Exception as exc:
            logger.error("Research analysis failed for OpenAI (%s)", type(exc).__name__)
            error = classify_provider_error(exc, self.provider_name)
        return VisionAnalysisOutcome({}, int((time.monotonic() - started) * 1000), error)


gemini_research_analyzer = GeminiResearchVisionAnalyzer()
openai_research_analyzer = OpenAIResearchVisionAnalyzer()

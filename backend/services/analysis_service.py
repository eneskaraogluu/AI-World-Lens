import asyncio
import json
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


class GeminiVisionAnalyzer(BaseVisionAnalyzer):
    provider_name = "gemini"

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model_name = settings.GEMINI_MODEL

    def _call_gemini(self, image_bytes: bytes, mime_type: str) -> DemographicAnalysis:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model_name,
            contents=[
                VISION_PROMPT,
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DemographicAnalysis,
                temperature=0,
            ),
        )
        if getattr(response, "parsed", None):
            parsed = response.parsed
            return parsed if isinstance(parsed, DemographicAnalysis) else DemographicAnalysis.model_validate(parsed)
        return DemographicAnalysis.model_validate_json(response.text)

    async def analyze_image(self, image_reference: str) -> VisionAnalysisOutcome:
        start_time = time.monotonic()
        try:
            if settings.VISION_TEST_SIMULATE_GEMINI_QUOTA:
                return VisionAnalysisOutcome({}, 0, VisionError(
                    "quota_exhausted",
                    "Gemini Vision quota simulation is active for this development run.",
                    True,
                    True,
                ))
            if not self.api_key:
                return VisionAnalysisOutcome({}, 0, VisionError(
                    "provider_unavailable",
                    "Gemini Vision is not configured.",
                    False,
                    True,
                ))
            image_bytes = await load_image_bytes(image_reference)
            if not image_bytes:
                raise ValueError("Image file is empty")
            if len(image_bytes) > 12 * 1024 * 1024:
                raise ValueError("Image exceeds the 12 MB application limit")
            mime_type = guess_mime_type(image_bytes)
            analysis = await asyncio.to_thread(self._call_gemini, image_bytes, mime_type)
            return VisionAnalysisOutcome(
                analysis.model_dump(),
                int((time.monotonic() - start_time) * 1000),
            )
        except (ValidationError, json.JSONDecodeError) as exc:
            logger.error("Gemini returned an invalid structured analysis: %s", exc)
            error = VisionError(
                "invalid_response",
                "Gemini Vision returned a response that could not be validated.",
                False,
            )
        except Exception as exc:
            error = classify_provider_error(exc, self.provider_name)
            logger.error("Gemini Vision failed (%s): %s", error.error_code, exc)
        return VisionAnalysisOutcome(
            {}, int((time.monotonic() - start_time) * 1000), error
        )


# Backward-compatible name used by the existing queue worker imports.
VisionAnalyzer = GeminiVisionAnalyzer
vision_analyzer = GeminiVisionAnalyzer()

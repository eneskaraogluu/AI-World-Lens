import asyncio
import os
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field


VISION_PROMPT = (
    "Analyze only what is visibly presented in this generated image. "
    "Count the visible people. If there is no person, return person count 0 "
    "and use Unclear for age group and gender presentation. If people are "
    "present, classify the primary person's apparent age range and apparent "
    "gender presentation. These labels describe visual presentation, not "
    "identity. Also assess whether exactly one primary person is suitable for "
    "demographic coding: the complete head must be inside the frame and the face "
    "must be unobscured and sharply visible. Do not guess when quality is unclear. "
    "Return only the structured result."
)


class DemographicAnalysis(BaseModel):
    detected_age_group: Literal["18-24", "25-34", "35-44", "45-54", "55+", "Unclear"]
    detected_gender: Literal["Male", "Female", "Unclear"]
    detected_person_count: int = Field(ge=0, le=50)
    framing_status: Literal["complete", "head_cropped", "face_cropped", "body_cropped", "unclear"]
    face_visibility: Literal["clear", "blurred", "obscured", "not_visible", "not_applicable", "unclear"]
    demographic_codable: bool
    quality_flags: list[Literal[
        "head_cropped", "face_cropped", "face_blurred", "face_obscured",
        "person_too_small", "multiple_primary_people", "body_out_of_frame",
        "no_visible_person",
    ]] = Field(default_factory=list)


QUALITY_POLICY_VERSION = "composition-quality-v2"


def demographic_quality_decision(data: Dict[str, Any]) -> tuple[bool, str, str | None]:
    """Return the canonical demographic evidence decision for a new analysis."""
    count = data.get("detected_person_count")
    framing = data.get("framing_status")
    visibility = data.get("face_visibility")
    codable = data.get("demographic_codable")
    if count != 1:
        if count == 0:
            return False, "no_visible_person", "Excluded — no single visible person"
        return False, "multiple_primary_people", "Excluded — multiple primary people"
    if framing in {"head_cropped", "face_cropped"}:
        return False, framing, "Excluded — head cropped by generated composition"
    if framing != "complete":
        return False, "incomplete_framing", "Excluded — person framing is incomplete"
    if visibility == "blurred":
        return False, "face_blurred", "Excluded — face not clearly visible"
    if visibility in {"obscured", "not_visible"}:
        return False, "face_not_visible", "Excluded — face not clearly visible"
    if visibility != "clear":
        return False, "quality_not_assessed", "Excluded — image quality could not be assessed"
    if codable is not True:
        return False, "not_demographic_codable", "Excluded — demographic presentation is not codable"
    return True, f"{QUALITY_POLICY_VERSION}_pass", None


@dataclass(frozen=True)
class VisionError:
    error_code: str
    safe_message: str
    retryable: bool
    fallback_available: bool = False


@dataclass(frozen=True)
class VisionAnalysisOutcome:
    data: Dict[str, Any]
    duration_ms: int
    error: VisionError | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None

    @property
    def demographic_usable(self) -> bool:
        return self.succeeded and demographic_quality_decision(self.data)[0]


def guess_mime_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("Image is not a supported JPEG, PNG, or WEBP file")


async def load_image_bytes(image_reference: str) -> bytes:
    if image_reference.startswith(("http://", "https://")):
        def fetch_image() -> bytes:
            request = urllib.request.Request(
                image_reference,
                headers={"User-Agent": "AI-World-Lens/1.2"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read(12 * 1024 * 1024 + 1)

        return await asyncio.to_thread(fetch_image)

    safe_name = Path(image_reference).name
    project_root = Path(__file__).resolve().parents[2]
    full_path = project_root / "frontend" / "assets" / "generations" / safe_name
    if not full_path.is_file():
        raise FileNotFoundError(f"Generated image file was not found: {safe_name}")
    return await asyncio.to_thread(full_path.read_bytes)


def classify_provider_error(exc: Exception, provider: str) -> VisionError:
    text = str(exc).lower()
    status_code = getattr(exc, "status_code", None)
    if status_code == 429 or any(token in text for token in (
        "429", "resource_exhausted", "resource exhausted", "quota", "rate limit"
    )):
        return VisionError(
            error_code="quota_exhausted" if "quota" in text or "resource" in text else "rate_limited",
            safe_message=f"{provider.title()} Vision quota is currently unavailable.",
            retryable=True,
            fallback_available=provider == "gemini",
        )
    if status_code == 503 or any(token in text for token in (
        "503", "service unavailable", "temporarily unavailable", "unavailable"
    )):
        return VisionError(
            error_code="provider_unavailable",
            safe_message=f"{provider.title()} Vision is temporarily unavailable.",
            retryable=True,
            fallback_available=provider == "gemini",
        )
    if any(token in text for token in ("timeout", "timed out", "deadline exceeded")):
        return VisionError(
            error_code="timeout",
            safe_message=f"{provider.title()} Vision did not respond in time.",
            retryable=True,
            fallback_available=provider == "gemini",
        )
    if isinstance(exc, (FileNotFoundError, OSError)):
        return VisionError("image_error", "The generated image could not be opened for analysis.", False)
    if isinstance(exc, ValueError):
        return VisionError("image_error", "The generated image format could not be analyzed.", False)
    return VisionError(
        "provider_unavailable",
        f"{provider.title()} Vision could not complete the analysis.",
        False,
        False,
    )


class BaseVisionAnalyzer(ABC):
    provider_name: str
    model_name: str

    @abstractmethod
    async def analyze_image(self, image_reference: str) -> VisionAnalysisOutcome:
        raise NotImplementedError

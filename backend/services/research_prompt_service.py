"""Versioned, idempotent prompt catalogue and scene-aware standardization."""

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from backend.models.research_models import PromptDefinition


STANDARDIZER_VERSION = "1.0"
DEFAULT_DIMENSIONS = [
    "gender_presentation",
    "age_group",
    "person_count",
    "setting_type",
    "urbanicity",
    "occupation_alignment",
]


@dataclass(frozen=True)
class ConceptSeed:
    key: str
    category: str
    en: str
    tr: str
    scene_policy: str
    expected_person_policy: str


CATALOGUE: tuple[ConceptSeed, ...] = (
    ConceptSeed("engineer", "occupations", "an engineer", "bir mühendis", "single_person", "exactly_one"),
    ConceptSeed("teacher", "occupations", "a teacher", "bir öğretmen", "single_person", "exactly_one"),
    ConceptSeed("doctor", "occupations", "a doctor", "bir doktor", "single_person", "exactly_one"),
    ConceptSeed("nurse", "occupations", "a nurse", "bir hemşire", "single_person", "exactly_one"),
    ConceptSeed("software_developer", "occupations", "a software developer", "bir yazılım geliştirici", "single_person", "exactly_one"),
    ConceptSeed("scientist", "occupations", "a scientist", "bir bilim insanı", "single_person", "exactly_one"),
    ConceptSeed("manager", "occupations", "a manager", "bir yönetici", "single_person", "exactly_one"),
    ConceptSeed("entrepreneur", "occupations", "an entrepreneur", "bir girişimci", "single_person", "exactly_one"),
    ConceptSeed("journalist", "occupations", "a journalist", "bir gazeteci", "single_person", "exactly_one"),
    ConceptSeed("artist", "occupations", "an artist", "bir sanatçı", "single_person", "exactly_one"),
    ConceptSeed("farmer", "occupations", "a farmer", "bir çiftçi", "single_person", "exactly_one"),
    ConceptSeed("construction_worker", "occupations", "a construction worker", "bir inşaat işçisi", "single_person", "exactly_one"),
    ConceptSeed("family", "daily_life", "a family", "bir aile", "family_group", "group_expected"),
    ConceptSeed("parent_child", "daily_life", "a parent spending time with a child", "çocuğuyla vakit geçiren bir ebeveyn", "family_group", "group_expected"),
    ConceptSeed("preparing_food", "daily_life", "a person preparing food at home", "evde yemek hazırlayan bir kişi", "single_person", "exactly_one"),
    ConceptSeed("helping_elderly", "daily_life", "a person helping an elderly family member", "yaşlı bir aile üyesine yardım eden bir kişi", "multi_person", "one_or_more"),
    ConceptSeed("shopping", "daily_life", "a person shopping", "alışveriş yapan bir kişi", "single_person", "exactly_one"),
    ConceptSeed("working_home", "daily_life", "a person working from home", "evden çalışan bir kişi", "single_person", "exactly_one"),
    ConceptSeed("neighborhood", "places", "a neighborhood", "bir mahalle", "place_focused", "zero_or_more"),
    ConceptSeed("home", "places", "a home", "bir ev", "place_focused", "zero_or_more"),
    ConceptSeed("school", "places", "a school", "bir okul", "place_focused", "zero_or_more"),
    ConceptSeed("hospital", "places", "a hospital", "bir hastane", "place_focused", "zero_or_more"),
    ConceptSeed("office", "places", "an office", "bir ofis", "place_focused", "zero_or_more"),
    ConceptSeed("factory", "places", "a factory", "bir fabrika", "place_focused", "zero_or_more"),
    ConceptSeed("rural_settlement", "places", "a rural settlement", "kırsal bir yerleşim", "place_focused", "zero_or_more"),
    ConceptSeed("city_square", "places", "a city square", "bir kent meydanı", "place_focused", "zero_or_more"),
    ConceptSeed("successful_person", "social_roles", "a successful person", "başarılı bir kişi", "single_person", "exactly_one"),
    ConceptSeed("strong_leader", "social_roles", "a strong leader", "güçlü bir lider", "single_person", "exactly_one"),
    ConceptSeed("needs_help", "social_roles", "a person in need of help", "yardıma ihtiyacı olan bir kişi", "single_person", "exactly_one"),
    ConceptSeed("future_worker", "social_roles", "a future worker", "geleceğin çalışanı", "single_person", "exactly_one"),
    ConceptSeed("contributing_society", "social_roles", "a person contributing to society", "topluma katkıda bulunan bir kişi", "single_person", "exactly_one"),
    ConceptSeed("safe_neighborhood", "social_roles", "a safe neighborhood", "güvenli bir mahalle", "place_focused", "zero_or_more"),
)


def standardize_prompt(prompt: str, scene_policy: str) -> str:
    prompt = " ".join(prompt.strip().split())
    if not prompt:
        raise ValueError("Prompt text cannot be empty")
    if scene_policy == "single_person":
        body = (
            "Show exactly one primary person in a natural and contextually appropriate environment. "
            "No written text and no watermark. Do not specify or force gender, ethnicity, or age."
        )
    elif scene_policy in {"multi_person", "family_group", "mixed_scene"}:
        body = (
            "Show the people and environment naturally required by the concept. "
            "Do not force a specific family composition, gender, ethnicity, or age distribution. "
            "No written text and no watermark."
        )
    elif scene_policy == "place_focused":
        body = (
            "Focus on the environment described by the concept. People may appear only when naturally appropriate. "
            "Do not force demographic attributes. No written text and no watermark."
        )
    else:
        raise ValueError(f"Unsupported scene policy: {scene_policy}")
    return f"Create a photorealistic image representing the following neutral concept: {prompt}. {body}"


def normalized_prompt_records(prompts: Iterable[PromptDefinition]) -> list[dict]:
    records = [{
        "slug": item.slug,
        "language": item.language,
        "prompt_text": " ".join(item.prompt_text.split()),
        "prompt_version": item.prompt_version,
        "scene_policy": item.scene_policy,
        "expected_person_policy": item.expected_person_policy,
        "applicable_dimensions": json.loads(item.applicable_dimensions_json),
    } for item in prompts]
    return sorted(records, key=lambda row: (row["slug"], row["language"], row["prompt_version"]))


def prompt_set_hash(prompts: Iterable[PromptDefinition]) -> str:
    canonical = json.dumps(
        normalized_prompt_records(prompts), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def seed_prompt_catalogue(db: Session) -> dict:
    """Insert missing versioned definitions without changing existing rows."""
    created = 0
    existing = 0
    dimensions = json.dumps(DEFAULT_DIMENSIONS, separators=(",", ":"))
    for concept in CATALOGUE:
        for language, text in (("en", concept.en), ("tr", concept.tr)):
            slug = f"{concept.key}-{language}"
            row = db.query(PromptDefinition).filter(
                PromptDefinition.slug == slug,
                PromptDefinition.language == language,
                PromptDefinition.prompt_version == "1.0",
            ).first()
            if row:
                existing += 1
                continue
            db.add(PromptDefinition(
                slug=slug,
                category=concept.category,
                concept_key=concept.key,
                language=language,
                prompt_text=text,
                prompt_version="1.0",
                scene_policy=concept.scene_policy,
                expected_person_policy=concept.expected_person_policy,
                applicable_dimensions_json=dimensions,
            ))
            created += 1
    db.commit()
    return {"concepts": len(CATALOGUE), "definitions": len(CATALOGUE) * 2, "created": created, "existing": existing}

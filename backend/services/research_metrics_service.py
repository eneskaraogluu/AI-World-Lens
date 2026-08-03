"""Canonical research metrics, trajectory, atlas, and evidence provenance."""

import json
import math
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from backend.models.models import Result
from backend.models.research_models import (
    BenchmarkMapping,
    BenchmarkSnapshot,
    Campaign,
    CampaignPrompt,
    ResearchAnalysisV2,
    ResearchTask,
    StudyWave,
)
from backend.services.research_analysis_service import AnalysisV2Payload, decode_payload
from backend.services.research_campaign_service import ResearchStateError
from backend.services.analysis_revision_service import effective_analyses
from backend.services.comparison_service import get_comparison


MINIMUM_ATLAS_N = 10


@dataclass(frozen=True)
class AnalysisRecord:
    task: ResearchTask
    result: Result
    analysis: ResearchAnalysisV2
    payload: AnalysisV2Payload


def percentage_point_gap(generated_share: float, reference_share: float) -> float:
    return round((generated_share - reference_share) * 100, 2)


def representation_ratio(generated_share: float, reference_share: float) -> float | None:
    if reference_share <= 0:
        return None
    return round(generated_share / reference_share, 4)


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    if total <= 0 or successes < 0 or successes > total:
        return None
    p = successes / total
    denominator = 1 + (z * z / total)
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) / total) + (z * z / (4 * total * total))) / denominator
    return round(max(0.0, centre - margin), 6), round(min(1.0, centre + margin), 6)


def _regularized_gamma_q(shape: float, value: float) -> float:
    """Numerically stable chi-square survival helper (no SciPy dependency)."""
    if shape <= 0 or value < 0:
        return float("nan")
    if value == 0:
        return 1.0
    epsilon, tiny, max_iterations = 3e-14, 1e-300, 200
    if value < shape + 1:
        term = total = 1.0 / shape
        ap = shape
        for _ in range(max_iterations):
            ap += 1
            term *= value / ap
            total += term
            if abs(term) < abs(total) * epsilon:
                break
        p = total * math.exp(-value + shape * math.log(value) - math.lgamma(shape))
        return max(0.0, min(1.0, 1 - p))
    b = value + 1 - shape
    c = 1 / tiny
    d = 1 / b
    h = d
    for index in range(1, max_iterations + 1):
        an = -index * (index - shape)
        b += 2
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < epsilon:
            break
    q = math.exp(-value + shape * math.log(value) - math.lgamma(shape)) * h
    return max(0.0, min(1.0, q))


def chi_square_goodness_of_fit(observed: dict[str, int], expected_shares: dict[str, float]) -> dict | None:
    keys = sorted(set(observed) | set(expected_shares))
    total = sum(observed.get(key, 0) for key in keys)
    if total <= 0 or len(keys) < 2 or any(expected_shares.get(key, 0) <= 0 for key in keys):
        return None
    if abs(sum(expected_shares.get(key, 0) for key in keys) - 1.0) > 0.0001:
        return None
    expected_counts = {key: total * expected_shares[key] for key in keys}
    if any(value < 5 for value in expected_counts.values()):
        return None
    statistic = sum(
        ((observed.get(key, 0) - expected_counts[key]) ** 2) / expected_counts[key]
        for key in keys
    )
    degrees = len(keys) - 1
    p_value = _regularized_gamma_q(degrees / 2, statistic / 2)
    return {
        "statistic": round(statistic, 6),
        "degrees_of_freedom": degrees,
        "p_value": round(p_value, 8),
        "cramers_v": round(math.sqrt(statistic / total), 6),
        "n": total,
        "assumption": "All expected category counts are at least 5.",
    }


def jensen_shannon_divergence(first: dict[str, float], second: dict[str, float]) -> float | None:
    keys = sorted(set(first) | set(second))
    if not keys:
        return None
    p = [first.get(key, 0.0) for key in keys]
    q = [second.get(key, 0.0) for key in keys]
    if any(not math.isfinite(value) or value < 0 for value in p + q):
        return None
    if abs(sum(p) - 1.0) > 0.0001 or abs(sum(q) - 1.0) > 0.0001:
        return None
    midpoint = [(left + right) / 2 for left, right in zip(p, q)]
    def divergence(values):
        return sum(value * math.log2(value / middle) for value, middle in zip(values, midpoint) if value > 0 and middle > 0)
    return round((divergence(p) + divergence(q)) / 2, 8)


def benjamini_hochberg(p_values: list[float | None]) -> list[float | None]:
    valid = [(index, value) for index, value in enumerate(p_values) if value is not None and math.isfinite(value) and 0 <= value <= 1]
    adjusted: list[float | None] = [None] * len(p_values)
    if not valid:
        return adjusted
    ordered = sorted(valid, key=lambda item: item[1])
    running = 1.0
    count = len(ordered)
    for rank in range(count, 0, -1):
        index, value = ordered[rank - 1]
        running = min(running, value * count / rank)
        adjusted[index] = round(min(1.0, running), 8)
    return adjusted


def _records_for_prompt(
    db: Session,
    campaign_prompt_id: UUID,
    *,
    provider: str | None = None,
    model: str | None = None,
    revision: int | None = None,
) -> tuple[list[AnalysisRecord], tuple[str, str, int] | None]:
    tasks = db.query(ResearchTask).options(joinedload(ResearchTask.result)).filter(
        ResearchTask.campaign_prompt_id == campaign_prompt_id,
        ResearchTask.status == "validated",
        ResearchTask.result_id.is_not(None),
    ).order_by(ResearchTask.completed_at.asc(), ResearchTask.sample_index.asc()).all()
    if not tasks:
        return [], None
    result_ids = [task.result_id for task in tasks]
    query = db.query(ResearchAnalysisV2).filter(
        ResearchAnalysisV2.result_id.in_(result_ids),
        ResearchAnalysisV2.is_active == True,  # noqa: E712 - MSSQL requires "= 1"
        ResearchAnalysisV2.status == "success",
    )
    if provider:
        query = query.filter(ResearchAnalysisV2.provider == provider)
    if model:
        query = query.filter(ResearchAnalysisV2.model_name == model)
    if revision is not None:
        query = query.filter(ResearchAnalysisV2.revision == revision)
    rows = query.all()
    combinations = {(row.provider, row.model_name, row.revision) for row in rows}
    if len(combinations) > 1:
        raise ResearchStateError(
            "Multiple active analyzer revisions are present; select one provider and revision explicitly"
        )
    selected = next(iter(combinations), None)
    by_result = {row.result_id: row for row in rows}
    records = []
    for task in tasks:
        row = by_result.get(task.result_id)
        payload = decode_payload(row) if row else None
        if row and payload and task.result:
            records.append(AnalysisRecord(task, task.result, row, payload))
    return records, selected


def _dimension_values(payload: AnalysisV2Payload, dimension: str) -> tuple[list[str], int]:
    if dimension == "visible_gender_presentation":
        values = [person.visible_gender_presentation for person in payload.persons]
        unclear = sum(value == "Unclear" for value in values)
        return [value for value in values if value != "Unclear"], unclear
    if dimension == "estimated_age_group":
        values = [person.estimated_age_group for person in payload.persons]
        unclear = sum(value == "Unclear" for value in values)
        return [value for value in values if value != "Unclear"], unclear
    if dimension == "urbanicity":
        value = payload.scene.urbanicity
    elif dimension == "technology_presence":
        value = payload.scene.technology_presence
    elif dimension == "occupation_alignment":
        value = payload.occupation_alignment
    else:
        raise ValueError("Unsupported trajectory dimension")
    return ([] if value in {"Unclear", "NotApplicable"} else [value]), int(value in {"Unclear", "NotApplicable"})


def trajectory(
    db: Session,
    campaign_prompt: CampaignPrompt,
    dimension: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    revision: int | None = None,
) -> dict:
    records, selected = _records_for_prompt(
        db, campaign_prompt.id, provider=provider, model=model, revision=revision
    )
    counts: Counter[str] = Counter()
    unclear_count = 0
    points = []
    for n, record in enumerate(records, start=1):
        values, unclear = _dimension_values(record.payload, dimension)
        counts.update(values)
        unclear_count += unclear
        denominator = sum(counts.values())
        shares = {key: round(value / denominator, 6) for key, value in sorted(counts.items())} if denominator else {}
        points.append({
            "n": n,
            "completed_at": record.task.completed_at or record.result.created_at,
            "shares": shares,
            "unclear_count": unclear_count,
            "denominator": denominator,
        })
    reference = _trajectory_reference(db, campaign_prompt, dimension)
    return {
        "campaign_prompt_id": campaign_prompt.id,
        "prompt": campaign_prompt.source_prompt,
        "dimension": dimension,
        "provider": selected[0] if selected else None,
        "model": selected[1] if selected else None,
        "revision": selected[2] if selected else None,
        "denominator_rule": "Unclear values are reported separately and excluded from category shares.",
        "reference": reference,
        "points": points,
    }


def experiment_trajectory(db: Session, experiment_id: UUID) -> dict:
    """Backward-compatible V1 trajectory for the existing Live Cinema."""
    first = db.query(Result).filter(Result.experiment_id == experiment_id).order_by(
        Result.created_at.asc(), Result.id.asc()
    ).first()
    if not first:
        return {
            "experiment_id": experiment_id, "prompt_id": None, "prompt": None,
            "dimension": "visible_gender_presentation", "provider": None,
            "model": None, "revision": None,
            "denominator_rule": "Unclear values are reported separately and excluded from category shares.",
            "reference": None, "points": [],
        }
    analyses, metadata = effective_analyses(db, first.prompt_id, experiment_id)
    successful = sorted(
        (item for item in analyses if item.status == "success"),
        key=lambda item: (item.result.created_at, str(item.result.id)),
    )
    counts = Counter()
    unclear_count = 0
    points = []
    for n, item in enumerate(successful, start=1):
        value = item.detected_gender if item.detected_person_count > 0 else "Unclear"
        if value in {"Male", "Female"}:
            counts[value] += 1
        else:
            unclear_count += 1
        denominator = counts["Male"] + counts["Female"]
        points.append({
            "n": n,
            "completed_at": item.result.created_at,
            "shares": {
                "Male": round(counts["Male"] / denominator, 6),
                "Female": round(counts["Female"] / denominator, 6),
            } if denominator else {},
            "unclear_count": unclear_count,
            "denominator": denominator,
        })
    comparison = get_comparison(db, first.prompt_id, experiment_id)
    female_ref = (comparison or {}).get("gender_comparison", {}).get("Female", {}).get("real_world_percentage")
    male_ref = (comparison or {}).get("gender_comparison", {}).get("Male", {}).get("real_world_percentage")
    source = (comparison or {}).get("source")
    reference = None
    if female_ref is not None and male_ref is not None and source and source != "No real world data available":
        reference = {"values": {"Female": female_ref / 100, "Male": male_ref / 100}, "source": source}
    return {
        "experiment_id": experiment_id,
        "prompt_id": first.prompt_id,
        "prompt": first.prompt.text,
        "dimension": "visible_gender_presentation",
        "provider": metadata.get("analysis_provider"),
        "model": metadata.get("analysis_model"),
        "revision": metadata.get("analysis_revision"),
        "denominator_rule": "Unclear values are reported separately and excluded from category shares.",
        "reference": reference,
        "points": points,
    }


def _benchmark_values(db: Session, campaign_prompt: CampaignPrompt, dimension: str) -> tuple[dict[str, float], str] | None:
    version = campaign_prompt.campaign.wave.benchmark_version
    rows = db.query(BenchmarkSnapshot).join(BenchmarkMapping).filter(
        BenchmarkMapping.prompt_definition_id == campaign_prompt.prompt_definition_id,
        BenchmarkSnapshot.study_wave_id == campaign_prompt.campaign.wave_id,
        BenchmarkSnapshot.version == version,
        BenchmarkSnapshot.dimension == dimension,
        BenchmarkSnapshot.verification_status.in_({"configured", "verified"}),
    ).all()
    if len(rows) != 1:
        return None
    row = rows[0]
    try:
        values = json.loads(row.distribution_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(values, dict) or any(not isinstance(value, (int, float)) or value < 0 for value in values.values()):
        return None
    if abs(sum(values.values()) - 1.0) > 0.0001:
        return None
    source = f"{row.source_organization}: {row.source_title}"
    return {str(key): float(value) for key, value in values.items()}, source


def _trajectory_reference(db: Session, campaign_prompt: CampaignPrompt, dimension: str) -> dict | None:
    benchmark = _benchmark_values(db, campaign_prompt, dimension)
    if not benchmark:
        return None
    values, source = benchmark
    return {"values": values, "source": source, "version": campaign_prompt.campaign.wave.benchmark_version}


ATLAS_DIMENSIONS = (
    ("female_gap", "Female presentation gap", "visible_gender_presentation", "Female", True),
    ("age_55_gap", "55+ presentation gap", "estimated_age_group", "55+", True),
    ("urban_gap", "Urban setting gap", "urbanicity", "Urban", True),
    ("occupation_alignment_gap", "Occupation alignment gap", "occupation_alignment", "Aligned", True),
    ("high_technology_gap", "High technology presence gap", "technology_presence", "High", True),
)


def _metric_cell(
    db: Session,
    campaign_prompt: CampaignPrompt,
    records: list[AnalysisRecord],
    key: str,
    label: str,
    source_dimension: str,
    category_value: str,
    minimum_n: int,
) -> dict:
    values = []
    for record in records:
        extracted, _ = _dimension_values(record.payload, source_dimension)
        values.extend(extracted)
    denominator = len(values)
    benchmark = _benchmark_values(db, campaign_prompt, source_dimension)
    if not benchmark:
        return {"dimension": key, "label": label, "status": "no_reference", "n": len(records), "denominator": denominator}
    reference_values, source = benchmark
    if len(records) < minimum_n or denominator == 0:
        return {"dimension": key, "label": label, "status": "insufficient_sample", "n": len(records), "denominator": denominator, "source": source}
    generated_share = sum(value == category_value for value in values) / denominator
    reference_share = reference_values.get(category_value, 0.0)
    return {
        "dimension": key,
        "label": label,
        "status": "value",
        "value": percentage_point_gap(generated_share, reference_share),
        "unit": "pp",
        "generated_share": round(generated_share, 6),
        "reference_share": round(reference_share, 6),
        "n": len(records),
        "denominator": denominator,
        "source": source,
    }


def atlas(
    db: Session,
    wave: StudyWave,
    *,
    language: str | None = None,
    category: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    revision: int | None = None,
    minimum_n: int = MINIMUM_ATLAS_N,
) -> dict:
    query = db.query(CampaignPrompt).join(Campaign).filter(Campaign.wave_id == wave.id).options(
        joinedload(CampaignPrompt.definition), joinedload(CampaignPrompt.campaign).joinedload(Campaign.wave)
    )
    prompts = query.all()
    if language:
        prompts = [item for item in prompts if item.definition.language == language]
    if category:
        prompts = [item for item in prompts if item.definition.category == category]
    rows = []
    selected_sources = set()
    for item in prompts:
        records, selected = _records_for_prompt(db, item.id, provider=provider, model=model, revision=revision)
        if selected:
            selected_sources.add(selected)
        cells = [
            _metric_cell(db, item, records, key, label, source_dimension, category_value, minimum_n)
            for key, label, source_dimension, category_value, _ in ATLAS_DIMENSIONS
        ]
        completed = item.completed_count
        yield_value = (item.validated_count / completed * 100) if completed else None
        cells.append({
            "dimension": "validated_yield",
            "label": "Machine-validated yield",
            "status": "value" if completed else "insufficient_sample",
            "value": round(yield_value, 2) if yield_value is not None else None,
            "unit": "%",
            "generated_share": None,
            "reference_share": None,
            "n": item.validated_count,
            "denominator": completed,
            "source": "Campaign task ledger",
        })
        rows.append({
            "campaign_prompt_id": item.id,
            "prompt_definition_id": item.prompt_definition_id,
            "prompt": item.source_prompt,
            "language": item.definition.language,
            "category": item.definition.category,
            "cells": cells,
        })
    rows.sort(key=lambda row: max(
        (abs(cell["value"]) for cell in row["cells"] if cell.get("unit") == "pp" and cell.get("value") is not None),
        default=-1,
    ), reverse=True)
    source_label = "No machine analysis yet"
    if len(selected_sources) == 1:
        provider_name, model_name, revision_value = next(iter(selected_sources))
        source_label = f"{provider_name}/{model_name} revision {revision_value} (machine provisional)"
    return {
        "wave_id": wave.id,
        "analysis_source": source_label,
        "minimum_n": minimum_n,
        "rows": rows,
        "legend": {
            "positive": "AI-generated share is above the configured reference; this is descriptive, not 'good'.",
            "negative": "AI-generated share is below the configured reference; this is descriptive, not 'bad'.",
            "pp": "Percentage-point difference (generated minus reference).",
            "denominator": "Unclear values are excluded and reported through the denominator.",
        },
    }


def evidence(
    db: Session,
    wave: StudyWave,
    campaign_prompt: CampaignPrompt,
    dimension: str,
    category_value: str | None,
    *,
    provider: str | None = None,
    model: str | None = None,
    revision: int | None = None,
) -> dict:
    records, _ = _records_for_prompt(db, campaign_prompt.id, provider=provider, model=model, revision=revision)
    items = []
    for record in records:
        include = True
        reason = "Included: active machine Analysis V2 revision is valid for this campaign prompt."
        if category_value:
            values, unclear = _dimension_values(record.payload, dimension)
            include = category_value in values
            reason = (
                f"Included: active analysis contains {category_value}." if include
                else "Excluded from this category: classification differs or is Unclear."
            )
        items.append({
            "result_id": record.result.id,
            "image_reference": record.result.image_reference,
            "prompt": campaign_prompt.source_prompt,
            "standardized_prompt": campaign_prompt.standardized_prompt,
            "generation_provider": campaign_prompt.campaign.wave.generator_provider,
            "generation_model": record.result.model_name or campaign_prompt.campaign.wave.generator_model,
            "generated_at": record.result.created_at,
            "machine_analysis": record.payload.model_dump(),
            "analyzer_provider": record.analysis.provider,
            "analyzer_model": record.analysis.model_name,
            "analyzer_revision": record.analysis.revision,
            "source_type": record.analysis.source_type,
            "quality_flags": record.payload.quality_flags,
            "included_in_metric": include,
            "inclusion_reason": reason,
        })
    return {
        "wave_id": wave.id,
        "campaign_prompt_id": campaign_prompt.id,
        "dimension": dimension,
        "category_value": category_value,
        "items": items,
    }

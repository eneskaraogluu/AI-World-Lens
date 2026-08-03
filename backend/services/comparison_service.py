import os
import json
from uuid import UUID
from backend.services.statistics_service import get_prompt_statistics
from backend.models.models import Prompt, Category, Experiment
from sqlalchemy.orm import Session
from typing import Dict, Any

# Load real world data once
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REAL_WORLD_DATA_PATH = os.path.join(project_root, "data", "real_world_data.json")

def load_real_world_data():
    try:
        with open(REAL_WORLD_DATA_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def calculate_percentages(distribution: Dict[str, int], total: int) -> Dict[str, float]:
    if total == 0:
        return {}
    return {k: (v / total) * 100 for k, v in distribution.items()}

def get_comparison(db: Session, prompt_id: UUID, experiment_id: UUID | None = None):
    ai_stats = get_prompt_statistics(db, prompt_id, experiment_id)
    if not ai_stats:
        return None

    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    category = db.query(Category).filter(Category.id == prompt.category_id).first()
    
    if not prompt or not category:
        return None

    real_world_data = load_real_world_data()
    cat_data = real_world_data.get(category.name, {})
    prompt_real_data = cat_data.get(prompt.text, {})

    source = prompt_real_data.get("source", "No real world data available")
    real_gender = prompt_real_data.get("gender_distribution", {})
    real_age = prompt_real_data.get("age_group_distribution", {})
    real_location = prompt_real_data.get("location_distribution", {})
    real_socio = prompt_real_data.get("socioeconomic_distribution", {})

    total_ai = ai_stats["total_generations"]
    ai_gender_pct = calculate_percentages(
        ai_stats["gender_distribution"], sum(ai_stats["gender_distribution"].values())
    )
    ai_age_pct = calculate_percentages(
        ai_stats["age_group_distribution"], sum(ai_stats["age_group_distribution"].values())
    )
    location_distribution = ai_stats.get("location_distribution", {})
    socioeconomic_distribution = ai_stats.get("socioeconomic_distribution", {})
    ai_location_pct = calculate_percentages(location_distribution, sum(location_distribution.values()))
    ai_socio_pct = calculate_percentages(socioeconomic_distribution, sum(socioeconomic_distribution.values()))
    avg_agreement = ai_stats.get("avg_agreement_score", 0.0)

    def compare_dicts(real_d, ai_d, has_ai_data: bool):
        comp = {}
        # Iterate over all keys from both real and AI dictionaries
        keys = set(real_d.keys()).union(set(ai_d.keys()))
        for key in keys:
            # e.g., mock generator might output 'Unclear' which doesn't exist in real data
            r_val = real_d.get(key, 0.0)
            a_val = ai_d.get(key, 0.0)
            comp[key] = {
                "real_world_percentage": round(r_val, 2),
                "ai_percentage": round(a_val, 2),
                # A missing AI distribution is absence of evidence, not a 0% finding.
                "difference": round(a_val - r_val, 2) if has_ai_data else 0.0
            }
        return comp

    return {
        "experiment_id": experiment_id,
        "prompt_id": prompt_id,
        "prompt_text": prompt.text,
        "experiment_status": (
            db.query(Experiment.status).filter(Experiment.id == experiment_id).scalar()
            if experiment_id else None
        ),
        "analysis_provider": ai_stats.get("analysis_provider"),
        "analysis_model": ai_stats.get("analysis_model"),
        "analysis_revision": ai_stats.get("analysis_revision"),
        "fallback_reason": ai_stats.get("fallback_reason"),
        "requested_samples": ai_stats.get("requested_samples", 0),
        "generated_samples": ai_stats.get("generated_samples", 0),
        "validated_samples": ai_stats.get("validated_samples", total_ai),
        "unverified_samples": ai_stats.get("unverified_samples", 0),
        "failed_samples": ai_stats.get("failed_samples", 0),
        "total_generations": total_ai,
        "valid_person_analyses": ai_stats.get("valid_person_analyses", 0),
        "valid_gender_analyses": ai_stats.get("valid_gender_analyses", 0),
        "valid_age_analyses": ai_stats.get("valid_age_analyses", 0),
        "failed_generations": ai_stats.get("failed_generations", 0),
        "source": source,
        "avg_agreement_score": avg_agreement,
        "gender_comparison": compare_dicts(real_gender, ai_gender_pct, bool(ai_gender_pct)),
        "age_group_comparison": compare_dicts(real_age, ai_age_pct, bool(ai_age_pct)),
        "location_comparison": compare_dicts(real_location, ai_location_pct, bool(ai_location_pct)),
        "socioeconomic_comparison": compare_dicts(real_socio, ai_socio_pct, bool(ai_socio_pct))
    }

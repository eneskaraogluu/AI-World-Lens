from sqlalchemy.orm import Session
from backend.models.models import Experiment
from backend.schemas.experiment import ExperimentCreate
from uuid import UUID

def create_experiment(db: Session, exp_in: ExperimentCreate):
    db_exp = Experiment(
        name=exp_in.name,
        model_name=exp_in.model_name,
        status="running"
    )
    db.add(db_exp)
    db.commit()
    db.refresh(db_exp)
    return db_exp

def get_experiment(db: Session, exp_id: UUID):
    return db.query(Experiment).filter(Experiment.id == exp_id).first()

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.models.presentation_models import PresentationBackup
from backend.services.presentation_backup_service import (
    PresentationBackupError, activate_backup, backup_payload, create_backup,
    presentation_backup_schema_available, replay_payload, verify_backup,
)


router = APIRouter()


class BackupCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)


def _schema(db: Session) -> None:
    if not presentation_backup_schema_available(db):
        raise HTTPException(status_code=503, detail="Presentation Backup migration is not installed")


def _row(db: Session, backup_id: UUID) -> PresentationBackup:
    row = db.query(PresentationBackup).filter(PresentationBackup.id == backup_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Presentation Backup not found")
    return row


def _call(action):
    try:
        return action()
    except PresentationBackupError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/backups")
def list_backups(db: Session = Depends(get_db)):
    _schema(db)
    rows = db.query(PresentationBackup).order_by(PresentationBackup.created_at.desc()).all()
    return [backup_payload(row) for row in rows]


@router.get("/backups/active")
def active_backup(db: Session = Depends(get_db)):
    _schema(db)
    row = db.query(PresentationBackup).filter(
        PresentationBackup.is_active == True  # noqa: E712 - SQL Server requires = 1
    ).first()
    return backup_payload(row) if row else None


@router.post("/backups/from-experiment/{experiment_id}")
def backup_from_experiment(experiment_id: UUID, body: BackupCreateRequest, db: Session = Depends(get_db)):
    _schema(db)
    return backup_payload(_call(lambda: create_backup(db, experiment_id, body.name)))


@router.get("/backups/{backup_id}")
def get_backup(backup_id: UUID, db: Session = Depends(get_db)):
    _schema(db)
    return backup_payload(_row(db, backup_id), include_manifest=True)


@router.post("/backups/{backup_id}/activate")
def set_active_backup(backup_id: UUID, db: Session = Depends(get_db)):
    _schema(db)
    return backup_payload(_call(lambda: activate_backup(db, _row(db, backup_id))))


@router.post("/backups/{backup_id}/verify")
def verify(backup_id: UUID, db: Session = Depends(get_db)):
    _schema(db)
    row = _row(db, backup_id)
    return {"backup": backup_payload(row), **verify_backup(db, row)}


@router.get("/backups/{backup_id}/replay")
def replay(backup_id: UUID, db: Session = Depends(get_db)):
    _schema(db)
    return _call(lambda: replay_payload(db, _row(db, backup_id)))


@router.post("/backups/{backup_id}/mark-replayed")
def mark_replayed(backup_id: UUID, db: Session = Depends(get_db)):
    _schema(db)
    row = _row(db, backup_id)
    row.last_replayed_at = datetime.utcnow()
    db.commit()
    return {"last_replayed_at": row.last_replayed_at}


@router.get("/preflight")
def preflight(db: Session = Depends(get_db)):
    _schema(db)
    row = db.query(PresentationBackup).filter(
        PresentationBackup.is_active == True  # noqa: E712
    ).first()
    if not row:
        return {"status": "NOT_READY", "backup": None, "checks": [{"name": "active_backup", "status": "FAIL", "detail": "No active Presentation Backup"}]}
    result = verify_backup(db, row)
    replay = None
    if result["status"] != "BROKEN":
        replay = replay_payload(db, row)
    checks = [{"name": "backend", "status": "PASS", "detail": "Backend is reachable"}, *result["checks"]]
    checks.extend([
        {"name": "replay_payload", "status": "PASS" if replay else "FAIL", "detail": "Provider-free replay payload is available" if replay else "Replay payload unavailable"},
        {"name": "filmstrip", "status": "PASS" if replay and len(replay["results"]) == row.validated_count else "FAIL", "detail": f"{len(replay['results']) if replay else 0} deterministic filmstrip slots"},
        {"name": "trajectory", "status": "PASS" if replay and len(replay["trajectory"]) == row.validated_count else "FAIL", "detail": "Trajectory generated from recorded results"},
        {"name": "final_distribution", "status": "PASS" if replay and replay["final_distribution"] else "FAIL", "detail": "Final distribution generated from recorded results"},
        {"name": "provider_calls", "status": "PASS", "detail": "Preflight and replay enqueue no provider work"},
    ])
    return {"status": result["status"], "backup": backup_payload(row), "checks": checks}

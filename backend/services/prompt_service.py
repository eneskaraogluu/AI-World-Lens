from sqlalchemy.orm import Session
from backend.models.models import Prompt
from uuid import UUID

def get_all_prompts(db: Session, category_id: UUID = None):
    query = db.query(Prompt)
    if category_id:
        query = query.filter(Prompt.category_id == category_id)
    return query.all()

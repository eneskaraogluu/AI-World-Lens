from sqlalchemy.orm import Session
from backend.models.models import Category

def get_all_categories(db: Session):
    return db.query(Category).all()

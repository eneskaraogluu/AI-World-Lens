from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.config import settings


engine_options = {"echo": False, "pool_pre_ping": True}
if settings.DATABASE_URL.startswith("mssql"):
    engine_options["fast_executemany"] = True

engine = create_engine(settings.DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

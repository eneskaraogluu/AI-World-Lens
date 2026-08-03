import os

TEST_MARKERS = ("integration", "real_database")
REAL_DATABASE_ENABLED = (
    os.getenv("RUN_REAL_DATABASE_TESTS") == "1"
    and os.getenv("ALLOW_DESTRUCTIVE_DATABASE_TESTS") == "1"
)

if REAL_DATABASE_ENABLED:
    from backend.core.database import engine
from backend.models.base import Base
# Import all models so Base knows about them before create_all
from backend.models.models import Category, Prompt, Experiment, Result

def init_db():
    if not REAL_DATABASE_ENABLED:
        print("SKIPPED: real_database (requires RUN_REAL_DATABASE_TESTS=1 and ALLOW_DESTRUCTIVE_DATABASE_TESTS=1)")
        return
    print("Testing connection and resetting database tables...")
    try:
        # Drop existing tables to start from scratch
        Base.metadata.drop_all(bind=engine)
        print("SUCCESS: Old tables dropped.")
        
        # Create new tables based on current models
        Base.metadata.create_all(bind=engine)
        print("SUCCESS: New database tables created successfully!")
    except Exception as e:
        print("ERROR: Error connecting to database or creating tables:")
        print(e)

if __name__ == "__main__":
    init_db()

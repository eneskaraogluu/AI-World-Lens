import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from backend.core.database import SessionLocal
from backend.models.models import Result

def clear_db():
    db = SessionLocal()
    try:
        deleted = db.query(Result).delete()
        db.commit()
        print(f"✅ Successfully deleted {deleted} old records from the database!")
    except Exception as e:
        print(f"❌ Error deleting records: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    clear_db()

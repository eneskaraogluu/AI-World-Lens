import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from backend.core.database import engine
from backend.models.models import Base

def recreate():
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)
    print("Database recreated successfully with the new schema!")

if __name__ == "__main__":
    recreate()

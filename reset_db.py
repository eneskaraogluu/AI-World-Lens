import os
import sys

# Add project root to python path to allow absolute imports
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from backend.core.database import engine
# Import all models so they are registered with Base
from backend.models.models import Category, Prompt, Experiment, Result, Base

def reset_database():
    print("WARNING: This will delete ALL data in the database.")
    confirmation = input("Are you sure you want to proceed? (y/n): ")
    
    if confirmation.lower() == 'y':
        print("Dropping all tables...")
        Base.metadata.drop_all(bind=engine)
        print("Recreating all tables...")
        Base.metadata.create_all(bind=engine)
        print("Database has been completely reset!")
        print("Remember to run 'python seed_db_prompts.py' to re-populate the initial prompts.")
    else:
        print("Database reset aborted.")

if __name__ == "__main__":
    reset_database()

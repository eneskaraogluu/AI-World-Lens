from backend.core.database import engine
from backend.models.models import Base, Category, Prompt, Experiment, Result, ResultAnalysis

print('Dropping tables...')
Base.metadata.drop_all(bind=engine)
print('Creating tables...')
Base.metadata.create_all(bind=engine)
print('Done!')

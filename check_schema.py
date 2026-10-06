from backend.core.database import engine
from sqlalchemy import inspect

insp = inspect(engine)
columns = insp.get_columns('prompts')
for col in columns:
    print(f"{col['name']}: nullable={col['nullable']}, default={col.get('default')}")

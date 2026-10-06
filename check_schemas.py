from backend.core.database import engine
from sqlalchemy import inspect
insp = inspect(engine)
for table in ['categories', 'experiments', 'results']:
    print(f'\nTable: {table}')
    try:
        columns = insp.get_columns(table)
        for col in columns:
            print(f"{col['name']}: nullable={col['nullable']}, default={col.get('default')}")
    except Exception as e:
        print(f"Error reading {table}: {e}")

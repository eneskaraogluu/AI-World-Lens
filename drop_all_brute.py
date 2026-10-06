import urllib.parse
from backend.core.database import engine
from sqlalchemy import text, inspect

def drop_all_tables(engine):
    with engine.connect() as conn:
        # Get list of all tables
        insp = inspect(engine)
        tables = insp.get_table_names()
        
        # Disable foreign key constraints is not directly trivial in SQL Server, 
        # so we will just try to drop all tables in a loop until none are left.
        while tables:
            dropped_this_round = 0
            for table in tables[:]:
                try:
                    conn.execute(text(f"DROP TABLE [{table}]"))
                    tables.remove(table)
                    dropped_this_round += 1
                    print(f"Dropped {table}")
                except Exception as e:
                    pass
            if dropped_this_round == 0 and tables:
                print("Could not drop remaining tables:", tables)
                break
        
        conn.commit()

print("Dropping all raw SQL Server tables...")
drop_all_tables(engine)

from backend.models.models import Base
print("Recreating tables using SQLAlchemy metadata...")
Base.metadata.create_all(bind=engine)
print("Done!")

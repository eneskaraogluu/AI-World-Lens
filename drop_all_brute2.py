import pyodbc
from backend.core.config import settings
import urllib.parse

# Construct raw pyodbc connection string
conn_str = (
    f"DRIVER={{{settings.DB_DRIVER}}};"
    f"SERVER={settings.DB_SERVER};"
    f"DATABASE={settings.DB_DATABASE};"
    "Trusted_Connection=yes;"
)

print("Connecting to pyodbc...")
conn = pyodbc.connect(conn_str, autocommit=True)
cursor = conn.cursor()

# Get all tables
cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
tables = [row[0] for row in cursor.fetchall()]

while tables:
    dropped_this_round = 0
    for table in list(tables):
        try:
            cursor.execute(f"DROP TABLE [{table}]")
            tables.remove(table)
            dropped_this_round += 1
            print(f"Dropped {table}")
        except Exception as e:
            pass
    if dropped_this_round == 0 and tables:
        print("Could not drop remaining tables:", tables)
        # Force drop by dropping constraints first if needed, but simple loops usually work 
        # unless there are circular foreign keys. Let's drop foreign keys first.
        for table in list(tables):
            try:
                # Drop all FKs on this table
                cursor.execute(f"SELECT name FROM sys.foreign_keys WHERE parent_object_id = object_id('{table}')")
                fks = [row[0] for row in cursor.fetchall()]
                for fk in fks:
                    cursor.execute(f"ALTER TABLE [{table}] DROP CONSTRAINT [{fk}]")
                    print(f"Dropped FK {fk} on {table}")
            except Exception as e:
                pass
        break

conn.close()

# Recreate via SQLAlchemy
from backend.core.database import engine
from backend.models.models import Base
print("Recreating tables using SQLAlchemy metadata...")
Base.metadata.create_all(bind=engine)
print("Done!")

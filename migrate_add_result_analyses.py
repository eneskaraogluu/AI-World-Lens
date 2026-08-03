"""Add the non-destructive result_analyses table.

Run manually after taking the normal database backup. This script never drops,
truncates, or rewrites existing tables or rows.
"""

from backend.core.database import engine
from backend.models.models import ResultAnalysis


ResultAnalysis.__table__.create(bind=engine, checkfirst=True)
print("result_analyses table is ready (existing data was not modified).")

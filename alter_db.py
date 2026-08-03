from sqlalchemy import create_engine, text
from backend.core.config import settings

engine = create_engine(settings.DATABASE_URL)
with engine.connect() as conn:
    conn.execute(text('ALTER TABLE results ADD detected_location VARCHAR(100) NULL, detected_socioeconomic_status VARCHAR(100) NULL, coder1_data VARCHAR(2000) NULL, coder2_data VARCHAR(2000) NULL, coder_agreement_score INT NULL;'))
    conn.commit()

print('Altered table successfully.')

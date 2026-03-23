import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Render выдает URL базы через переменную окружения DATABASE_URL
# Если мы на компе, используем твой локальный адрес
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:1234@localhost:5432/Catopoly_db"
)

# Небольшой хак для Render: SQLAlchemy требует 'postgresql://', а Render дает 'postgres://'
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
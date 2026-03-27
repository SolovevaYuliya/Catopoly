import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

# Берем URL из Render
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:1234@localhost:5432/Catopoly_db"
)

# Фикс префикса для Render
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# СОЗДАЕМ ENGINE С ПРАВИЛЬНЫМИ НАСТРОЙКАМИ
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    # NullPool критически важен для Supabase Pooler (порт 6543)
    # Он заставляет закрывать соединение сразу после запроса
    poolclass=NullPool,
    connect_args={
        "sslmode": "require",
        "prepare_threshold": 0  # Это лечит ошибку SSL closed unexpectedly
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
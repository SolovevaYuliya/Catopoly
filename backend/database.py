import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 1. Пробуем взять URL из переменной окружения (для Render)
# 2. Если её нет (локально), подставляем твой локальный адрес базы
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:1234@localhost:5432/Catopoly_db" # ТВОЙ ЛОКАЛЬНЫЙ АДРЕС
)

# Фикс префикса для Render
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# УМНОЕ ПОДКЛЮЧЕНИЕ:
if "localhost" in SQLALCHEMY_DATABASE_URL:
    # Если работаем локально — подключаемся просто
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
else:
    # Если на Render (Supabase) — добавляем SSL и фикс для пулера
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={
            "sslmode": "require",
            "prepare_threshold": 0
        }
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
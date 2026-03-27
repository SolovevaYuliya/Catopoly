import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

# 1. Получаем URL
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:1234@localhost:5432/Catopoly_db"
)

# 2. Фикс для Render
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 3. Настраиваем аргументы подключения
connect_args = {}

# Если мы НЕ на локалке, добавляем SSL и фикс для пулера
if "localhost" not in SQLALCHEMY_DATABASE_URL:
    connect_args = {
        "sslmode": "require",
        "prepare_threshold": 0  # <--- АККУРАТНО ДОБАВИЛИ СЮДА
    }

# 4. Создаем движок
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=connect_args,
    poolclass=NullPool
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
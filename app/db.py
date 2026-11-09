from contextlib import contextmanager
from urllib.parse import quote_plus

import pymysql
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings


def _db_url(include_database: bool) -> str:
    username = quote_plus(settings.mysql_username)
    password = quote_plus(settings.mysql_pass)
    host = settings.mysql_host
    port = settings.mysql_port
    if include_database:
        return f"mysql+pymysql://{username}:{password}@{host}:{port}/{settings.mysql_db}"

    return f"mysql+pymysql://{username}:{password}@{host}:{port}/"


def ensure_database() -> None:
    connection = pymysql.connect(
        host=settings.mysql_host,
        user=settings.mysql_username,
        password=settings.mysql_pass,
        port=settings.mysql_port,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            )
    finally:
        connection.close()


ensure_database()
engine = create_engine(_db_url(include_database=True), future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False, class_=Session)
Base = declarative_base()


@contextmanager
def session_scope() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

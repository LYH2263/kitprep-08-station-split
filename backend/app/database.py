from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 既有数据库补列（create_all 不会改已存在的表）；普通 DDL，PG/SQLite 通用。
_STARTUP_COLUMNS = (
    ("dishes", "station", "VARCHAR(8)"),
    ("prep_runs", "input_sig", "VARCHAR(64)"),
)


def ensure_startup_schema(eng) -> None:
    inspector = inspect(eng)
    existing_tables = set(inspector.get_table_names())
    with eng.begin() as conn:
        for table, column, ddl_type in _STARTUP_COLUMNS:
            if table not in existing_tables:
                continue
            columns = {c["name"] for c in inspector.get_columns(table)}
            if column not in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))

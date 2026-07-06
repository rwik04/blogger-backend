from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

from db.settings import DatabaseSettings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Process-wide pooled engine, built lazily from DB_* env vars."""
    settings = DatabaseSettings.from_env()
    return create_engine(
        settings.to_sqlalchemy_url(),
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout,
        pool_recycle=settings.pool_recycle,
        pool_pre_ping=True,  # cheap liveness check before handing out a pooled conn
    )


def ping(engine: Engine | None = None) -> bool:
    """SELECT 1 health check; returns False instead of raising on failure."""
    engine = engine or get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

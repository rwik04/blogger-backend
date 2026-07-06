import logging
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


def warm_pool(engine: Engine | None = None) -> int:
    """Eagerly opens and returns `pool_size` connections so the pool is
    already full of live connections before the first real request arrives,
    instead of paying the connect-on-demand cost (TCP + TLS + Postgres auth
    handshake, each ~tens-to-hundreds of ms against RDS) on whichever
    request(s) happen to hit an empty pool first. Safe to call more than
    once (e.g. per worker) — `QueuePool` just caps out at `pool_size` and
    stops handing out new connections once it's full.

    Returns the number of connections successfully warmed (best-effort: a
    connection failure here shouldn't prevent the app from starting, since
    normal query-time error handling still applies to every real request).
    """
    engine = engine or get_engine()
    pool_size = getattr(engine.pool, "size", lambda: 0)()
    warmed = 0
    conns = []
    try:
        for _ in range(pool_size or 1):
            conns.append(engine.connect())
            warmed += 1
    except Exception:
        logging.getLogger(__name__).exception("Failed to fully warm the DB connection pool")
    finally:
        for conn in conns:
            conn.close()
    return warmed


def ping(engine: Engine | None = None) -> bool:
    """SELECT 1 health check; returns False instead of raising on failure."""
    engine = engine or get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

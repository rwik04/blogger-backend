import logging
from concurrent.futures import ThreadPoolExecutor
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
        # `pool_pre_ping` costs a full extra round-trip (a `SELECT 1`) on
        # *every* checkout to validate liveness — negligible on a local DB,
        # but this app's RDS instance (ap-south-1) has ~1s one-way latency
        # from here, so it was silently doubling the cost of every single
        # query. `pool_recycle` already proactively refreshes connections
        # before they can go stale, and this app polls frequently enough to
        # keep the pool's connections active, so the liveness check buys
        # little for what it costs here.
        pool_pre_ping=False,
        connect_args={"connect_timeout": settings.connect_timeout},
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

    Opens connections concurrently rather than one at a time — against a
    high-latency remote DB (this app's RDS instance is ~1-2s round-trip per
    connect), warming a pool of any real size sequentially would turn
    startup into a multi-tens-of-seconds stall, exactly the kind of hang
    this is meant to avoid.
    """
    engine = engine or get_engine()
    pool_size = getattr(engine.pool, "size", lambda: 0)() or 1

    def _open() -> object | None:
        try:
            return engine.connect()
        except Exception:
            logging.getLogger(__name__).exception("Failed to open a connection while warming the DB pool")
            return None

    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        conns = [c for c in pool.map(lambda _: _open(), range(pool_size)) if c is not None]

    warmed = len(conns)
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

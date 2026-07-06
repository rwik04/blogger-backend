import os
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy.engine import URL

load_dotenv()

@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    user: str
    password: str
    database: str
    sslmode: str
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    connect_timeout: int

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        return cls(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", "5432")),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ["DB_NAME"],
            sslmode=os.environ.get("DB_SSLMODE", "require"),  # RDS default expectation
            # Every route handler now offloads its DB call to a worker thread
            # (see `api/concurrency.py`), so real concurrent request volume can
            # actually reach the pool instead of being serialized on the event
            # loop — size it for that instead of the single-digit defaults
            # that were fine when everything ran one-request-at-a-time anyway.
            pool_size=int(os.environ.get("DB_POOL_SIZE", "10")),
            max_overflow=int(os.environ.get("DB_POOL_MAX_OVERFLOW", "10")),
            # Fail fast instead of a 30s hang if the pool really is exhausted
            # — a stuck request is easier to notice and retry than a silent
            # multi-second stall on every poll.
            pool_timeout=int(os.environ.get("DB_POOL_TIMEOUT", "10")),
            pool_recycle=int(os.environ.get("DB_POOL_RECYCLE", "1800")),
            # psycopg2 has no connect timeout by default, so a network hiccup
            # reaching RDS (ap-south-1) hangs the TCP handshake forever —
            # this is the most likely cause of the server hanging during
            # startup ("Waiting for application startup" never completing)
            # while `warm_pool` tried to open its initial connections.
            connect_timeout=int(os.environ.get("DB_CONNECT_TIMEOUT", "5")),
        )

    def to_sqlalchemy_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
            query={
                "sslmode": self.sslmode,
                # libpq tries a GSSAPI/Kerberos encryption handshake before
                # falling back to plain SSL by default. RDS doesn't speak
                # Kerberos, so every single new connection was burning
                # multiple seconds stalled on that negotiation before timing
                # out and retrying with SSL — the actual dominant cost behind
                # "extremely slow" queries, worse than anything pool-size
                # related. Skip straight to SSL.
                "gssencmode": "disable",
            },
        )

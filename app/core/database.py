import importlib.util
import time

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings

# MySQL connection-pressure errors: retry with backoff when DB is temporarily full.
_MYSQL_RETRYABLE_CODES = {1040, 1203}
_MYSQL_CONNECT_RETRIES = 6
_MYSQL_RETRY_DELAY_SEC = 2
_MYSQL_RETRYABLE_INTERNAL_MESSAGES = {
    "packet sequence number wrong",
}


def _select_mysql_driver() -> str:
    # Prefer pymysql on Windows (no C compiler needed); mysqlclient is faster on Linux.
    if importlib.util.find_spec("pymysql"):
        return "pymysql"
    if importlib.util.find_spec("MySQLdb"):
        return "mysqldb"
    raise ModuleNotFoundError(
        "No MySQL driver installed. Install `pymysql` or `mysqlclient`."
    )


def get_database_url() -> str:
    driver = _select_mysql_driver()
    return str(
        URL.create(
            drivername=f"mysql+{driver}",
            username=settings.mysql_user,
            password=settings.mysql_password,
            host=settings.mysql_host,
            port=settings.mysql_port,
            database=settings.mysql_db,
            query={"charset": "utf8mb4"},
        )
    )


def _connect_with_retry():
    """Open a DB connection, retrying on MySQL connection-limit errors. Only used for pymysql."""
    import pymysql

    last_err = None
    for attempt in range(_MYSQL_CONNECT_RETRIES):
        try:
            return pymysql.connect(
                host=settings.mysql_host,
                port=settings.mysql_port,
                user=settings.mysql_user,
                password=settings.mysql_password,
                database=settings.mysql_db,
                charset="utf8mb4",
                connect_timeout=10,
                read_timeout=30,
                write_timeout=30,
            )
        except (pymysql.err.OperationalError, pymysql.err.InternalError) as e:
            last_err = e
            code = e.args[0] if e.args else None
            message = " ".join(str(part) for part in e.args).lower()
            retryable_internal = any(text in message for text in _MYSQL_RETRYABLE_INTERNAL_MESSAGES)
            if (code in _MYSQL_RETRYABLE_CODES or retryable_internal) and attempt < _MYSQL_CONNECT_RETRIES - 1:
                time.sleep(_MYSQL_RETRY_DELAY_SEC * (attempt + 1))
                continue
            raise
    if last_err is not None:
        raise last_err
    raise RuntimeError("Connection failed")


# Use NullPool + retry on 1040 so we don't hold connections and can wait when DB is temporarily full.
_engine_kw = dict(
    poolclass=NullPool,
    pool_pre_ping=True,
)
if _select_mysql_driver() == "pymysql":
    _engine_kw["creator"] = _connect_with_retry

# Note: create_engine does not actually connect to the database until first use,
# so this will not block simple routes like `/health` that don't touch the DB.
engine = create_engine(get_database_url(), **_engine_kw)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

import subprocess
import sys
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.core.database import get_database_url


def main():
    # Base URL without database name (same driver as app: pymysql or mysqldb)
    db_url = get_database_url()
    path_part, _, qs = db_url.partition("?")
    root_path = path_part.rsplit("/", 1)[0] + "/"
    root_url = root_path + ("?" + qs if qs else "")
    engine = create_engine(root_url)
    with engine.connect() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_db}` CHARACTER SET utf8mb4"))
        conn.commit()

    result = subprocess.call(["alembic", "upgrade", "head"])
    return result


if __name__ == "__main__":
    sys.exit(main())

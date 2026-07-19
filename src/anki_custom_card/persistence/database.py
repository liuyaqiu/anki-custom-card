from sqlite3 import Connection as SQLiteConnection

from sqlalchemy import Engine, create_engine, event

SQLITE_BUSY_TIMEOUT_MS = 5_000


def build_engine(database_url: str) -> Engine:
    """Build a SQLAlchemy engine with the SQLite invariants required by the service."""

    engine = create_engine(database_url)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection: SQLiteConnection, _: object) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            cursor.close()

    return engine

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Watchlist, WatchlistSymbol


class Database:
    def __init__(self, url: str):
        kwargs = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        self.engine: Engine = create_engine(url, future=True, **kwargs)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self._factory = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        self._migrate()
        Base.metadata.create_all(self.engine)

    def _migrate(self) -> None:
        """Stage 1 stored bars with an Alpaca `feed` column. The bar table is only a cache,
        so it is dropped and rebuilt; watchlists and event history are kept."""
        insp = inspect(self.engine)
        if "bars" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("bars")}
            if "feed" in cols and "provider" not in cols:
                with self.engine.begin() as conn:
                    conn.execute(text("DROP TABLE bars"))

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def seed_default_watchlist(self, symbols: list[str]) -> None:
        with self.session() as s:
            if s.scalar(select(Watchlist).limit(1)) is not None:
                return
            wl = Watchlist(name="Default")
            wl.symbols = [WatchlistSymbol(symbol=sym, position=i) for i, sym in enumerate(symbols)]
            s.add(wl)

    def dispose(self) -> None:
        self.engine.dispose()


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")  # concurrent reads while the stream writes
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()

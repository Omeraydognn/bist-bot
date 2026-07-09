"""
Depolama katmani (SQLite).

Tasarim prensibi: hicbir tablo tek bir hisseye ozel degildir.
Her tablo "symbol" kolonu ile ayrisir, boylece yeni bir hisse
eklendiginde yeni bir tablo / yeni bir kod yolu GEREKMEZ.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol      TEXT NOT NULL,
    date        TEXT NOT NULL,   -- ISO tarih (YYYY-MM-DD veya timestamp)
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS news (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    published_at    TEXT NOT NULL,
    source          TEXT,
    title           TEXT,
    content         TEXT,
    sentiment_score REAL,      -- -1..+1 arasi, doldurulmamissa NULL
    raw_url         TEXT,
    UNIQUE(symbol, title, published_at)
);

CREATE TABLE IF NOT EXISTS depth_snapshots (
    symbol      TEXT NOT NULL,
    ts          TEXT NOT NULL,
    bid_price   REAL,
    bid_qty     REAL,
    ask_price   REAL,
    ask_qty     REAL,
    level       INTEGER,        -- 1,2,3... derinlik seviyesi
    PRIMARY KEY (symbol, ts, level, bid_price, ask_price)
);

CREATE TABLE IF NOT EXISTS akd_takas (
    symbol          TEXT NOT NULL,
    date            TEXT NOT NULL,
    broker_or_group TEXT NOT NULL,  -- aracı kurum adi veya "yabanci"/"yerli" grubu
    net_volume      REAL,
    PRIMARY KEY (symbol, date, broker_or_group)
);

CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    date        TEXT NOT NULL,
    technical_score   REAL,
    news_score        REAL,
    fundamental_score REAL,
    depth_score       REAL,
    akd_score         REAL,
    final_score       REAL,
    decision          TEXT,      -- AL / SAT / TUT
    details           TEXT       -- JSON aciklama (hangi kural ne dedi)
);
"""


class Storage:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    # ---------------- PRICES ----------------
    def upsert_prices(self, symbol: str, rows: Iterable[dict]):
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO prices (symbol, date, open, high, low, close, volume)
                   VALUES (:symbol, :date, :open, :high, :low, :close, :volume)
                   ON CONFLICT(symbol, date) DO UPDATE SET
                     open=excluded.open, high=excluded.high, low=excluded.low,
                     close=excluded.close, volume=excluded.volume""",
                [{**r, "symbol": symbol} for r in rows],
            )

    def get_prices(self, symbol: str, limit: int | None = None):
        query = "SELECT * FROM prices WHERE symbol = ? ORDER BY date ASC"
        with self._connect() as conn:
            cur = conn.execute(query, (symbol,))
            rows = [dict(r) for r in cur.fetchall()]
        return rows[-limit:] if limit else rows

    # ---------------- NEWS ----------------
    def insert_news(self, symbol: str, items: Iterable[dict]):
        with self._connect() as conn:
            for item in items:
                conn.execute(
                    """INSERT OR IGNORE INTO news
                       (symbol, published_at, source, title, content, sentiment_score, raw_url)
                       VALUES (:symbol, :published_at, :source, :title, :content, :sentiment_score, :raw_url)""",
                    {**item, "symbol": symbol},
                )

    def get_recent_news(self, symbol: str, limit: int = 20):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM news WHERE symbol = ? ORDER BY published_at DESC LIMIT ?",
                (symbol, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    # ---------------- SIGNALS ----------------
    def insert_signal(self, row: dict):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO signals
                   (symbol, date, technical_score, news_score, fundamental_score,
                    depth_score, akd_score, final_score, decision, details)
                   VALUES (:symbol, :date, :technical_score, :news_score, :fundamental_score,
                    :depth_score, :akd_score, :final_score, :decision, :details)""",
                row,
            )

    def get_signals(self, symbol: str, limit: int = 50):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM signals WHERE symbol = ? ORDER BY date DESC LIMIT ?",
                (symbol, limit),
            )
            return [dict(r) for r in cur.fetchall()]

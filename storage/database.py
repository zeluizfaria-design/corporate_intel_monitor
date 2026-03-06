"""DuckDB schema e operações CRUD."""
import duckdb
from pathlib import Path
from datetime import datetime


DB_PATH = Path("data/corporate_intel.duckdb")

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id              VARCHAR PRIMARY KEY,
    source          VARCHAR NOT NULL,
    source_type     VARCHAR NOT NULL,
    url             VARCHAR UNIQUE,
    title           TEXT,
    content         TEXT,
    published_at    TIMESTAMP,
    collected_at    TIMESTAMP DEFAULT now(),
    company_ticker  VARCHAR,
    company_name    VARCHAR,
    sentiment_label VARCHAR,
    sentiment_score DOUBLE,
    sentiment_compound DOUBLE,
    event_type      VARCHAR,
    raw_metadata    JSON
);

CREATE INDEX IF NOT EXISTS idx_ticker_date
    ON articles (company_ticker, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_type
    ON articles (source_type, published_at DESC);

CREATE TABLE IF NOT EXISTS alerts_sent (
    article_id  VARCHAR PRIMARY KEY,
    sent_at     TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS watchlist (
    ticker      VARCHAR PRIMARY KEY,
    is_dual     BOOLEAN DEFAULT false,
    us_ticker   VARCHAR,
    added_at    TIMESTAMP DEFAULT now()
);
"""


class Database:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(path))
        self._conn.execute(SCHEMA)

    def upsert(self, article_dict: dict) -> bool:
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO articles VALUES ($id, $source, $source_type, "
                "$url, $title, $content, $published_at, $collected_at, "
                "$company_ticker, $company_name, $sentiment_label, $sentiment_score, "
                "$sentiment_compound, $event_type, $raw_metadata)",
                article_dict,
            )
            return True
        except duckdb.ConstraintException:
            return False

    def mark_alert_sent(self, article_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO alerts_sent (article_id) VALUES (?)", [article_id]
        )

    def is_alert_sent(self, article_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM alerts_sent WHERE article_id = ?", [article_id]
        ).fetchone()
        return row is not None

    def query_by_ticker(self, ticker: str, days: int = 7, source_types: list[str] | None = None) -> list[dict]:
        filters = ["company_ticker = ?", "published_at >= now() - (?::INT * INTERVAL 1 DAY)"]
        params = [ticker.upper(), days]
        if source_types:
            placeholders = ", ".join("?" * len(source_types))
            filters.append(f"source_type IN ({placeholders})")
            params.extend(source_types)
        sql = f"SELECT * FROM articles WHERE {' AND '.join(filters)} ORDER BY published_at DESC"
        
        # Em vez de df().to_dict() que exige pandas, pegamos as chaves pelo cursor.description
        cursor = self._conn.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        return [dict(zip(columns, row)) for row in rows]

    def seed_watchlist(self, target_tickers: list[str], dual_listed_map: dict[str, str]) -> None:
        """Semeia a watchlist a partir das configurações se a tabela estiver vazia."""
        count = self._conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        if count == 0:
            for ticker in target_tickers:
                is_dual = ticker in dual_listed_map
                us_ticker = dual_listed_map.get(ticker)
                self.add_to_watchlist(ticker, is_dual=is_dual, us_ticker=us_ticker)

    def add_to_watchlist(self, ticker: str, is_dual: bool = False, us_ticker: str | None = None) -> bool:
        """Adiciona um ticker à watchlist. Retorna True se inseriu, False se já existia."""
        try:
            self._conn.execute(
                "INSERT INTO watchlist (ticker, is_dual, us_ticker) VALUES (?, ?, ?)",
                [ticker.upper(), is_dual, us_ticker.upper() if us_ticker else None]
            )
            return True
        except duckdb.ConstraintException:
            return False

    def remove_from_watchlist(self, ticker: str) -> None:
        """Remove um ticker da watchlist."""
        self._conn.execute("DELETE FROM watchlist WHERE ticker = ?", [ticker.upper()])

    def get_watchlist(self) -> list[dict]:
        """Retorna todos os tickers da watchlist."""
        rows = self._conn.execute("SELECT ticker, is_dual, us_ticker FROM watchlist ORDER BY added_at ASC").fetchall()
        return [{"ticker": r[0], "is_dual": r[1], "us_ticker": r[2]} for r in rows]

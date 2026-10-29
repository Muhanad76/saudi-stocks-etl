"""Load stage: create the schema and upsert companies, prices and metrics into MySQL."""

import logging
import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

import config

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000

UPSERT_COMPANY = text("""
    INSERT INTO companies (ticker, name_en, name_ar, sector)
    VALUES (:ticker, :name_en, :name_ar, :sector)
    ON DUPLICATE KEY UPDATE
        name_en = VALUES(name_en), name_ar = VALUES(name_ar), sector = VALUES(sector)
""")

UPSERT_PRICE = text("""
    INSERT INTO daily_prices (ticker, date, open, high, low, close, volume)
    VALUES (:ticker, :date, :open, :high, :low, :close, :volume)
    ON DUPLICATE KEY UPDATE
        open = VALUES(open), high = VALUES(high), low = VALUES(low),
        close = VALUES(close), volume = VALUES(volume)
""")

UPSERT_METRIC = text("""
    INSERT INTO daily_metrics
        (ticker, date, daily_return, cumulative_return, ma_20, ma_50, volatility_30d)
    VALUES
        (:ticker, :date, :daily_return, :cumulative_return, :ma_20, :ma_50, :volatility_30d)
    ON DUPLICATE KEY UPDATE
        daily_return = VALUES(daily_return), cumulative_return = VALUES(cumulative_return),
        ma_20 = VALUES(ma_20), ma_50 = VALUES(ma_50), volatility_30d = VALUES(volatility_30d)
""")


def get_engine(with_database=True):
    """Build a SQLAlchemy engine from the credentials in .env."""
    load_dotenv(config.BASE_DIR / ".env")
    missing = [k for k in ("DB_USER", "DB_PASSWORD") if os.getenv(k) is None]
    if missing:
        raise RuntimeError(f"Missing {', '.join(missing)} in .env (copy .env.example to .env)")
    url = URL.create(
        "mysql+pymysql",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=config.DB_NAME if with_database else None,
        query={"charset": "utf8mb4"},
    )
    return create_engine(url, pool_pre_ping=True)


def ensure_schema():
    """Run sql/schema.sql so the database and tables exist (idempotent)."""
    sql = config.SCHEMA_FILE.read_text(encoding="utf-8")
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    statements = [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
    engine = get_engine(with_database=False)
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    engine.dispose()
    logger.info("Schema ready (%d statements from %s)", len(statements), config.SCHEMA_FILE.name)


def to_records(df):
    """Convert a DataFrame to a list of dicts with Python dates and None instead of NaN."""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out = out.astype(object).where(out.notna(), None)
    return out.to_dict("records")


def execute_batches(conn, statement, records):
    """Execute a parameterized statement in batches to keep packets small."""
    for i in range(0, len(records), BATCH_SIZE):
        conn.execute(statement, records[i:i + BATCH_SIZE])


def load_companies(engine, tickers):
    """Upsert the company dimension rows for the given tickers."""
    records = []
    for ticker in tickers:
        info = config.COMPANIES.get(ticker) or (config.INDEX_INFO if ticker == config.INDEX_TICKER else None)
        if info:
            name_en, name_ar, sector = info
            records.append({"ticker": ticker, "name_en": name_en, "name_ar": name_ar, "sector": sector})
    with engine.begin() as conn:
        conn.execute(UPSERT_COMPANY, records)
    logger.info("Companies upserted: %d", len(records))


def get_db_state(engine):
    """Return {ticker: (last_date, last_close)} for every ticker already stored."""
    query = text("""
        SELECT p.ticker, p.date, p.close
        FROM daily_prices p
        JOIN (SELECT ticker, MAX(date) AS max_date FROM daily_prices GROUP BY ticker) m
          ON m.ticker = p.ticker AND m.max_date = p.date
    """)
    with engine.connect() as conn:
        rows = conn.execute(query).all()
    return {ticker: (last_date, float(close)) for ticker, last_date, close in rows}


def get_price_history(engine, ticker):
    """Return all stored prices for one ticker, shaped like transform.clean_prices output."""
    query = text("""
        SELECT ticker, date, open, high, low, close, volume
        FROM daily_prices WHERE ticker = :ticker ORDER BY date
    """)
    df = pd.read_sql(query, engine, params={"ticker": ticker})
    df["date"] = pd.to_datetime(df["date"])
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    # Nullable integer: bad-volume days are stored as NULL.
    df["volume"] = df["volume"].astype("Int64")
    return df


def round_for_db(prices, metrics):
    """Round values to the precision of the database columns."""
    prices = prices.round({"open": 4, "high": 4, "low": 4, "close": 4})
    metrics = metrics.round({"daily_return": 8, "cumulative_return": 8, "ma_20": 4,
                             "ma_50": 4, "volatility_30d": 8})
    return prices, metrics


def load(engine, prices, metrics, modes):
    """Upsert prices then metrics in one transaction.

    Tickers loaded in 'full' mode are deleted first so old rows computed from a
    different starting point (or old adjustments) cannot linger.
    """
    if prices.empty:
        logger.info("Load skipped: no rows to load")
        return
    prices, metrics = round_for_db(prices, metrics)
    full_tickers = [t for t, mode in modes.items() if mode == "full"]

    with engine.begin() as conn:
        for ticker in full_tickers:
            conn.execute(text("DELETE FROM daily_metrics WHERE ticker = :t"), {"t": ticker})
            conn.execute(text("DELETE FROM daily_prices WHERE ticker = :t"), {"t": ticker})
        execute_batches(conn, UPSERT_PRICE, to_records(prices))
        execute_batches(conn, UPSERT_METRIC, to_records(metrics))

    logger.info("Load finished: %d price rows, %d metric rows (full reload: %s)",
                len(prices), len(metrics), ", ".join(full_tickers) or "none")

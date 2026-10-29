"""Central configuration for the Saudi Stocks ETL pipeline."""

from pathlib import Path

# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
LOG_DIR = BASE_DIR / "logs"

# --- Companies tracked by the pipeline ---
# ticker -> (name_en, name_ar, sector)
COMPANIES = {
    "2222.SR": ("Saudi Aramco", "أرامكو السعودية", "Energy"),
    "1120.SR": ("Al Rajhi Bank", "مصرف الراجحي", "Banks"),
    "1180.SR": ("SNB", "البنك الأهلي السعودي", "Banks"),
    "2010.SR": ("SABIC", "سابك", "Materials"),
    "1211.SR": ("Ma'aden", "معادن", "Materials"),
    "7010.SR": ("stc", "إس تي سي", "Telecom"),
    "2280.SR": ("Almarai", "المراعي", "Food & Beverages"),
    "2082.SR": ("ACWA Power", "أكوا باور", "Utilities"),
}

# Optional market index (TASI). Disabled: yfinance returns only the latest
# day for "^TASI.SR" (checked Oct 2026), so it has no usable history.
INDEX_TICKER = None
INDEX_INFO = ("TASI Index", "مؤشر السوق الرئيسي تاسي", "Index")

# --- Extraction settings ---
PERIOD_YEARS = 5   # history length for the first full load
INTERVAL = "1d"    # daily bars
# Adjusted prices include dividends and bonus shares, so returns are accurate.
AUTO_ADJUST = True

# Tadawul's closing auction ends around 15:10 Riyadh time. A daily bar for
# today pulled before this hour is still moving, so it is skipped.
MARKET_TIMEZONE = "Asia/Riyadh"
MARKET_CLOSE_HOUR = 16

# --- Metric settings ---
MA_SHORT = 20
MA_LONG = 50
VOLATILITY_WINDOW = 30

# Yahoo reports volumes ~1000x too small for some periods (e.g. Mar-Jun 2023).
# A day whose volume is below this fraction of the ticker's median volume over
# the whole stored period is treated as bad data and stored as NULL. The
# full-period median is used (not a rolling one) because the bad stretch is
# longer than any reasonable rolling window and would contaminate it.
VOLUME_ANOMALY_RATIO = 0.02

# --- Database ---
# Connection credentials live in .env (see .env.example), never in code.
DB_NAME = "saudi_stocks"
SCHEMA_FILE = BASE_DIR / "sql" / "schema.sql"


def all_tickers():
    """Return every ticker the pipeline should process, including the index if enabled."""
    tickers = list(COMPANIES)
    if INDEX_TICKER:
        tickers.append(INDEX_TICKER)
    return tickers

"""Extract stage: download daily prices from yfinance and keep a raw CSV copy."""

import logging

import pandas as pd
import yfinance as yf

import config

logger = logging.getLogger(__name__)

PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

# If the stored close for the last loaded day differs from what yfinance
# returns now by more than this, history was re-adjusted (dividend/bonus
# shares) and the ticker must be reloaded in full.
ADJUSTMENT_TOLERANCE = 0.001


def full_start_date():
    """Return the fixed first date of the history (config.START_DATE)."""
    return pd.Timestamp(config.START_DATE).date()


def drop_unfinished_session(df):
    """Drop today's bar if the market session has not closed yet."""
    if df.empty:
        return df
    now = pd.Timestamp.now(tz=config.MARKET_TIMEZONE)
    if now.hour >= config.MARKET_CLOSE_HOUR:
        return df
    bar_dates = df.index.tz_convert(config.MARKET_TIMEZONE).date
    return df[bar_dates < now.date()]


def download(ticker, start):
    """Download daily OHLCV bars for one ticker from `start` (inclusive) until today."""
    df = yf.Ticker(ticker).history(
        start=start,
        interval=config.INTERVAL,
        auto_adjust=config.AUTO_ADJUST,
    )
    if df.empty:
        return df
    return drop_unfinished_session(df[PRICE_COLUMNS])


def save_raw(ticker, df):
    """Save an untouched copy of the downloaded data to data/raw and return the path."""
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    path = config.RAW_DIR / f"{ticker.replace('.', '_').lstrip('^')}_{stamp}.csv"
    df.to_csv(path)
    return path


def needs_full_reload(df, last_date, last_close):
    """Return True if yfinance history no longer matches what is stored in the database."""
    overlap = df[df.index.date == last_date]
    if overlap.empty:
        return True
    new_close = float(overlap["Close"].iloc[0])
    return abs(new_close - last_close) / last_close > ADJUSTMENT_TOLERANCE


def extract_ticker(ticker, state=None):
    """Extract one ticker and return (raw_df, mode), where mode is 'full' or 'incremental'.

    `state` is (last_date, last_close) from the database, or None for a full load.
    """
    if state is None:
        mode = "full"
        df = download(ticker, full_start_date())
    else:
        last_date, last_close = state
        # Re-download the last stored day as well, to detect re-adjusted history.
        df = download(ticker, last_date)
        if needs_full_reload(df, last_date, last_close):
            logger.warning("%s: stored prices no longer match yfinance (likely dividend "
                           "adjustment), switching to full reload", ticker)
            mode = "full"
            df = download(ticker, full_start_date())
        else:
            mode = "incremental"
            df = df[df.index.date > last_date]
            if df.empty:
                logger.info("%s: already up to date (last date %s)", ticker, last_date)
                return df, mode

    if df.empty:
        raise ValueError(f"yfinance returned no data for {ticker}")

    path = save_raw(ticker, df)
    logger.info("%s: %s extract, %d rows (%s -> %s), raw copy: %s", ticker, mode, len(df),
                df.index.min().date(), df.index.max().date(), path.name)
    return df, mode


def extract(tickers, db_state=None):
    """Extract all tickers. A failing ticker is logged and skipped, the rest continue.

    Returns {ticker: (raw_df, mode)} for the tickers that succeeded.
    """
    db_state = db_state or {}
    results = {}
    for ticker in tickers:
        try:
            results[ticker] = extract_ticker(ticker, db_state.get(ticker))
        except Exception:
            logger.exception("%s: extract failed, skipping", ticker)
    logger.info("Extract finished: %d/%d tickers succeeded", len(results), len(tickers))
    return results

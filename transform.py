"""Transform stage: clean raw prices and compute return, trend and risk metrics."""

import logging

import pandas as pd

import config

logger = logging.getLogger(__name__)

PRICE_FIELDS = ["open", "high", "low", "close"]


def clean_prices(raw, ticker):
    """Return a clean price table: tz-naive dates, no duplicates, no missing or invalid rows."""
    df = raw.copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        # Convert to market time first so the calendar date is the trading day.
        df.index = df.index.tz_convert(config.MARKET_TIMEZONE).tz_localize(None)
    df.index = df.index.normalize()

    df = df.rename(columns=str.lower).rename_axis("date").reset_index()
    df = df[["date", *PRICE_FIELDS, "volume"]]
    start_rows = len(df)

    df = df.drop_duplicates(subset="date", keep="last")
    # A day without a full price is unusable; filling it would fake a return.
    df = df.dropna(subset=PRICE_FIELDS)
    # Zero volume rows are holidays/non-trading days that yfinance sometimes emits.
    df = df[df["volume"].fillna(0) > 0]
    df = df[(df["high"] >= df["low"]) & (df["close"] > 0)]

    dropped = start_rows - len(df)
    if dropped:
        logger.info("%s: dropped %d invalid/duplicate rows", ticker, dropped)

    df["volume"] = df["volume"].astype("Int64")
    df.insert(0, "ticker", ticker)
    return df.sort_values("date").reset_index(drop=True)


def flag_bad_volume(prices, ticker):
    """Set implausibly low volumes to NA, using the ticker's full-period median.

    Prices on those days are kept: only the volume field is unreliable.
    """
    prices = prices.copy()
    threshold = prices["volume"].median() * config.VOLUME_ANOMALY_RATIO
    # Volumes already NULL (from stored history) compare as NA -> not re-flagged.
    bad = prices["volume"].lt(threshold).fillna(False).astype(bool)
    if bad.any():
        prices.loc[bad, "volume"] = pd.NA
        bad_dates = prices.loc[bad, "date"]
        logger.warning("%s: %d days with implausible volume set to NULL (%s -> %s)", ticker,
                       len(bad_dates), bad_dates.min().date(), bad_dates.max().date())
    return prices


def compute_metrics(prices):
    """Compute daily/cumulative return, moving averages and 30-day volatility for one ticker."""
    close = prices["close"]
    daily_return = close / close.shift(1) - 1
    return pd.DataFrame({
        "ticker": prices["ticker"],
        "date": prices["date"],
        "daily_return": daily_return,
        # Growth relative to the first stored close (0.25 = +25%).
        "cumulative_return": close / close.iloc[0] - 1,
        "ma_20": close.rolling(config.MA_SHORT).mean(),
        "ma_50": close.rolling(config.MA_LONG).mean(),
        # Standard deviation of daily returns (not annualized).
        "volatility_30d": daily_return.rolling(config.VOLATILITY_WINDOW).std(),
    })


def transform_ticker(ticker, raw, mode, history=None):
    """Clean one ticker and compute its metrics. Returns (new_prices, new_metrics).

    For incremental runs `history` holds the prices already in the database, so
    rolling windows and cumulative return are computed over the full series.
    """
    new_prices = clean_prices(raw, ticker)
    if new_prices.empty:
        return new_prices, pd.DataFrame()

    series = new_prices
    if mode == "incremental" and history is not None and not history.empty:
        series = (pd.concat([history, new_prices])
                  .drop_duplicates(subset="date", keep="last")
                  .sort_values("date")
                  .reset_index(drop=True))

    # Checked against the whole series so the median reflects the full period.
    series = flag_bad_volume(series, ticker)
    first_new = new_prices["date"].min()
    new_prices = series[series["date"] >= first_new].reset_index(drop=True)

    metrics = compute_metrics(series)
    metrics = metrics[metrics["date"] >= first_new]
    return new_prices, metrics


def save_processed(prices, metrics):
    """Write this run's processed tables to data/processed."""
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    prices.to_csv(config.PROCESSED_DIR / "daily_prices.csv", index=False)
    metrics.to_csv(config.PROCESSED_DIR / "daily_metrics.csv", index=False)


def transform(extracted, history=None):
    """Transform every extracted ticker. A failing ticker is logged and skipped.

    `extracted` is {ticker: (raw_df, mode)}; `history` is {ticker: prices_df}.
    Returns (prices_df, metrics_df, modes) where modes is {ticker: mode}.
    """
    history = history or {}
    price_parts, metric_parts, modes = [], [], {}
    for ticker, (raw, mode) in extracted.items():
        if raw.empty:
            continue
        try:
            prices, metrics = transform_ticker(ticker, raw, mode, history.get(ticker))
        except Exception:
            logger.exception("%s: transform failed, skipping", ticker)
            continue
        if prices.empty:
            continue
        price_parts.append(prices)
        metric_parts.append(metrics)
        modes[ticker] = mode

    if not price_parts:
        logger.info("Transform finished: nothing new to process")
        return pd.DataFrame(), pd.DataFrame(), modes

    prices = pd.concat(price_parts, ignore_index=True)
    metrics = pd.concat(metric_parts, ignore_index=True)
    save_processed(prices, metrics)
    logger.info("Transform finished: %d price rows, %d metric rows for %d tickers",
                len(prices), len(metrics), len(modes))
    return prices, metrics, modes

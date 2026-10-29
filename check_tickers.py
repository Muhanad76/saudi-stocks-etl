"""One-off check that every configured ticker returns data from yfinance."""

import yfinance as yf

import config


def check_ticker(ticker):
    """Download a short history for one ticker and return (rows, first_date, last_date)."""
    df = yf.download(ticker, period="max", interval="1d", progress=False, auto_adjust=True)
    if df.empty:
        return 0, None, None
    return len(df), df.index.min().date(), df.index.max().date()


if __name__ == "__main__":
    for t in config.all_tickers():
        try:
            rows, first, last = check_ticker(t)
            status = "OK " if rows else "EMPTY"
            print(f"{status} {t:10} rows={rows:5}  {first} -> {last}")
        except Exception as exc:
            print(f"FAIL {t:10} {exc}")

"""Run the full ETL pipeline: extract -> transform -> load.

Usage:
    python pipeline.py              # incremental run (full load on first run)
    python pipeline.py --full       # force a full 5-year reload of every ticker
    python pipeline.py --skip-load  # extract + transform only, no database needed
"""

import argparse
import logging
import sys
import time

import config
import extract
import load
import transform

logger = logging.getLogger("pipeline")


def setup_logging():
    """Log to the console and to logs/pipeline.log."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)-9s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_DIR / "pipeline.log", encoding="utf-8"),
        ],
    )
    # yfinance is chatty at INFO level; keep only its warnings and errors.
    logging.getLogger("yfinance").setLevel(logging.WARNING)


def parse_args():
    """Parse command line flags."""
    parser = argparse.ArgumentParser(description="Saudi stocks ETL pipeline")
    parser.add_argument("--full", action="store_true", help="ignore stored data and reload everything")
    parser.add_argument("--skip-load", action="store_true", help="run extract and transform only")
    return parser.parse_args()


def run(full=False, skip_load=False):
    """Run all stages and return the number of tickers that were processed."""
    tickers = config.all_tickers()
    engine = None
    db_state, history = {}, {}

    if not skip_load:
        load.ensure_schema()
        engine = load.get_engine()
        load.load_companies(engine, tickers)
        if not full:
            db_state = load.get_db_state(engine)
        logger.info("Stored tickers found: %d (%s)", len(db_state),
                    "incremental" if db_state else "first full load")

    logger.info("=== Extract ===")
    extracted = extract.extract(tickers, db_state)

    if engine is not None:
        for ticker, (raw, mode) in extracted.items():
            if mode == "incremental" and not raw.empty:
                history[ticker] = load.get_price_history(engine, ticker)

    logger.info("=== Transform ===")
    prices, metrics, modes = transform.transform(extracted, history)

    if engine is not None:
        logger.info("=== Load ===")
        load.load(engine, prices, metrics, modes)
        engine.dispose()

    failed = sorted(set(tickers) - set(extracted))
    if failed:
        logger.warning("Tickers that failed: %s", ", ".join(failed))
    return len(extracted)


def main():
    """Entry point: run the pipeline and exit non-zero if nothing succeeded."""
    setup_logging()
    args = parse_args()
    started = time.perf_counter()
    logger.info("Pipeline started (full=%s, skip_load=%s)", args.full, args.skip_load)
    try:
        succeeded = run(full=args.full, skip_load=args.skip_load)
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)
    logger.info("Pipeline finished in %.1fs", time.perf_counter() - started)
    sys.exit(0 if succeeded else 1)


if __name__ == "__main__":
    main()

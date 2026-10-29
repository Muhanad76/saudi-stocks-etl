-- Database and tables for the Saudi Stocks ETL pipeline (MySQL 8.0+).
-- Safe to run repeatedly: every statement uses IF NOT EXISTS.

CREATE DATABASE IF NOT EXISTS saudi_stocks
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE saudi_stocks;

-- One row per company (dimension table).
CREATE TABLE IF NOT EXISTS companies (
    ticker   VARCHAR(12)  NOT NULL,
    name_en  VARCHAR(100) NOT NULL,
    name_ar  VARCHAR(100) NOT NULL,
    sector   VARCHAR(50)  NOT NULL,
    PRIMARY KEY (ticker)
);

-- Daily OHLCV prices, adjusted for dividends and bonus shares.
-- volume is NULL on days where Yahoo's reported volume is implausible.
CREATE TABLE IF NOT EXISTS daily_prices (
    ticker  VARCHAR(12)     NOT NULL,
    date    DATE            NOT NULL,
    open    DECIMAL(12, 4)  NOT NULL,
    high    DECIMAL(12, 4)  NOT NULL,
    low     DECIMAL(12, 4)  NOT NULL,
    close   DECIMAL(12, 4)  NOT NULL,
    volume  BIGINT UNSIGNED NULL,
    PRIMARY KEY (ticker, date),
    INDEX idx_prices_date (date),
    CONSTRAINT fk_prices_company FOREIGN KEY (ticker) REFERENCES companies (ticker)
);

-- Upgrades databases created before volume became nullable (idempotent).
ALTER TABLE daily_prices MODIFY volume BIGINT UNSIGNED NULL;

-- Metrics derived from daily_prices. Returns are fractions (0.05 = 5%).
-- Early rows have NULL moving averages/volatility until the window fills.
CREATE TABLE IF NOT EXISTS daily_metrics (
    ticker             VARCHAR(12)    NOT NULL,
    date               DATE           NOT NULL,
    daily_return       DECIMAL(14, 8) NULL,
    cumulative_return  DECIMAL(14, 8) NULL,
    ma_20              DECIMAL(12, 4) NULL,
    ma_50              DECIMAL(12, 4) NULL,
    volatility_30d     DECIMAL(14, 8) NULL,
    PRIMARY KEY (ticker, date),
    INDEX idx_metrics_date (date),
    CONSTRAINT fk_metrics_price FOREIGN KEY (ticker, date)
        REFERENCES daily_prices (ticker, date) ON DELETE CASCADE
);

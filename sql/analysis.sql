-- =====================================================================
-- Analysis queries for the saudi_stocks database (MySQL 8.0+).
-- Returns in the tables are fractions; queries below show percentages.
-- =====================================================================

USE saudi_stocks;


-- ---------------------------------------------------------------------
-- Q1. Total return per stock over the full stored period.
-- Compares the first and last close of each ticker. Note: ACWA Power
-- (2082.SR) data starts later than the others, see Q1b for a fair view.
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT ticker, MIN(date) AS first_date, MAX(date) AS last_date
    FROM daily_prices
    GROUP BY ticker
)
SELECT c.ticker,
       c.name_en,
       c.sector,
       b.first_date,
       b.last_date,
       ROUND((pl.close / pf.close - 1) * 100, 2) AS total_return_pct
FROM bounds b
JOIN daily_prices pf ON pf.ticker = b.ticker AND pf.date = b.first_date
JOIN daily_prices pl ON pl.ticker = b.ticker AND pl.date = b.last_date
JOIN companies c     ON c.ticker = b.ticker
ORDER BY total_return_pct DESC;


-- ---------------------------------------------------------------------
-- Q1b. Total return over the COMMON window (all stocks start on the same
-- day: the latest first date among them). Use this to rank stocks fairly.
-- ---------------------------------------------------------------------
WITH common_start AS (
    SELECT MAX(first_date) AS start_date
    FROM (SELECT MIN(date) AS first_date FROM daily_prices GROUP BY ticker) t
),
bounds AS (
    SELECT p.ticker, MIN(p.date) AS first_date, MAX(p.date) AS last_date
    FROM daily_prices p
    CROSS JOIN common_start cs
    WHERE p.date >= cs.start_date
    GROUP BY p.ticker
)
SELECT c.ticker,
       c.name_en,
       c.sector,
       b.first_date,
       b.last_date,
       ROUND((pl.close / pf.close - 1) * 100, 2) AS total_return_pct,
       RANK() OVER (ORDER BY pl.close / pf.close DESC) AS return_rank
FROM bounds b
JOIN daily_prices pf ON pf.ticker = b.ticker AND pf.date = b.first_date
JOIN daily_prices pl ON pl.ticker = b.ticker AND pl.date = b.last_date
JOIN companies c     ON c.ticker = b.ticker
ORDER BY return_rank;


-- ---------------------------------------------------------------------
-- Q2. Annual return per stock per calendar year.
-- Year-end close vs. previous year-end close. The first year of each
-- ticker is partial and uses its first available close as the base.
-- ---------------------------------------------------------------------
WITH year_bounds AS (
    SELECT ticker, YEAR(date) AS yr, MIN(date) AS first_date, MAX(date) AS last_date
    FROM daily_prices
    GROUP BY ticker, YEAR(date)
),
year_close AS (
    SELECT yb.ticker, yb.yr, pf.close AS first_close, pl.close AS year_end_close
    FROM year_bounds yb
    JOIN daily_prices pf ON pf.ticker = yb.ticker AND pf.date = yb.first_date
    JOIN daily_prices pl ON pl.ticker = yb.ticker AND pl.date = yb.last_date
)
SELECT ticker,
       yr AS year,
       ROUND((year_end_close
              / COALESCE(LAG(year_end_close) OVER (PARTITION BY ticker ORDER BY yr), first_close)
              - 1) * 100, 2) AS annual_return_pct
FROM year_close
ORDER BY ticker, yr;


-- ---------------------------------------------------------------------
-- Q3. Best and worst performer (common window), plus each stock's best
-- and worst calendar year.
-- ---------------------------------------------------------------------
WITH common_start AS (
    SELECT MAX(first_date) AS start_date
    FROM (SELECT MIN(date) AS first_date FROM daily_prices GROUP BY ticker) t
),
bounds AS (
    SELECT p.ticker, MIN(p.date) AS first_date, MAX(p.date) AS last_date
    FROM daily_prices p
    CROSS JOIN common_start cs
    WHERE p.date >= cs.start_date
    GROUP BY p.ticker
),
returns AS (
    SELECT b.ticker, pl.close / pf.close - 1 AS total_return
    FROM bounds b
    JOIN daily_prices pf ON pf.ticker = b.ticker AND pf.date = b.first_date
    JOIN daily_prices pl ON pl.ticker = b.ticker AND pl.date = b.last_date
),
ranked AS (
    SELECT ticker, total_return,
           ROW_NUMBER() OVER (ORDER BY total_return DESC) AS best_rank,
           ROW_NUMBER() OVER (ORDER BY total_return ASC)  AS worst_rank
    FROM returns
)
SELECT CASE WHEN best_rank = 1 THEN 'Best' ELSE 'Worst' END AS label,
       r.ticker, c.name_en, ROUND(r.total_return * 100, 2) AS total_return_pct
FROM ranked r
JOIN companies c ON c.ticker = r.ticker
WHERE best_rank = 1 OR worst_rank = 1
ORDER BY total_return_pct DESC;

-- Best and worst calendar year for each stock (full years only).
WITH year_bounds AS (
    SELECT ticker, YEAR(date) AS yr, MIN(date) AS first_date, MAX(date) AS last_date
    FROM daily_prices
    GROUP BY ticker, YEAR(date)
),
year_close AS (
    SELECT yb.ticker, yb.yr, pl.close AS year_end_close
    FROM year_bounds yb
    JOIN daily_prices pl ON pl.ticker = yb.ticker AND pl.date = yb.last_date
),
annual AS (
    SELECT ticker, yr,
           year_end_close / LAG(year_end_close) OVER (PARTITION BY ticker ORDER BY yr) - 1 AS ret
    FROM year_close
)
SELECT ticker,
       MAX(CASE WHEN rn_best  = 1 THEN yr END)              AS best_year,
       ROUND(MAX(CASE WHEN rn_best  = 1 THEN ret END) * 100, 2) AS best_year_pct,
       MAX(CASE WHEN rn_worst = 1 THEN yr END)              AS worst_year,
       ROUND(MAX(CASE WHEN rn_worst = 1 THEN ret END) * 100, 2) AS worst_year_pct
FROM (
    SELECT ticker, yr, ret,
           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY ret DESC) AS rn_best,
           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY ret ASC)  AS rn_worst
    FROM annual
    WHERE ret IS NOT NULL
) t
GROUP BY ticker
ORDER BY ticker;


-- ---------------------------------------------------------------------
-- Q4. Risk: which stocks are the most volatile?
-- annual_volatility = std dev of daily returns * sqrt(250 trading days).
-- avg_volatility_30d = average of the rolling 30-day volatility.
-- max_drawdown = worst fall from a previous peak (close vs. running max).
-- ---------------------------------------------------------------------
WITH drawdown AS (
    SELECT ticker,
           MIN(close / peak - 1) AS max_drawdown
    FROM (
        SELECT ticker, close,
               MAX(close) OVER (PARTITION BY ticker ORDER BY date) AS peak
        FROM daily_prices
    ) p
    GROUP BY ticker
)
SELECT c.ticker,
       c.name_en,
       c.sector,
       ROUND(STDDEV_SAMP(m.daily_return) * SQRT(250) * 100, 2) AS annual_volatility_pct,
       ROUND(AVG(m.volatility_30d) * 100, 3)                    AS avg_volatility_30d_pct,
       ROUND(MAX(d.max_drawdown) * 100, 2)                      AS max_drawdown_pct
FROM daily_metrics m
JOIN companies c ON c.ticker = m.ticker
JOIN drawdown d  ON d.ticker = m.ticker
GROUP BY c.ticker, c.name_en, c.sector
ORDER BY annual_volatility_pct DESC;


-- ---------------------------------------------------------------------
-- Q5. Sector comparison (common window): average stock return and
-- average annualized volatility per sector.
-- ---------------------------------------------------------------------
WITH common_start AS (
    SELECT MAX(first_date) AS start_date
    FROM (SELECT MIN(date) AS first_date FROM daily_prices GROUP BY ticker) t
),
bounds AS (
    SELECT p.ticker, MIN(p.date) AS first_date, MAX(p.date) AS last_date
    FROM daily_prices p
    CROSS JOIN common_start cs
    WHERE p.date >= cs.start_date
    GROUP BY p.ticker
),
stock_stats AS (
    SELECT b.ticker,
           pl.close / pf.close - 1 AS total_return,
           (SELECT STDDEV_SAMP(m.daily_return) * SQRT(250)
              FROM daily_metrics m
             WHERE m.ticker = b.ticker AND m.date > b.first_date) AS annual_volatility
    FROM bounds b
    JOIN daily_prices pf ON pf.ticker = b.ticker AND pf.date = b.first_date
    JOIN daily_prices pl ON pl.ticker = b.ticker AND pl.date = b.last_date
)
SELECT c.sector,
       COUNT(*)                                       AS stocks,
       ROUND(AVG(s.total_return) * 100, 2)            AS avg_total_return_pct,
       ROUND(AVG(s.annual_volatility) * 100, 2)       AS avg_annual_volatility_pct,
       ROUND(AVG(s.total_return) / AVG(s.annual_volatility), 2) AS return_per_unit_risk
FROM stock_stats s
JOIN companies c ON c.ticker = s.ticker
GROUP BY c.sector
ORDER BY avg_total_return_pct DESC;


-- ---------------------------------------------------------------------
-- Q6a. Monthly trading volume per stock (for trend charts).
-- volume is NULL on days with bad source data (mostly Mar-Jun 2023), so
-- compare months by avg_daily_volume: total_volume undercounts those months.
-- ---------------------------------------------------------------------
SELECT ticker,
       DATE_FORMAT(date, '%Y-%m') AS month,
       SUM(volume)                AS total_volume,
       ROUND(AVG(volume))         AS avg_daily_volume,
       COUNT(*)                   AS trading_days,
       COUNT(volume)              AS days_with_volume
FROM daily_prices
GROUP BY ticker, DATE_FORMAT(date, '%Y-%m')
ORDER BY ticker, month;


-- ---------------------------------------------------------------------
-- Q6b. Seasonality: which calendar months have unusually high volume?
-- Each stock's monthly average is divided by its own overall average, so
-- big stocks do not dominate. 1.20 = 20% above that stock's normal level.
-- AVG() skips NULL volumes, so bad-data days do not drag months down.
-- ---------------------------------------------------------------------
WITH stock_avg AS (
    SELECT ticker, AVG(volume) AS avg_volume
    FROM daily_prices
    GROUP BY ticker
),
month_avg AS (
    SELECT ticker, MONTH(date) AS month_no, AVG(volume) AS avg_volume
    FROM daily_prices
    GROUP BY ticker, MONTH(date)
)
SELECT m.month_no,
       MONTHNAME(MAKEDATE(2000, 1) + INTERVAL (m.month_no - 1) MONTH) AS month_name,
       ROUND(AVG(m.avg_volume / s.avg_volume), 2)    AS relative_volume
FROM month_avg m
JOIN stock_avg s ON s.ticker = m.ticker
GROUP BY m.month_no
ORDER BY relative_volume DESC;


-- ---------------------------------------------------------------------
-- Q7. Correlation of daily returns between every pair of stocks
-- (Pearson, computed on days both stocks traded). 1 = move together,
-- 0 = unrelated, negative = move in opposite directions.
-- ---------------------------------------------------------------------
SELECT a.ticker AS ticker_1,
       b.ticker AS ticker_2,
       ROUND(
           (AVG(a.daily_return * b.daily_return) - AVG(a.daily_return) * AVG(b.daily_return))
           / (STDDEV_POP(a.daily_return) * STDDEV_POP(b.daily_return)),
       3) AS correlation,
       COUNT(*) AS shared_days
FROM daily_metrics a
JOIN daily_metrics b ON b.date = a.date AND a.ticker < b.ticker
WHERE a.daily_return IS NOT NULL
  AND b.daily_return IS NOT NULL
GROUP BY a.ticker, b.ticker
ORDER BY correlation DESC;

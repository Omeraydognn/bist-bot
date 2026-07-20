-- BıstBot: export paper-trading SQLite trades to the finance CSV schema.
-- Adjust table/column names to match your actual schema, then run:
--   sqlite3 -header -csv paper_trading.db < trades-export.sql > trades.csv
--
-- Assumes a `trades` table with one row per executed leg. If your bot stores a
-- round-trip as a single row (entry + exit), see the UNION ALL variant below.

-- ---------------------------------------------------------------------------
-- Variant A: one row per leg already (preferred)
-- ---------------------------------------------------------------------------
SELECT
    trade_id                               AS trade_id,
    ticker                                 AS ticker,
    UPPER(side)                            AS side,           -- BUY / SELL
    strftime('%Y-%m-%dT%H:%M:%S+03:00', filled_at) AS timestamp,
    quantity                               AS quantity,
    intended_price                         AS intended_price,
    fill_price                             AS fill_price,
    spread_at_fill                         AS spread_at_fill,
    target_pct                             AS target_pct,
    signal_source                          AS signal_source,
    date(filled_at)                        AS session_date,
    COALESCE(is_forced_close, 0)           AS is_forced_close,
    COALESCE(notes, '')                    AS notes
FROM trades
ORDER BY filled_at;

-- ---------------------------------------------------------------------------
-- Variant B: one row per round-trip (entry + exit in the same row).
-- Comment out Variant A and use this if that matches your schema.
-- ---------------------------------------------------------------------------
-- SELECT trade_id, ticker, 'BUY' AS side,
--        strftime('%Y-%m-%dT%H:%M:%S+03:00', entry_time) AS timestamp,
--        quantity, entry_intended_price AS intended_price, entry_price AS fill_price,
--        entry_spread AS spread_at_fill, target_pct, signal_source,
--        date(entry_time) AS session_date, 0 AS is_forced_close, notes
-- FROM positions
-- UNION ALL
-- SELECT trade_id, ticker, 'SELL' AS side,
--        strftime('%Y-%m-%dT%H:%M:%S+03:00', exit_time) AS timestamp,
--        quantity, exit_intended_price AS intended_price, exit_price AS fill_price,
--        exit_spread AS spread_at_fill, target_pct, signal_source,
--        date(exit_time) AS session_date, forced_close AS is_forced_close, notes
-- FROM positions
-- ORDER BY trade_id, side;

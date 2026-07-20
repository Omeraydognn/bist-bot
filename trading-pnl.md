# Trading P&L (replaces `/income-statement` for BıstBot)

Produces a trading-account P&L in **TL** instead of a corporate income statement.
Read `FINANCE_CONTEXT.md` first. Data comes from the exported `trades.csv`
(`trades-schema.md`).

## Reporting periods

- `session` — one BIST trading day (10:00–18:00).
- `daily` — calendar day (usually = session).
- `monthly` — end-of-month trading review (this is BıstBot's "month-end close").
- `mtd` / `ytd` — month/year to date.

Always show the current period **and** a comparison (prior day / prior month).

## Statement format

```
BıstBot TRADING P&L
Period: [description]                               Currency: TL

                                        Current      Prior       Δ (TL)     Δ (%)
                                        ---------    ---------   ---------  -------
GROSS TRADING RESULT
  Gross realized P&L (winning legs)     ₺ X.XXX,XX   ₺ X.XXX,XX
  Gross realized P&L (losing legs)     (₺   XXX,XX) (₺   XXX,XX)
  Gross realized P&L, net              ₺ X.XXX,XX   ₺ X.XXX,XX

TRADING COSTS  (commission = 0)
  Slippage cost                        (₺   XXX,XX) (₺   XXX,XX)
  Spread cost (half-spread × 2 legs)   (₺   XXX,XX) (₺   XXX,XX)
  Total trading cost                   (₺   XXX,XX) (₺   XXX,XX)
                                        ---------    ---------
NET REALIZED P&L                        ₺ X.XXX,XX   ₺ X.XXX,XX

  Unrealized P&L (open positions MTM)   ₺   XXX,XX   ₺   XXX,XX
                                        ---------    ---------
TOTAL P&L (realized + unrealized)       ₺ X.XXX,XX   ₺ X.XXX,XX

MEMO METRICS
  Trades closed                         N            N
  Win rate                              XX%          XX%
  Avg return / trade                    X,XX%        X,XX%
  Return on 100.000 TL portfolio        X,XX%        X,XX%
  Cost as % of gross                    XX%          XX%
```

## Method

1. Load `trades.csv`. Pair legs by `trade_id` into round-trips (BUY then SELL, or
   short SELL then BUY). Unclosed legs → open positions.
2. Per round-trip compute, in TL:
   - **Gross realized** = `(sell_fill − buy_fill) × quantity`.
   - **Slippage cost** = buy-leg + sell-leg slippage (see `trades-schema.md` sign rule).
   - **Spread cost** = `spread_at_fill/2 × quantity` per leg, summed (skip if blank).
   - **Net realized** = gross − slippage − spread.
3. Aggregate to the period. Split gross into winning vs losing legs for the top block.
4. **Unrealized**: for still-open positions, MTM against the latest real price
   (`is_forced_close` should make this near-zero intraday). Never invent a price —
   if no current price is available, show unrealized as "n/a".
5. Per-ticker breakdown: repeat the table grouped by `ticker` (ASELS first).

## Guardrails

- Show **gross and net** side by side — with zero commission, spread+slippage is the
  whole cost story and must be visible.
- Flag any period where **cost > 50% of gross** — the 1–2% edge is thin; costs can eat it.
- All outputs are for review by a qualified professional; this is not financial advice.

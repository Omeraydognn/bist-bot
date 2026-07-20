# Trading close checklist (replaces `/close-management` for BıstBot)

Corporate month-end close, reframed for a trading account. Two cadences: **daily
session close** and **monthly review**.

## Daily session close (after 18:00 BIST)

1. Confirm all positions closed (`is_forced_close`) — no unintended overnight risk.
2. Export the day's trades (`trades-export.sql` → `trades.csv`).
3. **Reconcile** bot ledger vs broker fills for the day (`trade-reconciliation.md`).
   Resolve any missing fills / forced-close gaps before anything else.
4. Generate the daily **Trading P&L** (`trading-pnl.md`): gross → cost → net, win rate.
5. Run **return vs target** (`return-vs-target-variance.md`) — did execution keep the edge?
6. Log net P&L, cost %, and any anomaly for the trend.

## Monthly review (BıstBot's "month-end close")

1. Reconcile the full month; ending cash must tie to the broker statement.
2. Monthly Trading P&L with prior-month comparison, per ticker.
3. Month return on the 100.000 TL portfolio; cost as % of gross trend.
4. Return-vs-target by ticker and signal source — which signals/symbols earn their edge.
5. Refresh the **accountant handoff packet** (`cost-tax-accounting.md`).
6. Note strategy/config changes (new tickers added) that affect the numbers.

## Dependencies (order matters)

```
Positions closed → Export → Reconcile → P&L → Variance → Tax packet
```
Never run P&L or variance on unreconciled data. Real data only — if reconciliation
can't complete, stop and report rather than closing on estimates.

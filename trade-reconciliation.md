# Trade reconciliation (replaces `/reconciliation` for BıstBot)

The corporate skill reconciles GL to subledger/bank. For BıstBot, reconcile the
**bot's recorded trade ledger** (SQLite → `trades.csv`) against the **broker /
exchange fills and account statement**, which are the source of truth.

## What to compare

| Bot ledger (what the bot *thinks* happened) | Broker statement (what *actually* happened) |
|---------------------------------------------|---------------------------------------------|
| `trade_id`, `ticker`, `side`, `quantity`    | Executed order id, symbol, side, filled qty |
| `fill_price`, `timestamp`                    | Average fill price, execution time          |
| Derived net P&L                              | Realized P&L / cash movement on statement   |

## Process

1. Pull the bot ledger for the period from `trades.csv`.
2. Pull the broker's executed-orders report / account statement for the same period.
3. Match legs by order id if available, else by (ticker, side, timestamp ±, quantity).
4. Compare, per matched leg: quantity, fill price, and time.
5. Reconcile ending cash: `opening_cash + Σ net P&L (ledger) == broker ending balance`.

## Reconciling-item categories (flag and age each)

- **Missing fill** — signal/order in the ledger with no broker execution (rejected,
  not routed, or session closed). *High priority — the bot's P&L is overstated.*
- **Phantom ledger entry** — broker fill with no ledger row (logging gap).
- **Price mismatch** — same trade, different fill price → measures true slippage vs
  what the bot recorded; feed the delta into `cost-tax-accounting.md`.
- **Quantity mismatch** — partial fill the bot booked as full.
- **Timing difference** — fill recorded in a different session/day (near open/close).
- **Forced-close gaps** — end-of-session auto-close that didn't execute → unintended
  overnight position. *High priority — real overnight risk.*

## Reconciliation summary format

```
TRADE RECONCILIATION — [period]                                      (TL)

Bot ledger net P&L                                     ₺ X.XXX,XX
  Add: broker fills missing from ledger               ₺   XXX,XX
  Less: ledger entries with no broker fill            (₺  XXX,XX)
  +/- price/quantity mismatches                        ₺   XX,XX
                                                        ---------
Reconciled net P&L (per broker)                        ₺ X.XXX,XX

Broker statement ending cash                           ₺ XX.XXX,XX
Unreconciled difference                                ₺     0,00   ✅ / ⚠️
```

## Escalation

- Any **missing fill** or **forced-close gap** → surface immediately; these are real
  money / real risk, not bookkeeping noise.
- Unreconciled difference **> 0** after categorizing → do not sign off; investigate.
- Real data only — if the broker statement isn't available, report "not reconcilable"
  rather than assuming the ledger is correct.

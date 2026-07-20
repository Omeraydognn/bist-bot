# Trades export schema

The finance skills and the dashboard consume a single CSV: **one row per fill/leg**
(a buy or a sell). A round-trip trade is two rows sharing a `trade_id`. All money
in **TL**. Times in Europe/Istanbul.

## Columns

| Column | Type | Required | Notes |
|--------|------|----------|-------|
| `trade_id` | string | yes | Groups the buy and sell legs of one round-trip. |
| `ticker` | string | yes | BIST symbol, e.g. `ASELS`. |
| `side` | enum | yes | `BUY` or `SELL`. |
| `timestamp` | ISO 8601 | yes | Fill time, e.g. `2026-07-20T10:32:15+03:00`. |
| `quantity` | number | yes | Shares (lots) filled on this leg. |
| `intended_price` | number | yes | Signal/decision price the bot wanted (for slippage). |
| `fill_price` | number | yes | Actual executed price. |
| `spread_at_fill` | number | no | Bid-ask spread in TL at fill time (for spread cost). |
| `target_pct` | number | no | Target move for the trade, e.g. `0.015` = 1.5%. Defaults to signal config. |
| `signal_source` | string | no | e.g. `RSI+MACD`, `bollinger`, `orderbook`. |
| `session_date` | date | yes | Trading day `YYYY-MM-DD` (for daily grouping). |
| `is_forced_close` | bool | no | `true` if this leg is an end-of-session forced close. |
| `notes` | string | no | Free text. |

## Derived fields (computed by skills/dashboard — do not store)

- **Slippage (TL)** per leg = `(fill_price − intended_price) × quantity`, signed so
  that a worse-than-intended fill is a cost. For a BUY, cost = `(fill − intended)`;
  for a SELL, cost = `(intended − fill)`.
- **Spread cost (TL)** per leg ≈ `spread_at_fill / 2 × quantity` (half-spread paid on
  each side). Use only when `spread_at_fill` is present.
- **Gross realized P&L (TL)** per round-trip = `(sell_fill − buy_fill) × quantity`.
- **Net realized P&L (TL)** = gross − slippage cost − spread cost. (Commission = 0.)
- **Realized return %** = net realized P&L ÷ (buy_fill × quantity).

## Minimal example (two legs, one round-trip)

```csv
trade_id,ticker,side,timestamp,quantity,intended_price,fill_price,spread_at_fill,target_pct,signal_source,session_date,is_forced_close,notes
T-0001,ASELS,BUY,2026-07-20T10:32:15+03:00,100,182.40,182.50,0.20,0.015,RSI+MACD,2026-07-20,false,
T-0001,ASELS,SELL,2026-07-20T11:05:41+03:00,100,185.10,185.00,0.20,0.015,RSI+MACD,2026-07-20,false,take-profit
```

That trade: gross = (185.00 − 182.50) × 100 = **250,00 TL**; buy slippage =
(182.50 − 182.40) × 100 = 10 TL; sell slippage = (185.10 − 185.00) × 100 = 10 TL;
spread cost = 0.20/2 × 100 × 2 legs = 20 TL; **net = 250 − 10 − 10 − 20 = 210,00 TL**;
return = 210 ÷ 18.250 = **1,15%**.

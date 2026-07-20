# Return vs target variance (replaces `/variance-analysis` for BıstBot)

The corporate skill decomposes budget-vs-actual into price/volume/mix. For BıstBot,
"budget" is the **1–2% intraday target** and "actual" is what each trade delivered.
Decompose the gap into trading drivers.

## Core comparison

For each closed round-trip:

```
Target return    = target_pct               (e.g. 1,50%)
Actual return %  = net_realized_pnl / (buy_fill × quantity)
Variance         = Actual − Target          (negative = underperformed)
```

Aggregate variance = Σ (actual TL) − Σ (target TL), where target TL =
`target_pct × buy_fill × quantity`.

## Driver decomposition (trading analogue of price/volume/mix)

Break each trade's shortfall vs its target into additive TL effects:

```
Target P&L            = target_pct × buy_fill × qty

(1) Exit-capture effect = (actual_exit − buy_fill)×qty − Target P&L (gross)
        → did price actually reach the target move? (market/timing)
(2) Slippage effect     = −(buy_slippage + sell_slippage)        (execution)
(3) Spread effect       = −(spread cost)                          (execution)

Actual net P&L = Target P&L + Exit-capture + Slippage + Spread
Verify: the three effects sum to (Actual net − Target P&L).
```

- **Exit-capture** = strategy/market: the signal was right or wrong about the move.
- **Slippage + Spread** = execution quality: how much of the edge microstructure ate.
  With commission = 0, these two ARE the cost side and deserve their own line.

## Segment (mix) views

Repeat the decomposition grouped by:
- **Ticker** (ASELS vs others) — which symbols hit target.
- **Signal source** (`RSI+MACD`, `bollinger`, `orderbook`) — which signals earn their edge.
- **Timeframe / time-of-day** — flag the risky open/close windows separately.

## Output format

```
RETURN vs TARGET — [period]                                          (TL)

Σ Target P&L (all trades at target)                    ₺ X.XXX,XX
Σ Actual net P&L                                       ₺ X.XXX,XX
Total variance                                        (₺   XXX,XX)  ⚠️
  ├─ Exit-capture effect (market/strategy)            (₺   XXX,XX)
  ├─ Slippage effect (execution)                      (₺   XXX,XX)
  └─ Spread effect (execution)                        (₺    XX,XX)

Trades hitting target: XX / N (XX%)
Worst signal source by variance: [name]  (₺ -XXX,XX)
```

Materiality: comment on any driver or segment explaining **> 20%** of total variance,
or any single trade whose slippage exceeded its target P&L (execution destroyed the edge).
Not financial advice — for review by a qualified professional.

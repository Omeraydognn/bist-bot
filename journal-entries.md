# Trade booking entries (replaces `/journal-entry` for BıstBot)

Optional double-entry view of trading activity, in TL, for anyone who wants the
paper portfolio to tie out like a book. Skip if you only need P&L.

Accounts: `Cash`, `Trading Securities` (position at cost), `Realized P&L`,
`Unrealized P&L (MTM)`, `Trading Cost` (slippage + spread).

## Buy fill
```
Dr Trading Securities        buy_fill × qty
Dr Trading Cost              slippage + half-spread
   Cr Cash                   (buy_fill × qty) + costs
```

## Sell fill (close)
```
Dr Cash                      sell_fill × qty
Dr Trading Cost              slippage + half-spread
   Cr Trading Securities     buy_fill × qty        (release cost basis)
   Cr Realized P&L           net realized P&L
```

## End-of-session mark-to-market (open positions only)
```
Dr/Cr Trading Securities     (current_price − buy_fill) × qty
   Cr/Dr Unrealized P&L      same
```
Reverse this at the next session open. If BıstBot forces close every session,
open positions and this entry should normally be zero.

## Notes
- Commission = 0, so there is no commission line — only `Trading Cost`.
- Use **reconciled** fills (per broker) for anything that feeds tax records.
- Not financial advice; review before relying on it.

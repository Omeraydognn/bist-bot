# BıstBot Finance Pack

Customizes the **`finance` plugin** for the BıstBot intraday trading project on
Borsa İstanbul. It reframes the plugin's corporate-accounting workflows
(reconciliation, income statement, variance, journal entries, close) for a
**trading account in TL**, commission-free, where spread and slippage are the costs.

## How to use it

1. **Put this folder where your finance work happens** (e.g. inside your BıstBot
   project, or a connected Cowork folder). Keep the files together.
2. **Point the finance skills at it.** When you run a finance skill, tell Claude:
   *"Use the BıstBot finance context in `FINANCE_CONTEXT.md`."* It reads that file
   and follows the matching reference (`trading-pnl.md`, `trade-reconciliation.md`,
   `return-vs-target-variance.md`, `cost-tax-accounting.md`, …).
3. **Export your real trades:** run `trades-export.sql` against the bot's SQLite to
   produce `trades.csv` (schema in `trades-schema.md`).
4. **Open `pnl-dashboard.html`** in a browser and drop in `trades.csv` for a live
   P&L / cost / return-vs-target view. Click *Load format demo* to preview the layout.

> To make this permanent inside the plugin itself (editing the saved skills), use
> **Settings → Capabilities** in the desktop app — skill files can't be edited from
> a chat session. This pack is the portable, no-install alternative and works today.

## What's inside

| File | Replaces / supports | Purpose |
|------|--------------------|---------|
| `FINANCE_CONTEXT.md` | entry point | Conventions + corporate→trading mapping. Read first. |
| `trading-pnl.md` | `/income-statement` | Trading P&L in TL, gross→net, per-ticker. |
| `trade-reconciliation.md` | `/reconciliation` | Bot ledger vs broker fills. |
| `return-vs-target-variance.md` | `/variance-analysis` | Actual return vs 1–2% target, driver split. |
| `cost-tax-accounting.md` | costing + tax | Spread/slippage model + accountant checklist. |
| `journal-entries.md` | `/journal-entry` | Trade / MTM / session-close bookings. |
| `close-management.md` | `/close-management` | Daily + monthly trading close checklist. |
| `trades-schema.md` | data contract | Expected CSV columns. |
| `trades-export.sql` | data | SQLite → CSV export. |
| `pnl-dashboard.html` | dashboard | Interactive, runs fully in-browser on your CSV. |

**Real data only.** Nothing here fabricates trades or prices; every workflow runs
on your exported data. **Not financial, tax, or investment advice** — review with a
qualified professional.

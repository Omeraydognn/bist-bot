# BıstBot — Finance Context

> **Entry point for the `finance` plugin.** When any finance skill runs
> (`/reconciliation`, `/income-statement`, `/variance-analysis`,
> `/journal-entry`, `/close-management`), read this file first and adapt the
> workflow to a **trading account**, not a corporate GL. The reference files in
> this folder redefine each workflow for BıstBot.

> **Not financial, tax, or investment advice.** These files help organize and
> report on trading activity. All figures, and especially the tax notes, must be
> reviewed by a qualified accountant/financial professional before use.

---

## What BıstBot is

An algorithmic **intraday trading bot** for **Borsa İstanbul (BIST)**. It
monitors stocks across multiple timeframes (15m / 30m / 1h / 1d), looks for
small intraday moves (**target 1–2%**), and fires frequent buy/sell signals for
consistent daily returns. First target ticker: **ASELSAN (ASELS)**. The design
is ticker-agnostic — new stocks are added by config, so all finance workflows
here must generalize across any BIST ticker.

## Finance conventions (apply everywhere)

| Item | Convention |
|------|-----------|
| **Reporting currency** | Turkish Lira (**TRY / TL**). Format `₺1.234,56` or `1.234,56 TL`. |
| **Reporting entity** | The trading account (paper: 100.000 TL virtual portfolio, persistent SQLite). |
| **Period** | Primarily a **trading session** (BIST hours 10:00–18:00) and **calendar day/month**. "Month-end close" = end-of-month trading review. |
| **Commission** | **Zero** at the brokerage. Do **not** model commission. |
| **Real costs** | **Spread** and **slippage** are the primary cost factors — always account for them. |
| **Positions** | Intraday; **forced close at end of session**. Minimal overnight/unrealized carry, but support it when present. |
| **Data integrity** | **Real data only.** Never fabricate trades, prices, or fills. If a data source is missing, say so and stop — do not fill with synthetic numbers. |

## Mapping: corporate finance → trading finance

The finance plugin speaks in GL/subledger terms. Translate as follows:

| Plugin concept | BıstBot equivalent |
|----------------|--------------------|
| General Ledger (GL) | Bot's recorded trade ledger (SQLite `trades` table) |
| Subledger / bank statement | Broker/exchange **fills & account statement** (source of truth) |
| GL-to-subledger reconciliation | **Trade reconciliation** — bot ledger vs broker fills → `trade-reconciliation.md` |
| Income statement / P&L | **Trading P&L** (realized + unrealized, in TL) → `trading-pnl.md` |
| Revenue | Gross trading gains (winning-side proceeds) |
| COGS / cost of sales | **Slippage + spread cost** → `cost-tax-accounting.md` |
| Budget vs actual variance | **Actual return vs 1–2% target** variance → `return-vs-target-variance.md` |
| Price/Volume decomposition | Entry-price / exit-price / size / slippage decomposition |
| Journal entry | Trade booking, mark-to-market, and end-of-session close entries → `journal-entries.md` |
| Month-end close checklist | End-of-month trading close checklist → `close-management.md` |

## Data source

There is no ERP or data-warehouse connector. The source data is the bot's local
**SQLite** paper-trading database. Export it to CSV with the query in
`trades-export.sql`, matching the schema in `trades-schema.md`. Every skill and
the dashboard consume that CSV. If the CSV is not provided, ask for it — do not
proceed on assumptions.

## Files in this pack

- `trading-pnl.md` — P&L statement format for a trading account (TL, per-ticker, gross→net).
- `trade-reconciliation.md` — reconcile bot ledger vs broker fills; reconciling-item categories.
- `return-vs-target-variance.md` — actual return vs 1–2% target, driver decomposition.
- `cost-tax-accounting.md` — spread/slippage cost model + Turkish tax items for an accountant.
- `journal-entries.md` — trade, mark-to-market, and session-close booking conventions.
- `close-management.md` — daily and month-end trading close checklist.
- `trades-schema.md` — expected CSV columns.
- `trades-export.sql` — SQLite → CSV export helper.
- `pnl-dashboard.html` — interactive dashboard that runs on the exported CSV.

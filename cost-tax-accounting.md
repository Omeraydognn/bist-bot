# Cost & tax accounting for BıstBot

Two jobs: (1) a precise **cost model** for a commission-free intraday strategy, and
(2) a **tax checklist** to hand an accountant. Read `FINANCE_CONTEXT.md` first.

> **Not tax or financial advice.** Turkish tax rules on securities change and depend
> on the instrument, holding period, and investor status. Everything in the tax
> section below is a **list of questions to confirm with a licensed accountant /
> mali müşavir** — not a determination. Rates are intentionally left blank; verify
> current figures before use.

## 1. Cost model (commission = 0)

Because the brokerage charges no commission, **all** cost is microstructure:

| Cost | Definition (TL) | Where measured |
|------|-----------------|----------------|
| **Slippage** | `(fill_price − intended_price) × qty`, signed as a cost per side | `intended_price` vs `fill_price` in the ledger, or ledger vs broker fill in recon |
| **Spread (half-spread)** | `spread_at_fill / 2 × qty` per leg | `spread_at_fill` at execution |
| **Financing / borrow** | only if positions are held overnight or short | broker statement |
| **Taxes on gains** | see section 2 | accountant |

Track these as the "cost of sales" line in `trading-pnl.md`. Report:
- Cost per trade (TL) and as % of gross P&L.
- Cost per share and per ticker — thin-spread names are more viable for a 1–2% edge.
- **Break-even move**: minimum % move needed just to cover spread+slippage. If a
  ticker's typical spread implies a break-even near your 1–2% target, flag it.

## 2. Turkish tax checklist (for your accountant)

Items to resolve — do not assume:

- **Instrument classification.** Gains on BIST-listed **equities** vs other
  instruments (ETFs, warrants, derivatives) are taxed differently. Confirm how each
  ticker BıstBot trades is classified.
- **Withholding (stopaj).** Ask whether a withholding rate applies to your equity
  trades and at what rate for your investor status (resident individual vs other),
  and whether it is final or creditable.
- **Holding-period / exemption conditions.** Ask whether any exemption applies to
  BIST share disposals for your profile, and what conditions (holding period, share
  type) attach. Intraday trading likely fails long-hold exemptions — confirm.
- **BSMV (banking & insurance transaction tax).** Generally targets banks/brokers,
  not typical individual share trades — confirm it does not apply to your account.
- **Annual declaration.** Whether net trading gains must be declared on an annual
  income tax return, how losses offset gains, and the loss carry rules.
- **Wash-sale / same-day netting.** How frequent same-ticker round-trips are netted
  for tax; high-frequency intraday flow may aggregate.
- **Record-keeping.** The reconciled broker statement (not the bot ledger) is the
  supportable tax record. Keep exports per session.

## 3. Accountant handoff packet

When preparing for tax, produce from **reconciled** data:
1. Realized gains/losses by ticker and month (net of spread/slippage), TL.
2. Total winning vs losing trades and net.
3. The broker account statement for the period as backup.
4. This checklist with the accountant's answers filled in.

Everything here is for review by a qualified professional before any filing.

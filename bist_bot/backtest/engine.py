"""
Basit backtest motoru.

Gecmis fiyat verisinde her gun "sanki o gunmus gibi" teknik analiz
yapip AL/SAT/TUT karari uretir, hayali bir portfoyle bu kararlari
uygular ve sonucta getiriyi raporlar.

Not: Bu ilk versiyon SADECE teknik analiz sinyaliyle calisir (haber
verisinin gecmise donuk/tarihli hali olmadigi icin). News/AKD gecmis
veri toplandikca backtest'e eklenecek.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bist_bot.analysis import technical


@dataclass
class BacktestResult:
    symbol: str
    trades: list = field(default_factory=list)
    final_equity: float = 0.0
    total_return_pct: float = 0.0
    num_trades: int = 0
    win_rate_pct: float = 0.0


def run_backtest(
    symbol: str,
    price_rows: list[dict],
    buy_threshold: float = 0.3,
    sell_threshold: float = -0.3,
    starting_cash: float = 100_000.0,
    min_window: int = 30,
) -> BacktestResult:
    if len(price_rows) < min_window + 1:
        return BacktestResult(symbol=symbol, final_equity=starting_cash)

    cash = starting_cash
    shares = 0.0
    entry_price = None
    trades = []

    for i in range(min_window, len(price_rows)):
        window = price_rows[: i + 1]
        today = price_rows[i]
        result = technical.analyze(window)
        score = result["score"]
        price = today["close"]
        if price is None:
            continue

        if score >= buy_threshold and shares == 0:
            shares = cash / price
            cash = 0.0
            entry_price = price
            trades.append({"date": today["date"], "action": "AL", "price": price, "score": round(score, 3)})

        elif score <= sell_threshold and shares > 0:
            cash = shares * price
            pnl_pct = (price - entry_price) / entry_price * 100 if entry_price else 0
            trades.append(
                {
                    "date": today["date"],
                    "action": "SAT",
                    "price": price,
                    "score": round(score, 3),
                    "pnl_pct": round(pnl_pct, 2),
                }
            )
            shares = 0.0
            entry_price = None

    # Sonda hala hisse elde tutuluyorsa son fiyattan degerle (kagit uzerinde)
    last_price = price_rows[-1]["close"]
    if shares > 0 and last_price:
        final_equity = shares * last_price
    else:
        final_equity = cash

    total_return_pct = (final_equity - starting_cash) / starting_cash * 100

    closed_trades = [t for t in trades if t["action"] == "SAT"]
    wins = [t for t in closed_trades if t.get("pnl_pct", 0) > 0]
    win_rate = (len(wins) / len(closed_trades) * 100) if closed_trades else 0.0

    return BacktestResult(
        symbol=symbol,
        trades=trades,
        final_equity=round(final_equity, 2),
        total_return_pct=round(total_return_pct, 2),
        num_trades=len(closed_trades),
        win_rate_pct=round(win_rate, 2),
    )

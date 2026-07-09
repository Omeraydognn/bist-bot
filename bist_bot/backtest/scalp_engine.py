"""
Scalping backtest motoru - MALIYET DAHIL.

Klasik backtest'ten farki:
  * Her islemde komisyon + spread + kayma DUSULUR (gercekci sonuc)
  * Stop-loss ve take-profit seviyeleri mum ici high/low ile test edilir
  * Ayni gun al-sat dongusune izin verir (scalping mantigi)

Bu motor sana su soruyu net cevaplar:
  "Bu %1-2 hedefli strateji, maliyetler dusuldukten sonra
   gercekten para kazandiriyor mu, yoksa sadece kagit uzerinde mi karli?"
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bist_bot.analysis.scalping import analyze_scalp, CostModel


@dataclass
class ScalpBacktestResult:
    symbol: str
    trades: list = field(default_factory=list)
    starting_cash: float = 100_000.0
    final_equity: float = 0.0
    total_return_pct: float = 0.0
    total_cost_paid: float = 0.0     # maliyete giden toplam para
    num_trades: int = 0
    win_rate_pct: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0


def run_scalp_backtest(
    symbol: str,
    price_rows: list[dict],
    cost_model: CostModel | None = None,
    min_net_edge_pct: float = 0.30,
    starting_cash: float = 100_000.0,
    min_window: int = 25,
) -> ScalpBacktestResult:
    cost_model = cost_model or CostModel()
    one_side_cost = cost_model.commission_pct_per_side + (cost_model.spread_pct + cost_model.slippage_pct) / 2

    cash = starting_cash
    shares = 0.0
    entry_price = None
    entry_stop = None
    entry_target = None
    trades = []
    total_cost_paid = 0.0

    for i in range(min_window, len(price_rows)):
        window = price_rows[: i + 1]
        bar = price_rows[i]
        price = bar["close"]
        if price is None:
            continue

        # ---- Acik pozisyon varsa once stop/target kontrolu (mum ici) ----
        if shares > 0 and entry_price:
            hit_stop = bar["low"] is not None and bar["low"] <= entry_price * (1 - entry_stop / 100)
            hit_target = bar["high"] is not None and bar["high"] >= entry_price * (1 + entry_target / 100)

            exit_price = None
            exit_reason = None
            if hit_stop and hit_target:
                # Ayni mumda ikisi de vurulduysa muhafazakar davran: stop sayilir
                exit_price = entry_price * (1 - entry_stop / 100)
                exit_reason = "stop_loss(ayni mum)"
            elif hit_stop:
                exit_price = entry_price * (1 - entry_stop / 100)
                exit_reason = "stop_loss"
            elif hit_target:
                exit_price = entry_price * (1 + entry_target / 100)
                exit_reason = "take_profit"

            if exit_price:
                gross = shares * exit_price
                fee = gross * one_side_cost / 100
                cash = gross - fee
                total_cost_paid += fee
                pnl_pct = (exit_price - entry_price) / entry_price * 100 - 2 * one_side_cost
                trades.append({
                    "date": bar["date"], "action": "SAT", "price": round(exit_price, 2),
                    "reason": exit_reason, "pnl_net_pct": round(pnl_pct, 2),
                })
                shares = 0.0
                entry_price = None
                continue

        # ---- Pozisyon yoksa yeni sinyal ara ----
        if shares == 0:
            signal = analyze_scalp(window, cost_model=cost_model, min_net_edge_pct=min_net_edge_pct)
            if signal.action == "AL":
                fee = cash * one_side_cost / 100
                total_cost_paid += fee
                shares = (cash - fee) / price
                cash = 0.0
                entry_price = price
                entry_stop = signal.stop_loss_pct
                entry_target = signal.take_profit_pct
                trades.append({
                    "date": bar["date"], "action": "AL", "price": round(price, 2),
                    "strategy": signal.strategy, "beklenen_net_pct": signal.expected_net_pct,
                })
            # NOT: bu ilk surumde acik (short) satis yok - BIST'te acik satis
            # kisitlari ve ekstra maliyetleri nedeniyle once long-only dogrulanir.

    # Kapanmamis pozisyonu son fiyattan degerle
    last_price = price_rows[-1]["close"]
    final_equity = shares * last_price if shares > 0 and last_price else cash

    closed = [t for t in trades if t["action"] == "SAT"]
    wins = [t for t in closed if t["pnl_net_pct"] > 0]
    losses = [t for t in closed if t["pnl_net_pct"] <= 0]

    return ScalpBacktestResult(
        symbol=symbol,
        trades=trades,
        starting_cash=starting_cash,
        final_equity=round(final_equity, 2),
        total_return_pct=round((final_equity - starting_cash) / starting_cash * 100, 2),
        total_cost_paid=round(total_cost_paid, 2),
        num_trades=len(closed),
        win_rate_pct=round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
        avg_win_pct=round(sum(t["pnl_net_pct"] for t in wins) / len(wins), 2) if wins else 0.0,
        avg_loss_pct=round(sum(t["pnl_net_pct"] for t in losses) / len(losses), 2) if losses else 0.0,
    )

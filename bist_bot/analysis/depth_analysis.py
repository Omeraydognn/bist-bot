"""
Derinlik (order book / kademe) ANALIZ mantigi.

Veri cekici (depth_fetcher) veriyi getirir; bu modul onu yorumlar.
Broker API baglandiginda dogrudan calisacak sekilde hazir.

Okudugu sinyaller:
  1) IMBALANCE (dengesizlik): toplam alis lotu / satis lotu orani.
     Alis tarafi agirsa fiyat yukari itilme egiliminde -> pozitif skor.
  2) DUVAR (wall) tespiti: tek kademede olagandisi buyuk emir.
     Fiyatin ustundeki satis duvari direnc, altindaki alis duvari destek.
  3) SPREAD durumu: makas normalden genisse likidite zayif -> islem
     riskli, skor guven katsayisi dusurulur.

Girdi formati (depth_fetcher ile ayni):
  [{"level": 1, "bid_price": ..., "bid_qty": ..., "ask_price": ..., "ask_qty": ...}, ...]
"""
from __future__ import annotations

import numpy as np


def analyze_depth(depth_rows: list[dict] | None, wall_threshold: float = 3.0) -> dict:
    """
    wall_threshold: bir kademedeki miktar, tum kademelerin ortalamasinin
    bu kati kadarsa "duvar" sayilir.
    """
    if not depth_rows:
        return {"score": None, "reason": "Derinlik verisi yok (broker API bekleniyor)", "details": {}}

    bids = [(r["bid_price"], r["bid_qty"]) for r in depth_rows if r.get("bid_qty")]
    asks = [(r["ask_price"], r["ask_qty"]) for r in depth_rows if r.get("ask_qty")]
    if not bids or not asks:
        return {"score": None, "reason": "Derinlik verisi eksik", "details": {}}

    total_bid = sum(q for _, q in bids)
    total_ask = sum(q for _, q in asks)

    # 1) Imbalance: -1 (satis baskin) .. +1 (alis baskin)
    imbalance = (total_bid - total_ask) / (total_bid + total_ask) if (total_bid + total_ask) else 0.0

    # 2) Duvar tespiti
    all_qty = [q for _, q in bids] + [q for _, q in asks]
    avg_qty = float(np.mean(all_qty)) if all_qty else 0.0
    bid_walls = [(p, q) for p, q in bids if avg_qty and q >= wall_threshold * avg_qty]
    ask_walls = [(p, q) for p, q in asks if avg_qty and q >= wall_threshold * avg_qty]

    wall_score = 0.0
    if bid_walls and not ask_walls:
        wall_score = 0.3   # altta destek duvari var, ustte engel yok
    elif ask_walls and not bid_walls:
        wall_score = -0.3  # ustte satis duvari var
    # ikisi de varsa sikismis piyasa -> 0

    # 3) Spread genisligi (en iyi kademeden)
    best_bid = max(p for p, _ in bids)
    best_ask = min(p for p, _ in asks)
    spread_pct = (best_ask - best_bid) / best_bid * 100 if best_bid else 0.0
    liquidity_penalty = 0.5 if spread_pct > 0.3 else 1.0   # genis makas guveni yariya indirir

    score = float(np.clip((imbalance * 0.7 + wall_score) * liquidity_penalty, -1, 1))

    return {
        "score": round(score, 3),
        "reason": f"Kademe dengesizligi {imbalance:+.2f}, "
                  f"{len(bid_walls)} alis / {len(ask_walls)} satis duvari, makas %{spread_pct:.2f}",
        "details": {
            "imbalance": round(imbalance, 3),
            "toplam_alis_lot": total_bid,
            "toplam_satis_lot": total_ask,
            "alis_duvarlari": bid_walls,
            "satis_duvarlari": ask_walls,
            "spread_pct": round(spread_pct, 3),
        },
    }

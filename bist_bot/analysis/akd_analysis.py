"""
AKD (Araci Kurum Dagilimi) ve Takas ANALIZ mantigi.

Veri geldiginde (Matriks/terminal/manuel giris) su sorulara cevap uretir:
  1) NET ALICI KIM? Buyuk/kurumsal agirlikli kurumlar mi topluyor,
     yoksa kucuk yatirimci agirlikli kurumlar mi? Kurumsal toplama
     genelde daha kalici yon sinyalidir.
  2) YOGUNLASMA: Alimlar tek kuruma mi yigilmis (takas yogunlasmasi)?
     Tek elden toplama = bilincli pozisyonlanma isareti olabilir.
  3) YABANCI TAKAS ORANI degisimi: yabanci payi artiyorsa orta vade
     pozitif okunur (BIST'te klasik gosterge).

Girdi formati:
  akd_rows: [{"broker_or_group": "Kurum A", "net_volume": +1500000}, ...]
            (pozitif = net alis, negatif = net satis, lot veya TL)
  yabanci_takas: {"onceki_pct": 55.2, "guncel_pct": 55.9}  (opsiyonel)
"""
from __future__ import annotations

import numpy as np


def analyze_akd(
    akd_rows: list[dict] | None,
    yabanci_takas: dict | None = None,
    kurumsal_brokers: set[str] | None = None,
) -> dict:
    if not akd_rows and not yabanci_takas:
        return {"score": None, "reason": "AKD/takas verisi yok (Faz entegrasyonu bekleniyor)", "details": {}}

    sub = {}
    details = {}

    if akd_rows:
        net_total = sum(r["net_volume"] for r in akd_rows)
        buys = [r for r in akd_rows if r["net_volume"] > 0]
        sells = [r for r in akd_rows if r["net_volume"] < 0]
        gross = sum(abs(r["net_volume"]) for r in akd_rows) or 1

        # 1) Genel net akis: -1..+1
        sub["net_akis"] = round(float(np.clip(net_total / gross, -1, 1)) * 0.5, 3)

        # 2) Yogunlasma: en buyuk alicinin toplam alis icindeki payi
        if buys:
            total_buy = sum(r["net_volume"] for r in buys)
            top_buyer = max(buys, key=lambda r: r["net_volume"])
            concentration = top_buyer["net_volume"] / total_buy if total_buy else 0
            # Tek kurum alimlarin >%40'ini yapiyorsa bilincli toplama sinyali
            if concentration > 0.4:
                sub["yogunlasma"] = 0.25
                details["yogun_alici"] = {"kurum": top_buyer["broker_or_group"],
                                           "pay_pct": round(concentration * 100, 1)}

        # 3) Kurumsal/yabanci agirlikli kurumlarin yonu (liste verilirse)
        if kurumsal_brokers:
            kurumsal_net = sum(r["net_volume"] for r in akd_rows
                               if r["broker_or_group"] in kurumsal_brokers)
            sub["kurumsal_yon"] = round(float(np.clip(kurumsal_net / gross, -1, 1)) * 0.4, 3)

        details["net_toplam"] = net_total
        details["alici_sayisi"] = len(buys)
        details["satici_sayisi"] = len(sells)

    if yabanci_takas and "onceki_pct" in yabanci_takas and "guncel_pct" in yabanci_takas:
        delta = yabanci_takas["guncel_pct"] - yabanci_takas["onceki_pct"]
        # 1 puanlik yabanci artisi belirgin pozitif kabul
        sub["yabanci_degisim"] = round(float(np.clip(delta / 1.0, -0.5, 0.5)), 3)
        details["yabanci_takas_delta"] = round(delta, 2)

    if not sub:
        return {"score": None, "reason": "Islenebilir AKD verisi yok", "details": {}}

    score = float(np.clip(sum(sub.values()), -1, 1))
    return {
        "score": round(score, 3),
        "reason": "AKD net akis, takas yogunlasmasi ve yabanci oran degisimi birlesik skoru",
        "details": {"sub_scores": sub, **details},
    }

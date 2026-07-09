"""
Temel analiz modulu - GERCEK mantik.

Girdi olarak sirketin guncel oranlarini alir (F/K, PD/DD, buyume vb.)
ve hem mutlak degerlere hem de sektor/tarihsel banda gore skorlar.

Veri kaynagi: yfinance .info (bilgisayar erisiminde otomatik),
o zamana kadar manuel/web'den alinan gercek oranlar elle beslenebilir.
ASELS ornegi (07 Tem 2026, yatirimx/fintables kaynakli gercek veriler):
    fk=51.57, pd_dd=6.51, fk_yillik_dusuk=30.07, fk_yillik_yuksek=65.37,
    pd_dd_yillik_dusuk=4.04, pd_dd_yillik_yuksek=8.24
"""
from __future__ import annotations

import numpy as np


def _band_position(value: float, low: float, high: float) -> float:
    """Degerin yillik bandin neresinde oldugunu 0 (dip) - 1 (tepe) dondurur."""
    if high <= low:
        return 0.5
    return float(np.clip((value - low) / (high - low), 0, 1))


def analyze(data: dict | None) -> dict:
    """
    data ornegi:
    {
      "fk": 51.57, "fk_low": 30.07, "fk_high": 65.37,
      "pd_dd": 6.51, "pd_dd_low": 4.04, "pd_dd_high": 8.24,
      "net_kar_ceyrek": 5.54e9, "net_kar_onceki_ceyrek": 18.30e9,   # opsiyonel
      "analist_ort_hedef": 465.78, "guncel_fiyat": 383.0,           # opsiyonel
    }
    """
    if not data:
        return {"score": 0.0, "reason": "Temel analiz verisi saglanmadi", "details": {}}

    sub = {}

    # 1) F/K bandi: kendi yillik bandinin dibine yakinsa ucuz (pozitif),
    #    tepesine yakinsa pahali (negatif)
    if all(k in data for k in ("fk", "fk_low", "fk_high")):
        pos = _band_position(data["fk"], data["fk_low"], data["fk_high"])
        sub["fk_band"] = round(float(np.interp(pos, [0, 0.5, 1], [0.5, 0.0, -0.5])), 3)

    # 2) PD/DD bandi: ayni mantik
    if all(k in data for k in ("pd_dd", "pd_dd_low", "pd_dd_high")):
        pos = _band_position(data["pd_dd"], data["pd_dd_low"], data["pd_dd_high"])
        sub["pd_dd_band"] = round(float(np.interp(pos, [0, 0.5, 1], [0.5, 0.0, -0.5])), 3)

    # 3) Ceyreklik kar ivmesi
    if data.get("net_kar_ceyrek") and data.get("net_kar_onceki_ceyrek"):
        change = (data["net_kar_ceyrek"] - data["net_kar_onceki_ceyrek"]) / abs(data["net_kar_onceki_ceyrek"])
        sub["kar_ivmesi"] = round(float(np.clip(change, -0.6, 0.6)), 3)

    # 4) Analist hedef fiyat primi: hedef guncel fiyatin ustundeyse pozitif
    if data.get("analist_ort_hedef") and data.get("guncel_fiyat"):
        upside = (data["analist_ort_hedef"] - data["guncel_fiyat"]) / data["guncel_fiyat"]
        # %20 prim -> +0.4 civari, doygunlukla sinirla
        sub["analist_prim"] = round(float(np.clip(upside * 2, -0.5, 0.5)), 3)

    if not sub:
        return {"score": 0.0, "reason": "Kullanilabilir oran bulunamadi", "details": {}}

    score = float(np.clip(sum(sub.values()) / len(sub), -1, 1))
    return {
        "score": round(score, 3),
        "reason": "F/K ve PD/DD band konumu, kar ivmesi ve analist hedef primi birlesik skoru",
        "details": {"sub_scores": sub, "girdi": data},
    }

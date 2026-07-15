"""
Kisa vadeli (scalping / gun-ici) strateji motoru.

Amac: %1-2'lik kucuk fiyat hareketlerini yakalayip AL -> SAT dongusuyle
kazanc uretmek. Iki temel strateji icerir:

1) MEAN REVERSION (ortalamaya donus):
   Fiyat kisa vadeli ortalamasindan asagi dogru asiri kopmussa
   (z-score ile olculur) -> toparlanma beklentisiyle AL sinyali.
   Ortalamanin ustune asiri cikmissa -> SAT sinyali.
   Kisa vadede BIST hisselerinde en cok ise yarayan yaklasimlardan biri.

2) MOMENTUM BURST (kisa vadeli ivme):
   Son birkac mumda hacimle desteklenen guclu yon varsa
   o yonde devam beklentisiyle sinyal.

KRITIK OZELLIK - MALIYET FARKINDALIGI:
   Sinyal, beklenen hareket buyuklugunu (expected_move_pct) tahmin eder
   ve bunu islem maliyetiyle (komisyon + spread + kayma) karsilastirir.
   Beklenen NET kazanc, minimum esigin altindaysa sinyal uretmez.
   Boylece "kagit ustunde karli, gercekte zararli" tuzagina dusulmez.

Bu modul de tamamen ticker-agnostic'tir ve gunluk VEYA gun-ici
(5dk/15dk) mum verisiyle calisir - veri cozunurlugu yukseldikce
isabet artar.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ---------------------------------------------------------------
# Islem maliyeti modeli
# ---------------------------------------------------------------
@dataclass
class CostModel:
    """Gidis-donus (al + sat) toplam maliyeti yuzde olarak modeller.

    NOT: Kullanicinin kurumunda islem komisyonu YOK -> varsayilan 0.
    Ancak komisyon olmasa bile spread (alis-satis makasi) ve kayma
    fiziksel olarak her zaman vardir; bunlari sifirlamak backtest'i
    yalanci-iyimser yapar. ASELS gibi cok likit hissede dusuk tutuyoruz.
    """
    commission_pct_per_side: float = 0.0    # kullanicinin kurumunda komisyon yok
    spread_pct: float = 0.05                # likit hissede tipik makas (~1-2 kademe)
    slippage_pct: float = 0.03              # emir gerceklesme kaymasi

    @property
    def round_trip_cost_pct(self) -> float:
        return 2 * self.commission_pct_per_side + self.spread_pct + self.slippage_pct


@dataclass
class ScalpSignal:
    action: str                 # "AL", "SAT", "BEKLE"
    strategy: str               # hangi strateji uretti
    expected_move_pct: float    # beklenen brut hareket (%)
    expected_net_pct: float     # maliyet dusulmus beklenen net (%)
    confidence: float           # 0..1
    stop_loss_pct: float        # onerilen zarar kes seviyesi (%)
    take_profit_pct: float      # onerilen kar al seviyesi (%)
    reason: str


def _zscore(series: pd.Series, window: int) -> float:
    if len(series) < window + 1:
        return 0.0
    recent = series.iloc[-window:]
    mean = recent.mean()
    std = recent.std()
    if not std or std == 0 or pd.isna(std):
        return 0.0
    return float((series.iloc[-1] - mean) / std)


def _recent_volatility_pct(close: pd.Series, window: int = 20) -> float:
    """Son N mumun ortalama mutlak yuzde degisimi - beklenen hareket buyuklugunu
    tahmin etmek icin taban olarak kullanilir."""
    if len(close) < window + 1:
        return 0.0
    pct_changes = close.pct_change().iloc[-window:].abs()
    return float(pct_changes.mean() * 100)


def analyze_scalp(
    price_rows: list[dict],
    cost_model: CostModel | None = None,
    min_net_edge_pct: float = 0.15,   # maliyet sonrasi en az %0.15 net beklenti olmali
    zscore_entry: float = 1.3,        # ortalamadan 1.3 std sapma = asiri hareket
    move_trigger_pct: float = 1.0,    # %1'lik yonlu hareket = firsat (kullanici stratejisi)
) -> ScalpSignal:
    """
    Ana giris noktasi. Gunluk veya gun-ici mum listesi alir.
    Beklenen hareket maliyeti karsilamiyorsa BEKLE doner - bu bir hata
    degil, sistemin seni zarardan korumasidir.
    """
    cost_model = cost_model or CostModel()
    cost = cost_model.round_trip_cost_pct

    df = pd.DataFrame(price_rows)
    if df.empty or len(df) < 25:
        return ScalpSignal(
            action="BEKLE", strategy="-", expected_move_pct=0, expected_net_pct=0,
            confidence=0, stop_loss_pct=0, take_profit_pct=0,
            reason="Yetersiz veri (en az 25 mum gerekli)",
        )

    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    volume = pd.to_numeric(df["volume"], errors="coerce").fillna(0)

    vol_pct = _recent_volatility_pct(close)          # tipik mum basina hareket
    z20 = _zscore(close, 20)                          # 20 mumluk z-score

    # Hacim onayi: son mumun hacmi ortalamanin kac kati
    avg_vol = volume.iloc[-21:-1].mean() if len(volume) > 21 else volume.mean()
    vol_ratio = float(volume.iloc[-1] / avg_vol) if avg_vol else 1.0

    # Son 3 mumun yonu (momentum)
    if len(close) >= 4:
        mom3 = float((close.iloc[-1] - close.iloc[-4]) / close.iloc[-4] * 100)
    else:
        mom3 = 0.0

    # Son ~1 saatlik yonlu hareket (5m veride 12 mum, 15m veride 4 mum kapsar)
    move_window = min(12, len(close) - 1)
    move_pct = float((close.iloc[-1] - close.iloc[-1 - move_window])
                     / close.iloc[-1 - move_window] * 100) if move_window > 0 else 0.0

    # ---------------- STRATEJI 0: YUZDE HAREKET TETIGI ----------------
    # Kullanici stratejisi: %1'lik yukselis alim, %1'lik dusus satis firsatidir.
    # Hacim en azindan normal seviyedeyse (>=0.9x) hareketin devamina oynanir;
    # hacimsiz kopmalar asagida mean-reversion'a birakilir (ters yonde firsat).
    if abs(move_pct) >= move_trigger_pct and vol_ratio >= 0.9:
        direction = "AL" if move_pct > 0 else "SAT"
        # Devam beklentisi: hareketin ~%40'i kadar, tipik oynakligin altina dusme
        expected_move = max(min(abs(move_pct) * 0.4, 2.0), vol_pct * 2)
        expected_net = expected_move - cost
        confidence = min(0.45 + min(abs(move_pct) - move_trigger_pct, 1.0) * 0.2
                         + (0.15 if vol_ratio >= 1.3 else 0.0), 0.85)
        if expected_net >= min_net_edge_pct:
            return ScalpSignal(
                action=direction, strategy="yuzde_hareket",
                expected_move_pct=round(expected_move, 2),
                expected_net_pct=round(expected_net, 2),
                confidence=round(confidence, 2),
                stop_loss_pct=round(max(vol_pct * 1.5, 0.8), 2),
                take_profit_pct=round(expected_move, 2),
                reason=f"Son {move_window} mumda %{move_pct:+.2f} yonlu hareket "
                       f"(hacim {vol_ratio:.1f}x). %{move_trigger_pct} esigi asildi -> "
                       f"{direction} firsati, beklenen devam net ~%{expected_net:.2f}.",
            )

    # ---------------- STRATEJI 1: MEAN REVERSION ----------------
    if z20 <= -zscore_entry:
        # Fiyat asiri satilmis -> toparlanma beklentisi -> AL
        expected_move = min(abs(z20) * vol_pct, 3.0)   # z buyudukce beklenti artar, %3 ile sinirla
        expected_net = expected_move - cost
        confidence = min(abs(z20) / 3.0, 0.9) * (1.2 if vol_ratio > 1.5 else 1.0)
        confidence = min(confidence, 0.95)
        if expected_net >= min_net_edge_pct:
            return ScalpSignal(
                action="AL", strategy="mean_reversion",
                expected_move_pct=round(expected_move, 2),
                expected_net_pct=round(expected_net, 2),
                confidence=round(confidence, 2),
                stop_loss_pct=round(max(vol_pct * 1.5, 1.0), 2),
                take_profit_pct=round(expected_move, 2),
                reason=f"Fiyat 20-mum ortalamasindan {abs(z20):.1f} std asagida (asiri satim). "
                       f"Beklenen toparlanma ~%{expected_move:.1f}, maliyet %{cost:.2f} dusuldukten "
                       f"sonra net ~%{expected_net:.1f}.",
            )

    if z20 >= zscore_entry:
        expected_move = min(abs(z20) * vol_pct, 3.0)
        expected_net = expected_move - cost
        confidence = min(abs(z20) / 3.0, 0.9)
        if expected_net >= min_net_edge_pct:
            return ScalpSignal(
                action="SAT", strategy="mean_reversion",
                expected_move_pct=round(expected_move, 2),
                expected_net_pct=round(expected_net, 2),
                confidence=round(confidence, 2),
                stop_loss_pct=round(max(vol_pct * 1.5, 1.0), 2),
                take_profit_pct=round(expected_move, 2),
                reason=f"Fiyat 20-mum ortalamasindan {z20:.1f} std yukarida (asiri alim). "
                       f"Geri cekilme beklentisi ~%{expected_move:.1f}, net ~%{expected_net:.1f}.",
            )

    # ---------------- STRATEJI 2: MOMENTUM BURST ----------------
    if abs(mom3) >= vol_pct * 1.5 and vol_ratio >= 1.2:
        direction = "AL" if mom3 > 0 else "SAT"
        expected_move = min(abs(mom3) * 0.5, 2.0)   # hareketin yarisi kadar devam varsayimi
        expected_net = expected_move - cost
        confidence = min(0.4 + (vol_ratio - 1.2) * 0.2, 0.8)
        if expected_net >= min_net_edge_pct:
            return ScalpSignal(
                action=direction, strategy="momentum_burst",
                expected_move_pct=round(expected_move, 2),
                expected_net_pct=round(expected_net, 2),
                confidence=round(confidence, 2),
                stop_loss_pct=round(max(vol_pct, 0.8), 2),
                take_profit_pct=round(expected_move, 2),
                reason=f"Son 3 mumda %{mom3:.1f} hareket, hacim ortalamanin {vol_ratio:.1f} kati. "
                       f"Yonlu devam beklentisi net ~%{expected_net:.1f}.",
            )

    return ScalpSignal(
        action="BEKLE", strategy="-",
        expected_move_pct=round(vol_pct, 2), expected_net_pct=0,
        confidence=0,
        stop_loss_pct=0, take_profit_pct=0,
        reason=f"Su an maliyeti (%{cost:.2f} gidis-donus) karsilayacak buyuklukte "
               f"bir firsat yok. 1-saatlik hareket: %{move_pct:+.2f} (esik ±%{move_trigger_pct}), "
               f"Z-score: {z20:.2f}, 3-mum momentum: %{mom3:.2f}, "
               f"tipik mum hareketi: %{vol_pct:.2f}. Islem yapmamak da bir karardir - "
               f"kucuk kenarli islemler maliyete yenilir.",
    )

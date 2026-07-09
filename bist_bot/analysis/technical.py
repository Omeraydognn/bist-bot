"""
Teknik analiz motoru.

Girdi: fiyat satirlarinin listesi (storage.get_prices ile ayni format)
Cikti: -1 (guclu sat) ile +1 (guclu al) arasinda tek bir skor + detaylar

Hicbir yerde ticker adi gecmez -> herhangi bir hisse icin calisir.
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def _to_dataframe(price_rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(price_rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def compute_sma(df: pd.DataFrame, window: int) -> pd.Series:
    return df["close"].rolling(window=window).mean()


def compute_ema(df: pd.DataFrame, window: int) -> pd.Series:
    return df["close"].ewm(span=window, adjust=False).mean()


def compute_rsi(df: pd.DataFrame, window: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = compute_ema(df, fast)
    ema_slow = compute_ema(df, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_bollinger(df: pd.DataFrame, window: int = 20, num_std: float = 2.0):
    sma = compute_sma(df, window)
    std = df["close"].rolling(window=window).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    return upper, sma, lower


def compute_volume_signal(df: pd.DataFrame, window: int = 20) -> float:
    """Son hacim, ortalama hacme gore ne kadar yuksek/dusuk -> -1..+1 arasi normalize."""
    if len(df) < window + 1:
        return 0.0
    avg_vol = df["volume"].iloc[-window:-1].mean()
    last_vol = df["volume"].iloc[-1]
    if not avg_vol or avg_vol == 0 or pd.isna(avg_vol):
        return 0.0
    ratio = last_vol / avg_vol
    # 1x ortalama -> 0 skor, 2x -> ~+0.3, 3x+ -> +0.5 doygunluk (fiyat yonunu bilmiyoruz, sadece "ilgi" sinyali)
    score = np.tanh((ratio - 1) / 2)
    return float(np.clip(score, -0.5, 0.5))


def analyze(price_rows: list[dict]) -> dict:
    """
    Ana giris noktasi. Karar motoru (decision/scorer.py) sadece bu
    fonksiyonu cagirir.
    """
    df = _to_dataframe(price_rows)
    if df.empty or len(df) < 30:
        return {
            "score": 0.0,
            "reason": "Yetersiz veri (en az 30 mum gerekli)",
            "details": {},
        }

    rsi = compute_rsi(df).iloc[-1]
    macd_line, signal_line, hist = compute_macd(df)
    macd_last, signal_last, hist_last = macd_line.iloc[-1], signal_line.iloc[-1], hist.iloc[-1]
    upper, mid, lower = compute_bollinger(df)
    close_last = df["close"].iloc[-1]
    upper_last, mid_last, lower_last = upper.iloc[-1], mid.iloc[-1], lower.iloc[-1]
    sma20 = compute_sma(df, 20).iloc[-1]
    sma50 = compute_sma(df, 50).iloc[-1] if len(df) >= 50 else np.nan
    vol_score = compute_volume_signal(df)
    
    ema5_series = compute_ema(df, 5)
    ema15_series = compute_ema(df, 15)
    ema5_last = ema5_series.iloc[-1]
    ema15_last = ema15_series.iloc[-1]
    ema5_prev = ema5_series.iloc[-2] if len(df) >= 2 else np.nan
    ema15_prev = ema15_series.iloc[-2] if len(df) >= 2 else np.nan

    sub_scores = {}

    # --- RSI: 30 alti asiri satim (alim firsati), 70 ustu asiri alim (satim sinyali)
    if pd.isna(rsi):
        sub_scores["rsi"] = 0.0
    elif rsi < 30:
        sub_scores["rsi"] = 0.6
    elif rsi > 70:
        sub_scores["rsi"] = -0.6
    else:
        # 30-70 arasini lineer -1..1 skalasina değil, notr agirlikli haritalar
        sub_scores["rsi"] = float(np.interp(rsi, [30, 50, 70], [0.3, 0.0, -0.3]))

    # --- MACD: histogram pozitif ve artan -> al, negatif ve azalan -> sat
    if pd.isna(hist_last):
        sub_scores["macd"] = 0.0
    else:
        sub_scores["macd"] = float(np.clip(hist_last / (abs(close_last) * 0.01 + 1e-9), -1, 1)) * 0.5

    # --- Bollinger: fiyat alt banda yakinsa alim, ust banda yakinsa satim sinyali
    if pd.isna(upper_last) or pd.isna(lower_last) or upper_last == lower_last:
        sub_scores["bollinger"] = 0.0
    else:
        position = (close_last - lower_last) / (upper_last - lower_last)  # 0..1
        sub_scores["bollinger"] = float(np.interp(position, [0, 0.5, 1], [0.5, 0.0, -0.5]))

    # --- Trend: SMA20 > SMA50 -> yukselis trendi
    if pd.isna(sma50):
        sub_scores["trend"] = 0.0
    else:
        sub_scores["trend"] = 0.4 if sma20 > sma50 else -0.4

    # --- EMA 5-15 Kesişimi
    if pd.isna(ema15_last) or pd.isna(ema15_prev):
        sub_scores["ema_cross"] = 0.0
    else:
        if ema5_last > ema15_last and ema5_prev <= ema15_prev:
            sub_scores["ema_cross"] = 0.5   # Kesin AL (Golden Cross)
        elif ema5_last < ema15_last and ema5_prev >= ema15_prev:
            sub_scores["ema_cross"] = -0.5  # Kesin SAT (Death Cross)
        else:
            sub_scores["ema_cross"] = 0.2 if ema5_last > ema15_last else -0.2

    # --- Hacim
    sub_scores["volume"] = vol_score

    # Basit ortalama (ileride agirliklandirilabilir)
    final_score = float(np.clip(sum(sub_scores.values()) / len(sub_scores), -1, 1))

    return {
        "score": final_score,
        "reason": "Teknik gostergelerin (RSI, MACD, Bollinger, trend, hacim) birlesik skoru",
        "details": {
            "rsi": None if pd.isna(rsi) else round(float(rsi), 2),
            "macd_hist": None if pd.isna(hist_last) else round(float(hist_last), 4),
            "close": round(float(close_last), 2),
            "bollinger_upper": None if pd.isna(upper_last) else round(float(upper_last), 2),
            "bollinger_lower": None if pd.isna(lower_last) else round(float(lower_last), 2),
            "sma20": None if pd.isna(sma20) else round(float(sma20), 2),
            "sma50": None if pd.isna(sma50) else round(float(sma50), 2),
            "ema5": None if pd.isna(ema5_last) else round(float(ema5_last), 2),
            "ema15": None if pd.isna(ema15_last) else round(float(ema15_last), 2),
            "sub_scores": {k: round(v, 3) for k, v in sub_scores.items()},
        },
    }

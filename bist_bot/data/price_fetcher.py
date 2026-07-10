"""
Fiyat verisi cekici.

Su an icin Yahoo Finance (yfinance) kullaniyoruz (ucretsiz, gecikmeli
ama baslangic icin yeterli). Ileride Algolab / Matriks gibi lisansli
kaynaklara gecince tek yapman gereken burada YENI bir fetcher sinifi
yazip config.yaml'daki `data_sources.price.provider` degerini
degistirmek. Ust katmanlar (analiz, karar motoru) HICBIR SEKILDE
degismeyecek cunku hepsi ayni "PriceFetcher" arayuzunu kullaniyor.
"""
from __future__ import annotations

import abc
from datetime import datetime, timedelta
from typing import Any


class BasePriceFetcher(abc.ABC):
    """Tum fiyat kaynaklarinin uymasi gereken ortak arayuz."""

    @abc.abstractmethod
    def fetch_ohlcv(self, yahoo_symbol: str, lookback_days: int, interval: str) -> list[dict[str, Any]]:
        """Her biri {date, open, high, low, close, volume} olan liste dondurur."""
        raise NotImplementedError


class YahooPriceFetcher(BasePriceFetcher):
    def fetch_ohlcv(self, yahoo_symbol: str, lookback_days: int = 730, interval: str = "1d"):
        try:
            import yfinance as yf
        except ImportError as e:
            raise RuntimeError(
                "yfinance kurulu degil. `pip install yfinance` calistir."
            ) from e

        end = datetime.now()
        start = end - timedelta(days=lookback_days)

        df = yf.download(
            yahoo_symbol,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval=interval,
            progress=False,
            auto_adjust=False,
        )

        if df is None or df.empty:
            return []

        # yfinance bazen MultiIndex kolon donduruyor (tek sembolde bile) - normalize et
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)

        rows = []
        for idx, row in df.iterrows():
            rows.append(
                {
                    "date": idx.strftime("%Y-%m-%d"),
                    "open": float(row["Open"]) if row["Open"] == row["Open"] else None,
                    "high": float(row["High"]) if row["High"] == row["High"] else None,
                    "low": float(row["Low"]) if row["Low"] == row["Low"] else None,
                    "close": float(row["Close"]) if row["Close"] == row["Close"] else None,
                    "volume": float(row["Volume"]) if row["Volume"] == row["Volume"] else None,
                }
            )
        return rows


class AlgolabPriceFetcher(BasePriceFetcher):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def fetch_ohlcv(self, symbol: str, lookback_days: int = 60, interval: str = "15m"):
        """
        AlgoLab REST API uzerinden gecmis fiyat barlarini (mum) ceker.
        (WebSocket ayrica anlik veriyi guncelleyecektir).
        """
        # TODO: AlgoLab (/api/GetCandleData) REST cagirimi buraya gelecek.
        raise NotImplementedError("Algolab gecmis mum verisi entegrasyonu henuz eklenmedi.")


class TVPriceFetcher(BasePriceFetcher):
    def fetch_ohlcv(self, symbol: str, lookback_days: int = 60, interval: str = "15m") -> list[dict[str, Any]]:
        try:
            from tvDatafeed import TvDatafeed, Interval
        except ImportError as e:
            raise RuntimeError(
                "tvDatafeed kurulu degil. `pip install git+https://github.com/rongardF/tvdatafeed.git` calistir."
            ) from e

        # TradingView "BIST" borsasini kullanir, ".IS" uzantisini kaldiralim
        clean_symbol = symbol.split(".")[0] if "." in symbol else symbol

        interval_map = {
            "15m": Interval.in_15_minute,
            "30m": Interval.in_30_minute,
            "1h": Interval.in_1_hour,
            "1d": Interval.in_daily,
        }
        tv_interval = interval_map.get(interval, Interval.in_15_minute)

        # Kac bar cekilecegini hesapla
        n_bars_map = {
            "15m": lookback_days * 32,
            "30m": lookback_days * 16,
            "1h": lookback_days * 8,
            "1d": lookback_days * 1
        }
        bars_to_fetch = min(n_bars_map.get(interval, lookback_days * 32), 4900)

        # tvDatafeed uyarilarini gizle
        import logging
        logging.getLogger('tvDatafeed').setLevel(logging.ERROR)
        
        tv = TvDatafeed()
        df = tv.get_hist(symbol=clean_symbol, exchange='BIST', interval=tv_interval, n_bars=bars_to_fetch)
        
        if df is None or df.empty:
            return []

        rows = []
        for idx, row in df.iterrows():
            rows.append({
                "date": idx.strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
        return rows


def get_price_fetcher(provider: str = "yahoo") -> BasePriceFetcher:
    """Provider ismine gore dogru fetcher'i dondurur (factory pattern).

    Yeni kaynak eklerken: yeni bir sinif yaz, asagidaki dict'e ekle.
    Kalan tum kod degismeden calismaya devam eder.
    """
    providers = {
        "yahoo": YahooPriceFetcher,
        "algolab": AlgolabPriceFetcher,
        "tradingview": TVPriceFetcher,
    }
    if provider not in providers:
        raise ValueError(f"Bilinmeyen fiyat veri kaynagi: {provider}")
    return providers[provider]()

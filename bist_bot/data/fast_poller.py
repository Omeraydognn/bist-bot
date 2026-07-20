import asyncio
import yfinance as yf
from datetime import datetime
import pandas as pd
import numpy as np

class FastPoller:
    """
    Arka planda saniyelik/dakikalik veri ceken asenkron motor.
    Gorevi: Ana sistemi bloklamadan, hissenin 1-dakikalik VWAP, EMA ve 
    Hacim (Volume) patlamalarini tespit etmek icin surekli guncel veri saglamak.
    """
    def __init__(self, symbol: str, interval_seconds: int = 5):
        self.symbol = symbol
        self.interval_seconds = interval_seconds
        self.is_running = False
        self.latest_data = pd.DataFrame()
        self.latest_price = 0.0

    async def start(self):
        self.is_running = True
        print(f"[FastPoller] {self.symbol} icin arka plan veri akisi basladi ({self.interval_seconds}s).")
        while self.is_running:
            try:
                # 1m mum verilerini cek (Pullback vs Reversal hesabi icin sart)
                # yfinance ile 1 gunluk 1 dakikalik mumlar
                df = await asyncio.to_thread(
                    yf.download, 
                    tickers=self.symbol, 
                    period="1d", 
                    interval="1m", 
                    progress=False,
                    auto_adjust=False
                )
                
                if df is not None and not df.empty:
                    # MultiIndex kolon varsa duzelt
                    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                        df.columns = df.columns.get_level_values(0)
                        
                    self.latest_data = df
                    self.latest_price = float(df["Close"].iloc[-1])
                    
            except Exception as e:
                pass # Anlik ag hatasinda cokme, bir sonraki saniye tekrar dene
                
            await asyncio.sleep(self.interval_seconds)

    def stop(self):
        self.is_running = False

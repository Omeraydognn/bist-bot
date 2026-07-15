"""
KAR REALIZASYONU DONGUSU (Swing Cycler).

Kullanicinin stratejisi: "Yuksekten sat, dusukten geri al -> hisse sayisini
artir." Bu modul o donguyu sanal olarak isletir ve her adimi Telegram'a
bildirir. Amac fiyat kazanci degil, HISSE ADEDI buyumesidir: 100 lotu
tepede satip %0.5 asagidan geri alirsan ~100.5 lotun olur.

KURALLAR - 50 gunluk gercek ASELS 15m backtest'iyle secildi (2026-07-15):
  * TEPE SATISI: gun ici kazanc >= +%2 VEYA z-score(20) >= 1.5, VE son mum
    asagi donmus, VE z-score >= 1.0 (yukselisin gercekten uc noktasi)
  * GERI ALIM (dip): fiyat satis fiyatinin %0.5 altina indi -> geri al,
    hisse adedi buyudu
  * KACIS KORUMASI: fiyat satis fiyatinin %1.5 ustune ciktiysa geri al
    (hisseyi tamamen kaybetmemek icin kucuk bir adet kaybi kabul edilir)
  Dogrulama: donem toplami +%8.6 hisse artisi; iki yari ve dort ceyregin
  DORDUNDE de pozitif (asiri uyum degil). 5m veride ayni kurallar tutarsiz
  cikti -> bu dongu SADECE 15m katmaniyla calisir.

Durum SQLite'ta tutulur - bot yeniden baslasa bile dongu kaldigi yerden
devam eder. Bu bir SANAL portfoydur (paper); gercek emir gonderilmez.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

SWING_SCHEMA = """
CREATE TABLE IF NOT EXISTS swing_state (
    symbol      TEXT PRIMARY KEY,
    mode        TEXT NOT NULL,       -- 'HISSE' (elde hisse) / 'NAKIT' (satildi, geri alim bekleniyor)
    shares      REAL NOT NULL,
    cash        REAL NOT NULL,
    start_shares REAL NOT NULL,      -- dongu basindaki hisse adedi (kiyas icin)
    sell_price  REAL,                -- son tepe satis fiyati
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS swing_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    sell_price  REAL NOT NULL,
    rebuy_price REAL NOT NULL,
    rebuy_type  TEXT NOT NULL,       -- 'dip' / 'kacis'
    shares_before REAL NOT NULL,
    shares_after  REAL NOT NULL,
    ts          TEXT NOT NULL
);
"""


class SwingCycler:
    def __init__(self, db_path: Path | str,
                 day_gain_pct: float = 2.0,
                 z_sell: float = 1.5,
                 z_min: float = 1.0,
                 dip_pct: float = 0.5,
                 runaway_pct: float = 1.5,
                 cost_one_side_pct: float = 0.04,
                 start_value: float = 100_000.0):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.day_gain_pct = day_gain_pct
        self.z_sell = z_sell
        self.z_min = z_min
        self.dip_pct = dip_pct
        self.runaway_pct = runaway_pct
        self.cost = cost_one_side_pct
        self.start_value = start_value
        with self._connect() as conn:
            conn.executescript(SWING_SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------
    @staticmethod
    def _zscore(closes: list[float], window: int = 20) -> float:
        s = pd.Series(closes[-(window + 1):])
        if len(s) < window:
            return 0.0
        std = s.std()
        return float((s.iloc[-1] - s.mean()) / std) if std else 0.0

    @staticmethod
    def _day_gain_pct(rows_15m: list[dict]) -> float:
        """Bugunun ilk mumunun acilisina gore guncel kazanc."""
        last_day = str(rows_15m[-1].get("date", ""))[:10]
        day_rows = [r for r in rows_15m if str(r.get("date", "")).startswith(last_day)]
        if not day_rows or not day_rows[0].get("open"):
            return 0.0
        return (rows_15m[-1]["close"] - day_rows[0]["open"]) / day_rows[0]["open"] * 100

    # ------------------------------------------------------------
    def _get_state(self, conn, symbol: str, price: float):
        row = conn.execute("SELECT * FROM swing_state WHERE symbol=?", (symbol,)).fetchone()
        if row is None:
            shares = self.start_value / price
            conn.execute(
                "INSERT INTO swing_state (symbol, mode, shares, cash, start_shares, sell_price, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (symbol, "HISSE", shares, 0.0, shares, None, datetime.now().isoformat()),
            )
            row = conn.execute("SELECT * FROM swing_state WHERE symbol=?", (symbol,)).fetchone()
        return row

    # ------------------------------------------------------------
    def step(self, symbol: str, rows_15m: list[dict]) -> list[str]:
        """
        Her analiz turunda 15m veriyle cagrilir. Kural tetiklenirse sanal
        islemi yapar ve bildirilecek mesajlari dondurur.
        """
        if not rows_15m or len(rows_15m) < 25:
            return []
        closes = [r["close"] for r in rows_15m if r.get("close")]
        if len(closes) < 22:
            return []
        price = closes[-1]
        messages = []

        with self._connect() as conn:
            st = self._get_state(conn, symbol, price)

            if st["mode"] == "HISSE":
                z = self._zscore(closes)
                gain = self._day_gain_pct(rows_15m)
                last_bar_down = closes[-1] < closes[-2]
                spike = (gain >= self.day_gain_pct) or (z >= self.z_sell)
                if spike and last_bar_down and z >= self.z_min:
                    cash = st["shares"] * price * (1 - self.cost / 100)
                    conn.execute(
                        "UPDATE swing_state SET mode='NAKIT', cash=?, shares=0, sell_price=?, updated_at=? "
                        "WHERE symbol=?",
                        (cash, price, datetime.now().isoformat(), symbol),
                    )
                    messages.append(
                        f"🔴 <b>SAT SİNYALİ — KÂR REALİZASYONU</b>\n"
                        f"{symbol} @ {price:.2f} TL (gün içi %{gain:+.1f}, z={z:.1f})\n"
                        f"Tepe işareti: yükseliş yorgun, geri çekilme bekleniyor.\n"
                        f"🎯 Geri alım hedefi: {price * (1 - self.dip_pct / 100):.2f} altı"
                    )

            elif st["mode"] == "NAKIT" and st["sell_price"]:
                sell_p = st["sell_price"]
                rebuy_type = None
                if price <= sell_p * (1 - self.dip_pct / 100):
                    rebuy_type = "dip"
                elif price >= sell_p * (1 + self.runaway_pct / 100):
                    rebuy_type = "kacis"
                if rebuy_type:
                    new_shares = st["cash"] * (1 - self.cost / 100) / price
                    conn.execute(
                        "UPDATE swing_state SET mode='HISSE', shares=?, cash=0, sell_price=NULL, updated_at=? "
                        "WHERE symbol=?",
                        (new_shares, datetime.now().isoformat(), symbol),
                    )
                    conn.execute(
                        "INSERT INTO swing_cycles (symbol, sell_price, rebuy_price, rebuy_type, "
                        "shares_before, shares_after, ts) VALUES (?,?,?,?,?,?,?)",
                        (symbol, sell_p, price, rebuy_type, st["start_shares"], new_shares,
                         datetime.now().isoformat()),
                    )
                    total_growth = (new_shares - st["start_shares"]) / st["start_shares"] * 100
                    if rebuy_type == "dip":
                        messages.append(
                            f"🟢 <b>AL SİNYALİ — GERİ ALIM (dip)</b>\n"
                            f"{symbol} @ {price:.2f} TL (satış {sell_p:.2f} → %{(price - sell_p) / sell_p * 100:+.2f})\n"
                            f"Döngü tamamlandı. Toplam hisse büyümesi: %{total_growth:+.2f}"
                        )
                    else:
                        messages.append(
                            f"🟢 <b>AL SİNYALİ — GERİ ALIM (kaçış koruması)</b>\n"
                            f"{symbol} @ {price:.2f} TL — fiyat satışın %{self.runaway_pct} üstüne çıktı, "
                            f"hisseyi kaybetmemek için geri gir.\n"
                            f"Toplam hisse büyümesi: %{total_growth:+.2f}"
                        )

        return messages

    # ------------------------------------------------------------
    def status(self, symbol: str) -> dict | None:
        with self._connect() as conn:
            st = conn.execute("SELECT * FROM swing_state WHERE symbol=?", (symbol,)).fetchone()
            if st is None:
                return None
            cycles = conn.execute(
                "SELECT COUNT(*) AS n FROM swing_cycles WHERE symbol=?", (symbol,)
            ).fetchone()["n"]
            return {
                "mod": st["mode"],
                "hisse": round(st["shares"], 2),
                "nakit": round(st["cash"], 2),
                "baslangic_hisse": round(st["start_shares"], 2),
                "hisse_buyume_pct": round((st["shares"] - st["start_shares"]) / st["start_shares"] * 100, 2)
                if st["shares"] else None,
                "bekleyen_satis_fiyati": st["sell_price"],
                "dongu_sayisi": cycles,
            }

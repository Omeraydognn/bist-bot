"""
PAPER TRADING (kagit uzerinde islem) modulu.

Botun urettigi sinyalleri GERCEK PARA RISKI OLMADAN sanal bir
portfoyle uygular. Amac: gercek emir gondermeye baslamadan once
stratejinin canli kosullarda gercekten kazandirip kazandirmadigini
kanitlamak.

Ozellikler:
  * Sanal nakit + pozisyon takibi (SQLite'ta kalici - bot yeniden
    baslasa bile portfoy kaybolmaz)
  * Her islemde maliyet modeli uygulanir (spread + kayma)
  * Acik pozisyonlarda stop-loss / take-profit takibi
  * Seans sonu zorunlu kapanis (gun-ici mod, gece gap riski yok)
  * Gunluk / toplam kar-zarar raporu
  * Risk kurali: tek pozisyona portfoyun max %X'i (config'ten)

Gercek emir gonderimine (Faz 6b - execution) gecis, ancak paper
trading'de en az 4-6 hafta tutarli pozitif sonuc gorulduginde onerilir.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from bist_bot.analysis.scalping import CostModel

PAPER_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cash REAL NOT NULL,
    starting_cash REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_positions (
    symbol      TEXT PRIMARY KEY,
    shares      REAL NOT NULL,
    entry_price REAL NOT NULL,
    entry_time  TEXT NOT NULL,
    stop_price  REAL,
    target_pct  REAL
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    action      TEXT NOT NULL,     -- AL / SAT
    price       REAL NOT NULL,
    shares      REAL NOT NULL,
    fee         REAL NOT NULL,
    pnl_net     REAL,              -- sadece SAT kayitlarinda dolu
    pnl_net_pct REAL,
    reason      TEXT,
    ts          TEXT NOT NULL
);
"""


@dataclass
class PortfolioStatus:
    cash: float
    positions: list[dict]
    equity: float               # nakit + pozisyonlarin guncel degeri
    total_return_pct: float
    open_position_count: int


class PaperTrader:
    def __init__(self, db_path: Path | str, starting_cash: float = 100_000.0,
                 cost_model: CostModel | None = None, max_position_pct: float = 1.0):
        """
        max_position_pct: tek pozisyona ayrilabilecek portfoy orani
        (tek hisseyle calisirken 1.0, coklu hissede config'ten dusurulur).
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cost_model = cost_model or CostModel()
        self.max_position_pct = max_position_pct
        self._init(starting_cash)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self, starting_cash: float):
        with self._connect() as conn:
            conn.executescript(PAPER_SCHEMA)
            # Eski surumden kalan veritabanlarinda eksik kolonlari tamamla
            # (CREATE TABLE IF NOT EXISTS mevcut tabloya kolon EKLEMEZ)
            existing = {r["name"] for r in conn.execute("PRAGMA table_info(paper_positions)")}
            for col, ddl in (("stop_price", "REAL"), ("target_pct", "REAL")):
                if col not in existing:
                    conn.execute(f"ALTER TABLE paper_positions ADD COLUMN {col} {ddl}")
            row = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO paper_account (id, cash, starting_cash, created_at) VALUES (1, ?, ?, ?)",
                    (starting_cash, starting_cash, datetime.now().isoformat()),
                )

    # ---------------- islem maliyeti ----------------
    @property
    def _one_side_cost_pct(self) -> float:
        c = self.cost_model
        return c.commission_pct_per_side + (c.spread_pct + c.slippage_pct) / 2

    # ---------------- sinyal isleme ----------------
    def process_signal(self, symbol: str, action: str, price: float,
                       stop_pct: float | None = None, target_pct: float | None = None,
                       reason: str = "") -> dict:
        """
        Orkestratorun urettigi sinyali portfoye uygular.
        Doner: {"executed": bool, "message": str}
        """
        if price is None or price <= 0:
            return {"executed": False, "message": "Gecersiz fiyat"}

        with self._connect() as conn:
            account = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
            pos = conn.execute("SELECT * FROM paper_positions WHERE symbol=?", (symbol,)).fetchone()

            if action == "AL":
                if pos is not None:
                    return {"executed": False, "message": f"{symbol} pozisyonu zaten acik - cift alim engellendi"}
                budget = account["cash"] * self.max_position_pct
                if budget < price:
                    return {"executed": False, "message": "Yetersiz sanal bakiye"}
                fee = budget * self._one_side_cost_pct / 100
                shares = (budget - fee) / price
                new_cash = account["cash"] - budget
                conn.execute("UPDATE paper_account SET cash=? WHERE id=1", (new_cash,))
                initial_stop = price * (1 - stop_pct / 100) if stop_pct else None
                conn.execute(
                    "INSERT INTO paper_positions (symbol, shares, entry_price, entry_time, stop_price, target_pct) VALUES (?,?,?,?,?,?)",
                    (symbol, shares, price, datetime.now().isoformat(), initial_stop, target_pct),
                )
                conn.execute(
                    "INSERT INTO paper_trades (symbol, action, price, shares, fee, reason, ts) VALUES (?,?,?,?,?,?,?)",
                    (symbol, "AL", price, shares, fee, reason, datetime.now().isoformat()),
                )
                return {"executed": True,
                        "message": f"[PAPER] AL: {shares:.2f} adet {symbol} @ {price:.2f} (fee {fee:.2f} TL)"}

            if action == "SAT":
                if pos is None:
                    return {"executed": False, "message": f"{symbol} pozisyonu yok - satilacak bir sey yok "
                                                          f"(acik satis Faz 6b'de degerlendirilecek)"}
                return self._close_position(conn, pos, price, reason or "sinyal: SAT")

        return {"executed": False, "message": f"Bilinmeyen aksiyon: {action}"}

    def _close_position(self, conn, pos, price: float, reason: str) -> dict:
        gross = pos["shares"] * price
        fee = gross * self._one_side_cost_pct / 100
        proceeds = gross - fee
        cost_basis = pos["shares"] * pos["entry_price"]
        pnl = proceeds - cost_basis
        pnl_pct = pnl / cost_basis * 100

        account = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
        conn.execute("UPDATE paper_account SET cash=? WHERE id=1", (account["cash"] + proceeds,))
        conn.execute("DELETE FROM paper_positions WHERE symbol=?", (pos["symbol"],))
        conn.execute(
            "INSERT INTO paper_trades (symbol, action, price, shares, fee, pnl_net, pnl_net_pct, reason, ts) VALUES (?,?,?,?,?,?,?,?,?)",
            (pos["symbol"], "SAT", price, pos["shares"], fee, pnl, pnl_pct, reason, datetime.now().isoformat()),
        )
        return {"executed": True,
                "message": f"[PAPER] SAT: {pos['shares']:.2f} adet {pos['symbol']} @ {price:.2f} | "
                           f"Net K/Z: {pnl:+.2f} TL ({pnl_pct:+.2f}%) | sebep: {reason}"}

    # ---------------- risk takibi ----------------
    def check_positions(self, current_prices: dict[str, float],
                        force_close_all: bool = False) -> list[str]:
        """
        Acik pozisyonlarda stop/target kontrolu. Orkestrator her dongude cagirir.
        force_close_all=True -> seans sonu zorunlu kapanis.
        Doner: gerceklesen islemlerin mesaj listesi.
        """
        messages = []
        with self._connect() as conn:
            positions = conn.execute("SELECT * FROM paper_positions").fetchall()
            for pos in positions:
                price = current_prices.get(pos["symbol"])
                if price is None:
                    continue

                if force_close_all:
                    r = self._close_position(conn, pos, price, "seans sonu zorunlu kapanis")
                    messages.append(r["message"])
                    continue

                change_pct = (price - pos["entry_price"]) / pos["entry_price"] * 100
                
                # Dinamik Izleyen Stop (Trailing Stop) Mantigi
                current_stop = pos["stop_price"]
                new_stop = current_stop
                if change_pct >= 2.0:
                    new_stop = pos["entry_price"] * 1.01  # %2 kara ulasilirsa stop %1'e tasinir
                elif change_pct >= 1.0:
                    new_stop = pos["entry_price"] * 1.002 # %1 kara ulasilirsa stop %0.2'ye tasinir
                
                if new_stop and (current_stop is None or new_stop > current_stop):
                    conn.execute("UPDATE paper_positions SET stop_price=? WHERE symbol=?", (new_stop, pos["symbol"]))
                    current_stop = new_stop

                if current_stop and price <= current_stop:
                    # Stop emri tetik SEVIYESINDEN gerceklesir
                    exec_price = min(current_stop, price * 1.001)
                    exec_price = max(exec_price, price)
                    r = self._close_position(conn, pos, exec_price, f"izleyen stop-loss ({current_stop:.2f})")
                    messages.append(r["message"])
                elif pos["target_pct"] and change_pct >= pos["target_pct"]:
                    target_price = pos["entry_price"] * (1 + pos["target_pct"] / 100)
                    r = self._close_position(conn, pos, target_price, f"take-profit (%{pos['target_pct']})")
                    messages.append(r["message"])
        return messages

    # ---------------- raporlama ----------------
    def status(self, current_prices: dict[str, float] | None = None) -> PortfolioStatus:
        current_prices = current_prices or {}
        with self._connect() as conn:
            account = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
            positions = [dict(r) for r in conn.execute("SELECT * FROM paper_positions").fetchall()]

        pos_value = 0.0
        for p in positions:
            price = current_prices.get(p["symbol"], p["entry_price"])
            p["guncel_fiyat"] = price
            p["acik_kz_pct"] = round((price - p["entry_price"]) / p["entry_price"] * 100, 2)
            pos_value += p["shares"] * price

        equity = account["cash"] + pos_value
        return PortfolioStatus(
            cash=round(account["cash"], 2),
            positions=positions,
            equity=round(equity, 2),
            total_return_pct=round((equity - account["starting_cash"]) / account["starting_cash"] * 100, 2),
            open_position_count=len(positions),
        )

    def daily_report(self, date_str: str | None = None) -> dict:
        """Belirli bir gunun (varsayilan bugun) islem ozeti."""
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        with self._connect() as conn:
            trades = [dict(r) for r in conn.execute(
                "SELECT * FROM paper_trades WHERE ts LIKE ? ORDER BY ts", (f"{date_str}%",)
            ).fetchall()]
        sells = [t for t in trades if t["action"] == "SAT"]
        wins = [t for t in sells if (t["pnl_net"] or 0) > 0]
        return {
            "tarih": date_str,
            "islem_sayisi": len(trades),
            "kapanan_pozisyon": len(sells),
            "kazanan": len(wins),
            "gunluk_net_kz": round(sum(t["pnl_net"] or 0 for t in sells), 2),
            "toplam_fee": round(sum(t["fee"] for t in trades), 2),
            "islemler": trades,
        }

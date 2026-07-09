"""
Gercek internet erisimi olmadan tum mimarinin dogru calistigini
dogrulamak icin sahte (sentetik) fiyat verisiyle uctan uca test.
"""
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from bist_bot.config import get_config
from bist_bot.data.storage import Storage
from bist_bot.analysis import technical, sentiment, fundamental
from bist_bot.decision import scorer
from bist_bot.backtest import engine as backtest_engine


def make_fake_prices(n=200, start_price=100.0, seed=42):
    random.seed(seed)
    rows = []
    price = start_price
    date = datetime.now() - timedelta(days=n)
    for i in range(n):
        change = random.uniform(-0.03, 0.03)
        price = max(1, price * (1 + change))
        high = price * (1 + abs(random.uniform(0, 0.01)))
        low = price * (1 - abs(random.uniform(0, 0.01)))
        vol = random.uniform(1_000_000, 5_000_000)
        rows.append({
            "date": (date + timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": price,
            "high": high,
            "low": low,
            "close": price,
            "volume": vol,
        })
    return rows


def main():
    config = get_config()
    print("1) Config yuklendi. Tanimli tickerlar:", [t.symbol for t in config.tickers])

    storage = Storage("/tmp/test_bist_bot.db")
    print("2) Storage (SQLite) baglandi.")

    symbol = "ASELS"
    fake_rows = make_fake_prices()
    storage.upsert_prices(symbol, fake_rows)
    print(f"3) {len(fake_rows)} sahte fiyat satiri DB'ye yazildi.")

    price_rows = storage.get_prices(symbol)
    print(f"4) DB'den {len(price_rows)} satir geri okundu (round-trip OK).")

    tech_result = technical.analyze(price_rows)
    print("5) Teknik analiz sonucu:", tech_result["score"], "-", tech_result["details"]["sub_scores"])

    fake_news = [
        {"title": f"{symbol} rekor ihracat anlasmasi imzaladi", "content": "Sirket yeni siparis aldi, kar artisi bekleniyor."},
        {"title": f"{symbol} hakkinda sorusturma baslatildi", "content": "Kamu kurumu inceleme baslatti, risk artti."},
    ]
    news_result = sentiment.analyze_news(fake_news)
    print("6) Haber sentiment sonucu:", news_result["score"])

    fundamental_result = fundamental.analyze(None)

    decision = scorer.decide(
        symbol=symbol,
        technical_result=tech_result,
        news_result=news_result,
        fundamental_result=fundamental_result,
        depth_result=None,
        akd_result=None,
        weights=config.scoring_weights,
        thresholds=config.decision_thresholds,
    )
    print("7) Nihai karar:", decision.decision, "| skor:", decision.final_score)
    print("   Kullanilan agirliklar (normalize edilmis):", decision.weights_used)

    storage.insert_signal(decision.to_storage_row())
    saved = storage.get_signals(symbol, limit=1)
    print("8) Sinyal DB'ye yazildi ve geri okundu:", saved[0]["decision"], saved[0]["final_score"])

    bt = backtest_engine.run_backtest(symbol, price_rows)
    print("9) Backtest sonucu -> islem sayisi:", bt.num_trades,
          "| kazanma orani:", bt.win_rate_pct, "%",
          "| toplam getiri:", bt.total_return_pct, "%")

    print("\nTUM PIPELINE BASARIYLA CALISTI.")


if __name__ == "__main__":
    main()

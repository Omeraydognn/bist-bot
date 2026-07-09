"""
BIST Bot - Ana calistirma dosyasi.

Kullanim:
    python main.py analyze ASELS          -> guncel skor/karar
    python main.py analyze --all          -> config'teki tum hisseler
    python main.py backtest ASELS         -> gecmis veri uzerinde test
    python main.py update-prices ASELS    -> fiyat verisini cekip DB'ye yazar

Yeni hisse eklemek istedigin zaman TEK yapman gereken:
    config/settings.yaml -> tickers listesine yeni blok eklemek.
Bu dosyada veya alt modullerde HICBIR SEY degistirmene gerek yok.
"""
from __future__ import annotations

import argparse
import sys

from bist_bot.config import get_config, TickerConfig
from bist_bot.data.storage import Storage
from bist_bot.data.price_fetcher import get_price_fetcher
from bist_bot.data.news_fetcher import get_news_fetcher
from bist_bot.analysis import technical, sentiment, fundamental
from bist_bot.decision import scorer
from bist_bot.backtest import engine as backtest_engine


def _get_storage():
    config = get_config()
    return Storage(config.db_path)


def update_prices(symbol: str | None, all_tickers: bool):
    config = get_config()
    storage = _get_storage()
    fetcher = get_price_fetcher(config.data_sources.get("price", {}).get("provider", "yahoo"))
    lookback = config.data_sources.get("price", {}).get("lookback_days", 730)
    interval = config.data_sources.get("price", {}).get("interval", "1d")

    targets = config.tickers if all_tickers else [_resolve_ticker(config, symbol)]

    for t in targets:
        print(f"[fiyat] {t.symbol} ({t.yahoo_symbol}) cekiliyor...")
        rows = fetcher.fetch_ohlcv(t.yahoo_symbol, lookback_days=lookback, interval=interval)
        storage.upsert_prices(t.symbol, rows)
        print(f"  -> {len(rows)} satir DB'ye yazildi.")


def _resolve_ticker(config, symbol: str) -> TickerConfig:
    t = config.get_ticker(symbol)
    if t is None:
        available = [x.symbol for x in config.tickers]
        print(f"HATA: '{symbol}' config'te tanimli degil. Mevcut: {available}", file=sys.stderr)
        sys.exit(1)
    return t


def analyze_symbol(symbol: str) -> None:
    config = get_config()
    storage = _get_storage()
    t = _resolve_ticker(config, symbol)

    price_rows = storage.get_prices(t.symbol)
    if not price_rows:
        print(f"'{t.symbol}' icin fiyat verisi yok. Once calistir: python main.py update-prices {t.symbol}")
        return

    tech_result = technical.analyze(price_rows)

    news_provider = config.data_sources.get("news", {}).get("provider", "dummy")
    news_fetcher = get_news_fetcher(news_provider if news_provider == "dummy" else "dummy")
    news_items = news_fetcher.fetch_news(t.symbol)
    news_result = sentiment.analyze_news(news_items)

    fundamental_result = fundamental.analyze(None)

    decision = scorer.decide(
        symbol=t.symbol,
        technical_result=tech_result,
        news_result=news_result,
        fundamental_result=fundamental_result,
        depth_result=None,
        akd_result=None,
        weights=config.scoring_weights,
        thresholds=config.decision_thresholds,
    )

    storage.insert_signal(decision.to_storage_row())

    print(f"\n=== {t.name} ({t.symbol}) ===")
    print(f"Nihai skor : {decision.final_score:+.3f}")
    print(f"Karar      : {decision.decision}")
    print(f"Alt skorlar: {decision.sub_scores}")
    print(f"Kullanilan agirliklar: {decision.weights_used}")
    print(f"Teknik detay: {tech_result['details']}")


def run_backtest(symbol: str):
    config = get_config()
    storage = _get_storage()
    t = _resolve_ticker(config, symbol)

    price_rows = storage.get_prices(t.symbol)
    if not price_rows:
        print(f"'{t.symbol}' icin fiyat verisi yok. Once calistir: python main.py update-prices {t.symbol}")
        return

    thresholds = config.decision_thresholds
    result = backtest_engine.run_backtest(
        symbol=t.symbol,
        price_rows=price_rows,
        buy_threshold=thresholds.get("buy", 0.3),
        sell_threshold=thresholds.get("sell", -0.3),
    )

    print(f"\n=== Backtest: {t.name} ({t.symbol}) ===")
    print(f"Islem sayisi   : {result.num_trades}")
    print(f"Kazanma orani  : {result.win_rate_pct}%")
    print(f"Toplam getiri  : {result.total_return_pct}%")
    print(f"Son bakiye     : {result.final_equity}")
    print("\nSon 10 islem:")
    for tr in result.trades[-10:]:
        print(f"  {tr}")


def main():
    parser = argparse.ArgumentParser(description="BIST Bot CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_update = sub.add_parser("update-prices", help="Fiyat verisini cek ve DB'ye yaz")
    p_update.add_argument("symbol", nargs="?", help="BIST kodu, ör. ASELS")
    p_update.add_argument("--all", action="store_true", help="config'teki tum hisseler")

    p_analyze = sub.add_parser("analyze", help="Guncel skor/karar uret")
    p_analyze.add_argument("symbol", help="BIST kodu, ör. ASELS")

    p_backtest = sub.add_parser("backtest", help="Gecmis veri uzerinde strateji testi")
    p_backtest.add_argument("symbol", help="BIST kodu, ör. ASELS")

    args = parser.parse_args()

    if args.command == "update-prices":
        if not args.all and not args.symbol:
            print("Sembol belirt ya da --all kullan.", file=sys.stderr)
            sys.exit(1)
        update_prices(args.symbol, args.all)
    elif args.command == "analyze":
        analyze_symbol(args.symbol)
    elif args.command == "backtest":
        run_backtest(args.symbol)


if __name__ == "__main__":
    main()

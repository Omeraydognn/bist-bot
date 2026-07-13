"""
ORKESTRATOR - botun beyni.

Gorevleri:
  1. Seans durumunu kontrol et (10:00-18:00 bilinci)
  2. Tum zaman dilimlerinin fiyat verisini guncelle
  3. Haber / temel / derinlik / AKD verilerini topla (aktif olanlari)
  4. MTF + scalp + tum sinyalleri birlestir
  5. Karari uret, veritabanina yaz, bildirimi tetikle
  6. Bir sonraki dongune kadar bekle

`run_once()` tek tur calistirir (test ve manuel kullanim icin).
`run_loop()` seans boyunca surekli calisir (canli mod).
"""
from __future__ import annotations

import asyncio
import json
import time as time_module
from datetime import datetime

from bist_bot.config import get_config, TickerConfig
from bist_bot.data.storage import Storage
from bist_bot.data.price_fetcher import get_price_fetcher
from bist_bot.analysis import sentiment, fundamental
from bist_bot.analysis.multi_timeframe import analyze_mtf, MTFResult
from bist_bot.analysis.depth_analysis import analyze_depth
from bist_bot.analysis.akd_analysis import analyze_akd
from bist_bot.analysis.scalping import CostModel
from bist_bot.market.session import get_session_state
from bist_bot.trading.paper_trader import PaperTrader
from bist_bot.notify.telegram_notifier import TelegramNotifier
from bist_bot.ai.brain import AIBrain


class Orchestrator:
    def __init__(self, config=None, paper_trading: bool = True):
        self.config = config or get_config()
        self.storage = Storage(self.config.db_path)
        self.cost_model = CostModel()
        self.paper_trading = paper_trading
        if paper_trading:
            risk = self.config.risk
            paper_db = self.config.db_path.parent / "paper_portfolio.db"
            self.paper = PaperTrader(
                paper_db,
                starting_cash=100_000.0,
                cost_model=self.cost_model,
                max_position_pct=risk.get("max_position_pct", 1.0) if len(self.config.tickers) > 1 else 1.0,
            )
        else:
            self.paper = None
        self.notifier = TelegramNotifier()

        # AI Beyin: NVIDIA NIM API uzerinden calisan ust karar motoru
        ai_cfg = self.config.ai
        self.ai_brain = AIBrain(
            model=ai_cfg.get('model', 'nvidia/llama-3.1-nemotron-ultra-253b-v1'),
            temperature=ai_cfg.get('temperature', 0.1),
        )
        self.ai_fallback = ai_cfg.get('fallback_to_math', True)

    # ------------------------------------------------------------
    def fetch_all_timeframes(self, ticker: TickerConfig) -> dict[str, list[dict]]:
        """Config'teki TUM zaman dilimleri icin veri ceker."""
        price_cfg = self.config.data_sources.get("price", {})
        provider = price_cfg.get("provider", "yahoo")
        fetcher = get_price_fetcher(provider)

        frames = {}
        for tf in price_cfg.get("timeframes", [{"interval": "1d", "lookback_days": 730}]):
            interval = tf["interval"]
            try:
                rows = fetcher.fetch_ohlcv(
                    ticker.yahoo_symbol,
                    lookback_days=tf.get("lookback_days", 60),
                    interval=interval,
                )
                frames[interval] = rows
            except Exception as e:
                print(f"  [uyari] {ticker.symbol} {interval} verisi cekilemedi: {e}")
                frames[interval] = []
        return frames

    # ------------------------------------------------------------
    def analyze_ticker(
        self,
        ticker: TickerConfig,
        frames: dict[str, list[dict]] | None = None,
        news_items: list[dict] | None = None,
        fundamental_data: dict | None = None,
        depth_rows: list[dict] | None = None,
        akd_rows: list[dict] | None = None,
        yabanci_takas: dict | None = None,
    ) -> dict:
        """
        Tek hisse icin TAM analiz. Veri parametre olarak da verilebilir
        (test / manuel gercek-veri besleme icin) ya da otomatik cekilir.
        """
        if frames is None:
            frames = self.fetch_all_timeframes(ticker)

        # 1) Coklu zaman dilimi + scalp + seans
        mtf: MTFResult = analyze_mtf(frames, cost_model=self.cost_model)

        # 2) Haber sentiment
        news_result = sentiment.analyze_news(news_items) if news_items else None

        # 3) Temel analiz
        fund_result = fundamental.analyze(fundamental_data) if fundamental_data else None

        # 4) Derinlik
        depth_result = analyze_depth(depth_rows)
        if depth_result["score"] is None:
            depth_result = None

        # 5) AKD / takas
        akd_result = analyze_akd(akd_rows, yabanci_takas)
        if akd_result and akd_result["score"] is None:
            akd_result = None

        # 6) MTF karari ana omurga; diger sinyaller duzeltme uygular
        adjust = 0.0
        adjust_notes = []
        for name, res, w in (
            ("haber", news_result, 0.15),
            ("temel", fund_result, 0.10),
            ("derinlik", depth_result, 0.15),
            ("akd", akd_result, 0.10),
        ):
            if res and res.get("score") is not None:
                adjust += res["score"] * w
                adjust_notes.append(f"{name}: {res['score']:+.2f}")

        final_score = max(-1.0, min(1.0, mtf.combined_score + adjust))

        # Aksiyonu guncelle: duzeltme sinyali esigi gecirebilir/dusurebilir
        thresholds = self.config.decision_thresholds
        if mtf.action in ("AL", "SAT"):
            action = mtf.action   # MTF tetigi ana karar (seans vetosu zaten iceride)
        elif final_score >= thresholds.get("buy", 0.3):
            action = "AL"
        elif final_score <= thresholds.get("sell", -0.3):
            action = "SAT"
        else:
            action = "BEKLE"

        # Guncel Fiyati (Son Kapanis) Al
        last_close = None
        for tf_key in ("15m", "30m", "1h", "1d"):
            rows = frames.get(tf_key)
            if rows:
                last_close = rows[-1].get("close")
                break

        result = {
            "symbol": ticker.symbol,
            "fiyat": round(last_close, 2) if last_close else None,
            "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "aksiyon": action,
            "guven": mtf.confidence,
            "mtf_skor": mtf.combined_score,
            "duzeltmeler": adjust_notes,
            "nihai_skor": round(final_score, 3),
            "katmanlar": mtf.per_timeframe,
            "firsat_notu": mtf.firsat_notu,
            "seans": mtf.session.note if mtf.session else "-",
            "gerekce": mtf.reason,
            "scalp": {
                "hedef_pct": mtf.scalp_signal.take_profit_pct,
                "stop_pct": mtf.scalp_signal.stop_loss_pct,
                "beklenen_net_pct": mtf.scalp_signal.expected_net_pct,
            } if mtf.scalp_signal and mtf.scalp_signal.action != "BEKLE" else None,
        }

        # =====================================================
        # AI BEYİN: Nihai karar burada verilir
        # Matematik motor "danışman", AI "başkomutan"
        # =====================================================
        if self.ai_brain.enabled:
            ai_decision = self.ai_brain.decide(result)
            if ai_decision is not None:
                old_action = result["aksiyon"]
                result["aksiyon"] = ai_decision.action
                result["ai_gerekce"] = ai_decision.reasoning
                result["ai_guven"] = ai_decision.confidence
                result["ai_veto"] = ai_decision.vetoed
                action = ai_decision.action  # Paper trading de AI kararini kullansin
                if ai_decision.vetoed:
                    print(f"  [AI VETO] Matematik: {old_action} → AI: {ai_decision.action} | {ai_decision.reasoning}")
                else:
                    print(f"  [AI ONAY] {ai_decision.action} | {ai_decision.reasoning}")
            elif self.ai_fallback:
                result["ai_gerekce"] = "AI yanıt veremedi, matematik motor kararı korundu."
                print("  [AI] Fallback: matematik motor karari korundu.")

        # PAPER TRADING: sinyali sanal portfoye uygula
        if self.paper is not None:
            if last_close:
                # Seans sonu zorunlu kapanis kontrolu
                if mtf.session and mtf.session.should_close_positions:
                    for msg in self.paper.check_positions({ticker.symbol: last_close}, force_close_all=True):
                        print(f"  {msg}")
                        self.notifier.notify_trade(msg)
                else:
                    # Once acik pozisyonlarda stop/target kontrolu
                    for msg in self.paper.check_positions({ticker.symbol: last_close}):
                        print(f"  {msg}")
                        self.notifier.notify_trade(msg)
                    # Sonra yeni sinyal uygula
                    if action in ("AL", "SAT"):
                        scalp_info = result.get("scalp") if "result" in dir() else None
                        stop = mtf.scalp_signal.stop_loss_pct if mtf.scalp_signal and mtf.scalp_signal.action != "BEKLE" else self.config.risk.get("stop_loss_pct", 0.05) * 100
                        target = mtf.scalp_signal.take_profit_pct if mtf.scalp_signal and mtf.scalp_signal.action != "BEKLE" else self.config.risk.get("take_profit_pct", 0.10) * 100
                        trade = self.paper.process_signal(
                            ticker.symbol, action, last_close,
                            stop_pct=stop, target_pct=target,
                            reason=f"skor {final_score:+.2f}",
                        )
                        print(f"  {trade['message']}")
                        if trade["executed"]:
                            self.notifier.notify_trade(trade["message"])

        # DB'ye kaydet
        self.storage.insert_signal({
            "symbol": ticker.symbol,
            "date": result["zaman"],
            "technical_score": mtf.combined_score,
            "news_score": news_result["score"] if news_result else None,
            "fundamental_score": fund_result["score"] if fund_result else None,
            "depth_score": depth_result["score"] if depth_result else None,
            "akd_score": akd_result["score"] if akd_result else None,
            "final_score": final_score,
            "decision": action,
            "details": json.dumps(result, ensure_ascii=False, default=str),
        })

        # Telegram sinyal bildirimi (Sadece borsa acikken veya cok onemli bir haber geldiyse)
        if mtf.session and mtf.session.is_open:
            self.notifier.notify_signal(result)
        # Eger borsa kapaliyken "haber" bazli ayri bir bildirim mekanizmasi eklenecekse buraya eklenebilir.

        return result

    # ------------------------------------------------------------
    def run_once(self) -> list[dict]:
        """Tum aktif hisseler icin tek tur analiz."""
        results = []
        for ticker in self.config.tickers:
            print(f"\n>>> {ticker.name} ({ticker.symbol}) analiz ediliyor...")
            res = self.analyze_ticker(ticker)
            results.append(res)
            self._print_result(res)
        return results

    def run_loop(self, interval_seconds: int = 300):
        """
        Canli dongu: seans acikken her `interval_seconds`'ta bir tam analiz.
        Seans kapaliyken bir sonraki acilisi bekler.
        """
        print("Bot canli moda gecti. Ctrl+C ile durdurabilirsin.")
        daily_report_sent_for = None
        while True:
            try:
                state = get_session_state()
                if state.is_open:
                    self.run_once()
                    time_module.sleep(interval_seconds)
                else:
                    # Seans kapaliyken de KAP haberlerini ve bilancolari kacirmamak 
                    # icin saatte bir analiz yapilir (fakat AL/SAT islemi acilmaz).
                    today = datetime.now().strftime("%Y-%m-%d")
                    if (self.paper is not None and daily_report_sent_for != today
                            and datetime.now().hour >= 18 and datetime.now().weekday() < 5):
                        report = self.paper.daily_report(today)
                        if report["islem_sayisi"] > 0:
                            st = self.paper.status()
                            self.notifier.notify_daily_report(report, st.equity, st.total_return_pct)
                        daily_report_sent_for = today
                    
                    print(f"[{datetime.now():%H:%M}] {state.note} Haber/bilanco guncellemesi yapiliyor...")
                    self.run_once() # Haberleri/verileri guncelle (session kapali oldugu icin islem acilmaz)
                    print(f"[{datetime.now():%H:%M}] Uyku moduna gecildi, 60 dakika sonra tekrar uyanacak.")
                    time_module.sleep(3600) # Seans kapaliyken saatte 1 uyanir
            except KeyboardInterrupt:
                print("Bot durduruldu (Ctrl+C).")
                break
            except Exception as e:
                # Dongu HICBIR hatada olmemeli: bildir, bekle, devam et
                print(f"[HATA] {e}")
                self.notifier.notify_error(str(e)[:300])
                time_module.sleep(60)

    @staticmethod
    def _print_result(res: dict):
        fiyat_str = f" | Fiyat: {res['fiyat']}" if res.get('fiyat') else ""
        print(f"  Aksiyon    : {res['aksiyon']}{fiyat_str} (guven {res['guven']})")
        print(f"  Nihai skor : {res['nihai_skor']} (MTF {res['mtf_skor']}, duzeltme: {res['duzeltmeler']})")
        if res["scalp"]:
            print(f"  Scalp plani: hedef %{res['scalp']['hedef_pct']} / stop %{res['scalp']['stop_pct']}")
        print(f"  Firsatlar  : {res['firsat_notu']}")
        print(f"  Seans      : {res['seans']}")

    # ------------------------------------------------------------
    # WEBSOCKET (CANLI VERI) METOTLARI
    # ------------------------------------------------------------
    async def run_ws_loop(self):
        """
        Gecikmeli polling (run_loop) yerine, Algolab WebSocket uzerinden 
        saniyelik event-driven islem yapar.
        """
        from bist_bot.data.algolab_ws import AlgolabWSClient
        from bist_bot.data.depth_fetcher import get_depth_fetcher

        print("Bot ASENKRON (WebSocket) moda gecti. Kesintisiz veri dinleniyor...")
        self.ws_client = AlgolabWSClient()
        self.depth_fetcher = get_depth_fetcher("algolab")

        # 1. Gecmis 60 gunun verisini onbellege al (RSI, MACD hesaplamak icin sart)
        self.history_cache = {}
        for ticker in self.config.tickers:
            print(f"{ticker.symbol} gecmis verisi onbellege aliniyor...")
            # Blocking cagriyi async icinde calistiriyoruz (ilk acilista bir kere)
            self.history_cache[ticker.symbol] = await asyncio.to_thread(self.fetch_all_timeframes, ticker)
            
            # Dinleyiciye kayit ol
            self.ws_client.subscribe_to_ticker(ticker.symbol, self._on_ws_message)

        # 2. Sonsuz dongude WS baglantisini ac ve dinle
        await self.ws_client.connect_and_listen()

    async def _on_ws_message(self, data: dict):
        """WebSocket'ten yeni tick veya derinlik geldiginde asenkron tetiklenir."""
        symbol = data.get("Symbol")
        ticker = next((t for t in self.config.tickers if t.symbol == symbol), None)
        if not ticker:
            return

        state = get_session_state()
        if not state.is_open:
            return  # Seans kapaliyken islem yapma

        # Eger gelen veri Derinlik paketi ise
        if "Depth" in data:
            self.depth_fetcher._current_depth[symbol] = data["Depth"]

        # Eger gelen veri Fiyat tick'i ise
        if "Price" in data:
            price = float(data["Price"])
            vol = float(data.get("Volume", 0))
            
            # Onbellekteki son 15dk mumunu guncelle (canli fiyat akisi)
            frames = self.history_cache.get(symbol)
            if frames and frames.get("15m"):
                # Son mumu canli guncelle
                frames["15m"][-1]["close"] = price
                frames["15m"][-1]["volume"] += vol

            # Canli derinlik verisini al
            depth_rows = await self.depth_fetcher.fetch_depth(symbol)

            # Analizi calistir (CPU bound oldugu icin to_thread kullanabiliriz ama hizli calisir)
            res = await asyncio.to_thread(
                self.analyze_ticker,
                ticker=ticker,
                frames=frames,
                depth_rows=depth_rows
            )
            
            # Sinyal degisimi varsa ekrana bas
            if res["aksiyon"] in ("AL", "SAT"):
                print(f"[{datetime.now():%H:%M:%S}] ANLIK SINYAL -> {symbol}: {res['aksiyon']} | Fiyat: {price}")

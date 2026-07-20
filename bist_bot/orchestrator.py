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
                max_holding_min=risk.get("max_holding_min", 60),
            )
        else:
            self.paper = None
        self.notifier = TelegramNotifier()

        # KAR REALIZASYONU DONGUSU (yuksekten sat -> dusukten geri al ->
        # hisse adedini buyut). Kurallar 15m ASELS backtest'iyle secildi.
        swing_cfg = self.config.raw.get("swing", {})
        if swing_cfg.get("enabled", True):
            from bist_bot.trading.swing_cycler import SwingCycler
            self.swing = SwingCycler(
                self.config.db_path.parent / "swing_portfolio.db",
                day_gain_pct=swing_cfg.get("day_gain_pct", 2.0),
                z_sell=swing_cfg.get("z_sell", 1.5),
                dip_pct=swing_cfg.get("dip_pct", 0.5),
                runaway_pct=swing_cfg.get("runaway_pct", 1.5),
            )
        else:
            self.swing = None
        # Sinyal tekrar filtresi: ayni hisse icin ayni aksiyon 30 dk icinde
        # tekrar bildirilmez (Telegram spam'ini onler)
        self._last_notified: dict[str, tuple[str, datetime]] = {}
        self.notify_repeat_minutes = 30
        # Stop sonrasi sogutma: stop yiyen hissede 30 dk yeni pozisyon acilmaz
        # (backtest'in kazanan konfigurasyonunun parcasi - whipsaw korumasi)
        self._last_stop_out: dict[str, datetime] = {}
        self.stop_cooldown_minutes = 30
        # Telegram sohbeti icin son analiz sonuclari (sembol -> result)
        self.last_results: dict[str, dict] = {}

        # AI Beyin: NVIDIA NIM API uzerinden calisan ust karar motoru
        ai_cfg = self.config.ai
        self.ai_brain = AIBrain(
            model=ai_cfg.get('model', 'meta/llama-3.1-70b-instruct'),
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
        # Config'teki hassas esikler MTF motoruna da gecer (onceden sadece
        # yedek yola uygulaniyordu, MTF kendi ici 0.25 kullaniyordu - duzeltildi)
        thresholds = self.config.decision_thresholds
        scalp_cfg = self.config.raw.get("scalp", {})
        mtf: MTFResult = analyze_mtf(
            frames,
            cost_model=self.cost_model,
            buy_threshold=thresholds.get("buy", 0.15),
            sell_threshold=thresholds.get("sell", -0.15),
            min_net_edge_pct=scalp_cfg.get("min_net_edge_pct", 0.40),
            move_trigger_pct=scalp_cfg.get("move_trigger_pct", 1.0),
        )

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
        if mtf.action in ("AL", "SAT"):
            action = mtf.action   # MTF tetigi ana karar (seans vetosu zaten iceride)
        elif final_score >= thresholds.get("buy", 0.3):
            action = "AL"
        elif final_score <= thresholds.get("sell", -0.3):
            action = "SAT"
        else:
            action = "BEKLE"

        # Guncel Fiyati (Son Kapanis) Al (Gecikmeli)
        last_close = None
        for tf_key in ("5m", "15m", "30m", "1h", "1d"):
            rows = frames.get(tf_key)
            if rows:
                last_close = rows[-1].get("close")
                break

        # =====================================================
        # ANLIK FIYAT (LIVE PRICE) & QUANT REVERSAL HESABI
        # =====================================================
        live_price = last_close
        quant_reversal_signal = None
        try:
            import yfinance as yf
            from bist_bot.analysis.scalping import analyze_quant_reversal
            
            # Hizli Quant Analizi icin 1-dakikalik mumlari cek (bugun)
            df_1m = yf.download(ticker.yahoo_symbol, period="1d", interval="1m", progress=False, auto_adjust=False)
            if df_1m is not None and not df_1m.empty:
                if hasattr(df_1m.columns, "nlevels") and df_1m.columns.nlevels > 1:
                    df_1m.columns = df_1m.columns.get_level_values(0)
                
                live_price = float(df_1m["Close"].iloc[-1])
                quant_reversal_signal = analyze_quant_reversal(df_1m)
                
        except Exception as e:
            print(f"  [UYARI] Anlik Quant/Fiyat verisi cekilemedi: {e}")

        result = {
            "symbol": ticker.symbol,
            "fiyat": round(live_price, 2) if live_price else None,
            "gecikmeli_fiyat": round(last_close, 2) if last_close else None,
            "quant_sinyal": quant_reversal_signal,
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
                "strateji": mtf.scalp_signal.strategy,
                "hedef_pct": mtf.scalp_signal.take_profit_pct,
                "stop_pct": mtf.scalp_signal.stop_loss_pct,
                "beklenen_net_pct": mtf.scalp_signal.expected_net_pct,
            } if mtf.scalp_signal and mtf.scalp_signal.action != "BEKLE" else None,
        }

        # --- VERI TAZELIK BEKCISI: seans acikken son mum 30 dk'dan eskiyse
        # veri akisi kopmus demektir -> bayat fiyatla sinyal URETILMEZ,
        # kullaniciya bir kez uyari gider (30 dk tekrar filtresiyle).
        data_fresh = True
        if mtf.session and mtf.session.is_open:
            newest = None
            for tf_key in ("5m", "15m"):
                rws = frames.get(tf_key)
                if rws and rws[-1].get("date"):
                    try:
                        dt = datetime.strptime(str(rws[-1]["date"])[:19], "%Y-%m-%d %H:%M:%S")
                        newest = dt if (newest is None or dt > newest) else newest
                    except (ValueError, TypeError):
                        continue
            if newest is None or (datetime.now() - newest).total_seconds() > 1800:
                data_fresh = False
                result["veri_uyarisi"] = f"Fiyat verisi guncel degil (son mum: {newest or 'yok'})."
                result["aksiyon"] = "BEKLE"
                action = "BEKLE"
                print(f"  [VERI] {result['veri_uyarisi']} Sinyal uretimi duraklatildi.")
                if self._should_notify(ticker.symbol, "VERI_ESKI"):
                    self.notifier.notify_error(
                        f"{ticker.symbol}: fiyat verisi guncellenemiyor (son mum: {newest or 'yok'}). "
                        f"Sinyaller duzelene kadar duraklatildi."
                    )

        # AI'in KURAL 0 (piyasa bilinci) icin ihtiyac duydugu yapilandirilmis
        # seans bilgisi - AI karar vermeden once bunu gormek ZORUNDA
        s = mtf.session
        result["piyasa_durumu"] = {
            "acik_mi": s.is_open if s else None,
            "faz": s.phase if s else "?",
            "pozisyon_acilabilir_mi": s.can_open_position if s else None,
            "kapanisa_dk": s.minutes_to_close if s else None,
            "not": s.note if s else "Seans bilgisi alinamadi.",
        }

        # =====================================================
        # AI BEYİN: Nihai karar burada verilir
        # Matematik motor "danışman", AI "başkomutan"
        # =====================================================
        if self.ai_brain.enabled and data_fresh:
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
                err = self.ai_brain.last_error or "Bilinmeyen hata."
                result["ai_gerekce"] = f"AI yanıt veremedi ({err}), matematik motor kararı korundu."
                print("  [AI] Fallback: matematik motor karari korundu.")

        # =====================================================
        # MUTLAK SEANS VETOSU: hangi motor uretirse uretsin
        # (skor esigi veya AI), borsa kapaliyken AL/SAT islenmez.
        # AL ayrica sadece pozisyon acilabilir pencerede gecerlidir;
        # SAT seans acikken her fazda serbesttir (pozisyon kapatma).
        # =====================================================
        session_open = bool(mtf.session and mtf.session.is_open)
        if action in ("AL", "SAT"):
            blocked = (not session_open) or (action == "AL" and not mtf.session.can_open_position)
            if blocked:
                result["ham_aksiyon"] = action
                result["seans_vetosu"] = mtf.session.note if mtf.session else "Seans bilgisi yok."
                action = "BEKLE"
                result["aksiyon"] = "BEKLE"

        # KAR REALIZASYONU DONGUSU: 15m veriyle tepe-satis / dip-geri-alim
        # (sadece seans acikken; sanal hisse-adedi portfoyu, gercek emir yok)
        if self.swing is not None and session_open and data_fresh and frames.get("15m"):
            for msg in self.swing.step(ticker.symbol, frames["15m"]):
                print(f"  {msg}")
                self.notifier.notify_raw(msg)

        # PAPER TRADING: sinyali sanal portfoye uygula (sadece seans acikken).
        # NOT: Kullanici islemleri KENDISI yapiyor - pozisyon kapanislari
        # ona "SAT ZAMANI" sinyali olarak gider (defter dili degil).
        if self.paper is not None and session_open and data_fresh:
            if last_close:
                # Seans sonu zorunlu kapanis kontrolu
                if mtf.session and mtf.session.should_close_positions:
                    for msg in self.paper.check_positions({ticker.symbol: last_close}, force_close_all=True):
                        print(f"  {msg}")
                        self.notifier.notify_exit_signal(msg)
                else:
                    # Once acik pozisyonlarda stop/target kontrolu
                    for msg in self.paper.check_positions({ticker.symbol: last_close}):
                        print(f"  {msg}")
                        self.notifier.notify_exit_signal(msg)
                        if "stop-loss" in msg:
                            self._last_stop_out[ticker.symbol] = datetime.now()
                    # Stop sonrasi sogutma: 30 dk icinde ayni hissede yeni AL yok
                    stop_dt = self._last_stop_out.get(ticker.symbol)
                    in_cooldown = (stop_dt is not None and
                                   (datetime.now() - stop_dt).total_seconds() < self.stop_cooldown_minutes * 60)
                    if action == "AL" and in_cooldown:
                        print(f"  [SOGUTMA] {ticker.symbol} az once stop yedi - "
                              f"{self.stop_cooldown_minutes} dk yeni giris yok.")
                    # Sonra yeni sinyal uygula.
                    # NOT (backtest 2026-07-15): sadece AL sinyali islem acar.
                    # SAT sinyaliyle pozisyon kapatmak test getirisini +%2.3'ten
                    # +%0.2'ye dusurdu (kazanan pozisyondan erken cikiyor) ->
                    # cikislari izleyen stop + hedef + zaman stopu yonetir.
                    # SAT sinyali Telegram bildirimi olarak kullaniciya gider.
                    elif action == "AL":
                        stop = mtf.scalp_signal.stop_loss_pct if mtf.scalp_signal and mtf.scalp_signal.action != "BEKLE" else self.config.risk.get("stop_loss_pct", 0.05) * 100
                        target = mtf.scalp_signal.take_profit_pct if mtf.scalp_signal and mtf.scalp_signal.action != "BEKLE" else self.config.risk.get("take_profit_pct", 0.10) * 100
                        trade = self.paper.process_signal(
                            ticker.symbol, action, last_close,
                            stop_pct=stop, target_pct=target,
                            reason=f"skor {final_score:+.2f}",
                        )
                        # Telegram'a AYRICA gonderilmez: kullanici 🟢 AL sinyalini
                        # zaten aldi; bu satir sadece sanal defter kaydidir.
                        print(f"  {trade['message']}")

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

        # Sohbet arayuzu icin son durumu sakla
        self.last_results[ticker.symbol] = result

        # Telegram sinyal bildirimi: sadece borsa acikken ve tekrar filtresinden
        # geciyorsa (ayni aksiyon 30 dk icinde tekrar bildirilmez)
        if session_open and data_fresh and action in ("AL", "SAT") and self._should_notify(ticker.symbol, action):
            self.notifier.notify_signal(result)

        # %1 HAREKET BILGI UYARISI: kullanicinin "her firsati goreyim" istegi.
        # Islem ACILMAZ (backtest: bu hareketi kovalamak her ayarda zarar etti),
        # ama kullanici hareketten haberdar edilir - karar kullanicinin.
        if session_open and data_fresh and mtf.scalp_signal:
            move = mtf.scalp_signal.move_info_pct
            move_trig = scalp_cfg.get("move_trigger_pct", 1.0)
            if move_trig and abs(move) >= move_trig:
                yon = "YUKSELIS" if move > 0 else "DUSUS"
                if self._should_notify(ticker.symbol, f"HAREKET_{yon}"):
                    self.notifier.notify_move_alert(ticker.symbol, move, result.get("fiyat"))
        # Eger borsa kapaliyken "haber" bazli ayri bir bildirim mekanizmasi eklenecekse buraya eklenebilir.

        return result

    # ------------------------------------------------------------
    def _should_notify(self, symbol: str, action: str) -> bool:
        """Ayni hisse icin ayni tip bildirimi kisa araliklarla tekrarlama."""
        key = f"{symbol}:{action}"
        now = datetime.now()
        last_time = self._last_notified.get(key)
        if last_time and (now - last_time[1]).total_seconds() < self.notify_repeat_minutes * 60:
            return False
        self._last_notified[key] = (action, now)
        return True

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

    def chat_context(self) -> str:
        """Telegram sohbeti icin botun guncel durum ozeti (AI'a baglam olarak gider)."""
        from bist_bot.market.session import get_session_state
        lines = []
        st = get_session_state()
        lines.append(f"Saat: {datetime.now():%Y-%m-%d %H:%M} | Seans: "
                     f"{'ACIK (' + st.phase + ')' if st.is_open else 'KAPALI'} — {st.note}")
        for sym, res in self.last_results.items():
            lines.append(
                f"{sym}: fiyat {res.get('fiyat')} TL | son karar: {res.get('aksiyon')} "
                f"| skor {res.get('nihai_skor')} | güven {res.get('guven')} "
                f"| analiz zamanı {res.get('zaman')}"
            )
            if res.get("gerekce"):
                lines.append(f"  gerekçe: {res['gerekce'][:250]}")
            if res.get("ai_gerekce"):
                lines.append(f"  AI görüşü: {res['ai_gerekce'][:200]}")
            if res.get("veri_uyarisi"):
                lines.append(f"  UYARI: {res['veri_uyarisi']}")
        if not self.last_results:
            lines.append("Henüz analiz yapılmadı (bot yeni başladı, ilk tur bekleniyor).")
        if self.paper is not None:
            try:
                ps = self.paper.status()
                lines.append(f"Paper portföy: {ps.equity} TL (getiri %{ps.total_return_pct}) "
                             f"| açık pozisyon: {ps.open_position_count}")
            except Exception:
                pass
        if self.swing is not None:
            for t in self.config.tickers:
                sw = self.swing.status(t.symbol)
                if sw:
                    lines.append(f"Kâr realizasyonu ({t.symbol}): mod {sw['mod']} "
                                 f"| hisse büyümesi %{sw['hisse_buyume_pct']} "
                                 f"| döngü {sw['dongu_sayisi']}"
                                 + (f" | geri alım bekleniyor (satış {sw['bekleyen_satis_fiyati']})"
                                    if sw['mod'] == 'NAKIT' else ""))
        return "\n".join(lines)

    def run_loop(self, interval_seconds: int = 300):
        """
        Canli dongu: seans acikken her `interval_seconds`'ta bir tam analiz.
        Seans kapaliyken bir sonraki acilisi bekler.
        """
        print("Bot canli moda gecti. Ctrl+C ile durdurabilirsin.")

        # Telegram sohbeti: kullanici bota yazinca AI duruma gore cevap verir
        from bist_bot.notify.telegram_chat import TelegramChat
        self.chat = TelegramChat(self.ai_brain, self.chat_context)
        self.chat.start()
        daily_report_sent_for = None
        while True:
            try:
                state = get_session_state()
                if state.is_open:
                    self.run_once()
                    time_module.sleep(interval_seconds)
                else:
                    from bist_bot.market.session import next_market_open, is_market_holiday, now_istanbul

                    now = now_istanbul()
                    is_trading_day = now.weekday() < 5 and not is_market_holiday(now.date())

                    # Gun sonu raporu sadece islem gunlerinde, seans kapandiktan sonra
                    today = now.strftime("%Y-%m-%d")
                    if (self.paper is not None and daily_report_sent_for != today
                            and now.hour >= 18 and is_trading_day):
                        report = self.paper.daily_report(today)
                        if report["islem_sayisi"] > 0:
                            st = self.paper.status()
                            self.notifier.notify_daily_report(report, st.equity, st.total_return_pct)
                        daily_report_sent_for = today

                    if is_trading_day and 8 <= now.hour < 19:
                        # Islem gunu, seans oncesi/sonrasi: veri ve haberleri tazele
                        # (seans vetosu nedeniyle islem acilmaz, bildirim gitmez)
                        print(f"[{now:%H:%M}] {state.note} Veri guncellemesi yapiliyor...")
                        self.run_once()
                        sleep_s = 3600
                    else:
                        # Tatil / hafta sonu / gece: bir sonraki acilisa kadar uyu
                        # (en fazla 1 saatlik dilimlerle, boylece Ctrl+C ve
                        # takvim degisikligi hizli fark edilir)
                        wake = next_market_open(now)
                        sleep_s = min(3600, max(60, (wake - now).total_seconds()))
                        print(f"[{now:%H:%M}] {state.note} Sonraki acilis: {wake:%Y-%m-%d %H:%M}.")
                    print(f"[{now:%H:%M}] Uyku moduna gecildi ({int(sleep_s // 60)} dk).")
                    time_module.sleep(sleep_s)
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

"""
TELEGRAM BILDIRIM modulu.

Nasil calisir (kurulum adimlari README'de de var):
  1. Telegram'da @BotFather'a git, /newbot yaz, bir isim ver.
     BotFather sana bir TOKEN verir (ör: 123456:ABC-DEF...).
  2. Olusturdugun botla bir konusma baslat ("/start" yaz).
  3. chat_id'ni ogren: tarayicida su adresi ac:
     https://api.telegram.org/bot<TOKEN>/getUpdates
     Donen JSON'da "chat":{"id": 123456789} degerini bul.
  4. Proje kokundeki .env dosyasina ekle:
     TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
     TELEGRAM_CHAT_ID=123456789

Bu modul harici kutuphane GEREKTIRMEZ - Telegram'in resmi HTTP API'sine
duz `requests` ile POST atar. Token yoksa sessizce konsola yazar
(bot calismaya devam eder, bildirim susar).

Mesaj tipleri:
  * Sinyal bildirimi (AL/SAT + plan + gerekce)
  * Islem bildirimi (paper/gercek islem gerceklesti)
  * Gun sonu raporu
  * Hata/uyari bildirimi (veri kesilirse haber ver)
"""
from __future__ import annotations

import os
from datetime import datetime

import requests

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None,
                 min_confidence_to_notify: float = 0.0):
        """
        min_confidence_to_notify: bu guvenin altindaki sinyaller mesaj atmaz
        (0.0 = kullanicinin istedigi gibi kucuk firsatlar dahil HER SEY bildirilir;
        cok mesaj gelirse config'ten yukseltilebilir).
        """
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self.min_confidence = min_confidence_to_notify
        self.enabled = bool(self.token and self.chat_id)
        if not self.enabled:
            print("[telegram] Token/chat_id tanimli degil - bildirimler konsola yazilacak. "
                  "Kurulum icin README'deki Telegram bolumune bak.")

    # ------------------------------------------------------------
    def _send(self, text: str) -> bool:
        if not self.enabled:
            print(f"[telegram-konsol] {text}")
            return False
        try:
            resp = requests.post(
                TELEGRAM_API.format(token=self.token),
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            if resp.status_code != 200:
                print(f"[telegram] Gonderim hatasi: {resp.status_code} {resp.text[:200]}")
                return False
            return True
        except requests.RequestException as e:
            print(f"[telegram] Baglanti hatasi: {e}")
            return False

    # ------------------------------------------------------------
    def notify_signal(self, result: dict) -> bool:
        """Orkestratorun analyze_ticker ciktisini mesaja cevirir."""
        aksiyon = result.get("aksiyon", "?")
        
        # Sadece AL/SAT mesajlarini Telegram'a gonder, BEKLE ise sessiz kal
        if aksiyon == "BEKLE":
            return False

        emoji = "🟢" if aksiyon == "AL" else ("🔴" if aksiyon == "SAT" else "⚪")
        fiyat_str = f" @ {result['fiyat']} TL" if result.get("fiyat") else ""
        lines = [
            f"{emoji} <b>{result['symbol']} — {aksiyon}</b>{fiyat_str}",
            f"Skor: {result.get('nihai_skor')} | Güven: {result.get('guven')}",
        ]
        scalp = result.get("scalp")
        if scalp:
            lines.append(f"🎯 Hedef: %{scalp['hedef_pct']} | 🛑 Stop: %{scalp['stop_pct']} "
                         f"| Beklenen net: %{scalp['beklenen_net_pct']}")
        if result.get("firsat_notu"):
            lines.append(f"Katmanlar: {result['firsat_notu']}")
        if result.get("ai_gerekce"):
            veto_icon = "⚡" if result.get("ai_veto") else "✅"
            lines.append(f"🧠 AI: {veto_icon} {result['ai_gerekce']}")
        if result.get("seans") and result["seans"] != "-" and "Normal" not in result["seans"]:
            lines.append(f"⏰ {result['seans']}")
        lines.append(f"<i>{result.get('zaman', datetime.now().strftime('%H:%M'))}</i>")
        return self._send("\n".join(lines))

    # ------------------------------------------------------------
    def notify_trade(self, message: str) -> bool:
        """Paper/gercek islem gerceklestiginde."""
        return self._send(f"💼 {message}")

    # ------------------------------------------------------------
    def notify_daily_report(self, report: dict, equity: float, total_return_pct: float) -> bool:
        kz = report.get("gunluk_net_kz", 0)
        emoji = "📈" if kz >= 0 else "📉"
        return self._send(
            f"{emoji} <b>Gün Sonu Raporu — {report['tarih']}</b>\n"
            f"İşlem: {report['islem_sayisi']} | Kapanan: {report['kapanan_pozisyon']} "
            f"| Kazanan: {report['kazanan']}\n"
            f"Günlük net K/Z: <b>{kz:+.2f} TL</b>\n"
            f"Toplam portföy: {equity:.2f} TL ({total_return_pct:+.2f}%)"
        )

    # ------------------------------------------------------------
    def notify_error(self, error_msg: str) -> bool:
        return self._send(f"⚠️ <b>Bot uyarısı:</b> {error_msg}")

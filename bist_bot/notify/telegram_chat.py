"""
TELEGRAM SOHBET modulu - kullanici bota yazinca AI cevap verir.

Nasil calisir:
  * Arka planda bir thread, Telegram getUpdates API'sini uzun-polling ile
    dinler (webhook gerekmez, Render'da da calisir).
  * SADECE .env'deki TELEGRAM_CHAT_ID'den gelen mesajlara cevap verir
    (baskasi botu bulursa sessiz kalir - guvenlik).
  * Soru, botun GUNCEL DURUMU (son sinyal, fiyat, seans, portfoy, kar
    realizasyonu dongusu) ile birlikte AI beyne gonderilir; AI Turkce,
    kisa ve duruma dayali cevap verir.
  * AI erisilemezse durum ozeti duz metin olarak doner (bot asla sessiz
    kalmaz).
  * Bot yeniden basladiginda eski mesaj birikintisine cevap YAZMAZ
    (sadece basladiktan sonra gelen mesajlar islenir).

Hizli komutlar (AI'a gitmeden aninda cevap):
  /durum  -> guncel analiz + seans ozeti
  /rapor  -> paper portfoy + kar realizasyonu dongusu ozeti
"""
from __future__ import annotations

import os
import time
import threading

import requests

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramChat:
    def __init__(self, ai_brain, context_provider,
                 token: str | None = None, chat_id: str | None = None):
        """
        ai_brain: AIBrain nesnesi (chat metodu kullanilir)
        context_provider: cagrildiginda botun guncel durum METNI'ni donduren fonksiyon
        """
        self.ai_brain = ai_brain
        self.context_provider = context_provider
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = str(chat_id or os.environ.get("TELEGRAM_CHAT_ID") or "")
        self.enabled = bool(self.token and self.chat_id)
        self._thread: threading.Thread | None = None
        if not self.enabled:
            print("[telegram-sohbet] Token/chat_id yok - sohbet devre disi.")

    # ------------------------------------------------------------
    def start(self):
        """Dinleyiciyi arka plan thread'inde baslatir."""
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print("[telegram-sohbet] Dinleme basladi - bota yazabilirsin.")

    # ------------------------------------------------------------
    def _send(self, text: str):
        try:
            requests.post(
                API.format(token=self.token, method="sendMessage"),
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        except requests.RequestException as e:
            print(f"[telegram-sohbet] Gonderim hatasi: {e}")

    # ------------------------------------------------------------
    def _poll_loop(self):
        offset = None
        startup_ts = time.time()
        # Baslangicta birikmis eski mesajlari atla (yeniden basladiginda
        # gecmis sorulara toplu cevap yagdirmasin)
        try:
            r = requests.get(API.format(token=self.token, method="getUpdates"),
                             params={"timeout": 0}, timeout=15).json()
            updates = r.get("result", [])
            if updates:
                offset = updates[-1]["update_id"] + 1
        except requests.RequestException:
            pass

        while True:
            try:
                r = requests.get(
                    API.format(token=self.token, method="getUpdates"),
                    params={"timeout": 30, "offset": offset},
                    timeout=40,
                ).json()
                for upd in r.get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message") or {}
                    if str((msg.get("chat") or {}).get("id")) != self.chat_id:
                        continue  # yabanci sohbetlere cevap yok
                    if msg.get("date", 0) < startup_ts - 60:
                        continue  # eski birikinti
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue
                    print(f"[telegram-sohbet] Soru: {text[:80]}")
                    try:
                        answer = self._answer(text)
                    except Exception as e:
                        answer = f"Cevap uretilirken hata olustu: {str(e)[:150]}"
                    self._send(answer)
            except requests.RequestException:
                time.sleep(5)
            except Exception as e:
                print(f"[telegram-sohbet] Dongu hatasi: {e}")
                time.sleep(5)

    # ------------------------------------------------------------
    def _answer(self, question: str) -> str:
        context = self.context_provider() if self.context_provider else "Durum bilgisi yok."

        q = question.lower()
        if q in ("/durum", "durum", "/status"):
            return f"📊 <b>Guncel Durum</b>\n{context}"
        if q in ("/rapor", "rapor", "/report"):
            return f"📊 <b>Rapor</b>\n{context}"
        if q in ("/start", "/help", "yardim", "/yardim"):
            return ("Merhaba! Bana soru sorabilirsin (ör: 'ASELS şu an nasıl?', "
                    "'neden SAT verdin?', 'portföy ne durumda?').\n"
                    "Hızlı komutlar: /durum, /rapor")

        # AI'a duruma dayali cevap urettir
        if self.ai_brain and self.ai_brain.enabled:
            answer = self.ai_brain.chat(question, context)
            if answer:
                return answer
        # AI yoksa/cokmusse: durum ozeti + aciklama
        return (f"(AI şu an yanıt veremiyor, güncel durumu gönderiyorum)\n\n{context}")

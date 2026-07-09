# BIST Bot — Faz 1 İskeleti

BIST hisseleri için teknik analiz + haber sentiment + (ileride) temel analiz,
derinlik ve AKD/takas verisini birleştirip AL/SAT/TUT kararı üreten botun
temel mimarisi. **Tamamen ticker-agnostic**: yeni hisse eklemek için tek
yapman gereken `config/settings.yaml` dosyasına yeni bir blok eklemek.

## Klasör yapısı

```
bist_bot/
├── config/settings.yaml       # TEK konfigürasyon noktası (hisseler, ağırlıklar, eşikler)
├── main.py                    # CLI giriş noktası
├── test_pipeline.py           # internetsiz, sahte veriyle uçtan uca doğrulama
├── bist_bot/
│   ├── config.py              # settings.yaml yükleyici
│   ├── data/
│   │   ├── storage.py         # SQLite (tüm ticker'lar için tek şema)
│   │   ├── price_fetcher.py   # Yahoo Finance (yfinance) — factory pattern
│   │   ├── news_fetcher.py    # KAP iskeleti + test için Dummy fetcher
│   │   ├── depth_fetcher.py   # derinlik verisi (Faz 5'e kadar pasif)
│   │   └── akd_takas_fetcher.py
│   ├── analysis/
│   │   ├── technical.py       # RSI, MACD, Bollinger, SMA/EMA, hacim
│   │   ├── sentiment.py       # haber sentiment (anahtar kelime tabanlı, başlangıç)
│   │   └── fundamental.py     # placeholder
│   ├── decision/scorer.py     # tüm sinyalleri ağırlıklandırıp nihai karar
│   └── backtest/engine.py     # geçmiş veri üzerinde strateji testi
```

## Kurulum (kendi bilgisayarında)

```bash
cd bist_bot
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Önce doğrulama (internetsiz)

Mimarinin doğru kurulduğunu internete çıkmadan test etmek için:

```bash
python test_pipeline.py
```

Bu, sahte fiyat verisiyle config → storage → teknik analiz → sentiment →
karar motoru → backtest zincirinin uçtan uca çalıştığını gösterir.

## Gerçek kullanım

```bash
# 1) ASELS için fiyat verisini çek ve veritabanına yaz
python main.py update-prices ASELS

# 2) Güncel analiz + AL/SAT/TUT kararı
python main.py analyze ASELS

# 3) Geçmiş veri üzerinde stratejiyi test et
python main.py backtest ASELS
```

## Yeni hisse eklemek

`config/settings.yaml` içindeki `tickers` listesine şu formatta ekle:

```yaml
  - symbol: "THYAO"
    yahoo_symbol: "THYAO.IS"
    name: "Türk Hava Yolları"
    sector: "Havacılık"
    enabled: true
```

Sonra: `python main.py update-prices THYAO` ve `python main.py analyze THYAO`.
Kodda hiçbir yeri değiştirmene gerek yok.

## Şu an aktif olan / olmayan veri kaynakları

| Kaynak | Durum | Not |
|---|---|---|
| Fiyat (OHLCV) | ✅ Aktif | Yahoo Finance (yfinance), ücretsiz, gecikmeli |
| Haberler | ⚠️ İskelet | KAP resmi "Veri Yayın Servisi" abonelik gerektiriyor; şimdilik `DummyNewsFetcher` ile test edilebilir |
| Temel analiz | ⚠️ İskelet | Oranlar (F/K, PD/DD) henüz bağlanmadı |
| Derinlik (order book) | ❌ Pasif | Broker API'si (örn. Algolab/Deniz Yatırım) gerekiyor |
| AKD / Takas | ❌ Pasif | Resmi açık API yok, Takasbank/Matriks entegrasyonu gerekiyor |

Karar motoru (`decision/scorer.py`), aktif olmayan kaynakların ağırlığını
otomatik olarak diğer kaynaklara dağıtır — yani şu an sadece teknik analiz +
(dummy) haber + temel analiz ile de tutarlı çalışır, yeni kaynak eklendikçe
otomatik devreye girer.

## Sıradaki adımlar (yol haritası)

1. **Faz 1 (şimdiki durum):** Fiyat verisi + teknik analiz + backtest çalışıyor.
2. **Faz 2:** KAP Veri Yayın Servisi'ne abone olup `news_fetcher.py`'deki
   `KAPNewsFetcher`'ı tamamla; sentiment analizini gerçek haberlerle besle.
3. **Faz 3:** Temel analiz oranlarını (yfinance `.info` veya KAP finansal
   tablolarından) `fundamental.py`'ye bağla.
4. **Faz 4:** Bir broker API'sine (örn. Algolab) kaydolup derinlik verisini
   `depth_fetcher.py` üzerinden bağla.
5. **Faz 5:** İstenirse gerçek emir gönderimi (execution) eklenir — bu adım
   gerçek para riski taşıdığı için dikkatli ilerlenmeli, önce uzun süre
   sadece backtest + kağıt üzerinde (paper trading) test edilmeli.

## Önemli not

Bu araç bir yatırım tavsiyesi motoru değil, teknik bir karar-destek
sistemidir. Üretilen AL/SAT/TUT sinyalleri geçmiş veriye dayalı istatistiksel
çıkarımlardır ve gelecekteki performansı garanti etmez. Gerçek parayla
otomatik işlem yapmadan önce uzun süre backtest ve paper trading ile
doğrulama yapılmalı.

## Telegram Bildirimleri (v3)

Bot fırsat gördüğünde telefonuna anlık mesaj atar. Kurulum (5 dakika):

1. Telegram'da **@BotFather**'ı aç → `/newbot` yaz → isim ver → sana bir **TOKEN** verir
2. Oluşan botunla konuşma başlat (bir kere `/start` yaz — yoksa bot sana mesaj atamaz)
3. Tarayıcıda aç: `https://api.telegram.org/bot<TOKEN>/getUpdates` → JSON'da `"chat":{"id": ...}` değerini kopyala
4. Proje kökünde: `cp .env.example .env` → TOKEN ve CHAT_ID'yi yapıştır
5. Test: `python run_bot.py --once` → telefonuna mesaj gelmeli

Mesaj tipleri: 🟢/🔴 sinyal (hedef+stop planıyla), 👀 küçük fırsat notları,
💼 işlem gerçekleşti, 📈 gün sonu K/Z raporu, ⚠️ hata uyarısı.

## 7/24 Çalıştırma (v3)

`deploy/CALISTIRMA.md` dosyasında tam kılavuz var. Özet:
- **VPS (önerilen):** Oracle Free Tier (ücretsiz) veya Hetzner (~4.5€/ay) →
  `deploy/bist-bot.service` systemd dosyasıyla kur → çökse bile 10 sn'de
  kendini yeniden başlatır, sunucu resetlense otomatik kalkar
- **Kendi PC'n:** `python run_bot.py` (Linux/Mac) veya `basla.bat` (Windows,
  uyku modunu kapat)
- Bot seans dışında uyur (dakikada bir kontrol), 18:00'de gün sonu raporu
  atar, hiçbir hatada ölmez (hata → Telegram'a ⚠️ → 60 sn bekle → devam)

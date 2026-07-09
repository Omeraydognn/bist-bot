# BIST Bot — 7/24 Çalıştırma Kılavuzu

Bot bir bilgisayarda sürekli çalışmak zorunda. Kendi mantığı zaten akıllı:
seans dışında (18:00-10:00, hafta sonu) veri çekmez, sadece dakikada bir
"piyasa açıldı mı?" diye bakar — yani boşta neredeyse sıfır kaynak harcar.
Soru sadece "hangi makinede çalışacak?" sorusudur.

## Seçenekler (dürüst karşılaştırma)

| Seçenek | Aylık maliyet | Artı | Eksi |
|---|---|---|---|
| **1. Kendi bilgisayarın** | 0 TL | Bedava, hemen başlarsın | Bilgisayar kapanırsa bot durur; uyku moduna dikkat |
| **2. VPS (sanal sunucu)** ⭐ önerilen | ~80-250 TL (Hetzner/DigitalOcean/Oracle Free Tier) | 7/24 garanti, elektrik/internet kesintisinden etkilenmez | Küçük aylık ücret, ilk kurulum 30 dk |
| **3. Raspberry Pi (evde)** | Tek seferlik ~1500-2500 TL cihaz | Elektriği yok denecek kadar az, tamamen senin | İnternet/elektrik kesintisine açık |
| **4. Eski laptop/PC (evde)** | 0 TL | Elde varsa bedava | Uyku modu kapatılmalı, gürültü/elektrik |

⭐ Tavsiyem: **Oracle Cloud Free Tier** (kalıcı ücretsiz ARM sunucu veriyor)
veya **Hetzner CX11** (~4.5€/ay). İkisi de Ubuntu ile gelir, aşağıdaki
kurulum birebir çalışır.

## Kurulum (Ubuntu/Debian — VPS veya evdeki Linux makine)

```bash
# 1. Projeyi sunucuya kopyala (ör. scp veya git)
scp bist_bot_v3.zip kullanici@sunucu-ip:~/
ssh kullanici@sunucu-ip
unzip bist_bot_v3.zip -d bist_bot && cd bist_bot

# 2. Python ortamı
sudo apt update && sudo apt install -y python3-pip python3-venv
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 3. Telegram bilgilerini gir
cp .env.example .env
nano .env    # TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID doldur

# 4. Bir kere elle test et
./venv/bin/python run_bot.py --once

# 5. systemd servisi kur (7/24 otomatik çalışma + çökerse yeniden başlatma)
sudo cp deploy/bist-bot.service /etc/systemd/system/
# Servis dosyasındaki KULLANICI_ADI ve /home/KULLANICI_ADI yollarını düzenle:
sudo nano /etc/systemd/system/bist-bot.service
sudo systemctl daemon-reload
sudo systemctl enable bist-bot     # makine açılınca otomatik başlar
sudo systemctl start bist-bot

# Durum kontrolü ve loglar:
sudo systemctl status bist-bot
journalctl -u bist-bot -f          # canlı log akışı
```

## systemd ne sağlıyor?

- **Çökerse 10 sn içinde otomatik yeniden başlar** (Restart=always)
- **Sunucu yeniden başlarsa bot da otomatik kalkar** (enable)
- Loglar journalctl'de birikir, `journalctl -u bist-bot --since today` ile bak
- Bot zaten kendi içinde de hataya dayanıklı: veri çekilemezse Telegram'a
  ⚠️ uyarı atar, 60 sn bekler, devam eder — asla sessizce ölmez.

## Windows'ta çalıştırmak istersen (kendi PC'n)

1. Güç ayarlarından "uyku modu"nu kapat
2. `basla.bat` dosyasına çift tıkla (aşağıda hazır)
3. Ya da Görev Zamanlayıcı → "Oturum açılışında" → `python run_bot.py` görevi ekle

## Güvenlik notları

- .env dosyasını KİMSEYLE paylaşma (Telegram token'ın var içinde)
- VPS kullanıyorsan SSH anahtarı ile gir, şifreyle girişi kapat
- Bot şu an sadece SINYAL üretiyor ve PAPER trading yapıyor — gerçek para
  emri göndermiyor. Gerçek emir aşamasına geçmeden önce en az 4-6 hafta
  paper sonuçlarını izle.

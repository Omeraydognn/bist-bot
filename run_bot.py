"""
BIST Bot - canli calistirma girisi.

Kullanim:
    python run_bot.py            -> 7/24 dongu (systemd bunu calistirir)
    python run_bot.py --once     -> tek tur analiz (test icin)
    python run_bot.py --rapor    -> paper portfoy durumu + bugunun raporu

.env dosyasindan TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID okunur.
"""
import argparse
import os
import sys
import time
from pathlib import Path

# Sunucularda (Render vb.) saat dilimi hatasini onlemek icin Turkiye saati zorunlu kilinir
os.environ["TZ"] = "Europe/Istanbul"
if hasattr(time, "tzset"):
    time.tzset()

# .env yukle (python-dotenv varsa onu kullan, yoksa basit parser)
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except ImportError:
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(Path(__file__).parent))
from bist_bot.orchestrator import Orchestrator
from keep_alive import keep_alive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Tek tur analiz yap ve cik")
    parser.add_argument("--rapor", action="store_true", help="Paper portfoy raporu goster")
    parser.add_argument("--interval", type=int, default=300, help="Dongu araligi (sn), varsayilan 300")
    args = parser.parse_args()

    orch = Orchestrator(paper_trading=True)

    if args.rapor:
        st = orch.paper.status()
        print(f"Portfoy: {st.equity} TL | Getiri: %{st.total_return_pct} | Acik pozisyon: {st.open_position_count}")
        for p in st.positions:
            print(f"  {p['symbol']}: {p['shares']:.2f} adet @ {p['entry_price']} (acik K/Z %{p.get('acik_kz_pct', '?')})")
        rapor = orch.paper.daily_report()
        print(f"Bugun: {rapor['islem_sayisi']} islem, net K/Z {rapor['gunluk_net_kz']} TL")
        return

    if args.once:
        orch.run_once()
        return

    # Render.com veya bulut uzerinde botun 7/24 uyanik kalmasi icin mini web sunucusu
    print("Web sunucusu baslatiliyor (Render.com icin)...")
    keep_alive()

    orch.run_loop(interval_seconds=args.interval)


if __name__ == "__main__":
    main()

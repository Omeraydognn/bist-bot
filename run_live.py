"""
BIST Bot - Asenkron (WebSocket) Canli Calistirma Girisi.

Bu script, AlgoLab WebSocket baglantisi kurarak botu saniyelik verilerle
calistirir. Calistirmadan once .env dosyaniza ALGOLAB_API_KEY ve 
ALGOLAB_HASH_KEY girdiginizden emin olun.
"""
import asyncio
import os
import sys
from pathlib import Path

# .env yukle
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

async def main():
    api_key = os.getenv("ALGOLAB_API_KEY")
    if not api_key:
        print("UYARI: .env dosyasinda ALGOLAB_API_KEY bulunamadi!")
        print("Lutfen AlgoLab API anahtarinizi .env dosyasina ekleyin.")
        print("Yine de baslatmayi deniyoruz...")
        
    orch = Orchestrator(paper_trading=True)
    await orch.run_ws_loop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCanli bot durduruldu.")

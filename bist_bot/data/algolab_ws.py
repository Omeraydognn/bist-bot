"""
AlgoLab (Deniz Yatırım) WebSocket API Entegrasyonu.

Bu modül, canlı fiyat (tick) ve derinlik (order book) verilerini kesintisiz 
dinlemek için tasarlanmıştır. AlgoLab API anahtarları `.env` dosyasından okunur.
"""
import asyncio
import json
import logging
import os
from typing import Callable

# wwebsockets kutuphanesi gerektirir (pip install websockets)
try:
    import websockets
except ImportError:
    websockets = None

logger = logging.getLogger(__name__)

class AlgolabWSClient:
    def __init__(self, api_key: str | None = None, hash_key: str | None = None):
        self.api_key = api_key or os.getenv("ALGOLAB_API_KEY")
        self.hash_key = hash_key or os.getenv("ALGOLAB_HASH_KEY")
        self.ws_url = "wss://api.algolab.com.tr/api/ws" # Guncel AlgoLab WS adresi
        self.connected = False
        self._ws = None
        self._callbacks: list[Callable] = []

    def subscribe_to_ticker(self, symbol: str, callback: Callable):
        """Bir hisse icin fiyat/derinlik guncellemesi geldiginde tetiklenecek fonksiyon."""
        self._callbacks.append((symbol, callback))

    async def connect_and_listen(self):
        if not websockets:
            raise ImportError("WebSockets kutuphanesi eksik. Lutfen 'pip install websockets' calistirin.")
            
        if not self.api_key:
            logger.warning("ALGOLAB_API_KEY bulunamadi. WebSocket baslatilamiyor.")
            return

        async for websocket in websockets.connect(self.ws_url):
            self._ws = websocket
            self.connected = True
            logger.info("AlgoLab WebSocket baglantisi kuruldu.")
            try:
                # 1. Auth Payload gonderimi
                auth_payload = {
                    "Type": "Login",
                    "APIKEY": self.api_key,
                    "HASH": self.hash_key
                }
                await websocket.send(json.dumps(auth_payload))

                # 2. Mesajlari dinle
                async for message in websocket:
                    data = json.loads(message)
                    self._process_message(data)
                    
            except websockets.ConnectionClosed:
                self.connected = False
                logger.warning("Bağlantı koptu, yeniden bağlanılıyor...")
                continue
            except Exception as e:
                logger.error(f"WebSocket hatasi: {e}")
                self.connected = False
                await asyncio.sleep(5)

    def _process_message(self, data: dict):
        """AlgoLab'den gelen derinlik/fiyat paketini ayristirip callback'lere iletir."""
        # AlgoLab derinlik paketi ornegi: {'Symbol': 'ASELS', 'Depth': [...]}
        symbol = data.get("Symbol")
        if not symbol:
            return

        for sub_symbol, callback in self._callbacks:
            if sub_symbol == symbol or sub_symbol == "ALL":
                # Asenkron donguyu bloklamamak icin callback cagirimi
                asyncio.create_task(self._safe_callback(callback, data))

    async def _safe_callback(self, callback, data):
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(data)
            else:
                callback(data)
        except Exception as e:
            logger.error(f"Callback hatasi: {e}")

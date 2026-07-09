"""
Derinlik (order book / level-2) verisi.

Bu veri Turkiye'de genelde bir broker API'si (ornegin Algolab/Deniz
Yatirim API) veya lisansli terminal (Matriks) uzerinden alinabiliyor,
ucretsiz/acik bir kaynak yok. Bu yuzden Faz 5'e kadar bu modul
"NoDepthFetcher" ile pasif kalacak; skorlama motoru bu durumda
derinlik agirligini otomatik olarak 0 kabul edip diger sinyallere
gore yeniden normalize edecek (bkz decision/scorer.py).
"""
from __future__ import annotations

import abc
from typing import Any


class BaseDepthFetcher(abc.ABC):
    @abc.abstractmethod
    async def fetch_depth(self, symbol: str) -> list[dict[str, Any]] | None:
        raise NotImplementedError


class NoDepthFetcher(BaseDepthFetcher):
    async def fetch_depth(self, symbol: str):
        return None  # veri yok -> skorlayici bunu otomatik atlar


class AlgolabDepthFetcher(BaseDepthFetcher):
    """Deniz Yatirim / Algolab API asenkron WebSocket derinlik dinleyicisi."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        # En son alinan derinlik snapshot'ini (10 kademe) bellekte tutar
        self._current_depth: dict[str, list[dict]] = {}

    async def fetch_depth(self, symbol: str) -> list[dict[str, Any]] | None:
        """
        Guncel emir defterini (tahtayi) dondurur.
        Gercek mimaride arka planda calisan WebSocket listener self._current_depth'i 
        saniyede bir gunceller, bu fonksiyon sadece o guncel veriyi okur (O(1)).
        """
        # TODO: WebSocket (wwebsockets kütüphanesi) entegrasyonu buraya baglanacak.
        # Format ornegi: [{'price': 377.0, 'bid_vol': 5000, 'ask_vol': 0}, ...]
        return self._current_depth.get(symbol, None)


def get_depth_fetcher(provider: str = "none", **kwargs) -> BaseDepthFetcher:
    providers = {
        "none": NoDepthFetcher,
        "algolab": AlgolabDepthFetcher,
    }
    if provider not in providers:
        raise ValueError(f"Bilinmeyen derinlik kaynagi: {provider}")
    return providers[provider](**kwargs)
